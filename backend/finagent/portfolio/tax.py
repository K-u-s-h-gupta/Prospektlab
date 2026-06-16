"""Tax pre-computation (STCG / LTCG) for Indian portfolios.

Assumes FY 2025-26 rates:
- Equity STCG: 20%
- Equity LTCG: 12.5% above ₹1.25L exemption
- Debt MF STCG: applicable slab rates (approximated as 20% for simplicity)
- Debt MF LTCG: 20% with indexation

Note: This is an estimate only. Actual tax liability depends on
filing status, other income, deductions, etc.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from finagent.portfolio_mirrors import PositionMirror

logger = logging.getLogger("finagent.portfolio.tax")

# FY 2025-26 rates
_EQUITY_LTCG_RATE = 0.125
_EQUITY_LTCG_EXEMPTION = 1_25_000
_EQUITY_STCG_RATE = 0.20
_DEBT_LTCG_RATE = 0.20
_DEBT_STCG_RATE = 0.20
_LTCG_THRESHOLD_DAYS = 365


def classify_gain_type(kind: str, days_held: int) -> str:
    """STCG or LTCG classification."""
    if kind == "equity":
        return "LTCG" if days_held > _LTCG_THRESHOLD_DAYS else "STCG"
    # MF: same threshold for equity-oriented; debt MF always LTCG if > 36mo but we use 1y for simplicity
    return "LTCG" if days_held > _LTCG_THRESHOLD_DAYS else "STCG"


def estimate_tax_realized(gain_amount: float, gain_type: str, kind: str, cumulative_ltcg: float = 0.0) -> float:
    """Estimate tax on a realized gain."""
    if gain_amount <= 0:
        return 0.0
    if kind == "equity":
        if gain_type == "STCG":
            return gain_amount * _EQUITY_STCG_RATE
        else:
            # LTCG with exemption
            taxable = max(0.0, cumulative_ltcg + gain_amount - _EQUITY_LTCG_EXEMPTION)
            return taxable * _EQUITY_LTCG_RATE
    else:
        if gain_type == "STCG":
            return gain_amount * _DEBT_STCG_RATE
        else:
            # Simplified: no indexation in this estimate
            return gain_amount * _DEBT_LTCG_RATE


def compute_tax_summary(positions: list[PositionMirror]) -> dict[str, Any]:
    """Compute tax summary for the portfolio.

    Returns realized + unrealized splits with tax estimates.
    Since we don't have individual lot purchase dates from CAS yet,
    we estimate days held from as_of date if available.
    """
    if not positions:
        return {"status": "NO_DATA"}

    unrealized_stcg = 0.0
    unrealized_ltcg = 0.0
    total_unrealized = 0.0
    position_taxes = []
    harvest_opportunities: list[dict[str, Any]] = []
    total_harvestable_loss = 0.0
    total_potential_shield = 0.0

    def _marginal_rate(gain_type: str, kind: str) -> float:
        if kind == "equity":
            return _EQUITY_STCG_RATE if gain_type == "STCG" else _EQUITY_LTCG_RATE
        return _DEBT_STCG_RATE if gain_type == "STCG" else _DEBT_LTCG_RATE

    for pos in positions:
        mkt_val = pos.market_value
        cost = pos.cost_basis or (pos.avg_cost * pos.quantity)
        gain = mkt_val - cost if cost else 0.0
        if gain == 0:
            continue

        # Estimate days held from as_of if present; otherwise assume STCG
        days_held = 0
        if pos.as_of:
            try:
                as_of_dt = datetime.fromisoformat(str(pos.as_of).replace("Z", "+00:00"))
                if as_of_dt.tzinfo is None:
                    as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
                days_held = (datetime.now(timezone.utc) - as_of_dt).days
            except Exception:
                pass
        gain_type = classify_gain_type(pos.kind, days_held)

        # Tax on unrealized (estimate if sold today)
        tax = estimate_tax_realized(gain, gain_type, pos.kind)

        if gain_type == "STCG":
            unrealized_stcg += gain
        else:
            unrealized_ltcg += gain
        total_unrealized += gain

        position_taxes.append({
            "symbol": pos.exchange_symbol,
            "name": pos.name,
            "kind": pos.kind,
            "gain": round(gain, 2),
            "gain_type": gain_type,
            "estimated_tax": round(tax, 2),
            "days_held": days_held,
        })

        # Tax-loss harvesting: a position sitting on an unrealized loss can be sold
        # to book that loss and offset realized gains. Shield = loss × marginal rate.
        if gain < 0:
            loss = abs(gain)
            shield = loss * _marginal_rate(gain_type, pos.kind)
            total_harvestable_loss += loss
            total_potential_shield += shield
            harvest_opportunities.append({
                "symbol": pos.exchange_symbol,
                "name": pos.name,
                "kind": pos.kind,
                "gain_type": gain_type,
                "unrealized_loss": round(loss, 2),
                "loss_pct": round((gain / cost) * 100, 2) if cost else None,
                "potential_tax_shield": round(shield, 2),
                "days_held": days_held,
            })

    harvest_opportunities.sort(key=lambda x: x.get("potential_tax_shield", 0), reverse=True)

    return {
        "status": "OK",
        "unrealized_total": round(total_unrealized, 2),
        "unrealized_stcg": round(unrealized_stcg, 2),
        "unrealized_ltcg": round(unrealized_ltcg, 2),
        "estimated_tax_if_sold_today": round(
            estimate_tax_realized(unrealized_stcg, "STCG", "equity") +
            estimate_tax_realized(unrealized_ltcg, "LTCG", "equity"),
            2,
        ),
        "harvest": {
            "opportunities": harvest_opportunities,
            "count": len(harvest_opportunities),
            "total_harvestable_loss": round(total_harvestable_loss, 2),
            "total_potential_shield": round(total_potential_shield, 2),
        },
        "positions": position_taxes,
        "fy_rates": {
            "equity_stcg": f"{_EQUITY_STCG_RATE*100:.0f}%",
            "equity_ltcg": f"{_EQUITY_LTCG_RATE*100:.1f}% above ₹{_EQUITY_LTCG_EXEMPTION/1000:.0f}k",
            "debt_stcg": f"{_DEBT_STCG_RATE*100:.0f}%",
            "debt_ltcg": f"{_DEBT_LTCG_RATE*100:.0f}%",
        },
    }
