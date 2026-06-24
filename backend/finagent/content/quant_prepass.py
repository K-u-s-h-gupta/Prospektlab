"""Quantitative pre-pass — computed insight the writer weaves in.

The differentiator vs a prose-only generator: cross-sectional peer ranking,
time-series inflection detection, and rule-based anomaly flags are COMPUTED
deterministically, not guessed by an LLM. The pipeline runs these over the
structured financials it already has, then hands the findings to the writer as
must-include facts.

Pure functions over plain dicts/lists. No IO, no LLM, tolerant of missing keys
(a check it can't run is skipped, never raised).
"""
from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Peer cross-section ────────────────────────────────────────────────────────

def peer_cross_section(
    target: dict[str, Any],
    peers: list[dict[str, Any]],
    metrics: list[str],
) -> dict[str, Any]:
    """Rank `target` against `peers` on each metric.

    Each company dict maps metric_name -> number (plus a "name" key). Returns
    per-metric {rank, of, percentile, median, delta_vs_median, read}.
    """
    out: dict[str, Any] = {}
    universe = [target] + list(peers)
    target_name = str(target.get("name") or "Target")
    for metric in metrics:
        vals = [(c.get("name"), _num(c.get(metric))) for c in universe]
        vals = [(n, v) for n, v in vals if v is not None]
        if len(vals) < 2 or _num(target.get(metric)) is None:
            continue
        tv = float(target[metric])
        # Higher is better by default (rank 1 = highest).
        ordered = sorted(vals, key=lambda kv: kv[1], reverse=True)
        rank = next(i for i, (n, v) in enumerate(ordered, start=1) if n == target_name)
        n_total = len(ordered)
        sorted_vals = sorted(v for _, v in vals)
        mid = len(sorted_vals) // 2
        median = (sorted_vals[mid] if len(sorted_vals) % 2
                  else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2)
        percentile = round((n_total - rank) / (n_total - 1) * 100) if n_total > 1 else 100
        delta = round(tv - median, 4)
        out[metric] = {
            "rank": rank,
            "of": n_total,
            "percentile": percentile,
            "median": round(median, 4),
            "delta_vs_median": delta,
            "read": f"{metric} {tv:g} = {_ordinal(rank)} of {n_total} peers "
                    f"({'+' if delta >= 0 else ''}{delta:g} vs median {median:g})",
        }
    return out


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ── Trend-break detection ─────────────────────────────────────────────────────

def detect_trend_breaks(series: list[float], labels: list[str] | None = None) -> list[dict[str, Any]]:
    """Find inflections in a metric time-series (chronological order).

    Detects: first decline after a run of rises (and vice versa), sign flips,
    and a sharp acceleration/deceleration in the step size. Returns a list of
    {index, label, kind, detail}.
    """
    nums = [_num(v) for v in series]
    nums = [v for v in nums if v is not None]
    breaks: list[dict[str, Any]] = []
    if len(nums) < 3:
        return breaks
    labels = labels or [str(i) for i in range(len(nums))]

    deltas = [nums[i] - nums[i - 1] for i in range(1, len(nums))]
    for i in range(1, len(deltas)):
        prev, cur = deltas[i - 1], deltas[i]
        idx = i + 1  # index into the value series
        label = labels[idx] if idx < len(labels) else str(idx)
        if prev > 0 and cur < 0:
            breaks.append({"index": idx, "label": label, "kind": "peak",
                           "detail": f"first decline after rising trend at {label}"})
        elif prev < 0 and cur > 0:
            breaks.append({"index": idx, "label": label, "kind": "trough",
                           "detail": f"first recovery after falling trend at {label}"})
        # Acceleration / deceleration on same-sign deltas.
        elif prev != 0 and cur != 0 and (cur > 0) == (prev > 0):
            if abs(cur) >= 2 * abs(prev):
                breaks.append({"index": idx, "label": label, "kind": "acceleration",
                               "detail": f"step size more than doubled at {label}"})
            elif abs(cur) * 2 <= abs(prev):
                breaks.append({"index": idx, "label": label, "kind": "deceleration",
                               "detail": f"step size more than halved at {label}"})
    # Sign flips of the level itself (e.g. profit to loss).
    for i in range(1, len(nums)):
        if (nums[i] < 0) != (nums[i - 1] < 0):
            label = labels[i] if i < len(labels) else str(i)
            breaks.append({"index": i, "label": label, "kind": "sign_flip",
                           "detail": f"value crossed zero at {label}"})
    return breaks


# ── Anomaly flags ─────────────────────────────────────────────────────────────

def flag_anomalies(financials: dict[str, Any]) -> list[dict[str, Any]]:
    """Rule-based red flags from a metrics dict. Missing keys → skip that check.

    Recognised keys (all optional): revenue_growth, receivables_growth,
    pat, ocf (operating cash flow), fcf, fcf_pat_ratio, promoter_pledge_pct,
    promoter_pledge_pct_prev, debt_growth, margin_change.
    """
    flags: list[dict[str, Any]] = []

    rev_g = _num(financials.get("revenue_growth"))
    recv_g = _num(financials.get("receivables_growth"))
    if rev_g is not None and recv_g is not None and recv_g > rev_g + 10:
        flags.append({"code": "receivables_outpacing_revenue", "severity": "high",
                      "detail": f"receivables +{recv_g:g}% vs revenue +{rev_g:g}% — possible revenue-quality risk"})

    pat = _num(financials.get("pat"))
    ocf = _num(financials.get("ocf"))
    if pat is not None and ocf is not None and pat > 0 and ocf < 0.6 * pat:
        flags.append({"code": "cashflow_below_profit", "severity": "high",
                      "detail": f"operating cash flow {ocf:g} is under 60% of PAT {pat:g} — earnings not converting to cash"})

    ratio = _num(financials.get("fcf_pat_ratio"))
    if ratio is not None and ratio < 0.5:
        flags.append({"code": "weak_fcf_conversion", "severity": "medium",
                      "detail": f"FCF/PAT {ratio:g} below 0.5"})

    pledge = _num(financials.get("promoter_pledge_pct"))
    pledge_prev = _num(financials.get("promoter_pledge_pct_prev"))
    if pledge is not None and pledge_prev is not None and pledge > pledge_prev + 2:
        flags.append({"code": "rising_promoter_pledge", "severity": "high",
                      "detail": f"promoter pledge up {pledge - pledge_prev:g}pp to {pledge:g}%"})
    elif pledge is not None and pledge >= 25:
        flags.append({"code": "high_promoter_pledge", "severity": "medium",
                      "detail": f"promoter pledge at {pledge:g}%"})

    debt_g = _num(financials.get("debt_growth"))
    margin_chg = _num(financials.get("margin_change"))
    if debt_g is not None and margin_chg is not None and debt_g > 0 and margin_chg < 0:
        flags.append({"code": "debt_up_margin_down", "severity": "high",
                      "detail": f"debt +{debt_g:g}% while margin {margin_chg:g}pp — leverage rising into weakness"})

    return flags
