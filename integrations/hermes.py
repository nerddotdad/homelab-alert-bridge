"""Hermes AIOps integration — investigate + admin (skills/memory)."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import threading
import urllib.error
import urllib.request
from typing import Any

from config import get_config
from hermes_client import HermesClient, HermesError
from integrations.base import IntegrationMeta, IntegrationStatus


class HermesIntegration:
    meta = IntegrationMeta(
        id="hermes",
        name="Hermes",
        kind="investigate",
        description="AIOps via Hermes WebUI — investigations, skills, and memory.",
        config_group="hermes",
        enabled_key="hermes.enabled",
        field_keys=[
            "hermes.enabled",
            "hermes.auto_triage",
            "hermes.webui_url",
            "hermes.webui_password",
            "hermes.workspace",
            "hermes.public_base_url",
            "hermes.webhook_url",
            "hermes.webhook_secret",
        ],
    )

    def is_enabled(self) -> bool:
        return get_config().get_bool(self.meta.enabled_key)

    def client(self) -> HermesClient:
        cfg = get_config()
        return HermesClient(
            base_url=cfg.get_str("hermes.webui_url"),
            password=cfg.get_str("hermes.webui_password"),
            workspace=cfg.get_str("hermes.workspace") or "/workspace",
        )

    def public_base_url(self) -> str:
        return get_config().get_str("hermes.public_base_url")

    def connection_errors(self) -> list[str]:
        """Human-readable blockers when AIOps is on but not ready."""
        cfg = get_config()
        if not self.is_enabled():
            return []
        errors: list[str] = []
        if not cfg.get_str("hermes.webui_url"):
            errors.append("Hermes WebUI URL is not set (HERMES_WEBUI_URL or Settings).")
        if not cfg.get_str("hermes.webui_password"):
            errors.append("Hermes WebUI password is not set (HERMES_WEBUI_PASSWORD or Settings).")
        if errors:
            return errors
        try:
            self.client()
        except HermesError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"Hermes connection failed: {exc}")
        return errors

    def is_connected(self) -> bool:
        return self.is_enabled() and not self.connection_errors()

    def validate(self) -> IntegrationStatus:
        cfg = get_config()
        if not self.is_enabled():
            return IntegrationStatus(False, "AIOps is disabled")
        errors = self.connection_errors()
        if errors:
            return IntegrationStatus(False, errors[0], detail=errors)
        return IntegrationStatus(True, f"Connected to {cfg.get_str('hermes.webui_url')}")

    def forward_webhook(self, incident: dict[str, Any]) -> tuple[int, bytes]:
        cfg = get_config()
        secret = cfg.get_str("hermes.webhook_secret")
        url = cfg.get_str("hermes.webhook_url")
        if not secret or not url:
            return 503, b'{"error":"hermes webhook not configured"}'
        body = json.dumps(incident).encode("utf-8")
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            return 502, json.dumps(
                {"error": "hermes webhook unreachable", "detail": str(exc.reason)}
            ).encode("utf-8")

    def maybe_auto_triage(
        self,
        incident_id: str,
        *,
        event: str = "created",
        investigate=None,
    ) -> None:
        """Fire-and-forget investigation when auto-triage is enabled."""
        # Reopened = same incident, new occurrence — always start a fresh chat.
        if event not in ("created", "manual", "reopened"):
            return
        if investigate is None:
            return
        cfg = get_config()
        if not cfg.auto_triage_enabled():
            return
        if self.connection_errors():
            sys.stderr.write(
                f"auto-triage skipped incident={incident_id}: AIOps not connected\n"
            )
            return

        force = event == "reopened"

        def _run() -> None:
            try:
                investigate(incident_id, force=force)
                sys.stderr.write(
                    f"auto-triage started incident={incident_id} event={event} force={force}\n"
                )
            except Exception as exc:
                sys.stderr.write(f"auto-triage failed incident={incident_id}: {exc}\n")

        threading.Thread(target=_run, name=f"auto-triage-{incident_id}", daemon=True).start()
