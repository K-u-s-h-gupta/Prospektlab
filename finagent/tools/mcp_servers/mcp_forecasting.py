"""
mcp_forecasting.py
==================
FastMCP Server that exposes Google TimesFM 2.5 (200M) zero-shot forecasting
as reusable MCP tools.

This allows any agent (ValuationAgent, AccountingAgent, or external clients)
to call TimesFM forecasting over HTTP instead of importing the module directly.

Exposed Tools:
- generate_zero_shot_forecast
- detect_anomalies

Run with:
    python -m finagent.tools.mcp_servers.mcp_forecasting
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

# Import the core forecasting logic (in-process implementation)
from finagent.tools.mcp.forecasting import (
    generate_zero_shot_forecast as _generate_forecast,
    detect_anomalies as _detect_anomalies,
    ForecastResult,
    AnomalyResult,
)

mcp = FastMCP("TimesFM 2.5 Forecasting Engine")


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def generate_zero_shot_forecast(
    values: list[float],
    horizon: int = 8,
    freq: int = 1,
    quantiles: list[float] | None = None,
) -> dict[str, Any]:
    """
    Project a numerical time series N periods into the future using
    Google Research TimesFM 2.5 (200M parameter zero-shot model).

    Returns point forecasts + quantile risk bands (P10, P25, P50, P75, P90).

    Parameters:
        values: Historical time series (oldest first), e.g. [100, 105, 112, 119]
        horizon: Number of future periods to forecast (default 8)
        freq: Frequency indicator for TimesFM (0=high-freq, 1=medium, 2=low)
        quantiles: List of quantiles to return (default [0.1, 0.25, 0.5, 0.75, 0.9])

    Returns:
        Dictionary containing point_forecast, quantile_forecasts, model_used, etc.
    """
    if not values or len(values) < 2:
        return {
            "error": "At least 2 historical values are required",
            "point_forecast": [],
            "model_used": "none",
        }

    try:
        result: ForecastResult = await _generate_forecast(
            values,
            horizon=horizon,
            freq=freq,
            quantiles=quantiles,
        )

        return {
            "point_forecast": result.point_forecast,
            "quantile_forecasts": result.quantile_forecasts,
            "horizon": result.horizon,
            "model_used": result.model_used,
            "metadata": result.metadata,
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "point_forecast": [],
            "model_used": "error",
        }


@mcp.tool()
async def detect_anomalies(
    historical: list[float],
    new_values: list[float],
    freq: int = 1,
) -> dict[str, Any]:
    """
    Use TimesFM 2.5 to detect whether newly reported values are anomalous
    compared to historical patterns.

    Builds P10–P90 confidence corridors from the model's probabilistic forecast.
    Values falling outside the corridor are flagged as anomalies.

    Parameters:
        historical: Past time series forming the context (oldest first)
        new_values: Newly observed values to evaluate
        freq: Frequency indicator (0=high, 1=medium, 2=low)

    Returns:
        Per-value anomaly flags, confidence bounds, deviation magnitudes, and model_used.
    """
    if not historical or len(historical) < 3 or not new_values:
        return {
            "error": "Need at least 3 historical points and at least one new value",
            "is_anomaly": [False] * len(new_values) if new_values else [],
            "model_used": "none",
        }

    try:
        result: AnomalyResult = await _detect_anomalies(
            historical,
            new_values,
            freq=freq,
        )

        return {
            "is_anomaly": result.is_anomaly,
            "lower_bound": result.lower_bound,
            "upper_bound": result.upper_bound,
            "deviations": result.deviations,
            "model_used": result.model_used,
            "metadata": result.metadata,
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "is_anomaly": [False] * len(new_values),
            "model_used": "error",
        }


# ---------------------------------------------------------------------------
# Server Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting TimesFM 2.5 Forecasting MCP Server on port 8006...")
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8006,
    )
