import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SeverityBadge, StatusBadge } from '../components/StatusBadge'
import { api, type Alert } from '../lib/api/client'

const STATUSES = [
  { value: '', label: 'all' },
  { value: 'firing', label: 'firing' },
  { value: 'resolved', label: 'resolved' },
]

function alertTitle(alert: Alert): string {
  return alert.labels?.alertname || alert.fingerprint || 'alert'
}

function alertSeverity(alert: Alert): string {
  return alert.labels?.severity || 'unknown'
}

export function AlertsPage() {
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const qc = useQueryClient()
  const navigate = useNavigate()

  const query = useInfiniteQuery({
    queryKey: ['alerts', status, search],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.listAlerts({ status, q: search, offset: pageParam, limit: 25 }),
    getNextPageParam: (last) => (last.has_more ? last.next_offset : undefined),
    refetchInterval: 8000,
  })

  const alerts = useMemo(
    () => query.data?.pages.flatMap((p) => p.alerts) ?? [],
    [query.data],
  )

  const raise = useMutation({
    mutationFn: () => api.raiseAlerts([...selected]),
    onSuccess: (res) => {
      setSelected(new Set())
      void qc.invalidateQueries({ queryKey: ['alerts'] })
      void qc.invalidateQueries({ queryKey: ['incidents'] })
      if (res.incident?.id) navigate(`/incidents/${res.incident.id}`)
    },
  })

  function toggle(fp: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(fp)) next.delete(fp)
      else next.add(fp)
      return next
    })
  }

  return (
    <>
      <div className="page-toolbar">
        {STATUSES.map((s) => (
          <button
            key={s.label}
            type="button"
            className={status === s.value ? 'active' : undefined}
            onClick={() => setStatus(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <p className="muted">
        Alertmanager → <strong>alerts inbox</strong> → raise incident (manual or auto-raise rules in
        Settings).
      </p>

      <div className="panel">
        <form
          className="grid"
          onSubmit={(e) => {
            e.preventDefault()
            setSearch(q.trim())
          }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder='status:firing alertname:Homelab* text~"disk"'
          />
          <div className="actions">
            <button className="primary" type="submit">
              Search
            </button>
            <button
              className="primary"
              type="button"
              disabled={!selected.size || raise.isPending}
              onClick={() => raise.mutate()}
            >
              Raise incident ({selected.size})
            </button>
          </div>
        </form>
      </div>

      {query.isError ? (
        <div className="panel error-banner">{(query.error as Error).message}</div>
      ) : null}
      {raise.isError ? (
        <div className="panel error-banner">{(raise.error as Error).message}</div>
      ) : null}

      <div className="grid">
        {alerts.map((alert) => {
          const fp = alert.fingerprint || ''
          return (
            <label key={fp || alertTitle(alert)} className="incident-row" style={{ cursor: 'pointer' }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <input
                  type="checkbox"
                  checked={selected.has(fp)}
                  disabled={!fp}
                  onChange={() => fp && toggle(fp)}
                />
                <div>
                  <div className="row-title">{alertTitle(alert)}</div>
                  <div className="muted mono">{fp || 'no fingerprint'}</div>
                </div>
              </div>
              <StatusBadge status={alert.status} />
              <SeverityBadge severity={alertSeverity(alert)} />
              <div className="muted">{alert.updated_at || alert.startsAt || '—'}</div>
              <div className="muted">{alert.labels?.namespace || ''}</div>
            </label>
          )
        })}
      </div>

      {!query.isLoading && alerts.length === 0 ? (
        <div className="panel empty">No alerts match this view.</div>
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
