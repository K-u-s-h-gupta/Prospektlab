"""Earnings Tab API routes - simplified to 3 core endpoints."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from finagent.earnings.service import (
    get_earnings_calendar,
    get_earnings_companies,
    get_earnings_overview,
    get_earnings_result,
    get_earnings_stats,
    ensure_earnings_detail_for_result,
)
from finagent.earnings.scraper import run_earnings_ingestion

router = APIRouter(prefix="/earnings", tags=["earnings"])


def _default_start() -> str:
    return (date.today() - timedelta(days=7)).isoformat()


def _default_end() -> str:
    return (date.today() + timedelta(days=21)).isoformat()


# ---------------------------------------------------------------------------
# Core 3 endpoints for new Earnings Tab
# ---------------------------------------------------------------------------

@router.get("/calendar")
async def earnings_calendar(
    start_date: str = Query(default_factory=_default_start),
    end_date: str = Query(default_factory=_default_end),
) -> dict[str, Any]:
    """Return dates with earnings company counts (date strip + monthly grid data).
    
    Returns:
      {
        start_date, end_date,
        dates: [{date, company_count, summary, sectors, timings}]
      }
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_earnings_calendar, start_date, end_date),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Earnings calendar request timed out. Please retry.")


@router.get("/companies")
async def earnings_companies(
    date_: str | None = Query(default=None, alias="date"),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    index: str = Query(default="All"),
    market_cap: str = Query(default="All"),
    sector: str = Query(default="All"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    """Return companies with earnings on a given date, or across a date range.
    
    Provide either `date` for a single date, or `start_date` + `end_date` for a range.
    
    Returns:
      {
        date, start_date, end_date, mode, page, page_size, total,
        items: [{
          event_uid, symbol, name, sector, index, market_cap, date, timing,
          fiscal_quarter, highlights, is_past,
          eps_actual, eps_estimated, eps_surprise_pct, post_earnings_move_1d,
          revenue_yoy_pct, pat_yoy_pct, revenue_actual, revenue_surprise_pct
        }]
      }
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                get_earnings_companies,
                target_date=date_,
                start_date=start_date,
                end_date=end_date,
                index=index,
                market_cap=market_cap,
                sector=sector,
                page=page,
                page_size=page_size,
            ),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Earnings companies request timed out. Please retry.")


@router.get("/stats")
async def earnings_stats(
    date_: str = Query(alias="date"),
) -> dict[str, Any]:
    """Return aggregate earnings counts for the selected date."""
    return await asyncio.to_thread(get_earnings_stats, date_)


@router.get("/overview")
async def earnings_overview(
    start_date: str = Query(default_factory=_default_start),
    end_date: str = Query(default_factory=_default_end),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    """Combined endpoint: calendar + companies for the overview Earnings Pulse.
    
    Returns both calendar dates and company items in a single response
    using a single DB connection to avoid timeout issues.
    
    On timeout or DB failure, returns a valid empty response (never a 504)
    so the frontend can display a graceful empty state instead of an error.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_earnings_overview, start_date, end_date, page_size),
            timeout=20.0,
        )
    except (asyncio.TimeoutError, Exception):
        # Return a valid empty response instead of an error.
        # The background warmup thread will populate caches for the next request.
        return {
            "calendar": {
                "start_date": start_date,
                "end_date": end_date,
                "dates": [],
                "source": "pending",
            },
            "companies": {
                "start_date": start_date,
                "end_date": end_date,
                "mode": "range",
                "page": 1,
                "page_size": page_size,
                "total": 0,
                "items": [],
            },
        }


@router.get("/result/{symbol}")
async def earnings_result(
    symbol: str,
    background_tasks: BackgroundTasks,
    date_: str = Query(alias="date"),
) -> dict[str, Any]:
    """Return complete result detail for a past earnings announcement (Perplexity-style).
    
    Returns:
      {
        symbol, name, sector, fiscal_quarter, timing, meeting_date, current_price,
        quarter_tabs: [{label, fiscal_year, fiscal_period, move_1d_pct, is_current, is_future}],
        revenue: {actual, estimated, beat_miss_pct},
        eps: {actual, estimated, beat_miss_pct},
        move_1d: {pct, pre_close, post_close},
        highlights: [list of AI-generated bullets],
        transcript: {prepared_remarks, qa},
        documents: [{type, title, url, storage_path}],
        financials: {rows: [{key, label, unit, current, previous_quarter, same_quarter_last_year, qoq_pct, yoy_pct}]}
      }
    """
    result = await asyncio.to_thread(get_earnings_result, symbol, date_)
    if not result:
        raise HTTPException(status_code=404, detail=f"Earnings result not found for {symbol.upper()} on {date_}")
    financials = result.get("financials") if isinstance(result, dict) else {}
    if isinstance(financials, dict) and financials.get("source") == "announcement_fallback":
        background_tasks.add_task(ensure_earnings_detail_for_result, symbol, date_)
    return result


@router.post("/sync")
async def earnings_sync(
    background_tasks: BackgroundTasks,
    start_date: str = Query(default_factory=_default_start),
    end_date: str = Query(default_factory=_default_end),
) -> dict[str, Any]:
    """Trigger immediate earnings data sync from NSE/BSE.
    
    This runs the scraper in the background to fetch the latest announcements.
    Useful when the database is empty or stale.
    """
    def _sync():
        from finagent.earnings.analysis import parse_date
        start = parse_date(start_date) or date.today() - timedelta(days=7)
        end = parse_date(end_date) or date.today() + timedelta(days=30)
        return run_earnings_ingestion(start_date=start, end_date=end)
    
    background_tasks.add_task(_sync)
    return {"status": "sync_started", "start_date": start_date, "end_date": end_date}
