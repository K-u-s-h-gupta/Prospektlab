from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from dataclasses import dataclass

from finagent.events import BUS
from finagent.telemetry import TELEMETRY

logger = logging.getLogger("finagent.telemetry_burner")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class TelemetryBurnerSettings:
    enabled: bool
    interval_seconds: float
    burst_size: int
    payload_kb: int
    session_fanout: int
    exception_every: int
    replay_limit: int
    rotate_after_cycles: int


def load_telemetry_burner_settings() -> TelemetryBurnerSettings:
    return TelemetryBurnerSettings(
        enabled=_env_bool("TELEMETRY_BURNER_ENABLED", False),
        interval_seconds=_env_float("TELEMETRY_BURNER_INTERVAL_S", 5.0),
        burst_size=_env_int("TELEMETRY_BURNER_BURST_SIZE", 12),
        payload_kb=_env_int("TELEMETRY_BURNER_PAYLOAD_KB", 12),
        session_fanout=_env_int("TELEMETRY_BURNER_SESSION_FANOUT", 3),
        exception_every=max(1, _env_int("TELEMETRY_BURNER_EXCEPTION_EVERY", 5)),
        replay_limit=_env_int("TELEMETRY_BURNER_REPLAY_LIMIT", 5000),
        rotate_after_cycles=_env_int("TELEMETRY_BURNER_ROTATE_AFTER_CYCLES", 60),
    )


def _payload_blob(*, session_id: str, cycle: int, index: int, size_kb: int) -> str:
    size_bytes = max(256, size_kb * 1024)
    seed = json.dumps(
        {
            "session_id": session_id,
            "cycle": cycle,
            "index": index,
            "source": "telemetry_burner",
            "note": "synthetic high-volume observability payload",
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    repeat_count = (size_bytes // max(1, len(seed))) + 2
    return (seed * repeat_count)[:size_bytes]


class TelemetryBurner:
    def __init__(self, settings: TelemetryBurnerSettings | None = None) -> None:
        self.settings = settings or load_telemetry_burner_settings()
        self._instance_id = (socket.gethostname() or "backend").replace(" ", "-")
        self._session_ids = [
            f"telemetry-burner-{self._instance_id}-{index + 1}"
            for index in range(self.settings.session_fanout)
        ]
        self._last_replayed_seq: dict[str, int] = {session_id: -1 for session_id in self._session_ids}
        self._cycle = 0
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def start(self) -> asyncio.Task[None] | None:
        if not self.enabled:
            return None
        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.run_forever(), name="telemetry-burner")
        return self._task

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_forever(self) -> None:
        if not self.enabled:
            return

        logger.info(
            "Telemetry burner enabled: interval=%ss burst=%s payload=%sKB fanout=%s",
            self.settings.interval_seconds,
            self.settings.burst_size,
            self.settings.payload_kb,
            self.settings.session_fanout,
        )

        try:
            while True:
                await self.run_cycle()
                await asyncio.sleep(self.settings.interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telemetry burner stopped unexpectedly")

    async def run_cycle(self) -> None:
        if not self.enabled:
            return

        self._cycle += 1
        cycle_id = self._cycle
        payload_size = self.settings.payload_kb * 1024

        for session_index, session_id in enumerate(self._session_ids):
            if cycle_id > 1 and self.settings.rotate_after_cycles and cycle_id % self.settings.rotate_after_cycles == 0:
                BUS.forget_memory(session_id)
                self._last_replayed_seq[session_id] = -1

            base_request_id = f"{session_id}-{cycle_id}-{session_index}"
            burst_started = asyncio.get_running_loop().time()

            TELEMETRY.emit_request(
                name="POST /telemetry-burner/cycle",
                url=f"telemetry://{session_id}/cycle/{cycle_id}",
                method="POST",
                duration_ms=1,
                success=True,
                status_code=200,
                request_id=base_request_id,
                session_id=session_id,
                properties={
                    "source": "telemetry_burner",
                    "burn_mode": "aggressive",
                    "cycle_id": cycle_id,
                    "session_id": session_id,
                    "session_index": session_index,
                    "payload_kb": self.settings.payload_kb,
                    "burst_size": self.settings.burst_size,
                },
                measurements={
                    "payload_bytes": float(payload_size),
                },
            )

            BUS.emit(
                session_id,
                "session_started",
                source="telemetry_burner",
                burn_mode="aggressive",
                cycle=cycle_id,
                session_index=session_index,
                payload_kb=self.settings.payload_kb,
                payload_bytes=payload_size,
            )
            TELEMETRY.emit_event(
                "telemetry_burner_session_started",
                request_id=base_request_id,
                session_id=session_id,
                properties={
                    "source": "telemetry_burner",
                    "burn_mode": "aggressive",
                    "cycle_id": cycle_id,
                    "session_id": session_id,
                    "session_index": session_index,
                    "payload_kb": self.settings.payload_kb,
                    "payload_bytes": payload_size,
                },
                measurements={
                    "payload_bytes": float(payload_size),
                },
            )

            for burst_index in range(self.settings.burst_size):
                event_type = ("phase", "agent_task", "query", "log")[burst_index % 4]
                payload_blob = _payload_blob(
                    session_id=session_id,
                    cycle=cycle_id,
                    index=burst_index,
                    size_kb=self.settings.payload_kb,
                )
                record_payload = {
                    "source": "telemetry_burner",
                    "burn_mode": "aggressive",
                    "cycle": cycle_id,
                    "session_id": session_id,
                    "session_index": session_index,
                    "burst_index": burst_index,
                    "event_type": event_type,
                    "payload_blob": payload_blob,
                }

                BUS.emit(session_id, event_type, **record_payload)

                request_id = f"{base_request_id}-{burst_index}"
                TELEMETRY.emit_event(
                    f"telemetry_burner_{event_type}",
                    request_id=request_id,
                    session_id=session_id,
                    properties=record_payload,
                    measurements={
                        "payload_bytes": float(len(payload_blob.encode("utf-8"))),
                        "burst_index": float(burst_index),
                    },
                )
                TELEMETRY.emit_trace(
                    f"telemetry burner {event_type}",
                    severity_level=1,
                    request_id=request_id,
                    session_id=session_id,
                    properties=record_payload,
                    measurements={
                        "payload_bytes": float(len(payload_blob.encode("utf-8"))),
                    },
                )
                TELEMETRY.emit_dependency(
                    name="telemetry-burner-local",
                    target="telemetry-burner",
                    data=f"telemetry://{session_id}/{cycle_id}/{burst_index}",
                    duration_ms=max(1, int((asyncio.get_running_loop().time() - burst_started) * 1000)),
                    success=True,
                    status_code=200,
                    request_id=request_id,
                    properties=record_payload,
                    measurements={
                        "payload_bytes": float(len(payload_blob.encode("utf-8"))),
                    },
                )
                TELEMETRY.emit_metric(
                    "telemetry_burner_payload_bytes",
                    len(payload_blob.encode("utf-8")),
                    request_id=request_id,
                    session_id=session_id,
                    properties=record_payload,
                )

                if (cycle_id + burst_index + session_index) % self.settings.exception_every == 0:
                    try:
                        raise RuntimeError(
                            f"synthetic telemetry burner exception cycle={cycle_id} session={session_id} burst={burst_index}"
                        )
                    except Exception as exc:
                        TELEMETRY.emit_exception(
                            exc,
                            request_id=request_id,
                            session_id=session_id,
                            properties=record_payload,
                            measurements={
                                "payload_bytes": float(len(payload_blob.encode("utf-8"))),
                            },
                        )

            history = BUS.history(
                session_id,
                after=self._last_replayed_seq.get(session_id, -1),
                limit=self.settings.replay_limit,
            )
            for seq, event in history:
                record = event.to_record()
                record_json = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                TELEMETRY.emit_trace(
                    f"telemetry burner replay {event.type}",
                    severity_level=1,
                    request_id=f"{base_request_id}-replay-{seq}",
                    session_id=session_id,
                    properties={
                        "source": "telemetry_burner",
                        "burn_mode": "aggressive",
                        "cycle_id": cycle_id,
                        "session_id": session_id,
                        "seq": seq,
                        "event_type": event.type,
                        "raw_jsonl": record_json,
                    },
                    measurements={
                        "record_bytes": float(len(record_json.encode("utf-8"))),
                    },
                )
                TELEMETRY.emit_metric(
                    "telemetry_burner_record_bytes",
                    len(record_json.encode("utf-8")),
                    request_id=f"{base_request_id}-replay-{seq}",
                    session_id=session_id,
                    properties={
                        "source": "telemetry_burner",
                        "burn_mode": "aggressive",
                        "cycle_id": cycle_id,
                        "session_id": session_id,
                        "seq": seq,
                        "event_type": event.type,
                    },
                )
                self._last_replayed_seq[session_id] = seq


_BURNER: TelemetryBurner | None = None


def get_telemetry_burner() -> TelemetryBurner:
    global _BURNER
    if _BURNER is None:
        _BURNER = TelemetryBurner()
    return _BURNER


def create_telemetry_burner_task() -> asyncio.Task[None] | None:
    burner = get_telemetry_burner()
    return burner.start()
