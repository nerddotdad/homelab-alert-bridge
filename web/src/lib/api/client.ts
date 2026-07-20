const API_TOKEN = (import.meta.env.VITE_API_TOKEN as string | undefined) || ''

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  if (API_TOKEN) {
    headers.Authorization = `Bearer ${API_TOKEN}`
  }

  const response = await fetch(path, { ...options, headers })
  const text = await response.text()
  let data: unknown = undefined
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!response.ok) {
    const message =
      typeof data === 'object' && data && 'error' in data
        ? String((data as { error: unknown }).error)
        : `Request failed (${response.status})`
    throw new ApiError(response.status, message, data)
  }

  return data as T
}

export type Incident = {
  id: string
  title?: string
  status?: string
  severity?: string
  summary?: string
  updated_at?: string
  created_at?: string
  alerts?: Alert[]
  events?: IncidentEvent[]
  enrichment?: {
    tags?: string[]
    notes?: Note[]
    manual?: boolean
    hermes?: Record<string, unknown>
  }
  merged_into_id?: string
}

export type Alert = {
  fingerprint?: string
  status?: string
  labels?: Record<string, string>
  annotations?: Record<string, string>
  startsAt?: string
  endsAt?: string
  updated_at?: string
}

export type Note = {
  body?: string
  actor?: string
  created_at?: string
}

export type IncidentEvent = {
  event_type?: string
  created_at?: string
  actor?: string
  detail?: Record<string, unknown>
}

export type ListIncidentsResponse = {
  incidents: Incident[]
  has_more: boolean
  next_offset: number
  hidden_alertnames?: string
}

export type ListAlertsResponse = {
  alerts: Alert[]
  has_more: boolean
  next_offset: number
}

export type SettingsField = {
  key: string
  value: unknown
  raw_value?: unknown
  locked?: boolean
  label?: string
  hint?: string
  env?: string
  secret?: boolean
}

export type SettingsSnapshot = {
  ok: boolean
  groups: Record<string, SettingsField[]>
  integrations: Array<{
    id: string
    name?: string
    enabled?: boolean
    kind?: string
  }>
}

export type AiopsStatus = {
  ok: boolean
  enabled: boolean
  auto_triage: boolean
  connected: boolean
  errors: string[]
  env_keys?: Record<string, string>
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => request<{ ok: boolean; version: string; service: string }>('/health'),

  listIncidents: (opts: { status?: string; q?: string; offset?: number; limit?: number } = {}) =>
    request<ListIncidentsResponse>(`/api/incidents${qs(opts)}`),

  listAlerts: (opts: { status?: string; q?: string; offset?: number; limit?: number } = {}) =>
    request<ListAlertsResponse>(`/api/alerts${qs(opts)}`),

  raiseAlerts: (fingerprints: string[], title?: string) =>
    request<{ ok: boolean; kind: string; incident: Incident }>('/api/alerts/raise', {
      method: 'POST',
      body: JSON.stringify({ fingerprints, title }),
    }),

  getIncident: (id: string) => request<Incident>(`/api/incidents/${encodeURIComponent(id)}`),

  createIncident: (body: {
    title: string
    summary?: string
    severity?: string
    tags?: string[]
    note?: string
  }) =>
    request<Incident>('/api/incidents', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  ack: (id: string) =>
    request<{ ok: boolean }>(`/api/incidents/${encodeURIComponent(id)}/ack`, { method: 'POST', body: '{}' }),

  resolve: (id: string) =>
    request<{ ok: boolean }>(`/api/incidents/${encodeURIComponent(id)}/resolve`, {
      method: 'POST',
      body: '{}',
    }),

  investigate: (id: string, force = false) =>
    request<Record<string, unknown>>(
      `/api/incidents/${encodeURIComponent(id)}/investigate`,
      { method: 'POST', body: JSON.stringify({ force }) },
    ),

  addNote: (id: string, body: string) =>
    request<{ ok: boolean }>(`/api/incidents/${encodeURIComponent(id)}/notes`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    }),

  bulkIncidents: (action: string, incident_ids: string[]) =>
    request<{ ok: boolean }>('/api/incidents/bulk', {
      method: 'POST',
      body: JSON.stringify({ action, incident_ids }),
    }),

  getSettings: () => request<SettingsSnapshot>('/api/settings'),

  saveSettings: (updates: Record<string, unknown>) =>
    request<{ ok: boolean; changed: string[]; groups: Record<string, SettingsField[]> }>(
      '/api/settings',
      { method: 'POST', body: JSON.stringify({ updates }) },
    ),

  testIntegration: (id: string) =>
    request<{ ok: boolean; message: string }>(`/api/settings/test/${encodeURIComponent(id)}`, {
      method: 'POST',
      body: '{}',
    }),

  aiopsStatus: () => request<AiopsStatus>('/api/aiops/status'),

  aiopsSkills: () =>
    request<{ ok: boolean; skills: Array<Record<string, unknown>> }>('/api/aiops/skills'),

  aiopsMemory: () =>
    request<{ ok: boolean; memory: Record<string, string> }>('/api/aiops/memory'),
}
