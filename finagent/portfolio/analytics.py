"""Portfolio analytics: compute risk metrics, performance vs benchmark, NAV history.

Uses the existing yfinance integration to fetch live quotes and historical prices.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

from finagent.portfolio_mirrors import PositionMirror

logger = logging.getLogger("finagent.portfolio.analytics")

# Silence noisy yfinance output (it prints to stderr for 404s even when we catch exceptions)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("yfinance.utils").setLevel(logging.CRITICAL)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)


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
        t = yf.Ticker(ticker)
        norm_period = _normalize_period(period)
        hist = t.history(period=norm_period, auto_adjust=True)
        if hist.empty:
            return {}
        return {
            "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
            "prices": hist["Close"].tolist(),
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
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", auto_adjust=True)
        if hist.empty:
            return {}
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
        return {
            "price": last,
            "prev_close": prev,
            "day_change_pct": (last - prev) / prev if prev else 0.0,
            "currency": t.info.get("currency", "INR"),
        }
    except Exception as exc:
        logger.debug("Yahoo quote fetch failed for %s: %s", ticker, exc)
        return {}


def _weighted_nav_history(
    positions: list[PositionMirror],
    period: str = "1y",
) -> dict[str, Any]:
    """Compute portfolio NAV series by weighting individual stock histories."""
    total_value = sum(p.market_value for p in positions if p.market_value > 0)
    if total_value <= 0:
        return {"dates": [], "prices": []}

    # Fetch all histories
    histories: list[dict[str, Any]] = []
    weights: list[float] = []
    for pos in positions:
        if pos.market_value <= 0:
            continue
        ticker = pos.exchange_symbol
        hist = _fetch_history_cached(ticker, period)
        if hist and hist.get("prices"):
            histories.append(hist)
            weights.append(pos.market_value / total_value)

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
                nav += h["prices"][idx] * w
        navs.append(nav)

    return {"dates": common_dates, "prices": navs}


def _compute_beta(portfolio_returns: np.ndarray, benchmark_returns: np.ndarray) -> float:
    """Rolling 1Y beta vs benchmark."""
    if len(portfolio_returns) < 10 or len(benchmark_returns) < 10:
        return 0.0
    # Align lengths
    min_len = min(len(portfolio_returns), len(benchmark_returns))
    p = portfolio_returns[-min_len:]
    b = benchmark_returns[-min_len:]
    cov = np.cov(p, b)[0, 1]
    var_b = np.var(b)
    return float(cov / var_b) if var_b else 0.0


def _max_drawdown(prices: list[float]) -> float:
    if not prices:
        return 0.0
    arr = np.array(prices)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(np.min(dd))


def _annualized_volatility(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns, ddof=1) * np.sqrt(252))


def _compute_correlation_matrix(
    positions: list[PositionMirror],
    period: str = "1y",
) -> dict[str, Any]:
    """Compute pairwise log-return correlation for top 12 equity holdings."""
    equity_positions = [p for p in positions if p.kind == "equity" and _is_valid_ticker(p.exchange_symbol)]
    top = sorted(equity_positions, key=lambda p: p.market_value, reverse=True)[:12]
    if len(top) < 2:
        return {"labels": [], "matrix": []}

    histories: dict[str, list[float]] = {}
    for pos in top:
        hist = _fetch_history_cached(pos.exchange_symbol, period=period)
        if hist and hist.get("prices") and len(hist["prices"]) > 10:
            histories[pos.exchange_symbol] = hist["prices"]

    labels = list(histories.keys())
    n = len(labels)
    if n < 2:
        return {"labels": [], "matrix": []}

    # Compute returns
    returns: dict[str, np.ndarray] = {}
    for sym, prices in histories.items():
        arr = np.array(prices)
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
                        corr = float(np.corrcoef(ri[-min_len:], rj[-min_len:])[0, 1])
                        row.append(round(corr, 2))
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
    total_value = sum(p.market_value for p in positions if p.market_value > 0)
    total_cost = sum(p.cost_basis for p in positions if p.cost_basis > 0)
    unrealized_pnl = total_value - total_cost
    unrealized_pnl_pct = (unrealized_pnl / total_cost) if total_cost else 0.0

    # Per-holding live quotes + P/L
    enriched_positions = []
    day_change_total = 0.0
    for pos in positions:
        ticker = pos.exchange_symbol
        quote = _fetch_quote(ticker) if pos.kind == "equity" else {}
        price = quote.get("price", pos.last_price or 0)
        day_change_pct = quote.get("day_change_pct", 0)
        # For MFs, day change is not available intraday; skip
        if pos.kind == "mf":
            day_change_pct = 0.0
        mkt_val = price * pos.quantity if price and pos.quantity else pos.market_value
        cost = pos.cost_basis or (pos.avg_cost * pos.quantity)
        pnl = mkt_val - cost if cost else None
        pnl_pct = (pnl / cost) if cost else None
        if pnl is not None:
            day_change_total += mkt_val * (day_change_pct or 0)
        enriched_positions.append({
            "symbol": pos.exchange_symbol,
            "name": pos.name or pos.symbol,
            "exchange": pos.exchange,
            "quantity": pos.quantity,
            "avg_cost": pos.avg_cost,
            "last_price": price,
            "market_value": mkt_val,
            "cost_basis": cost,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
            "day_change_pct": day_change_pct,
            "weight": mkt_val / total_value if total_value else 0,
            "kind": pos.kind,
            "sector": pos.sector,
            "industry": pos.industry,
            "isin": pos.isin,
            "amfi": pos.amfi,
        })

    # Benchmark ticker mapping
    benchmark_tickers = {
        "NIFTY50": "^NSEI",
        "NIFTYMIDCAP": "^NSEMDCP50",
        "SENSEX": "^BSESN",
        "NIFTYBANK": "^NSEBANK",
        "NIFTYIT": "^CNXIT",
    }
    benchmark_ticker = benchmark_tickers.get(benchmark, "^NSEI")

    # Portfolio NAV history vs benchmark
    port_hist = _weighted_nav_history(positions, period=period)
    bench_hist = _fetch_history_cached(benchmark_ticker, period=period)

    # Risk metrics
    beta = 0.0
    volatility = 0.0
    max_dd = 0.0
    if port_hist.get("prices") and len(port_hist["prices"]) > 10:
        port_rets = np.diff(np.log(np.array(port_hist["prices"])))
        max_dd = _max_drawdown(port_hist["prices"])
        volatility = _annualized_volatility(port_rets)
        if bench_hist.get("prices") and len(bench_hist["prices"]) > 10:
            bench_rets = np.diff(np.log(np.array(bench_hist["prices"])))
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
