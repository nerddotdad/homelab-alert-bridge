import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

const API_TOKEN = (import.meta.env.VITE_API_TOKEN as string | undefined) || ''

export type LiveStatus = 'connecting' | 'live' | 'reconnect' | 'off'

/**
 * Subscribe to /api/events (SSE) and invalidate React Query caches on push.
 * Reconnects catch up by refetching — publishes during a dead stream are otherwise lost.
 */
export function useLiveUpdates(): LiveStatus {
  const qc = useQueryClient()
  const [status, setStatus] = useState<LiveStatus>('connecting')

  useEffect(() => {
    let closed = false
    let source: EventSource | null = null
    let retryTimer: number | undefined
    let pollTimer: number | undefined
    let attempt = 0

    const refreshLists = () => {
      void qc.invalidateQueries({ queryKey: ['incidents'] })
      void qc.invalidateQueries({ queryKey: ['incident'] })
      void qc.invalidateQueries({ queryKey: ['alerts'] })
    }

    const connect = () => {
      if (closed) return
      setStatus(attempt === 0 ? 'connecting' : 'reconnect')
      const url = API_TOKEN
        ? `/api/events?token=${encodeURIComponent(API_TOKEN)}`
        : '/api/events'
      source = new EventSource(url)

      source.addEventListener('connected', () => {
        const wasReconnect = attempt > 0
        attempt = 0
        setStatus('live')
        // Catch up after every (re)connect — events published while offline are gone.
        if (wasReconnect) refreshLists()
      })

      source.addEventListener('incidents', () => {
        void qc.invalidateQueries({ queryKey: ['incidents'] })
        void qc.invalidateQueries({ queryKey: ['incident'] })
      })
      source.addEventListener('alerts', () => {
        void qc.invalidateQueries({ queryKey: ['alerts'] })
      })
      source.addEventListener('settings', () => {
        void qc.invalidateQueries({ queryKey: ['settings'] })
        void qc.invalidateQueries({ queryKey: ['aiops-status'] })
      })

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

    // Safety net: soft poll while the tab is visible (covers missed SSE / proxy quirks).
    pollTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshLists()
    }, 15_000)

    const onVisible = () => {
      if (document.visibilityState === 'visible') refreshLists()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      closed = true
      if (retryTimer) window.clearTimeout(retryTimer)
      if (pollTimer) window.clearInterval(pollTimer)
      document.removeEventListener('visibilitychange', onVisible)
      source?.close()
    }
  }, [qc])

  return status
}
