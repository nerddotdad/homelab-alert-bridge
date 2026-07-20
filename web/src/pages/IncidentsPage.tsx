import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '../components/Icon'
import {
  AgentBadge,
  AlertCountBadge,
  SeverityBadge,
  StatusBadge,
} from '../components/StatusBadge'
import { api, type Incident } from '../lib/api/client'
import {
  faCircleCheck,
  faCircleExclamation,
  faCircleInfo,
  faEye,
  faFire,
  faInbox,
  faLayerGroup,
  faMagnifyingGlass,
  faRobot,
  faTriangleExclamation,
} from '../lib/icons'

const STATUS_FILTERS = [
  { value: 'active', tip: 'Active (not resolved)', icon: faInbox },
  { value: 'open', tip: 'Open', icon: faCircleExclamation },
  { value: 'acknowledged', tip: 'Acknowledged', icon: faEye },
  { value: 'resolved', tip: 'Resolved', icon: faCircleCheck },
  { value: '', tip: 'All incidents', icon: faLayerGroup },
]

const SEVERITY_FILTERS = [
  { value: 'critical', tip: 'Critical', icon: faFire },
  { value: 'warning', tip: 'Warning', icon: faTriangleExclamation },
  { value: 'info', tip: 'Info', icon: faCircleInfo },
]

function buildQuery(search: string, severity: string, agentRunning: boolean): string {
  const parts: string[] = []
  if (search.trim()) parts.push(search.trim())
  if (severity) parts.push(`severity:${severity}`)
  if (agentRunning) parts.push('agent:running')
  return parts.join(' ')
}

export function IncidentsPage() {
  const [status, setStatus] = useState('active')
  const [severity, setSeverity] = useState('')
  const [agentRunning, setAgentRunning] = useState(false)
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const qc = useQueryClient()

  const composedQ = useMemo(
    () => buildQuery(search, severity, agentRunning),
    [search, severity, agentRunning],
  )

  const query = useInfiniteQuery({
    queryKey: ['incidents', status, composedQ],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.listIncidents({ status, q: composedQ, offset: pageParam, limit: 25 }),
    getNextPageParam: (last) => (last.has_more ? last.next_offset : undefined),
  })

  const incidents = useMemo(
    () => query.data?.pages.flatMap((p) => p.incidents) ?? [],
    [query.data],
  )

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['incidents'] })
  }

  const ack = useMutation({
    mutationFn: (id: string) => api.ack(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: invalidate,
  })

  const investigate = useMutation({
    mutationFn: (id: string) => api.investigate(id, false),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: invalidate,
  })

  function toggleSeverity(value: string) {
    setSeverity((prev) => (prev === value ? '' : value))
  }

  return (
    <>
      <div className="page-toolbar">
        <div className="filter-group" role="group" aria-label="Status filter">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s.value || 'all'}
              type="button"
              className={`icon-btn ${status === s.value ? 'active' : ''}`}
              title={s.tip}
              aria-label={s.tip}
              aria-pressed={status === s.value}
              onClick={() => setStatus(s.value)}
            >
              <Icon icon={s.icon} label={s.tip} />
            </button>
          ))}
        </div>
        <div className="filter-sep" aria-hidden />
        <div className="filter-group" role="group" aria-label="Severity filter">
          {SEVERITY_FILTERS.map((s) => (
            <button
              key={s.value}
              type="button"
              className={`icon-btn ${severity === s.value ? 'active' : ''}`}
              title={s.tip}
              aria-label={s.tip}
              aria-pressed={severity === s.value}
              onClick={() => toggleSeverity(s.value)}
            >
              <Icon icon={s.icon} label={s.tip} />
            </button>
          ))}
        </div>
        <div className="filter-sep" aria-hidden />
        <button
          type="button"
          className={`icon-btn ${agentRunning ? 'active' : ''}`}
          title="Agent processing"
          aria-label="Agent processing"
          aria-pressed={agentRunning}
          onClick={() => setAgentRunning((v) => !v)}
        >
          <Icon icon={faRobot} label="Agent processing" spin={agentRunning} />
        </button>
      </div>

      <div className="panel">
        <form
          className="search-row"
          onSubmit={(e) => {
            e.preventDefault()
            setSearch(q.trim())
          }}
        >
          <input
            id="incident-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder='status:open severity>=warning title~"flux"'
            aria-label="Search incidents"
          />
          <button className="icon-btn primary" type="submit" title="Search" aria-label="Search">
            <Icon icon={faMagnifyingGlass} label="Search" />
          </button>
          {search ? (
            <button
              type="button"
              className="icon-btn"
              title="Clear search"
              aria-label="Clear search"
              onClick={() => {
                setQ('')
                setSearch('')
              }}
            >
              Clear
            </button>
          ) : null}
        </form>
      </div>

      {query.isError ? (
        <div className="panel error-banner">{(query.error as Error).message}</div>
      ) : null}
      {ack.isError ? (
        <div className="panel error-banner">{(ack.error as Error).message}</div>
      ) : null}
      {investigate.isError ? (
        <div className="panel error-banner">{(investigate.error as Error).message}</div>
      ) : null}

      <div className="grid">
        {incidents.map((inc) => (
          <IncidentRow
            key={inc.id}
            incident={inc}
            busy={busyId === inc.id}
            onAck={() => ack.mutate(inc.id)}
            onInvestigate={() => investigate.mutate(inc.id)}
          />
        ))}
      </div>

      {!query.isLoading && incidents.length === 0 ? (
        <div className="panel empty">No incidents match this view.</div>
      ) : null}

      <div className="actions" style={{ marginTop: 12 }}>
        {query.hasNextPage ? (
          <button type="button" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
            {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </button>
        ) : null}
      </div>
    </>
  )
}

function IncidentRow({
  incident,
  busy,
  onAck,
  onInvestigate,
}: {
  incident: Incident
  busy: boolean
  onAck: () => void
  onInvestigate: () => void
}) {
  const status = (incident.status || 'open').toLowerCase()
  const agentStatus = String(incident.enrichment?.hermes?.status || '')
  const canAck = status === 'open'
  const canInvestigate = agentStatus !== 'running'

  return (
    <div className="incident-row">
      <Link to={`/incidents/${incident.id}`} className="row-main">
        <div className="row-title">{incident.title || incident.id}</div>
        <div className="muted mono">{incident.id}</div>
      </Link>
      <div className="row-meta">
        <StatusBadge status={incident.status} />
        <SeverityBadge severity={incident.severity} />
        <AgentBadge status={agentStatus} />
      </div>
      <div className="muted" title={incident.updated_at || undefined}>
        {incident.updated_at || '—'}
      </div>
      <AlertCountBadge count={(incident.alerts || []).length} />
      <div className="row-actions">
        {canAck ? (
          <button
            type="button"
            className="icon-btn"
            title="Acknowledge"
            aria-label="Acknowledge"
            disabled={busy}
            onClick={onAck}
          >
            <Icon icon={faEye} label="Acknowledge" />
          </button>
        ) : null}
        {canInvestigate ? (
          <button
            type="button"
            className="icon-btn"
            title="Investigate with agent"
            aria-label="Investigate with agent"
            disabled={busy}
            onClick={onInvestigate}
          >
            <Icon icon={faRobot} label="Investigate with agent" spin={busy && agentStatus !== 'running'} />
          </button>
        ) : null}
      </div>
    </div>
  )
}
