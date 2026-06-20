"""TechnicalAgent — Yahoo price series → simple technical readouts.

Computes: 52-week position, distance from MA20/MA50 (where data
allows), volatility band, recent drawdown. Pure-math; no LLM calls.
"""

from __future__ import annotations

import statistics

from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext


def _ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _max_drawdown(values: list[float]) -> float | None:
    if len(values) < 5:
        return None
    peak = values[0]
    mdd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak else 0
        if dd < mdd:
            mdd = dd
    return mdd


class TechnicalAgent(BaseSubAgent):
    name = "technical"
    display = "Price & Technicals"
    priority = 30

    def precondition(self, ctx: SubAgentContext):
        y = ctx.bundle.yahoo if ctx.bundle else None
        if not y:
            return False, "no Yahoo quote"
        return True, ""

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        y = ctx.bundle.yahoo
        ticker = getattr(y, "symbol", None) or getattr(y, "ticker", None) or ctx.target
        currency = getattr(y, "currency", None) or ""
        closes = getattr(y, "series_closes", None) or []
        low_52w = getattr(y, "low_52w", None)
        if low_52w is None:
            low_52w = getattr(y, "fifty_two_week_low", None)
        high_52w = getattr(y, "high_52w", None)
        if high_52w is None:
            high_52w = getattr(y, "fifty_two_week_high", None)

        if y.price is not None and low_52w is not None and high_52w is not None:
            span = high_52w - low_52w
            pos = (y.price - low_52w) / span if span > 0 else None
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="technical",
                    headline=f"At {pos * 100:.0f}% of 52-week range" if pos is not None else "52-week range available",
                    detail=(
                        f"Current {currency} {y.price:,.2f} sits between 52w low {currency} {low_52w:,.2f} "
                        f"and 52w high {currency} {high_52w:,.2f}."
                    ),
                    confidence="HIGH",
                    evidence=[f"https://finance.yahoo.com/quote/{ticker}"],
                    metrics={"position_in_52w": pos, "price": y.price, "low_52w": low_52w, "high_52w": high_52w},
                )
            )

        if len(closes) >= 20:
            ma20 = _ma(closes, 20)
            ma50 = _ma(closes, 50)
            last = closes[-1]
            relmsg = []
            if ma20:
                relmsg.append(f"{'above' if last >= ma20 else 'below'} MA20 by {((last - ma20) / ma20) * 100:+.1f}%")
            if ma50:
                relmsg.append(f"{'above' if last >= ma50 else 'below'} MA50 by {((last - ma50) / ma50) * 100:+.1f}%")
            vol = None
            if len(closes) >= 10:
                vol = statistics.stdev(closes[-20:]) / statistics.mean(closes[-20:])
            mdd = _max_drawdown(closes)
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="technical",
                    headline="Trend posture: " + ("; ".join(relmsg) if relmsg else "MAs unavailable"),
                    detail=(
                        f"Series of {len(closes)} closes. "
                        + (f"Realised 20d vol ≈ {vol * 100:.1f}% of mean. " if vol is not None else "")
                        + (f"Max drawdown in window: {mdd * 100:.1f}%." if mdd is not None else "")
                    ),
                    confidence="MEDIUM",
                    evidence=[f"https://finance.yahoo.com/quote/{ticker}"],
                    metrics={"ma20": ma20, "ma50": ma50, "last": last, "vol_20d": vol, "max_drawdown": mdd},
                )
            )

        return out
