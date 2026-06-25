"""Exchange delisting / suspension failure-label scraper (BSE List-of-Scrips).

BSE publishes the full delisted (~4,600) and suspended (~1,200) equity lists with
ISIN. Exchange delisting *for cause* and long suspension are stronger governance-
failure signals for the listed universe than MCA strike-off (which is dominated by
tiny private shells). These map to a CIN via ISIN/scrip and become high-quality
positive labels in ``failure_events``.

The BSE ListofScripData API carries no delisting date.  ``backfill_delisting_dates``
fetches per-scrip announcement history from the BSE announcements API
(AnnSubCategoryGetData) and extracts the earliest filing whose subject line contains
a delisting keyword — that date is written back to ``failure_events.event_date``.
This replaces the shp_raw.fetched_at proxy with a real-event date (~20 day precision).

Reachable from ikg-vm (api.bseindia.com is not IP-blocked, unlike NSE).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.scrapers.bse_delisting")

_BSE_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
_BSE_ANN_URL  = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
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


_DELIST_KW_RE = re.compile(
    r"\b(delist|delisted|delisting|compulsory\s+delist|voluntary\s+delist|"
    r"exit\s+from\s+trading|suspend|suspens|trading\s+halt)\b",
    flags=re.I,
)


def _delist_date_from_announcements(scrip_code: str, *, timeout_s: float = 15.0) -> date | None:
    """Fetch BSE announcement history for a scrip and return the earliest date
    whose subject line matches a delisting/suspension keyword.

    Uses the BSE AnnSubCategoryGetData endpoint which returns all corporate
    filings for a scrip in reverse-chronological order.  We walk pages until
    we find a delisting keyword or exhaust the history.
    """
    for page in range(1, 6):  # max 5 pages (~100 filings)
        try:
            with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as c:
                r = c.get(
                    _BSE_ANN_URL,
                    headers=_BSE_HEADERS,
                    params={
                        "pageno": page,
                        "strCat": -1,
                        "strPrevDate": "19900101",
                        "strScrip": scrip_code,
                        "strSearch": "P",
                        "strToDate": "20301231",
                        "strType": "C",
                        "subcategory": -1,
                    },
                )
            if r.status_code != 200:
                break
            payload = r.json()
            rows = payload.get("Table") or payload.get("Table1") or []
            if not rows:
                break
            for row in rows:
                subject = str(row.get("NEWSSUB") or "")
                if _DELIST_KW_RE.search(subject):
                    raw_dt = str(row.get("NEWS_DT") or row.get("DT_TM") or "")
                    # Formats: "2016-02-16T16:52:53" or "2016-02-16"
                    try:
                        return date.fromisoformat(raw_dt[:10])
                    except ValueError:
                        continue
        except Exception:
            break
        time.sleep(0.2)
    return None


def backfill_delisting_dates(
    database_url: str | None = None,
    *,
    batch_size: int = 500,
    delay_s: float = 0.25,
) -> dict[str, Any]:
    """Backfill real delisting/suspension dates from BSE announcement history.

    Fetches undated ``exchange_delisting`` / ``exchange_suspension`` rows from
    ``failure_events``, resolves the BSE scrip code via ``ikg_company_master``,
    calls the announcements API per scrip, and updates ``failure_events.event_date``
    with the earliest matching filing date.

    Replaces the ``shp_raw.fetched_at`` proxy with a real event date so the
    temporal backtest can measure lead-time between governance flags and the
    actual delisting event.
    """
    from finagent.ikg.db import connect_postgres, get_database_url
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "updated": 0}

    from psycopg.rows import dict_row

    stats: dict[str, Any] = {"success": False, "updated": 0, "skipped": 0, "errors": 0,
                              "already_dated": 0}
    try:
        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                # Fetch undated delisting / suspension rows with their BSE scrip code
                cur.execute(
                    """
                    select fe.id, fe.cin, fe.event_type,
                           m.bse_scrip_code
                    from failure_events fe
                    join ikg_company_master m using (cin)
                    where fe.event_type in ('exchange_delisting', 'exchange_suspension')
                      and fe.event_date is null
                      and m.bse_scrip_code is not null
                      and m.bse_scrip_code <> ''
                    order by fe.id
                    limit %s
                    """,
                    (batch_size,),
                )
                rows = cur.fetchall()
                logger.info("backfill_delisting_dates: %d undated rows to process", len(rows))

                for row in rows:
                    scrip = str(row["bse_scrip_code"]).strip()
                    if not scrip:
                        stats["skipped"] += 1
                        continue
                    try:
                        event_date = _delist_date_from_announcements(scrip)
                    except Exception as exc:
                        logger.debug("scrip %s announcement fetch failed: %s", scrip, exc)
                        stats["errors"] += 1
                        continue
                    if event_date is None:
                        stats["skipped"] += 1
                        continue
                    cur.execute(
                        "UPDATE failure_events SET event_date = %s, updated_at = now() WHERE id = %s",
                        (event_date, row["id"]),
                    )
                    stats["updated"] += 1
                    time.sleep(delay_s)

                conn.commit()

                # Count remaining undated after this run
                cur.execute(
                    "SELECT count(1) FROM failure_events "
                    "WHERE event_type IN ('exchange_delisting','exchange_suspension') AND event_date IS NULL"
                )
                stats["remaining_undated"] = cur.fetchone()[0]

        stats["success"] = True
    except Exception as exc:
        logger.error("backfill_delisting_dates failed: %s", exc)
        stats["error"] = str(exc)
    return stats



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
