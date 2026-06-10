"""GovernanceAgent — insider activity + board / leadership signals.

Note: Promoter transactions and exchange disclosure details are scanned via web search,
prioritizing official NSE/BSE corporate announcements and regulatory filing portals.
"""

from __future__ import annotations

from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext, search_and_dedupe


def _needs_fresh_signals(objective: str) -> bool:
    text = (objective or "").lower()
    return any(token in text for token in ("latest", "recent", "today", "news", "announcement", "update"))


class GovernanceAgent(BaseSubAgent):
    name = "governance"
    display = "Governance & Insiders"
    priority = 60

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        ikg_ctx = ctx.agent_context(self.name)
        pledge = ikg_ctx.get("pledge_summary") or {}
        directors = ikg_ctx.get("director_history") or []
        enforcement = ikg_ctx.get("enforcement_actions") or []

        if directors:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline=f"IKG board graph exposes {len(directors)} director relationship(s)",
                    detail=(
                        "Use this as a high-signal governance baseline before layering in fresh exchange disclosures. "
                        f"Recent graph freshness: {ctx.ikg_bundle.as_of_date if ctx.ikg_bundle else 'unknown'}."
                    ),
                    confidence="HIGH" if ctx.ikg_bundle and ctx.ikg_bundle.coverage.get("governance") == "complete" else "MEDIUM",
                    evidence=(ctx.ikg_bundle.source_refs[:3] if ctx.ikg_bundle else []),
                    metrics={"ikg_director_count": len(directors)},
                )
            )

        pledge_pct = pledge.get("total_pledge_pct")
        if pledge_pct is not None:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline=f"Promoter pledge baseline: {float(pledge_pct):.2f}%",
                    detail=(
                        f"IKG ownership summary shows promoter holding {float(pledge.get('total_promoter_holding_pct') or 0.0):.2f}% "
                        f"with pledge flag {pledge.get('pledge_flag') or 'unknown'}."
                    ),
                    confidence="HIGH",
                    evidence=(ctx.ikg_bundle.source_refs[:3] if ctx.ikg_bundle else []),
                    metrics={
                        "promoter_holding_pct": pledge.get("total_promoter_holding_pct"),
                        "pledge_pct": pledge_pct,
                    },
                )
            )

        if enforcement:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline=f"Governance graph links {len(enforcement)} enforcement action(s)",
                    detail="Regulatory history exists in the IKG and should be reconciled with any recent disclosure scan.",
                    confidence="HIGH",
                    evidence=(ctx.ikg_bundle.source_refs[:3] if ctx.ikg_bundle else []),
                    metrics={"enforcement_actions": len(enforcement)},
                )
            )

        if (
            ctx.ikg_bundle
            and ctx.ikg_bundle.coverage.get("governance") == "complete"
            and not _needs_fresh_signals(ctx.objective)
        ):
            out.status = "ok" if out.findings else "partial"
            return out

        queries = [
            f"{ctx.canonical_label} promoter shareholding insider trading NSE BSE",
            f"{ctx.canonical_label} CEO CFO board change resignation appointment",
            f"{ctx.canonical_label} corporate governance report exchange disclosure NSE BSE",
        ]
        docs, used = await search_and_dedupe(ctx, queries)
        out.new_docs = docs
        out.queries_used = used

        exchange_hits = [d for d in docs if any(domain in (d.final_url or d.url or "") for domain in ["nseindia.com", "bseindia.com"])]
        if exchange_hits:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline=f"Exchange disclosure governance source(s) located ({len(exchange_hits)} primary)",
                    detail=(
                        f"Primary exchange (NSE/BSE) sources for insider/governance lookup: "
                        + "; ".join((d.title or d.final_url or d.url)[:80] for d in exchange_hits[:3])
                    ),
                    confidence="HIGH",
                    evidence=[d.final_url or d.url for d in exchange_hits[:3]],
                )
            )
        elif docs:
            top = docs[0]
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline="Governance secondary coverage retrieved",
                    detail=(
                        f"{len(docs)} doc(s) on insider activity, executive moves, or "
                        f"compensation. Top: '{(top.title or '')[:120]}'."
                    ),
                    confidence="MEDIUM",
                    evidence=[d.final_url or d.url for d in docs[:3]],
                )
            )
        else:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline="No governance signals retrieved this run",
                    detail="Insider-activity and executive-change queries returned no fresh docs.",
                    confidence="LOW",
                )
            )
        return out
