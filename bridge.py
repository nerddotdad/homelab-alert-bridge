#!/usr/bin/env python3
"""Hearth — homelab incident desk: ingest alerts, organize, merge, enrich, notify."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import get_config, init_config
from db import IncidentStore
from filters import ignored_summary
from hermes_client import HermesError
from incidents import IncidentService, safe_id
from integrations import init_registry
from notifications import NotificationService
from ui import (
    PAGE_SIZE,
    alerts_list_page,
    create_incident_page,
    error_page,
    incident_detail_page,
    incident_list_page,
    render_alert_rows,
    render_incident_rows,
    settings_page,
)

INCIDENT_DIR = Path(os.environ.get("INCIDENT_DIR", "/data/incidents"))
DB_PATH = Path(os.environ.get("INCIDENT_DB", str(INCIDENT_DIR / "incidents.db")))
PENDING_ID_FILE = INCIDENT_DIR / ".pending_incident"
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8000"))
MAX_BODY = int(os.environ.get("MAX_BODY_BYTES", str(2 * 1024 * 1024)))
STATIC_DIR = Path(os.environ.get("HEARTH_STATIC", str(Path(__file__).resolve().parent / "web" / "dist")))
LEGACY_UI = os.environ.get("HEARTH_LEGACY_UI", "").strip().lower() in ("1", "true", "yes", "on")
APP_VERSION = Path(__file__).with_name("VERSION")
try:
    VERSION = APP_VERSION.read_text(encoding="utf-8").strip() or "6.0.0"
except OSError:
    VERSION = "6.0.0"


def _spa_enabled() -> bool:
    return (not LEGACY_UI) and (STATIC_DIR / "index.html").is_file()

CONFIG = init_config(INCIDENT_DIR / "hearth_settings.json", legacy_dir=INCIDENT_DIR)
REGISTRY = init_registry()
STORE = IncidentStore(DB_PATH)
SERVICE = IncidentService(STORE, INCIDENT_DIR, config=CONFIG)
NOTIFIER = NotificationService(STORE, CONFIG)


def _hermes_public_base() -> str:
    return get_config().get_str("hermes.public_base_url").rstrip("/")


def _triage_auth_token() -> str:
    return get_config().get_str("core.triage_auth_token")


def _incidents_auth_token() -> str:
    return get_config().get_str("core.incidents_auth_token")


def _list_params(params: dict[str, list[str]]) -> tuple[int, int, str, str]:
    try:
        offset = max(0, int((params.get("offset") or ["0"])[0] or 0))
    except ValueError:
        offset = 0
    try:
        limit = min(100, max(1, int((params.get("limit") or [str(PAGE_SIZE)])[0] or PAGE_SIZE)))
    except ValueError:
        limit = PAGE_SIZE
    status_filter = (params.get("status") or [""])[0]
    search_query = (params.get("q") or [""])[0]
    return offset, limit, status_filter, search_query


def _incident_id_from_query(query: str) -> str:
    params = urllib.parse.parse_qs(query)
    for key in ("incident_id", "incident", "id"):
        values = params.get(key)
        if values and values[0]:
            return safe_id(str(values[0]))
    return ""


def _investigate_actor(headers) -> str:
    token = _incidents_auth_token()
    if token and _token_matches(headers, "", token):
        return "api"
    return "ui"


def _start_investigation(handler: BaseHTTPRequestHandler, iid: str, *, force: bool = False) -> None:
    try:
        result = SERVICE.investigate(iid, force=force, actor=_investigate_actor(handler.headers))
    except ValueError as exc:
        handler._json(404, {"error": str(exc)})
        return
    except HermesError as exc:
        handler._json(502, {"error": "hermes investigation failed", "detail": str(exc), "hermes": exc.detail})
        return
    handler._redirect(f"/incidents/{iid}#agent")


def _summarize_hook_payload(payload: dict) -> str:
    alerts = payload.get("alerts") or []
    parts: list[str] = []
    for alert in alerts[:12]:
        if not isinstance(alert, dict):
            continue
        labels = alert.get("labels") or {}
        parts.append(
            f"{alert.get('status', '?')}:{labels.get('alertname', '?')}@{labels.get('namespace', '?')}"
        )
    suffix = f" (+{len(alerts) - 12} more)" if len(alerts) > 12 else ""
    return f"status={payload.get('status')} count={len(alerts)} [{', '.join(parts)}{suffix}]"


def _maybe_auto_triage(incident_id: str, event: str) -> None:
    REGISTRY.hermes().maybe_auto_triage(
        incident_id,
        event=event,
        investigate=lambda iid: SERVICE.investigate(iid, force=False, actor="auto_triage"),
    )


def _notify_and_triage(incident_id: str, event: str) -> None:
    NOTIFIER.notify(incident_id, event)
    _maybe_auto_triage(incident_id, event)


def _notify_many_and_triage(events: list[tuple[str, str]]) -> None:
    NOTIFIER.notify_many(events)
    for incident_id, event in events:
        _maybe_auto_triage(incident_id, event)


def _handle_alertmanager_hook(payload: dict) -> tuple[int, bytes]:
    sys.stderr.write(f"hook received: {_summarize_hook_payload(payload)}\n")

    def ingest(p: dict) -> list:
        events = SERVICE.ingest_alertmanager_payload(p)
        if events:
            ids = ", ".join(sorted({iid for iid, _ in events}))
            sys.stderr.write(f"incidents touched: {ids}\n")
            _notify_many_and_triage(events)
        return events

    return REGISTRY.prometheus().handle_webhook(payload, ingest)


def _token_matches(headers, query: str, token: str) -> bool:
    if not token:
        return False
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == token:
        return True
    if headers.get("X-Homelab-Triage-Token") == token:
        return True
    for part in query.split("&"):
        if part.startswith("token=") and urllib.parse.unquote(part[6:]) == token:
            return True
    return False


def _check_incidents_auth(headers, query: str = "") -> bool:
    token = _incidents_auth_token()
    if not token:
        return True
    return _token_matches(headers, query, token)


def _check_triage_auth(headers, query: str = "") -> bool:
    token = _triage_auth_token()
    if not token:
        return False
    return _token_matches(headers, query, token)


def _forward_to_hermes(incident: dict) -> tuple[int, bytes]:
    return REGISTRY.hermes().forward_webhook(incident)


def _read_form(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}


def _read_form_multi(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    return urllib.parse.parse_qs(raw)


def _alerts_redirect_url(*, status: str = "", message: str = "") -> str:
    params: list[str] = []
    if status:
        params.append(f"status={urllib.parse.quote(status)}")
    if message:
        params.append(f"msg={urllib.parse.quote(message)}")
    return "/alerts?" + "&".join(params) if params else "/alerts"


def _list_redirect_url(*, status: str = "", message: str = "") -> str:
    params: list[str] = []
    if status:
        params.append(f"status={urllib.parse.quote(status)}")
    if message:
        params.append(f"msg={urllib.parse.quote(message)}")
    return "/?" + "&".join(params) if params else "/"


class Handler(BaseHTTPRequestHandler):
    server_version = f"hearth/{VERSION}"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status: int, content: str) -> None:
        self._send_bytes(status, content.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, status: int, payload: dict) -> None:
        self._send_bytes(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_file(self, path: Path, *, status: int = 200) -> None:
        data = path.read_bytes()
        content_type, _ = mimetypes.guess_type(str(path))
        if path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".svg":
            content_type = "image/svg+xml"
        elif path.name == "index.html" or path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self._send_bytes(status, data, content_type or "application/octet-stream")

    def _try_static(self, path: str) -> bool:
        if not STATIC_DIR.is_dir():
            return False
        rel = path.lstrip("/")
        if not rel or rel.endswith("/"):
            return False
        candidate = (STATIC_DIR / rel).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return False
        if candidate.is_file():
            self._send_file(candidate)
            return True
        return False

    def _serve_spa(self) -> None:
        index = STATIC_DIR / "index.html"
        if index.is_file():
            self._send_file(index)
            return
        self._json(503, {"error": "ui not built", "hint": "run npm run build in web/"})

    def _read_json_body(self) -> tuple[dict | None, int | None]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            return None, 413
        if length == 0:
            return {}, None
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None, 400
        if not isinstance(payload, dict):
            return None, 400
        return payload, None

    def _incident_id_from_request(self, payload: dict | None, query: str = "") -> str:
        if payload:
            for key in ("incident_id", "id", "fingerprint"):
                value = payload.get(key)
                if value:
                    return safe_id(str(value))
        if not query and "?" in self.path:
            query = self.path.split("?", 1)[1]
        return _incident_id_from_query(query)

    def _require_ui_auth(self) -> bool:
        return True

    def _require_api_auth(self, query: str = "") -> bool:
        if _check_incidents_auth(self.headers, query):
            return True
        self._json(401, {"error": "unauthorized"})
        return False

    def _proxy_hermes_stream(self, stream_id: str, incident_id: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            client = REGISTRY.hermes().client()
            for chunk in client.iter_stream(stream_id):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except HermesError as exc:
            sys.stderr.write(f"agent stream error incident={incident_id}: {exc}\n")
        finally:
            SERVICE.mark_hermes_complete(incident_id)

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")

        if path in ("/health", "/healthz"):
            self._json(
                200,
                {
                    "ok": True,
                    "service": "hearth",
                    "version": VERSION,
                    "integrations": REGISTRY.status_summary(),
                },
            )
            return

        if path == "/login":
            self._redirect("/")
            return

        if path.startswith("/assets/") or path in ("/favicon.svg", "/favicon.ico"):
            if self._try_static(path):
                return

        if path == "/":
            if not self._require_ui_auth():
                return
            if _spa_enabled():
                self._serve_spa()
                return
            params = urllib.parse.parse_qs(query)
            status_filter = (params.get("status") or [""])[0]
            search_query = (params.get("q") or [""])[0]
            include_noise = bool(NOTIFIER.settings().get("show_noise"))
            flash_message = (params.get("msg") or [""])[0]
            self._html(
                200,
                incident_list_page(
                    status_filter=status_filter,
                    hermes_base=_hermes_public_base(),
                    include_noise=include_noise,
                    hidden_summary=ignored_summary(),
                    flash_message=flash_message,
                    search_query=search_query,
                    setup_hints=CONFIG.setup_hints(),
                    aiops_errors=REGISTRY.hermes().connection_errors() if CONFIG.aiops_enabled() else None,
                ),
            )
            return

        if path == "/settings":
            if not self._require_ui_auth():
                return
            if _spa_enabled():
                self._serve_spa()
                return
            params = urllib.parse.parse_qs(query)
            flash_message = (params.get("msg") or [""])[0]
            self._html(
                200,
                settings_page(
                    CONFIG,
                    REGISTRY,
                    flash_message=flash_message,
                ),
            )
            return

        if path == "/api/settings":
            if not self._require_api_auth(query):
                return
            self._json(200, {"ok": True, "groups": CONFIG.snapshot(), "integrations": REGISTRY.status_summary()})
            return

        if path == "/api/aiops/status":
            if not self._require_api_auth(query):
                return
            hermes = REGISTRY.hermes()
            errors = hermes.connection_errors()
            self._json(
                200,
                {
                    "ok": not errors,
                    "enabled": CONFIG.aiops_enabled(),
                    "auto_triage": CONFIG.auto_triage_enabled(),
                    "connected": hermes.is_connected(),
                    "errors": errors,
                    "env_keys": CONFIG.hydrate_aiops_from_env() if CONFIG.aiops_enabled() else {},
                },
            )
            return

        if path == "/api/aiops/skills":
            if not self._require_api_auth(query):
                return
            if not REGISTRY.hermes().is_connected():
                self._json(503, {"error": "AIOps not connected", "errors": REGISTRY.hermes().connection_errors()})
                return
            try:
                self._json(200, {"ok": True, "skills": REGISTRY.hermes().client().list_skills()})
            except HermesError as exc:
                self._json(502, {"error": str(exc), "detail": exc.detail})
            return

        if path == "/api/aiops/memory":
            if not self._require_api_auth(query):
                return
            if not REGISTRY.hermes().is_connected():
                self._json(503, {"error": "AIOps not connected", "errors": REGISTRY.hermes().connection_errors()})
                return
            try:
                self._json(200, {"ok": True, "memory": REGISTRY.hermes().client().get_memory()})
            except HermesError as exc:
                self._json(502, {"error": str(exc), "detail": exc.detail})
            return

        if path == "/alerts":
            if not self._require_ui_auth():
                return
            if _spa_enabled():
                self._serve_spa()
                return
            params = urllib.parse.parse_qs(query)
            status_filter = (params.get("status") or [""])[0]
            search_query = (params.get("q") or [""])[0]
            flash_message = (params.get("msg") or [""])[0]
            self._html(
                200,
                alerts_list_page(
                    status_filter=status_filter,
                    flash_message=flash_message,
                    search_query=search_query,
                ),
            )
            return

        if path == "/incidents/new":
            if not self._require_ui_auth():
                return
            if _spa_enabled():
                self._serve_spa()
                return
            self._html(200, create_incident_page())
            return

        if path.startswith("/incidents/") and path.endswith("/investigate"):
            iid = safe_id(path[len("/incidents/") : -len("/investigate")].strip("/"))
            params = urllib.parse.parse_qs(query)
            force = (params.get("force") or [""])[0] in ("1", "true", "yes")
            _start_investigation(self, iid, force=force)
            return

        if path.startswith("/incidents/"):
            if not self._require_ui_auth():
                return
            if _spa_enabled():
                self._serve_spa()
                return
            iid = safe_id(path[len("/incidents/") :].strip("/"))
            incident = STORE.get_incident(iid)
            if incident is None:
                self._html(404, error_page("Incident not found"))
                return
            params = urllib.parse.parse_qs(query)
            auto_investigate = (params.get("investigate") or [""])[0] in ("1", "true", "yes")
            self._html(
                200,
                incident_detail_page(
                    incident,
                    hermes_base=_hermes_public_base(),
                    auto_investigate=auto_investigate,
                    hermes_enabled=REGISTRY.hermes().is_enabled(),
                ),
            )
            return

        if path == "/homelab/triage":
            self._handle_triage()
            return

        if path.startswith("/homelab/api/incidents/"):
            iid = safe_id(path[len("/homelab/api/incidents/") :].split("?", 1)[0].strip("/"))
            incident = SERVICE.export_legacy(iid)
            if incident is None:
                self._json(404, {"error": "incident not found", "id": iid})
                return
            self._json(200, incident)
            return

        if path.startswith("/api/incidents/") and path.endswith("/agent/stream"):
            if not self._require_api_auth(query):
                return
            iid = safe_id(path[len("/api/incidents/") : -len("/agent/stream")].strip("/"))
            params = urllib.parse.parse_qs(query)
            stream_id = (params.get("stream_id") or [""])[0]
            if not stream_id:
                incident = STORE.get_incident(iid)
                if incident:
                    stream_id = str((incident.get("enrichment") or {}).get("hermes", {}).get("stream_id") or "")
            if not stream_id:
                self._json(400, {"error": "stream_id required"})
                return
            self._proxy_hermes_stream(stream_id, iid)
            return

        if path.startswith("/api/incidents/") and path.endswith("/agent/session"):
            if not self._require_api_auth(query):
                return
            iid = safe_id(path[len("/api/incidents/") : -len("/agent/session")].strip("/"))
            data = SERVICE.get_agent_session(iid)
            if data is None:
                self._json(404, {"error": "no agent session for incident", "id": iid})
                return
            self._json(200, data)
            return

        if path.startswith("/api/incidents/") and path.endswith("/investigate"):
            if not self._require_api_auth(query):
                return
            iid = safe_id(path[len("/api/incidents/") : -len("/investigate")].strip("/"))
            params = urllib.parse.parse_qs(query)
            force = (params.get("force") or [""])[0] in ("1", "true", "yes")
            try:
                result = SERVICE.investigate(iid, force=force, actor="api")
            except ValueError as exc:
                self._json(404, {"error": str(exc)})
                return
            except HermesError as exc:
                self._json(502, {"error": "hermes investigation failed", "detail": str(exc)})
                return
            self._json(200, result)
            return

        if path.startswith("/api/incidents/"):
            iid = safe_id(path[len("/api/incidents/") :].split("?", 1)[0].strip("/"))
            incident = STORE.get_incident(iid)
            if incident is None:
                self._json(404, {"error": "incident not found", "id": iid})
                return
            self._json(200, incident)
            return

        if path == "/api/list/incidents":
            if not self._require_api_auth(query):
                return
            params = urllib.parse.parse_qs(query)
            offset, limit, status_filter, search_query = _list_params(params)
            include_noise = bool(NOTIFIER.settings().get("show_noise"))
            try:
                incidents, has_more, next_offset = SERVICE.list_for_dashboard(
                    status=status_filter or None,
                    include_noise=include_noise,
                    query=search_query,
                    offset=offset,
                    limit=limit,
                )
            except ValueError as exc:
                self._json(
                    400,
                    {"error": str(exc), "html": "", "has_more": False, "next_offset": offset},
                )
                return
            self._json(
                200,
                {
                    "html": render_incident_rows(incidents),
                    "has_more": has_more,
                    "next_offset": next_offset,
                },
            )
            return

        if path == "/api/list/alerts":
            if not self._require_api_auth(query):
                return
            params = urllib.parse.parse_qs(query)
            offset, limit, status_filter, search_query = _list_params(params)
            try:
                alerts, has_more, next_offset = SERVICE.list_inbox(
                    status=status_filter or None,
                    query=search_query,
                    offset=offset,
                    limit=limit,
                )
            except ValueError as exc:
                self._json(
                    400,
                    {"error": str(exc), "html": "", "has_more": False, "next_offset": offset},
                )
                return
            self._json(
                200,
                {
                    "html": render_alert_rows(alerts),
                    "has_more": has_more,
                    "next_offset": next_offset,
                },
            )
            return

        if path == "/api/alerts":
            if not self._require_api_auth(query):
                return
            params = urllib.parse.parse_qs(query)
            offset, limit, status_filter, search_query = _list_params(params)
            try:
                alerts, has_more, next_offset = SERVICE.list_inbox(
                    status=status_filter or None,
                    query=search_query,
                    offset=offset,
                    limit=limit,
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(
                200,
                {
                    "alerts": alerts,
                    "has_more": has_more,
                    "next_offset": next_offset,
                },
            )
            return

        if path == "/api/incidents":
            if not self._require_api_auth(query):
                return
            params = urllib.parse.parse_qs(query)
            offset, limit, status_filter, search_query = _list_params(params)
            include_noise = bool(NOTIFIER.settings().get("show_noise"))
            try:
                incidents, has_more, next_offset = SERVICE.list_for_dashboard(
                    status=status_filter or None,
                    include_noise=include_noise,
                    query=search_query,
                    offset=offset,
                    limit=limit,
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(
                200,
                {
                    "incidents": incidents,
                    "has_more": has_more,
                    "next_offset": next_offset,
                    "hidden_alertnames": ignored_summary(),
                },
            )
            return

        if path == "/homelab/api/pending-incident":
            iid = self._take_pending_incident()
            self._json(200, {"incident_id": iid})
            return

        if self._try_static(path):
            return
        if _spa_enabled() and not path.startswith(("/api/", "/homelab/", "/hook")):
            if not self._require_ui_auth():
                return
            self._serve_spa()
            return

        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path, _, query = self.path.partition("?")

        if path == "/login":
            self._redirect("/")
            return

        if path == "/incidents/bulk":
            if not self._require_ui_auth():
                return
            form = _read_form_multi(self)
            action = (form.get("action") or [""])[0]
            incident_ids = form.get("incident_id", [])
            return_status = (form.get("return_status") or [""])[0]
            result = SERVICE.bulk_apply(action, incident_ids, actor="ui")
            if result.get("error"):
                self._redirect(
                    _list_redirect_url(
                        status=return_status,
                        message=result["error"],
                    )
                )
                return
            NOTIFIER.notify_many(result.get("notify") or [])
            if action == "merge" and result.get("target_id"):
                self._redirect(f"/incidents/{result['target_id']}")
                return
            self._redirect(
                _list_redirect_url(
                    status=return_status,
                    message=str(result.get("message") or "Done"),
                )
            )
            return

        if path == "/incidents/new":
            if not self._require_ui_auth():
                return
            form = _read_form(self)
            tags = [t.strip() for t in form.get("tags", "").split(",") if t.strip()]
            incident = SERVICE.create_manual(
                title=form.get("title", ""),
                summary=form.get("summary") or None,
                severity=form.get("severity") or "warning",
                tags=tags,
                note=form.get("note") or None,
                actor="ui",
            )
            if incident is None:
                self._html(400, create_incident_page(error="Title is required"))
                return
            _notify_and_triage(incident["id"], "manual")
            self._redirect(f"/incidents/{incident['id']}")
            return

        if path == "/settings":
            if not self._require_ui_auth():
                return
            form = _read_form(self)
            section = form.get("section") or "ntfy"
            updates = _settings_updates_from_form(form, section)
            was_aiops = CONFIG.aiops_enabled()
            CONFIG.save_ui(updates)
            section_anchors = {
                "core": "#general",
                "prometheus": "#integrations",
                "ntfy": "#integrations",
                "hermes": "#aiops",
                "aiops": "#aiops",
                "auto_raise": "#auto-raise",
                "display": "#display",
            }
            anchor = section_anchors.get(section, "")
            if section in ("hermes", "aiops") and CONFIG.aiops_enabled() and not was_aiops:
                found = CONFIG.hydrate_aiops_from_env()
                if found:
                    keys = ", ".join(sorted(found.values()))
                    self._redirect(
                        f"/settings?msg={urllib.parse.quote('AIOps enabled — applied env: ' + keys)}#aiops"
                    )
                    return
            label = "AIOps" if section in ("hermes", "aiops") else section.replace("_", " ").title()
            self._redirect(f"/settings?msg={urllib.parse.quote(label + ' settings saved')}{anchor}")
            return

        if path.startswith("/settings/test/"):
            if not self._require_ui_auth():
                return
            integration_id = path[len("/settings/test/") :].strip("/")
            try:
                status = REGISTRY.validate(integration_id)
            except KeyError:
                self._redirect("/settings?msg=Unknown+integration")
                return
            msg = ("OK:+" if status.ok else "Failed:+") + urllib.parse.quote(status.message)
            if integration_id == "hermes":
                anchor = "#aiops"
            elif integration_id in ("prometheus", "ntfy"):
                anchor = "#integrations"
            else:
                anchor = ""
            self._redirect(f"/settings?msg={msg}{anchor}")
            return

        if path == "/settings/aiops/skills/save":
            if not self._require_ui_auth():
                return
            form = _read_form(self)
            try:
                REGISTRY.hermes().client().save_skill(
                    form.get("name", ""),
                    form.get("content", ""),
                    category=form.get("category", ""),
                )
                self._redirect("/settings?msg=Skill+saved#aiops-skills")
            except HermesError as exc:
                self._redirect(f"/settings?msg={urllib.parse.quote('Skill save failed: ' + str(exc))}#aiops-skills")
            return

        if path == "/settings/aiops/skills/delete":
            if not self._require_ui_auth():
                return
            form = _read_form(self)
            try:
                REGISTRY.hermes().client().delete_skill(form.get("name", ""))
                self._redirect("/settings?msg=Skill+deleted#aiops-skills")
            except HermesError as exc:
                self._redirect(f"/settings?msg={urllib.parse.quote('Skill delete failed: ' + str(exc))}#aiops-skills")
            return

        if path == "/settings/aiops/skills/toggle":
            if not self._require_ui_auth():
                return
            form = _read_form(self)
            enabled = form.get("enabled") == "on" or form.get("enabled") == "true"
            try:
                REGISTRY.hermes().client().toggle_skill(form.get("name", ""), enabled)
                self._redirect("/settings?msg=Skill+updated#aiops-skills")
            except HermesError as exc:
                self._redirect(f"/settings?msg={urllib.parse.quote('Skill toggle failed: ' + str(exc))}#aiops-skills")
            return

        if path == "/settings/aiops/memory":
            if not self._require_ui_auth():
                return
            form = _read_form(self)
            section = form.get("memory_section") or "memory"
            try:
                REGISTRY.hermes().client().write_memory(section, form.get("content", ""))
                self._redirect(f"/settings?msg={urllib.parse.quote(section.title() + ' saved')}#aiops-memory")
            except HermesError as exc:
                self._redirect(f"/settings?msg={urllib.parse.quote('Memory save failed: ' + str(exc))}#aiops-memory")
            return

        if path == "/api/settings":
            if not self._require_api_auth():
                return
            payload, err = self._read_json_body()
            if err:
                self._json(err, {"error": "bad request"})
                return
            updates = (payload or {}).get("updates") or {}
            if not isinstance(updates, dict):
                self._json(400, {"error": "updates must be an object"})
                return
            changed = CONFIG.save_ui(updates)
            self._json(200, {"ok": True, "changed": list(changed.keys()), "groups": CONFIG.snapshot()})
            return

        if path.startswith("/api/settings/test/"):
            if not self._require_api_auth():
                return
            integration_id = path[len("/api/settings/test/") :].strip("/")
            try:
                status = REGISTRY.validate(integration_id)
            except KeyError:
                self._json(404, {"error": "unknown integration"})
                return
            self._json(
                200 if status.ok else 502,
                {"ok": status.ok, "message": status.message, "detail": status.detail},
            )
            return

        if path == "/api/alerts/raise":
            if not self._require_api_auth(query):
                return
            payload, err = self._read_json_body()
            if err:
                self._json(err, {"error": "invalid request"})
                return
            fingerprints = payload.get("fingerprints") or payload.get("fingerprint") or []
            if isinstance(fingerprints, str):
                fingerprints = [fingerprints]
            if not isinstance(fingerprints, list):
                fingerprints = []
            title = str(payload.get("title") or "").strip() or None
            incident, kind = SERVICE.raise_from_alerts(
                [str(x) for x in fingerprints],
                title=title,
                actor="api",
                group_open=False,
            )
            if incident is None:
                self._json(400, {"error": "could not raise incident"})
                return
            if kind != "already_raised":
                _notify_and_triage(incident["id"], "created" if kind == "created" else "updated")
            self._json(200, {"ok": True, "kind": kind, "incident": incident})
            return

        if path == "/alerts/raise":
            if not self._require_ui_auth():
                return
            form = _read_form_multi(self)
            fingerprints = form.get("fingerprint", [])
            title = (form.get("title") or [""])[0].strip() or None
            return_status = (form.get("return_status") or [""])[0]
            incident, kind = SERVICE.raise_from_alerts(
                fingerprints,
                title=title,
                actor="ui",
                group_open=False,
            )
            if incident is None:
                self._redirect(_alerts_redirect_url(status=return_status, message="Could not raise incident"))
                return
            if kind == "already_raised":
                self._redirect(
                    _alerts_redirect_url(
                        status=return_status,
                        message=f"Alert already on incident {incident['id']}",
                    )
                )
                return
            _notify_and_triage(incident["id"], "created" if kind == "created" else "updated")
            self._redirect(f"/incidents/{incident['id']}")
            return

        if path.startswith("/alerts/") and path.endswith("/raise"):
            if not self._require_ui_auth():
                return
            fp = safe_id(path[len("/alerts/") : -6].strip("/"))
            incident, kind = SERVICE.raise_from_alerts([fp], actor="ui", group_open=False)
            if incident is None:
                self._redirect(_alerts_redirect_url(message="Could not raise incident"))
                return
            if kind == "already_raised":
                self._redirect(f"/incidents/{incident['id']}")
                return
            _notify_and_triage(incident["id"], "created" if kind == "created" else "updated")
            self._redirect(f"/incidents/{incident['id']}")
            return

        if path.startswith("/incidents/") and path.endswith("/investigate"):
            if not self._require_ui_auth():
                return
            iid = safe_id(path[len("/incidents/") : -len("/investigate")].strip("/"))
            form = _read_form(self)
            force = form.get("force", "") in ("1", "true", "on", "yes")
            _start_investigation(self, iid, force=force)
            return

        if path.startswith("/incidents/") and path.endswith("/ack"):
            if not self._require_ui_auth():
                return
            iid = safe_id(path[len("/incidents/") : -4].strip("/"))
            incident = SERVICE.acknowledge(iid, actor="ui")
            if incident is None:
                self._html(404, error_page("Incident not found"))
                return
            NOTIFIER.notify(iid, "acknowledged")
            self._redirect(f"/incidents/{iid}")
            return

        if path.startswith("/incidents/") and path.endswith("/resolve"):
            if not self._require_ui_auth():
                return
            iid = safe_id(path[len("/incidents/") : -8].strip("/"))
            incident = SERVICE.resolve(iid, actor="ui")
            if incident is None:
                self._html(404, error_page("Incident not found"))
                return
            NOTIFIER.notify(iid, "resolved")
            self._redirect(f"/incidents/{iid}")
            return

        if path.startswith("/incidents/") and path.endswith("/reopen"):
            if not self._require_ui_auth():
                return
            iid = safe_id(path[len("/incidents/") : -7].strip("/"))
            incident = SERVICE.reopen(iid, actor="ui")
            if incident is None:
                self._html(404, error_page("Incident not found"))
                return
            NOTIFIER.notify(iid, "reopened")
            self._redirect(f"/incidents/{iid}")
            return

        if path.startswith("/incidents/") and path.endswith("/notes"):
            if not self._require_ui_auth():
                return
            iid = safe_id(path[len("/incidents/") : -6].strip("/"))
            form = _read_form(self)
            incident = SERVICE.add_note(iid, form.get("body", ""), actor="ui")
            if incident is None:
                self._html(404, error_page("Incident not found"))
                return
            self._redirect(f"/incidents/{iid}")
            return

        if path.startswith("/incidents/") and path.endswith("/enrich"):
            if not self._require_ui_auth():
                return
            iid = safe_id(path[len("/incidents/") : -7].strip("/"))
            form = _read_form(self)
            tags = [t.strip() for t in form.get("tags", "").split(",") if t.strip()]
            incident = SERVICE.enrich(
                iid,
                title=form.get("title") or None,
                summary=form.get("summary") or None,
                severity=form.get("severity") or None,
                tags=tags,
                actor="ui",
            )
            if incident is None:
                self._html(404, error_page("Incident not found"))
                return
            self._redirect(f"/incidents/{iid}")
            return

        if path.startswith("/incidents/") and path.endswith("/merge"):
            if not self._require_ui_auth():
                return
            iid = safe_id(path[len("/incidents/") : -6].strip("/"))
            form = _read_form(self)
            source_ids = [safe_id(part) for part in re.split(r"[\s,]+", form.get("source_ids", "")) if part.strip()]
            incident = SERVICE.merge(iid, source_ids, actor="ui")
            if incident is None:
                self._html(404, error_page("Incident not found"))
                return
            NOTIFIER.notify(iid, "merged")
            self._redirect(f"/incidents/{iid}")
            return

        if path == "/api/incidents/bulk":
            if not self._require_api_auth(query):
                return
            payload, err = self._read_json_body()
            if err:
                self._json(err, {"error": "invalid request"})
                return
            action = str(payload.get("action") or "")
            raw_ids = payload.get("incident_ids") or payload.get("ids") or []
            if not isinstance(raw_ids, list):
                raw_ids = []
            result = SERVICE.bulk_apply(action, [str(x) for x in raw_ids], actor="api")
            _notify_many_and_triage(result.get("notify") or [])
            status = 400 if result.get("error") else 200
            self._json(status, result)
            return

        if path == "/api/incidents":
            if not self._require_api_auth(query):
                return
            payload, err = self._read_json_body()
            if err:
                self._json(err, {"error": "invalid request"})
                return
            tags = payload.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            incident = SERVICE.create_manual(
                title=str(payload.get("title") or ""),
                summary=payload.get("summary"),
                severity=str(payload.get("severity") or "warning"),
                tags=[str(t) for t in tags] if isinstance(tags, list) else None,
                note=payload.get("note"),
                actor="api",
            )
            if incident is None:
                self._json(400, {"error": "title required"})
                return
            _notify_and_triage(incident["id"], "manual")
            self._json(201, incident)
            return

        if path == "/api/incidents/merge":
            if not self._require_api_auth(query):
                return
            payload, err = self._read_json_body()
            if err:
                self._json(err, {"error": "invalid request"})
                return
            target_id = safe_id(str(payload.get("target_id") or payload.get("into") or ""))
            source_ids = [safe_id(str(x)) for x in (payload.get("source_ids") or payload.get("sources") or [])]
            incident = SERVICE.merge(target_id, source_ids, actor="api")
            if incident is None:
                self._json(404, {"error": "incident not found", "id": target_id})
                return
            self._json(200, incident)
            return

        if path.startswith("/api/incidents/") and path.endswith("/ack"):
            if not self._require_api_auth(query):
                return
            iid = safe_id(path[len("/api/incidents/") : -4].strip("/"))
            incident = SERVICE.acknowledge(iid, actor="api")
            if incident is None:
                self._json(404, {"error": "incident not found", "id": iid})
                return
            self._json(200, incident)
            return

        if path.startswith("/api/incidents/") and path.endswith("/resolve"):
            if not self._require_api_auth(query):
                return
            iid = safe_id(path[len("/api/incidents/") : -8].strip("/"))
            incident = SERVICE.resolve(iid, actor="api")
            if incident is None:
                self._json(404, {"error": "incident not found", "id": iid})
                return
            self._json(200, incident)
            return

        if path.startswith("/api/incidents/") and path.endswith("/investigate"):
            if not self._require_api_auth(query):
                return
            iid = safe_id(path[len("/api/incidents/") : -len("/investigate")].strip("/"))
            payload, err = self._read_json_body()
            if err == 413:
                self._json(413, {"error": "payload too large"})
                return
            force = bool(payload and payload.get("force"))
            try:
                result = SERVICE.investigate(iid, force=force, actor="api")
            except ValueError as exc:
                self._json(404, {"error": str(exc)})
                return
            except HermesError as exc:
                self._json(502, {"error": "hermes investigation failed", "detail": str(exc)})
                return
            self._json(200, result)
            return

        if path.startswith("/api/incidents/") and path.endswith("/notes"):
            if not self._require_api_auth(query):
                return
            iid = safe_id(path[len("/api/incidents/") : -6].strip("/"))
            payload, err = self._read_json_body()
            if err:
                self._json(err, {"error": "invalid request"})
                return
            incident = SERVICE.add_note(iid, str(payload.get("body") or ""), actor="api")
            if incident is None:
                self._json(404, {"error": "incident not found", "id": iid})
                return
            self._json(200, incident)
            return

        if path == "/homelab/triage":
            self._handle_triage()
            return

        if path == "/homelab/api/pending-incident":
            payload, err = self._read_json_body()
            if err == 413:
                self._json(413, {"error": "payload too large"})
                return
            if err == 400:
                self._json(400, {"error": "invalid json"})
                return
            incident_id = self._incident_id_from_request(payload, query)
            if not incident_id:
                self._json(400, {"error": "incident_id required"})
                return
            if STORE.get_incident(incident_id) is None:
                self._json(404, {"error": "incident not found", "id": incident_id})
                return
            PENDING_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
            PENDING_ID_FILE.write_text(incident_id, encoding="utf-8")
            self._json(200, {"ok": True, "incident_id": incident_id})
            return

        if path not in ("/hook", "/"):
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            self._json(413, {"error": "payload too large"})
            return
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "invalid payload"})
            return
        try:
            status, resp_body = _handle_alertmanager_hook(payload)
        except Exception as exc:
            sys.stderr.write(f"hook handler error: {exc}\n")
            self._json(500, {"error": "hook handler failed", "detail": str(exc)})
            return
        self._send_bytes(status, resp_body, "application/json")

    def _handle_triage(self) -> None:
        _, _, query = self.path.partition("?")
        if not _check_triage_auth(self.headers, query):
            self._json(401, {"error": "unauthorized"})
            return
        incident_id = _incident_id_from_query(query)
        if not incident_id:
            payload, err = self._read_json_body()
            if err == 413:
                self._json(413, {"error": "payload too large"})
                return
            if err == 400:
                self._json(400, {"error": "invalid json"})
                return
            incident_id = self._incident_id_from_request(payload, query)
        if not incident_id:
            self._json(400, {"error": "incident_id required"})
            return
        incident = SERVICE.export_legacy(incident_id)
        if incident is None:
            self._json(404, {"error": "incident not found", "id": incident_id})
            return
        status, resp_body = _forward_to_hermes(incident)
        try:
            detail = json.loads(resp_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = {"raw": resp_body.decode("utf-8", errors="replace")[:500]}
        if status >= 400:
            self._json(status if status != 502 else 502, {"error": "hermes webhook failed", "detail": detail})
            return
        if self.command == "GET":
            base = _hermes_public_base()
            if not base:
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
                if host:
                    proto = self.headers.get("X-Forwarded-Proto", "https")
                    base = f"{proto}://{host.split(',')[0].strip()}"
            if base:
                self._redirect(f"{base}/?incident={incident_id}&autostart=1")
                return
        self._json(200, {"ok": True, "incident_id": incident_id, "hermes": detail})

    def _take_pending_incident(self) -> str:
        if not PENDING_ID_FILE.is_file():
            return ""
        iid = PENDING_ID_FILE.read_text(encoding="utf-8").strip()
        try:
            PENDING_ID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return iid


def _settings_updates_from_form(form: dict[str, str], section: str) -> dict:
    """Map HTML form posts into dotted ConfigStore keys for one settings section."""
    updates: dict = {}
    def set_bool(key: str, form_name: str) -> None:
        if not CONFIG.is_locked(key):
            updates[key] = form.get(form_name) == "on"

    def set_text(key: str, form_name: str, *, keep_blank_secret: bool = False) -> None:
        if form_name not in form or CONFIG.is_locked(key):
            return
        val = form.get(form_name, "")
        if keep_blank_secret and not str(val).strip():
            return
        updates[key] = val

    if section == "display":
        set_bool("display.show_noise", "show_noise")
        return updates
    if section == "auto_raise":
        set_bool("auto_raise.enabled", "raise_enabled")
        set_bool("auto_raise.group_open", "group_open")
        set_text("auto_raise.min_severity", "min_severity")
        set_text("auto_raise.alertnames", "alertnames")
        set_text("auto_raise.label_rules", "label_rules")
        return updates
    if section == "core":
        set_text("core.incidents_public_base_url", "incidents_public_base_url")
        set_text("core.grafana_public_url", "grafana_public_url")
        set_text("core.default_runbook_url", "default_runbook_url")
        set_text("core.incidents_auth_token", "incidents_auth_token", keep_blank_secret=True)
        set_text("core.triage_auth_token", "triage_auth_token", keep_blank_secret=True)
        return updates
    if section == "prometheus":
        set_bool("prometheus.enabled", "prometheus_enabled")
        set_text("prometheus.ignored_alertnames", "ignored_alertnames")
        set_text("prometheus.ignored_alert_rules", "ignored_alert_rules")
        return updates
    if section == "ntfy":
        set_bool("ntfy.enabled", "enabled")
        set_text("ntfy.topic", "topic")
        set_text("ntfy.base_url", "base_url")
        set_text("ntfy.public_url", "public_url")
        for key in ("created", "updated", "resolved", "reopened", "manual", "acknowledged", "merged"):
            set_bool(f"ntfy.events.{key}", f"event_{key}")
        return updates
    if section in ("hermes", "aiops"):
        set_bool("hermes.enabled", "hermes_enabled")
        set_bool("hermes.auto_triage", "auto_triage")
        set_text("hermes.webui_url", "webui_url")
        set_text("hermes.webui_password", "webui_password", keep_blank_secret=True)
        set_text("hermes.workspace", "workspace")
        set_text("hermes.public_base_url", "public_base_url")
        set_text("hermes.webhook_url", "webhook_url")
        set_text("hermes.webhook_secret", "webhook_secret", keep_blank_secret=True)
        return updates
    return updates


def main() -> None:
    INCIDENT_DIR.mkdir(parents=True, exist_ok=True)
    imported = SERVICE.migrate_legacy_json()
    if imported:
        print(f"migrated {imported} legacy incident file(s)", flush=True)
    fixed = SERVICE.reconcile_resolved_incidents()
    if fixed:
        print(f"reconciled {fixed} stale open incident(s) (all alerts already resolved)", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print(f"hearth {VERSION} listening on :{HTTP_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
