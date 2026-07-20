"""In-process pub/sub for Hearth UI live updates (SSE)."""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Iterator


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: set[queue.Queue[dict[str, Any]]] = set()
        self._seq = 0

    def publish(self, event_type: str, **payload: Any) -> None:
        with self._lock:
            self._seq += 1
            message = {
                "type": event_type,
                "seq": self._seq,
                "ts": time.time(),
                **payload,
            }
            dead: list[queue.Queue[dict[str, Any]]] = []
            for q in self._subs:
                try:
                    q.put_nowait(message)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subs.discard(q)

    def subscribe(self, *, maxsize: int = 64) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subs.discard(q)

    def stream(self, *, heartbeat_seconds: float = 20.0) -> Iterator[bytes]:
        """Yield SSE chunks until the consumer stops reading."""
        q = self.subscribe()
        try:
            # Initial hello so clients know the stream is live.
            hello = {"type": "connected", "seq": 0, "ts": time.time()}
            yield f"event: connected\ndata: {json.dumps(hello)}\n\n".encode("utf-8")
            while True:
                try:
                    message = q.get(timeout=heartbeat_seconds)
                except queue.Empty:
                    yield b": keepalive\n\n"
                    continue
                event_type = str(message.get("type") or "message")
                yield f"event: {event_type}\ndata: {json.dumps(message)}\n\n".encode("utf-8")
        finally:
            self.unsubscribe(q)


BUS = EventBus()


def publish_ui(*topics: str, **payload: Any) -> None:
    """Publish one or more UI topics (incidents, alerts, settings)."""
    for topic in topics:
        BUS.publish(topic, **payload)
