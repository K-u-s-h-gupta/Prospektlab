"""In-process event bus that connects the agent loop to the gateway SSE stream."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AgentEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionBus:
    """One asyncio.Queue per session, plus a `done` sentinel."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[AgentEvent | None]] = {}

    def open(self, session_id: str) -> asyncio.Queue[AgentEvent | None]:
        q: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=1000)
        self._queues[session_id] = q
        return q

    def emit(self, session_id: str, event_type: str, **payload: Any) -> None:
        q = self._queues.get(session_id)
        if q is None:
            return
        try:
            q.put_nowait(AgentEvent(type=event_type, payload=payload))
        except asyncio.QueueFull:
            pass

    def close(self, session_id: str) -> None:
        q = self._queues.get(session_id)
        if q is not None:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    def remove(self, session_id: str) -> None:
        self._queues.pop(session_id, None)

    def get(self, session_id: str) -> asyncio.Queue[AgentEvent | None] | None:
        return self._queues.get(session_id)


BUS = SessionBus()
