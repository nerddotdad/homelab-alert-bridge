"""In-memory fan-out for live agent turn events (SSE subscribers)."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any, Iterator


class _StreamState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.buffer: deque[dict[str, Any]] = deque(maxlen=800)
        self.subscribers: list[queue.Queue[dict[str, Any] | None]] = []
        self.done = False
        self.updated_at = time.time()


class AgentRunBus:
    """Publish normalized agent events; SSE handlers subscribe by stream_id."""

    def __init__(self) -> None:
        self._streams: dict[str, _StreamState] = {}
        self._lock = threading.Lock()

    def _get(self, stream_id: str) -> _StreamState:
        with self._lock:
            state = self._streams.get(stream_id)
            if state is None:
                state = _StreamState()
                self._streams[stream_id] = state
            return state

    def begin(self, stream_id: str) -> None:
        state = self._get(stream_id)
        with state.lock:
            state.done = False
            state.buffer.clear()
            state.updated_at = time.time()

    def publish(self, stream_id: str, event: dict[str, Any]) -> None:
        if not stream_id or not isinstance(event, dict):
            return
        state = self._get(stream_id)
        with state.lock:
            state.buffer.append(event)
            state.updated_at = time.time()
            dead: list[queue.Queue[dict[str, Any] | None]] = []
            for q in state.subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                try:
                    state.subscribers.remove(q)
                except ValueError:
                    pass
            kind = str(event.get("kind") or "")
            if kind in ("end", "error"):
                state.done = True
                for q in list(state.subscribers):
                    try:
                        q.put_nowait(None)
                    except queue.Full:
                        pass

    def subscribe(self, stream_id: str, *, timeout: float = 600.0) -> Iterator[dict[str, Any]]:
        """Yield buffered events then live ones until end/error or timeout."""
        state = self._get(stream_id)
        q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1000)
        with state.lock:
            replay = list(state.buffer)
            already_done = state.done
            if not already_done:
                state.subscribers.append(q)
        for event in replay:
            yield event
        if already_done:
            return
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                remaining = max(0.05, deadline - time.time())
                try:
                    item = q.get(timeout=min(1.0, remaining))
                except queue.Empty:
                    with state.lock:
                        if state.done:
                            break
                    continue
                if item is None:
                    break
                yield item
                if str(item.get("kind") or "") in ("end", "error"):
                    break
        finally:
            with state.lock:
                try:
                    state.subscribers.remove(q)
                except ValueError:
                    pass

    def is_active(self, stream_id: str) -> bool:
        with self._lock:
            state = self._streams.get(stream_id)
        if state is None:
            return False
        with state.lock:
            return not state.done

    def discard(self, stream_id: str) -> None:
        with self._lock:
            self._streams.pop(stream_id, None)


BUS = AgentRunBus()
