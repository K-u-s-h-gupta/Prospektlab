"""Exchange delisting / suspension failure-label scraper (BSE List-of-Scrips).

BSE publishes the full delisted (~4,600) and suspended (~1,200) equity lists with
ISIN. Exchange delisting *for cause* and long suspension are stronger governance-
failure signals for the listed universe than MCA strike-off (which is dominated by
tiny private shells). These map to a CIN via ISIN/scrip and become high-quality
positive labels in ``failure_events``.

The API carries no delisting date, so the event is dated by a proxy: the company's
last shareholding-pattern filing (a delisted company stops filing — its last SHP
quarter ≈ when it went dark). That makes the label usable for point-in-time training.
Reachable from ikg-vm (api.bseindia.com is not IP-blocked, unlike NSE).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.scrapers.bse_delisting")

_BSE_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
}
# (BSE status, failure event_type, is_failure, confidence)
_STATUS_MAP: tuple[tuple[str, str, float], ...] = (
    ("Delisted", "exchange_delisting", 0.85),
    ("Suspended", "exchange_suspension", 0.70),
)


def fetch_status_list(status: str, *, timeout_s: float = 60.0) -> list[dict[str, Any]]:
    """Fetch the BSE equity list for a given status (Delisted / Suspended)."""
    for _ in range(3):
        try:
            with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as c:
                r = c.get(_BSE_LIST_URL, headers=_BSE_HEADERS, params={
                    "Group": "", "Scripcode": "", "industry": "",
                    "segment": "Equity", "status": status,
                })
                if r.status_code == 200 and (r.text.strip().startswith("[")):
                    data = r.json()
                    if isinstance(data, list):
                        return data
        except Exception as exc:
            logger.debug("BSE %s list fetch retry: %s", status, exc)
    return []


def run_bse_delisting_labels(database_url: str | None = None) -> dict[str, Any]:
    """Mine BSE delisted + suspended securities into ``failure_events``."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "rows_upserted": 0}

    # Ensure the labels table exists (shared with the MCA miner).
    from finagent.ikg.scrapers.failure_labels import ensure_failure_events_table

    ensure_failure_events_table(db_url)

    from finagent.ikg.entity_resolver import IKGEntityResolver, EntityLookupError

    resolver = IKGEntityResolver(db_url)
    min_sim = 0.62
    stats: dict[str, Any] = {"success": False, "rows_upserted": 0, "fetched": 0, "mapped": 0}
    try:
        from psycopg.rows import dict_row

        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                upserted = 0
                for status, event_type, confidence in _STATUS_MAP:
                    rows = fetch_status_list(status)
                    stats["fetched"] += len(rows)
                    for row in rows:
                        scrip = str(row.get("SCRIP_CD") or "").strip()
                        isin = str(row.get("ISIN_NUMBER") or "").strip().upper()
                        name = str(row.get("Issuer_Name") or row.get("Scrip_Name") or "").strip()
                        if not scrip and not isin and not name:
                            continue
                        # Resolve CIN: ISIN, then scrip, then name-trigram over the 3.1M
                        # master (delisted cos left the exchange so rarely match by ISIN/scrip).
                        cur.execute(
                            """
                            select cin from ikg_company_master
                            where (%s <> '' and upper(isin) = %s)
                               or (%s <> '' and bse_scrip_code = %s)
                            limit 1
                            """,
                            (isin, isin, scrip, scrip),
                        )
                        hit = cur.fetchone()
                        cin = (hit or {}).get("cin") if hit else None
                        if not cin and name:
                            try:
                                matches = resolver.resolve_by_name(name, limit=1)
                                if matches and matches[0].cin and float(matches[0].confidence or 0) >= min_sim:
                                    cin = matches[0].cin
                            except EntityLookupError:
                                pass
                        if not cin:
                            continue
                        stats["mapped"] += 1
                        # Proxy event date: last SHP filing for this company (when it went dark).
                        cur.execute(
                            "select max(fetched_at)::date as d from shp_raw where cin = %s",
                            (cin,),
                        )
                        drow = cur.fetchone() or {}
                        event_date = drow.get("d")
                        cur.execute(
                            """
                            insert into failure_events
                                (cin, event_type, event_subtype, event_date, is_failure,
                                 source, source_url, confidence, evidence_text, properties)
                            values (%s, %s, %s, %s, true, 'bse_delisting', %s, %s, %s,
                                    jsonb_build_object('bse_scrip', %s::text, 'isin', %s::text, 'group', %s::text))
                            on conflict (cin, event_type, source) do update set
                                event_date = excluded.event_date,
                                confidence = excluded.confidence,
                                evidence_text = excluded.evidence_text,
                                properties = excluded.properties,
                                updated_at = now()
                            """,
                            (
                                cin, event_type, status, event_date, str(row.get("NSURL") or ""),
                                confidence, str(name or "")[:200], scrip, isin, str(row.get("GROUP") or ""),
                            ),
                        )
                        upserted += cur.rowcount or 0
                    conn.commit()
                stats["rows_upserted"] = upserted
        stats["success"] = True
    except Exception as exc:
        logger.error("BSE delisting label mining failed: %s", exc)
        stats["error"] = str(exc)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json

    print(json.dumps(run_bse_delisting_labels(), default=str, indent=2))
