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


_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_SAVED_PROXY_ENV: dict[str, str] = {}
if not _httpx_trust_env():
    for _proxy_key in _PROXY_KEYS:
        val = os.environ.pop(_proxy_key, None)
        if val is not None:
            _SAVED_PROXY_ENV[_proxy_key] = val

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


import threading
import time

_FETCH_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL = 900
_CACHE_LOCK = threading.Lock()
try:
    # Hard ceiling on each yfinance HTTP call so a throttled/unreachable Yahoo
    # (HTTP 429 triggers internal retries) cannot stall analytics for 30s+.
    _YF_TIMEOUT_S = max(2.0, float(os.environ.get("FINAGENT_YF_TIMEOUT_S", "6")))
except Exception:
    _YF_TIMEOUT_S = 6.0
_YF_RATE_LOCK = threading.Lock()
_LAST_YF_CALL_TIME: float = 0.0
try:
    _MIN_YF_INTERVAL_SECONDS = max(0.05, float(os.environ.get("FINAGENT_YF_MIN_INTERVAL_S", "0.35")))
except Exception:
    _MIN_YF_INTERVAL_SECONDS = 0.35


def _yf_rate_limit() -> None:
    global _LAST_YF_CALL_TIME
    with _YF_RATE_LOCK:
        elapsed = time.time() - _LAST_YF_CALL_TIME
        if elapsed < _MIN_YF_INTERVAL_SECONDS:
            time.sleep(_MIN_YF_INTERVAL_SECONDS - elapsed)
        _LAST_YF_CALL_TIME = time.time()


def _fetch_history_cached(ticker: str, period: str = "1y") -> dict[str, Any]:
    """Fetch yfinance history with 15-minute in-process TTL cache and rate limiting."""
    key = (ticker, period)
    with _CACHE_LOCK:
        cached = _FETCH_CACHE.get(key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]
    _yf_rate_limit()
    result = _fetch_history(ticker, period)
    with _CACHE_LOCK:
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
        hist = t.history(period=norm_period, auto_adjust=True, timeout=_YF_TIMEOUT_S)
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
        # Indian market data — default to INR. Avoid t.info (a separate, slow
        # yfinance network call that hangs hard when Yahoo throttles).
        return {
            "dates": dates,
            "prices": prices,
            "currency": "INR",
        }
    except Exception as exc:
        logger.debug("Yahoo history fetch failed for %s (period=%s): %s", ticker, period, exc)
        return {}


_QUOTE_CACHE: dict[str, tuple[float, dict]] = {}


def _fetch_quote_cached(ticker: str) -> dict[str, Any]:
    """Fetch last price and day change with 15-min cache + rate limiting."""
    with _CACHE_LOCK:
        cached = _QUOTE_CACHE.get(ticker)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]
    _yf_rate_limit()
    result = _fetch_quote(ticker)
    with _CACHE_LOCK:
        _QUOTE_CACHE[ticker] = (time.time(), result)
    return result


def _fetch_quote(ticker: str) -> dict[str, Any]:
    """Fetch last price and day change."""
    if not _is_valid_ticker(ticker):
        return {}
    try:
        import yfinance as yf
        _configure_yfinance(yf)
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", auto_adjust=True, timeout=_YF_TIMEOUT_S)
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
            "currency": "INR",
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


def _compute_beta(
    port_hist: dict[str, Any],
    bench_hist: dict[str, Any],
) -> float:
    """Compute beta by aligning portfolio and benchmark returns on common dates."""
    port_dates = port_hist.get("dates") or []
    port_prices = port_hist.get("prices") or []
    bench_dates = bench_hist.get("dates") or []
    bench_prices = bench_hist.get("prices") or []
    if len(port_dates) < 12 or len(bench_dates) < 12:
        return 0.0
    port_by_date = {d: p for d, p in zip(port_dates, port_prices) if _finite_float(p) and p > 0}
    bench_by_date = {d: p for d, p in zip(bench_dates, bench_prices) if _finite_float(p) and p > 0}
    common = sorted(set(port_by_date) & set(bench_by_date))
    if len(common) < 12:
        return 0.0
    p_arr = np.array([port_by_date[d] for d in common])
    b_arr = np.array([bench_by_date[d] for d in common])
    p_ret = np.diff(np.log(p_arr))
    b_ret = np.diff(np.log(b_arr))
    cov = _finite_float(np.cov(p_ret, b_ret)[0, 1], 0.0) or 0.0
    var_b = _finite_float(np.var(b_ret), 0.0) or 0.0
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


# Risk-free rate for risk-adjusted ratios (India ~6.5% 10Y G-sec). Env-overridable.
_RISK_FREE_RATE = _finite_float(os.environ.get("FINAGENT_RISK_FREE_RATE"), 0.065) or 0.065
_TRADING_DAYS = 252


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO date/datetime string into a tz-aware datetime, or None."""
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _annualized_return(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    return _finite_float(float(np.mean(returns)) * _TRADING_DAYS, 0.0) or 0.0


def _downside_deviation(returns: np.ndarray, target_daily: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < target_daily]
    if len(downside) < 1:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(downside - target_daily))))
    return _finite_float(rms * np.sqrt(_TRADING_DAYS), 0.0) or 0.0


def _risk_adjusted_ratios(port_rets: np.ndarray, ann_vol: float, max_dd: float) -> dict[str, Any]:
    """Sharpe / Sortino / Calmar from live portfolio returns. None when undefined."""
    if len(port_rets) < 12:
        return {"annualized_return_pct": None, "sharpe": None, "sortino": None, "calmar": None}
    ann_ret = _annualized_return(port_rets)
    excess = ann_ret - _RISK_FREE_RATE
    sharpe = (excess / ann_vol) if ann_vol > 0 else None
    dd = _downside_deviation(port_rets, _RISK_FREE_RATE / _TRADING_DAYS)
    sortino = (excess / dd) if dd > 0 else None
    calmar = (ann_ret / abs(max_dd)) if max_dd < 0 else None
    return {
        "annualized_return_pct": round(ann_ret * 100, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None and math.isfinite(sharpe) else None,
        "sortino": round(sortino, 2) if sortino is not None and math.isfinite(sortino) else None,
        "calmar": round(calmar, 2) if calmar is not None and math.isfinite(calmar) else None,
    }


def _historical_var_cvar(port_rets: np.ndarray, confidence: float = 0.95) -> dict[str, Any]:
    """1-day historical VaR + CVaR (expected shortfall) from the empirical return distribution."""
    if len(port_rets) < 20:
        return {"historical_var_pct": None, "cvar_pct": None, "confidence": confidence}
    losses = -port_rets  # positive number = loss
    var_threshold = float(np.quantile(losses, confidence))
    tail = losses[losses >= var_threshold]
    cvar = float(np.mean(tail)) if len(tail) else var_threshold
    return {
        "historical_var_pct": round(max(var_threshold, 0.0) * 100, 2),
        "cvar_pct": round(max(cvar, 0.0) * 100, 2),
        "confidence": confidence,
    }


def _drawdown_series(dates: list[str], prices: list[float]) -> list[dict[str, Any]]:
    """Underwater curve: % below running peak, downsampled to ~120 points."""
    pairs = [(d, p) for d, p in zip(dates or [], prices or []) if _finite_float(p) and p and p > 0]
    if len(pairs) < 2:
        return []
    arr = np.array([p for _, p in pairs])
    peak = np.maximum.accumulate(arr)
    dd = np.divide(arr - peak, peak, out=np.zeros_like(arr), where=peak > 0)
    n = len(pairs)
    step = max(1, n // 120)
    series = [{"date": pairs[i][0], "drawdown_pct": round(float(dd[i]) * 100, 2)} for i in range(0, n, step)]
    if series and series[-1]["date"] != pairs[-1][0]:
        series.append({"date": pairs[-1][0], "drawdown_pct": round(float(dd[-1]) * 100, 2)})
    return series


def _rolling_returns(prices: list[float]) -> dict[str, Any]:
    """Trailing-window total returns from the portfolio NAV series."""
    clean = _clean_price_series(prices)
    n = len(clean)
    if n < 2:
        return {}
    last = clean[-1]
    out: dict[str, Any] = {}
    for label, win in (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252)):
        if n > win:
            start = clean[-win - 1]
        elif n >= int(win * 0.6):
            # Not quite a full window (e.g. ~250 trading days for "1Y"): use the
            # earliest point we have rather than hiding the metric entirely.
            start = clean[0]
        else:
            out[label] = None
            continue
        out[label] = round((last / start - 1.0) * 100, 2) if start > 0 else None
    return out


def _xirr(cashflows: list[tuple[datetime, float]]) -> float | None:
    """Annualized money-weighted return (IRR) for dated cashflows via Newton-Raphson."""
    if len(cashflows) < 2:
        return None
    amounts = [cf[1] for cf in cashflows]
    if not (any(a > 0 for a in amounts) and any(a < 0 for a in amounts)):
        return None
    t0 = min(cf[0] for cf in cashflows)
    years = [(cf[0] - t0).days / 365.0 for cf in cashflows]

    def npv(rate: float) -> float:
        return sum(amt / ((1.0 + rate) ** yr) for amt, yr in zip(amounts, years))

    def dnpv(rate: float) -> float:
        return sum(-yr * amt / ((1.0 + rate) ** (yr + 1.0)) for amt, yr in zip(amounts, years))

    rate = 0.1
    for _ in range(100):
        try:
            f = npv(rate)
            df = dnpv(rate)
            if abs(df) < 1e-10:
                break
            new_rate = rate - f / df
            if not math.isfinite(new_rate):
                break
            if new_rate <= -0.9999:
                new_rate = -0.9999
            if abs(new_rate - rate) < 1e-7:
                rate = new_rate
                break
            rate = new_rate
        except (OverflowError, ZeroDivisionError):
            break
    if rate is None or not math.isfinite(rate) or rate <= -0.9999 or rate > 100:
        return None
    return round(rate * 100, 2)


def _health_score(
    *,
    hhi: float,
    sharpe: float | None,
    max_dd_pct: float,
    ann_vol_pct: float,
    top5_weight_pct: float,
) -> dict[str, Any]:
    """Composite 0-100 portfolio health from diversification, risk-adjusted return,
    drawdown resilience, volatility and concentration. Deterministic, no hardcoded data."""
    def clamp(x: float) -> float:
        return max(0.0, min(1.0, x))

    div = 25.0 * clamp((0.40 - hhi) / (0.40 - 0.05))
    sharpe_pts = 25.0 * clamp((sharpe or 0.0) / 2.0)
    dd_pts = 20.0 * clamp(1.0 - (abs(max_dd_pct) / 100.0) / 0.40)
    vol_pts = 15.0 * clamp((0.45 - ann_vol_pct / 100.0) / (0.45 - 0.15))
    conc_pts = 15.0 * clamp((0.80 - top5_weight_pct / 100.0) / (0.80 - 0.40))
    total = div + sharpe_pts + dd_pts + vol_pts + conc_pts
    score = int(round(total))
    if score >= 75:
        band = "Strong"
    elif score >= 50:
        band = "Balanced"
    elif score >= 25:
        band = "Fragile"
    else:
        band = "At Risk"
    return {
        "score": score,
        "band": band,
        "components": {
            "diversification": round(div, 1),
            "risk_adjusted_return": round(sharpe_pts, 1),
            "drawdown_resilience": round(dd_pts, 1),
            "volatility": round(vol_pts, 1),
            "concentration": round(conc_pts, 1),
        },
        "max_components": {
            "diversification": 25,
            "risk_adjusted_return": 25,
            "drawdown_resilience": 20,
            "volatility": 15,
            "concentration": 15,
        },
    }


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
        quote = _fetch_quote_cached(ticker) if kind == "equity" else {}
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
    # Only indices with a reliable Yahoo Finance history feed are exposed. Nifty
    # Smallcap 250 (^CNXSC) and Nifty Next 50 have no working Yahoo symbol (they
    # return 0–1 rows), so they were dropped in favour of Nifty 100 / Nifty 500.
    # Legacy ids are kept as aliases so previously-saved selections still resolve.
    benchmark_tickers = {
        "NIFTY50": "^NSEI",
        "SENSEX": "^BSESN",
        "NIFTYBANK": "^NSEBANK",
        "NIFTYIT": "^CNXIT",
        "MIDCAP50": "^NSEMDCP50",
        "NIFTY100": "^CNX100",
        "NIFTY500": "^CRSLDX",
        # ── legacy aliases (map to the closest working index) ──
        "NIFTYMIDCAP": "^NSEMDCP50",
        "MIDCAP150": "^NSEMDCP50",
        "NEXT50": "^CNX100",
        "SMALLCAP250": "^CRSLDX",
    }
    benchmark_key = (benchmark or "NIFTY50").upper()
    benchmark_ticker = benchmark_tickers.get(benchmark_key)
    if benchmark_ticker is None:
        logger.warning("Unknown benchmark '%s', falling back to NIFTY50 (^NSEI)", benchmark_key)
        benchmark_ticker = "^NSEI"

    # Portfolio NAV history vs benchmark
    port_hist = _weighted_nav_history_from_enriched(enriched_positions, period=period)
    bench_hist = _fetch_history_cached(benchmark_ticker, period=period)

    # Risk metrics
    beta = 0.0
    volatility = 0.0
    max_dd = 0.0
    port_rets = np.array([])
    if port_hist.get("prices") and len(port_hist["prices"]) > 10:
        port_prices = _clean_price_series(port_hist["prices"])
        port_rets = np.diff(np.log(np.array(port_prices)))
        max_dd = _max_drawdown(port_hist["prices"])
        volatility = _annualized_volatility(port_rets)
        if bench_hist.get("prices") and len(bench_hist["prices"]) > 10:
            beta = _compute_beta(port_hist, bench_hist)

    # Risk-adjusted ratios, historical tail risk, drawdown curve, rolling returns
    ratios = _risk_adjusted_ratios(port_rets, volatility, max_dd)
    var_block = _historical_var_cvar(port_rets, confidence=0.95)
    drawdown_curve = _drawdown_series(port_hist.get("dates", []), port_hist.get("prices", []))
    rolling = _rolling_returns(port_hist.get("prices", []))

    # XIRR (money-weighted return) from dated purchase cashflows. Uses raw mirror
    # as_of (the manual-entry purchase date / statement date), not the live quote ts.
    now_dt = datetime.now(timezone.utc)
    cashflows: list[tuple[datetime, float]] = []
    for pos in positions:
        cost = _positive_float(pos.cost_basis) or (_positive_float(pos.avg_cost) * _positive_float(pos.quantity))
        pdate = _parse_dt(pos.as_of)
        if cost > 0 and pdate and pdate < now_dt:
            cashflows.append((pdate, -cost))
    xirr_pct = _xirr(cashflows + [(now_dt, total_value)]) if (cashflows and total_value > 0) else None

    # Top-5 concentration
    sorted_by_weight = sorted(enriched_positions, key=lambda x: x["market_value"], reverse=True)[:5]
    top5 = [
        {"symbol": p["symbol"], "name": p["name"], "weight_pct": round(p["weight"] * 100, 2)}
        for p in sorted_by_weight
    ]
    hhi_value = sum(p["weight"] * p["weight"] for p in enriched_positions)
    top5_weight_pct = sum(t["weight_pct"] for t in top5)

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

    # Health needs real return history — without it, drawdown/volatility would
    # default to zero and wrongly award a perfect score. Gate on >=12 returns.
    if len(port_rets) >= 12:
        health_block = _health_score(
            hhi=hhi_value,
            sharpe=ratios.get("sharpe"),
            max_dd_pct=round(max_dd * 100, 2),
            ann_vol_pct=round(volatility * 100, 2),
            top5_weight_pct=top5_weight_pct,
        )
    else:
        health_block = {"score": None, "band": "Building", "components": {}, "max_components": {}, "insufficient_history": True}

    priced_count = sum(1 for p in enriched_positions if p.get("price_source") != "unavailable")
    coverage_ratio = priced_count / len(enriched_positions) if enriched_positions else 0.0

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
            "hhi": hhi_value,
            "beta_vs_nifty": round(beta, 2),
            "annualized_volatility_pct": round(volatility * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "top5_concentration": top5,
            "top5_weight_pct": round(top5_weight_pct, 2),
            "annualized_return_pct": ratios.get("annualized_return_pct"),
            "sharpe": ratios.get("sharpe"),
            "sortino": ratios.get("sortino"),
            "calmar": ratios.get("calmar"),
            "historical_var_pct": var_block.get("historical_var_pct"),
            "cvar_pct": var_block.get("cvar_pct"),
            "var_confidence": var_block.get("confidence"),
            "xirr_pct": xirr_pct,
            "risk_free_rate_pct": round(_RISK_FREE_RATE * 100, 2),
        },
        "health": health_block,
        "rolling_returns": rolling,
        "drawdown_series": drawdown_curve,
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
        "price_coverage_ratio": round(coverage_ratio, 2),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
