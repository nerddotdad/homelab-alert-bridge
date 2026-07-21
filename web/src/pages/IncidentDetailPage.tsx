import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AgentMarkdown } from '../components/AgentMarkdown'
import { AgentToolCard } from '../components/AgentToolCard'
import { Icon } from '../components/Icon'
import { AgentBadge, SeverityBadge, StatusBadge } from '../components/StatusBadge'
import { TriageTerminal } from '../components/TriageTerminal'
import { useAgentSession } from '../hooks/useAgentSession'
import { api, hermesChatUrl } from '../lib/api/client'
import {
  faArrowUpRightFromSquare,
  faArrowsRotate,
  faCircleCheck,
  faEye,
  faPaperPlane,
  faRobot,
  faStop,
} from '../lib/icons'

export function IncidentDetailPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [chatDraft, setChatDraft] = useState('')
  const feedEndRef = useRef<HTMLDivElement | null>(null)

  const query = useQuery({
    queryKey: ['incident', id],
    queryFn: () => api.getIncident(id),
    enabled: Boolean(id),
  })

  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.getSettings(),
  })

  const hermes = query.data?.enrichment?.hermes || {}
  const agent = useAgentSession(id, hermes)

  const hermesBase = useMemo(() => {
    const field = settings.data?.groups?.hermes?.find((f) => f.key === 'hermes.public_base_url')
    return field ? String(field.value || '') : ''
  }, [settings.data])

  const hermesEnabled = useMemo(() => {
    const field = settings.data?.groups?.hermes?.find((f) => f.key === 'hermes.enabled')
    if (!field) return true
    return Boolean(field.raw_value ?? field.value)
  }, [settings.data])

  const agentProvider = useMemo(() => {
    const field = settings.data?.groups?.hermes?.find((f) => f.key === 'hermes.provider')
    const fromSettings = field ? String(field.value || field.raw_value || '') : ''
    return String(hermes.provider || fromSettings || 'agent')
  }, [settings.data, hermes.provider])

  const openInHermesUrl = hermesChatUrl(hermesBase, hermes.session_id as string | undefined)
  const agentBusy = String(hermes.status || '') === 'running'
  const canStop = Boolean(agent.capabilities?.run_stop) && agentBusy

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['incident', id] })
    void qc.invalidateQueries({ queryKey: ['incidents'] })
  }

  const ack = useMutation({
    mutationFn: () => api.ack(id),
    onSuccess: invalidate,
  })
  const resolve = useMutation({
    mutationFn: () => api.resolve(id),
    onSuccess: invalidate,
  })
  const investigate = useMutation({
    mutationFn: (force: boolean) => api.investigate(id, force),
    onSuccess: invalidate,
  })
  const chat = useMutation({
    mutationFn: (message: string) => api.agentChat(id, message),
    onSuccess: () => {
      setChatDraft('')
      invalidate()
    },
  })
  const stopAgent = useMutation({
    mutationFn: () => api.agentStop(id),
    onSuccess: invalidate,
  })
  const addNote = useMutation({
    mutationFn: () => api.addNote(id, note),
    onSuccess: () => {
      setNote('')
      invalidate()
    },
  })

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [agent.messages.length, agent.messages[agent.messages.length - 1]?.content, agent.tools.length, agent.streaming])

  if (query.isLoading) {
    return <div className="panel muted">Loading incident…</div>
  }
  if (query.isError || !query.data) {
    return (
      <div className="panel error-banner">
        {(query.error as Error)?.message || 'Incident not found'}{' '}
        <Link to="/">Back to incidents</Link>
      </div>
    )
  }

  const incident = query.data
  const status = (incident.status || 'open').toLowerCase()
  const tags = incident.enrichment?.tags || []
  const notes = incident.enrichment?.notes || []
  const sessionId = String(hermes.session_id || '')

  return (
    <>
      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ margin: '0 0 8px' }}>{incident.title || incident.id}</h2>
            <div className="muted mono">
              {incident.id} · updated {incident.updated_at || '—'}
            </div>
            <div style={{ marginTop: 8 }} className="row-meta">
              <StatusBadge status={incident.status} />
              <SeverityBadge severity={incident.severity} />
              <AgentBadge status={String(hermes.status || '')} />
              {incident.enrichment?.manual ? (
                <span className="icon-badge" title="Manual incident" aria-label="Manual incident">
                  M
                </span>
              ) : null}
            </div>
          </div>
          <div className="actions">
            {status === 'open' ? (
              <button
                className="icon-btn primary"
                type="button"
                title="Acknowledge"
                aria-label="Acknowledge"
                onClick={() => ack.mutate()}
                disabled={ack.isPending}
              >
                <Icon icon={faEye} label="Acknowledge" />
              </button>
            ) : null}
            {status === 'open' || status === 'acknowledged' ? (
              <button
                className="icon-btn"
                type="button"
                title="Resolve"
                aria-label="Resolve"
                onClick={() => resolve.mutate()}
                disabled={resolve.isPending}
              >
                <Icon icon={faCircleCheck} label="Resolve" />
              </button>
            ) : null}
          </div>
        </div>
        {incident.summary ? <p>{incident.summary}</p> : null}
        {tags.length ? <p className="muted">Tags: {tags.join(', ')}</p> : null}
        {incident.merged_into_id ? (
          <p>
            Merged into <Link to={`/incidents/${incident.merged_into_id}`}>{incident.merged_into_id}</Link>
          </p>
        ) : null}
      </div>

      <div className="panel" id="agent">
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <h3 style={{ margin: 0 }}>Incident agent</h3>
          <div className="actions">
            {hermesEnabled ? (
              <>
                <button
                  className="icon-btn primary"
                  type="button"
                  title="Investigate"
                  aria-label="Investigate"
                  onClick={() => investigate.mutate(false)}
                  disabled={investigate.isPending || agentBusy}
                >
                  <Icon icon={faRobot} label="Investigate" spin={investigate.isPending} />
                </button>
                {sessionId ? (
                  <button
                    className="icon-btn"
                    type="button"
                    title="New investigation"
                    aria-label="New investigation"
                    onClick={() => investigate.mutate(true)}
                    disabled={investigate.isPending || agentBusy}
                  >
                    <Icon icon={faArrowsRotate} label="New investigation" />
                  </button>
                ) : null}
              </>
            ) : null}
            {openInHermesUrl && agentProvider !== 'agent' ? (
              <a
                className="icon-btn"
                href={openInHermesUrl}
                target="_blank"
                rel="noopener noreferrer"
                title="Open in Hermes"
                aria-label="Open in Hermes"
              >
                <Icon icon={faArrowUpRightFromSquare} label="Open in Hermes" />
              </a>
            ) : null}
          </div>
        </div>

        {!hermesEnabled ? (
          <div className="agent-status">
            AIOps is disabled. Configure it in <Link to="/settings#aiops">Settings</Link>.
          </div>
        ) : (
          <div className="agent-status">{agent.statusText}</div>
        )}

        {sessionId ? (
          <div className="muted mono" style={{ marginTop: 6 }}>
            session {sessionId}
          </div>
        ) : null}

        {investigate.isError ? (
          <div className="error-banner panel" style={{ marginTop: 12 }}>
            {(investigate.error as Error).message}
          </div>
        ) : null}

        {chat.isError ? (
          <div className="error-banner panel" style={{ marginTop: 12 }}>
            {(chat.error as Error).message}
          </div>
        ) : null}

        {agent.error && sessionId ? (
          <div className="error-banner panel" style={{ marginTop: 12 }}>
            {agent.error}
          </div>
        ) : null}

        {hermesEnabled ? (
          <>
            <div className="agent-feed" style={{ marginTop: 12 }}>
              {agent.tools.length ? (
                <div className="agent-tools">
                  {agent.tools.map((t) => (
                    <AgentToolCard
                      key={t.call_id || t.name}
                      name={t.name}
                      phase={t.phase}
                      detail={t.detail}
                    />
                  ))}
                </div>
              ) : null}
              {agent.messages.length ? (
                agent.messages.map((msg, i) => {
                  const role = msg.role || 'message'
                  const isLast = i === agent.messages.length - 1
                  const showCursor = agent.streaming && role === 'assistant' && isLast
                  return (
                    <div key={`${role}-${i}`} className={`agent-msg ${role}${showCursor ? ' streaming' : ''}`}>
                      <div className="role">{role}</div>
                      {role === 'assistant' ? (
                        <>
                          <AgentMarkdown content={msg.content || ''} />
                          {showCursor ? <span className="agent-cursor" aria-hidden /> : null}
                        </>
                      ) : (
                        <div className="agent-msg-plain">{msg.content || ''}</div>
                      )}
                    </div>
                  )
                })
              ) : (
                <div className="muted">
                  No messages yet. Run Investigate for a full triage pass, or ask a question below.
                </div>
              )}
              <div ref={feedEndRef} />
            </div>

            {agentProvider === 'agent' ? (
              <form
                className="agent-chat"
                onSubmit={(e) => {
                  e.preventDefault()
                  const text = chatDraft.trim()
                  if (!text || agentBusy || chat.isPending) return
                  chat.mutate(text)
                }}
              >
                <textarea
                  value={chatDraft}
                  onChange={(e) => setChatDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      const text = chatDraft.trim()
                      if (!text || agentBusy || chat.isPending) return
                      chat.mutate(text)
                    }
                  }}
                  placeholder={
                    agentBusy
                      ? 'Agent is working…'
                      : 'Ask about this incident (Enter to send, Shift+Enter for newline)'
                  }
                  rows={3}
                  disabled={agentBusy || chat.isPending}
                />
                <div className="actions">
                  {canStop ? (
                    <button
                      className="icon-btn"
                      type="button"
                      title="Stop"
                      aria-label="Stop"
                      disabled={stopAgent.isPending}
                      onClick={() => stopAgent.mutate()}
                    >
                      <Icon icon={faStop} label="Stop" spin={stopAgent.isPending} />
                    </button>
                  ) : null}
                  <button
                    className="icon-btn primary"
                    type="submit"
                    title="Send"
                    aria-label="Send"
                    disabled={!chatDraft.trim() || agentBusy || chat.isPending}
                  >
                    <Icon icon={faPaperPlane} label="Send" spin={chat.isPending} />
                  </button>
                </div>
              </form>
            ) : (
              <div className="muted" style={{ marginTop: 12 }}>
                Incident chat requires the agent provider. Switch AIOps to Agent in{' '}
                <Link to="/settings#aiops">Settings</Link>.
              </div>
            )}
          </>
        ) : null}
      </div>

      <TriageTerminal incidentId={id} />

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Alerts ({(incident.alerts || []).length})</h3>
        <div className="grid">
          {(incident.alerts || []).map((alert) => (
            <div key={alert.fingerprint || alert.labels?.alertname} className="panel" style={{ margin: 0 }}>
              <strong>{alert.labels?.alertname || 'alert'}</strong> · {alert.status}
              <div className="muted mono">{alert.fingerprint}</div>
              <div>{alert.annotations?.description || alert.annotations?.summary || ''}</div>
            </div>
          ))}
          {!incident.alerts?.length ? <div className="muted">No alerts attached.</div> : null}
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Add note</h3>
        <form
          className="grid"
          onSubmit={(e) => {
            e.preventDefault()
            if (note.trim()) addNote.mutate()
          }}
        >
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What did you try? What worked?"
            required
          />
          <div className="actions">
            <button type="submit" disabled={addNote.isPending}>
              Add note
            </button>
          </div>
        </form>
        <div className="grid" style={{ marginTop: 16 }}>
          {notes.map((n, i) => (
            <div key={`${n.created_at}-${i}`}>
              <div>{n.body}</div>
              <div className="muted">
                {n.actor} · {n.created_at}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Timeline</h3>
        <div className="grid">
          {(incident.events || []).map((ev, i) => (
            <div key={`${ev.created_at}-${i}`}>
              <strong>{ev.event_type}</strong> <span className="muted">{ev.created_at}</span>
              <div className="muted">{ev.actor}</div>
            </div>
          ))}
          {!incident.events?.length ? <div className="muted">No events yet.</div> : null}
        </div>
      </div>
    </>
  )
}
