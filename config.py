"""Unified Hearth config: Grafana-style env locks + PVC-backed UI values."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _env_raw(name: str) -> str | None:
    """Return env value when set and non-empty; otherwise None (UI may own the field)."""
    if name not in os.environ:
        return None
    value = os.environ.get(name)
    if value is None:
        return None
    if str(value).strip() == "":
        return None
    return value


def _env_raw_for_field(key: str, primary_env: str | None) -> tuple[str | None, str | None]:
    """Return (raw_value, env_name) for a field, honoring aliases."""
    candidates: list[str] = []
    if primary_env:
        candidates.append(primary_env)
    candidates.extend(ENV_ALIASES.get(key) or ())
    for name in candidates:
        raw = _env_raw(name)
        if raw is not None:
            return raw, name
    return None, None


def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _coerce(field_type: str, value: Any) -> Any:
    if field_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return _parse_bool(value)
        return bool(value)
    if field_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if field_type == "json":
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []
        return [] if value is None or value == "" else value
    if field_type == "string_list":
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return []
    if value is None:
        return ""
    return str(value)


@dataclass(frozen=True)
class FieldDef:
    key: str
    env: str | None
    default: Any
    field_type: str  # str | bool | int | secret | json | string_list
    group: str
    label: str
    hint: str = ""
    secret: bool = False


# Flat field registry. Nested groups are derived from the key prefix before '.'.
FIELD_DEFS: list[FieldDef] = [
    # Core
    FieldDef(
        "core.incidents_public_base_url",
        "INCIDENTS_PUBLIC_BASE_URL",
        "",
        "str",
        "core",
        "Public base URL",
        "Used in ntfy action links and share URLs",
    ),
    FieldDef(
        "core.incidents_auth_token",
        "INCIDENTS_AUTH_TOKEN",
        "",
        "secret",
        "core",
        "API auth token",
        "Optional bearer token for /api routes",
        secret=True,
    ),
    FieldDef(
        "core.triage_auth_token",
        "TRIAGE_AUTH_TOKEN",
        "",
        "secret",
        "core",
        "Triage auth token",
        "Token for /homelab/triage and legacy Hermes API",
        secret=True,
    ),
    FieldDef(
        "core.grafana_public_url",
        "GRAFANA_PUBLIC_URL",
        "",
        "str",
        "core",
        "Grafana public URL",
        "Linked from notification messages when set",
    ),
    FieldDef(
        "core.default_runbook_url",
        "DEFAULT_RUNBOOK_URL",
        "",
        "str",
        "core",
        "Default runbook URL",
        "Fallback runbook link in messages",
    ),
    # Display
    FieldDef(
        "display.show_noise",
        None,
        False,
        "bool",
        "display",
        "Show noise on incident list",
        "Include Watchdog, InfoInhibitor, and other filtered alerts",
    ),
    # Prometheus / Alertmanager ingest
    FieldDef(
        "prometheus.enabled",
        "PROMETHEUS_ENABLED",
        True,
        "bool",
        "prometheus",
        "Enabled",
        "Accept Alertmanager webhooks at /hook",
    ),
    FieldDef(
        "prometheus.ignored_alertnames",
        "IGNORED_ALERTNAMES",
        "",
        "string_list",
        "prometheus",
        "Extra ignored alertnames",
        "Comma-separated alertnames dropped on ingest",
    ),
    FieldDef(
        "prometheus.ignored_alert_rules",
        "IGNORED_ALERT_RULES",
        [],
        "json",
        "prometheus",
        "Extra ignore rules (JSON)",
        'Label matchers e.g. [{"alertname":"Foo","namespace":"bar"}]',
    ),
    # Auto-raise (product policy under ingest)
    FieldDef("auto_raise.enabled", None, True, "bool", "auto_raise", "Auto-raise enabled"),
    FieldDef(
        "auto_raise.group_open",
        None,
        True,
        "bool",
        "auto_raise",
        "Group into open incidents",
        "Attach to an open incident with the same alertname + namespace",
    ),
    FieldDef(
        "auto_raise.min_severity",
        None,
        "critical",
        "str",
        "auto_raise",
        "Minimum severity",
        "critical | warning | info | unknown",
    ),
    FieldDef(
        "auto_raise.alertnames",
        None,
        [],
        "string_list",
        "auto_raise",
        "Alertnames only",
        "Comma-separated; empty = all names that meet severity",
    ),
    FieldDef(
        "auto_raise.label_rules",
        None,
        [],
        "json",
        "auto_raise",
        "Label rules (JSON)",
        'Matchers e.g. [{"alertname":"Foo","namespace":"bar"}]',
    ),
    # ntfy
    FieldDef(
        "ntfy.enabled",
        "NTFY_ENABLED",
        True,
        "bool",
        "ntfy",
        "Enabled",
        "Master switch for incident → ntfy posts",
    ),
    FieldDef(
        "ntfy.base_url",
        "NTFY_BASE_URL",
        "",
        "str",
        "ntfy",
        "Base URL",
        "In-cluster or public ntfy server root (no topic)",
    ),
    FieldDef("ntfy.topic", "NTFY_TOPIC", "homelab-alerts", "str", "ntfy", "Topic"),
    FieldDef(
        "ntfy.public_url",
        "NTFY_PUBLIC_URL",
        "",
        "str",
        "ntfy",
        "Public URL",
        "Used for click-through when incident public URL is unset",
    ),
    FieldDef("ntfy.events.created", None, True, "bool", "ntfy", "Notify: new incident"),
    FieldDef("ntfy.events.updated", None, True, "bool", "ntfy", "Notify: updated"),
    FieldDef("ntfy.events.resolved", None, True, "bool", "ntfy", "Notify: resolved"),
    FieldDef("ntfy.events.reopened", None, True, "bool", "ntfy", "Notify: reopened"),
    FieldDef("ntfy.events.manual", None, True, "bool", "ntfy", "Notify: manual incident"),
    FieldDef("ntfy.events.acknowledged", None, False, "bool", "ntfy", "Notify: acknowledged"),
    FieldDef("ntfy.events.merged", None, False, "bool", "ntfy", "Notify: merged"),
    # AIOps / Hermes
    FieldDef(
        "hermes.enabled",
        "HEARTH_AIOPS_ENABLED",
        True,
        "bool",
        "hermes",
        "Enable AIOps",
        "Master switch for Hermes investigation + management (alias env: HERMES_ENABLED)",
    ),
    FieldDef(
        "hermes.auto_triage",
        "HERMES_AUTO_TRIAGE",
        False,
        "bool",
        "hermes",
        "Auto-triage",
        "Automatically start a Hermes investigation on new incidents and on reopen",
    ),
    FieldDef(
        "hermes.webui_url",
        "HERMES_WEBUI_URL",
        "",
        "str",
        "hermes",
        "WebUI URL",
        "In-cluster Hermes WebUI base URL",
    ),
    FieldDef(
        "hermes.webui_password",
        "HERMES_WEBUI_PASSWORD",
        "",
        "secret",
        "hermes",
        "WebUI password",
        secret=True,
    ),
    FieldDef(
        "hermes.workspace",
        "HERMES_WEBUI_DEFAULT_WORKSPACE",
        "/workspace",
        "str",
        "hermes",
        "Default workspace",
    ),
    FieldDef(
        "hermes.public_base_url",
        "HERMES_PUBLIC_BASE_URL",
        "",
        "str",
        "hermes",
        "Public base URL",
        "Open-in-Hermes links",
    ),
    FieldDef(
        "hermes.webhook_url",
        "HERMES_WEBHOOK_URL",
        "",
        "str",
        "hermes",
        "Webhook URL (legacy)",
        "Optional legacy triage forward target",
    ),
    FieldDef(
        "hermes.webhook_secret",
        "HERMES_WEBHOOK_SECRET",
        "",
        "secret",
        "hermes",
        "Webhook secret (legacy)",
        secret=True,
    ),
]

# Env aliases: primary FieldDef.env plus these extras also lock/source the field.
ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "hermes.enabled": ("HERMES_ENABLED",),
}

FIELD_BY_KEY: dict[str, FieldDef] = {f.key: f for f in FIELD_DEFS}


def _set_nested(root: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur: dict[str, Any] = root
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _get_nested(root: dict[str, Any], dotted: str) -> Any:
    cur: Any = root
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-2:]


class ConfigStore:
    """Resolve each field from env (lock) or PVC UI JSON (editable)."""

    def __init__(self, path: Path, *, legacy_dir: Path | None = None) -> None:
        self.path = path
        self.legacy_dir = legacy_dir or path.parent
        self._ui: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._ui = raw
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self._ui = {}
        self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        notif_path = self.legacy_dir / "notification_settings.json"
        raise_path = self.legacy_dir / "auto_raise_settings.json"
        migrated = False

        if notif_path.is_file():
            try:
                raw = json.loads(notif_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw = None
            if isinstance(raw, dict):
                if "enabled" in raw:
                    _set_nested(self._ui, "ntfy.enabled", bool(raw["enabled"]))
                if raw.get("topic"):
                    _set_nested(self._ui, "ntfy.topic", str(raw["topic"]).strip())
                if "show_noise" in raw:
                    _set_nested(self._ui, "display.show_noise", bool(raw["show_noise"]))
                events = raw.get("events")
                if isinstance(events, dict):
                    for key, value in events.items():
                        _set_nested(self._ui, f"ntfy.events.{key}", bool(value))
                migrated = True

        if raise_path.is_file():
            try:
                raw = json.loads(raise_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw = None
            if isinstance(raw, dict):
                for key in ("enabled", "group_open", "min_severity", "alertnames", "label_rules"):
                    if key in raw:
                        _set_nested(self._ui, f"auto_raise.{key}", raw[key])
                migrated = True

        if migrated:
            self._persist()

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._ui, indent=2), encoding="utf-8")

    def field_source(self, key: str) -> str:
        spec = FIELD_BY_KEY.get(key)
        if not spec:
            return "default"
        env_val, _ = _env_raw_for_field(key, spec.env)
        if env_val is not None:
            return "env"
        if _get_nested(self._ui, key) is not None:
            return "ui"
        return "default"

    def get(self, key: str) -> Any:
        spec = FIELD_BY_KEY.get(key)
        if not spec:
            return None
        env_val, _ = _env_raw_for_field(key, spec.env)
        if env_val is not None:
            return _coerce(spec.field_type, env_val)
        ui_val = _get_nested(self._ui, key)
        if ui_val is not None:
            return _coerce(spec.field_type, ui_val)
        return _coerce(spec.field_type, spec.default)

    def get_str(self, key: str) -> str:
        return str(self.get(key) or "").strip()

    def get_bool(self, key: str) -> bool:
        return bool(self.get(key))

    def is_locked(self, key: str) -> bool:
        return self.field_source(key) == "env"

    def describe(self, key: str, *, mask_secrets: bool = True) -> dict[str, Any]:
        spec = FIELD_BY_KEY[key]
        value = self.get(key)
        source = self.field_source(key)
        _, env_name = _env_raw_for_field(key, spec.env)
        display = value
        if spec.secret or spec.field_type == "secret":
            raw = str(value or "")
            display = _mask_secret(raw) if mask_secrets and raw else ""
        elif spec.field_type == "json":
            display = json.dumps(value, indent=2) if not isinstance(value, str) else value
        elif spec.field_type == "string_list":
            display = ", ".join(value) if isinstance(value, list) else str(value or "")
        return {
            "key": key,
            "label": spec.label,
            "hint": spec.hint,
            "group": spec.group,
            "type": spec.field_type,
            "secret": bool(spec.secret or spec.field_type == "secret"),
            "env": env_name or spec.env,
            "source": source,
            "locked": source == "env",
            "value": display,
            "raw_value": value if not (spec.secret or spec.field_type == "secret") else None,
        }

    def hydrate_aiops_from_env(self) -> dict[str, str]:
        """Discover Hermes/AIOps env keys present at enable time (for UI messaging)."""
        found: dict[str, str] = {}
        for spec in FIELD_DEFS:
            if spec.group != "hermes":
                continue
            raw, env_name = _env_raw_for_field(spec.key, spec.env)
            if raw is not None and env_name:
                found[spec.key] = env_name
        return found

    def aiops_enabled(self) -> bool:
        return self.get_bool("hermes.enabled")

    def auto_triage_enabled(self) -> bool:
        return self.aiops_enabled() and self.get_bool("hermes.auto_triage")

    def snapshot(self, *, mask_secrets: bool = True) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for spec in FIELD_DEFS:
            groups.setdefault(spec.group, []).append(self.describe(spec.key, mask_secrets=mask_secrets))
        return groups

    def group_values(self, group: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        prefix = f"{group}."
        for spec in FIELD_DEFS:
            if spec.key.startswith(prefix) or spec.group == group:
                rel = spec.key[len(prefix) :] if spec.key.startswith(prefix) else spec.key
                _set_nested(out, rel, self.get(spec.key))
        return out

    def ntfy_settings(self) -> dict[str, Any]:
        events = {
            key: self.get_bool(f"ntfy.events.{key}")
            for key in (
                "created",
                "updated",
                "resolved",
                "reopened",
                "manual",
                "acknowledged",
                "merged",
            )
        }
        return {
            "enabled": self.get_bool("ntfy.enabled"),
            "topic": self.get_str("ntfy.topic") or "homelab-alerts",
            "base_url": self.get_str("ntfy.base_url"),
            "public_url": self.get_str("ntfy.public_url"),
            "events": events,
            "show_noise": self.get_bool("display.show_noise"),
        }

    def raise_settings(self) -> dict[str, Any]:
        return {
            "enabled": self.get_bool("auto_raise.enabled"),
            "group_open": self.get_bool("auto_raise.group_open"),
            "min_severity": self.get_str("auto_raise.min_severity") or "critical",
            "alertnames": self.get("auto_raise.alertnames") or [],
            "label_rules": self.get("auto_raise.label_rules") or [],
        }

    def save_ui(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Persist only unlocked fields. Keys are dotted field paths."""
        changed: dict[str, Any] = {}
        for key, value in updates.items():
            spec = FIELD_BY_KEY.get(key)
            if not spec:
                continue
            if self.is_locked(key):
                continue
            coerced = _coerce(spec.field_type, value)
            _set_nested(self._ui, key, coerced)
            changed[key] = coerced
        if changed:
            self._persist()
        return changed

    def setup_hints(self) -> list[str]:
        hints: list[str] = []
        if not self.get_bool("prometheus.enabled"):
            hints.append("Prometheus ingest is disabled — enable it under Settings → Integrations.")
        if self.get_bool("ntfy.enabled") and not self.get_str("ntfy.base_url"):
            hints.append("Connect ntfy under Settings → Integrations to receive push notifications.")
        if self.aiops_enabled() and not self.get_str("hermes.webui_url"):
            hints.append("AIOps is enabled but Hermes WebUI URL is missing — fix Settings → AIOps.")
        return hints


# Process-wide store set by bridge on startup.
_STORE: ConfigStore | None = None


def init_config(path: Path, *, legacy_dir: Path | None = None) -> ConfigStore:
    global _STORE
    _STORE = ConfigStore(path, legacy_dir=legacy_dir)
    return _STORE


def get_config() -> ConfigStore:
    if _STORE is None:
        raise RuntimeError("ConfigStore not initialized")
    return _STORE


def config_or_none() -> ConfigStore | None:
    return _STORE
