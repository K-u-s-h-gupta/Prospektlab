from __future__ import annotations

import asyncio
from dataclasses import dataclass

from finagent.telemetry import TelemetryClient, TelemetrySettings
from finagent.telemetry_burner import TelemetryBurner, TelemetryBurnerSettings


@dataclass
class _FakeEvent:
    type: str
    payload: dict
    seq: int

    def to_record(self) -> dict:
        return {
            "seq": self.seq,
            "type": self.type,
            "timestamp": f"2026-06-05T00:00:0{self.seq}Z",
            "payload": self.payload,
        }


class _FakeBus:
    def __init__(self) -> None:
        self.events: dict[str, list[_FakeEvent]] = {}
        self.forgot: list[str] = []

    def emit(self, *args, **payload):
        session_id, event_type = args
        history = self.events.setdefault(session_id, [])
        history.append(_FakeEvent(type=event_type, payload=payload, seq=len(history)))

    def history(self, session_id: str, *, after: int = 0, limit: int = 500):
        history = self.events.get(session_id, [])
        selected = [event for event in history if event.seq >= after][:limit]
        return [(event.seq, event) for event in selected]

    def forget_memory(self, session_id: str) -> None:
        self.events.pop(session_id, None)
        self.forgot.append(session_id)


class _FakeTelemetry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def emit_request(self, *args, **kwargs):
        self.calls.append(("request", args, kwargs))

    def emit_event(self, *args, **kwargs):
        self.calls.append(("event", args, kwargs))

    def emit_trace(self, *args, **kwargs):
        self.calls.append(("trace", args, kwargs))

    def emit_dependency(self, *args, **kwargs):
        self.calls.append(("dependency", args, kwargs))

    def emit_metric(self, *args, **kwargs):
        self.calls.append(("metric", args, kwargs))

    def emit_exception(self, *args, **kwargs):
        self.calls.append(("exception", args, kwargs))


def test_telemetry_client_emits_trace_and_metric_envelopes():
    client = TelemetryClient()
    client.settings = TelemetrySettings(
        enabled=True,
        connection_string="InstrumentationKey=ikey;IngestionEndpoint=https://example.test/",
        ingestion_url="https://example.test/v2/track",
        instrumentation_key="ikey",
        role_name="role",
        role_instance="instance",
    )
    client._client = None

    captured: list[dict] = []
    client._schedule = lambda payload: captured.append(payload)

    client.emit_trace(
        "hello trace",
        request_id="req-1",
        session_id="sess-1",
        properties={"foo": "bar"},
        measurements={"payload_bytes": 12},
    )
    client.emit_metric(
        "payload_bytes",
        12,
        request_id="req-2",
        session_id="sess-2",
        properties={"kind": "burner"},
    )

    assert captured[0]["data"]["baseType"] == "MessageData"
    assert captured[0]["tags"]["ai.operation.id"] == "req-1"
    assert captured[0]["tags"]["ai.session.id"] == "sess-1"
    assert captured[0]["data"]["baseData"]["message"] == "hello trace"
    assert captured[1]["data"]["baseType"] == "MetricData"
    assert captured[1]["data"]["baseData"]["metrics"][0]["name"] == "payload_bytes"
    assert captured[1]["tags"]["ai.operation.id"] == "req-2"


def test_telemetry_burner_replays_jsonl_and_emits_bursts(monkeypatch):
    fake_bus = _FakeBus()
    fake_telemetry = _FakeTelemetry()
    monkeypatch.setattr("finagent.telemetry_burner.BUS", fake_bus)
    monkeypatch.setattr("finagent.telemetry_burner.TELEMETRY", fake_telemetry)

    burner = TelemetryBurner(
        TelemetryBurnerSettings(
            enabled=True,
            interval_seconds=60.0,
            burst_size=2,
            payload_kb=1,
            session_fanout=2,
            exception_every=2,
            replay_limit=100,
            rotate_after_cycles=100,
        )
    )

    asyncio.run(burner.run_cycle())

    assert any(kind == "request" for kind, _, _ in fake_telemetry.calls)
    assert any(kind == "event" for kind, _, _ in fake_telemetry.calls)
    assert any(kind == "trace" and kwargs["properties"].get("raw_jsonl") for kind, _, kwargs in fake_telemetry.calls)
    assert any(kind == "metric" for kind, _, _ in fake_telemetry.calls)
    assert any(kind == "exception" for kind, _, _ in fake_telemetry.calls)
    assert set(fake_bus.events.keys()) == {
        f"telemetry-burner-{burner._instance_id}-1",
        f"telemetry-burner-{burner._instance_id}-2",
    }
