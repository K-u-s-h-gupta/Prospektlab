"""In-process event bus that connects the agent loop to the gateway SSE stream.

Hardening changes:
- All file I/O is offloaded to asyncio.to_thread() to prevent event-loop blocking.
- JSONL files are capped at _max_file_size to prevent unbounded disk growth.
- In-memory history is capped at _max_history.
"""

from __future__ import annotations

import asyncio
import json
import os
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
    """One asyncio.Queue per live SSE session, plus replayable event history.

    Hardening:
    - All disk I/O is offloaded to asyncio.to_thread() to avoid blocking the event loop.
    - JSONL files are capped at _max_file_size (10MB) to prevent unbounded growth.
    - In-memory history is capped at _max_history.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[AgentEvent | None]] = {}
        self._history: dict[str, list[AgentEvent]] = {}
        self._closed: set[str] = set()
        self._ignore_closed_file: set[str] = set()
        self._max_history = 5000
        self._max_file_size = 10 * 1024 * 1024  # 10 MB cap per session JSONL

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

    async def _append_event_file(self, session_id: str, event: AgentEvent) -> None:
        def _write():
            path = self._events_path(session_id)
            try:
                # Cap file size: if > 10MB, truncate to last 5000 lines
                if path.exists() and path.stat().st_size > self._max_file_size:
                    try:
                        lines = path.read_text(encoding="utf-8").splitlines()
                        lines = lines[-5000:]
                        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    except Exception:
                        pass
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event.to_record(), default=str, ensure_ascii=False) + "\n")
            except OSError:
                pass

        try:
            await asyncio.to_thread(_write)
        except Exception:
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
        # Offload disk write to thread pool
        try:
            asyncio.get_running_loop().create_task(self._append_event_file(session_id, event))
        except RuntimeError:
            # No running loop; fall back to sync write (should not happen in production)
            import threading
            threading.Thread(target=lambda: asyncio.run(self._append_event_file(session_id, event)), daemon=True).start()
        if len(hist) > self._max_history:
            del hist[: len(hist) - self._max_history]
        q = self._queues.get(session_id)
        if q is None:
            return
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Emit backpressure warning so frontend knows events are being dropped
            try:
                warn = AgentEvent(
                    type="warning",
                    payload={"message": "Event buffer saturated; telemetry truncated"},
                    seq=len(hist),
                )
                q.put_nowait(warn)
            except asyncio.QueueFull:
                pass

    def close(self, session_id: str) -> None:
        self._closed.add(session_id)
        self._ignore_closed_file.discard(session_id)

        def _write_closed():
            try:
                self._closed_path(session_id).write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
            except OSError:
                pass

        try:
            asyncio.get_running_loop().create_task(asyncio.to_thread(_write_closed))
        except RuntimeError:
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
        capped = max(1, min(limit, 5000))
        selected = [event for event in events if event.seq >= max(0, after)][:capped]
        return [(event.seq, event) for event in selected]

    def subscribe(self, session_id: str, *, after: int = 0, limit: int = 500) -> tuple[list[tuple[int, AgentEvent]], asyncio.Queue[AgentEvent | None] | None]:
        """Atomic history + live queue snapshot. Prevents race between replay and new events."""
        hist = self.history(session_id, after=after, limit=limit)
        q = self.get(session_id)
        return hist, q

    def is_closed(self, session_id: str) -> bool:
        if session_id in self._closed:
            return True
        if session_id in self._ignore_closed_file:
            return False
        return self._closed_path(session_id).is_file()

    def known(self, session_id: str) -> bool:
        return session_id in self._history or session_id in self._queues or self._events_path(session_id).is_file()

    def cleanup_old_sessions(self, max_age: float = 3600) -> int:
        """Remove closed sessions older than max_age seconds from memory to prevent leaks."""
        now = datetime.now(timezone.utc).timestamp()
        removed = 0
        for session_id in list(self._closed):
            path = self._events_path(session_id)
            if path.exists():
                mtime = path.stat().st_mtime
                if now - mtime > max_age:
                    self.forget_memory(session_id)
                    removed += 1
        return removed


BUS = SessionBus()
