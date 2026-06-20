"""Scoring, technical indicators, contradictions, and NL filter parsing."""

from __future__ import annotations

import math
import re
from typing import Any

from .schemas import ScreenerFilter


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / float(window)


def _ema(values: list[float], window: int) -> float | None:
    if len(values) < window or window <= 0:
        return None
    alpha = 2.0 / (window + 1.0)
    ema_val = sum(values[:window]) / float(window)
    for price in values[window:]:
        ema_val = (price * alpha) + (ema_val * (1.0 - alpha))
    return ema_val


def _stddev(values: list[float]) -> float | None:
    usable = [float(v) for v in (safe_float(value) for value in values) if v is not None]
    if len(usable) < 2:
        return None
    mean = sum(usable) / len(usable)
    variance = sum((v - mean) ** 2 for v in usable) / len(usable)
    return math.sqrt(variance)


def _pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return ((current - base) / abs(base)) * 100.0


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, len(values)):
        delta = values[idx] - values[idx - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        return 100.0
    for idx in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[idx]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[idx]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_technicals(series_dates: list[str], series_prices: list[float]) -> dict[str, Any]:
    """Compute the technical summary from a close-price series."""
    prices = [p for p in (safe_float(x) for x in series_prices) if p is not None]
    dates = list(series_dates or [])
    if len(prices) < 3:
        return {
            "status": "unavailable",
            "reason": "insufficient_history",
            "as_of": dates[-1] if dates else None,
        }

    latest = prices[-1]
    sma20 = _sma(prices, 20)
    sma50 = _sma(prices, 50)
    sma200 = _sma(prices, 200)
    rsi14 = _rsi(prices, 14)
    ema12 = _ema(prices, 12)
    ema26 = _ema(prices, 26)
    macd = (ema12 - ema26) if (ema12 is not None and ema26 is not None) else None

    # Signal line uses recent macd series approximation.
    signal = None
    if len(prices) >= 35:
        macd_series: list[float] = []
        for idx in range(26, len(prices)):
            fast = _ema(prices[: idx + 1], 12)
            slow = _ema(prices[: idx + 1], 26)
            if fast is None or slow is None:
                continue
            macd_series.append(fast - slow)
        signal = _ema(macd_series, 9) if len(macd_series) >= 9 else None
    histogram = (macd - signal) if (macd is not None and signal is not None) else None

    pct_1m = _pct_change(latest, prices[-22]) if len(prices) >= 22 else None
    pct_3m = _pct_change(latest, prices[-66]) if len(prices) >= 66 else None

    lookback_52w = prices[-min(252, len(prices)):]
    year_high = max(lookback_52w) if lookback_52w else None
    year_low = min(lookback_52w) if lookback_52w else None
    drawdown_from_52w_high_pct = _pct_change(latest, year_high) if year_high else None
    upside_to_52w_high_pct = _pct_change(year_high, latest) if year_high else None

    std20 = _stddev(prices[-20:]) if len(prices) >= 20 else None
    bollinger_upper = (sma20 + (2 * std20)) if (sma20 is not None and std20 is not None) else None
    bollinger_lower = (sma20 - (2 * std20)) if (sma20 is not None and std20 is not None) else None
    bollinger_position_pct = None
    bollinger_state = "unavailable"
    if bollinger_upper is not None and bollinger_lower is not None and bollinger_upper != bollinger_lower:
        bollinger_position_pct = ((latest - bollinger_lower) / (bollinger_upper - bollinger_lower)) * 100.0
        if latest > bollinger_upper:
            bollinger_state = "above_upper_band"
        elif latest < bollinger_lower:
            bollinger_state = "below_lower_band"
        else:
            bollinger_state = "within_band"

    recent_returns: list[float] = []
    for idx in range(max(1, len(prices) - 22), len(prices)):
        prev = prices[idx - 1]
        if prev:
            recent_returns.append((prices[idx] - prev) / prev)
    volatility_1m_annualized_pct = None
    std_returns = _stddev(recent_returns)
    if std_returns is not None:
        volatility_1m_annualized_pct = std_returns * math.sqrt(252.0) * 100.0

    prev_sma20 = _sma(prices[:-1], 20)
    prev_sma50 = _sma(prices[:-1], 50)
    prev_sma200 = _sma(prices[:-1], 200)
    sma20_50_signal = "neutral"
    if sma20 is not None and sma50 is not None:
        sma20_50_signal = "bullish" if sma20 > sma50 else "bearish"
        if prev_sma20 is not None and prev_sma50 is not None:
            if prev_sma20 <= prev_sma50 and sma20 > sma50:
                sma20_50_signal = "bullish_crossover"
            elif prev_sma20 >= prev_sma50 and sma20 < sma50:
                sma20_50_signal = "bearish_crossover"

    sma50_200_signal = "neutral"
    if sma50 is not None and sma200 is not None:
        sma50_200_signal = "golden_cross_bias" if sma50 > sma200 else "death_cross_bias"
        if prev_sma50 is not None and prev_sma200 is not None:
            if prev_sma50 <= prev_sma200 and sma50 > sma200:
                sma50_200_signal = "golden_cross"
            elif prev_sma50 >= prev_sma200 and sma50 < sma200:
                sma50_200_signal = "death_cross"

    support_20d = min(prices[-20:]) if len(prices) >= 20 else min(prices)
    resistance_20d = max(prices[-20:]) if len(prices) >= 20 else max(prices)

    trend_bias = "neutral"
    if sma200 is not None and latest > sma200:
        trend_bias = "bullish" if sma50 is not None and sma20 is not None and sma20 > sma50 else "uptrend"
    elif sma200 is not None and latest < sma200:
        trend_bias = "bearish"

    breakout_state = "range"
    if year_high is not None and year_low is not None:
        if latest >= (year_high * 0.99):
            breakout_state = "near_52w_high"
        elif latest <= (year_low * 1.01):
            breakout_state = "near_52w_low"

    return {
        "status": "ok",
        "as_of": dates[-1] if dates else None,
        "latest_price": latest,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "sma20_50_signal": sma20_50_signal,
        "sma50_200_signal": sma50_200_signal,
        "rsi14": rsi14,
        "macd": macd,
        "macd_signal": signal,
        "macd_histogram": histogram,
        "bollinger_upper": bollinger_upper,
        "bollinger_mid": sma20,
        "bollinger_lower": bollinger_lower,
        "bollinger_position_pct": bollinger_position_pct,
        "bollinger_state": bollinger_state,
        "volatility_1m_annualized_pct": volatility_1m_annualized_pct,
        "return_1m_pct": pct_1m,
        "return_3m_pct": pct_3m,
        "high_52w": year_high,
        "low_52w": year_low,
        "drawdown_from_52w_high_pct": drawdown_from_52w_high_pct,
        "upside_to_52w_high_pct": upside_to_52w_high_pct,
        "support_20d": support_20d,
        "resistance_20d": resistance_20d,
        "trend_bias": trend_bias,
        "breakout_state": breakout_state,
        "above_200dma": bool(sma200 is not None and latest > sma200),
    }


_FILTER_RULE_RE = re.compile(
    r"(?P<metric>roce|roe|p\/e|pe|debt\s*to\s*equity|debt\/equity|d\/e|promoter\s*holding|promoter\s*pledge|rsi|price)"
    r"\s*(?P<op>>=|<=|>|<|=)\s*(?P<value>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_nl_filters(query: str) -> ScreenerFilter:
    parsed = ScreenerFilter()
    text = (query or "").strip().lower()
    if not text:
        parsed.parse_notes.append("No query text provided; using broad universe scan.")
        return parsed

    for match in _FILTER_RULE_RE.finditer(text):
        metric = match.group("metric").strip().lower()
        op = match.group("op")
        value = safe_float(match.group("value"))
        if value is None:
            continue

        def _apply_bounds(kind: str) -> None:
            if op in {">", ">=", "="}:
                if kind == "roce":
                    parsed.min_roce = value
                elif kind == "roe":
                    parsed.min_roe = value
                elif kind == "pe":
                    parsed.min_pe = value
                elif kind == "promoter_holding":
                    parsed.min_promoter_holding = value
                elif kind == "rsi":
                    parsed.min_rsi = value
                elif kind == "price":
                    parsed.min_price = value
            if op in {"<", "<=", "="}:
                if kind == "pe":
                    parsed.max_pe = value
                elif kind == "de":
                    parsed.max_debt_to_equity = value
                elif kind == "promoter_pledge":
                    parsed.max_promoter_pledge = value
                elif kind == "rsi":
                    parsed.max_rsi = value
                elif kind == "price":
                    parsed.max_price = value

        if metric in {"roce"}:
            _apply_bounds("roce")
        elif metric in {"roe"}:
            _apply_bounds("roe")
        elif metric in {"p/e", "pe"}:
            _apply_bounds("pe")
        elif metric in {"debt to equity", "debt/equity", "d/e"}:
            _apply_bounds("de")
        elif metric in {"promoter holding"}:
            _apply_bounds("promoter_holding")
        elif metric in {"promoter pledge"}:
            _apply_bounds("promoter_pledge")
        elif metric in {"rsi"}:
            _apply_bounds("rsi")
        elif metric in {"price"}:
            _apply_bounds("price")

    if any(token in text for token in ("debt free", "debt-free", "zero debt", "no debt")):
        parsed.max_debt_to_equity = 0.1
        parsed.parse_notes.append("Interpreted debt-free condition as debt/equity <= 0.1.")
    if any(token in text for token in ("no pledge", "without pledge", "zero pledge")):
        parsed.require_no_pledge = True
        parsed.max_promoter_pledge = 0.0
    if any(token in text for token in ("above 200 dma", "above 200-day", "above 200 day", "above 200 ma")):
        parsed.require_above_200dma = True

    if "quality" in text:
        parsed.min_roce = max(parsed.min_roce or 0.0, 15.0)
        parsed.min_roe = max(parsed.min_roe or 0.0, 12.0)
        parsed.parse_notes.append("Applied baseline quality heuristics (ROCE >= 15, ROE >= 12).")
    if "value" in text or "undervalued" in text:
        parsed.max_pe = min(parsed.max_pe if parsed.max_pe is not None else 20.0, 20.0)
        parsed.parse_notes.append("Applied baseline value heuristic (PE <= 20).")
    if "momentum" in text:
        parsed.require_above_200dma = True
        parsed.min_rsi = max(parsed.min_rsi or 0.0, 50.0)
        parsed.parse_notes.append("Applied baseline momentum heuristics (above 200DMA, RSI >= 50).")

    tokens = [tok for tok in re.split(r"[^a-z0-9]+", text) if len(tok) >= 4]
    ignored = {
        "with", "that", "this", "from", "india", "stock", "stocks", "screener", "find", "show",
        "above", "below", "greater", "less", "than", "under", "over", "where", "have", "having",
    }
    parsed.keywords = [tok for tok in tokens if tok not in ignored][:6]
    return parsed


def _bounded(value: float | None, lo: float, hi: float) -> float:
    if value is None:
        return 0.0
    return max(lo, min(hi, value))


def compute_scores(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute explainable pillar scores and final Prospekt score."""
    fundamental = snapshot.get("fundamentals") or {}
    metrics = fundamental.get("metrics") or {}
    technical = snapshot.get("technicals") or {}
    governance = snapshot.get("governance") or {}
    coverage = (snapshot.get("ikg") or {}).get("coverage") or {}
    risk = snapshot.get("risk_signals") or {}

    roce = safe_float(metrics.get("roce"))
    roe = safe_float(metrics.get("roe"))
    pe = safe_float(metrics.get("pe_ratio"))
    debt_eq = safe_float(metrics.get("debt_to_equity"))
    promoter_holding = safe_float(metrics.get("promoter_holding_pct"))
    promoter_pledge = safe_float(metrics.get("promoter_pledge_pct"))
    fcf = safe_float(metrics.get("free_cashflow"))
    revenue_growth = safe_float(metrics.get("revenue_growth_pct"))

    # Fundamental quality
    fundamental_score = 50.0
    if roce is not None:
        fundamental_score += _bounded((roce - 10.0) * 1.5, -20.0, 25.0)
    if roe is not None:
        fundamental_score += _bounded((roe - 10.0) * 1.2, -15.0, 20.0)
    if debt_eq is not None:
        fundamental_score += _bounded((1.2 - debt_eq) * 16.0, -25.0, 20.0)
    if fcf is not None:
        fundamental_score += 8.0 if fcf > 0 else -8.0
    if revenue_growth is not None:
        fundamental_score += _bounded(revenue_growth * 0.7, -10.0, 12.0)
    fundamental_score = _bounded(fundamental_score, 0.0, 100.0)

    # Valuation
    valuation_score = 50.0
    if pe is not None:
        if pe <= 15:
            valuation_score += 25.0
        elif pe <= 25:
            valuation_score += 12.0
        elif pe >= 45:
            valuation_score -= 20.0
        elif pe >= 30:
            valuation_score -= 10.0
    if revenue_growth is not None and pe is not None and pe > 0:
        peg = pe / max(revenue_growth, 1.0)
        if peg < 1.2:
            valuation_score += 8.0
        elif peg > 2.5:
            valuation_score -= 8.0
    valuation_score = _bounded(valuation_score, 0.0, 100.0)

    # Technical
    technical_score = 50.0
    rsi = safe_float(technical.get("rsi14"))
    trend_bias = str(technical.get("trend_bias") or "")
    if trend_bias in {"bullish", "uptrend"}:
        technical_score += 18.0
    elif trend_bias == "bearish":
        technical_score -= 18.0
    if rsi is not None:
        if 45 <= rsi <= 65:
            technical_score += 8.0
        elif rsi >= 75:
            technical_score -= 8.0
        elif rsi <= 30:
            technical_score -= 6.0
    if technical.get("above_200dma"):
        technical_score += 12.0
    technical_score = _bounded(technical_score, 0.0, 100.0)

    # Governance: existing score is risk (higher is worse), convert to quality score.
    governance_risk = safe_float(governance.get("score"))
    governance_score = _bounded(100.0 - governance_risk, 0.0, 100.0) if governance_risk is not None else 55.0
    if promoter_pledge is not None:
        governance_score -= _bounded(promoter_pledge * 0.6, 0.0, 25.0)
    if promoter_holding is not None:
        governance_score += _bounded((promoter_holding - 40.0) * 0.25, -10.0, 10.0)
    if risk.get("enforcement_count", 0) > 0:
        governance_score -= 15.0
    governance_score = _bounded(governance_score, 0.0, 100.0)

    # Momentum/news
    momentum_score = 50.0
    if safe_float(technical.get("return_1m_pct")) is not None:
        momentum_score += _bounded(safe_float(technical.get("return_1m_pct")) * 1.1, -15.0, 15.0)
    if safe_float(technical.get("return_3m_pct")) is not None:
        momentum_score += _bounded(safe_float(technical.get("return_3m_pct")) * 0.6, -12.0, 12.0)
    momentum_score = _bounded(momentum_score, 0.0, 100.0)

    # Confidence/freshness
    complete_count = sum(1 for val in coverage.values() if val == "complete")
    partial_count = sum(1 for val in coverage.values() if val == "partial")
    confidence_score = _bounded(30.0 + (complete_count * 11.0) + (partial_count * 5.0), 0.0, 100.0)

    final_score = (
        fundamental_score * 0.26
        + valuation_score * 0.18
        + technical_score * 0.16
        + governance_score * 0.22
        + momentum_score * 0.10
        + confidence_score * 0.08
    )
    final_score = round(_bounded(final_score, 0.0, 100.0), 1)
    grade = "A" if final_score >= 80 else ("B" if final_score >= 65 else ("C" if final_score >= 50 else "D"))

    return {
        "prospekt_score": final_score,
        "grade": grade,
        "pillars": {
            "fundamental_quality": round(fundamental_score, 1),
            "valuation": round(valuation_score, 1),
            "technicals": round(technical_score, 1),
            "governance": round(governance_score, 1),
            "momentum_news": round(momentum_score, 1),
            "confidence": round(confidence_score, 1),
        },
        "method": "weighted_explainable_v1",
    }


def detect_contradictions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect tension between metrics so users see blind spots quickly."""
    contradictions: list[dict[str, Any]] = []
    fundamentals = snapshot.get("fundamentals") or {}
    metrics = fundamentals.get("metrics") or {}
    technical = snapshot.get("technicals") or {}
    governance = snapshot.get("governance") or {}

    pe = safe_float(metrics.get("pe_ratio"))
    growth = safe_float(metrics.get("revenue_growth_pct"))
    fcf = safe_float(metrics.get("free_cashflow"))
    net_income = safe_float(metrics.get("net_income"))
    promoter_pledge = safe_float(metrics.get("promoter_pledge_pct"))
    gov_risk = safe_float(governance.get("score"))

    if pe is not None and growth is not None and pe > 45 and growth < 10:
        contradictions.append({
            "code": "VALUATION_VS_GROWTH",
            "title": "High valuation with modest growth",
            "detail": f"PE is {pe:.1f} while revenue growth is {growth:.1f}%.",
            "severity": "watch",
        })
    if net_income is not None and net_income > 0 and fcf is not None and fcf < 0:
        contradictions.append({
            "code": "PROFIT_VS_CASHFLOW",
            "title": "Profits positive but cash flow negative",
            "detail": "Reported earnings are positive while free cash flow is negative.",
            "severity": "high",
        })
    if technical.get("trend_bias") in {"bullish", "uptrend"} and gov_risk is not None and gov_risk >= 70:
        contradictions.append({
            "code": "TECHNICALS_VS_GOVERNANCE",
            "title": "Technical strength with governance stress",
            "detail": "Price trend is constructive, but governance risk is elevated.",
            "severity": "watch",
        })
    if promoter_pledge is not None and promoter_pledge >= 25:
        contradictions.append({
            "code": "PROMOTER_PLEDGE_STRESS",
            "title": "Promoter pledge is elevated",
            "detail": f"Promoter pledge is {promoter_pledge:.1f}% of promoter holdings.",
            "severity": "high" if promoter_pledge >= 40 else "watch",
        })
    return contradictions


def summarize_positive_negative(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    """Extract explainable positive/negative bullets from the current snapshot."""
    positives: list[str] = []
    negatives: list[str] = []

    metrics = ((snapshot.get("fundamentals") or {}).get("metrics") or {})
    tech = snapshot.get("technicals") or {}
    governance = snapshot.get("governance") or {}

    roce = safe_float(metrics.get("roce"))
    roe = safe_float(metrics.get("roe"))
    debt_eq = safe_float(metrics.get("debt_to_equity"))
    pe = safe_float(metrics.get("pe_ratio"))
    pledge = safe_float(metrics.get("promoter_pledge_pct"))

    if roce is not None and roce >= 20:
        positives.append(f"Strong capital efficiency (ROCE {roce:.1f}%).")
    if roe is not None and roe >= 15:
        positives.append(f"Healthy equity returns (ROE {roe:.1f}%).")
    if debt_eq is not None and debt_eq <= 0.5:
        positives.append(f"Balance sheet appears disciplined (Debt/Equity {debt_eq:.2f}).")
    if tech.get("above_200dma"):
        positives.append("Price is trading above 200DMA, signalling medium-term trend support.")
    if safe_float(governance.get("score")) is not None and safe_float(governance.get("score")) < 35:
        positives.append("Governance risk score is currently low.")

    if pe is not None and pe >= 40:
        negatives.append(f"Valuation is rich (PE {pe:.1f}).")
    if debt_eq is not None and debt_eq >= 1.5:
        negatives.append(f"Leverage looks high (Debt/Equity {debt_eq:.2f}).")
    if tech.get("trend_bias") == "bearish":
        negatives.append("Price is below key trend support and technically weak.")
    if pledge is not None and pledge > 0:
        negatives.append(f"Promoter shares are pledged ({pledge:.1f}%).")
    if safe_float(governance.get("score")) is not None and safe_float(governance.get("score")) >= 70:
        negatives.append("Governance risk score is elevated and needs close monitoring.")

    if not positives:
        positives.append("No strong quality edge is confirmed from the current data snapshot.")
    if not negatives:
        negatives.append("No major red flags are currently evident from the tracked signals.")
    return {"positives": positives[:6], "negatives": negatives[:6]}


def check_filter_match(
    parsed_filter: ScreenerFilter,
    *,
    price: float | None,
    metrics: dict[str, Any],
    technicals: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Apply parsed filters to one stock and return pass/fail + reason trace."""
    reasons: list[str] = []

    def _cmp(value: float | None, lower: float | None = None, upper: float | None = None, label: str = "") -> bool:
        if value is None:
            reasons.append(f"{label} unavailable")
            return False
        if lower is not None and value < lower:
            reasons.append(f"{label} {value:.2f} < {lower:.2f}")
            return False
        if upper is not None and value > upper:
            reasons.append(f"{label} {value:.2f} > {upper:.2f}")
            return False
        reasons.append(f"{label} {value:.2f} within bounds")
        return True

    if parsed_filter.min_price is not None or parsed_filter.max_price is not None:
        if not _cmp(price, parsed_filter.min_price, parsed_filter.max_price, "Price"):
            return False, reasons

    if parsed_filter.min_roce is not None:
        if not _cmp(safe_float(metrics.get("roce")), parsed_filter.min_roce, None, "ROCE"):
            return False, reasons
    if parsed_filter.min_roe is not None:
        if not _cmp(safe_float(metrics.get("roe")), parsed_filter.min_roe, None, "ROE"):
            return False, reasons
    if parsed_filter.max_pe is not None or parsed_filter.min_pe is not None:
        if not _cmp(safe_float(metrics.get("pe_ratio")), parsed_filter.min_pe, parsed_filter.max_pe, "PE"):
            return False, reasons
    if parsed_filter.max_debt_to_equity is not None:
        if not _cmp(safe_float(metrics.get("debt_to_equity")), None, parsed_filter.max_debt_to_equity, "Debt/Equity"):
            return False, reasons
    if parsed_filter.min_promoter_holding is not None:
        if not _cmp(safe_float(metrics.get("promoter_holding_pct")), parsed_filter.min_promoter_holding, None, "Promoter Holding"):
            return False, reasons
    if parsed_filter.max_promoter_pledge is not None:
        if not _cmp(safe_float(metrics.get("promoter_pledge_pct")), None, parsed_filter.max_promoter_pledge, "Promoter Pledge"):
            return False, reasons
    if parsed_filter.require_no_pledge:
        pledge = safe_float(metrics.get("promoter_pledge_pct")) or 0.0
        if pledge > 0:
            reasons.append(f"Promoter pledge not zero ({pledge:.2f}).")
            return False, reasons
        reasons.append("Promoter pledge is zero.")
    if parsed_filter.require_above_200dma:
        if not technicals.get("above_200dma"):
            reasons.append("Not above 200DMA.")
            return False, reasons
        reasons.append("Above 200DMA.")
    if parsed_filter.min_rsi is not None or parsed_filter.max_rsi is not None:
        if not _cmp(safe_float(technicals.get("rsi14")), parsed_filter.min_rsi, parsed_filter.max_rsi, "RSI"):
            return False, reasons

    return True, reasons

