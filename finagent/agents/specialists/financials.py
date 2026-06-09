"""FinancialsAgent — interprets company financial metrics + historical series.

Inputs: bundle.sec (metrics + history) from the shared enrichment.
Output: structured findings — e.g. "Revenue grew at 30% CAGR over 5y",
"Net margin compressed by 400bps YoY", "Operating cash flow positive".
"""

from __future__ import annotations

from finagent.accuracy_validator import Claim
from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext
from finagent.tools.data import format_inr


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


def _fmt_local_money(value: float | None, currency: str | None, fx_rate: float | None) -> str:
    if value is None:
        return "n/a"
    currency = (currency or "USD").upper()
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    if currency == "USD" and fx_rate:
        return f"{sign}${abs_value:,.2f} ({format_inr(abs_value, fx_rate)})"
    if currency == "INR":
        return f"{sign}{format_inr(abs_value, 1.0)}"
    if abs_value >= 1e9:
        compact = f"{abs_value/1e9:,.2f}B"
    elif abs_value >= 1e6:
        compact = f"{abs_value/1e6:,.2f}M"
    elif abs_value >= 1e3:
        compact = f"{abs_value/1e3:,.2f}K"
    else:
        compact = f"{abs_value:,.2f}"
    return f"{sign}{currency} {compact}"


def _append_yahoo_metric_findings(ctx: SubAgentContext, out: AgentTaskResult) -> None:
    yahoo = ctx.bundle.yahoo if ctx.bundle else None
    if not yahoo:
        return
    fx_rate = ctx.bundle.fx.rate if ctx.bundle and ctx.bundle.fx else None
    metrics = dict(yahoo.financial_metrics or {})
    if not metrics and not yahoo.annual_revenue and not yahoo.annual_net_income:
        return

    currency = yahoo.currency
    evidence = [yahoo.source_url]
    headline_parts: list[str] = []
    detail_parts: list[str] = []
    for label, key in (
        ("Revenue", "total_revenue"),
        ("EBITDA", "ebitda"),
        ("Free cash flow", "free_cashflow"),
        ("Cash", "total_cash"),
        ("Debt", "total_debt"),
    ):
        value = metrics.get(key)
        if value is None:
            continue
        formatted = _fmt_local_money(value, currency, fx_rate)
        headline_parts.append(f"{label} {formatted}")
        detail_parts.append(f"{label} is {formatted}")

    margin_bits: list[str] = []
    for label, key in (
        ("gross margin", "gross_margins"),
        ("operating margin", "operating_margins"),
        ("profit margin", "profit_margins"),
        ("ROE", "return_on_equity"),
        ("ROA", "return_on_assets"),
        ("revenue growth", "revenue_growth"),
        ("earnings growth", "earnings_growth"),
    ):
        value = metrics.get(key)
        if value is not None:
            margin_bits.append(f"{label} {value * 100:.1f}%")
    if metrics.get("debt_to_equity") is not None:
        margin_bits.append(f"debt/equity {metrics['debt_to_equity']:.2f}x")
    if metrics.get("current_ratio") is not None:
        margin_bits.append(f"current ratio {metrics['current_ratio']:.2f}x")
    if metrics.get("trailing_pe") is not None:
        margin_bits.append(f"trailing P/E {metrics['trailing_pe']:.2f}x")
    if metrics.get("forward_pe") is not None:
        margin_bits.append(f"forward P/E {metrics['forward_pe']:.2f}x")
    if metrics.get("price_to_book") is not None:
        margin_bits.append(f"P/B {metrics['price_to_book']:.2f}x")
    if margin_bits:
        detail_parts.append("Key ratios include " + ", ".join(margin_bits) + ".")

    if headline_parts or detail_parts:
        out.findings.append(
            Finding(
                agent="financials",
                kind="financial",
                headline=f"Yahoo fundamentals for {yahoo.ticker}",
                detail=". ".join(detail_parts) + ".",
                confidence="MEDIUM" if margin_bits else "LOW",
                evidence=evidence,
                metrics=metrics,
            )
        )

    if yahoo.annual_revenue and len(yahoo.annual_revenue) >= 2:
        rev_values = yahoo.annual_revenue
        rev_cagr = _cagr(rev_values)
        rev_yoy = _pct_change(rev_values[-2], rev_values[-1]) if len(rev_values) >= 2 else None
        first_date = yahoo.annual_revenue_dates[0] if yahoo.annual_revenue_dates else "start"
        last_date = yahoo.annual_revenue_dates[-1] if yahoo.annual_revenue_dates else "latest"
        out.findings.append(
            Finding(
                agent="financials",
                kind="financial",
                headline=f"Revenue history spans {len(rev_values)} annual points",
                detail=(
                    f"Revenue moved from {_fmt_local_money(rev_values[0], currency, fx_rate)} in {first_date} "
                    f"to {_fmt_local_money(rev_values[-1], currency, fx_rate)} in {last_date}"
                    + (f", a {rev_cagr * 100:+.1f}% CAGR" if rev_cagr is not None else "")
                    + (f", with latest YoY {rev_yoy * 100:+.1f}%." if rev_yoy is not None else ".")
                ),
                confidence="MEDIUM",
                evidence=evidence,
                metrics={"revenue_cagr": rev_cagr, "revenue_yoy": rev_yoy, "years": len(rev_values)},
            )
        )

    if yahoo.annual_net_income and len(yahoo.annual_net_income) >= 2:
        ni_values = yahoo.annual_net_income
        ni_cagr = _cagr(ni_values) if ni_values[0] > 0 and ni_values[-1] > 0 else None
        ni_yoy = _pct_change(ni_values[-2], ni_values[-1]) if len(ni_values) >= 2 else None
        first_date = yahoo.annual_net_income_dates[0] if yahoo.annual_net_income_dates else "start"
        last_date = yahoo.annual_net_income_dates[-1] if yahoo.annual_net_income_dates else "latest"
        out.findings.append(
            Finding(
                agent="financials",
                kind="financial",
                headline=f"Net income history spans {len(ni_values)} annual points",
                detail=(
                    f"Net income moved from {_fmt_local_money(ni_values[0], currency, fx_rate)} in {first_date} "
                    f"to {_fmt_local_money(ni_values[-1], currency, fx_rate)} in {last_date}"
                    + (f", a {ni_cagr * 100:+.1f}% CAGR" if ni_cagr is not None else "")
                    + (f", with latest YoY {ni_yoy * 100:+.1f}%." if ni_yoy is not None else ".")
                ),
                confidence="MEDIUM",
                evidence=evidence,
                metrics={"net_income_cagr": ni_cagr, "net_income_yoy": ni_yoy, "years": len(ni_values)},
            )
        )

    if metrics:
        claims: list[str] = []
        if metrics.get("total_revenue") is not None:
            claims.append(f"Yahoo Finance reports total revenue of {_fmt_local_money(metrics['total_revenue'], currency, fx_rate)}.")
        if metrics.get("profit_margins") is not None:
            claims.append(f"Yahoo Finance reports a profit margin of {metrics['profit_margins'] * 100:.1f}%.")
        if metrics.get("return_on_equity") is not None:
            claims.append(f"Yahoo Finance reports ROE of {metrics['return_on_equity'] * 100:.1f}%.")
        for text in claims[:3]:
            out.claims.append(Claim(text=text, is_material=True))


def _append_ikg_financial_findings(ctx: SubAgentContext, out: AgentTaskResult) -> None:
    ikg_ctx = ctx.agent_context("financials")
    fin = ikg_ctx or {}
    statement = fin.get("income_statement") or {}
    ratios = fin.get("ratios") or {}
    if not statement and not ratios:
        company_financials = (ctx.ikg_bundle.financials.get("company_financials") if ctx.ikg_bundle else {}) or {}
        if not company_financials:
            return
        detail_parts: list[str] = []
        for label, key in (
            ("Revenue", "total_revenue"),
            ("Net income", "net_income"),
            ("EBITDA", "ebitda"),
            ("Cash", "total_cash"),
            ("Debt", "total_debt"),
        ):
            value = company_financials.get(key)
            if value is not None:
                detail_parts.append(f"{label} {value}")
        if detail_parts:
            out.findings.append(
                Finding(
                    agent="financials",
                    kind="financial",
                    headline="IKG financial snapshot available",
                    detail=". ".join(detail_parts) + ".",
                    confidence="MEDIUM",
                    evidence=(ctx.ikg_bundle.source_refs[:3] if ctx.ikg_bundle else []),
                    metrics={k: company_financials.get(k) for k in ("total_revenue", "net_income", "ebitda", "total_cash", "total_debt")},
                )
            )
        return

    details: list[str] = []
    for label, key in (
        ("Revenue", "revenue"),
        ("Net income", "net_income"),
        ("Operating income", "operating_income"),
    ):
        value = statement.get(key)
        if value is not None:
            details.append(f"{label} {value}")
    if ratios:
        ratio_bits = []
        for label, key in (
            ("ROE", "roe"),
            ("ROCE", "roce"),
            ("P/E", "pe_ratio"),
            ("P/B", "pb_ratio"),
        ):
            value = ratios.get(key)
            if value is not None:
                ratio_bits.append(f"{label} {value}")
        if ratio_bits:
            details.append("Ratios " + ", ".join(ratio_bits))
    if details:
        out.findings.append(
            Finding(
                agent="financials",
                kind="financial",
                headline="IKG financial context injected",
                detail=". ".join(details) + ".",
                confidence="MEDIUM",
                evidence=(ctx.ikg_bundle.source_refs[:3] if ctx.ikg_bundle else []),
                metrics={"source": "ikg_bundle"},
            )
        )


class FinancialsAgent(BaseSubAgent):
    name = "financials"
    display = "Financial Health"
    priority = 10
    dependencies = ()

    def precondition(self, ctx: SubAgentContext):
        has_bundle = ctx.bundle and (ctx.bundle.sec is not None or ctx.bundle.yahoo is not None)
        has_ikg = bool(ctx.ikg_bundle and ctx.ikg_bundle.coverage.get("financials") != "missing")
        return bool(has_bundle or has_ikg or ctx.seed_docs), "no financial enrichment"

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        sec = ctx.bundle.sec if ctx.bundle else None
        yahoo = ctx.bundle.yahoo if ctx.bundle else None
        out = AgentTaskResult(agent_name=self.name)
        metrics = sec.metrics or {} if sec else {}
        hist = sec.history or {} if sec else {}

        if ctx.ikg_bundle:
            _append_ikg_financial_findings(ctx, out)

        if not sec and yahoo:
            detail = f"{yahoo.currency or ''} {yahoo.price:,.2f}" if yahoo.price is not None else "quote unavailable"
            if yahoo.change_pct is not None:
                detail += f", {yahoo.change_pct:+.2f}% vs previous close"
            if yahoo.market_cap:
                detail += f", market cap {yahoo.market_cap:,.0f}"
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="financial",
                    headline=f"Market snapshot for {yahoo.ticker}",
                    detail=detail,
                    confidence="MEDIUM",
                    evidence=[yahoo.source_url],
                    metrics={
                        "price": yahoo.price,
                        "change_pct": yahoo.change_pct,
                        "market_cap": yahoo.market_cap,
                        "exchange": yahoo.exchange,
                    },
                )
            )
            _append_yahoo_metric_findings(ctx, out)

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
                evidence=[sec.source_url] if (sec and getattr(sec, "source_url", None)) else [],
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
                        evidence=[sec.source_url] if (sec and getattr(sec, "source_url", None)) else [],
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
                    evidence=[sec.source_url] if (sec and getattr(sec, "source_url", None)) else [],
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
                    evidence=[sec.source_url] if (sec and getattr(sec, "source_url", None)) else [],
                    metrics={"net_cash": net, "cash": cash.value, "long_term_debt": long_debt.value},
                )
            )

        if not out.findings:
            out.status = "partial"
        return out
