"""IGS Phase A — failure-event label mining.

Builds the ``failure_events`` positive-class label set that converts the heuristic
governance score into a trainable predictor. Two free sources, no new scraping:

  1. MCA master ``status`` column — ~975k struck-off / liquidated / CIRP / dissolved
     companies already in ``ikg_company_master`` (corporate-death outcomes).
  2. SEBI enforcement orders — debarment / restraint actions, linked to companies via
     the (now trigram-resolved) ENFORCEMENT_ACTION_AGAINST edges.

Mapping is intentionally conservative: only unambiguous corporate-death / financial-
failure statuses get ``is_failure = true``. Ambiguous outcomes (amalgamation,
dormancy, e-filing lapses) are recorded with ``is_failure = false`` so the modelling
layer can opt in or out without re-mining.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.scrapers.failure_labels")

# (raw MCA status, canonical event_type, is_failure, confidence)
# Counts (live, 2026-06) shown for context.
STATUS_MAP: tuple[tuple[str, str, bool, float], ...] = (
    ("Strike Off",                      "struck_off",          True,  0.90),  # 895,779
    ("Under process of striking off",   "struck_off_pending",  True,  0.70),  # 26,370
    ("Strike Off-AwaitingPublication",  "struck_off_pending",  True,  0.75),  # 35
    ("Dissolved (Liquidated)",          "dissolved_liquidated", True, 0.90),  # 11,972
    ("Dissolved",                       "dissolved",           True,  0.85),  # 186
    ("Dissolved under section 59(8)",   "dissolved",           True,  0.85),  # 973
    ("Dissolved under section 54",      "dissolved",           True,  0.85),  # 497
    ("Under Liquidation",               "under_liquidation",   True,  0.85),  # 8,519
    ("Under CIRP",                      "ibc_cirp",            True,  0.95),  # 1,925 — strongest financial-failure signal
    ("Vanished",                        "vanished",            True,  0.95),  # 1
    # Weak / ambiguous — recorded but not labelled as failure by default.
    ("Amalgamated",                     "amalgamated",         False, 0.40),  # 40,187
    ("Dormant under section 455",       "dormant",             False, 0.30),  # 2,609
    ("Inactive",                        "inactive",            False, 0.30),  # 5
    ("Inactive for e-filing",           "efiling_lapse",       False, 0.20),  # 8,402
)

_DEBARMENT_RE = re.compile(
    r"\b(debar|restrain|prohibit|banned|barred|disgorge|cease and desist|"
    r"not to access the securities market|restrained from)\b",
    flags=re.I,
)

_FAILURE_EVENTS_DDL = """
create table if not exists failure_events (
    id            bigserial primary key,
    cin           text not null,
    event_type    text not null,
    event_subtype text,
    event_date    date,
    is_failure    boolean not null default true,
    source        text not null,
    source_url    text,
    confidence    numeric not null default 0.80,
    evidence_text text,
    properties    jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    unique (cin, event_type, source)
);
create index if not exists idx_failure_events_cin        on failure_events (cin);
create index if not exists idx_failure_events_event_type on failure_events (event_type);
create index if not exists idx_failure_events_event_date on failure_events (event_date);
create index if not exists idx_failure_events_is_failure on failure_events (is_failure) where is_failure;
"""


def ensure_failure_events_table(database_url: str | None = None) -> None:
    db_url = get_database_url(database_url)
    if not db_url:
        return
    with connect_postgres(db_url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute(_FAILURE_EVENTS_DDL)
        conn.commit()


def mine_mca_status_failures(database_url: str | None = None) -> dict[str, Any]:
    """Mine ``ikg_company_master.status`` into ``failure_events`` (single set-based upsert)."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "rows_upserted": 0}
    ensure_failure_events_table(db_url)

    values_sql = ", ".join("(%s, %s, %s, %s)" for _ in STATUS_MAP)
    params: list[Any] = []
    for raw, event_type, is_failure, confidence in STATUS_MAP:
        params.extend([raw, event_type, is_failure, confidence])

    stats: dict[str, Any] = {"success": False, "rows_upserted": 0}
    try:
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    insert into failure_events
                        (cin, event_type, event_subtype, is_failure, source, confidence, properties)
                    select m.cin, map.event_type, m.status, map.is_failure,
                           'mca_master_status', map.confidence,
                           jsonb_build_object(
                               'mca_status', m.status,
                               'company_name', m.company_name,
                               'listing_status', m.listing_status,
                               'registration_date', m.registration_date::text
                           )
                    from ikg_company_master m
                    join (values {values_sql})
                         as map(raw_status, event_type, is_failure, confidence)
                      on upper(btrim(m.status)) = upper(map.raw_status)
                    where m.cin is not null and btrim(m.cin) <> ''
                    on conflict (cin, event_type, source) do update set
                        event_subtype = excluded.event_subtype,
                        is_failure    = excluded.is_failure,
                        confidence    = excluded.confidence,
                        properties    = excluded.properties,
                        updated_at    = now()
                    """,
                    params,
                )
                stats["rows_upserted"] = cur.rowcount
                cur.execute(
                    "select count(*) from failure_events where source = 'mca_master_status' and is_failure"
                )
                stats["total_failures"] = cur.fetchone()[0]
            conn.commit()
        stats["success"] = True
    except Exception as exc:
        logger.error("MCA status failure mining failed: %s", exc)
        stats["error"] = str(exc)
    return stats


def mine_sebi_debarments(database_url: str | None = None) -> dict[str, Any]:
    """Record SEBI debarment/restraint orders as failure events for linked companies."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "rows_upserted": 0}
    ensure_failure_events_table(db_url)

    stats: dict[str, Any] = {"success": False, "rows_upserted": 0, "orders_scanned": 0}
    try:
        from psycopg.rows import dict_row

        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                # Companies linked to debarment-type orders via the enforcement edges.
                cur.execute(
                    """
                    select e.to_vertex_id as company_vid, r.order_number, r.order_date,
                           r.violation_type, r.pdf_url, r.full_text
                    from ikg_edges e
                    join enforcement_raw r on r.order_number = split_part(e.from_vertex_id, ':', 2)
                    where e.label = 'ENFORCEMENT_ACTION_AGAINST'
                      and e.to_vertex_id like 'company:%'
                    """
                )
                rows = cur.fetchall()
                stats["orders_scanned"] = len(rows)
                upserted = 0
                for row in rows:
                    text = f"{row.get('violation_type') or ''} {row.get('full_text') or ''}"
                    if not _DEBARMENT_RE.search(text):
                        continue
                    cin = str(row.get("company_vid") or "").split(":", 1)[-1].strip()
                    if not cin:
                        continue
                    cur.execute(
                        """
                        insert into failure_events
                            (cin, event_type, event_subtype, event_date, is_failure,
                             source, source_url, confidence, evidence_text, properties)
                        values (%s, 'sebi_debarment', %s, %s, true, 'sebi_enforcement', %s, 0.85, %s,
                                jsonb_build_object('order_number', %s::text))
                        on conflict (cin, event_type, source) do update set
                            event_date = excluded.event_date,
                            source_url = excluded.source_url,
                            evidence_text = excluded.evidence_text,
                            properties = excluded.properties,
                            updated_at = now()
                        """,
                        (
                            cin,
                            row.get("violation_type"),
                            row.get("order_date"),
                            row.get("pdf_url"),
                            (text or "")[:500],
                            row.get("order_number"),
                        ),
                    )
                    upserted += cur.rowcount
                stats["rows_upserted"] = upserted
            conn.commit()
        stats["success"] = True
    except Exception as exc:
        logger.error("SEBI debarment mining failed: %s", exc)
        stats["error"] = str(exc)
    return stats


def run_failure_label_refresh(database_url: str | None = None) -> dict[str, Any]:
    """Mine all free failure-label sources into ``failure_events``."""
    db_url = get_database_url(database_url)
    mca = mine_mca_status_failures(db_url)
    sebi = mine_sebi_debarments(db_url)
    return {
        "success": bool(mca.get("success") and sebi.get("success")),
        "mca": mca,
        "sebi": sebi,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json

    print(json.dumps(run_failure_label_refresh(), default=str, indent=2))
