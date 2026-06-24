"""Yahoo Finance earnings data scraper.

Fetches quarterly earnings history (actual vs estimated EPS/Revenue with
surprise %), forward estimates, and quarterly financial statements for Indian
stocks (*.NS suffix) via the public Yahoo Finance quoteSummary API.

No API key required. Rate-limited internally.
"""

from __future__ import annotations

import logging
import math
import os
import time
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger("finagent.earnings.yahoo_scraper")

_BASE = "https://query1.finance.yahoo.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}

_RATE_LOCK = threading.Lock()
_LAST_CALL: float = 0.0
_MIN_INTERVAL_S = float(os.getenv("FINAGENT_YAHOO_EARNINGS_MIN_INTERVAL_S", "1.0"))


def _throttle() -> None:
    global _LAST_CALL
    with _RATE_LOCK:
        elapsed = time.monotonic() - _LAST_CALL
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)
        _LAST_CALL = time.monotonic()


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _surprise_pct(actual: float | None, estimated: float | None) -> float | None:
    if actual is None or estimated is None or estimated == 0:
        return None
    return round((actual - estimated) / abs(estimated) * 100.0, 2)


def _nse_ticker(symbol: str) -> str:
    """Convert bare NSE symbol to Yahoo Finance ticker format."""
    s = symbol.strip().upper()
    # BSE numeric codes — skip Yahoo
    if s.isdigit():
        return ""
    if s.endswith(".NS") or s.endswith(".BO"):
        return s
    return f"{s}.NS"


def _quote_summary(ticker: str, modules: list[str]) -> dict[str, Any]:
    """Call /v10/finance/quoteSummary with requested modules."""
    _throttle()
    url = f"{_BASE}/v10/finance/quoteSummary/{ticker}"
    params = {"modules": ",".join(modules), "lang": "en-US", "region": "IN"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url, params=params, headers=_HEADERS)
            resp.raise_for_status()
            body = resp.json()
            result = body.get("quoteSummary", {}).get("result") or []
            return result[0] if result else {}
    except Exception as exc:
        logger.debug("Yahoo quoteSummary failed for %s: %s", ticker, exc)
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_earnings_history(symbol: str) -> list[dict[str, Any]]:
    """Return quarterly EPS history: actual, estimated, surprise %.

    Returns a list of records ordered most recent first.
    Each record:
      {symbol, fiscal_year, fiscal_period, earnings_date,
       actual_eps, estimated_eps, surprise_eps_pct}
    """
    ticker = _nse_ticker(symbol)
    if not ticker:
        return []

    data = _quote_summary(ticker, ["earningsHistory"])
    history = (
        data.get("earningsHistory", {})
        .get("history", [])
    )

    records: list[dict[str, Any]] = []
    for item in (history or []):
        if not isinstance(item, dict):
            continue
        actual_eps = _safe_float(
            (item.get("epsActual") or {}).get("raw")
        )
        est_eps = _safe_float(
            (item.get("epsEstimate") or {}).get("raw")
        )
        # Yahoo returns surprisePercent as a decimal fraction (e.g. -0.0168 = -1.68%)
        surprise_raw = _safe_float(
            (item.get("surprisePercent") or {}).get("raw")
        )
        surprise_eps = round(surprise_raw * 100, 2) if surprise_raw is not None else None
        if surprise_eps is None:
            surprise_eps = _surprise_pct(actual_eps, est_eps)

        # "period" is like "-3q", "-2q", "-1q", "0q" relative to today
        period = str(item.get("period") or "")

        # "quarter" is {"raw": <unix_epoch>, "fmt": "YYYY-MM-DD"} — the quarter end date
        quarter_obj = item.get("quarter") or {}
        quarter_epoch = None
        quarter_fmt: str | None = None
        if isinstance(quarter_obj, dict):
            quarter_epoch = quarter_obj.get("raw")
            quarter_fmt = str(quarter_obj.get("fmt") or "")
        elif isinstance(quarter_obj, (int, float)):
            quarter_epoch = quarter_obj

        # Parse earnings_date from the quarter epoch
        earnings_date: datetime | None = None
        if quarter_epoch:
            try:
                earnings_date = datetime.fromtimestamp(int(quarter_epoch), tz=timezone.utc)
            except Exception:
                pass

        # Infer Indian fiscal year & quarter from end date
        # Indian FY: Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar
        fiscal_year: int | None = None
        fiscal_period: str | None = None
        ref_date = earnings_date.date() if earnings_date else None
        if not ref_date and quarter_fmt:
            try:
                ref_date = date.fromisoformat(quarter_fmt[:10])
            except Exception:
                pass
        if ref_date:
            m = ref_date.month
            if m in (4, 5, 6):
                fiscal_period = "Q1"
                fiscal_year = ref_date.year + 1
            elif m in (7, 8, 9):
                fiscal_period = "Q2"
                fiscal_year = ref_date.year + 1
            elif m in (10, 11, 12):
                fiscal_period = "Q3"
                fiscal_year = ref_date.year + 1
            else:  # Jan, Feb, Mar
                fiscal_period = "Q4"
                fiscal_year = ref_date.year

        quarter_label = (
            f"{fiscal_period} FY{str(fiscal_year)[-2:]}"
            if fiscal_period and fiscal_year
            else quarter_fmt or period
        )

        records.append({
            "symbol": symbol.upper(),
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period,
            "period_raw": period,
            "quarter_label": quarter_label,
            "earnings_date": earnings_date.isoformat() if earnings_date else None,
            "actual_eps": actual_eps,
            "estimated_eps": est_eps,
            "surprise_eps_pct": surprise_eps,
            # Revenue comes from quarterly financials — filled separately
            "actual_revenue": None,
            "estimated_revenue": None,
            "surprise_revenue_pct": None,
        })

    return records


def fetch_earnings_trend(symbol: str) -> dict[str, Any]:
    """Return forward earnings estimates (current Q, next Q, current year).

    Returns:
      {
        current_quarter: {period, end_date, eps_estimate, revenue_estimate},
        next_quarter: {...},
        current_year: {...},
        next_year: {...},
      }
    
    DEPRECATED: Kept for backwards compatibility but not used in new Earnings Tab.
    """
    ticker = _nse_ticker(symbol)
    if not ticker:
        return {}

    data = _quote_summary(ticker, ["earningsTrend"])
    trend = data.get("earningsTrend", {}).get("trend", [])

    result: dict[str, Any] = {}
    period_map = {
        "0q": "current_quarter",
        "+1q": "next_quarter",
        "0y": "current_year",
        "+1y": "next_year",
    }
    for item in (trend or []):
        if not isinstance(item, dict):
            continue
        period_key = str(item.get("period") or "").lower()
        out_key = period_map.get(period_key)
        if not out_key:
            continue
        eps_est = _safe_float((item.get("earningsEstimate") or {}).get("avg", {}).get("raw"))
        rev_est = _safe_float((item.get("revenueEstimate") or {}).get("avg", {}).get("raw"))
        end_date = str(item.get("endDate") or "")
        result[out_key] = {
            "period": period_key,
            "end_date": end_date,
            "eps_estimate": eps_est,
            "revenue_estimate": rev_est,
        }

    return result


def fetch_quarterly_financials(symbol: str) -> list[dict[str, Any]]:
    """Return quarterly income statement data from Yahoo Finance.

    Each record:
      {symbol, period_date, fiscal_period_label,
       revenue, net_income, operating_income, gross_profit,
       ebitda, eps_basic, eps_diluted}
    
    DEPRECATED: Kept for backwards compatibility but not used in new Earnings Tab.
    """
    ticker = _nse_ticker(symbol)
    if not ticker:
        return []

    data = _quote_summary(ticker, ["incomeStatementHistoryQuarterly", "earningsHistory"])
    stmts = (
        data.get("incomeStatementHistoryQuarterly", {})
        .get("incomeStatementHistory", [])
    ) or []

    records: list[dict[str, Any]] = []
    for item in stmts:
        if not isinstance(item, dict):
            continue

        def _get(key: str) -> float | None:
            return _safe_float((item.get(key) or {}).get("raw"))

        period_date = str(item.get("endDate", {}).get("fmt") or "")
        records.append({
            "symbol": symbol.upper(),
            "period_date": period_date,
            "revenue": _get("totalRevenue"),
            "cost_of_revenue": _get("costOfRevenue"),
            "gross_profit": _get("grossProfit"),
            "operating_income": _get("operatingIncome"),
            "net_income": _get("netIncome"),
            "ebitda": _get("ebitda"),
            "interest_expense": _get("interestExpense"),
            "total_expenses": _get("totalOperatingExpenses"),
        })

    return records


def fetch_next_earnings_date(symbol: str) -> dict[str, Any] | None:
    """Return the next expected earnings date for a symbol.

    Returns: {symbol, earnings_date, fiscal_period} or None
    
    DEPRECATED: Kept for backwards compatibility but not used in new Earnings Tab.
    """
    ticker = _nse_ticker(symbol)
    if not ticker:
        return None

    data = _quote_summary(ticker, ["calendarEvents"])
    cal = data.get("calendarEvents", {})
    earnings = cal.get("earnings", {})
    dates = earnings.get("earningsDate", [])

    if not dates:
        return None

    for date_item in dates:
        raw = None
        if isinstance(date_item, dict):
            raw = date_item.get("raw")
        elif isinstance(date_item, (int, float)):
            raw = date_item
        if raw:
            try:
                dt = datetime.fromtimestamp(int(raw), tz=timezone.utc)
                if dt.date() >= date.today():
                    return {
                        "symbol": symbol.upper(),
                        "earnings_date": dt.isoformat(),
                        "earnings_date_fmt": dt.strftime("%d %b %Y"),
                    }
            except Exception:
                continue
    return None


def fetch_current_price(symbol: str) -> float | None:
    """Fetch the current market price for a symbol.
    
    Returns: float | None (price in INR, or None if fetch fails)
    """
    ticker = _nse_ticker(symbol)
    if not ticker:
        return None
    
    data = _quote_summary(ticker, ["price"])
    price_data = data.get("price", {})
    current_price = _safe_float(price_data.get("regularMarketPrice", {}).get("raw"))
    return current_price


def fetch_price_history_around_date(
    symbol: str, earnings_date: str, window_days: int = 3
) -> dict[str, Any]:
    """Fetch daily close prices around an earnings date to compute 1D move.

    Returns:
      {pre_close: float|None, post_close: float|None, move_1d_pct: float|None}
    """
    ticker = _nse_ticker(symbol)
    if not ticker:
        return {"pre_close": None, "post_close": None, "move_1d_pct": None}

    try:
        dt = datetime.fromisoformat(earnings_date.replace("Z", "+00:00"))
    except Exception:
        return {"pre_close": None, "post_close": None, "move_1d_pct": None}

    start = (dt.date() - timedelta(days=window_days + 1)).strftime("%Y-%m-%d")
    end = (dt.date() + timedelta(days=window_days + 1)).strftime("%Y-%m-%d")

    _throttle()
    url = f"{_BASE}/v8/finance/chart/{ticker}"
    params = {
        "period1": int((dt - timedelta(days=window_days + 1)).timestamp()),
        "period2": int((dt + timedelta(days=window_days + 1)).timestamp()),
        "interval": "1d",
        "events": "history",
    }
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url, params=params, headers=_HEADERS)
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        logger.debug("price history fetch failed for %s: %s", ticker, exc)
        return {"pre_close": None, "post_close": None, "move_1d_pct": None}

    try:
        chart = body["chart"]["result"][0]
        timestamps = chart["timestamp"]
        closes = chart["indicators"]["quote"][0]["close"]
        dated = sorted(
            [
                (datetime.fromtimestamp(ts, tz=timezone.utc).date(), c)
                for ts, c in zip(timestamps, closes)
                if c is not None
            ]
        )
    except Exception:
        return {"pre_close": None, "post_close": None, "move_1d_pct": None}

    target = dt.date()
    # Find day on or just before earnings, and day just after
    pre_close: float | None = None
    post_close: float | None = None
    for d, c in dated:
        if d <= target:
            pre_close = c
        elif d > target and post_close is None:
            post_close = c

    move_1d_pct: float | None = None
    if pre_close and post_close and pre_close != 0:
        move_1d_pct = round((post_close - pre_close) / pre_close * 100.0, 2)

    return {
        "pre_close": pre_close,
        "post_close": post_close,
        "move_1d_pct": move_1d_pct,
    }
