"""NewsAgent — fetches and classifies recent news coverage.

Reuses Google News RSS from the enrichment bundle, plus runs an extra
two targeted searches (earnings, analyst rating) to widen the catch.
Findings: noteworthy headlines bucketed by topic (earnings, analyst,
M&A, regulatory) with confidence scaled by outlet tier.
"""

from __future__ import annotations

import re

from finagent.accuracy_validator import Claim
from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext, search_and_dedupe


_TIER1_OUTLETS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "nytimes.com",
    "barrons.com",
    "investors.com",
    "cnbc.com",
    "marketwatch.com",
    "morningstar.com",
}
_TOPIC_KEYWORDS = {
    "earnings": ("earning", "revenue", "profit", "eps", "quarter", "fiscal"),
    "analyst": ("upgrade", "downgrade", "rating", "price target", "buy", "sell"),
    "M&A": ("acquisition", "acquire", "merger", "buyout", "ipo", "spinoff", "divest"),
    "regulatory": ("sec ", "doj", "ftc", "fda", "lawsuit", "settlement", "investigation", "subpoena", "fine"),
    "product": ("launch", "unveil", "announce", "release", "partnership"),
}


def _classify(title: str) -> str:
    t = title.lower()
    for topic, keys in _TOPIC_KEYWORDS.items():
        if any(k in t for k in keys):
            return topic
    return "general"


def _outlet_tier(source: str) -> str:
    s = (source or "").lower()
    for top in _TIER1_OUTLETS:
        if top in s:
            return "tier1"
    return "tier2"


class NewsAgent(BaseSubAgent):
    name = "news"
    display = "News & Catalysts"
    priority = 20

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        news = (ctx.bundle.news if ctx.bundle else None) or []

        # Bucket by topic, then promote the highest-tier headline per
        # bucket to a Finding.
        buckets: dict[str, list] = {}
        for n in news:
            topic = _classify(n.title or "")
            buckets.setdefault(topic, []).append(n)
        for topic, items in buckets.items():
            if topic == "general" and len(buckets) > 1:
                continue
            items.sort(key=lambda i: (_outlet_tier(i.source) != "tier1", i.published or ""), reverse=False)
            top = items[0]
            conf = "HIGH" if _outlet_tier(top.source) == "tier1" else "MEDIUM"
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="news",
                    headline=f"{topic.title()} news: {top.title[:120]}",
                    detail=f"{top.source} ({top.published}): {top.title}. {len(items)} similar headline(s) across this topic.",
                    confidence=conf,
                    evidence=[top.link],
                    metrics={"topic": topic, "outlet_tier": _outlet_tier(top.source), "cluster_size": len(items)},
                )
            )
            out.claims.append(Claim(text=top.title, is_material=topic in ("earnings", "M&A", "regulatory")))

        # Additional targeted searches to harden coverage
        queries = [
            f"{ctx.canonical_label} latest analyst rating target price",
            f"{ctx.canonical_label} earnings beat miss last quarter",
        ]
        new_docs, used = await search_and_dedupe(ctx, queries)
        out.new_docs.extend(new_docs)
        out.queries_used.extend(used)

        return out
