"""Hermes SecretSource plugin — fetch secrets from Hearth export API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, FrozenSet

from agent.secret_sources.base import ErrorKind, FetchResult, SecretSource


def register(ctx: Any) -> None:
    ctx.register_secret_source(HearthSecretSource())


class HearthSecretSource(SecretSource):
    """Bulk secret source backed by Hearth's /api/aiops/secrets/export."""

    name = "hearth"
    label = "Hearth"
    shape = "bulk"

    def is_enabled(self, cfg: dict) -> bool:
        return bool(isinstance(cfg, dict) and cfg.get("enabled"))

    def override_existing(self, cfg: dict) -> bool:
        return bool(isinstance(cfg, dict) and cfg.get("override_existing", True))

    def protected_env_vars(self, cfg: dict) -> FrozenSet[str]:
        token_env = str((cfg or {}).get("token_env") or "HEARTH_SECRETS_TOKEN")
        return frozenset({token_env, "HEARTH_SANDBOX_AGENT_API_KEY", "HEARTH_AGENT_API_KEY"})

    def fetch(self, cfg: dict, home_path: Path) -> FetchResult:
        result = FetchResult()
        cfg = cfg if isinstance(cfg, dict) else {}
        token_env = str(cfg.get("token_env") or "HEARTH_SECRETS_TOKEN")
        token = (
            os.environ.get(token_env) or os.environ.get("HEARTH_SANDBOX_AGENT_API_KEY") or ""
        ).strip()
        if not token:
            result.error = f"secrets.hearth.enabled is true but {token_env} is not set"
            result.error_kind = ErrorKind.NOT_CONFIGURED
            return result

        url = str(
            cfg.get("export_url")
            or os.environ.get("HEARTH_SECRETS_EXPORT_URL")
            or "http://127.0.0.1:8000/api/aiops/secrets/export"
        ).strip()
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_seconds") or 15)) as resp:
                raw = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            result.error = f"Hearth secrets export HTTP {exc.code}"
            result.error_kind = ErrorKind.AUTH_FAILED if exc.code in (401, 403) else ErrorKind.NETWORK
            return result
        except Exception as exc:
            result.error = f"Hearth secrets export failed: {exc}"
            result.error_kind = ErrorKind.NETWORK
            return result

        secrets = raw.get("secrets") if isinstance(raw, dict) else None
        if not isinstance(secrets, dict):
            secrets = raw if isinstance(raw, dict) else {}
        cleaned: dict[str, str] = {}
        protected = self.protected_env_vars(cfg)
        for key, value in secrets.items():
            k = str(key).strip()
            if not k or k in protected:
                continue
            v = "" if value is None else str(value)
            if v == "":
                continue
            cleaned[k] = v
        result.secrets = cleaned
        return result

    def config_schema(self) -> dict:
        return {
            "enabled": {"description": "Pull secrets from Hearth export API", "default": False},
            "override_existing": {
                "description": "Overwrite vars already set in .env/shell",
                "default": True,
            },
            "export_url": {
                "description": "Hearth secrets export URL (loopback)",
                "default": "http://127.0.0.1:8000/api/aiops/secrets/export",
            },
            "token_env": {
                "description": "Env var holding the Bearer token for export",
                "default": "HEARTH_SECRETS_TOKEN",
            },
            "timeout_seconds": {"description": "Fetch wall-clock budget", "default": 15},
        }
