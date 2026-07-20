import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Icon } from '../components/Icon'
import { api, type SettingsField } from '../lib/api/client'
import { faFloppyDisk } from '../lib/icons'

type Tab = 'general' | 'integrations' | 'aiops' | 'auto-raise' | 'display'

const TABS: { id: Tab; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'integrations', label: 'Integrations' },
  { id: 'aiops', label: 'AIOps' },
  { id: 'auto-raise', label: 'Auto-raise' },
  { id: 'display', label: 'Display' },
]

function fieldMap(fields: SettingsField[] | undefined): Record<string, SettingsField> {
  const out: Record<string, SettingsField> = {}
  for (const f of fields || []) out[f.key] = f
  return out
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field?: SettingsField
  value: string
  onChange: (v: string) => void
}) {
  if (!field) return null
  const locked = Boolean(field.locked)
  return (
    <div className={`field ${locked ? 'field-locked' : ''}`}>
      <label>
        {field.label || field.key}
        {locked ? <span className="lock-badge">env</span> : null}
      </label>
      {field.hint ? <div className="muted">{field.hint}</div> : null}
      <input
        type={field.secret && !locked ? 'password' : 'text'}
        value={locked ? String(field.value ?? '') : value}
        disabled={locked}
        placeholder={field.secret && !locked ? 'leave blank to keep' : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

function BoolToggle({
  field,
  checked,
  onChange,
}: {
  field?: SettingsField
  checked: boolean
  onChange: (v: boolean) => void
}) {
  if (!field) return null
  const locked = Boolean(field.locked)
  return (
    <label className="actions" style={{ justifyContent: 'flex-start' }}>
      <input
        type="checkbox"
        checked={checked}
        disabled={locked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <strong>
          {field.label || field.key}
          {locked ? <span className="lock-badge">env</span> : null}
        </strong>
        {field.hint ? (
          <>
            <br />
            <span className="muted">{field.hint}</span>
          </>
        ) : null}
      </span>
    </label>
  )
}

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>(() => {
    const hash = window.location.hash.replace(/^#/, '') as Tab
    return TABS.some((t) => t.id === hash) ? hash : 'general'
  })
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  const [flash, setFlash] = useState('')
  const qc = useQueryClient()

  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.getSettings(),
  })
  const aiops = useQuery({
    queryKey: ['aiops-status'],
    queryFn: () => api.aiopsStatus(),
  })

  const groups = settings.data?.groups || {}
  const core = fieldMap(groups.core)
  const prometheus = fieldMap(groups.prometheus)
  const ntfy = fieldMap(groups.ntfy)
  const hermes = fieldMap(groups.hermes)
  const autoRaise = fieldMap(groups.auto_raise)
  const display = fieldMap(groups.display)

  const val = (key: string, field?: SettingsField) => {
    if (key in draft) return draft[key]
    if (!field) return ''
    if (typeof field.raw_value === 'boolean') return field.raw_value
    if (typeof field.value === 'boolean') return field.value
    return String(field.value ?? '')
  }

  const save = useMutation({
    mutationFn: (updates: Record<string, unknown>) => api.saveSettings(updates),
    onSuccess: (res) => {
      setFlash(`Saved ${res.changed.length || 0} field(s)`)
      setDraft({})
      void qc.invalidateQueries({ queryKey: ['settings'] })
      void qc.invalidateQueries({ queryKey: ['aiops-status'] })
    },
  })

  const test = useMutation({
    mutationFn: (id: string) => api.testIntegration(id),
    onSuccess: (res) => setFlash(res.ok ? `OK: ${res.message}` : `Failed: ${res.message}`),
    onError: (err) => setFlash((err as Error).message),
  })

  const saveKeys = (keys: string[]) => {
    const updates: Record<string, unknown> = {}
    for (const key of keys) {
      if (key in draft) updates[key] = draft[key]
    }
    if (!Object.keys(updates).length) {
      setFlash('No changes to save')
      return
    }
    save.mutate(updates)
  }

  const integPills = useMemo(() => {
    return (settings.data?.integrations || []).map((row) => {
      const name = row.id === 'hermes' ? 'AIOps' : row.name || row.id
      if (!row.enabled) return `${name}: off`
      return `${name}: ${row.id}`
    })
  }, [settings.data])

  function selectTab(next: Tab) {
    setTab(next)
    history.replaceState(null, '', `#${next}`)
  }

  if (settings.isLoading) return <div className="panel muted">Loading settings…</div>
  if (settings.isError) {
    return <div className="panel error-banner">{(settings.error as Error).message}</div>
  }

  return (
    <>
      {flash ? <div className="panel flash">{flash}</div> : null}
      <div className="actions" style={{ marginBottom: 12 }}>
        {integPills.map((p) => (
          <span key={p} className="badge">
            {p}
          </span>
        ))}
      </div>
      <p className="muted">
        Fields marked <span className="lock-badge">env</span> are set by environment variables and
        cannot be edited here.
      </p>

      <div className="settings-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            className={tab === t.id ? 'active' : undefined}
            aria-selected={tab === t.id}
            onClick={() => selectTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'general' ? (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>General</h2>
          <div className="grid">
            {(
              [
                'core.incidents_public_base_url',
                'core.grafana_public_url',
                'core.default_runbook_url',
                'core.incidents_auth_token',
                'core.triage_auth_token',
              ] as const
            ).map((key) => (
              <FieldInput
                key={key}
                field={core[key]}
                value={String(val(key, core[key]))}
                onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))}
              />
            ))}
            <div className="actions">
              <button
                className="primary"
                type="button"
                onClick={() =>
                  saveKeys([
                    'core.incidents_public_base_url',
                    'core.grafana_public_url',
                    'core.default_runbook_url',
                    'core.incidents_auth_token',
                    'core.triage_auth_token',
                  ])
                }
              >
                <Icon icon={faFloppyDisk} /> Save general
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {tab === 'integrations' ? (
        <>
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>Prometheus</h2>
            <div className="grid">
              <BoolToggle
                field={prometheus['prometheus.enabled']}
                checked={Boolean(val('prometheus.enabled', prometheus['prometheus.enabled']))}
                onChange={(v) => setDraft((d) => ({ ...d, 'prometheus.enabled': v }))}
              />
              <FieldInput
                field={prometheus['prometheus.ignored_alertnames']}
                value={String(val('prometheus.ignored_alertnames', prometheus['prometheus.ignored_alertnames']))}
                onChange={(v) => setDraft((d) => ({ ...d, 'prometheus.ignored_alertnames': v }))}
              />
              <div className="actions">
                <button
                  className="primary"
                  type="button"
                  onClick={() =>
                    saveKeys(['prometheus.enabled', 'prometheus.ignored_alertnames'])
                  }
                >
                  Save Prometheus
                </button>
                <button type="button" onClick={() => test.mutate('prometheus')}>
                  Test connection
                </button>
              </div>
            </div>
          </div>
          <div className="panel">
            <h2 style={{ marginTop: 0 }}>ntfy</h2>
            <div className="grid">
              <BoolToggle
                field={ntfy['ntfy.enabled']}
                checked={Boolean(val('ntfy.enabled', ntfy['ntfy.enabled']))}
                onChange={(v) => setDraft((d) => ({ ...d, 'ntfy.enabled': v }))}
              />
              {(['ntfy.base_url', 'ntfy.topic', 'ntfy.public_url'] as const).map((key) => (
                <FieldInput
                  key={key}
                  field={ntfy[key]}
                  value={String(val(key, ntfy[key]))}
                  onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))}
                />
              ))}
              <div className="actions">
                <button
                  className="primary"
                  type="button"
                  onClick={() =>
                    saveKeys(['ntfy.enabled', 'ntfy.base_url', 'ntfy.topic', 'ntfy.public_url'])
                  }
                >
                  Save ntfy
                </button>
                <button type="button" onClick={() => test.mutate('ntfy')}>
                  Test connection
                </button>
              </div>
            </div>
          </div>
        </>
      ) : null}

      {tab === 'aiops' ? (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>AIOps</h2>
          {aiops.data?.errors?.length ? (
            <div className="panel error-banner">
              <strong>AIOps not ready</strong>
              <ul>
                {aiops.data.errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {aiops.data?.connected ? (
            <div className="panel flash">
              <strong>AIOps connected</strong>
            </div>
          ) : null}
          <div className="grid">
            <BoolToggle
              field={hermes['hermes.enabled']}
              checked={Boolean(val('hermes.enabled', hermes['hermes.enabled']))}
              onChange={(v) => setDraft((d) => ({ ...d, 'hermes.enabled': v }))}
            />
            <BoolToggle
              field={hermes['hermes.auto_triage']}
              checked={Boolean(val('hermes.auto_triage', hermes['hermes.auto_triage']))}
              onChange={(v) => setDraft((d) => ({ ...d, 'hermes.auto_triage': v }))}
            />
            {(
              [
                'hermes.webui_url',
                'hermes.webui_password',
                'hermes.workspace',
                'hermes.public_base_url',
              ] as const
            ).map((key) => (
              <FieldInput
                key={key}
                field={hermes[key]}
                value={String(val(key, hermes[key]))}
                onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))}
              />
            ))}
            <div className="actions">
              <button
                className="primary"
                type="button"
                onClick={() =>
                  saveKeys([
                    'hermes.enabled',
                    'hermes.auto_triage',
                    'hermes.webui_url',
                    'hermes.webui_password',
                    'hermes.workspace',
                    'hermes.public_base_url',
                  ])
                }
              >
                Save AIOps
              </button>
              <button type="button" onClick={() => test.mutate('hermes')}>
                Test connection
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {tab === 'auto-raise' ? (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Auto-raise rules</h2>
          <p className="muted">
            Alerts below the minimum severity stay in the inbox until you raise them manually.
            After a fresh volume, defaults reset to <code>critical</code>.
          </p>
          <div className="grid">
            <BoolToggle
              field={autoRaise['auto_raise.enabled']}
              checked={Boolean(val('auto_raise.enabled', autoRaise['auto_raise.enabled']))}
              onChange={(v) => setDraft((d) => ({ ...d, 'auto_raise.enabled': v }))}
            />
            <BoolToggle
              field={autoRaise['auto_raise.group_open']}
              checked={Boolean(val('auto_raise.group_open', autoRaise['auto_raise.group_open']))}
              onChange={(v) => setDraft((d) => ({ ...d, 'auto_raise.group_open': v }))}
            />
            {autoRaise['auto_raise.min_severity'] ? (
              <div className="field">
                <label>{autoRaise['auto_raise.min_severity'].label}</label>
                {autoRaise['auto_raise.min_severity'].hint ? (
                  <div className="muted">{autoRaise['auto_raise.min_severity'].hint}</div>
                ) : null}
                <select
                  value={String(val('auto_raise.min_severity', autoRaise['auto_raise.min_severity']))}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, 'auto_raise.min_severity': e.target.value }))
                  }
                >
                  {['critical', 'warning', 'info', 'unknown'].map((s) => (
                    <option key={s} value={s}>
                      {s} and above
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <FieldInput
              field={autoRaise['auto_raise.alertnames']}
              value={String(val('auto_raise.alertnames', autoRaise['auto_raise.alertnames']))}
              onChange={(v) => setDraft((d) => ({ ...d, 'auto_raise.alertnames': v }))}
            />
            <FieldInput
              field={autoRaise['auto_raise.label_rules']}
              value={String(val('auto_raise.label_rules', autoRaise['auto_raise.label_rules']))}
              onChange={(v) => setDraft((d) => ({ ...d, 'auto_raise.label_rules': v }))}
            />
            <div className="actions">
              <button
                className="primary"
                type="button"
                onClick={() =>
                  saveKeys([
                    'auto_raise.enabled',
                    'auto_raise.group_open',
                    'auto_raise.min_severity',
                    'auto_raise.alertnames',
                    'auto_raise.label_rules',
                  ])
                }
              >
                Save auto-raise
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {tab === 'display' ? (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Display</h2>
          <div className="grid">
            <BoolToggle
              field={display['display.show_noise']}
              checked={Boolean(val('display.show_noise', display['display.show_noise']))}
              onChange={(v) => setDraft((d) => ({ ...d, 'display.show_noise': v }))}
            />
            <div className="actions">
              <button
                className="primary"
                type="button"
                onClick={() => saveKeys(['display.show_noise'])}
              >
                Save display
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
