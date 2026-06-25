"""Table-backed earnings API service with deterministic local fallbacks."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from finagent.earnings.analysis import (
    TIMING_LABELS,
    build_ai_highlights,
    build_financial_comparison_rows,
    compact_summary,
    fiscal_quarter_from_date,
    infer_call_timing,
    infer_quarter_ref,
    parse_date,
    stable_event_uid,
)
from finagent.earnings.universe import earnings_universe_sql_filter
from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.earnings.service")


_EARNINGS_BOOTSTRAP_SQL = """
create table if not exists earnings_announcements (
    id                  bigserial primary key,
    event_uid           text not null unique,
    exchange            varchar(20) not null,
    source_uid          text,
    symbol              varchar(20),
    isin                varchar(12),
    bse_scrip_code      varchar(10),
    company_name        text not null,
    sector              text,
    index_bucket        varchar(40) default 'All',
    market_cap_bucket   varchar(40) default 'All',
    announcement_type   text,
    category            text,
    title               text,
    summary             text,
    meeting_date        date not null,
    announced_at        timestamptz,
    quarter_ref         varchar(40),
    timing              varchar(40),
    attachment_urls     jsonb default '[]'::jsonb,
    storage_paths       jsonb default '[]'::jsonb,
    raw_json            jsonb default '{}'::jsonb,
    processing_status   varchar(40) default 'pending',
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);
create index if not exists idx_earnings_announcements_date
    on earnings_announcements(meeting_date, symbol);
create index if not exists idx_earnings_announcements_symbol
    on earnings_announcements(symbol, meeting_date desc);
create index if not exists idx_earnings_announcements_filters
    on earnings_announcements(index_bucket, market_cap_bucket, sector);

create table if not exists earnings_details (
    id                      bigserial primary key,
    event_uid               text not null unique references earnings_announcements(event_uid) on delete cascade,
    symbol                  varchar(20) not null,
    company_name            text not null,
    meeting_date            date not null,
    fiscal_quarter          varchar(40),
    timing                  varchar(40),
    highlights_json         jsonb default '[]'::jsonb,
    management_json         jsonb default '[]'::jsonb,
    transcript_json         jsonb default '{}'::jsonb,
    documents_json          jsonb default '[]'::jsonb,
    financials_json         jsonb default '{}'::jsonb,
    text_excerpt            text,
    parser_version          varchar(80),
    updated_at              timestamptz default now()
);
create index if not exists idx_earnings_details_symbol_date
    on earnings_details(symbol, meeting_date desc);
"""

_BOOTSTRAPPED: set[str] = set()
_DB_DOWN_UNTIL = 0.0
_DB_COOLDOWN_S = 15.0
_READ_LOCK_TIMEOUT_MS = "2000"
_READ_STATEMENT_TIMEOUT_MS = "12000"
_READ_CONNECT_TIMEOUT_S = 8

# Simple in-memory cache for calendar queries to reduce DB pressure
_CALENDAR_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CALENDAR_CACHE_TTL_S = 60.0  # Cache calendar results for 1 minute

# Simple in-memory cache for company range queries (overview pulse)
_COMPANIES_CACHE: dict[str, tuple[float, tuple[list[dict[str, Any]], int]]] = {}
_COMPANIES_CACHE_TTL_S = 60.0  # Cache company results for 1 minute


def _db_circuit_open() -> bool:
    return time.monotonic() < _DB_DOWN_UNTIL


def _trip_db_circuit() -> None:
    global _DB_DOWN_UNTIL
    _DB_DOWN_UNTIL = time.monotonic() + _DB_COOLDOWN_S


def _reset_db_circuit() -> None:
    global _DB_DOWN_UNTIL
    _DB_DOWN_UNTIL = 0.0


def _enable_local_earnings_fallback() -> bool:
    return os.getenv("PROSPEKTLAB_ENV") != "production"


def _configure_read_timeouts(cur: Any) -> None:
    try:
        # Use SET LOCAL so settings apply to the current transaction only.
        # This is compatible with PgBouncer transaction-mode pooling where
        # session-level set_config() values can bleed across pooled connections.
        cur.execute(f"SET LOCAL lock_timeout = '{_READ_LOCK_TIMEOUT_MS}ms'")
        cur.execute(f"SET LOCAL statement_timeout = '{_READ_STATEMENT_TIMEOUT_MS}ms'")
    except Exception as exc:  # noqa: BLE001
        logger.debug("earnings read timeout configuration skipped: %s", exc)


def _probe_earnings_tables(db_url: str) -> bool:
    if _db_circuit_open():
        return False
    if db_url in _BOOTSTRAPPED:
        return True
    try:
        with connect_postgres(db_url, connect_timeout=_READ_CONNECT_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                _configure_read_timeouts(cur)
                cur.execute(
                    """
                    select
                      to_regclass('public.earnings_announcements') is not null
                      and to_regclass('public.earnings_details') is not null
                    """
                )
                row = cur.fetchone()
        ready = bool(row[0]) if row else False
        if ready:
            _BOOTSTRAPPED.add(db_url)
            _reset_db_circuit()
        return ready
    except Exception as exc:  # noqa: BLE001
        logger.debug("earnings table probe failed: %s", exc)
        _trip_db_circuit()
        return False


def ensure_earnings_tables(database_url: str | None = None) -> bool:
    db_url = get_database_url(database_url)
    if not db_url:
        return False
    if _db_circuit_open():
        return False
    if db_url in _BOOTSTRAPPED:
        return True
    try:
        with connect_postgres(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(_EARNINGS_BOOTSTRAP_SQL)
            conn.commit()
        _BOOTSTRAPPED.add(db_url)
        _reset_db_circuit()
        # Also run extended schema migrations right after base tables succeed
        # (idempotent - uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)
        try:
            with connect_postgres(db_url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(_EARNINGS_EXTENDED_BOOTSTRAP_SQL)
                conn.commit()
            _EXTENDED_BOOTSTRAPPED.add(f"ext:{db_url}")
        except Exception as ext_exc:
            logger.debug("extended earnings table bootstrap skipped: %s", ext_exc)
        
        # Run startup backfill in background thread so it doesn't block server startup
        try:
            import threading
            from finagent.earnings.scraper import check_and_backfill_if_needed
            thread = threading.Thread(
                target=check_and_backfill_if_needed,
                daemon=True,
                name="earnings-backfill",
            )
            thread.start()
        except Exception as backfill_exc:
            logger.debug("startup backfill trigger failed (non-fatal): %s", backfill_exc)
        
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("earnings table bootstrap failed: %s", exc)
        _trip_db_circuit()
        return False


def get_earnings_overview(start_date: str, end_date: str, page_size: int = 50) -> dict[str, Any]:
    """Combined calendar + companies fetch using a single DB connection.
    
    This avoids the overhead of opening 2 separate connections to the remote
    database, which was causing timeouts on the overview Earnings Pulse section.
    """
    start = parse_date(start_date) or date.today() - timedelta(days=7)
    end = parse_date(end_date) or start + timedelta(days=30)
    if end < start:
        start, end = end, start

    # Check both caches first
    cal_cache_key = f"{start.isoformat()}:{end.isoformat()}"
    comp_cache_key = f"{start.isoformat()}:{end.isoformat()}:1:{page_size}"
    
    cal_cached = _CALENDAR_CACHE.get(cal_cache_key)
    comp_cached = _COMPANIES_CACHE.get(comp_cache_key)
    
    cal_rows = None
    comp_result = None
    
    if cal_cached:
        cached_at, cached_rows = cal_cached
        if time.monotonic() - cached_at < _CALENDAR_CACHE_TTL_S:
            cal_rows = cached_rows
    
    if comp_cached:
        cached_at, cached_result = comp_cached
        if time.monotonic() - cached_at < _COMPANIES_CACHE_TTL_S:
            comp_result = cached_result
    
    # If both are cached, return immediately
    if cal_rows is not None and comp_result is not None:
        cal_response = _build_calendar_response(start, end, cal_rows)
        comp_rows, comp_total = comp_result
        return {
            "calendar": cal_response,
            "companies": {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "mode": "range",
                "page": 1,
                "page_size": page_size,
                "total": comp_total,
                "items": comp_rows,
            },
        }
    
    # Fetch both in a single DB connection
    if not _query_available():
        # Fallback to demo data
        cal_rows_raw = _demo_calendar_rows(start, end) if _enable_local_earnings_fallback() else []
        cal_response = _build_calendar_response(start, end, cal_rows_raw)
        return {
            "calendar": cal_response,
            "companies": {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "mode": "range",
                "page": 1,
                "page_size": page_size,
                "total": 0,
                "items": [],
            },
        }
    
    universe_sql, universe_params = earnings_universe_sql_filter("a")
    where_sql = "a.meeting_date between %s and %s"
    params: list[Any] = [start, end]
    if universe_sql:
        where_sql += f" and {universe_sql}"
        params.extend(universe_params)
    
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=_READ_CONNECT_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                _configure_read_timeouts(cur)
                
                # Calendar query
                cur.execute(
                    f"""
                    with base as (
                      select a.meeting_date, a.sector, coalesce(a.timing, 'TAS') as timing
                      from earnings_announcements a
                      where {where_sql}
                    ), timing_counts as (
                      select meeting_date, timing, count(*)::int as company_count
                      from base
                      group by meeting_date, timing
                    ), timing_json as (
                      select meeting_date, jsonb_object_agg(timing, company_count) as timings
                      from timing_counts
                      group by meeting_date
                    ), day_rows as (
                      select
                        meeting_date,
                        meeting_date::text as date,
                        count(*)::int as company_count,
                        array_remove(array_agg(distinct sector), null) as sectors
                      from base
                      group by meeting_date
                    )
                    select d.date, d.company_count, d.sectors, coalesce(t.timings, '{{}}'::jsonb) as timings
                    from day_rows d
                    left join timing_json t on t.meeting_date = d.meeting_date
                    order by d.meeting_date
                    """,
                    params,
                )
                cal_rows_raw = [dict(row) for row in cur.fetchall()]
                
                # Companies query (same connection)
                cur.execute(
                    f"select count(*) as total from earnings_announcements a where {where_sql}",
                    params,
                )
                comp_total = int((cur.fetchone() or {}).get("total") or 0)
                
                cur.execute(
                    f"""
                    select
                      a.event_uid,
                      a.symbol,
                      a.company_name as name,
                      a.sector,
                      a.index_bucket,
                      a.market_cap_bucket,
                      a.meeting_date::text as date,
                      coalesce(d.timing, a.timing, 'TAS') as timing,
                      coalesce(d.fiscal_quarter, a.quarter_ref, '') as fiscal_quarter,
                      coalesce(d.highlights_json, '[]'::jsonb) as highlights,
                      a.attachment_urls,
                      a.summary,
                      h.actual_eps,
                      h.estimated_eps,
                      h.surprise_eps_pct,
                      h.post_earnings_move_1d,
                      h.actual_revenue,
                      h.surprise_revenue_pct,
                      (select (fin->>'yoy_pct')::numeric
                         from jsonb_array_elements(coalesce(d.financials_json->'rows', '[]'::jsonb)) fin
                         where fin->>'key' = 'revenue' limit 1) as revenue_yoy_pct,
                      (select (fin->>'yoy_pct')::numeric
                         from jsonb_array_elements(coalesce(d.financials_json->'rows', '[]'::jsonb)) fin
                         where fin->>'key' = 'pat' limit 1) as pat_yoy_pct
                    from earnings_announcements a
                    left join earnings_details d on d.event_uid = a.event_uid
                    left join earnings_history h on
                      h.symbol = a.symbol
                      and h.earnings_date >= a.meeting_date::timestamptz
                      and h.earnings_date < (a.meeting_date + interval '1 day')::timestamptz
                    where {where_sql}
                    order by a.meeting_date desc, a.company_name
                    limit %s offset %s
                    """,
                    [*params, page_size, 0],
                )
                comp_rows = [_company_row_from_db(dict(row)) for row in cur.fetchall()]
        
        # Process calendar rows
        for row in cal_rows_raw:
            row["summary"] = f"{row.get('company_count', 0)} earnings call(s)"
            row["sectors"] = list(row.get("sectors") or [])
            row["timings"] = dict(row.get("timings") or {})
        
        # Cache both results
        _CALENDAR_CACHE[cal_cache_key] = (time.monotonic(), cal_rows_raw)
        _COMPANIES_CACHE[comp_cache_key] = (time.monotonic(), (comp_rows, comp_total))
        
        cal_response = _build_calendar_response(start, end, cal_rows_raw)
        return {
            "calendar": cal_response,
            "companies": {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "mode": "range",
                "page": 1,
                "page_size": page_size,
                "total": comp_total,
                "items": comp_rows,
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("earnings overview query failed: %s", exc)
        _trip_db_circuit()
        # Return empty but valid response
        cal_response = _build_calendar_response(start, end, [])
        return {
            "calendar": cal_response,
            "companies": {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "mode": "range",
                "page": 1,
                "page_size": page_size,
                "total": 0,
                "items": [],
            },
        }


def _build_calendar_response(start: date, end: date, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the standard calendar response dict from processed rows."""
    by_date = {str(row["date"]): row for row in rows}
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "dates": [
            by_date.get(
                (start + timedelta(days=offset)).isoformat(),
                {
                    "date": (start + timedelta(days=offset)).isoformat(),
                    "company_count": 0,
                    "summary": "",
                    "sectors": [],
                    "timings": {},
                },
            )
            for offset in range((end - start).days + 1)
        ],
        "source": "postgres" if rows else "empty",
    }


def get_earnings_calendar(start_date: str, end_date: str) -> dict[str, Any]:
    start = parse_date(start_date) or date.today() - timedelta(days=7)
    end = parse_date(end_date) or start + timedelta(days=30)
    if end < start:
        start, end = end, start

    rows = _query_calendar_rows(start, end)
    source = "postgres"
    if rows is None:
        rows = _demo_calendar_rows(start, end) if _enable_local_earnings_fallback() else []
        source = "demo" if rows else "empty"

    by_date = {
        str(row["date"]): row
        for row in rows
    }
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "dates": [
            by_date.get(
                (start + timedelta(days=offset)).isoformat(),
                {
                    "date": (start + timedelta(days=offset)).isoformat(),
                    "company_count": 0,
                    "summary": "",
                    "sectors": [],
                    "timings": {},
                },
            )
            for offset in range((end - start).days + 1)
        ],
        "source": source,
    }


def get_earnings_companies(
    *,
    target_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    index: str = "All",
    market_cap: str = "All",
    sector: str = "All",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Return companies for a single date, or across a date range if start_date+end_date are provided."""
    selected = parse_date(target_date) or date.today()
    range_start = parse_date(start_date)
    range_end = parse_date(end_date)

    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 25)))

    if range_start and range_end:
        if range_end < range_start:
            range_start, range_end = range_end, range_start
        range_result = _query_company_rows_range(
            range_start,
            range_end,
            index_filter=index,
            market_cap_filter=market_cap,
            sector_filter=sector,
            page=page,
            page_size=page_size,
        )
        if range_result is None:
            demo_rows = _demo_company_rows_range(
                range_start,
                range_end,
                index_filter=index,
                market_cap_filter=market_cap,
                sector_filter=sector,
            ) if _enable_local_earnings_fallback() else []
            total = len(demo_rows)
            start_idx = (page - 1) * page_size
            rows = demo_rows[start_idx:start_idx + page_size]
        else:
            rows, total = range_result
        return {
            "start_date": range_start.isoformat(),
            "end_date": range_end.isoformat(),
            "mode": "range",
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": rows,
        }

    single_result = _query_company_rows(
        selected,
        index_filter=index,
        market_cap_filter=market_cap,
        sector_filter=sector,
        page=page,
        page_size=page_size,
    )
    if single_result is None:
        demo_rows = _filter_company_rows(_demo_companies_for_date(selected), index, market_cap, sector) if _enable_local_earnings_fallback() else []
        total = len(demo_rows)
        start_idx = (page - 1) * page_size
        rows = demo_rows[start_idx:start_idx + page_size]
    else:
        rows, total = single_result

    return {
        "date": selected.isoformat(),
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


def get_earnings_detail(symbol: str, target_date: str | None = None) -> dict[str, Any] | None:
    clean_symbol = str(symbol or "").strip().upper()
    if not clean_symbol:
        return None
    selected = parse_date(target_date) if target_date else None
    row = _query_detail_row(clean_symbol, selected)
    if row:
        return row
    if selected:
        return _query_announcement_detail_row(clean_symbol, selected)
    return None


def get_earnings_result(symbol: str, target_date: str) -> dict[str, Any] | None:
    """Fetch complete result detail for a past earnings announcement.
    
    Returns dict with:
      - symbol, name, sector, fiscal_quarter, timing, meeting_date, current_price
      - quarter_tabs: last 8 quarters with labels, move_1d_pct, is_current
      - revenue: {actual, estimated, beat_miss_pct}
      - eps: {actual, estimated, beat_miss_pct}
      - move_1d: {pct, pre_close, post_close}
      - highlights: list of bullet points
      - ai_summary: LLM-generated structured intelligence (if available)
      - transcript: {prepared_remarks, qa}
      - documents: list with type/title/url
      - financials: {rows: [{key, label, unit, current, previous_quarter, same_quarter_last_year, qoq_pct, yoy_pct}]}
    """
    clean_symbol = str(symbol or "").strip().upper()
    selected = parse_date(target_date)
    if not clean_symbol or not selected:
        return None
    
    # Get announcement + detail data from DB in one query for a fast click path.
    detail_row = _query_result_detail_row(clean_symbol, selected)
    if not detail_row:
        return None  # No announcement or parsed detail available

    # If only the announcement fallback exists (no parsed PDF detail), trigger a
    # synchronous parse of the outcome PDF so the first click returns real data.
    if detail_row.get("source") == "announcement_fallback":
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(ensure_earnings_detail_for_result, clean_symbol, target_date)
                # Wait up to 45 seconds for the parse. Azure DI can be slow for
                # complex results PDFs, but most complete within 10-30s.
                parse_result = future.result(timeout=45)
                if parse_result.get("stored"):
                    # Re-query so the rest of this function uses the parsed detail
                    refreshed = _query_result_detail_row(clean_symbol, selected)
                    if refreshed:
                        detail_row = refreshed
        except Exception as sync_exc:
            logger.debug("Synchronous detail parse failed/timed out for %s %s: %s", clean_symbol, selected, sync_exc)

    current_price = None
    
    # Build metrics rows: revenue, EPS, margins from earnings_details + Yahoo
    revenue_actual = None
    revenue_estimated = None
    revenue_beat_miss = None
    eps_actual = None
    eps_estimated = None
    eps_beat_miss = None
    move_1d_pct = None
    pre_close = None
    post_close = None
    
    try:
        # Query Yahoo-sourced history for this quarter's EPS/revenue estimates + 1D move
        history_for_quarter = _query_earnings_history_for_date(clean_symbol, selected)
        if history_for_quarter:
            h = history_for_quarter
            eps_actual = h.get("actual_eps")
            eps_estimated = h.get("estimated_eps")
            eps_beat_miss = h.get("surprise_eps_pct")
            revenue_actual = h.get("actual_revenue")
            revenue_estimated = h.get("estimated_revenue")
            revenue_beat_miss = h.get("surprise_revenue_pct")
            move_1d_pct = h.get("post_earnings_move_1d")
            pre_close = h.get("pre_close")
            post_close = h.get("post_close")
    except Exception:
        pass
    
    # Fetch financial comparison rows from stored parser payload
    financials_payload = _financials_payload(detail_row.get("financials") or detail_row.get("financials_json") or {})

    # NOTE: XBRL unit correction and historical-QoQ/YoY lookups are intentionally
    # performed once at parse/storage time (ensure_earnings_detail_for_result),
    # not on every GET. This keeps the earnings result endpoint fast and avoids
    # NSE network timeouts in the hot path.

    # Enrich QoQ/YoY: if rows exist but have no QoQ/YoY, query historical quarters and rebuild
    try:
        rows = financials_payload.get("rows") or []
        has_current = any(r.get("current") is not None for r in rows)
        has_qoq = any(r.get("qoq_pct") is not None for r in rows)
        if has_current and not has_qoq:
            prev_metrics, yoy_metrics = _query_historical_metrics(clean_symbol, selected)
            if prev_metrics or yoy_metrics:
                # Use stored direct metrics when available (more complete than row extraction)
                stored_metrics = _dict_json(financials_payload.get("metrics") or {})
                current_m: dict[str, Any] = {k: v for k, v in stored_metrics.items() if v is not None}
                # Supplement from rows
                for r in rows:
                    if r.get("key") and r.get("current") is not None and r["key"] not in current_m:
                        current_m[r["key"]] = r["current"]
                if current_m:
                    rebuilt = build_financial_comparison_rows(current_m, prev_metrics, yoy_metrics)
                    financials_payload["rows"] = rebuilt
    except Exception as qoq_exc:
        logger.debug("QoQ/YoY enrichment failed for %s: %s", clean_symbol, qoq_exc)

    # Assemble highlights from detail row or generate from summary
    highlights = []
    try:
        highlights = _highlight_items(detail_row.get("headline_highlights") or detail_row.get("highlights_json") or [])
    except Exception:
        pass
    if not highlights:
        try:
            highlights = build_ai_highlights(detail_row.get("summary") or "", source_url="")
        except Exception:
            pass
    
    # Transcript
    transcript = {}
    try:
        transcript = _transcript_payload(detail_row.get("transcript") or {})
    except Exception:
        pass
    
    # Documents
    documents = []
    try:
        documents = _document_items(detail_row.get("documents") or [], detail_row.get("attachment_urls") or [])
    except Exception:
        pass

    # Quarter tabs: real 8-quarter timeline
    quarter_tabs: list[dict[str, Any]] = []
    try:
        quarter_tabs = _query_quarter_tabs(clean_symbol, selected)
    except Exception as qt_exc:
        logger.debug("quarter_tabs query failed for %s: %s", clean_symbol, qt_exc)

    # AI summary: use stored value if available
    ai_summary: dict[str, Any] | None = detail_row.get("ai_summary") or None
    if not ai_summary:
        ai_summary = None
    
    return {
        "symbol": clean_symbol,
        "name": detail_row.get("name") or clean_symbol,
        "sector": detail_row.get("sector") or "Other",
        "fiscal_quarter": detail_row.get("fiscal_quarter") or "",
        "timing": detail_row.get("timing") or "TAS",
        "meeting_date": detail_row.get("date") or selected.isoformat(),
        "current_price": current_price,
        "quarter_tabs": quarter_tabs,
        "revenue": {
            "actual": revenue_actual,
            "estimated": revenue_estimated,
            "beat_miss_pct": revenue_beat_miss,
        },
        "eps": {
            "actual": eps_actual,
            "estimated": eps_estimated,
            "beat_miss_pct": eps_beat_miss,
        },
        "move_1d": {
            "pct": move_1d_pct,
            "pre_close": pre_close,
            "post_close": post_close,
        },
        "highlights": highlights[:5],
        "ai_summary": ai_summary,
        "transcript": transcript,
        "documents": documents,
        "financials": financials_payload,
    }


def _is_recent_processing(record: dict[str, Any], *, max_age_minutes: int = 15) -> bool:
    updated = record.get("updated_at")
    if isinstance(updated, datetime):
        updated_at = updated
    elif isinstance(updated, str) and updated.strip():
        raw = updated.strip()
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            updated_at = datetime.fromisoformat(raw)
        except ValueError:
            return False
    else:
        return False

    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)
    return age < timedelta(minutes=max_age_minutes)


def ensure_earnings_detail_for_result(symbol: str, target_date: str, *, generate_ai_summary: bool = True) -> dict[str, Any]:
    """Parse and store missing earnings detail for an announced result.

    This is intended for background execution after the result endpoint returns.
    It keeps the UI fast while still filling earnings_details from the official
    filing when an announcement exists but parsed detail does not.

    ``generate_ai_summary`` defaults to True so detail pages are complete. Bulk
    pre-parse jobs can set it to False to save time because summaries are optional.
    """
    clean_symbol = str(symbol or "").strip().upper()
    selected = parse_date(target_date)
    if not clean_symbol or not selected:
        return {"stored": False, "reason": "invalid_input"}
    if _query_detail_row(clean_symbol, selected):
        return {"stored": False, "reason": "detail_exists"}

    record = _query_announcement_record_for_parse(clean_symbol, selected)
    if not record:
        return {"stored": False, "reason": "announcement_missing"}
    if str(record.get("processing_status") or "").lower() == "parsing" and _is_recent_processing(record):
        return {"stored": False, "reason": "already_parsing"}

    event_uid = str(record.get("event_uid") or "")
    _set_announcement_processing_status(event_uid, "parsing")
    try:
        from finagent.earnings.scraper import build_detail_from_announcement, _fetch_outcome_urls_from_nse, _fetch_outcome_urls_from_bse

        # Pre-enrich attachment_urls with outcome docs from exchange APIs.
        # Stored URLs are often pre-meeting intimation-only (from corporate-board-meetings API).
        # Fetching from corporate-announcements gives us post-meeting result PDFs.
        if selected:
            try:
                outcome_urls = _fetch_outcome_urls_from_nse(clean_symbol, selected)
                if not outcome_urls:
                    outcome_urls = _fetch_outcome_urls_from_bse(clean_symbol, selected)
                if outcome_urls:
                    # Prepend outcome URLs to existing list; parser will try these first
                    existing = list(record.get("attachment_urls") or [])
                    merged = list(dict.fromkeys(outcome_urls + existing))  # outcome first, deduped
                    record = {**record, "attachment_urls": merged}
                    logger.debug(
                        "Pre-enriched %s %s with %d outcome URL(s) from exchange APIs",
                        clean_symbol, selected, len(outcome_urls),
                    )
            except Exception as re_exc:
                logger.debug("Outcome URL pre-fetch failed for %s: %s", clean_symbol, re_exc)

        detail = build_detail_from_announcement(record)
        if detail:
            # Apply XBRL unit correction once at parse time so stored metrics are
            # already scaled correctly. This removes the expensive NSE call from the
            # GET /result hot path.
            try:
                financials = detail.get("financials") or {}
                corrected = _apply_xbrl_unit_correction(
                    clean_symbol,
                    _financials_payload(financials),
                )
                if corrected:
                    detail["financials"] = corrected
            except Exception as uc_exc:
                logger.debug("XBRL unit correction at parse time failed for %s: %s", clean_symbol, uc_exc)

        if detail and upsert_detail(detail):
            _set_announcement_processing_status(event_uid, "parsed")
            # Generate and store AI summary (non-fatal if LLM unavailable)
            if generate_ai_summary:
                try:
                    text_excerpt = detail.get("text_excerpt") or ""
                    if text_excerpt and len(text_excerpt) > 200:
                        fin = detail.get("financials") or {}
                        ai_summary = _generate_ai_summary(
                            text_excerpt=text_excerpt,
                            metrics=fin.get("metrics") or {},
                            company_name=str(record.get("company_name") or clean_symbol),
                            symbol=clean_symbol,
                            fiscal_quarter=str(detail.get("fiscal_quarter") or record.get("quarter_ref") or ""),
                            meeting_date=str(record.get("meeting_date") or ""),
                        )
                        if ai_summary:
                            _store_ai_summary(event_uid, ai_summary)
                except Exception as ai_exc:
                    logger.debug("AI summary generation skipped for %s: %s", clean_symbol, ai_exc)
            return {"stored": True, "event_uid": event_uid}
        _set_announcement_processing_status(event_uid, "parse_empty")
        return {"stored": False, "reason": "parse_empty", "event_uid": event_uid}
    except Exception as exc:  # noqa: BLE001
        logger.warning("on-demand earnings detail parse failed for %s %s: %s", clean_symbol, selected, exc)
        _set_announcement_processing_status(event_uid, "parse_failed")
        return {"stored": False, "reason": "parse_failed", "event_uid": event_uid, "error": str(exc)}

def preparse_earnings_last_30_days() -> dict[str, Any]:
    """Pre-parse earnings details for all companies in the last 30 days.

    Called once on server startup in a background thread. This warms the cache
    so users don't have to wait for the first PDF parse when opening a detail page.
    """
    return preparse_earnings_range(start_date=date.today() - timedelta(days=30))


def preparse_earnings_current_year() -> dict[str, Any]:
    """Pre-parse earnings details for all past companies in the current year.

    Called once on server startup in a background thread. This warms the cache
    for every company that has already announced in the current year, so detail pages
    resolve instantly with complete data.
    """
    today = date.today()
    return preparse_earnings_range(start_date=date(today.year, 1, 1))


def preparse_earnings_range(
    start_date: date | None = None,
    limit: int | None = None,
    max_workers: int = 1,
) -> dict[str, Any]:
    """Pre-parse earnings details for all companies in the given range.

    Defaults to the current year. It skips records that already have a detail row
    and only processes past dates so we don't block on future board meetings.
    When ``limit`` is provided, only that many records are processed in one call
    so the function can be scheduled repeatedly to drain the backlog.
    """
    from datetime import date
    from concurrent.futures import ThreadPoolExecutor, as_completed

    today = date.today()
    start = start_date or date(today.year, 1, 1)
    url = get_database_url()
    if not url:
        return {"success": False, "reason": "no_database_url"}
    try:
        with connect_postgres(connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.symbol, a.meeting_date
                    FROM earnings_announcements a
                    WHERE a.meeting_date >= %s AND a.meeting_date < CURRENT_DATE
                      AND NOT EXISTS (
                          SELECT 1 FROM earnings_details d
                          WHERE d.event_uid = a.event_uid
                      )
                      AND COALESCE(a.processing_status, 'pending') NOT IN ('parsing', 'parse_failed')
                    ORDER BY a.meeting_date DESC, a.symbol
                    LIMIT %s
                    """,
                    (start, limit or 1000000),
                )
                rows = cur.fetchall()
        if not rows:
            return {"success": True, "parsed": 0, "reason": "no_records"}

        logger.info("Pre-parsing earnings details for %d companies (%s onwards)", len(rows), start)
        parsed = 0
        failed = 0

        def _process(symbol: str, meeting_date: Any) -> bool:
            try:
                result = ensure_earnings_detail_for_result(
                    symbol, str(meeting_date), generate_ai_summary=False
                )
                if result.get("stored") or result.get("reason") == "detail_exists":
                    return True
                return False
            except Exception as exc:
                logger.debug("Pre-parse failed for %s %s: %s", symbol, meeting_date, exc)
                return False

        if max_workers <= 1:
            for symbol, meeting_date in rows:
                if _process(symbol, meeting_date):
                    parsed += 1
                else:
                    failed += 1
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_process, symbol, meeting_date): (symbol, meeting_date)
                    for symbol, meeting_date in rows
                }
                for future in as_completed(futures):
                    if future.result():
                        parsed += 1
                    else:
                        failed += 1

        logger.info("Pre-parsing completed: parsed=%s, failed=%s", parsed, failed)
        return {"success": True, "parsed": parsed, "failed": failed, "total": len(rows)}
    except Exception as exc:
        logger.warning("Pre-parse earnings range failed: %s", exc)
        return {"success": False, "reason": str(exc)}


def get_earnings_stats(target_date: str) -> dict[str, Any]:
    selected = parse_date(target_date) or date.today()
    rows = _query_stats_rows(selected)
    if rows is None:
        rows = _demo_stats_rows(selected) if _enable_local_earnings_fallback() else []

    by_timing: dict[str, int] = {label: 0 for label in TIMING_LABELS}
    by_sector: dict[str, int] = {}
    for row in rows:
        timing = str(row.get("timing") or "TAS")
        sector = str(row.get("sector") or "Other")
        count = int(row.get("company_count") or 0)
        by_timing[timing] = by_timing.get(timing, 0) + count
        by_sector[sector] = by_sector.get(sector, 0) + count
    return {
        "date": selected.isoformat(),
        "timing": [{"label": key, "count": value} for key, value in by_timing.items()],
        "sector": [
            {"label": key, "count": value}
            for key, value in sorted(by_sector.items(), key=lambda item: item[1], reverse=True)
        ],
        "total": sum(by_timing.values()),
    }


def upsert_announcement(record: dict[str, Any], database_url: str | None = None) -> bool:
    db_url = get_database_url(database_url)
    if not db_url or not ensure_earnings_tables(db_url):
        return False
    meeting_date = parse_date(record.get("meeting_date") or record.get("announced_at")) or date.today()
    announced_at = record.get("announced_at")
    symbol = str(record.get("symbol") or "").strip().upper()
    event_uid = str(record.get("event_uid") or "").strip() or stable_event_uid(
        record.get("exchange"),
        symbol,
        record.get("title"),
        meeting_date,
        record.get("attachment_urls"),
    )
    title = str(record.get("title") or record.get("announcement_type") or "Earnings announcement").strip()
    summary = str(record.get("summary") or compact_summary(title, 180)).strip()
    quarter = str(record.get("quarter_ref") or "").strip() or infer_quarter_ref(title, meeting_date)
    timing = str(record.get("timing") or "").strip() or infer_call_timing(title, None)
    try:
        with connect_postgres(db_url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into earnings_announcements (
                      event_uid, exchange, source_uid, symbol, isin, bse_scrip_code,
                      company_name, sector, index_bucket, market_cap_bucket,
                      announcement_type, category, title, summary, meeting_date,
                      announced_at, quarter_ref, timing, attachment_urls,
                      storage_paths, raw_json, processing_status, updated_at
                    )
                    values (
                      %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s::jsonb,
                      %s::jsonb, %s::jsonb, %s, now()
                    )
                    on conflict (event_uid) do update set
                      symbol = excluded.symbol,
                      company_name = excluded.company_name,
                      sector = excluded.sector,
                      index_bucket = excluded.index_bucket,
                      market_cap_bucket = excluded.market_cap_bucket,
                      title = excluded.title,
                      summary = excluded.summary,
                      meeting_date = excluded.meeting_date,
                      announced_at = excluded.announced_at,
                      quarter_ref = excluded.quarter_ref,
                      timing = excluded.timing,
                      attachment_urls = excluded.attachment_urls,
                      storage_paths = excluded.storage_paths,
                      raw_json = excluded.raw_json,
                      processing_status = excluded.processing_status,
                      updated_at = now()
                    """,
                    (
                        event_uid,
                        str(record.get("exchange") or "NSE").upper(),
                        str(record.get("source_uid") or ""),
                        symbol,
                        str(record.get("isin") or ""),
                        str(record.get("bse_scrip_code") or ""),
                        str(record.get("company_name") or symbol or "Unknown company"),
                        str(record.get("sector") or "Other"),
                        str(record.get("index_bucket") or "All"),
                        str(record.get("market_cap_bucket") or "All"),
                        str(record.get("announcement_type") or ""),
                        str(record.get("category") or ""),
                        title,
                        summary,
                        meeting_date,
                        announced_at,
                        quarter,
                        timing,
                        json.dumps(record.get("attachment_urls") or []),
                        json.dumps(record.get("storage_paths") or []),
                        json.dumps(record.get("raw_json") or {}),
                        str(record.get("processing_status") or "pending"),
                    ),
                )
            conn.commit()
        record["event_uid"] = event_uid
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("earnings announcement upsert failed for %s: %s", symbol, exc)
        return False


def batch_upsert_announcements(records: list[dict[str, Any]], database_url: str | None = None) -> int:
    """Bulk-upsert many announcements in a single transaction. Returns count of rows processed."""
    if not records:
        return 0
    db_url = get_database_url(database_url)
    if not db_url or not ensure_earnings_tables(db_url):
        return 0

    rows_to_insert: list[tuple] = []
    for record in records:
        meeting_date = parse_date(record.get("meeting_date") or record.get("announced_at")) or date.today()
        symbol = str(record.get("symbol") or "").strip().upper()
        title = str(record.get("title") or record.get("announcement_type") or "Earnings announcement").strip()
        summary = str(record.get("summary") or compact_summary(title, 180)).strip()
        quarter = str(record.get("quarter_ref") or "").strip() or infer_quarter_ref(title, meeting_date)
        timing = str(record.get("timing") or "").strip() or infer_call_timing(title, None)
        event_uid = str(record.get("event_uid") or "").strip() or stable_event_uid(
            record.get("exchange"), symbol, title, meeting_date, record.get("attachment_urls"),
        )
        record["event_uid"] = event_uid
        # Normalise sector: treat empty/"None"/"-" as empty string (service normalizes to "Other")
        sector_raw = str(record.get("sector") or "").strip()
        sector = sector_raw if sector_raw and sector_raw not in ("-", "None") else ""
        rows_to_insert.append((
            event_uid,
            str(record.get("exchange") or "NSE").upper(),
            str(record.get("source_uid") or ""),
            symbol,
            str(record.get("isin") or ""),
            str(record.get("bse_scrip_code") or ""),
            str(record.get("company_name") or symbol or "Unknown company"),
            sector,
            str(record.get("index_bucket") or "All"),
            str(record.get("market_cap_bucket") or "All"),
            str(record.get("announcement_type") or ""),
            str(record.get("category") or ""),
            title,
            summary,
            meeting_date,
            record.get("announced_at"),
            quarter,
            timing,
            json.dumps(record.get("attachment_urls") or []),
            json.dumps(record.get("storage_paths") or []),
            json.dumps(record.get("raw_json") or {}),
            str(record.get("processing_status") or "stored"),
        ))

    processed = 0
    try:
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                # Process in small chunks and commit per chunk to avoid Supabase
                # statement timeouts during large backfills.
                CHUNK_SIZE = 100
                for i in range(0, len(rows_to_insert), CHUNK_SIZE):
                    chunk = rows_to_insert[i: i + CHUNK_SIZE]
                    cur.executemany(
                        """
                        INSERT INTO earnings_announcements (
                          event_uid, exchange, source_uid, symbol, isin, bse_scrip_code,
                          company_name, sector, index_bucket, market_cap_bucket,
                          announcement_type, category, title, summary, meeting_date,
                          announced_at, quarter_ref, timing, attachment_urls,
                          storage_paths, raw_json, processing_status, updated_at
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s,
                          %s, %s, %s, %s, %s,
                          %s, %s, %s, %s::jsonb,
                          %s::jsonb, %s::jsonb, %s, now()
                        )
                        ON CONFLICT (event_uid) DO UPDATE SET
                          symbol = EXCLUDED.symbol,
                          company_name = EXCLUDED.company_name,
                          sector = CASE WHEN EXCLUDED.sector != '' THEN EXCLUDED.sector ELSE earnings_announcements.sector END,
                          index_bucket = EXCLUDED.index_bucket,
                          market_cap_bucket = EXCLUDED.market_cap_bucket,
                          title = EXCLUDED.title,
                          summary = EXCLUDED.summary,
                          meeting_date = EXCLUDED.meeting_date,
                          announced_at = COALESCE(EXCLUDED.announced_at, earnings_announcements.announced_at),
                          quarter_ref = EXCLUDED.quarter_ref,
                          timing = CASE WHEN EXCLUDED.timing != 'TAS' THEN EXCLUDED.timing ELSE earnings_announcements.timing END,
                          attachment_urls = CASE WHEN EXCLUDED.attachment_urls != '[]'::jsonb THEN EXCLUDED.attachment_urls ELSE earnings_announcements.attachment_urls END,
                          storage_paths = EXCLUDED.storage_paths,
                          raw_json = EXCLUDED.raw_json,
                          processing_status = EXCLUDED.processing_status,
                          updated_at = now()
                        """,
                        chunk,
                    )
                    processed += len(chunk)
                    conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("batch_upsert_announcements failed: %s", exc)

    return processed


def upsert_detail(record: dict[str, Any], database_url: str | None = None) -> bool:
    db_url = get_database_url(database_url)
    if not db_url or not ensure_earnings_tables(db_url):
        return False
    symbol = str(record.get("symbol") or "").strip().upper()
    event_uid = str(record.get("event_uid") or "").strip()
    if not symbol or not event_uid:
        return False
    meeting_date = parse_date(record.get("meeting_date")) or date.today()
    try:
        with connect_postgres(db_url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into earnings_details (
                      event_uid, symbol, company_name, meeting_date, fiscal_quarter,
                      timing, highlights_json, management_json, transcript_json,
                      documents_json, financials_json, text_excerpt, parser_version,
                      updated_at
                    )
                    values (
                      %s, %s, %s, %s, %s,
                      %s, %s::jsonb, %s::jsonb, %s::jsonb,
                      %s::jsonb, %s::jsonb, %s, %s,
                      now()
                    )
                    on conflict (event_uid) do update set
                      fiscal_quarter = excluded.fiscal_quarter,
                      timing = excluded.timing,
                      highlights_json = excluded.highlights_json,
                      management_json = excluded.management_json,
                      transcript_json = excluded.transcript_json,
                      documents_json = excluded.documents_json,
                      financials_json = excluded.financials_json,
                      text_excerpt = excluded.text_excerpt,
                      parser_version = excluded.parser_version,
                      updated_at = now()
                    """,
                    (
                        event_uid,
                        symbol,
                        str(record.get("company_name") or symbol),
                        meeting_date,
                        str(record.get("fiscal_quarter") or record.get("quarter") or ""),
                        str(record.get("timing") or "TAS"),
                        json.dumps(record.get("highlights") or []),
                        json.dumps(record.get("management_commentary") or record.get("management") or []),
                        json.dumps(record.get("transcript") or {}),
                        json.dumps(record.get("documents") or []),
                        json.dumps(record.get("financials") or {}),
                        str(record.get("text_excerpt") or ""),
                        str(record.get("parser_version") or ""),
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("earnings detail upsert failed for %s: %s", symbol, exc)
        return False


def _query_available() -> bool:
    db_url = get_database_url()
    if not db_url:
        return False
    if db_url in _BOOTSTRAPPED:
        return True
    return _probe_earnings_tables(db_url)


def _query_calendar_rows(start: date, end: date) -> list[dict[str, Any]] | None:
    if not _query_available():
        return None
    
    # Check cache first
    cache_key = f"{start.isoformat()}:{end.isoformat()}"
    cached = _CALENDAR_CACHE.get(cache_key)
    if cached:
        cached_at, cached_rows = cached
        if time.monotonic() - cached_at < _CALENDAR_CACHE_TTL_S:
            return cached_rows
    
    universe_sql, universe_params = earnings_universe_sql_filter("a")
    where_sql = "a.meeting_date between %s and %s"
    params: list[Any] = [start, end]
    if universe_sql:
        where_sql += f" and {universe_sql}"
        params.extend(universe_params)
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=_READ_CONNECT_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                _configure_read_timeouts(cur)
                cur.execute(
                    f"""
                    with base as (
                      select a.meeting_date, a.sector, coalesce(a.timing, 'TAS') as timing
                      from earnings_announcements a
                      where {where_sql}
                    ), timing_counts as (
                      select meeting_date, timing, count(*)::int as company_count
                      from base
                      group by meeting_date, timing
                    ), timing_json as (
                      select meeting_date, jsonb_object_agg(timing, company_count) as timings
                      from timing_counts
                      group by meeting_date
                    ), day_rows as (
                      select
                        meeting_date,
                        meeting_date::text as date,
                        count(*)::int as company_count,
                        array_remove(array_agg(distinct sector), null) as sectors
                      from base
                      group by meeting_date
                    )
                    select d.date, d.company_count, d.sectors, coalesce(t.timings, '{{}}'::jsonb) as timings
                    from day_rows d
                    left join timing_json t on t.meeting_date = d.meeting_date
                    order by d.meeting_date
                    """,
                    params,
                )
                rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            row["summary"] = f"{row.get('company_count', 0)} earnings call(s)"
            row["sectors"] = list(row.get("sectors") or [])
            row["timings"] = dict(row.get("timings") or {})
        # Cache the result
        _CALENDAR_CACHE[cache_key] = (time.monotonic(), rows)
        return rows
    except Exception as exc:  # noqa: BLE001
        logger.debug("calendar query failed: %s", exc)
        _trip_db_circuit()
        return None


def _query_company_rows(
    selected: date,
    *,
    index_filter: str,
    market_cap_filter: str,
    sector_filter: str,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int] | None:
    if not _query_available():
        return None
    clauses = ["a.meeting_date = %s"]
    params: list[Any] = [selected]
    if _active_filter(index_filter):
        clauses.append("coalesce(a.index_bucket, 'All') = %s")
        params.append(index_filter)
    if _active_filter(market_cap_filter):
        clauses.append("coalesce(a.market_cap_bucket, 'All') = %s")
        params.append(market_cap_filter)
    if _active_filter(sector_filter):
        clauses.append("coalesce(a.sector, 'Other') = %s")
        params.append(sector_filter)
    universe_sql, universe_params = earnings_universe_sql_filter("a")
    if universe_sql:
        clauses.append(universe_sql)
        params.extend(universe_params)
    where_sql = " and ".join(clauses)
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=_READ_CONNECT_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                _configure_read_timeouts(cur)
                cur.execute(f"select count(*) as total from earnings_announcements a where {where_sql}", params)
                total = int((cur.fetchone() or {}).get("total") or 0)
                cur.execute(
                    f"""
                    select
                      a.event_uid,
                      a.symbol,
                      a.company_name as name,
                      a.sector,
                      a.index_bucket,
                      a.market_cap_bucket,
                      a.meeting_date::text as date,
                      coalesce(d.timing, a.timing, 'TAS') as timing,
                      coalesce(d.fiscal_quarter, a.quarter_ref, '') as fiscal_quarter,
                      coalesce(d.highlights_json, '[]'::jsonb) as highlights,
                      a.attachment_urls,
                      a.summary,
                      h.actual_eps,
                      h.estimated_eps,
                      h.surprise_eps_pct,
                      h.post_earnings_move_1d,
                      h.actual_revenue,
                      h.surprise_revenue_pct,
                      (select (fin->>'yoy_pct')::numeric
                         from jsonb_array_elements(coalesce(d.financials_json->'rows', '[]'::jsonb)) fin
                         where fin->>'key' = 'revenue' limit 1) as revenue_yoy_pct,
                      (select (fin->>'yoy_pct')::numeric
                         from jsonb_array_elements(coalesce(d.financials_json->'rows', '[]'::jsonb)) fin
                         where fin->>'key' = 'pat' limit 1) as pat_yoy_pct
                    from earnings_announcements a
                    left join earnings_details d on d.event_uid = a.event_uid
                    left join earnings_history h on
                      h.symbol = a.symbol
                      and h.earnings_date >= a.meeting_date::timestamptz
                      and h.earnings_date < (a.meeting_date + interval '1 day')::timestamptz
                    where {where_sql}
                    order by a.company_name
                    limit %s offset %s
                    """,
                    [*params, page_size, (page - 1) * page_size],
                )
                rows = [_company_row_from_db(dict(row)) for row in cur.fetchall()]
        return rows, total
    except Exception as exc:  # noqa: BLE001
        logger.debug("company query failed: %s", exc)
        _trip_db_circuit()
        return None


def _query_company_rows_range(
    range_start: date,
    range_end: date,
    *,
    index_filter: str,
    market_cap_filter: str,
    sector_filter: str,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int] | None:
    """Return companies across a date range, ordered by date desc, then name."""
    if not _query_available():
        return None
    
    # Check cache for unfiltered range queries (overview pulse)
    is_unfiltered = (
        not _active_filter(index_filter)
        and not _active_filter(market_cap_filter)
        and not _active_filter(sector_filter)
    )
    cache_key = f"{range_start.isoformat()}:{range_end.isoformat()}:{page}:{page_size}"
    if is_unfiltered:
        cached = _COMPANIES_CACHE.get(cache_key)
        if cached:
            cached_at, cached_result = cached
            if time.monotonic() - cached_at < _COMPANIES_CACHE_TTL_S:
                return cached_result
    
    clauses = ["a.meeting_date between %s and %s"]
    params: list[Any] = [range_start, range_end]
    if _active_filter(index_filter):
        clauses.append("coalesce(a.index_bucket, 'All') = %s")
        params.append(index_filter)
    if _active_filter(market_cap_filter):
        clauses.append("coalesce(a.market_cap_bucket, 'All') = %s")
        params.append(market_cap_filter)
    if _active_filter(sector_filter):
        clauses.append("coalesce(a.sector, 'Other') = %s")
        params.append(sector_filter)
    universe_sql, universe_params = earnings_universe_sql_filter("a")
    if universe_sql:
        clauses.append(universe_sql)
        params.extend(universe_params)
    where_sql = " and ".join(clauses)
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=_READ_CONNECT_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                _configure_read_timeouts(cur)
                cur.execute(f"select count(*) as total from earnings_announcements a where {where_sql}", params)
                total = int((cur.fetchone() or {}).get("total") or 0)
                cur.execute(
                    f"""
                    select
                      a.event_uid,
                      a.symbol,
                      a.company_name as name,
                      a.sector,
                      a.index_bucket,
                      a.market_cap_bucket,
                      a.meeting_date::text as date,
                      coalesce(d.timing, a.timing, 'TAS') as timing,
                      coalesce(d.fiscal_quarter, a.quarter_ref, '') as fiscal_quarter,
                      coalesce(d.highlights_json, '[]'::jsonb) as highlights,
                      a.attachment_urls,
                      a.summary,
                      h.actual_eps,
                      h.estimated_eps,
                      h.surprise_eps_pct,
                      h.post_earnings_move_1d,
                      h.actual_revenue,
                      h.surprise_revenue_pct,
                      (select (fin->>'yoy_pct')::numeric
                         from jsonb_array_elements(coalesce(d.financials_json->'rows', '[]'::jsonb)) fin
                         where fin->>'key' = 'revenue' limit 1) as revenue_yoy_pct,
                      (select (fin->>'yoy_pct')::numeric
                         from jsonb_array_elements(coalesce(d.financials_json->'rows', '[]'::jsonb)) fin
                         where fin->>'key' = 'pat' limit 1) as pat_yoy_pct
                    from earnings_announcements a
                    left join earnings_details d on d.event_uid = a.event_uid
                    left join earnings_history h on
                      h.symbol = a.symbol
                      and h.earnings_date >= a.meeting_date::timestamptz
                      and h.earnings_date < (a.meeting_date + interval '1 day')::timestamptz
                    where {where_sql}
                    order by a.meeting_date desc, a.company_name
                    limit %s offset %s
                    """,
                    [*params, page_size, (page - 1) * page_size],
                )
                rows = [_company_row_from_db(dict(row)) for row in cur.fetchall()]
        # Cache unfiltered results for the overview pulse
        if is_unfiltered:
            _COMPANIES_CACHE[cache_key] = (time.monotonic(), (rows, total))
        return rows, total
    except Exception as exc:  # noqa: BLE001
        logger.debug("company range query failed: %s", exc)
        _trip_db_circuit()
        return None


def _query_result_detail_row(symbol: str, selected: date) -> dict[str, Any] | None:
    if not _query_available():
        return None
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                      d.event_uid as detail_event_uid,
                      d.*,
                      a.event_uid as announcement_event_uid,
                      a.symbol as announcement_symbol,
                      a.company_name as announcement_company_name,
                      a.meeting_date::text as announcement_date,
                      a.timing as announcement_timing,
                      a.quarter_ref as announcement_quarter_ref,
                      a.title as announcement_title,
                      a.summary as announcement_summary,
                      a.attachment_urls,
                      a.storage_paths,
                      a.sector,
                      a.index_bucket,
                      a.market_cap_bucket,
                      a.updated_at as announcement_updated_at
                    from earnings_announcements a
                    left join earnings_details d on d.event_uid = a.event_uid
                    where upper(a.symbol) = %s
                      and a.meeting_date = %s
                    order by d.updated_at desc nulls last, a.updated_at desc
                    limit 1
                    """,
                    (symbol.upper(), selected),
                )
                row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        if data.get("detail_event_uid"):
            return _detail_row_from_db(data)
        return _announcement_detail_row_from_db(
            {
                "event_uid": data.get("announcement_event_uid"),
                "symbol": data.get("announcement_symbol"),
                "company_name": data.get("announcement_company_name"),
                "sector": data.get("sector"),
                "date": data.get("announcement_date"),
                "timing": data.get("announcement_timing"),
                "fiscal_quarter": data.get("announcement_quarter_ref"),
                "attachment_urls": data.get("attachment_urls"),
                "storage_paths": data.get("storage_paths"),
                "title": data.get("announcement_title"),
                "summary": data.get("announcement_summary"),
                "updated_at": data.get("announcement_updated_at"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("result detail joined query failed: %s", exc)
        _trip_db_circuit()
        return None
def _query_detail_row(symbol: str, selected: date | None) -> dict[str, Any] | None:
    if not _query_available():
        return None
    clauses = ["upper(d.symbol) = %s"]
    params: list[Any] = [symbol.upper()]
    if selected:
        clauses.append("d.meeting_date = %s")
        params.append(selected)
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    select
                      d.*, a.sector, a.index_bucket, a.market_cap_bucket,
                      a.attachment_urls, a.storage_paths, a.title, a.summary
                    from earnings_details d
                    join earnings_announcements a on a.event_uid = d.event_uid
                    where {" and ".join(clauses)}
                    order by d.meeting_date desc, d.updated_at desc
                    limit 1
                    """,
                    params,
                )
                row = cur.fetchone()
        return _detail_row_from_db(dict(row)) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("detail query failed: %s", exc)
        _trip_db_circuit()
        return None


def _query_announcement_detail_row(symbol: str, selected: date) -> dict[str, Any] | None:
    """Return a detail-compatible row from the announcement table.

    Announcement ingestion is intentionally faster than PDF parsing, so a past
    company can be visible in the calendar before earnings_details is populated.
    This fallback prevents the detail page from 404ing while still linking the
    official filing and showing generated highlights from the exchange summary.
    """
    if not _query_available():
        return None
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                      a.event_uid,
                      a.symbol,
                      a.company_name,
                      a.sector,
                      a.index_bucket,
                      a.market_cap_bucket,
                      a.meeting_date::text as date,
                      coalesce(a.timing, 'TAS') as timing,
                      coalesce(a.quarter_ref, '') as fiscal_quarter,
                      a.attachment_urls,
                      a.storage_paths,
                      a.title,
                      a.summary,
                      a.updated_at
                    from earnings_announcements a
                    where upper(a.symbol) = %s
                      and a.meeting_date = %s
                    order by a.updated_at desc
                    limit 1
                    """,
                    (symbol.upper(), selected),
                )
                row = cur.fetchone()
        return _announcement_detail_row_from_db(dict(row)) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("announcement detail fallback query failed: %s", exc)
        _trip_db_circuit()
        return None

def _query_announcement_record_for_parse(symbol: str, selected: date) -> dict[str, Any] | None:
    if not _query_available():
        return None
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                      event_uid, exchange, source_uid, symbol, isin, bse_scrip_code,
                      company_name, sector, index_bucket, market_cap_bucket,
                      announcement_type, category, title, summary,
                      meeting_date::text as meeting_date, announced_at,
                      quarter_ref, timing, attachment_urls, storage_paths,
                      raw_json, processing_status, updated_at
                    from earnings_announcements
                    where upper(symbol) = %s
                      and meeting_date = %s
                    order by updated_at desc
                    limit 1
                    """,
                    (symbol.upper(), selected),
                )
                row = cur.fetchone()
        if not row:
            return None
        record = dict(row)
        record["attachment_urls"] = _list_json(record.get("attachment_urls"))
        record["storage_paths"] = _list_json(record.get("storage_paths"))
        record["raw_json"] = _dict_json(record.get("raw_json"))
        return record
    except Exception as exc:  # noqa: BLE001
        logger.debug("announcement parse-record query failed: %s", exc)
        _trip_db_circuit()
        return None


def _set_announcement_processing_status(event_uid: str, status: str) -> bool:
    if not event_uid or not _query_available():
        return False
    try:
        with connect_postgres(connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update earnings_announcements
                    set processing_status = %s, updated_at = now()
                    where event_uid = %s
                    """,
                    (status, event_uid),
                )
            conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("announcement processing status update failed: %s", exc)
        _trip_db_circuit()
        return False


def _query_earnings_history_for_date(symbol: str, selected: date) -> dict[str, Any] | None:
    """Return the Yahoo-sourced history row matching the given earnings date (±3 days)."""
    if not _query_available():
        return None
    try:
        from psycopg.rows import dict_row
        date_min = selected - timedelta(days=3)
        date_max = selected + timedelta(days=3)
        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT actual_eps, estimated_eps, surprise_eps_pct,
                           actual_revenue, estimated_revenue, surprise_revenue_pct,
                           post_earnings_move_1d, pre_close, post_close
                    FROM earnings_history
                    WHERE upper(symbol) = %s
                      AND earnings_date::date BETWEEN %s AND %s
                    ORDER BY earnings_date DESC NULLS LAST
                    LIMIT 1
                    """,
                    (symbol.upper(), date_min, date_max),
                )
                row = cur.fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.debug("_query_earnings_history_for_date failed for %s: %s", symbol, exc)
        return None


def _query_historical_metrics(
    symbol: str,
    selected: date,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return (prev_quarter_metrics, year_ago_metrics) from stored earnings_details records.

    Source: earnings_details (parsed from PDF via Azure DI).
    XBRL-based QoQ/YoY is now populated at parse time, so the hot path stays DB-only.
    """
    if _query_available():
        try:
            from psycopg.rows import dict_row
            prev_min = selected - timedelta(days=120)
            prev_max = selected - timedelta(days=60)
            yoy_min = selected - timedelta(days=400)
            yoy_max = selected - timedelta(days=300)

            with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.financials_json
                        FROM earnings_details d
                        JOIN earnings_announcements a ON a.event_uid = d.event_uid
                        WHERE upper(a.symbol) = %s AND a.meeting_date BETWEEN %s AND %s
                        ORDER BY a.meeting_date DESC LIMIT 1
                        """,
                        (symbol.upper(), prev_min, prev_max),
                    )
                    prev_row = cur.fetchone()
                    cur.execute(
                        """
                        SELECT d.financials_json
                        FROM earnings_details d
                        JOIN earnings_announcements a ON a.event_uid = d.event_uid
                        WHERE upper(a.symbol) = %s AND a.meeting_date BETWEEN %s AND %s
                        ORDER BY a.meeting_date DESC LIMIT 1
                        """,
                        (symbol.upper(), yoy_min, yoy_max),
                    )
                    yoy_row = cur.fetchone()

            def _extract(row: dict[str, Any] | None) -> dict[str, float]:
                if not row:
                    return {}
                fin = _financials_payload(row["financials_json"])
                m = fin.get("metrics")
                if isinstance(m, dict) and m:
                    return {k: float(v) for k, v in m.items() if v is not None}
                return {
                    r["key"]: float(r["current"])
                    for r in (fin.get("rows") or [])
                    if r.get("key") and r.get("current") is not None
                }

            db_prev = _extract(dict(prev_row) if prev_row else None)
            db_yoy = _extract(dict(yoy_row) if yoy_row else None)

            if db_prev or db_yoy:
                return db_prev, db_yoy
        except Exception as exc:
            logger.debug("DB historical metrics lookup failed for %s: %s", symbol, exc)

    return {}, {}


def _tab_label(row: dict[str, Any]) -> str:
    """Build a human-readable quarter label from an earnings_history or announcement row."""
    label = str(row.get("quarter_label") or "").strip()
    if label:
        return label
    fp = str(row.get("fiscal_period") or "").strip()
    fy = row.get("fiscal_year")
    if fp and fy:
        return f"{fp} FY{str(fy)[-2:]}"
    dt_str = str(row.get("earnings_date") or "")[:10]
    if dt_str:
        return fiscal_quarter_from_date(parse_date(dt_str)) or "Q?"
    return "Q?"


def _query_quarter_tabs(symbol: str, current_date: date) -> list[dict[str, Any]]:
    """Return last 8 quarters of earnings tab data with 1D move, newest first."""
    if not _query_available():
        return []
    try:
        from psycopg.rows import dict_row
        cutoff = current_date - timedelta(days=800)
        today = date.today()

        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT fiscal_year, fiscal_period, quarter_label,
                           earnings_date::date AS earnings_date,
                           post_earnings_move_1d
                    FROM earnings_history
                    WHERE upper(symbol) = %s
                      AND (earnings_date IS NULL OR earnings_date::date >= %s)
                    ORDER BY earnings_date DESC NULLS LAST
                    LIMIT 8
                    """,
                    (symbol.upper(), cutoff),
                )
                history_rows = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT quarter_ref, meeting_date::date AS earnings_date
                    FROM earnings_announcements
                    WHERE upper(symbol) = %s AND meeting_date >= %s
                    ORDER BY meeting_date DESC
                    LIMIT 10
                    """,
                    (symbol.upper(), cutoff),
                )
                ann_rows = [dict(r) for r in cur.fetchall()]

        seen: dict[str, dict[str, Any]] = {}
        for row in history_rows:
            dt_str = str(row.get("earnings_date") or "")[:10]
            if not dt_str:
                continue
            dt = parse_date(dt_str)
            seen[dt_str] = {
                "label": _tab_label(row),
                "fiscal_year": row.get("fiscal_year"),
                "fiscal_period": row.get("fiscal_period"),
                "move_1d_pct": row.get("post_earnings_move_1d"),
                "earnings_date": dt_str,
                "is_future": bool(dt and dt > today),
                "is_current": bool(dt == current_date),
            }

        for row in ann_rows:
            dt_str = str(row.get("earnings_date") or "")[:10]
            if not dt_str or dt_str in seen:
                continue
            dt = parse_date(dt_str)
            label = str(row.get("quarter_ref") or "").strip() or fiscal_quarter_from_date(dt) or "Q?"
            seen[dt_str] = {
                "label": label,
                "fiscal_year": None,
                "fiscal_period": None,
                "move_1d_pct": None,
                "earnings_date": dt_str,
                "is_future": bool(dt and dt > today),
                "is_current": bool(dt == current_date),
            }

        return sorted(seen.values(), key=lambda t: t["earnings_date"], reverse=True)[:8]
    except Exception as exc:
        logger.debug("_query_quarter_tabs failed for %s: %s", symbol, exc)
        return []


def _generate_ai_summary(
    *,
    text_excerpt: str,
    metrics: dict[str, Any],
    company_name: str,
    symbol: str,
    fiscal_quarter: str,
    meeting_date: str,
) -> dict[str, Any]:
    """Call LLM to produce structured earnings intelligence. Returns {} on any failure."""
    if not text_excerpt or len(text_excerpt) < 200:
        return {}
    try:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        from finagent.swarm.llm import swarm_chat, loads_lenient  # type: ignore[import]
    except ImportError:
        return {}

    _metric_labels: dict[str, str] = {
        "revenue": "Revenue (Rs Cr)",
        "pat": "PAT (Rs Cr)",
        "ebitda": "EBITDA (Rs Cr)",
        "eps": "EPS (Rs)",
        "ebitda_margin": "EBITDA Margin (%)",
        "pat_margin": "PAT Margin (%)",
    }
    metrics_text = "\n".join(
        f"{_metric_labels[k]}: {metrics[k]}" for k in _metric_labels if metrics.get(k) is not None
    ) or "Not available"

    system_prompt = (
        "You are a senior equity research analyst specialising in Indian listed companies. "
        "Analyse the earnings results and return ONLY valid JSON — no markdown, no prose outside the JSON. "
        "Required JSON structure:\n"
        "{\n"
        '  "performance_narrative": "2-3 sentence overall performance summary",\n'
        '  "pov_analysis": "1-2 sentence qualitative POV on what this result means for investors",\n'
        '  "key_highlights": {\n'
        '    "revenue_drivers": "Key revenue driver commentary",\n'
        '    "margin_quality": "Margin analysis — quality, drivers, sustainability",\n'
        '    "demand_geography": "Demand trends by segment, geography, or product line",\n'
        '    "management_guidance": "Guidance for next quarter or full year",\n'
        '    "order_book": "Order book or backlog commentary if applicable"\n'
        "  },\n"
        '  "risks_outlook": "Key risks and near-term outlook in 1-2 sentences",\n'
        '  "verdict": "One-sentence verdict on the quarter",\n'
        '  "rating": "Positive or Neutral or Negative"\n'
        "}"
    )
    user_prompt = (
        f"Company: {company_name} ({symbol})\n"
        f"Quarter: {fiscal_quarter}\n"
        f"Meeting Date: {meeting_date}\n\n"
        f"Financial Metrics:\n{metrics_text}\n\n"
        f"Document Text (excerpt):\n{text_excerpt[:4000]}"
    )

    def _run() -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                swarm_chat(system_prompt, user_prompt, complexity="medium", json_mode=True, max_tokens=1200)
            )
        if not loop.is_running():
            return loop.run_until_complete(
                swarm_chat(system_prompt, user_prompt, complexity="medium", json_mode=True, max_tokens=1200)
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                lambda: asyncio.run(
                    swarm_chat(system_prompt, user_prompt, complexity="medium", json_mode=True, max_tokens=1200)
                )
            ).result()

    try:
        raw = _run()
        result = loads_lenient(raw) if isinstance(raw, str) else raw
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        logger.debug("_generate_ai_summary failed for %s: %s", symbol, exc)
        return {}


def _store_ai_summary(event_uid: str, ai_summary: dict[str, Any]) -> bool:
    """Persist LLM-generated AI summary in earnings_details.ai_summary_json."""
    if not event_uid or not ai_summary or not _query_available():
        return False
    try:
        with connect_postgres(connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE earnings_details
                    SET ai_summary_json = %s::jsonb, updated_at = now()
                    WHERE event_uid = %s
                    """,
                    (json.dumps(ai_summary), event_uid),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.debug("_store_ai_summary failed for %s: %s", event_uid, exc)
        return False


def _apply_xbrl_unit_correction(
    symbol: str,
    financials_payload: dict[str, Any],
) -> dict[str, Any]:
    """Detect unit-scale errors in extracted metrics by comparing against recent XBRL data.

    Some companies report financials in Rs Millions (not Crore) in their PDFs.
    If the PDF unit declaration wasn't detected, extracted revenue will be ~10x too high.
    Cross-validate: if extracted_revenue / xbrl_revenue is ~10 → divide by 10.
    """
    metrics = _dict_json(financials_payload.get("metrics") or {})
    extracted_revenue = metrics.get("revenue")
    if not extracted_revenue or extracted_revenue <= 0:
        return financials_payload

    try:
        from finagent.earnings.nse_xbrl_scraper import fetch_nse_quarterly_financials
        xbrl_quarters = fetch_nse_quarterly_financials(symbol, max_quarters=2)
    except Exception:
        return financials_payload

    if not xbrl_quarters:
        return financials_payload

    xbrl_revenue = xbrl_quarters[0].get("revenue")
    if not xbrl_revenue or xbrl_revenue <= 0:
        return financials_payload

    ratio = extracted_revenue / xbrl_revenue

    # Detect unit mismatch: 8–12x = Rs Millions; 80–120x = Rs Lakhs
    if 8.0 <= ratio <= 12.0:
        scale = 0.1
        logger.info(
            "Unit correction for %s: extracted revenue %.1f Cr is ~10x XBRL %.1f Cr → applying ÷10 (Rs Millions)",
            symbol, extracted_revenue, xbrl_revenue,
        )
    elif 80.0 <= ratio <= 120.0:
        scale = 0.01
        logger.info(
            "Unit correction for %s: extracted revenue %.1f Cr is ~100x XBRL %.1f Cr → applying ÷100 (Rs Lakhs)",
            symbol, extracted_revenue, xbrl_revenue,
        )
    else:
        return financials_payload  # values look reasonable, no correction

    # Apply correction to all absolute monetary metrics
    _ABSOLUTE_KEYS = {"revenue", "pat", "ebitda"}
    corrected_metrics: dict[str, Any] = {}
    for k, v in metrics.items():
        if v is None:
            corrected_metrics[k] = v
        elif k in _ABSOLUTE_KEYS:
            corrected_metrics[k] = round(float(v) * scale, 2)
        else:
            corrected_metrics[k] = v  # EPS and margins stay as-is

    # Recompute margins with corrected values
    if corrected_metrics.get("revenue") and corrected_metrics.get("pat"):
        corrected_metrics["pat_margin"] = round(
            corrected_metrics["pat"] / corrected_metrics["revenue"] * 100, 2
        )
    if corrected_metrics.get("revenue") and corrected_metrics.get("ebitda"):
        corrected_metrics["ebitda_margin"] = round(
            corrected_metrics["ebitda"] / corrected_metrics["revenue"] * 100, 2
        )

    # Apply same correction to financial comparison rows
    corrected_rows = []
    for row in (financials_payload.get("rows") or []):
        if row.get("key") in _ABSOLUTE_KEYS:
            new_row = dict(row)
            if new_row.get("current") is not None:
                new_row["current"] = round(float(new_row["current"]) * scale, 2)
            if new_row.get("previous_quarter") is not None:
                new_row["previous_quarter"] = round(float(new_row["previous_quarter"]) * scale, 2)
            if new_row.get("same_quarter_last_year") is not None:
                new_row["same_quarter_last_year"] = round(float(new_row["same_quarter_last_year"]) * scale, 2)
            corrected_rows.append(new_row)
        else:
            corrected_rows.append(row)

    result = dict(financials_payload)
    result["metrics"] = corrected_metrics
    result["rows"] = corrected_rows
    return result


def _query_stats_rows(selected: date) -> list[dict[str, Any]] | None:
    if not _query_available():
        return None
    universe_sql, universe_params = earnings_universe_sql_filter("a")
    where_sql = "a.meeting_date = %s"
    params: list[Any] = [selected]
    if universe_sql:
        where_sql += f" and {universe_sql}"
        params.extend(universe_params)
    try:
        from psycopg.rows import dict_row

        with connect_postgres(row_factory=dict_row, connect_timeout=_READ_CONNECT_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                _configure_read_timeouts(cur)
                cur.execute(
                    f"""
                    select coalesce(a.timing, 'TAS') as timing, coalesce(a.sector, 'Other') as sector, count(*)::int as company_count
                    from earnings_announcements a
                    where {where_sql}
                    group by coalesce(a.timing, 'TAS'), coalesce(a.sector, 'Other')
                    """,
                    params,
                )
                return [dict(row) for row in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("stats query failed: %s", exc)
        _trip_db_circuit()
        return None


def _active_filter(value: str | None) -> bool:
    return bool(value and str(value).strip().lower() != "all")


def _normalize_sector(value: Any) -> str:
    """Normalise sector: treat empty strings, None, or placeholder '-' as 'Other'."""
    s = str(value or "").strip()
    if not s or s == "-":
        return "Other"
    return s


def _json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _list_json(value: Any) -> list[Any]:
    parsed = _json_value(value, [])
    return parsed if isinstance(parsed, list) else []


def _dict_json(value: Any) -> dict[str, Any]:
    parsed = _json_value(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _highlight_items(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _list_json(value):
        if isinstance(item, dict):
            items.append(item)
        elif item not in (None, ""):
            items.append({"text": str(item), "url": "", "source_label": ""})
    return items


def _document_items(documents_value: Any, attachment_value: Any) -> list[dict[str, Any]]:
    documents = [item for item in _list_json(documents_value) if isinstance(item, dict)]
    if documents:
        return documents
    return [
        {
            "type": "Official attachment",
            "title": "Exchange filing",
            "url": str(url),
            "storage_path": "",
        }
        for url in _list_json(attachment_value)
        if str(url or "").strip()
    ]


def _transcript_payload(value: Any) -> dict[str, list[Any]]:
    payload = _dict_json(value)
    return {
        "prepared_remarks": _list_json(payload.get("prepared_remarks")),
        "qa": _list_json(payload.get("qa")),
    }


def _financials_payload(value: Any) -> dict[str, Any]:
    payload = _dict_json(value)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        rows = payload.get("financial_comparison")
    normalized = dict(payload)
    normalized["rows"] = rows if isinstance(rows, list) else []
    return normalized


def _company_row_from_db(row: dict[str, Any]) -> dict[str, Any]:
    attachments = _list_json(row.get("attachment_urls"))
    highlights = _highlight_items(row.get("highlights"))
    if not highlights:
        source_url = str(attachments[0]) if attachments else ""
        highlights = build_ai_highlights(str(row.get("summary") or ""), source_url=source_url)
    
    # Parse meeting date to determine if past or future
    meeting_date_str = row.get("date") or ""
    try:
        meeting_date = datetime.fromisoformat(meeting_date_str).date()
        is_past = meeting_date < date.today()
    except (ValueError, TypeError):
        is_past = False
    
    return {
        "event_uid": row.get("event_uid"),
        "symbol": row.get("symbol") or "",
        "name": row.get("name") or row.get("company_name") or row.get("symbol") or "",
        "sector": _normalize_sector(row.get("sector")),
        "index": row.get("index_bucket") or "All",
        "market_cap": row.get("market_cap_bucket") or "All",
        "date": row.get("date"),
        "timing": row.get("timing") or "TAS",
        "fiscal_quarter": row.get("fiscal_quarter") or "",
        "highlights": highlights[:3],
        "is_past": is_past,
        "eps_actual": row.get("actual_eps"),
        "eps_estimated": row.get("estimated_eps"),
        "eps_surprise_pct": row.get("surprise_eps_pct"),
        "post_earnings_move_1d": row.get("post_earnings_move_1d"),
        # Revenue and PAT metrics for the Earnings Pulse overview card
        "revenue_actual": row.get("actual_revenue"),
        "revenue_surprise_pct": row.get("surprise_revenue_pct"),
        "revenue_yoy_pct": row.get("revenue_yoy_pct"),
        "pat_yoy_pct": row.get("pat_yoy_pct"),
    }


def _detail_row_from_db(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_uid": row.get("event_uid"),
        "symbol": row.get("symbol") or "",
        "name": row.get("company_name") or row.get("symbol") or "",
        "sector": _normalize_sector(row.get("sector")),
        "date": str(row.get("meeting_date") or ""),
        "timing": row.get("timing") or "TAS",
        "fiscal_quarter": row.get("fiscal_quarter") or "",
        "headline_highlights": _highlight_items(row.get("highlights_json")),
        "management_commentary": _highlight_items(row.get("management_json")),
        "transcript": _transcript_payload(row.get("transcript_json")),
        "documents": _document_items(row.get("documents_json"), row.get("attachment_urls")),
        "financials": _financials_payload(row.get("financials_json")),
        "ai_summary": _dict_json(row.get("ai_summary_json")),
        "summary": row.get("summary") or "",
        "updated_at": str(row.get("updated_at") or ""),
    }

def _announcement_detail_row_from_db(row: dict[str, Any]) -> dict[str, Any]:
    attachments = _list_json(row.get("attachment_urls"))
    storage_paths = _list_json(row.get("storage_paths"))
    documents = []
    for idx, url in enumerate(attachments):
        if not str(url or "").strip():
            continue
        documents.append(
            {
                "type": "Official attachment",
                "title": "Exchange filing" if idx == 0 else f"Exchange filing {idx + 1}",
                "url": str(url),
                "storage_path": str(storage_paths[idx]) if idx < len(storage_paths) else "",
            }
        )
    summary = str(row.get("summary") or row.get("title") or "")
    source_url = documents[0]["url"] if documents else ""
    highlights = build_ai_highlights(summary, source_url=source_url) if summary else []
    return {
        "event_uid": row.get("event_uid"),
        "symbol": row.get("symbol") or "",
        "name": row.get("company_name") or row.get("symbol") or "",
        "sector": _normalize_sector(row.get("sector")),
        "date": str(row.get("date") or ""),
        "timing": row.get("timing") or "TAS",
        "fiscal_quarter": row.get("fiscal_quarter") or "",
        "headline_highlights": highlights,
        "management_commentary": [],
        "transcript": {"prepared_remarks": [], "qa": []},
        "documents": documents,
        "financials": {
            "unit_note": "PDF parsing is pending; official filing is linked for source verification.",
            "source": "announcement_fallback",
            "rows": [],
        },
        "ai_summary": {},
        "summary": summary,
        "updated_at": str(row.get("updated_at") or ""),
        "source": "announcement_fallback",
    }

def _filter_company_rows(rows: list[dict[str, Any]], index: str, market_cap: str, sector: str) -> list[dict[str, Any]]:
    def keep(row: dict[str, Any]) -> bool:
        if _active_filter(index) and row.get("index") != index:
            return False
        if _active_filter(market_cap) and row.get("market_cap") != market_cap:
            return False
        if _active_filter(sector) and row.get("sector") != sector:
            return False
        return True

    return [row for row in rows if keep(row)]


def _demo_base_date() -> date:
    return date.today()


def _demo_calendar_rows(start: date, end: date) -> list[dict[str, Any]]:
    demo_dates = {
        _demo_base_date(): 3,
        _demo_base_date() + timedelta(days=2): 2,
        _demo_base_date() - timedelta(days=3): 1,
    }
    rows = []
    for day, count in demo_dates.items():
        if start <= day <= end:
            rows.append(
                {
                    "date": day.isoformat(),
                    "company_count": count,
                    "summary": f"{count} earnings call(s)",
                    "sectors": ["Metals", "Information Technology", "Financial Services"][:count],
                    "timings": {"Post-market": max(1, count - 1), "TAS": 1},
                }
            )
    return rows


def _demo_companies_for_date(selected: date) -> list[dict[str, Any]]:
    base = _demo_base_date()
    if selected == base:
        return [_demo_company("NMDC", selected), _demo_company("TCS", selected), _demo_company("HDFCBANK", selected)]
    if selected == base + timedelta(days=2):
        return [_demo_company("INFY", selected), _demo_company("LT", selected)]
    if selected == base - timedelta(days=3):
        return [_demo_company("SUNPHARMA", selected)]
    return []


def _demo_company_rows_range(
    range_start: date,
    range_end: date,
    *,
    index_filter: str,
    market_cap_filter: str,
    sector_filter: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = range_start
    while cursor <= range_end:
        rows.extend(_demo_companies_for_date(cursor))
        cursor += timedelta(days=1)
    rows = _filter_company_rows(rows, index_filter, market_cap_filter, sector_filter)
    rows.sort(key=lambda item: str(item.get("name") or ""))
    rows.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    return rows


def _demo_stats_rows(selected: date) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for item in _demo_companies_for_date(selected):
        timing = str(item.get("timing") or "TAS")
        sector = str(item.get("sector") or "Other")
        key = (timing, sector)
        counts[key] = counts.get(key, 0) + 1
    return [
        {"timing": timing, "sector": sector, "company_count": count}
        for (timing, sector), count in counts.items()
    ]


def _demo_company(symbol: str, selected: date) -> dict[str, Any]:
    data = _DEMO_DETAILS.get(symbol, _DEMO_DETAILS["NMDC"])
    source_url = data["documents"][0]["url"]
    reported_now = selected == _demo_base_date() and symbol == "NMDC"
    return {
        "event_uid": stable_event_uid("demo", symbol, selected),
        "symbol": symbol,
        "name": data["name"],
        "sector": data["sector"],
        "index": data["index"],
        "market_cap": data["market_cap"],
        "date": selected.isoformat(),
        "timing": data["timing"],
        "fiscal_quarter": data["fiscal_quarter"],
        "highlights": [
            {**highlight, "url": highlight.get("url") or source_url}
            for highlight in data["headline_highlights"][:3]
        ],
        "is_past": selected < _demo_base_date() or reported_now,
        "eps_actual": 6.8 if reported_now else None,
        "eps_estimated": 6.3 if reported_now else None,
        "eps_surprise_pct": 7.94 if reported_now else None,
        "post_earnings_move_1d": 1.8 if reported_now else None,
    }


def _demo_detail(symbol: str, selected: date | None) -> dict[str, Any] | None:
    data = _DEMO_DETAILS.get(symbol.upper())
    if not data:
        return None
    selected = selected or _demo_base_date()
    return {
        "event_uid": stable_event_uid("demo", symbol, selected),
        "symbol": symbol.upper(),
        "name": data["name"],
        "sector": data["sector"],
        "date": selected.isoformat(),
        "timing": data["timing"],
        "fiscal_quarter": data["fiscal_quarter"],
        "headline_highlights": data["headline_highlights"],
        "management_commentary": data["management_commentary"],
        "transcript": data["transcript"],
        "documents": data["documents"],
        "financials": data["financials"],
        "summary": data["summary"],
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source": "fallback_fixture",
    }


def _comparison(current: dict[str, Any], previous: dict[str, Any], year_ago: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_note": "Absolute values are in Rs crore except EPS and margins.",
        "rows": build_financial_comparison_rows(current, previous, year_ago),
    }


_NSE_FILINGS_URL = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
_BSE_FILINGS_URL = "https://www.bseindia.com/corporates/ann.html"

_DEMO_DETAILS: dict[str, dict[str, Any]] = {
    "NMDC": {
        "name": "NMDC Limited",
        "sector": "Metals",
        "index": "NIFTY 500",
        "market_cap": "Large",
        "timing": "Post-market",
        "fiscal_quarter": "Q4 FY26",
        "summary": "NMDC result pack focused on production scale, realizations, and margin resilience.",
        "headline_highlights": [
            {
                "text": "NMDC achieved 55.3 million tonnes production in FY26, with PAT growing 11% year-over-year.",
                "url": _NSE_FILINGS_URL,
                "source_label": "NSE filing",
            },
            {
                "text": "Management commentary emphasized volume growth, cost discipline, and better evacuation logistics.",
                "url": _NSE_FILINGS_URL,
                "source_label": "Investor presentation",
            },
            {
                "text": "EBITDA margin expanded as higher volumes offset softer blended realizations.",
                "url": _BSE_FILINGS_URL,
                "source_label": "BSE filing",
            },
        ],
        "management_commentary": [
            {
                "text": "Management said domestic steel demand remains supportive and the company is prioritizing mine capacity, rail dispatches, and pellet-feed availability.",
                "url": _NSE_FILINGS_URL,
                "source_label": "Concall transcript",
            },
            {
                "text": "The next watchpoint is realization versus volume trade-off as iron ore prices and royalty costs move through the quarter.",
                "url": _BSE_FILINGS_URL,
                "source_label": "Investor meet schedule",
            },
        ],
        "transcript": {
            "prepared_remarks": [
                {
                    "speaker": "Management",
                    "text": "The quarter reflected record production, stronger dispatch coordination, and operating leverage from higher mine throughput.",
                    "order": 1,
                },
                {
                    "speaker": "CFO",
                    "text": "Cost control and realizations helped preserve EBITDA margin despite freight and royalty movement.",
                    "order": 2,
                },
            ],
            "qa": [
                {
                    "speaker": "Analyst",
                    "text": "Asked whether FY27 volume guidance assumes new evacuation capacity.",
                    "order": 1,
                },
                {
                    "speaker": "Management",
                    "text": "Management said guidance depends on mine approvals, rake availability, and end-market steel demand.",
                    "order": 2,
                },
            ],
        },
        "documents": [
            {"type": "Press release", "title": "Q4 FY26 results press release", "url": _NSE_FILINGS_URL, "storage_path": ""},
            {"type": "Investor presentation", "title": "Investor presentation", "url": _NSE_FILINGS_URL, "storage_path": ""},
            {"type": "Concall transcript PDF", "title": "Earnings call transcript", "url": _BSE_FILINGS_URL, "storage_path": ""},
            {"type": "Investor meet schedule", "title": "Schedule of investor meet", "url": _BSE_FILINGS_URL, "storage_path": ""},
        ],
        "financials": _comparison(
            {"revenue": 6985, "pat": 1412, "ebitda": 2260, "eps": 4.82, "ebitda_margin": 32.4, "pat_margin": 20.2},
            {"revenue": 6410, "pat": 1306, "ebitda": 2075, "eps": 4.45, "ebitda_margin": 32.4, "pat_margin": 20.4},
            {"revenue": 6135, "pat": 1272, "ebitda": 1930, "eps": 4.34, "ebitda_margin": 31.5, "pat_margin": 20.7},
        ),
    },
    "TCS": {
        "name": "Tata Consultancy Services Limited",
        "sector": "Information Technology",
        "index": "NIFTY 50",
        "market_cap": "Large",
        "timing": "TAS",
        "fiscal_quarter": "Q1 FY27",
        "summary": "TCS call focuses on deal conversion, BFSI demand, and margin levers.",
        "headline_highlights": [
            {"text": "Revenue growth was led by manufacturing and regional markets while discretionary technology spending stayed uneven.", "url": _NSE_FILINGS_URL, "source_label": "NSE filing"},
            {"text": "Management commentary pointed to stronger cost discipline and stable attrition as margin offsets.", "url": _NSE_FILINGS_URL, "source_label": "Concall transcript"},
        ],
        "management_commentary": [
            {"text": "Management described client decision cycles as selective, with larger transformation deals taking longer but cost-takeout programs staying active.", "url": _NSE_FILINGS_URL, "source_label": "Concall transcript"}
        ],
        "transcript": {"prepared_remarks": [{"speaker": "CEO", "text": "Demand remained mixed across verticals, with cloud migration and efficiency programs continuing to anchor the pipeline.", "order": 1}], "qa": [{"speaker": "Analyst", "text": "Asked about BFSI recovery timing and whether margin improvement is sustainable.", "order": 1}]},
        "documents": [
            {"type": "Press release", "title": "Results press release", "url": _NSE_FILINGS_URL, "storage_path": ""},
            {"type": "Investor presentation", "title": "Earnings presentation", "url": _NSE_FILINGS_URL, "storage_path": ""},
            {"type": "Concall transcript PDF", "title": "Analyst call transcript", "url": _BSE_FILINGS_URL, "storage_path": ""},
        ],
        "financials": _comparison(
            {"revenue": 64790, "pat": 12340, "ebitda": 16710, "eps": 34.1, "ebitda_margin": 25.8, "pat_margin": 19.0},
            {"revenue": 63820, "pat": 12180, "ebitda": 16390, "eps": 33.6, "ebitda_margin": 25.7, "pat_margin": 19.1},
            {"revenue": 61237, "pat": 11890, "ebitda": 15580, "eps": 32.7, "ebitda_margin": 25.4, "pat_margin": 19.4},
        ),
    },
    "HDFCBANK": {
        "name": "HDFC Bank Limited",
        "sector": "Financial Services",
        "index": "NIFTY 50",
        "market_cap": "Large",
        "timing": "Pre-market",
        "fiscal_quarter": "Q1 FY27",
        "summary": "HDFC Bank call centers on deposit growth, margin normalization, and asset-quality stability.",
        "headline_highlights": [
            {"text": "Deposit mobilization and CASA trajectory remained the main management focus for the quarter.", "url": _NSE_FILINGS_URL, "source_label": "NSE filing"},
            {"text": "Credit costs stayed contained while net interest margin recovery was guided as gradual.", "url": _BSE_FILINGS_URL, "source_label": "BSE filing"},
        ],
        "management_commentary": [
            {"text": "Management framed loan growth as balance-sheet optimized, with deposit granularity and repricing cadence taking priority.", "url": _NSE_FILINGS_URL, "source_label": "Analyst meet"}
        ],
        "transcript": {"prepared_remarks": [{"speaker": "Management", "text": "The bank continued to focus on deposit growth, branch productivity, and a measured loan-growth mix.", "order": 1}], "qa": [{"speaker": "Analyst", "text": "Asked about NIM trajectory and unsecured retail growth filters.", "order": 1}]},
        "documents": [
            {"type": "Press release", "title": "Quarterly results release", "url": _NSE_FILINGS_URL, "storage_path": ""},
            {"type": "Investor presentation", "title": "Investor presentation", "url": _NSE_FILINGS_URL, "storage_path": ""},
            {"type": "Concall transcript PDF", "title": "Earnings call transcript", "url": _BSE_FILINGS_URL, "storage_path": ""},
        ],
        "financials": _comparison(
            {"revenue": 85210, "pat": 16890, "ebitda": 0, "eps": 22.2, "ebitda_margin": 0, "pat_margin": 19.8},
            {"revenue": 83440, "pat": 16420, "ebitda": 0, "eps": 21.6, "ebitda_margin": 0, "pat_margin": 19.7},
            {"revenue": 78610, "pat": 15870, "ebitda": 0, "eps": 20.9, "ebitda_margin": 0, "pat_margin": 20.2},
        ),
    },
    "INFY": {
        "name": "Infosys Limited",
        "sector": "Information Technology",
        "index": "NIFTY 50",
        "market_cap": "Large",
        "timing": "Post-market",
        "fiscal_quarter": "Q1 FY27",
        "summary": "Infosys call tracks revenue guidance, large deals, and margin bridge.",
        "headline_highlights": [
            {"text": "Large-deal TCV and FY guidance remain the key management-commentary anchors.", "url": _NSE_FILINGS_URL, "source_label": "NSE filing"},
            {"text": "Margin commentary points to utilization, subcontractor costs, and pricing mix as major levers.", "url": _BSE_FILINGS_URL, "source_label": "Investor presentation"},
        ],
        "management_commentary": [{"text": "Management said clients remain focused on cost efficiency, AI modernization, and vendor consolidation.", "url": _NSE_FILINGS_URL, "source_label": "Concall transcript"}],
        "transcript": {"prepared_remarks": [{"speaker": "CEO", "text": "The pipeline is shaped by cost takeout, cloud, and AI-led modernization programs.", "order": 1}], "qa": [{"speaker": "Analyst", "text": "Asked whether discretionary spend has bottomed across retail and financial services.", "order": 1}]},
        "documents": [{"type": "Press release", "title": "Results press release", "url": _NSE_FILINGS_URL, "storage_path": ""}, {"type": "Concall transcript PDF", "title": "Earnings call transcript", "url": _BSE_FILINGS_URL, "storage_path": ""}],
        "financials": _comparison(
            {"revenue": 40220, "pat": 6850, "ebitda": 8800, "eps": 16.5, "ebitda_margin": 21.9, "pat_margin": 17.0},
            {"revenue": 39870, "pat": 6720, "ebitda": 8610, "eps": 16.2, "ebitda_margin": 21.6, "pat_margin": 16.9},
            {"revenue": 37933, "pat": 6368, "ebitda": 8070, "eps": 15.3, "ebitda_margin": 21.3, "pat_margin": 16.8},
        ),
    },
    "LT": {
        "name": "Larsen & Toubro Limited",
        "sector": "Construction",
        "index": "NIFTY 50",
        "market_cap": "Large",
        "timing": "During-market",
        "fiscal_quarter": "Q1 FY27",
        "summary": "L&T result pack emphasizes order inflow, execution velocity, and core E&C margin.",
        "headline_highlights": [
            {"text": "Order inflow and executable order book are the primary read-throughs for revenue visibility.", "url": _NSE_FILINGS_URL, "source_label": "NSE filing"},
            {"text": "Management commentary focused on domestic capex, Middle East execution, and working-capital discipline.", "url": _BSE_FILINGS_URL, "source_label": "Investor presentation"},
        ],
        "management_commentary": [{"text": "Management said tendering remains healthy across infrastructure, energy transition, and hydrocarbon projects.", "url": _NSE_FILINGS_URL, "source_label": "Concall transcript"}],
        "transcript": {"prepared_remarks": [{"speaker": "Management", "text": "Execution momentum improved as supply-chain bottlenecks normalized across major projects.", "order": 1}], "qa": [{"speaker": "Analyst", "text": "Asked about core E&C margin and order inflow conversion.", "order": 1}]},
        "documents": [{"type": "Press release", "title": "Results press release", "url": _NSE_FILINGS_URL, "storage_path": ""}, {"type": "Investor presentation", "title": "Investor presentation", "url": _NSE_FILINGS_URL, "storage_path": ""}],
        "financials": _comparison(
            {"revenue": 58920, "pat": 3410, "ebitda": 6035, "eps": 24.8, "ebitda_margin": 10.2, "pat_margin": 5.8},
            {"revenue": 57200, "pat": 3260, "ebitda": 5810, "eps": 23.7, "ebitda_margin": 10.2, "pat_margin": 5.7},
            {"revenue": 53110, "pat": 2980, "ebitda": 5295, "eps": 21.6, "ebitda_margin": 10.0, "pat_margin": 5.6},
        ),
    },
    "SUNPHARMA": {
        "name": "Sun Pharmaceutical Industries Limited",
        "sector": "Healthcare",
        "index": "NIFTY 50",
        "market_cap": "Large",
        "timing": "Post-market",
        "fiscal_quarter": "Q1 FY27",
        "summary": "Sun Pharma call focuses on specialty sales, US generics, and R&D intensity.",
        "headline_highlights": [
            {"text": "Specialty portfolio traction and R&D spend are the central margin and growth watchpoints.", "url": _NSE_FILINGS_URL, "source_label": "NSE filing"},
            {"text": "Management commentary highlighted product launches and resilient India formulation growth.", "url": _BSE_FILINGS_URL, "source_label": "Investor presentation"},
        ],
        "management_commentary": [{"text": "Management said specialty investments will continue while India and emerging-market businesses provide cash-flow support.", "url": _NSE_FILINGS_URL, "source_label": "Concall transcript"}],
        "transcript": {"prepared_remarks": [{"speaker": "Management", "text": "The specialty business continued to scale, though R&D and launch investments remain elevated.", "order": 1}], "qa": [{"speaker": "Analyst", "text": "Asked about specialty margin path and US price erosion.", "order": 1}]},
        "documents": [{"type": "Press release", "title": "Results press release", "url": _NSE_FILINGS_URL, "storage_path": ""}, {"type": "Concall transcript PDF", "title": "Earnings call transcript", "url": _BSE_FILINGS_URL, "storage_path": ""}],
        "financials": _comparison(
            {"revenue": 12680, "pat": 2840, "ebitda": 3550, "eps": 11.8, "ebitda_margin": 28.0, "pat_margin": 22.4},
            {"revenue": 12190, "pat": 2710, "ebitda": 3375, "eps": 11.3, "ebitda_margin": 27.7, "pat_margin": 22.2},
            {"revenue": 11340, "pat": 2515, "ebitda": 3070, "eps": 10.5, "ebitda_margin": 27.1, "pat_margin": 22.2},
        ),
    },
}


# ---------------------------------------------------------------------------
# Bootstrap SQL extensions for new tables
# ---------------------------------------------------------------------------

_EARNINGS_EXTENDED_BOOTSTRAP_SQL = """
alter table if exists earnings_details
  add column if not exists ai_summary_json jsonb default '{}'::jsonb;

alter table if exists earnings_announcements
  add column if not exists actual_revenue   numeric,
  add column if not exists estimated_revenue numeric,
  add column if not exists actual_eps        numeric,
  add column if not exists estimated_eps     numeric,
  add column if not exists surprise_eps_pct  numeric,
  add column if not exists surprise_revenue_pct numeric,
  add column if not exists post_earnings_move_1d numeric;

create table if not exists earnings_history (
    id                  bigserial primary key,
    symbol              varchar(20) not null,
    fiscal_year         integer,
    fiscal_period       varchar(10),
    period_raw          varchar(20),
    quarter_label       varchar(20),
    earnings_date       timestamptz,
    actual_eps          numeric,
    estimated_eps       numeric,
    surprise_eps_pct    numeric,
    actual_revenue      numeric,
    estimated_revenue   numeric,
    surprise_revenue_pct numeric,
    post_earnings_move_1d numeric,
    pre_close           numeric,
    post_close          numeric,
    source              varchar(40) default 'yahoo',
    created_at          timestamptz default now(),
    updated_at          timestamptz default now(),
    unique(symbol, fiscal_year, fiscal_period)
);
create index if not exists idx_earnings_history_symbol
    on earnings_history(symbol, earnings_date desc nulls last);

create table if not exists analyst_reports (
    id              bigserial primary key,
    symbol          varchar(20) not null,
    title           text not null,
    provider        text,
    source_url      text,
    report_date     date,
    outlook         varchar(30),
    summary         text,
    target_price    varchar(40),
    rating          varchar(40),
    fiscal_quarter  varchar(20),
    text_excerpt    text,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now(),
    unique(source_url)
);
create index if not exists idx_analyst_reports_symbol
    on analyst_reports(symbol, report_date desc nulls last);
"""

_EXTENDED_BOOTSTRAPPED: set[str] = set()


def ensure_extended_tables(database_url: str | None = None) -> bool:
    """Run the extended schema migration (new tables + new columns)."""
    db_url = get_database_url(database_url)
    if not db_url:
        return False
    if _db_circuit_open():
        return False
    if f"ext:{db_url}" in _EXTENDED_BOOTSTRAPPED:
        return True
    # Ensure base tables exist first
    if not ensure_earnings_tables(db_url):
        return False
    try:
        with connect_postgres(db_url, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(_EARNINGS_EXTENDED_BOOTSTRAP_SQL)
            conn.commit()
        _EXTENDED_BOOTSTRAPPED.add(f"ext:{db_url}")
        return True
    except Exception as exc:
        logger.debug("extended table bootstrap failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Earnings history (Yahoo-sourced quarterly data)
# ---------------------------------------------------------------------------

def upsert_earnings_history(record: dict[str, Any], database_url: str | None = None) -> bool:
    db_url = get_database_url(database_url)
    if not db_url or not ensure_extended_tables(db_url):
        return False
    symbol = str(record.get("symbol") or "").strip().upper()
    if not symbol:
        return False
    try:
        with connect_postgres(db_url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into earnings_history (
                        symbol, fiscal_year, fiscal_period, period_raw, quarter_label,
                        earnings_date, actual_eps, estimated_eps, surprise_eps_pct,
                        actual_revenue, estimated_revenue, surprise_revenue_pct,
                        post_earnings_move_1d, pre_close, post_close, source, updated_at
                    )
                    values (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s, now()
                    )
                    on conflict (symbol, fiscal_year, fiscal_period) do update set
                        period_raw = excluded.period_raw,
                        quarter_label = excluded.quarter_label,
                        earnings_date = coalesce(excluded.earnings_date, earnings_history.earnings_date),
                        actual_eps = coalesce(excluded.actual_eps, earnings_history.actual_eps),
                        estimated_eps = coalesce(excluded.estimated_eps, earnings_history.estimated_eps),
                        surprise_eps_pct = coalesce(excluded.surprise_eps_pct, earnings_history.surprise_eps_pct),
                        actual_revenue = coalesce(excluded.actual_revenue, earnings_history.actual_revenue),
                        estimated_revenue = coalesce(excluded.estimated_revenue, earnings_history.estimated_revenue),
                        surprise_revenue_pct = coalesce(excluded.surprise_revenue_pct, earnings_history.surprise_revenue_pct),
                        post_earnings_move_1d = coalesce(excluded.post_earnings_move_1d, earnings_history.post_earnings_move_1d),
                        pre_close = coalesce(excluded.pre_close, earnings_history.pre_close),
                        post_close = coalesce(excluded.post_close, earnings_history.post_close),
                        source = excluded.source,
                        updated_at = now()
                    """,
                    (
                        symbol,
                        record.get("fiscal_year"),
                        str(record.get("fiscal_period") or ""),
                        str(record.get("period_raw") or ""),
                        str(record.get("quarter_label") or ""),
                        record.get("earnings_date"),
                        record.get("actual_eps"),
                        record.get("estimated_eps"),
                        record.get("surprise_eps_pct"),
                        record.get("actual_revenue"),
                        record.get("estimated_revenue"),
                        record.get("surprise_revenue_pct"),
                        record.get("post_earnings_move_1d"),
                        record.get("pre_close"),
                        record.get("post_close"),
                        str(record.get("source") or "yahoo"),
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.warning("earnings_history upsert failed for %s: %s", symbol, exc)
        return False


def get_earnings_history(symbol: str, *, limit: int = 12, fallback_demo: bool = True) -> list[dict[str, Any]]:
    """Return quarterly earnings history for a symbol, newest first."""
    clean = str(symbol or "").strip().upper()
    if not clean:
        return []
    ensure_extended_tables()

    db_url = get_database_url()
    if not db_url or not _query_available():
        return _demo_earnings_history(clean) if fallback_demo else []

    try:
        from psycopg.rows import dict_row
        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select symbol, fiscal_year, fiscal_period, quarter_label,
                           earnings_date, actual_eps, estimated_eps, surprise_eps_pct,
                           actual_revenue, estimated_revenue, surprise_revenue_pct,
                           post_earnings_move_1d, pre_close, post_close, source
                    from earnings_history
                    where upper(symbol) = %s
                    order by earnings_date desc nulls last, fiscal_year desc, fiscal_period desc
                    limit %s
                    """,
                    (clean, max(1, min(24, limit))),
                )
                rows = [dict(r) for r in cur.fetchall()]
        return rows if rows else (_demo_earnings_history(clean) if fallback_demo else [])
    except Exception as exc:
        logger.debug("earnings_history query failed for %s: %s", clean, exc)
        _trip_db_circuit()
        return _demo_earnings_history(clean) if fallback_demo else []


def get_next_earnings_date(symbol: str) -> dict[str, Any] | None:
    """Return the next expected earnings date for a symbol (Yahoo-sourced)."""
    from finagent.earnings.yahoo_scraper import fetch_next_earnings_date
    try:
        result = fetch_next_earnings_date(symbol)
        if result:
            # Compute countdown
            try:
                dt = datetime.fromisoformat(result["earnings_date"].replace("Z", "+00:00"))
                days_away = (dt.date() - date.today()).days
                result["days_away"] = days_away
            except Exception:
                result["days_away"] = None
        return result
    except Exception as exc:
        logger.debug("get_next_earnings_date failed for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Analyst reports
# ---------------------------------------------------------------------------

def upsert_analyst_report(record: dict[str, Any], database_url: str | None = None) -> bool:
    db_url = get_database_url(database_url)
    if not db_url or not ensure_extended_tables(db_url):
        return False
    symbol = str(record.get("symbol") or "").strip().upper()
    source_url = str(record.get("source_url") or "").strip()
    if not symbol or not source_url:
        return False
    try:
        with connect_postgres(db_url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into analyst_reports (
                        symbol, title, provider, source_url, report_date,
                        outlook, summary, target_price, rating,
                        fiscal_quarter, text_excerpt, updated_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    on conflict (source_url) do update set
                        title = excluded.title,
                        provider = coalesce(excluded.provider, analyst_reports.provider),
                        report_date = coalesce(excluded.report_date, analyst_reports.report_date),
                        outlook = coalesce(excluded.outlook, analyst_reports.outlook),
                        summary = coalesce(excluded.summary, analyst_reports.summary),
                        target_price = coalesce(excluded.target_price, analyst_reports.target_price),
                        rating = coalesce(excluded.rating, analyst_reports.rating),
                        fiscal_quarter = coalesce(excluded.fiscal_quarter, analyst_reports.fiscal_quarter),
                        updated_at = now()
                    """,
                    (
                        symbol,
                        str(record.get("title") or "Analyst Report"),
                        str(record.get("provider") or ""),
                        source_url,
                        record.get("report_date"),
                        str(record.get("outlook") or "neutral"),
                        str(record.get("summary") or ""),
                        str(record.get("target_price") or ""),
                        str(record.get("rating") or ""),
                        str(record.get("fiscal_quarter") or ""),
                        str(record.get("text_excerpt") or "")[:4000],
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.warning("analyst_report upsert failed for %s: %s", symbol, exc)
        return False


def get_analyst_reports(symbol: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return analyst reports for a symbol, newest first."""
    clean = str(symbol or "").strip().upper()
    if not clean:
        return []
    ensure_extended_tables()

    db_url = get_database_url()
    if not db_url or not _query_available():
        return []

    try:
        from psycopg.rows import dict_row
        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select symbol, title, provider, source_url, report_date,
                           outlook, summary, target_price, rating, fiscal_quarter
                    from analyst_reports
                    where upper(symbol) = %s
                    order by report_date desc nulls last, created_at desc
                    limit %s
                    """,
                    (clean, max(1, min(20, limit))),
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("analyst_reports query failed for %s: %s", clean, exc)
        _trip_db_circuit()
        return []


def get_earnings_forward_estimates(symbol: str) -> dict[str, Any]:
    """Return forward estimates (current Q, next Q, current year, next year) from Yahoo."""
    from finagent.earnings.yahoo_scraper import fetch_earnings_trend
    try:
        return fetch_earnings_trend(symbol)
    except Exception as exc:
        logger.debug("forward estimates failed for %s: %s", symbol, exc)
        return {}


# ---------------------------------------------------------------------------
# Demo fallback for earnings history
# ---------------------------------------------------------------------------

def _demo_earnings_history(symbol: str) -> list[dict[str, Any]]:
    """Return plausible demo earnings history for display when DB is empty."""
    today = date.today()
    records = []
    for i in range(1, 9):
        qnum = ((4 - i) % 4) + 1
        yr = today.year - ((i - 1) // 4)
        dt = today - timedelta(days=i * 90)
        actual = round(10.0 + i * 0.5, 2)
        estimated = round(actual * (0.95 + 0.1 * ((i % 3) / 3)), 2)
        surprise = round((actual - estimated) / abs(estimated) * 100, 2) if estimated else None
        records.append({
            "symbol": symbol,
            "fiscal_year": yr,
            "fiscal_period": f"Q{qnum}",
            "quarter_label": f"{qnum}Q{yr}",
            "earnings_date": dt.isoformat() + "T00:00:00Z",
            "actual_eps": actual,
            "estimated_eps": estimated,
            "surprise_eps_pct": surprise,
            "actual_revenue": round(5000 + i * 200, 0),
            "estimated_revenue": round((5000 + i * 200) * 0.97, 0),
            "surprise_revenue_pct": round(3.0 * ((i % 2) * 2 - 1), 2),
            "post_earnings_move_1d": round(1.5 * ((i % 2) * 2 - 1), 2),
            "pre_close": None,
            "post_close": None,
            "source": "demo",
        })
    return records



