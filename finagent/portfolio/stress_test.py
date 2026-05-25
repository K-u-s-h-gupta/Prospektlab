"""Stress test simulator.

Computes portfolio sensitivity = Σ(weight_i × beta_i × shock).
Also supports sector-shock scenarios.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from finagent.portfolio_mirrors import PositionMirror
from finagent.portfolio.analytics import _fetch_history, _is_valid_ticker

logger = logging.getLogger("finagent.portfolio.stress_test")


def _compute_single_beta(ticker: str) -> float:
    """Compute 1Y beta vs Nifty for a single ticker."""
    if not _is_valid_ticker(ticker):
        return 1.0
    try:
        import yfinance as yf
        t_hist = _fetch_history(ticker, period="1y")
        n_hist = _fetch_history("^NSEI", period="1y")
        if not t_hist.get("prices") or not n_hist.get("prices"):
            return 1.0
        t_rets = np.diff(np.log(np.array(t_hist["prices"])))
        n_rets = np.diff(np.log(np.array(n_hist["prices"])))
        min_len = min(len(t_rets), len(n_rets))
        if min_len < 10:
            return 1.0
        cov = np.cov(t_rets[-min_len:], n_rets[-min_len:])[0, 1]
        var = np.var(n_rets[-min_len:])
        return float(cov / var) if var else 1.0
    except Exception as exc:
        logger.debug("Beta compute failed for %s: %s", ticker, exc)
        return 1.0


SCENARIOS: dict[str, dict[str, float]] = {
    "nifty_down_10": {"nifty": -0.10},
    "nifty_down_20": {"nifty": -0.20},
    "nifty_down_30": {"nifty": -0.30},
    "banks_down_15": {"nifty": -0.05, "banks": -0.15},
    "it_down_20": {"nifty": -0.05, "it": -0.20},
}


def run_stress_test(
    positions: list[PositionMirror],
    scenario: str = "nifty_down_20",
    custom_shocks: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run stress test on portfolio.

    Returns projected portfolio loss % and per-position impact.
    """
    if not positions:
        return {"status": "NO_DATA", "portfolio_loss_pct": 0.0, "positions": []}

    total_value = sum(p.market_value for p in positions if p.market_value > 0)
    if total_value <= 0:
        return {"status": "NO_DATA", "portfolio_loss_pct": 0.0, "positions": []}

    shocks = custom_shocks or SCENARIOS.get(scenario, {"nifty": -0.20})

    portfolio_loss = 0.0
    pos_results = []
    for pos in positions:
        if pos.market_value <= 0:
            continue
        weight = pos.market_value / total_value
        beta = _compute_single_beta(pos.exchange_symbol) if pos.kind == "equity" else 0.0

        # Determine applicable shock
        shock = shocks.get("nifty", 0.0)
        for sector_key, sector_shock in shocks.items():
            if sector_key == "nifty":
                continue
            if sector_key.lower() in (pos.sector or "").lower():
                shock = sector_shock
                break

        # Impact = weight * beta * shock
        impact = weight * beta * shock
        portfolio_loss += impact

        pos_results.append({
            "symbol": pos.exchange_symbol,
            "name": pos.name,
            "weight_pct": round(weight * 100, 2),
            "beta": round(beta, 2),
            "shock_pct": round(shock * 100, 1),
            "impact_pct": round(impact * 100, 2),
        })

    pos_results.sort(key=lambda x: abs(x.get("impact_pct", 0)), reverse=True)

    return {
        "status": "OK",
        "scenario": scenario,
        "portfolio_loss_pct": round(portfolio_loss * 100, 2),
        "total_value": round(total_value, 2),
        "positions": pos_results,
        "available_scenarios": list(SCENARIOS.keys()),
    }
