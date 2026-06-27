"""Subsidiary Cash-Drain Matrix analysis.

Calculates exact rupee contribution of unlisted subsidiaries by comparing
Standalone vs Consolidated financials. Flags companies where subsidiaries
are draining profits or diluting margins.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("finagent.earnings.subsidiary_analysis")


def extract_subsidiary_analysis(
    standalone_metrics: dict[str, Any] | None,
    consolidated_metrics: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Calculate subsidiary contribution by subtracting standalone from consolidated.

    Args:
        standalone_metrics: Extracted standalone financial metrics (revenue, pat, ebitda, etc.)
        consolidated_metrics: Extracted consolidated financial metrics

    Returns:
        dict with subsidiary contribution analysis and flags, or None if insufficient data
    """
    if not standalone_metrics or not consolidated_metrics:
        return None

    # Need at least revenue or PAT in both to compute meaningful analysis
    has_standalone = standalone_metrics.get("revenue") or standalone_metrics.get("pat")
    has_consolidated = consolidated_metrics.get("revenue") or consolidated_metrics.get("pat")
    if not has_standalone or not has_consolidated:
        return None

    result: dict[str, Any] = {
        "standalone": {},
        "consolidated": {},
        "subsidiary_contribution": {},
        "flags": {},
        "verdict": "",
    }

    metrics = ["revenue", "pat", "ebitda", "operating_profit"]

    for metric in metrics:
        standalone_val = _safe_float(standalone_metrics.get(metric))
        consolidated_val = _safe_float(consolidated_metrics.get(metric))

        if standalone_val is not None:
            result["standalone"][metric] = standalone_val
        if consolidated_val is not None:
            result["consolidated"][metric] = consolidated_val

        if standalone_val is not None and consolidated_val is not None:
            contribution = consolidated_val - standalone_val
            result["subsidiary_contribution"][metric] = round(contribution, 2)

            if consolidated_val != 0:
                pct = (contribution / consolidated_val) * 100
                result["subsidiary_contribution"][f"{metric}_pct"] = round(pct, 2)

    # Calculate margin comparison
    standalone_revenue = result["standalone"].get("revenue")
    consolidated_revenue = result["consolidated"].get("revenue")
    standalone_ebitda = result["standalone"].get("ebitda")
    consolidated_ebitda = result["consolidated"].get("ebitda")

    if all(v and v > 0 for v in [standalone_revenue, consolidated_revenue, standalone_ebitda, consolidated_ebitda]):
        standalone_margin = (standalone_ebitda / standalone_revenue) * 100
        consolidated_margin = (consolidated_ebitda / consolidated_revenue) * 100
        result["subsidiary_contribution"]["standalone_ebitda_margin"] = round(standalone_margin, 2)
        result["subsidiary_contribution"]["consolidated_ebitda_margin"] = round(consolidated_margin, 2)
        result["subsidiary_contribution"]["margin_drag"] = round(consolidated_margin - standalone_margin, 2)

    # Calculate PAT margin comparison
    standalone_pat = result["standalone"].get("pat")
    consolidated_pat = result["consolidated"].get("pat")

    if all(v and v > 0 for v in [standalone_revenue, consolidated_revenue]) and standalone_pat is not None and consolidated_pat is not None:
        standalone_pat_margin = (standalone_pat / standalone_revenue) * 100
        consolidated_pat_margin = (consolidated_pat / consolidated_revenue) * 100
        result["subsidiary_contribution"]["standalone_pat_margin"] = round(standalone_pat_margin, 2)
        result["subsidiary_contribution"]["consolidated_pat_margin"] = round(consolidated_pat_margin, 2)
        result["subsidiary_contribution"]["pat_margin_drag"] = round(consolidated_pat_margin - standalone_pat_margin, 2)

    # Set flags
    pat_contribution = result["subsidiary_contribution"].get("pat", 0)
    result["flags"]["profit_drain"] = pat_contribution < 0 if pat_contribution != 0 else False

    margin_drag = result["subsidiary_contribution"].get("margin_drag", 0)
    result["flags"]["margin_dilution"] = margin_drag < -2 if margin_drag != 0 else False

    revenue_pct = result["subsidiary_contribution"].get("revenue_pct", 0)
    result["flags"]["revenue_dependent"] = revenue_pct > 25 if revenue_pct else False

    pat_pct = result["subsidiary_contribution"].get("pat_pct", 0)
    result["flags"]["profit_concentration"] = pat_pct > 40 if pat_pct else False

    # Generate verdict
    verdicts = []
    if result["flags"]["profit_drain"]:
        drain_amt = abs(pat_contribution)
        verdicts.append(f"Subsidiaries draining ₹{drain_amt:.0f} Cr profit")
    elif pat_contribution > 0 and pat_pct > 20:
        verdicts.append(f"Subsidiaries contribute {pat_pct:.1f}% of profit (₹{pat_contribution:.0f} Cr)")

    if result["flags"]["margin_dilution"]:
        drag = abs(margin_drag)
        verdicts.append(f"EBITDA margin diluted by {drag:.1f} percentage points")

    if result["flags"]["revenue_dependent"]:
        verdicts.append(f"Subsidiaries drive {revenue_pct:.1f}% of revenue")

    if verdicts:
        result["verdict"] = ". ".join(verdicts) + "."
    else:
        # Check if subsidiaries are performing well
        if pat_contribution > 0 and margin_drag >= 0:
            result["verdict"] = "Subsidiaries performing in line with or better than parent."
        else:
            result["verdict"] = "Subsidiary impact is minimal."

    # Determine alert level
    if result["flags"]["profit_drain"] and abs(pat_contribution) > 50:
        result["alert_level"] = "high"
    elif result["flags"]["margin_dilution"] or result["flags"]["profit_drain"]:
        result["alert_level"] = "medium"
    elif result["flags"]["revenue_dependent"]:
        result["alert_level"] = "low"
    else:
        result["alert_level"] = "none"

    return result


def _safe_float(value: Any) -> float | None:
    """Convert value to float, returning None if invalid."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def extract_metrics_from_tables(
    tables: list[dict[str, Any]],
    table_type: str = "consolidated",
) -> dict[str, float]:
    """Extract financial metrics from parsed tables.

    Args:
        tables: List of table dicts with 'rows' key
        table_type: "consolidated" or "standalone"

    Returns:
        Dict with metric keys and values
    """
    from finagent.earnings.analysis import METRIC_SPECS

    metrics: dict[str, float] = {}

    for table in tables:
        rows = table.get("rows") or []
        for row in rows:
            if not row:
                continue
            row_text = " ".join(str(cell or "") for cell in row).lower()

            for spec in METRIC_SPECS:
                if spec.key in metrics:
                    continue
                if any(alias.lower() in row_text for alias in spec.aliases):
                    # Extract first numeric value from row
                    for cell in row[1:]:
                        val = _extract_number(cell)
                        if val is not None:
                            metrics[spec.key] = val
                            break

    return metrics


def _extract_number(cell: Any) -> float | None:
    """Extract a numeric value from a table cell."""
    import re

    text = str(cell or "").strip()
    if not text or text in {"-", "--", "na", "n.a."}:
        return None

    # Skip date-like strings
    if re.search(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", text):
        return None

    # Find number pattern
    match = re.search(r"\(?[-+]?\d[\d,]*(?:\.\d+)?\)?", text.replace("Rs.", "").replace("INR", ""))
    if not match:
        return None

    raw = match.group(0)
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()").replace(",", "")

    try:
        value = float(raw)
        return -value if negative else value
    except ValueError:
        return None
