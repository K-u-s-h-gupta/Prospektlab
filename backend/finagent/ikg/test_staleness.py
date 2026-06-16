"""Tests for IKG staleness classification (pure)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from finagent.ikg.staleness import classify_staleness


def test_fresh_window():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    v = classify_staleness(now - timedelta(days=5), now=now)
    assert v.band == "fresh"
    assert v.needs_refresh is False


def test_moderate_window():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    v = classify_staleness(now - timedelta(days=30), now=now)
    assert v.band == "moderate"
    assert v.needs_refresh is False


def test_stale_triggers_refresh():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    v = classify_staleness(now - timedelta(days=120), now=now)
    assert v.band == "stale"
    assert v.needs_refresh is True
    assert v.age_days == 120


def test_no_data_treated_as_refresh():
    v = classify_staleness(None)
    assert v.band == "no_data"
    assert v.needs_refresh is True


def test_naive_datetime_normalized_to_utc():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    v = classify_staleness(datetime(2026, 6, 10), now=now)
    assert v.band == "fresh"


def test_thresholds_configurable():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    v = classify_staleness(now - timedelta(days=20), now=now, fresh_days=10, stale_days=15)
    assert v.band == "stale"
    assert v.needs_refresh is True
