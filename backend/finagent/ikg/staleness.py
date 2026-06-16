"""IKG context staleness checks.

Deep mode must not synthesize off a stale graph snapshot. These helpers compare
the most recent `updated_at` of a company's IKG vertices and edges (plus the
latest fact `as_of_date`) against thresholds, and emit a structured staleness
verdict the agent can act on (refresh / proceed / warn).

Pure scoring core (`classify_staleness`) + thin DB layer (`StalenessChecker`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.staleness")


# ── Thresholds (overridable by callers) ──────────────────────────────────────
DEFAULT_FRESH_DAYS = 14
DEFAULT_STALE_DAYS = 60


@dataclass
class StalenessVerdict:
    band: str                # "fresh" | "moderate" | "stale" | "no_data"
    needs_refresh: bool
    age_days: int | None
    last_updated: str | None
    sources_checked: dict[str, Any]
    reason: str = ""


def classify_staleness(
    last_updated: datetime | None,
    *,
    now: datetime | None = None,
    fresh_days: int = DEFAULT_FRESH_DAYS,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> StalenessVerdict:
    """Pure verdict from a single 'latest update' timestamp."""
    if last_updated is None:
        return StalenessVerdict(
            band="no_data", needs_refresh=True, age_days=None,
            last_updated=None, sources_checked={}, reason="no IKG vertices/edges/facts found",
        )
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age = (now - last_updated).total_seconds() / 86400.0
    age_days = int(age)
    if age <= fresh_days:
        return StalenessVerdict(
            band="fresh", needs_refresh=False, age_days=age_days,
            last_updated=last_updated.isoformat(), sources_checked={}, reason="within fresh window",
        )
    if age <= stale_days:
        return StalenessVerdict(
            band="moderate", needs_refresh=False, age_days=age_days,
            last_updated=last_updated.isoformat(), sources_checked={},
            reason=f"age {age_days}d > fresh window {fresh_days}d; usable with caveat",
        )
    return StalenessVerdict(
        band="stale", needs_refresh=True, age_days=age_days,
        last_updated=last_updated.isoformat(), sources_checked={},
        reason=f"age {age_days}d exceeds stale threshold {stale_days}d",
    )


class StalenessChecker:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = get_database_url(database_url)

    def _connect(self) -> Any:
        from psycopg.rows import dict_row
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=5)

    def check_company(
        self,
        cin: str,
        *,
        fresh_days: int = DEFAULT_FRESH_DAYS,
        stale_days: int = DEFAULT_STALE_DAYS,
    ) -> StalenessVerdict:
        """Compute the staleness verdict for a single company CIN.

        Inspects the most recent updated_at across the vertex itself, outgoing
        and incoming edges, and the most recent fact as_of/event_date. The
        latest of those wins — that's the freshest evidence we know about.
        """
        cin = (cin or "").upper().strip()
        if not cin or not self.database_url:
            return StalenessVerdict(
                band="no_data", needs_refresh=True, age_days=None,
                last_updated=None, sources_checked={}, reason="no CIN or DB URL configured",
            )
        entity_id = f"company:{cin}"
        sources: dict[str, str | None] = {}
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("select updated_at from ikg_vertices where vertex_id = %s", (entity_id,))
                    row = cur.fetchone()
                    sources["vertex"] = row["updated_at"].isoformat() if row and row.get("updated_at") else None

                    cur.execute(
                        "select max(updated_at) as t from ikg_edges "
                        "where from_vertex_id = %s or to_vertex_id = %s",
                        (entity_id, entity_id),
                    )
                    row = cur.fetchone()
                    sources["edges"] = row["t"].isoformat() if row and row.get("t") else None

                    cur.execute(
                        "select max(coalesce(as_of_date, event_date, updated_at::date)) as t "
                        "from ikg_facts where subject_entity_id = %s",
                        (entity_id,),
                    )
                    row = cur.fetchone()
                    t = row.get("t") if row else None
                    sources["facts"] = t.isoformat() if t else None
        except Exception as exc:
            logger.warning("Staleness check DB error for %s: %s", cin, exc)
            return StalenessVerdict(
                band="no_data", needs_refresh=True, age_days=None,
                last_updated=None, sources_checked={"error": str(exc)},
                reason="staleness DB lookup failed",
            )

        # Pick the latest timestamp across all sources.
        candidates: list[datetime] = []
        for v in sources.values():
            if not v:
                continue
            try:
                if "T" in v:
                    candidates.append(datetime.fromisoformat(v.replace("Z", "+00:00")))
                else:
                    candidates.append(datetime.fromisoformat(v + "T00:00:00+00:00"))
            except ValueError:
                continue
        latest = max(candidates) if candidates else None
        verdict = classify_staleness(latest, fresh_days=fresh_days, stale_days=stale_days)
        verdict.sources_checked = sources
        return verdict


_checker: StalenessChecker | None = None


def get_staleness_checker() -> StalenessChecker:
    global _checker
    if _checker is None:
        _checker = StalenessChecker()
    return _checker
