import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

const API_TOKEN = (import.meta.env.VITE_API_TOKEN as string | undefined) || ''

export type LiveStatus = 'connecting' | 'live' | 'reconnect' | 'off'

/**
 * Subscribe to /api/events (SSE) and invalidate React Query caches on push.
 * Replaces list polling for incidents/alerts/settings.
 */
export function useLiveUpdates(): LiveStatus {
  const qc = useQueryClient()
  const [status, setStatus] = useState<LiveStatus>('connecting')

  useEffect(() => {
    let closed = false
    let source: EventSource | null = null
    let retryTimer: number | undefined
    let attempt = 0

    const connect = () => {
      if (closed) return
      setStatus(attempt === 0 ? 'connecting' : 'reconnect')
      const url = API_TOKEN
        ? `/api/events?token=${encodeURIComponent(API_TOKEN)}`
        : '/api/events'
      source = new EventSource(url)

      source.addEventListener('connected', () => {
        attempt = 0
        setStatus('live')
      })

      const onTopic = (topic: 'incidents' | 'alerts' | 'settings') => {
        void qc.invalidateQueries({ queryKey: [topic === 'settings' ? 'settings' : topic] })
        if (topic === 'incidents') {
          void qc.invalidateQueries({ queryKey: ['incident'] })
        }
        if (topic === 'settings') {
          void qc.invalidateQueries({ queryKey: ['aiops-status'] })
        }
      }

      source.addEventListener('incidents', () => onTopic('incidents'))
      source.addEventListener('alerts', () => onTopic('alerts'))
      source.addEventListener('settings', () => onTopic('settings'))

      source.onerror = () => {
        source?.close()
        source = null
        if (closed) return
        setStatus('reconnect')
        attempt += 1
        const delay = Math.min(15_000, 1000 * 2 ** Math.min(attempt, 4))
        retryTimer = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closed = true
      if (retryTimer) window.clearTimeout(retryTimer)
      source?.close()
    }
  }, [qc])

  return status
}
