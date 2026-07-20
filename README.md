# Hearth

Homelab incident desk — alerts in, tickets out, agents optional.

| | |
|--|--|
| **GitHub** | [nerddotdad/hearth](https://github.com/nerddotdad/hearth) |
| **Image** | `ghcr.io/nerddotdad/hearth` |
| **Cluster pin** | [truecharts](https://github.com/nerddotdad/truecharts) → `clusters/.../observability/hearth/` |

## Layout (ClipUp-style)

```text
hearth/
├── bridge.py + …     # Python API + static file server
├── ui.py             # Legacy HTML UI (HEARTH_LEGACY_UI=1)
└── web/              # Vite + React + TypeScript + React Query SPA
```

Local UI:

```bash
# terminal 1 — API
python3 bridge.py

# terminal 2 — Vite (proxies /api to :8000)
cd web && npm install && npm run dev
```

Production image builds `web/` and serves `web/dist` from the same process (`HEARTH_STATIC`). Set `HEARTH_LEGACY_UI=1` to force the old `ui.py` pages.

## Flow

```text
Alertmanager → alerts inbox (UI: /alerts)
                    ↓ auto-raise rules (Settings) OR manual "Raise incident"
              incident record
                    ↓ notification settings
                  ntfy
```

1. **`POST /hook`** — ingest alerts into the **inbox** (Prometheus integration)
2. **Auto-raise** — configurable rules create incidents automatically (default: `critical` only)
3. **Alerts inbox** — review, multi-select, **Raise incident**
4. **Incidents UI** — ack, merge, enrich, resolve; notifications flow **incident → ntfy**
5. **Manual incidents** — `+ New incident` without any alert
6. **Hermes** — optional AI investigation from the incident page

## Integrations (modular)

Settings → Integrations / AIOps:

| Integration | Kind | Role |
|-------------|------|------|
| **Prometheus** | ingest | Alertmanager / Grafana webhooks → `/hook` |
| **ntfy** | notify | Incident push notifications |
| **AIOps (Hermes)** | investigate | Investigations, skills, memory; optional auto-triage |

**AIOps:** enable via Settings or `HEARTH_AIOPS_ENABLED` / `HERMES_ENABLED`. Hermes env vars (`HERMES_WEBUI_*`, etc.) are applied and locked. Red status errors show until connected. When connected, manage skills + SOUL/USER/MEMORY from Hearth. **Auto-triage** (`HERMES_AUTO_TRIAGE`) starts Investigate on new incidents.

New adapters implement the protocol in `integrations/` and register in `integrations/registry.py`.

## Configuration (Grafana-style)

Every setting can come from an **environment variable** or the **Settings UI**.

| Source | Behavior |
|--------|----------|
| Env var set (non-empty) | Applied and **locked** in the UI (`env` badge) |
| Env unset / empty | Editable in Settings; persisted on the PVC (`hearth_settings.json`) |

Legacy `notification_settings.json` and `auto_raise_settings.json` are migrated on first startup.

Common env keys: `NTFY_*`, `HERMES_*`, `INCIDENTS_PUBLIC_BASE_URL`, `PROMETHEUS_ENABLED`, `NTFY_ENABLED`, `HERMES_ENABLED`, `IGNORED_ALERTNAMES`, `TRIAGE_AUTH_TOKEN`, `INCIDENTS_AUTH_TOKEN`.

## URLs

| Surface | Path |
|---------|------|
| **Incidents** | `https://incidents.${DOMAIN_0}/` |
| **Alerts inbox** | `https://incidents.${DOMAIN_0}/alerts` |
| **Settings** | `https://incidents.${DOMAIN_0}/settings` |

## Lazy lists + JQL search

Incident and alert lists load **25 rows at a time** with **infinite scroll**. Search uses a small JQL-style language.

| Surface | Examples |
|---------|----------|
| **Incidents** | `status:open severity>=warning title~"flux"` |
| **Alerts inbox** | `status:firing alertname:Homelab* namespace:flux-system` |

**List APIs:** `GET /api/list/incidents`, `GET /api/list/alerts` — params: `offset`, `limit`, `status`, `q`.  
**Settings API:** `GET/POST /api/settings`, `POST /api/settings/test/<id>`.

## Agent investigations (Hermes)

```text
Investigate → Hermes session/new + chat/start
           → Agent panel (SSE proxy + session poll)
Open in Hermes → https://hermes.<domain>/?session_id=<id>
```

Built by **Build Image** (`.github/workflows/build-image.yml`) on push to `main` or manual **workflow_dispatch**.

**`VERSION`** → GHCR tag `ghcr.io/nerddotdad/hearth:<version>`; **Renovate** updates the truecharts Deployment pin.
