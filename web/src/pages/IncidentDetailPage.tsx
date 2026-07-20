import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { SeverityBadge, StatusBadge } from '../components/StatusBadge'
import { api } from '../lib/api/client'

export function IncidentDetailPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const [note, setNote] = useState('')

  const query = useQuery({
    queryKey: ['incident', id],
    queryFn: () => api.getIncident(id),
    enabled: Boolean(id),
    refetchInterval: 5000,
  })

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
    mutationFn: () => api.investigate(id),
    onSuccess: invalidate,
  })
  const addNote = useMutation({
    mutationFn: () => api.addNote(id, note),
    onSuccess: () => {
      setNote('')
      invalidate()
    },
  })

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
  const hermes = incident.enrichment?.hermes || {}

  return (
    <>
      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ margin: '0 0 8px' }}>{incident.title || incident.id}</h2>
            <div className="muted mono">
              {incident.id} · updated {incident.updated_at || '—'}
            </div>
            <div style={{ marginTop: 8 }} className="actions">
              <StatusBadge status={incident.status} />
              <SeverityBadge severity={incident.severity} />
              {incident.enrichment?.manual ? <span className="badge">manual</span> : null}
            </div>
          </div>
          <div className="actions">
            {status === 'open' ? (
              <button className="primary" type="button" onClick={() => ack.mutate()} disabled={ack.isPending}>
                Acknowledge
              </button>
            ) : null}
            {status === 'open' || status === 'acknowledged' ? (
              <button type="button" onClick={() => resolve.mutate()} disabled={resolve.isPending}>
                Resolve
              </button>
            ) : null}
            <button type="button" onClick={() => investigate.mutate()} disabled={investigate.isPending}>
              Investigate
            </button>
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

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Agent</h3>
        <p className="muted">
          Hermes status: {String(hermes.status || 'none')}
          {hermes.session_id ? (
            <>
              {' '}
              · session <span className="mono">{String(hermes.session_id)}</span>
            </>
          ) : null}
        </p>
        {investigate.isError ? (
          <div className="error-banner panel">{(investigate.error as Error).message}</div>
        ) : null}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Alerts ({(incident.alerts || []).length})</h3>
        <div className="grid">
          {(incident.alerts || []).map((alert) => (
            <div key={alert.fingerprint || alert.labels?.alertname} className="panel" style={{ margin: 0 }}>
              <strong>{alert.labels?.alertname || 'alert'}</strong> · {alert.status}
              <div className="muted mono">{alert.fingerprint}</div>
              <div>
                {alert.annotations?.description || alert.annotations?.summary || ''}
              </div>
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
