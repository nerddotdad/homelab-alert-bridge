"""HTTP client for hearth-agent (Hermes Agent OpenAI-compatible API)."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Iterator


class AgentError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


_CAP_LOCK = threading.Lock()
_CAP_CACHE: dict[str, Any] = {"at": 0.0, "base": "", "data": {}}


class HearthAgentClient:
    """Talk to Hermes Agent core via Runs, /v1/responses, and chat completions."""

    def __init__(self, *, base_url: str, api_key: str, model: str = "hermes-agent") -> None:
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model or "hermes-agent"
        if not self.base:
            raise AgentError("Hearth Agent URL is not configured")
        if not self.api_key:
            raise AgentError("Hearth Agent API key is not configured")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def health(self) -> dict[str, Any]:
        url = f"{self.base}/health"
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {"ok": True}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return self.list_models()
            raise AgentError("hearth-agent health failed", status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc
        except json.JSONDecodeError:
            return {"ok": True}

    def list_models(self) -> dict[str, Any]:
        url = f"{self.base}/v1/models"
        req = urllib.request.Request(url, method="GET", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentError("hearth-agent /v1/models failed", status=exc.code, detail=body[:500]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

    def capabilities(self, *, ttl: float = 30.0) -> dict[str, Any]:
        """GET /v1/capabilities — never raises; missing endpoint ⇒ empty features."""
        now = time.time()
        with _CAP_LOCK:
            if (
                _CAP_CACHE.get("base") == self.base
                and now - float(_CAP_CACHE.get("at") or 0) < ttl
                and isinstance(_CAP_CACHE.get("data"), dict)
            ):
                return dict(_CAP_CACHE["data"])
        empty = {
            "ok": False,
            "features": {},
            "run_submission": False,
            "run_events_sse": False,
            "run_stop": False,
            "run_approval": False,
            "chat_completions": True,
            "responses_api": True,
        }
        url = f"{self.base}/v1/capabilities"
        req = urllib.request.Request(url, method="GET", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read().decode("utf-8") or "{}")
        except Exception:
            with _CAP_LOCK:
                _CAP_CACHE.update({"at": now, "base": self.base, "data": empty})
            return dict(empty)

        features = raw.get("features") if isinstance(raw.get("features"), dict) else {}
        # Some builds nest under features; others flatten.
        flat = {**features, **{k: v for k, v in raw.items() if k != "features"}}
        out = {
            "ok": True,
            "raw": raw,
            "features": features,
            "run_submission": bool(flat.get("run_submission")),
            "run_events_sse": bool(flat.get("run_events_sse")),
            "run_stop": bool(flat.get("run_stop")),
            "run_approval": bool(flat.get("run_approval")),
            "chat_completions": bool(flat.get("chat_completions", True)),
            "responses_api": bool(flat.get("responses_api", True)),
        }
        with _CAP_LOCK:
            _CAP_CACHE.update({"at": now, "base": self.base, "data": out})
        return dict(out)

    def chat_completions(
        self,
        messages: list[dict[str, str]],
        *,
        stream: bool = False,
        timeout: int = 600,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/chat/completions",
            data=data,
            method="POST",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentError("chat/completions failed", status=exc.code, detail=body[:800]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

    def responses(
        self,
        *,
        input_text: str,
        conversation: str,
        instructions: str | None = None,
        timeout: int = 600,
    ) -> dict[str, Any]:
        """OpenAI Responses API with named conversation (server-side history)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_text,
            "conversation": conversation,
            "store": True,
        }
        if instructions:
            payload["instructions"] = instructions
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/responses",
            data=data,
            method="POST",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (404, 405):
                return self.chat_completions(
                    [
                        *([{"role": "system", "content": instructions}] if instructions else []),
                        {"role": "user", "content": input_text},
                    ],
                    timeout=timeout,
                )
            raise AgentError("responses failed", status=exc.code, detail=body[:800]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

    def create_run(
        self,
        *,
        input_text: str,
        session_id: str | None = None,
        instructions: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"input": input_text, "model": self.model}
        if session_id:
            payload["session_id"] = session_id
        if instructions:
            payload["instructions"] = instructions
        if conversation_history:
            payload["conversation_history"] = conversation_history
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/runs",
            data=data,
            method="POST",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentError("create run failed", status=exc.code, detail=body[:800]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

    def get_run(self, run_id: str, *, timeout: int = 30) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base}/v1/runs/{_quote(run_id)}",
            method="GET",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentError("get run failed", status=exc.code, detail=body[:500]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

    def stop_run(self, run_id: str, *, timeout: int = 30) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base}/v1/runs/{_quote(run_id)}/stop",
            data=b"{}",
            method="POST",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentError("stop run failed", status=exc.code, detail=body[:500]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

    def approve_run(self, run_id: str, body: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/runs/{_quote(run_id)}/approval",
            data=data,
            method="POST",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body_t = exc.read().decode("utf-8", errors="replace")
            raise AgentError("approval failed", status=exc.code, detail=body_t[:500]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

    def iter_run_events(self, run_id: str, *, timeout: int = 600) -> Iterator[dict[str, Any]]:
        """Yield normalized events from GET /v1/runs/{id}/events."""
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(
            f"{self.base}/v1/runs/{_quote(run_id)}/events",
            method="GET",
            headers=headers,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentError("run events failed", status=exc.code, detail=body[:500]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

        event_name = ""
        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if text.startswith(":"):
                    continue
                if text.startswith("event:"):
                    event_name = text[6:].strip()
                    continue
                if not text.startswith("data:"):
                    if text == "":
                        event_name = ""
                    continue
                data_s = text[5:].strip()
                if data_s in ("[DONE]", "done"):
                    yield {"kind": "end", "status": "complete"}
                    break
                try:
                    payload = json.loads(data_s)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if event_name and "type" not in payload:
                    payload = {**payload, "type": event_name}
                for normalized in self.normalize_stream_event(payload):
                    yield normalized
                    if normalized.get("kind") in ("end", "error"):
                        return
                event_name = ""
        finally:
            resp.close()

    def iter_turn_events(
        self,
        *,
        input_text: str,
        conversation: str,
        instructions: str | None = None,
        session_id: str | None = None,
        timeout: int = 600,
    ) -> Iterator[dict[str, Any]]:
        """Preferred turn iterator: Runs → responses SSE → chat SSE → blocking."""
        caps = self.capabilities()
        if caps.get("run_submission") and caps.get("run_events_sse"):
            try:
                created = self.create_run(
                    input_text=input_text,
                    session_id=session_id,
                    instructions=instructions,
                    timeout=min(60, timeout),
                )
                run_id = str(created.get("run_id") or created.get("id") or "").strip()
                if run_id:
                    yield {"kind": "run", "status": "started", "run_id": run_id}
                    yield from self.iter_run_events(run_id, timeout=timeout)
                    return
            except AgentError as exc:
                if exc.status not in (404, 405, 400, 422, 501):
                    yield {"kind": "error", "message": str(exc)}
                    yield {"kind": "end", "status": "failed"}
                    return
                # Fall through to responses/chat.

        # Responses / chat streaming as normalized events.
        try:
            yielded = False
            for delta in self.iter_assistant_stream(
                input_text=input_text,
                conversation=conversation,
                instructions=instructions,
                timeout=timeout,
            ):
                yielded = True
                yield {"kind": "assistant.delta", "delta": delta}
            if not yielded:
                result = self.responses(
                    input_text=input_text,
                    conversation=conversation,
                    instructions=instructions,
                    timeout=timeout,
                )
                text = self.extract_assistant_text(result)
                if text:
                    yield {"kind": "assistant.delta", "delta": text}
            yield {"kind": "end", "status": "complete"}
        except AgentError as exc:
            yield {"kind": "error", "message": str(exc)}
            yield {"kind": "end", "status": "failed"}

    def iter_assistant_stream(
        self,
        *,
        input_text: str,
        conversation: str,
        instructions: str | None = None,
        timeout: int = 600,
    ) -> Iterator[str]:
        """Yield assistant text deltas while Hermes runs (tools + final answer)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_text,
            "conversation": conversation,
            "store": True,
            "stream": True,
        }
        if instructions:
            payload["instructions"] = instructions
        data = json.dumps(payload).encode("utf-8")
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(
            f"{self.base}/v1/responses",
            data=data,
            method="POST",
            headers=headers,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (404, 405, 400, 422):
                yield from self.iter_chat_stream(
                    [
                        *([{"role": "system", "content": instructions}] if instructions else []),
                        {"role": "user", "content": input_text},
                    ],
                    timeout=timeout,
                )
                return
            raise AgentError("responses stream failed", status=exc.code, detail=body[:800]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc

        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text or text.startswith(":") or not text.startswith("data:"):
                    continue
                data_s = text[5:].strip()
                if data_s in ("[DONE]", "done"):
                    break
                try:
                    event = json.loads(data_s)
                except json.JSONDecodeError:
                    continue
                for normalized in self.normalize_stream_event(event):
                    if normalized.get("kind") == "assistant.delta" and normalized.get("delta"):
                        yield str(normalized["delta"])
        finally:
            resp.close()

    @classmethod
    def normalize_stream_event(cls, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Map Hermes/OpenAI SSE payloads to Hearth normalized events."""
        if not isinstance(event, dict):
            return []
        out: list[dict[str, Any]] = []
        etype = str(event.get("type") or event.get("event") or "").strip()
        kind = str(event.get("kind") or "").strip()

        # Already normalized
        if kind in ("assistant.delta", "tool", "run", "approval", "end", "error"):
            return [event]

        # Runs / Responses text deltas
        if etype in (
            "response.output_text.delta",
            "response.text.delta",
            "assistant.delta",
            "response.output_text.delta.done",
        ):
            delta = event.get("delta")
            if isinstance(delta, dict):
                delta = delta.get("content") or delta.get("text") or ""
            if delta:
                out.append({"kind": "assistant.delta", "delta": str(delta)})

        # Chat completion chunks
        choices = event.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            part = choices[0].get("delta") or {}
            if isinstance(part, dict) and part.get("content"):
                out.append({"kind": "assistant.delta", "delta": str(part["content"])})
            fr = choices[0].get("finish_reason")
            if fr:
                out.append({"kind": "end", "status": "complete"})

        # Tool progress (chat completions custom event)
        if etype in ("hermes.tool.progress", "tool.started", "tool.completed", "tool"):
            phase = "started"
            if "completed" in etype or str(event.get("phase") or "") == "completed":
                phase = "completed"
            elif str(event.get("phase") or ""):
                phase = str(event.get("phase"))
            name = str(
                event.get("name")
                or event.get("tool")
                or event.get("tool_name")
                or (event.get("item") or {}).get("name")
                or "tool"
            )
            call_id = str(
                event.get("call_id")
                or event.get("id")
                or (event.get("item") or {}).get("call_id")
                or name
            )
            detail = event.get("detail") or event.get("message") or event.get("output")
            out.append(
                {
                    "kind": "tool",
                    "phase": phase,
                    "name": name,
                    "call_id": call_id,
                    "detail": (str(detail)[:500] if detail is not None else ""),
                }
            )

        # Responses function_call items
        if etype in ("response.output_item.added", "response.output_item.done"):
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            itype = str(item.get("type") or "")
            if itype == "function_call":
                phase = "completed" if etype.endswith(".done") else "started"
                out.append(
                    {
                        "kind": "tool",
                        "phase": phase,
                        "name": str(item.get("name") or "function"),
                        "call_id": str(item.get("call_id") or item.get("id") or ""),
                        "detail": str(item.get("arguments") or "")[:500],
                    }
                )
            elif itype == "function_call_output":
                out.append(
                    {
                        "kind": "tool",
                        "phase": "completed",
                        "name": str(item.get("name") or "function"),
                        "call_id": str(item.get("call_id") or ""),
                        "detail": str(item.get("output") or "")[:500],
                    }
                )

        if etype in ("response.completed", "run.completed", "response.done"):
            status = str(event.get("status") or "complete")
            out.append({"kind": "end", "status": status, "output": event.get("output")})

        if etype in ("response.failed", "run.failed"):
            out.append(
                {
                    "kind": "error",
                    "message": str(event.get("error") or event.get("message") or "run failed"),
                }
            )
            out.append({"kind": "end", "status": "failed"})

        if etype in ("run.cancelled", "response.cancelled"):
            out.append({"kind": "end", "status": "cancelled"})

        if etype in ("run.started", "response.created"):
            out.append({"kind": "run", "status": "started", "run_id": event.get("run_id") or event.get("id")})

        # Generic delta string
        if not out:
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                out.append({"kind": "assistant.delta", "delta": delta})
            elif isinstance(event.get("output"), str) and etype.endswith("delta"):
                out.append({"kind": "assistant.delta", "delta": str(event["output"])})

        return out

    @staticmethod
    def _stream_event_text(event: dict[str, Any]) -> str:
        for normalized in HearthAgentClient.normalize_stream_event(event):
            if normalized.get("kind") == "assistant.delta":
                return str(normalized.get("delta") or "")
        return ""

    @staticmethod
    def extract_assistant_text(result: dict[str, Any]) -> str:
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict) and msg.get("content"):
                return str(msg["content"])
        output = result.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "message":
                    content = item.get("content") or []
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                                parts.append(str(part.get("text") or ""))
                    elif isinstance(content, str):
                        parts.append(content)
            if parts:
                return "\n".join(p for p in parts if p)
        if isinstance(output, str) and output.strip():
            return output
        if result.get("output_text"):
            return str(result["output_text"])
        return json.dumps(result)[:4000]

    def iter_chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        timeout: int = 600,
    ) -> Iterator[str]:
        """Yield text deltas from a streaming chat completion."""
        payload = {"model": self.model, "messages": messages, "stream": True}
        data = json.dumps(payload).encode("utf-8")
        headers = self._headers()
        headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(
            f"{self.base}/v1/chat/completions",
            data=data,
            method="POST",
            headers=headers,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentError("stream failed", status=exc.code, detail=body[:500]) from exc
        except urllib.error.URLError as exc:
            raise AgentError(f"hearth-agent unreachable: {exc.reason}") from exc
        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text or text.startswith(":"):
                    continue
                if text.startswith("data:"):
                    data_s = text[5:].strip()
                    if data_s == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_s)
                    except json.JSONDecodeError:
                        continue
                    for normalized in self.normalize_stream_event(chunk):
                        if normalized.get("kind") == "assistant.delta" and normalized.get("delta"):
                            yield str(normalized["delta"])
        finally:
            resp.close()


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")
