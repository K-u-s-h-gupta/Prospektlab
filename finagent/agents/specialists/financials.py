"""FinancialsAgent — interprets SEC concept metrics + historical series.

Inputs: bundle.sec (metrics + history) from the shared enrichment.
Output: structured findings — e.g. "Revenue grew at 30% CAGR over 5y",
"Net margin compressed by 400bps YoY", "Operating cash flow positive".
"""

from __future__ import annotations

from finagent.accuracy_validator import Claim
from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext


def _cagr(values: list[float]) -> float | None:
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return None
    n = len(values) - 1
    try:
        return (values[-1] / values[0]) ** (1.0 / n) - 1
    except (ZeroDivisionError, ValueError):
        return None


def _pct_change(a: float, b: float) -> float | None:
    if a == 0 or a is None or b is None:
        return None
    return (b - a) / abs(a)


class FinancialsAgent(BaseSubAgent):
    name = "financials"
    display = "Financial Health"
    priority = 10
    dependencies = ()

    def precondition(self, ctx: SubAgentContext):
        return (ctx.bundle and ctx.bundle.sec is not None), "no SEC enrichment"

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        sec = ctx.bundle.sec
        out = AgentTaskResult(agent_name=self.name)
        metrics = sec.metrics or {}
        hist = sec.history or {}

        # Latest-period snapshot finding
        revenue = metrics.get("revenue")
        ni = metrics.get("net_income")
        if revenue and ni:
            f = Finding(
                agent=self.name,
                kind="financial",
                headline=f"FY snapshot: {revenue.display_value()} revenue, {ni.display_value()} net income",
                detail=(
                    f"From {revenue.form} (period {revenue.end}): revenue {revenue.display_value()}, "
                    f"net income {ni.display_value()}."
                ),
                confidence="HIGH",
                evidence=[f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sec.cik}"],
                metrics={
                    "revenue_value": revenue.value,
                    "revenue_unit": revenue.unit,
                    "net_income_value": ni.value,
                    "form": revenue.form,
                    "period_end": revenue.end,
                },
            )
            out.findings.append(f)
            out.claims.append(
                Claim(
                    text=f"{sec.name} reported revenue of {revenue.display_value()} per {revenue.form} ({revenue.end}).",
                    is_material=True,
                )
            )

        # Margin finding
        op_inc = metrics.get("operating_income")
        if revenue and op_inc and revenue.value:
            op_margin = op_inc.value / revenue.value
            if 0 <= op_margin <= 1:
                out.findings.append(
                    Finding(
                        agent=self.name,
                        kind="financial",
                        headline=f"Operating margin: {op_margin * 100:.1f}%",
                        detail=(
                            f"Computed from {op_inc.display_value()} operating income on "
                            f"{revenue.display_value()} revenue ({revenue.end})."
                        ),
                        confidence="HIGH" if op_margin > 0.15 else "MEDIUM",
                        evidence=[f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sec.cik}"],
                        metrics={"operating_margin": op_margin},
                    )
                )

        # CAGR finding from multi-year history
        for key in ("revenue", "net_income"):
            ts = hist.get(key)
            if not ts or len(ts.annual or []) < 3:
                continue
            sorted_pts = sorted(ts.annual, key=lambda p: p.end)
            values = [p.value for p in sorted_pts if p.value is not None]
            cagr = _cagr(values)
            if cagr is None:
                continue
            yrs = len(values) - 1
            yoy = _pct_change(values[-2], values[-1]) if len(values) >= 2 else None
            conf = "HIGH" if yrs >= 4 else "MEDIUM"
            headline = f"{ts.label} {yrs}-yr CAGR: {cagr * 100:+.1f}%"
            detail = (
                f"From {yrs + 1} annual data points ending {sorted_pts[-1].end}. "
                + (f"Latest YoY: {yoy * 100:+.1f}%." if yoy is not None else "")
            )
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="financial",
                    headline=headline,
                    detail=detail,
                    confidence=conf,
                    evidence=[f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sec.cik}"],
                    metrics={"cagr": cagr, "yoy": yoy, "years": yrs + 1, "concept": ts.concept},
                )
            )

        # Cash position / debt commentary
        cash = metrics.get("cash_and_equivalents")
        long_debt = metrics.get("long_term_debt")
        if cash and long_debt:
            net = cash.value - long_debt.value
            if net > 0:
                headline = f"Net cash position: cash exceeds long-term debt"
                detail = f"Cash {cash.display_value()} vs long-term debt {long_debt.display_value()} — net surplus."
                conf = "HIGH"
            else:
                headline = f"Net debt position: long-term debt exceeds cash"
                detail = f"Cash {cash.display_value()} vs long-term debt {long_debt.display_value()} — net liability."
                conf = "MEDIUM"
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="financial",
                    headline=headline,
                    detail=detail,
                    confidence=conf,
                    evidence=[f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sec.cik}"],
                    metrics={"net_cash": net, "cash": cash.value, "long_term_debt": long_debt.value},
                )
            )

        if not out.findings:
            out.status = "partial"
        return out
