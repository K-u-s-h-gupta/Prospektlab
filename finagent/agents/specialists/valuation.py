"""ValuationAgent — data-driven DCF projections via TimesFM zero-shot forecasts.

Replaces static or rule-based growth assumptions with transformer-based
time-series projections.  Extracts historical revenue (and optionally
operating-margin) arrays from the enrichment bundle, feeds them into the
TimesFM forecasting module, and uses the resulting P50 projected values
as DCF terminal growth inputs.

Falls back to CAGR-based growth when TimesFM is unavailable.
"""

from __future__ import annotations

import logging

from finagent.accuracy_validator import Claim
from finagent.agents.base import (
    AgentTaskResult,
    BaseSubAgent,
    Finding,
    SubAgentContext,
)
from finagent.tools.mcp.forecasting import cagr as _cagr   # shared implementation

logger = logging.getLogger("finagent.agents.specialists.valuation")


def _fmt_compact(value: float) -> str:
    """Format a large number compactly (e.g. 1.23B, 456.7M)."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e12:
        return f"{sign}{v / 1e12:,.2f}T"
    if v >= 1e9:
        return f"{sign}{v / 1e9:,.2f}B"
    if v >= 1e6:
        return f"{sign}{v / 1e6:,.2f}M"
    if v >= 1e3:
        return f"{sign}{v / 1e3:,.2f}K"
    return f"{sign}{v:,.2f}"


class ValuationAgent(BaseSubAgent):
    """Specialist that computes forward-looking valuations using TimesFM projections."""

    name = "valuation"
    display = "Valuation & DCF Projections"
    priority = 40
    dependencies = ("financials",)

    def precondition(self, ctx: SubAgentContext) -> tuple[bool, str]:
        yahoo = ctx.bundle.yahoo if ctx.bundle else None
        sec = ctx.bundle.sec if ctx.bundle else None

        has_revenue_history = False
        if yahoo and yahoo.annual_revenue and len(yahoo.annual_revenue) >= 3:
            has_revenue_history = True
        if sec and hasattr(sec, "quarterly_revenue") and sec.quarterly_revenue:
            has_revenue_history = True

        if not has_revenue_history:
            return False, "insufficient revenue history for projection"
        return True, ""

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        logger.info("[VALUATION-START] valuation agent starts processing...")
        out = AgentTaskResult(agent_name=self.name)
        yahoo = ctx.bundle.yahoo if ctx.bundle else None
        sec = ctx.bundle.sec if ctx.bundle else None

        # ── 1. Extract historical revenue array ────────────────────────
        revenue_values: list[float] = []
        revenue_dates: list[str] = []
        currency: str = "INR"

        if yahoo and yahoo.annual_revenue and len(yahoo.annual_revenue) >= 3:
            revenue_values = list(yahoo.annual_revenue)
            revenue_dates = list(yahoo.annual_revenue_dates) if yahoo.annual_revenue_dates else []
            currency = (yahoo.currency or "INR").upper()
        elif sec and hasattr(sec, "quarterly_revenue") and sec.quarterly_revenue:
            for q in sec.quarterly_revenue:
                val = q.get("value") if isinstance(q, dict) else getattr(q, "value", None)
                if val is not None:
                    revenue_values.append(float(val))
                    date = q.get("date", "") if isinstance(q, dict) else getattr(q, "date", "")
                    revenue_dates.append(str(date))

        if len(revenue_values) < 3:
            out.status = "partial"
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="financial",
                    headline="Insufficient data for valuation projection",
                    detail="Need at least 3 historical revenue data points to generate forecasts.",
                    confidence="LOW",
                    evidence=[],
                    metrics={"data_points_available": len(revenue_values)},
                )
            )
            return out

        # ── 2. Run TimesFM forecast ────────────────────────────────────
        # Note: The forecasting logic can also be called via the dedicated
        # MCP server (mcp_forecasting.py on port 8006) for external clients.
        # Inside the agent we currently use the fast in-process version.
        try:
            from finagent.tools.mcp.forecasting import generate_zero_shot_forecast
        except ImportError:
            logger.warning("forecasting module unavailable")
            generate_zero_shot_forecast = None  # type: ignore[assignment]

        forecast_result = None
        horizon = min(8, max(4, len(revenue_values)))  # 4-8 periods

        if generate_zero_shot_forecast is not None:
            logger.info("[TIMESFM] ValuationAgent -> calling generate_zero_shot_forecast (real or fallback)")
            try:
                forecast_result = await generate_zero_shot_forecast(
                    revenue_values,
                    horizon=horizon,
                    freq=2,  # low-frequency (annual data)
                    quantiles=[0.1, 0.25, 0.5, 0.75, 0.9],
                )
            except Exception as exc:
                logger.warning("Forecast call failed: %s", exc)

        # ── 3. Extract projections or fall back ────────────────────────
        if forecast_result and forecast_result.point_forecast:
            projected = forecast_result.point_forecast
            model_used = forecast_result.model_used
            q50 = forecast_result.quantile_forecasts.get(0.5, projected)
            q10 = forecast_result.quantile_forecasts.get(0.1, [])
            q90 = forecast_result.quantile_forecasts.get(0.9, [])
        else:
            # Pure CAGR fallback
            growth = _cagr(revenue_values) or 0.08
            last = revenue_values[-1]
            projected = [last * (1 + growth) ** (i + 1) for i in range(horizon)]
            q50 = projected
            q10 = [p * 0.85 for p in projected]
            q90 = [p * 1.15 for p in projected]
            model_used = "fallback_cagr"

        # ── 4. Compute implied growth rate ─────────────────────────────
        current_rev = revenue_values[-1]
        terminal_rev = q50[-1] if q50 else projected[-1]
        years_out = len(projected)

        if current_rev > 0 and terminal_rev > 0:
            implied_growth = (terminal_rev / current_rev) ** (1.0 / years_out) - 1
        else:
            implied_growth = _cagr(revenue_values) or 0.05

        logger.info("[VALUATION-FORECAST] forecast generated using model: %s | projected_values_len=%d | implied_growth=%.2f%%", model_used, len(projected), implied_growth * 100)

        historical_cagr = _cagr(revenue_values)

        # ── 5. Emit projection finding ─────────────────────────────────
        p10_terminal = q10[-1] if q10 else terminal_rev * 0.85
        p90_terminal = q90[-1] if q90 else terminal_rev * 1.15

        is_real_timesfm = model_used == "timesfm_2.5"
        headline = (
            f"TimesFM 2.5 Revenue Projection: {_fmt_compact(terminal_rev)} in {years_out}yr"
            if is_real_timesfm else
            f"Revenue Projection (statistical fallback): {_fmt_compact(terminal_rev)} in {years_out}yr"
        )

        detail = (
            f"TimesFM 2.5 zero-shot forecast (real model) based on {len(revenue_values)} historical points. "
            f"Projected {currency} revenue in {years_out} years: {_fmt_compact(terminal_rev)} (P50). "
            f"Risk corridor: {_fmt_compact(p10_terminal)} (P10) – {_fmt_compact(p90_terminal)} (P90). "
            f"Implied CAGR from TimesFM: {implied_growth * 100:+.1f}%."
            if is_real_timesfm else
            f"Statistical fallback (CAGR-based) used because TimesFM 2.5 was unavailable. "
            f"Projected {currency} revenue in {years_out} years: {_fmt_compact(terminal_rev)} (P50). "
            f"Implied CAGR: {implied_growth * 100:+.1f}%."
        )

        out.findings.append(
            Finding(
                agent=self.name,
                kind="financial",
                headline=headline,
                detail=detail,
                confidence="MEDIUM" if is_real_timesfm else "LOW",
                evidence=[yahoo.source_url] if yahoo else [],
                metrics={
                    "projected_terminal_revenue": terminal_rev,
                    "implied_growth_rate": implied_growth,
                    "historical_cagr": historical_cagr,
                    "model_used": model_used,
                    "horizon_years": years_out,
                    "p10_terminal": p10_terminal,
                    "p90_terminal": p90_terminal,
                    "timesfm_active": is_real_timesfm,
                },
            )
        )

        # ── 6. Attempt DCF if we have the inputs ──────────────────────
        dcf_result = None
        metrics = yahoo.financial_metrics if yahoo else {}
        fcf = metrics.get("free_cashflow")
        total_debt = metrics.get("total_debt", 0)
        total_cash = metrics.get("total_cash", 0)
        market_cap = metrics.get("market_cap") or (yahoo.market_cap if yahoo else None)
        shares = None
        if market_cap and yahoo and yahoo.price and yahoo.price > 0:
            shares = market_cap / yahoo.price

        if fcf and fcf > 0 and shares and shares > 0:
            try:
                from finagent.tools.valuation_engine import dcf_valuation

                # Cap growth rates at reasonable bounds.
                high_growth = max(0.03, min(0.35, implied_growth))
                stable_growth = max(0.03, min(0.12, high_growth * 0.5))

                ticker_str = yahoo.ticker if yahoo else (sec.ticker if (sec and hasattr(sec, "ticker")) else "UNKNOWN")
                logger.info("[MCP-USE] valuation_engine | tool=run_dcf_valuation | args={'symbol': '%s'}", ticker_str)
                try:
                    from finagent.state.session_context import record_mcp
                    record_mcp("valuation_engine")
                except ImportError:
                    pass

                dcf_result = dcf_valuation(
                    free_cash_flow=fcf,
                    growth_rate_high=high_growth,
                    growth_rate_stable=stable_growth,
                    high_growth_years=5,
                    discount_rate=max(high_growth + 0.02, 0.10),
                    terminal_growth_rate=0.04,
                    shares_outstanding=shares,
                    net_debt=(total_debt or 0) - (total_cash or 0),
                )
            except Exception as exc:
                logger.warning("DCF computation failed: %s", exc)

        if dcf_result and "intrinsic_value_per_share" in dcf_result:
            intrinsic = dcf_result["intrinsic_value_per_share"]
            current_price = yahoo.price if yahoo else None
            upside = None
            if current_price and current_price > 0:
                upside = ((intrinsic - current_price) / current_price) * 100

            verdict = ""
            if upside is not None:
                if upside > 15:
                    verdict = " — potentially UNDERVALUED"
                elif upside < -15:
                    verdict = " — potentially OVERVALUED"
                else:
                    verdict = " — FAIRLY VALUED"

            detail_parts = [
                f"DCF intrinsic value per share: {currency} {intrinsic:,.2f}",
            ]
            if current_price:
                detail_parts.append(f"Current price: {currency} {current_price:,.2f}")
            if upside is not None:
                detail_parts.append(f"Upside: {upside:+.1f}%{verdict}")
            detail_parts.append(
                f"Using TimesFM-derived growth of {high_growth * 100:.1f}% (high) / "
                f"{stable_growth * 100:.1f}% (stable)."
            )

            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="financial",
                    headline=f"DCF intrinsic value: {currency} {intrinsic:,.2f}{verdict}",
                    detail=" ".join(detail_parts),
                    confidence="MEDIUM",
                    evidence=[yahoo.source_url] if yahoo else [],
                    metrics={
                        "intrinsic_value": intrinsic,
                        "current_price": current_price,
                        "upside_pct": upside,
                        "high_growth_rate": high_growth,
                        "stable_growth_rate": stable_growth,
                        "fcf": fcf,
                        "dcf_model": dcf_result.get("model"),
                    },
                )
            )
            out.claims.append(
                Claim(
                    text=(
                        f"TimesFM-projected DCF intrinsic value is {currency} {intrinsic:,.2f}"
                        + (f" ({upside:+.1f}% vs current price)" if upside is not None else "")
                        + "."
                    ),
                    is_material=True,
                )
            )

        # ── 7. Margin projection if operating margins available ────────
        op_margins_val = metrics.get("operating_margins")
        if (
            op_margins_val is not None
            and yahoo
            and yahoo.annual_revenue
            and len(yahoo.annual_revenue) >= 3
        ):
            # Synthesize a margin series from revenue + margin.
            margin_pct = op_margins_val * 100
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="financial",
                    headline=f"Operating margin context: {margin_pct:.1f}%",
                    detail=(
                        f"Current operating margin of {margin_pct:.1f}% applied to "
                        f"projected terminal revenue of {_fmt_compact(terminal_rev)} yields "
                        f"implied operating income of "
                        f"{_fmt_compact(terminal_rev * op_margins_val)} in {years_out} years."
                    ),
                    confidence="LOW",
                    evidence=[yahoo.source_url] if yahoo else [],
                    metrics={
                        "operating_margin": op_margins_val,
                        "projected_op_income": terminal_rev * op_margins_val,
                    },
                )
            )

        if not out.findings:
            out.status = "partial"

        intrinsic_str = "None"
        if dcf_result and "intrinsic_value_per_share" in dcf_result:
            intrinsic_str = f"{dcf_result['intrinsic_value_per_share']:.2f}"
        logger.info("[VALUATION-DONE] ValuationAgent completed | intrinsic_value=%s | status=%s", intrinsic_str, out.status)
        return out
