import { useEffect, useRef, useState } from 'react'
import { api, type AgentMessage } from '../lib/api/client'

export type AgentTool = {
  call_id: string
  name: string
  phase: string
  detail?: string
}

type AgentFeedState = {
  messages: AgentMessage[]
  tools: AgentTool[]
  statusText: string
  error: string | null
  streaming: boolean
  capabilities: {
    run_stop?: boolean
    run_approval?: boolean
    run_events_sse?: boolean
  }
}

/**
 * Live agent feed: initial session load + SSE deltas (no 2s full refetch loop).
 */
export function useAgentSession(
  incidentId: string,
  hermes: { session_id?: unknown; stream_id?: unknown; status?: unknown },
): AgentFeedState {
  const sessionId = String(hermes.session_id || '')
  const streamId = String(hermes.stream_id || '')
  const hermesStatus = String(hermes.status || '')

  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [tools, setTools] = useState<AgentTool[]>([])
  const [statusText, setStatusText] = useState(
    sessionId
      ? `Status: ${hermesStatus || 'unknown'}`
      : 'No agent session yet — Investigate or send a chat message.',
  )
  const [error, setError] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [capabilities, setCapabilities] = useState<AgentFeedState['capabilities']>({})
  const assistantBuf = useRef('')

  useEffect(() => {
    if (!incidentId || !sessionId) {
      setMessages([])
      setTools([])
      setError(null)
      setStreaming(false)
      setStatusText('No agent session yet — Investigate or send a chat message.')
      return
    }

    let cancelled = false
    let source: EventSource | null = null
    let safetyTimer: number | undefined

    const applySession = async () => {
      try {
        const data = await api.getAgentSession(incidentId)
        if (cancelled) return
        const msgs = data.messages || []
        setMessages(msgs)
        setTools((data.tools as AgentTool[]) || [])
        setCapabilities(data.capabilities || {})
        setError(null)
        const running = data.status === 'running'
        setStreaming(running)
        setStatusText(
          running
            ? 'Agent is working…'
            : msgs.length
              ? 'Ready — ask a follow-up about this incident'
              : 'Waiting for agent output',
        )
        const last = msgs[msgs.length - 1]
        assistantBuf.current =
          last?.role === 'assistant' && running ? String(last.content || '') : ''
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Could not load agent feed')
        setStatusText(`Could not load agent feed: ${err instanceof Error ? err.message : 'error'}`)
      }
    }

    const upsertAssistant = (content: string) => {
      setMessages((prev) => {
        const next = [...prev]
        if (next.length && next[next.length - 1]?.role === 'assistant') {
          next[next.length - 1] = { role: 'assistant', content }
        } else {
          next.push({ role: 'assistant', content })
        }
        return next
      })
    }

    const onTool = (ev: AgentTool) => {
      setTools((prev) => {
        const idx = prev.findIndex((t) => t.call_id === ev.call_id)
        if (idx >= 0) {
          const copy = [...prev]
          copy[idx] = { ...copy[idx], ...ev }
          return copy
        }
        return [...prev, ev]
      })
    }

    void applySession()

    if (streamId && hermesStatus === 'running') {
      setStreaming(true)
      setStatusText('Streaming agent response…')
      assistantBuf.current = ''
      source = new EventSource(api.agentStreamUrl(incidentId, streamId))

      source.addEventListener('agent', (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data || '{}')
          if (Array.isArray(data.messages)) setMessages(data.messages)
          if (Array.isArray(data.tools)) setTools(data.tools)
          if (data.capabilities) setCapabilities(data.capabilities)
        } catch {
          /* ignore */
        }
      })

      source.addEventListener('assistant.delta', (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data || '{}')
          const delta = String(data.delta || '')
          if (!delta) return
          assistantBuf.current += delta
          upsertAssistant(assistantBuf.current)
          setStreaming(true)
          setStatusText('Streaming agent response…')
        } catch {
          /* ignore */
        }
      })

      source.addEventListener('tool', (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data || '{}')
          onTool({
            call_id: String(data.call_id || data.name || ''),
            name: String(data.name || 'tool'),
            phase: String(data.phase || 'started'),
            detail: data.detail ? String(data.detail) : '',
          })
        } catch {
          /* ignore */
        }
      })

      source.addEventListener('run', () => {
        setStreaming(true)
        setStatusText('Agent is working…')
      })

      source.addEventListener('agent.error', (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data || '{}')
          if (data.message) setError(String(data.message))
        } catch {
          /* ignore */
        }
      })

      const finish = () => {
        source?.close()
        setStreaming(false)
        void applySession()
      }

      source.addEventListener('end', finish)
      source.onerror = () => {
        // Browser fires onerror on disconnect; reconcile once.
        finish()
      }

      // Slow safety net while streaming (not the primary update path).
      safetyTimer = window.setInterval(() => {
        void applySession()
      }, 10000)
    } else if (sessionId) {
      safetyTimer = window.setInterval(() => {
        void applySession()
      }, 15000)
    }

    return () => {
      cancelled = true
      source?.close()
      if (safetyTimer) window.clearInterval(safetyTimer)
    }
  }, [incidentId, sessionId, streamId, hermesStatus])

  return { messages, tools, statusText, error, streaming, capabilities }
}
