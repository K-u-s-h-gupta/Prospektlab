from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from finagent.portfolio_mirrors import load_active_positions, portfolio_weights

logger = logging.getLogger("finagent.portfolio_sentinel")

CONCENTRATION_HHI_THRESHOLD = 0.25
CONCENTRATION_RULE = (
    "High structural concentration detected. Force downstream Forensic Accounting "
    "and Corporate Governance agents to prioritize inspection loops on high-weight entities."
)


@dataclass
class PortfolioSentinelResult:
    tenant_id: str
    positions_found: int = 0
    symbols: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def concentration_alert(self) -> bool:
        hhi = self.risk.get("hhi_analysis", {}).get("hhi_decimal")
        return isinstance(hhi, (int, float)) and hhi >= CONCENTRATION_HHI_THRESHOLD


async def run_portfolio_sentinel(tenant_id: str) -> PortfolioSentinelResult:
    result = PortfolioSentinelResult(tenant_id=tenant_id)
    positions = load_active_positions(tenant_id)
    result.positions_found = len(positions)
    result.symbols = [pos.exchange_symbol for pos in positions if pos.exchange_symbol]
    result.weights = portfolio_weights(positions)

    if not result.weights:
        result.error = "No active portfolio holdings found. Upload eCAS or CSV positions first."
        return result

    try:
        from finagent.tools.mcp_servers.quant_server import run_full_portfolio_risk

        portfolio_value = sum(pos.market_value for pos in positions if pos.market_value > 0)
        risk = await asyncio.to_thread(
            run_full_portfolio_risk,
            result.weights,
            "^NSEI",
            "1y",
            portfolio_value,
        )
        result.risk = risk if isinstance(risk, dict) else {"error": "Unexpected risk result"}
        if result.concentration_alert:
            result.rules.append(CONCENTRATION_RULE)
    except Exception as exc:
        logger.warning("Portfolio Sentinel failed for tenant %s: %s", tenant_id, exc)
        result.error = str(exc)
    return result
