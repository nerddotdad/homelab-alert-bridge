import { useInfiniteQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { SeverityBadge, StatusBadge } from '../components/StatusBadge'
import { api } from '../lib/api/client'

const STATUSES = [
  { value: '', label: 'all' },
  { value: 'open', label: 'open' },
  { value: 'acknowledged', label: 'acknowledged' },
  { value: 'resolved', label: 'resolved' },
]

export function IncidentsPage() {
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')

  const query = useInfiniteQuery({
    queryKey: ['incidents', status, search],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.listIncidents({ status, q: search, offset: pageParam, limit: 25 }),
    getNextPageParam: (last) => (last.has_more ? last.next_offset : undefined),
    refetchInterval: 8000,
  })

  const incidents = useMemo(
    () => query.data?.pages.flatMap((p) => p.incidents) ?? [],
    [query.data],
  )

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

      <div className="panel">
        <label htmlFor="incident-search">
          <strong>Search</strong>{' '}
          <span className="muted">
            JQL-style, e.g. <code>status:open severity&gt;=warning title~&quot;flux&quot;</code>
          </span>
        </label>
        <form
          className="grid"
          style={{ marginTop: 8 }}
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
          />
          <div className="actions">
            <button className="primary" type="submit">
              Search
            </button>
            {search ? (
              <button
                type="button"
                onClick={() => {
                  setQ('')
                  setSearch('')
                }}
              >
                Clear
              </button>
            ) : null}
          </div>
        </form>
      </div>

      {query.isError ? (
        <div className="panel error-banner">{(query.error as Error).message}</div>
      ) : null}

      <div className="grid">
        {incidents.map((inc) => (
          <Link key={inc.id} className="incident-row" to={`/incidents/${inc.id}`}>
            <div>
              <div className="row-title">{inc.title || inc.id}</div>
              <div className="muted mono">{inc.id}</div>
            </div>
            <StatusBadge status={inc.status} />
            <SeverityBadge severity={inc.severity} />
            <div className="muted">{inc.updated_at || '—'}</div>
            <div className="muted">{(inc.alerts || []).length} alerts</div>
          </Link>
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
        <span className="muted">
          {query.isFetching && !query.isFetchingNextPage ? 'Refreshing…' : null}
        </span>
      </div>
    </>
  )
}
