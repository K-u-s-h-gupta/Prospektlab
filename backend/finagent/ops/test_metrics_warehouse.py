"""Tests for metrics warehouse: pure cohort functions + SQLite round-trip."""

from __future__ import annotations

import os
import tempfile
from datetime import date

from finagent.ops.metrics_warehouse import (
    MetricsWarehouse,
    compute_dau_mau,
    compute_event_volume,
    compute_weekly_retention,
)


def _ev(uid, ts, etype="login"):
    return {"user_id": uid, "event_ts": ts, "event_type": etype}


def test_dau_mau_basic():
    events = [
        _ev("u1", "2026-06-12"),
        _ev("u2", "2026-06-12"),
        _ev("u1", "2026-06-12"),       # dup user same day
        _ev("u3", "2026-05-20"),       # in MAU window, not DAU
        _ev("u4", "2026-04-01"),       # outside 30d window
    ]
    out = compute_dau_mau(events, date(2026, 6, 12))
    assert out["dau"] == 2
    assert out["mau"] == 3            # u1,u2,u3 within trailing 30 days
    assert out["stickiness"] == round(2 / 3, 3)


def test_dau_mau_empty():
    out = compute_dau_mau([], date(2026, 6, 12))
    assert out["dau"] == 0 and out["mau"] == 0 and out["stickiness"] == 0.0


def test_weekly_retention_perfect():
    # u1 active 3 consecutive weeks from cohort week
    events = [
        _ev("u1", "2026-06-01"),  # Mon W0
        _ev("u1", "2026-06-08"),  # W1
        _ev("u1", "2026-06-15"),  # W2
    ]
    out = compute_weekly_retention(events, max_weeks=2)
    coh = out["cohorts"][0]
    assert coh["size"] == 1
    assert coh["retention"][0] == 1.0
    assert coh["retention"][1] == 1.0
    assert coh["retention"][2] == 1.0


def test_weekly_retention_churn():
    # 2 users in cohort; only 1 returns in W1
    events = [
        _ev("u1", "2026-06-01"), _ev("u2", "2026-06-01"),  # cohort W0, size 2
        _ev("u1", "2026-06-08"),                            # only u1 in W1
    ]
    out = compute_weekly_retention(events, max_weeks=1)
    coh = out["cohorts"][0]
    assert coh["size"] == 2
    assert coh["retention"][0] == 1.0
    assert coh["retention"][1] == 0.5


def test_event_volume():
    events = [_ev("u1", "2026-06-01", "login"), _ev("u1", "2026-06-01", "memo_generated"),
              _ev("u2", "2026-06-01", "login")]
    vol = compute_event_volume(events)
    assert vol["login"] == 2
    assert vol["memo_generated"] == 1


def test_warehouse_roundtrip_and_snapshot():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        wh = MetricsWarehouse(db_path=path)
        wh.record_event("u1", "login", event_ts="2026-06-12T08:00:00+00:00")
        wh.record_event("u2", "login", event_ts="2026-06-12T09:00:00+00:00")
        wh.record_event("u1", "memo_generated", event_ts="2026-06-12T09:30:00+00:00")
        snap = wh.snapshot(as_of=date(2026, 6, 12))
        assert snap["engagement"]["dau"] == 2
        assert snap["event_volume"]["login"] == 2
        assert snap["event_volume"]["memo_generated"] == 1
        assert "cohorts" in snap["retention"]
    finally:
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(path + ext)
            except OSError:
                pass


def test_record_event_ignores_blank():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        wh = MetricsWarehouse(db_path=path)
        wh.record_event("", "login")          # blank user → ignored
        wh.record_event("u1", "")             # blank type → ignored
        snap = wh.snapshot(as_of=date(2026, 6, 12))
        assert snap["event_volume"] == {}
    finally:
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(path + ext)
            except OSError:
                pass
