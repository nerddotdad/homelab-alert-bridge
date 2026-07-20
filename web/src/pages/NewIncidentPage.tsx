import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api/client'

export function NewIncidentPage() {
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [severity, setSeverity] = useState('warning')
  const [tags, setTags] = useState('')
  const [note, setNote] = useState('')

  const create = useMutation({
    mutationFn: () =>
      api.createIncident({
        title,
        summary,
        severity,
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        note: note || undefined,
      }),
    onSuccess: (incident) => {
      navigate(`/incidents/${incident.id}`)
    },
  })

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>New incident</h2>
      <p className="muted">Create a manual ticket — useful for work that did not come from an alert.</p>
      <form
        className="grid"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate()
        }}
      >
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          required
          autoFocus
        />
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="What is going on?"
        />
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="critical">critical</option>
          <option value="warning">warning</option>
          <option value="info">info</option>
          <option value="unknown">unknown</option>
        </select>
        <input
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="Tags (comma-separated)"
        />
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Initial note (optional)"
        />
        {create.isError ? (
          <div className="error-banner panel">{(create.error as Error).message}</div>
        ) : null}
        <div className="actions">
          <button className="primary" type="submit" disabled={create.isPending || !title.trim()}>
            {create.isPending ? 'Creating…' : 'Create incident'}
          </button>
          <Link className="btn" to="/">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
