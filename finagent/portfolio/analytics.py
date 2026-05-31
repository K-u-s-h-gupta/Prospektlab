"""Portfolio analytics: compute risk metrics, performance vs benchmark, NAV history.

Uses the existing yfinance integration to fetch live quotes and historical prices.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

import numpy as np

from finagent.portfolio_mirrors import PositionMirror

logger = logging.getLogger("finagent.portfolio.analytics")


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


def _configure_yfinance(yf: Any) -> None:
    try:
        if hasattr(yf, "set_tz_cache_location"):
            yf.set_tz_cache_location(_YFINANCE_CACHE_DIR)
    except Exception:
        pass

# Silence noisy yfinance output (it prints to stderr for 404s even when we catch exceptions)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("yfinance.utils").setLevel(logging.CRITICAL)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)


def _finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _positive_float(value: Any, default: float = 0.0) -> float:
    number = _finite_float(value)
    return number if number is not None and number > 0 else default


def _clean_price_series(values: list[Any] | None) -> list[float]:
    clean: list[float] = []
    for value in values or []:
        number = _finite_float(value)
        if number is not None and number > 0:
            clean.append(number)
    return clean


def _is_valid_ticker(symbol: str) -> bool:
    """Reject symbols that are clearly malformed (old sandbox data) or ISIN codes.
    
    ISINs look like 'INE123A01234' (starts with IN, 12 chars total).
    MF codes might be numeric ISINs. Both should be rejected for yfinance lookup.
    """
    if not symbol:
        return False
    s = symbol.strip().upper()
    
    # Reject ISIN codes (start with IN, ~12 chars, alphanumeric pattern)
    # Pattern: IN followed by 10 alphanumeric chars = typical ISIN
    import re
    if re.match(r"^IN[A-Z0-9]{10}$", s):
        return False
    
    # Reject numeric AMFI codes (e.g., 120308)
    if s.isdigit() and len(s) == 6:
        return False
    
    # Reject symbols with obvious malformations
    if len(s) > 16:
        return False
    if "," in s or ".." in s:
        return False
    if "LIMITED" in s or "LTD." in s or "LTD " in s:
        return False
    
    return True


# Period normalization: widget sends "1M"/"3M" but yfinance needs "1mo"/"3mo"
_PERIOD_MAP = {
    "1M": "1mo", "3M": "3mo", "6M": "6mo",
    "1Y": "1y", "2Y": "2y", "5Y": "5y",
    "YTD": "ytd", "MAX": "max",
}


def _normalize_period(period: str) -> str:
    """Convert frontend period strings to yfinance-valid strings."""
    return _PERIOD_MAP.get(period.upper(), period.lower())


# In-process TTL cache for yfinance calls (5 minutes)
import time
_FETCH_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL = 300  # seconds


def _fetch_history_cached(ticker: str, period: str = "1y") -> dict[str, Any]:
    """Fetch yfinance history with 5-minute in-process TTL cache."""
    key = (ticker, period)
    cached = _FETCH_CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]
    result = _fetch_history(ticker, period)
    _FETCH_CACHE[key] = (time.time(), result)
    return result


def _fetch_history(ticker: str, period: str = "1y") -> dict[str, Any]:
    """Fetch yfinance history; return {dates, prices, currency} or empty dict on failure."""
    if not _is_valid_ticker(ticker):
        return {}
    try:
        import yfinance as yf
        _configure_yfinance(yf)
        t = yf.Ticker(ticker)
        norm_period = _normalize_period(period)
        hist = t.history(period=norm_period, auto_adjust=True)
        if hist.empty:
            return {}
        dates: list[str] = []
        prices: list[float] = []
        for idx, value in zip(hist.index, hist["Close"].tolist()):
            price = _finite_float(value)
            if price is None or price <= 0:
                continue
            dates.append(idx.strftime("%Y-%m-%d"))
            prices.append(price)
        if not prices:
            return {}
        return {
            "dates": dates,
            "prices": prices,
            "currency": t.info.get("currency", "INR"),
        }
    except Exception as exc:
        logger.debug("Yahoo history fetch failed for %s (period=%s): %s", ticker, period, exc)
        return {}


def _fetch_quote(ticker: str) -> dict[str, Any]:
    """Fetch last price and day change."""
    if not _is_valid_ticker(ticker):
        return {}
    try:
        import yfinance as yf
        _configure_yfinance(yf)
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", auto_adjust=True)
        if hist.empty:
            return {}
        closes = _clean_price_series(hist["Close"].tolist())
        if not closes:
            return {}
        last = closes[-1]
        prev = closes[-2] if len(closes) > 1 else last
        return {
            "price": last,
            "prev_close": prev,
            "day_change_pct": (last - prev) / prev if prev else 0.0,
            "currency": t.info.get("currency", "INR"),
            "source": "yfinance",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.debug("Yahoo quote fetch failed for %s: %s", ticker, exc)
        return {}


def _weighted_nav_history(
    positions: list[PositionMirror],
    period: str = "1y",
) -> dict[str, Any]:
    """Compute portfolio NAV series by weighting individual stock histories."""
    total_value = sum(_positive_float(p.market_value) for p in positions)
    if total_value <= 0:
        return {"dates": [], "prices": []}

    # Fetch all histories
    histories: list[dict[str, Any]] = []
    weights: list[float] = []
    for pos in positions:
        market_value = _positive_float(pos.market_value)
        if market_value <= 0:
            continue
        ticker = pos.exchange_symbol
        hist = _fetch_history_cached(ticker, period)
        if hist and hist.get("prices"):
            histories.append(hist)
            weights.append(market_value / total_value)

    if not histories:
        return {"dates": [], "prices": []}

    # Renormalize weights after excluding MFs/invalid tickers
    total_weight = sum(weights)
    if total_weight > 0 and total_weight < 1.0:
        weights = [w / total_weight for w in weights]

    # Align by date intersection
    date_sets = [set(h["dates"]) for h in histories]
    common_dates = sorted(date_sets[0].intersection(*date_sets[1:]))
    if not common_dates:
        return {"dates": [], "prices": []}

    # Build fast lookup dicts: {date -> index} per history
    date_index_maps = [{d: i for i, d in enumerate(h["dates"])} for h in histories]

    navs: list[float] = []
    for d in common_dates:
        nav = 0.0
        for h, w, dim in zip(histories, weights, date_index_maps):
            idx = dim.get(d)
            if idx is not None:
                price = _finite_float(h["prices"][idx])
                if price is not None and price > 0:
                    nav += price * w
        navs.append(nav)

    return {"dates": common_dates, "prices": navs}


def _weighted_nav_history_from_enriched(
    positions: list[dict[str, Any]],
    period: str = "1y",
) -> dict[str, Any]:
    """Compute indexed portfolio history using repriced live market weights.

    The history intentionally uses the union of available holding dates, not the
    intersection. A newly listed or recently mapped holding should not collapse a
    5Y/MAX comparison down to only the shortest available series.
    """
    total_value = sum(_positive_float(p.get("market_value")) for p in positions)
    if total_value <= 0:
        return {"dates": [], "prices": []}

    weighted_series: list[tuple[float, dict[str, float]]] = []
    for pos in positions:
        market_value = _positive_float(pos.get("market_value"))
        ticker = str(pos.get("symbol") or "")
        if market_value <= 0 or not ticker:
            continue
        hist = _fetch_history_cached(ticker, period)
        dates = hist.get("dates") or []
        prices = hist.get("prices") or []
        if not dates or not prices:
            continue

        clean_pairs: list[tuple[str, float]] = []
        for date, price in zip(dates, prices):
            px = _finite_float(price)
            if not date or px is None or px <= 0:
                continue
            clean_pairs.append((str(date), px))
        if len(clean_pairs) < 2:
            continue

        first_price = clean_pairs[0][1]
        if first_price <= 0:
            continue
        index_by_date = {
            date: (price / first_price) * 100.0
            for date, price in clean_pairs
        }
        weighted_series.append((market_value / total_value, index_by_date))

    if not weighted_series:
        return {"dates": [], "prices": []}

    all_dates = sorted({date for _, series in weighted_series for date in series})
    if not all_dates:
        return {"dates": [], "prices": []}

    navs: list[float] = []
    aligned_dates: list[str] = []
    for d in all_dates:
        weighted_nav = 0.0
        active_weight = 0.0
        for weight, series in weighted_series:
            indexed_price = series.get(d)
            if indexed_price is None or indexed_price <= 0:
                continue
            weighted_nav += indexed_price * weight
            active_weight += weight
        if active_weight <= 0:
            continue
        nav = weighted_nav / active_weight
        if nav > 0 and math.isfinite(nav):
            navs.append(nav)
            aligned_dates.append(d)

    return {"dates": aligned_dates, "prices": navs}


def _compute_beta(portfolio_returns: np.ndarray, benchmark_returns: np.ndarray) -> float:
    """Rolling 1Y beta vs benchmark."""
    if len(portfolio_returns) < 10 or len(benchmark_returns) < 10:
        return 0.0
    # Align lengths
    min_len = min(len(portfolio_returns), len(benchmark_returns))
    p = portfolio_returns[-min_len:]
    b = benchmark_returns[-min_len:]
    cov = _finite_float(np.cov(p, b)[0, 1], 0.0) or 0.0
    var_b = _finite_float(np.var(b), 0.0) or 0.0
    beta = cov / var_b if var_b else 0.0
    return beta if math.isfinite(beta) else 0.0


def _max_drawdown(prices: list[float]) -> float:
    if not prices:
        return 0.0
    clean = _clean_price_series(prices)
    if not clean:
        return 0.0
    arr = np.array(clean)
    peak = np.maximum.accumulate(arr)
    dd = np.divide(arr - peak, peak, out=np.zeros_like(arr), where=peak > 0)
    result = _finite_float(np.min(dd), 0.0) or 0.0
    return result


def _annualized_volatility(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    result = _finite_float(np.std(returns, ddof=1) * np.sqrt(252), 0.0) or 0.0
    return result


def _compute_correlation_matrix(
    positions: list[PositionMirror],
    period: str = "1y",
) -> dict[str, Any]:
    """Compute pairwise log-return correlation for top 12 equity holdings."""
    equity_positions = [p for p in positions if (p.kind or "equity").strip().lower() == "equity" and _is_valid_ticker(p.exchange_symbol)]
    top = sorted(equity_positions, key=lambda p: _positive_float(p.market_value), reverse=True)[:12]
    if len(top) < 2:
        return {"labels": [], "matrix": []}

    histories: dict[str, list[float]] = {}
    for pos in top:
        hist = _fetch_history_cached(pos.exchange_symbol, period=period)
        if hist and hist.get("prices") and len(hist["prices"]) > 10:
            histories[pos.exchange_symbol] = _clean_price_series(hist["prices"])

    labels = list(histories.keys())
    n = len(labels)
    if n < 2:
        return {"labels": [], "matrix": []}

    # Compute returns
    returns: dict[str, np.ndarray] = {}
    for sym, prices in histories.items():
        arr = np.array(_clean_price_series(prices))
        if len(arr) > 10:
            returns[sym] = np.diff(np.log(arr))

    # Pairwise correlation
    matrix: list[list[float | None]] = []
    for i in range(n):
        row: list[float | None] = []
        for j in range(n):
            if i == j:
                row.append(1.0)
            elif i < j:
                ri = returns.get(labels[i])
                rj = returns.get(labels[j])
                if ri is not None and rj is not None:
                    min_len = min(len(ri), len(rj))
                    if min_len >= 5:
                        corr = _finite_float(np.corrcoef(ri[-min_len:], rj[-min_len:])[0, 1])
                        row.append(round(corr, 2) if corr is not None else None)
                    else:
                        row.append(None)
                else:
                    row.append(None)
            else:
                # Mirror lower triangle
                row.append(matrix[j][i])
        matrix.append(row)

    return {"labels": labels, "matrix": matrix}


def compute_portfolio_analytics(
    positions: list[PositionMirror],
    *,
    period: str = "1y",
    benchmark: str = "NIFTY50",
) -> dict[str, Any]:
    """Full analytics bundle for the portfolio mirror."""
    enriched_positions = []
    for pos in positions:
        ticker = pos.exchange_symbol
        kind = (pos.kind or "equity").strip().lower()
        quote = _fetch_quote(ticker) if kind == "equity" else {}
        quote_price = _positive_float(quote.get("price"))
        mirror_price = _positive_float(pos.last_price)
        price = quote_price or mirror_price
        day_change_pct = _finite_float(quote.get("day_change_pct"), 0.0) or 0.0
        if kind == "mf":
            day_change_pct = 0.0
        quantity = _positive_float(pos.quantity)
        mkt_val = price * quantity if price and quantity else _positive_float(pos.market_value)
        cost = _positive_float(pos.cost_basis) or (_positive_float(pos.avg_cost) * quantity)
        pnl = mkt_val - cost if cost else None
        pnl_pct = (pnl / cost) if cost else None
        enriched_positions.append({
            "symbol": pos.exchange_symbol,
            "name": pos.name or pos.symbol,
            "exchange": pos.exchange,
            "quantity": quantity,
            "avg_cost": _positive_float(pos.avg_cost),
            "last_price": price,
            "market_value": mkt_val,
            "cost_basis": cost,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
            "day_change_pct": day_change_pct,
            "day_change_value": mkt_val * day_change_pct,
            "weight": 0.0,
            "kind": kind,
            "sector": pos.sector,
            "industry": pos.industry,
            "isin": pos.isin,
            "amfi": pos.amfi,
            "price_source": quote.get("source") if quote_price else ("mirror" if mirror_price else "unavailable"),
            "as_of": quote.get("as_of") or pos.as_of,
        })

    total_value = sum(_positive_float(p.get("market_value")) for p in enriched_positions)
    total_cost = sum(_positive_float(p.get("cost_basis")) for p in enriched_positions)
    unrealized_pnl = total_value - total_cost if total_cost else 0.0
    unrealized_pnl_pct = (unrealized_pnl / total_cost) if total_cost else 0.0
    day_change_total = sum(_finite_float(p.get("day_change_value"), 0.0) or 0.0 for p in enriched_positions)
    for p in enriched_positions:
        p["weight"] = (_positive_float(p.get("market_value")) / total_value) if total_value else 0.0

    # Benchmark ticker mapping
    benchmark_tickers = {
        "NIFTY50": "^NSEI",
        "NIFTYMIDCAP": "^NSEMDCP50",
        "MIDCAP150": "^NSEMDCP50",
        "SENSEX": "^BSESN",
        "NIFTYBANK": "^NSEBANK",
        "NIFTYIT": "^CNXIT",
        "NEXT50": "^NSMIDCP",
        "SMALLCAP250": "^CNXSC",
    }
    benchmark_key = (benchmark or "NIFTY50").upper()
    benchmark_ticker = benchmark_tickers.get(benchmark_key, "^NSEI")

    # Portfolio NAV history vs benchmark
    port_hist = _weighted_nav_history_from_enriched(enriched_positions, period=period)
    bench_hist = _fetch_history_cached(benchmark_ticker, period=period)

    # Risk metrics
    beta = 0.0
    volatility = 0.0
    max_dd = 0.0
    if port_hist.get("prices") and len(port_hist["prices"]) > 10:
        port_prices = _clean_price_series(port_hist["prices"])
        port_rets = np.diff(np.log(np.array(port_prices)))
        max_dd = _max_drawdown(port_hist["prices"])
        volatility = _annualized_volatility(port_rets)
        if bench_hist.get("prices") and len(bench_hist["prices"]) > 10:
            bench_prices = _clean_price_series(bench_hist["prices"])
            bench_rets = np.diff(np.log(np.array(bench_prices)))
            beta = _compute_beta(port_rets, bench_rets)

    # Top-5 concentration
    sorted_by_weight = sorted(enriched_positions, key=lambda x: x["market_value"], reverse=True)[:5]
    top5 = [
        {"symbol": p["symbol"], "name": p["name"], "weight_pct": round(p["weight"] * 100, 2)}
        for p in sorted_by_weight
    ]

    # Sector and kind breakdowns
    sector_totals: dict[str, float] = {}
    kind_totals: dict[str, float] = {}
    for p in enriched_positions:
        sec = p.get("sector") or "Unknown"
        knd = p.get("kind") or "equity"
        val = p["market_value"] if p["market_value"] > 0 else 0
        sector_totals[sec] = sector_totals.get(sec, 0.0) + val
        kind_totals[knd] = kind_totals.get(knd, 0.0) + val
    total_val = sum(sector_totals.values())
    sector_breakdown = {s: v / total_val for s, v in sector_totals.items()} if total_val else {}
    kind_breakdown = {k: v / total_val for k, v in kind_totals.items()} if total_val else {}

    # Performance attribution: per-position contribution = return × weight
    attribution = []
    for p in enriched_positions:
        ret = p.get("unrealized_pnl_pct") or 0.0
        w = p.get("weight") or 0.0
        contribution = ret * w
        attribution.append({
            "symbol": p["symbol"],
            "name": p["name"],
            "return_pct": round(ret * 100, 2),
            "weight_pct": round(w * 100, 2),
            "contribution_pct": round(contribution * 100, 2),
        })
    attribution.sort(key=lambda x: x["contribution_pct"], reverse=True)
    top_contributors = [a for a in attribution if a["contribution_pct"] > 0][:5]
    top_detractors = [a for a in attribution if a["contribution_pct"] < 0][-5:]

    # Correlation heatmap: pairwise correlation for top 12 holdings
    correlation_matrix = _compute_correlation_matrix(positions, period=period)

    return {
        "status": "MIRROR_SYNCHRONIZED" if positions else "MIRROR_EMPTY",
        "sync_status": "MIRROR_SYNCHRONIZED" if positions else "MIRROR_EMPTY",
        "count": len(positions),
        "total_market_value": total_value,
        "total_cost_basis": total_cost,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "day_change_total": day_change_total,
        "day_change_pct": (day_change_total / total_value) if total_value else 0.0,
        "positions": enriched_positions,
        "sector_breakdown": sector_breakdown,
        "kind_breakdown": kind_breakdown,
        "risk": {
            "hhi": sum(p["weight"] * p["weight"] for p in enriched_positions),
            "beta_vs_nifty": round(beta, 2),
            "annualized_volatility_pct": round(volatility * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "top5_concentration": top5,
        },
        "attribution": {
            "top_contributors": top_contributors,
            "top_detractors": top_detractors,
        },
        "correlation_matrix": correlation_matrix,
        "history": {
            "portfolio": port_hist,
            "benchmark": bench_hist,
            "benchmark_label": benchmark,
        },
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
