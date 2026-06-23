"""Yahoo Finance market + fundamentals enrichment.

Uses the `yfinance` library which handles session management, rate-limiting,
and User-Agent rotation automatically. Falls back to direct API calls if
yfinance is unavailable.

Supports Indian tickers with .NS (NSE) and .BO (BSE) suffixes natively.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Fix: curl_cffi (used by yfinance) cannot encode CA cert paths containing
# non-ASCII characters (e.g. Hindi directory names on Windows).
# ---------------------------------------------------------------------------
import os
import shutil
import tempfile
try:
    import certifi
    _safe_cacert = os.path.join(tempfile.gettempdir(), "cacert.pem")
    try:
        _safe_cacert.encode('ascii')
    except UnicodeEncodeError:
        _safe_cacert = "C:\\temp\\cacert.pem"
        os.makedirs("C:\\temp", exist_ok=True)
    if not os.path.exists(_safe_cacert):
        shutil.copy2(certifi.where(), _safe_cacert)
    os.environ["CURL_CA_BUNDLE"] = _safe_cacert
    os.environ["REQUESTS_CA_BUNDLE"] = _safe_cacert
    os.environ["SSL_CERT_FILE"] = _safe_cacert
except Exception:
    pass
# ---------------------------------------------------------------------------

def _httpx_trust_env() -> bool:
    raw = os.environ.get("FINAGENT_HTTP_TRUST_ENV", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


if not _httpx_trust_env():
    for _proxy_key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(_proxy_key, None)

_YFINANCE_CACHE_DIR = os.path.join(tempfile.gettempdir(), "finagent_yfinance_cache")
try:
    os.makedirs(_YFINANCE_CACHE_DIR, exist_ok=True)
except Exception:
    pass

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote as url_quote

import httpx

logger = logging.getLogger("finagent.yahoo")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


_HISTORY_LOOKBACK_S = 365 * 24 * 60 * 60 * 10

# ---------------------------------------------------------------------------
# Shared in-process cache + rate limiter for yfinance to avoid 429s
# ---------------------------------------------------------------------------
_FETCH_CACHE: dict[str, tuple[float, YahooQuote | None]] = {}
_CHART_CACHE: dict[str, tuple[float, YahooQuote | None]] = {}
_CHART_CACHE_TTL_SECONDS = 90
_CACHE_TTL_SECONDS = 900  # default 15 minutes; callers can request fresher reads
_LAST_YF_CALL_TIME: float = 0.0
_MIN_YF_INTERVAL_SECONDS = _float_env("FINAGENT_YF_MIN_INTERVAL_S", 0.15)
_MIN_CHART_INTERVAL_SECONDS = _float_env("FINAGENT_YAHOO_CHART_MIN_INTERVAL_S", 0.25)
_LAST_CHART_CALL_TIME: float = 0.0
_YF_RATE_LIMIT_LOCK = threading.Lock()
_CHART_RATE_LIMIT_LOCK = threading.Lock()


def _cached_yahoo_quote(ticker: str, *, ttl_s: float | None = None) -> YahooQuote | None:
    """Return cached quote if still fresh; otherwise None."""
    cached = _FETCH_CACHE.get(ticker)
    max_age = _CACHE_TTL_SECONDS if ttl_s is None else max(0.0, float(ttl_s))
    if cached and (time.time() - cached[0]) < max_age:
        return cached[1]
    return None


def _set_yahoo_quote_cache(ticker: str, result: YahooQuote | None) -> None:
    """Store result in cache with current timestamp."""
    _FETCH_CACHE[ticker] = (time.time(), result)


def _rate_limited_fetch_yfinance_sync(ticker: str) -> YahooQuote | None:
    """Enforce min interval between yfinance calls to avoid rate limits."""
    global _LAST_YF_CALL_TIME
    if _MIN_YF_INTERVAL_SECONDS > 0:
        with _YF_RATE_LIMIT_LOCK:
            elapsed = time.time() - _LAST_YF_CALL_TIME
            if elapsed < _MIN_YF_INTERVAL_SECONDS:
                time.sleep(_MIN_YF_INTERVAL_SECONDS - elapsed)
            _LAST_YF_CALL_TIME = time.time()
    return _fetch_yfinance_sync(ticker)


@dataclass
class YahooQuote:
    ticker: str
    name: str | None
    currency: str | None
    exchange: str | None
    price: float | None
    previous_close: float | None
    change_pct: float | None
    market_cap: float | None
    fifty_two_week_high: float | None
    fifty_two_week_low: float | None
    series_dates: list[str]
    series_closes: list[float]
    source_url: str
    financial_metrics: dict[str, float] = field(default_factory=dict)
    annual_revenue: list[float] = field(default_factory=list)
    annual_revenue_dates: list[str] = field(default_factory=list)
    annual_net_income: list[float] = field(default_factory=list)
    annual_net_income_dates: list[str] = field(default_factory=list)
    business_summary: str | None = None
    company_info: dict[str, Any] = field(default_factory=dict)


def _safe_float(val) -> float | None:
    """Extract float from raw value or yfinance dict-like object."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fetch_yfinance_sync(ticker: str) -> YahooQuote | None:
    """Synchronous yfinance fetch — runs in a thread executor."""
    try:
        import yfinance as yf
        try:
            if hasattr(yf, "set_tz_cache_location"):
                yf.set_tz_cache_location(_YFINANCE_CACHE_DIR)
        except Exception:
            pass
    except ImportError:
        logger.warning("yfinance not installed — pip install yfinance")
        return None

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        name = info.get("longName") or info.get("shortName")
        currency = info.get("currency")
        exchange = info.get("exchange") or info.get("exchangeName")
        price = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))
        prev_close = _safe_float(info.get("regularMarketPreviousClose") or info.get("previousClose"))
        market_cap = _safe_float(info.get("marketCap"))
        high52 = _safe_float(info.get("fiftyTwoWeekHigh"))
        low52 = _safe_float(info.get("fiftyTwoWeekLow"))
        change_pct: float | None = None
        if price is not None and prev_close and prev_close != 0:
            change_pct = (price - prev_close) / prev_close * 100.0

        # Financial metrics
        metrics: dict[str, float] = {}
        metric_map = {
            "total_revenue": "totalRevenue",
            "ebitda": "ebitda",
            "gross_margins": "grossMargins",
            "operating_margins": "operatingMargins",
            "profit_margins": "profitMargins",
            "revenue_growth": "revenueGrowth",
            "earnings_growth": "earningsGrowth",
            "return_on_assets": "returnOnAssets",
            "return_on_equity": "returnOnEquity",
            "free_cashflow": "freeCashflow",
            "operating_cashflow": "operatingCashflow",
            "total_cash": "totalCash",
            "total_debt": "totalDebt",
            "debt_to_equity": "debtToEquity",
            "current_ratio": "currentRatio",
            "quick_ratio": "quickRatio",
            "target_mean_price": "targetMeanPrice",
            "dividend_yield": "dividendYield",
            "trailing_pe": "trailingPE",
            "forward_pe": "forwardPE",
            "price_to_book": "priceToBook",
            "book_value": "bookValue",
            "enterprise_value": "enterpriseValue",
            "market_cap": "marketCap",
            "beta": "beta",
        }
        for key, yf_key in metric_map.items():
            v = _safe_float(info.get(yf_key))
            if v is not None:
                metrics[key] = v

        # Business summary
        summary_text = info.get("longBusinessSummary") or info.get("description")

        # Company profile facts (qualitative — not part of numeric metrics)
        company_info: dict[str, Any] = {}
        _info_map = {
            "sector": "sector",
            "industry": "industry",
            "website": "website",
            "employees": "fullTimeEmployees",
            "city": "city",
            "state": "state",
            "country": "country",
            "long_name": "longName",
            "exchange_name": "fullExchangeName",
        }
        for out_key, yf_key in _info_map.items():
            val = info.get(yf_key)
            if val not in (None, ""):
                company_info[out_key] = val

        # Price history (last 1 month, daily)
        series_dates: list[str] = []
        series_closes: list[float] = []
        try:
            hist = t.history(period="5y", interval="1d", auto_adjust=True)
            if hist is not None and not hist.empty:
                for ts, row in hist.iterrows():
                    try:
                        d = ts.strftime("%Y-%m-%d")
                        c = _safe_float(row.get("Close"))
                        if d and c is not None:
                            series_dates.append(d)
                            series_closes.append(c)
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug("price history fetch failed for %s: %s", ticker, exc)

        # Annual revenue & net income history (last 5 years)
        revenue_values: list[float] = []
        revenue_dates: list[str] = []
        net_values: list[float] = []
        net_dates: list[str] = []
        try:
            financials = t.financials  # annual P&L
            if financials is not None and not financials.empty:
                # yfinance returns columns as DatetimeIndex (most recent first)
                for col in financials.columns:
                    date_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]
                    rev_row = financials.loc["Total Revenue"] if "Total Revenue" in financials.index else None
                    ni_row = financials.loc["Net Income"] if "Net Income" in financials.index else None
                    if rev_row is not None:
                        v = _safe_float(rev_row.get(col))
                        if v is not None and date_str not in revenue_dates:
                            revenue_dates.append(date_str)
                            revenue_values.append(v)
                    if ni_row is not None:
                        v = _safe_float(ni_row.get(col))
                        if v is not None and date_str not in net_dates:
                            net_dates.append(date_str)
                            net_values.append(v)
        except Exception as exc:
            logger.debug("financials fetch failed for %s: %s", ticker, exc)

        # Sort history oldest-first for CAGR calculations downstream
        if revenue_values and revenue_dates:
            paired = sorted(zip(revenue_dates, revenue_values))
            revenue_dates, revenue_values = [p[0] for p in paired], [p[1] for p in paired]
        if net_values and net_dates:
            paired = sorted(zip(net_dates, net_values))
            net_dates, net_values = [p[0] for p in paired], [p[1] for p in paired]

        # Bail if there's truly nothing usable
        if not any([price, market_cap, series_closes, metrics, revenue_values, name]):
            logger.info("yfinance: no usable data for %s", ticker)
            return None

        return YahooQuote(
            ticker=ticker.upper(),
            name=name,
            currency=currency,
            exchange=exchange,
            price=price,
            previous_close=prev_close,
            change_pct=change_pct,
            market_cap=market_cap,
            fifty_two_week_high=high52,
            fifty_two_week_low=low52,
            series_dates=series_dates,
            series_closes=series_closes,
            source_url=f"https://finance.yahoo.com/quote/{ticker.upper()}",
            financial_metrics=metrics,
            annual_revenue=revenue_values,
            annual_revenue_dates=revenue_dates,
            annual_net_income=net_values,
            annual_net_income_dates=net_dates,
            business_summary=str(summary_text).strip() if summary_text else None,
            company_info=company_info,
        )

    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return None


def _cached_yahoo_chart(ticker: str, *, ttl_s: float | None = None) -> YahooQuote | None:
    cached = _CHART_CACHE.get(ticker)
    max_age = _CHART_CACHE_TTL_SECONDS if ttl_s is None else max(0.0, float(ttl_s))
    if cached and (time.time() - cached[0]) < max_age:
        return cached[1]
    return None


def _set_yahoo_chart_cache(ticker: str, result: YahooQuote | None) -> None:
    _CHART_CACHE[ticker] = (time.time(), result)


async def fetch_yahoo_chart(
    ticker: str,
    *,
    range_: str = "5y",
    interval: str = "1d",
    timeout_s: float = 4.0,
    cache_ttl_s: float | None = None,
) -> YahooQuote | None:
    """Fetch lightweight quote/history from Yahoo chart JSON without yfinance."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None
    cached = _cached_yahoo_chart(ticker, ttl_s=cache_ttl_s)
    if cached is not None:
        return cached
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(ticker, safe='')}"
        f"?range={url_quote(range_)}&interval={url_quote(interval)}&includePrePost=false"
    )
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    result: YahooQuote | None = None
    global _LAST_CHART_CALL_TIME
    if _MIN_CHART_INTERVAL_SECONDS > 0:
        with _CHART_RATE_LIMIT_LOCK:
            elapsed = time.time() - _LAST_CHART_CALL_TIME
            if elapsed < _MIN_CHART_INTERVAL_SECONDS:
                time.sleep(_MIN_CHART_INTERVAL_SECONDS - elapsed)
            _LAST_CHART_CALL_TIME = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout_s, headers=headers, trust_env=_httpx_trust_env()) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                _set_yahoo_chart_cache(ticker, None)
                return None
            data = resp.json()
        chart = (data.get("chart") or {}) if isinstance(data, dict) else {}
        rows = chart.get("result") or []
        if not rows:
            _set_yahoo_chart_cache(ticker, None)
            return None
        row = rows[0] or {}
        meta = row.get("meta") or {}
        quote_rows = ((row.get("indicators") or {}).get("quote") or [{}])
        quote_data = quote_rows[0] if quote_rows else {}
        timestamps = row.get("timestamp") or []
        closes = quote_data.get("close") or []
        series_dates: list[str] = []
        series_closes: list[float] = []
        for idx, raw_close in enumerate(closes):
            close = _safe_float(raw_close)
            if close is None:
                continue
            ts = timestamps[idx] if idx < len(timestamps) else None
            date_text = ""
            if isinstance(ts, (int, float)):
                try:
                    date_text = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
                except Exception:
                    date_text = ""
            series_dates.append(date_text)
            series_closes.append(close)
        last_close = series_closes[-1] if series_closes else None
        price = _safe_float(meta.get("regularMarketPrice")) or last_close
        prev = _safe_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
        change_pct = ((price - prev) / prev * 100.0) if (price is not None and prev) else None
        if not any([price, series_closes]):
            _set_yahoo_chart_cache(ticker, None)
            return None
        result = YahooQuote(
            ticker=ticker,
            name=meta.get("longName") or meta.get("shortName") or meta.get("symbol"),
            currency=meta.get("currency"),
            exchange=meta.get("exchangeName") or meta.get("fullExchangeName"),
            price=price,
            previous_close=prev,
            change_pct=change_pct,
            market_cap=None,
            fifty_two_week_high=_safe_float(meta.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_safe_float(meta.get("fiftyTwoWeekLow")),
            series_dates=series_dates,
            series_closes=series_closes,
            source_url=f"https://finance.yahoo.com/quote/{ticker}",
        )
        return result
    except Exception as exc:
        logger.debug("Yahoo chart fetch failed for %s: %s", ticker, exc)
        return None
    finally:
        _set_yahoo_chart_cache(ticker, result)


async def fetch_yahoo_quote(
    ticker: str,
    *,
    timeout_s: float = 30.0,
    cache_ttl_s: float | None = None,
) -> YahooQuote | None:
    """Async wrapper: runs yfinance in a thread executor to avoid blocking.
    
    Uses in-process caching and rate-limiting (2s min interval) to reduce
    Yahoo Finance 429 rate-limit errors. cache_ttl_s lets public market
    widgets request fresher data without changing slower research workflows.
    """
    if not ticker:
        return None
    # Check cache first
    cached = _cached_yahoo_quote(ticker, ttl_s=cache_ttl_s)
    if cached is not None:
        logger.debug("yfinance cache hit for %s", ticker)
        return cached
    logger.info("[MCP-USE] fundamentals | tool=profile | args={'symbol': '%s'}", ticker)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("fundamentals")
    except ImportError:
        pass
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _rate_limited_fetch_yfinance_sync, ticker),
            timeout=timeout_s,
        )
        _set_yahoo_quote_cache(ticker, result)
        return result
    except asyncio.TimeoutError:
        logger.warning("yfinance timeout for %s (>%ss)", ticker, timeout_s)
        _set_yahoo_quote_cache(ticker, None)
        return None
    except Exception as exc:
        logger.warning("fetch_yahoo_quote failed for %s: %s", ticker, exc)
        _set_yahoo_quote_cache(ticker, None)
        return None
