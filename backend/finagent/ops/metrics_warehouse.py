"""Metrics warehouse — durable usage-event log + investor-grade cohort metrics.

Records product usage events to a WAL-mode SQLite table (host-durable, survives
restarts) and computes the metrics investors ask for:

  - DAU / MAU / stickiness (DAU/MAU)
  - Weekly retention cohorts (W0..Wn)
  - Per-event-type volume

Cohort math is implemented as PURE functions over event rows so it is unit-
testable without a database. `MetricsWarehouse` is the thin DB layer.

This exists so the "6-month metrics history" investors expect starts
accumulating today. Events should be recorded at the gateway for: login,
research_session, memo_generated, portfolio_view, governance_view, api_call.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from finagent.paths import finagent_data_path
from finagent.storage.sqlite import connect_wal


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value)
    # Accept ISO date or datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def _week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


# ── Pure cohort/metric functions (no DB) ──────────────────────────────────────

def compute_dau_mau(events: Iterable[dict[str, Any]], as_of: date) -> dict[str, Any]:
    """DAU (as_of day), MAU (trailing 30 days incl. as_of), stickiness."""
    dau_users: set[str] = set()
    mau_users: set[str] = set()
    window_start = as_of - timedelta(days=29)
    for e in events:
        uid = str(e.get("user_id") or "")
        if not uid:
            continue
        d = _to_date(e.get("event_ts"))
        if d == as_of:
            dau_users.add(uid)
        if window_start <= d <= as_of:
            mau_users.add(uid)
    dau = len(dau_users)
    mau = len(mau_users)
    return {
        "as_of": as_of.isoformat(),
        "dau": dau,
        "mau": mau,
        "stickiness": round(dau / mau, 3) if mau else 0.0,
    }


def compute_weekly_retention(events: Iterable[dict[str, Any]], max_weeks: int = 8) -> dict[str, Any]:
    """Weekly retention cohorts keyed by each user's first-seen week.

    Returns: {"cohorts": [{"cohort_week","size","retention":[1.0, w1, w2,...]}]}
    retention[N] = fraction of cohort users active in the Nth week after signup.
    """
    # first-seen week per user, and set of active weeks per user
    first_week: dict[str, date] = {}
    active_weeks: dict[str, set[date]] = defaultdict(set)
    for e in events:
        uid = str(e.get("user_id") or "")
        if not uid:
            continue
        wk = _week_start(_to_date(e.get("event_ts")))
        active_weeks[uid].add(wk)
        if uid not in first_week or wk < first_week[uid]:
            first_week[uid] = wk

    cohort_members: dict[date, list[str]] = defaultdict(list)
    for uid, wk in first_week.items():
        cohort_members[wk].append(uid)

    cohorts = []
    for cohort_week in sorted(cohort_members):
        members = cohort_members[cohort_week]
        size = len(members)
        retention: list[float] = []
        for n in range(max_weeks + 1):
            target = cohort_week + timedelta(weeks=n)
            active = sum(1 for uid in members if target in active_weeks[uid])
            retention.append(round(active / size, 3) if size else 0.0)
        cohorts.append({
            "cohort_week": cohort_week.isoformat(),
            "size": size,
            "retention": retention,
        })
    return {"cohorts": cohorts, "max_weeks": max_weeks}


def compute_event_volume(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    vol: dict[str, int] = defaultdict(int)
    for e in events:
        vol[str(e.get("event_type") or "unknown")] += 1
    return dict(vol)


# ── DB layer ──────────────────────────────────────────────────────────────────

class MetricsWarehouse:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or finagent_data_path("metrics_warehouse.db")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return connect_wal(self.db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    session_id TEXT,
                    props TEXT,
                    event_ts TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_usage_user_ts ON usage_events(user_id, event_ts)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_usage_type_ts ON usage_events(event_type, event_ts)")
            conn.commit()

    def record_event(
        self,
        user_id: str,
        event_type: str,
        *,
        session_id: str | None = None,
        props: str | None = None,
        event_ts: str | None = None,
    ) -> None:
        if not user_id or not event_type:
            return
        ts = event_ts or datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO usage_events (user_id, event_type, session_id, props, event_ts) VALUES (?, ?, ?, ?, ?)",
                (user_id, event_type, session_id, props, ts),
            )
            conn.commit()

    def _fetch_events(self, since: date | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            cur = conn.cursor()
            if since:
                cur.execute(
                    "SELECT user_id, event_type, event_ts FROM usage_events WHERE event_ts >= ?",
                    (since.isoformat(),),
                )
            else:
                cur.execute("SELECT user_id, event_type, event_ts FROM usage_events")
            return [{"user_id": r[0], "event_type": r[1], "event_ts": r[2]} for r in cur.fetchall()]

    def snapshot(self, as_of: date | None = None) -> dict[str, Any]:
        """Full metrics snapshot for the internal /metrics dashboard."""
        as_of = as_of or datetime.now(timezone.utc).date()
        events = self._fetch_events()
        return {
            "engagement": compute_dau_mau(events, as_of),
            "retention": compute_weekly_retention(events),
            "event_volume": compute_event_volume(events),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


_warehouse: MetricsWarehouse | None = None


def get_metrics_warehouse() -> MetricsWarehouse:
    global _warehouse
    if _warehouse is None:
        _warehouse = MetricsWarehouse()
    return _warehouse
