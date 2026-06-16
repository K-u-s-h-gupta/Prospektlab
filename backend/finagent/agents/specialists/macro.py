"""MacroAgent — sector context + macro tailwinds/headwinds.

Uses the industry classification from company enrichment as a sector seed
and runs focused queries about sector tailwinds, headwinds, and policy
exposures.
"""

from __future__ import annotations

from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext, search_and_dedupe


class MacroAgent(BaseSubAgent):
    name = "macro"
    display = "Macro & Sector Context"
    priority = 50

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        sec = ctx.bundle.sec if ctx.bundle else None
        sector = (sec.sic_description if sec and sec.sic_description else "").strip()
        if not sector:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="macro",
                    headline="Sector classification unavailable",
                    detail="Sector industry description was not populated for this issuer.",
                    confidence="LOW",
                )
            )
            return out

        queries = [
            f"{sector} industry outlook 2026 tailwinds headwinds",
            f"{sector} regulatory environment policy risk",
            f"{ctx.canonical_label} exposure to interest rates fx commodity",
        ]
        docs, used = await search_and_dedupe(ctx, queries)
        out.new_docs = docs
        out.queries_used = used

        # If we managed to pull at least one doc, surface a structured
        # finding pointing to it. The synthesis layer will incorporate
        # the actual text downstream.
        if docs:
            top = docs[0]
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="macro",
                    headline=f"Sector backdrop sourced for '{sector}'",
                    detail=(
                        f"Pulled {len(docs)} doc(s) covering sector outlook, regulatory environment, "
                        f"and macro factor sensitivities. Top doc: '{(top.title or '')[:120]}'."
                    ),
                    confidence="MEDIUM",
                    evidence=[d.final_url or d.url for d in docs[:3]],
                    metrics={"sector": sector, "docs": len(docs)},
                )
            )
        else:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="macro",
                    headline=f"No macro coverage retrieved for '{sector}'",
                    detail="Macro search returned no fresh docs above the dedup floor.",
                    confidence="LOW",
                    metrics={"sector": sector, "docs": 0},
                )
            )
        return out
