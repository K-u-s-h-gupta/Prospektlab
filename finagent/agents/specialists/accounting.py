"""AccountingAgent — forensic anomaly detection via TimesFM confidence corridors.

Ingests sequential historical financial series (revenue, net income,
quarterly profits) into TimesFM to build P10–P90 confidence corridors.
If newly reported values fall outside these corridors, the agent flags a
structural accounting anomaly.

Falls back to ±2σ z-score bands when TimesFM is unavailable.
"""

from __future__ import annotations

import logging
import statistics

from finagent.accuracy_validator import Claim
from finagent.agents.base import (
    AgentTaskResult,
    BaseSubAgent,
    Finding,
    SubAgentContext,
)

logger = logging.getLogger("finagent.agents.specialists.accounting")


def _safe_pct_change(a: float, b: float) -> float | None:
    """Percentage change from a to b."""
    if a == 0 or a is None or b is None:
        return None
    return (b - a) / abs(a)


class AccountingAgent(BaseSubAgent):
    """Specialist that detects structural anomalies in financial reporting."""

    name = "accounting"
    display = "Forensic Accounting"
    priority = 45
    dependencies = ("financials",)

    def precondition(self, ctx: SubAgentContext) -> tuple[bool, str]:
        yahoo = ctx.bundle.yahoo if ctx.bundle else None
        sec = ctx.bundle.sec if ctx.bundle else None

        has_data = False
        if yahoo:
            if yahoo.annual_revenue and len(yahoo.annual_revenue) >= 4:
                has_data = True
            if yahoo.annual_net_income and len(yahoo.annual_net_income) >= 4:
                has_data = True
        if sec and hasattr(sec, "quarterly_revenue") and len(sec.quarterly_revenue) >= 4:
            has_data = True

        if not has_data:
            return False, "insufficient historical data for anomaly detection"
        return True, ""

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        yahoo = ctx.bundle.yahoo if ctx.bundle else None
        sec = ctx.bundle.sec if ctx.bundle else None

        # ── Import forecasting module ──────────────────────────────────
        try:
            from finagent.tools.mcp.forecasting import detect_anomalies
        except ImportError:
            logger.warning("forecasting module unavailable for accounting agent")
            detect_anomalies = None  # type: ignore[assignment]

        anomaly_count = 0
        clean_count = 0
        evidence_urls = []
        if yahoo:
            evidence_urls.append(yahoo.source_url)

        # ── 1. Annual revenue anomaly check ────────────────────────────
        if yahoo and yahoo.annual_revenue and len(yahoo.annual_revenue) >= 4:
            anomaly_count, clean_count = await self._check_series(
                out=out,
                series_name="Annual Revenue",
                values=yahoo.annual_revenue,
                dates=yahoo.annual_revenue_dates,
                detect_fn=detect_anomalies,
                evidence=evidence_urls,
                anomaly_count=anomaly_count,
                clean_count=clean_count,
            )

        # ── 2. Annual net income anomaly check ─────────────────────────
        if yahoo and yahoo.annual_net_income and len(yahoo.annual_net_income) >= 4:
            anomaly_count, clean_count = await self._check_series(
                out=out,
                series_name="Annual Net Income",
                values=yahoo.annual_net_income,
                dates=yahoo.annual_net_income_dates,
                detect_fn=detect_anomalies,
                evidence=evidence_urls,
                anomaly_count=anomaly_count,
                clean_count=clean_count,
            )

        # ── 3. Quarterly series from India snapshot ────────────────────
        if sec and hasattr(sec, "quarterly_revenue") and sec.quarterly_revenue:
            q_values = []
            q_dates = []
            for q in sec.quarterly_revenue:
                val = q.get("value") if isinstance(q, dict) else getattr(q, "value", None)
                date = q.get("date", "") if isinstance(q, dict) else getattr(q, "date", "")
                if val is not None:
                    q_values.append(float(val))
                    q_dates.append(str(date))

            if len(q_values) >= 4:
                anomaly_count, clean_count = await self._check_series(
                    out=out,
                    series_name="Quarterly Revenue",
                    values=q_values,
                    dates=q_dates,
                    detect_fn=detect_anomalies,
                    evidence=evidence_urls,
                    anomaly_count=anomaly_count,
                    clean_count=clean_count,
                )

        if sec and hasattr(sec, "quarterly_profit") and sec.quarterly_profit:
            q_values = []
            q_dates = []
            for q in sec.quarterly_profit:
                val = q.get("value") if isinstance(q, dict) else getattr(q, "value", None)
                date = q.get("date", "") if isinstance(q, dict) else getattr(q, "date", "")
                if val is not None:
                    q_values.append(float(val))
                    q_dates.append(str(date))

            if len(q_values) >= 4:
                anomaly_count, clean_count = await self._check_series(
                    out=out,
                    series_name="Quarterly Profit",
                    values=q_values,
                    dates=q_dates,
                    detect_fn=detect_anomalies,
                    evidence=evidence_urls,
                    anomaly_count=anomaly_count,
                    clean_count=clean_count,
                )

        # ── 4. Working capital / ratio anomaly heuristics ──────────────
        if yahoo and yahoo.financial_metrics:
            self._check_ratio_flags(out, yahoo.financial_metrics, evidence_urls)

        # ── 5. Summary finding ─────────────────────────────────────────
        if anomaly_count == 0 and clean_count > 0:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="financial",
                    headline="No structural accounting anomalies detected",
                    detail=(
                        f"All {clean_count} financial series passed anomaly screening. "
                        "Latest reported values fall within expected confidence corridors."
                    ),
                    confidence="MEDIUM",
                    evidence=evidence_urls,
                    metrics={"series_checked": clean_count, "anomalies": 0},
                )
            )
        elif anomaly_count > 0:
            out.claims.append(
                Claim(
                    text=(
                        f"Forensic accounting screen flagged {anomaly_count} "
                        f"anomaly/anomalies across {anomaly_count + clean_count} series examined."
                    ),
                    is_material=True,
                )
            )

        if not out.findings:
            out.status = "partial"

        return out

    async def _check_series(
        self,
        *,
        out: AgentTaskResult,
        series_name: str,
        values: list[float],
        dates: list[str],
        detect_fn,
        evidence: list[str],
        anomaly_count: int,
        clean_count: int,
    ) -> tuple[int, int]:
        """Run anomaly detection on one financial series.

        Returns updated (anomaly_count, clean_count).
        """
        historical = values[:-1]
        new_value = [values[-1]]
        latest_date = dates[-1] if dates else "latest period"

        result = None
        if detect_fn is not None:
            try:
                result = await detect_fn(historical, new_value, freq=2)
            except Exception as exc:
                logger.warning("Anomaly detection failed for %s: %s", series_name, exc)

        if result is None:
            # In-line z-score fallback.
            result = self._zscore_check(historical, new_value)

        is_anomaly = result.is_anomaly[0] if result.is_anomaly else False
        model_used = result.model_used
        deviation = result.deviations[0] if result.deviations else 0.0
        lower = result.lower_bound[0] if result.lower_bound else 0.0
        upper = result.upper_bound[0] if result.upper_bound else 0.0

        if is_anomaly:
            anomaly_count += 1
            severity = "significant" if abs(deviation) > 3.0 else "moderate"
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="risk",
                    headline=f"⚠ {series_name} anomaly detected ({latest_date})",
                    detail=(
                        f"The latest {series_name} value of {values[-1]:,.2f} "
                        f"falls OUTSIDE the model's P10–P90 confidence corridor "
                        f"[{lower:,.2f} – {upper:,.2f}]. "
                        f"Deviation magnitude: {deviation:+.2f}σ ({severity}). "
                        f"Model: {model_used}. "
                        "This may indicate unusual accounting activity, "
                        "one-time charges, structural business changes, "
                        "or potential financial restatement risk."
                    ),
                    confidence="HIGH" if severity == "significant" else "MEDIUM",
                    evidence=evidence,
                    metrics={
                        "series": series_name,
                        "latest_value": values[-1],
                        "expected_lower": lower,
                        "expected_upper": upper,
                        "deviation_sigma": deviation,
                        "severity": severity,
                        "model": model_used,
                    },
                )
            )
        else:
            clean_count += 1

        return anomaly_count, clean_count

    @staticmethod
    def _zscore_check(historical: list[float], new_values: list[float]):
        """Inline z-score fallback when both forecasting module and detect_anomalies fail."""
        from dataclasses import dataclass, field as dc_field

        @dataclass
        class _SimpleResult:
            is_anomaly: list[bool]
            lower_bound: list[float]
            upper_bound: list[float]
            deviations: list[float]
            model_used: str = "inline_zscore"

        if len(historical) < 3:
            return _SimpleResult(
                is_anomaly=[False] * len(new_values),
                lower_bound=[0.0] * len(new_values),
                upper_bound=[0.0] * len(new_values),
                deviations=[0.0] * len(new_values),
            )

        mu = statistics.mean(historical)
        sigma = statistics.stdev(historical)
        if sigma == 0:
            sigma = abs(mu) * 0.01 or 1.0

        lo = mu - 2.0 * sigma
        hi = mu + 2.0 * sigma

        flags = [v < lo or v > hi for v in new_values]
        devs = [(v - mu) / sigma for v in new_values]

        return _SimpleResult(
            is_anomaly=flags,
            lower_bound=[lo] * len(new_values),
            upper_bound=[hi] * len(new_values),
            deviations=devs,
        )

    @staticmethod
    def _check_ratio_flags(
        out: AgentTaskResult,
        metrics: dict,
        evidence: list[str],
    ) -> None:
        """Flag suspicious ratio patterns from Yahoo financial metrics."""
        flags: list[str] = []

        # Debt/equity spike
        dte = metrics.get("debt_to_equity")
        if dte is not None and dte > 2.0:
            flags.append(f"High debt-to-equity ratio ({dte:.2f}x)")

        # Current ratio below 1 (liquidity stress)
        cr = metrics.get("current_ratio")
        if cr is not None and cr < 1.0:
            flags.append(f"Current ratio below 1.0 ({cr:.2f}x) — potential liquidity stress")

        # Negative operating cash flow with positive net income (earnings quality)
        opcf = metrics.get("operating_cashflow")
        profit_margin = metrics.get("profit_margins")
        if opcf is not None and opcf < 0 and profit_margin is not None and profit_margin > 0:
            flags.append(
                "Negative operating cash flow despite positive profit margin — "
                "potential earnings quality concern"
            )

        # Quick ratio stress
        qr = metrics.get("quick_ratio")
        if qr is not None and qr < 0.5:
            flags.append(f"Quick ratio critically low ({qr:.2f}x)")

        if flags:
            out.findings.append(
                Finding(
                    agent="accounting",
                    kind="risk",
                    headline=f"Financial ratio warnings ({len(flags)} flag{'s' if len(flags) != 1 else ''})",
                    detail=" | ".join(flags) + ".",
                    confidence="MEDIUM",
                    evidence=evidence,
                    metrics={
                        "flags": flags,
                        "debt_to_equity": dte,
                        "current_ratio": cr,
                        "quick_ratio": qr,
                    },
                )
            )
