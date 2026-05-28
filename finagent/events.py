"""In-process event bus that connects the agent loop to the gateway SSE stream."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finagent.paths import finagent_data_path


@dataclass
class AgentEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seq: int = 0

    def to_record(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "AgentEvent":
        return cls(
            type=record.get("type", ""),
            payload=dict(record.get("payload") or {}),
            timestamp=record.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            seq=int(record.get("seq", 0)),
        )


class SessionBus:
    """One asyncio.Queue per live SSE session, plus replayable event history."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[AgentEvent | None]] = {}
        self._history: dict[str, list[AgentEvent]] = {}
        self._closed: set[str] = set()
        self._ignore_closed_file: set[str] = set()
        self._max_history = 5000

    def forget_memory(self, session_id: str) -> None:
        """Drop live/in-memory state while preserving durable files."""
        self._queues.pop(session_id, None)
        self._history.pop(session_id, None)
        self._closed.discard(session_id)
        self._ignore_closed_file.discard(session_id)

    def _session_dir(self, session_id: str) -> Path:
        path = finagent_data_path("sessions", session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _events_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "events.jsonl"

    def _closed_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "closed"

    def _append_event_file(self, session_id: str, event: AgentEvent) -> None:
        try:
            with self._events_path(session_id).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_record(), default=str, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _load_history_file(self, session_id: str) -> list[AgentEvent]:
        path = self._events_path(session_id)
        if not path.is_file():
            return []
        out: list[AgentEvent] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                out.append(AgentEvent.from_record(json.loads(line)))
        except Exception:
            return out
        return out

    def open(self, session_id: str, *, reset: bool = False) -> asyncio.Queue[AgentEvent | None]:
        """Open a live event queue.

        ``reset=True`` starts a fresh run for an existing conversation session.
        Chat memory and memo storage live elsewhere; the SSE event log is
        per-run UI state, so replaying old memo events would render the prior
        answer under a new follow-up question.
        """

        q: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=1000)
        self._queues[session_id] = q
        self._session_dir(session_id)
        if reset:
            self._history[session_id] = []
            events_path = self._events_path(session_id)
            try:
                events_path.unlink(missing_ok=True)
            except OSError:
                try:
                    events_path.write_text("", encoding="utf-8")
                except OSError:
                    pass
            closed_path = self._closed_path(session_id)
            try:
                closed_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._ignore_closed_file.add(session_id)
        else:
            self._history.setdefault(session_id, self._load_history_file(session_id))
        self._closed.discard(session_id)
        return q

    def emit(self, session_id: str, event_type: str, **payload: Any) -> None:
        hist = self._history.setdefault(session_id, [])
        event = AgentEvent(type=event_type, payload=payload, seq=len(hist))
        hist.append(event)
        self._append_event_file(session_id, event)
        if len(hist) > self._max_history:
            del hist[: len(hist) - self._max_history]
        q = self._queues.get(session_id)
        if q is None:
            return
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def close(self, session_id: str) -> None:
        self._closed.add(session_id)
        self._ignore_closed_file.discard(session_id)
        try:
            self._closed_path(session_id).write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
        except OSError:
            pass
        q = self._queues.get(session_id)
        if q is not None:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    def remove(self, session_id: str, queue: asyncio.Queue[AgentEvent | None] | None = None) -> None:
        if queue is None:
            self._queues.pop(session_id, None)
        else:
            current_q = self._queues.get(session_id)
            if current_q is queue:
                self._queues.pop(session_id, None)

    def get(self, session_id: str) -> asyncio.Queue[AgentEvent | None] | None:
        return self._queues.get(session_id)

    def history(self, session_id: str, *, after: int = 0, limit: int = 500) -> list[tuple[int, AgentEvent]]:
        events = self._history.get(session_id)
        if events is None:
            events = self._load_history_file(session_id)
            if events:
                self._history[session_id] = events
        events = events or []
        capped = max(1, min(limit, 2000))
        selected = [event for event in events if event.seq >= max(0, after)][:capped]
        return [(event.seq, event) for event in selected]

    def is_closed(self, session_id: str) -> bool:
        if session_id in self._closed:
            return True
        if session_id in self._ignore_closed_file:
            return False
        return self._closed_path(session_id).is_file()

    def known(self, session_id: str) -> bool:
        return session_id in self._history or session_id in self._queues or self._events_path(session_id).is_file()


BUS = SessionBus()
