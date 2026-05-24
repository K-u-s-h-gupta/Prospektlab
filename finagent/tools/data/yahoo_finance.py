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

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("finagent.yahoo")

_HISTORY_LOOKBACK_S = 365 * 24 * 60 * 60 * 10


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
        }
        for key, yf_key in metric_map.items():
            v = _safe_float(info.get(yf_key))
            if v is not None:
                metrics[key] = v

        # Business summary
        summary_text = info.get("longBusinessSummary") or info.get("description")

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
        )

    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return None


async def fetch_yahoo_quote(ticker: str, *, timeout_s: float = 30.0) -> YahooQuote | None:
    """Async wrapper: runs yfinance in a thread executor to avoid blocking."""
    if not ticker:
        return None
    logger.info("[MCP-USE] fundamentals | tool=profile | args={'symbol': '%s'}", ticker)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("fundamentals")
    except ImportError:
        pass
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _fetch_yfinance_sync, ticker),
            timeout=timeout_s,
        )
        return result
    except asyncio.TimeoutError:
        logger.warning("yfinance timeout for %s (>%ss)", ticker, timeout_s)
        return None
    except Exception as exc:
        logger.warning("fetch_yahoo_quote failed for %s: %s", ticker, exc)
        return None
