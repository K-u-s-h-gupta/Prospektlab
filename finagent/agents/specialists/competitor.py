"""CompetitorAgent — discovers peers and surfaces comparative claims.

Strategy:
1. Use SIC description from SEC enrichment to bias the query toward
   sector-relevant peers (semiconductors, software, etc.).
2. Run 3 targeted searches: "top competitors of X", "X vs Y", "X
   alternatives". Extract candidate competitor names from titles +
   excerpts using a light regex.
3. Promote any name that shows up in ≥2 distinct docs into a finding.
"""

from __future__ import annotations

import re
from collections import Counter

from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext, search_and_dedupe


# Static sector hints for well-known Indian companies so that peer queries
# are meaningful even when the live india_snap.industry field is blank.
_STATIC_SECTOR_HINTS: dict[str, str] = {
    "tcs": "information technology services India",
    "tata consultancy services": "information technology services India",
    "infosys": "information technology services India",
    "wipro": "information technology services India",
    "hcltech": "information technology services India",
    "techm": "information technology services India",
    "ltimindtree": "information technology services India",
    "mphasis": "information technology services India",
    "reliance": "oil gas telecom conglomerate India",
    "hdfcbank": "private sector bank India",
    "icicibank": "private sector bank India",
    "kotakbank": "private sector bank India",
    "axisbank": "private sector bank India",
    "sbin": "public sector bank India",
    "bajfinance": "NBFC consumer finance India",
    "bajajfinsv": "financial services NBFC India",
    "maruti": "automobile passenger cars India",
    "tatamotors": "automobile commercial vehicles India",
    "sunpharma": "pharmaceuticals India",
    "drreddy": "pharmaceuticals generics India",
    "bhartiartl": "telecom mobile broadband India",
    "ongc": "oil gas upstream India",
    "ntpc": "power generation electricity India",
    "adanient": "infrastructure ports energy India",
    "ltfoods": "FMCG food products India",
    "itc": "FMCG cigarettes hotels India",
    "hindunilvr": "FMCG consumer goods India",
    "nestleind": "FMCG packaged foods India",
    "asianpaint": "paints decorative India",
    "titan": "jewellery watches retail India",
    "tatasteel": "steel metals India",
    "jswsteel": "steel metals India",
    "ultracemco": "cement construction India",
    "grasim": "cement chemicals India",
}


# Words to never count as competitors
_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "their", "they", "from",
    "today", "company", "companies", "stock", "stocks", "market", "shares",
    "report", "year", "yearly", "quarter", "growth", "industry", "sector",
    "tech", "global", "world", "best", "top", "vs", "alternative", "alternatives",
    "competitor", "competitors", "rival", "rivals", "peer", "peers", "amid",
    "according", "after", "before", "during", "while", "than", "between",
}
_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z][a-zA-Z\.\-&]{1,18}(?:\s+[A-Z][a-zA-Z][a-zA-Z\.\-&]{1,18}){0,2})\b")
_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")


def _candidate_names(text: str, target: str) -> list[str]:
    target_l = target.lower()
    names = []
    for m in _NAME_RE.findall(text or ""):
        n = m.strip()
        nl = n.lower()
        if nl == target_l or target_l in nl or nl in target_l:
            continue
        toks = [t for t in re.split(r"\s+", nl) if t]
        if all(t in _STOPWORDS for t in toks):
            continue
        if len(n) < 3 or len(n) > 60:
            continue
        names.append(n)
    return names


class CompetitorAgent(BaseSubAgent):
    name = "competitor"
    display = "Competitive Landscape"
    priority = 40

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        sec = ctx.bundle.sec if ctx.bundle else None
        # Prefer live industry from the India snapshot; fall back to the static
        # map so peer queries always have meaningful sector context.
        sector_hint = (sec.sic_description if sec and sec.sic_description else "").strip()
        if not sector_hint:
            label_key = (ctx.canonical_label or "").lower().strip()
            sector_hint = _STATIC_SECTOR_HINTS.get(label_key, "")

        queries = [
            f"top competitors of {ctx.canonical_label} {sector_hint}".strip(),
            f"{ctx.canonical_label} vs",
            f"alternatives to {ctx.canonical_label} {sector_hint}".strip(),
        ]
        docs, used = await search_and_dedupe(ctx, queries)
        out.new_docs = docs
        out.queries_used = used

        # Mine candidate names from the original seed docs + the new ones
        source_docs = list(ctx.seed_docs) + docs
        counter: Counter[str] = Counter()
        evidence_by_name: dict[str, list[str]] = {}
        for d in source_docs:
            text = (d.title or "") + " . " + (d.excerpt or "")
            for n in _candidate_names(text, ctx.canonical_label):
                counter[n] += 1
                evidence_by_name.setdefault(n, []).append(d.final_url or d.url)

        # Promote names mentioned in ≥2 distinct doc sources
        promoted = [n for n, c in counter.most_common(15) if c >= 2]
        if promoted:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="competitor",
                    headline=f"Candidate peers identified: {', '.join(promoted[:6])}",
                    detail=(
                        f"Found {len(promoted)} repeated-mention candidates across "
                        f"{len(source_docs)} docs after running 3 peer-discovery queries."
                    ),
                    confidence="MEDIUM",
                    evidence=list({u for n in promoted[:6] for u in evidence_by_name.get(n, [])[:2]})[:6],
                    metrics={"candidates": promoted, "mention_counts": dict(counter.most_common(10))},
                )
            )
        else:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="competitor",
                    headline="No clear peer set surfaced",
                    detail=(
                        "Peer-discovery queries did not produce a consistent set of named "
                        "rivals across multiple sources. Manual sector mapping may be needed."
                    ),
                    confidence="LOW",
                    evidence=[d.final_url or d.url for d in docs[:3]],
                )
            )

        return out
