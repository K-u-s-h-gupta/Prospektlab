"""GovernanceAgent — insider activity + board / leadership signals.

Note: SEC Form 4 detail isn't pulled in the current enrichment bundle,
so this agent's primary mode is a web-search-driven scan with a high
priority on the SEC Insider Transactions XBRL viewer when accessible.
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
            f"{ctx.canonical_label} insider trading form 4 site:sec.gov",
            f"{ctx.canonical_label} CEO CFO board change",
            f"{ctx.canonical_label} executive compensation proxy DEF 14A",
        ]
        docs, used = await search_and_dedupe(ctx, queries)
        out.new_docs = docs
        out.queries_used = used

        sec_hits = [d for d in docs if "sec.gov" in (d.final_url or d.url or "")]
        if sec_hits:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline=f"SEC governance source(s) located ({len(sec_hits)} primary)",
                    detail=(
                        f"Primary SEC sources for insider/governance lookup: "
                        + "; ".join((d.title or d.final_url or d.url)[:80] for d in sec_hits[:3])
                    ),
                    confidence="HIGH",
                    evidence=[d.final_url or d.url for d in sec_hits[:3]],
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
