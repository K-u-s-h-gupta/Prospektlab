"""GovernanceAgent — insider activity + board / leadership signals.

Note: Promoter transactions and exchange disclosure details are scanned via web search,
prioritizing official NSE/BSE corporate announcements and regulatory filing portals.
"""

from __future__ import annotations

from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext, search_and_dedupe


class GovernanceAgent(BaseSubAgent):
    name = "governance"
    display = "Governance & Insiders"
    priority = 60

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
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
