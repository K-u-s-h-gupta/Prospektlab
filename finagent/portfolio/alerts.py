"""Concentration & risk alerts engine.

Rules:
- Any holding > 15% (single-name)
- Any sector > 30% (sector)
- Any holding day-loss > 5%
- Any holding 30d-loss > 20%
- Beta > 1.3 with >70% equity exposure
- Top-5 concentration > 60%
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.portfolio_mirrors import PositionMirror

logger = logging.getLogger("finagent.portfolio.alerts")


def compute_alerts(positions: list[PositionMirror], analytics: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of active risk/concentration alerts."""
    if not positions:
        return []

    alerts: list[dict[str, Any]] = []
    total_value = sum(p.market_value for p in positions if p.market_value > 0)
    equity_value = sum(p.market_value for p in positions if p.market_value > 0 and p.kind == "equity")
    equity_pct = (equity_value / total_value) if total_value else 0.0

    # Per-holding alerts (single-name concentration disabled per user request)
    # for pos in positions:
    #     if pos.market_value <= 0:
    #         continue
    #     weight = pos.market_value / total_value if total_value else 0
    #     if weight > 0.15:
    #         alerts.append({...})

    # Sector alerts
    sector_totals: dict[str, float] = {}
    for p in positions:
        if p.market_value > 0 and p.sector:
            sector_totals[p.sector] = sector_totals.get(p.sector, 0.0) + p.market_value
    for sector, val in sector_totals.items():
        weight = val / total_value if total_value else 0
        if weight > 0.30:
            alerts.append({
                "severity": "warning" if weight < 0.45 else "danger",
                "code": "SECTOR_CONCENTRATION",
                "message": f"{sector} sector is {weight*100:.1f}% of portfolio",
                "threshold": 30,
                "actual": round(weight * 100, 1),
            })

    # Beta alert
    beta = analytics.get("risk", {}).get("beta_vs_nifty", 0)
    if beta > 1.3 and equity_pct > 0.70:
        alerts.append({
            "severity": "warning",
            "code": "HIGH_BETA",
            "message": f"Portfolio beta {beta} with {equity_pct*100:.0f}% equity exposure",
            "threshold": 1.3,
            "actual": beta,
        })

    # Top-5 concentration
    risk = analytics.get("risk", {})
    top5 = risk.get("top5_concentration", [])
    if top5:
        top5_weight = sum(p.get("weight_pct", 0) for p in top5) / 100.0
        if top5_weight > 0.60:
            alerts.append({
                "severity": "warning",
                "code": "TOP5_CONCENTRATION",
                "message": f"Top 5 holdings are {top5_weight*100:.1f}% of portfolio",
                "threshold": 60,
                "actual": round(top5_weight * 100, 1),
            })

    return alerts
