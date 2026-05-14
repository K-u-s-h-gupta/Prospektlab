"""RiskAgent — Item 1A digest + active litigation / regulatory scan."""

from __future__ import annotations

import re

from finagent.accuracy_validator import Claim
from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext, search_and_dedupe


_RISK_PATTERNS = (
    (re.compile(r"\bclass[- ]action\b|\blawsuit\b|\bcomplaint filed\b", re.I), "Litigation exposure"),
    (re.compile(r"\bsubpoena\b|\binvestigation\b|\bprobe\b|\bDOJ\b|\bSEC charged\b", re.I), "Regulatory inquiry"),
    (re.compile(r"\brecall\b|\bdefect\b|\bsafety issue\b", re.I), "Product safety"),
    (re.compile(r"\bbreach\b|\bhack\b|\bdata leak\b|\bransomware\b", re.I), "Cyber incident"),
    (re.compile(r"\bgoing concern\b|\baccount(ing|s) restate\b|\bmaterial weakness\b", re.I), "Accounting concern"),
)


class RiskAgent(BaseSubAgent):
    name = "risk"
    display = "Risk & Litigation"
    priority = 20

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        filing = ctx.bundle.filing if ctx.bundle else None

        # Risk Factors digest from the most recent 10-K
        if filing and getattr(filing, "risk_factors", None):
            rf = filing.risk_factors.strip()
            preview = rf[:520].rsplit(" ", 1)[0]
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="risk",
                    headline=f"Item 1A digest from {filing.form} filed {filing.filed_date}",
                    detail=preview + ("..." if len(rf) > 520 else ""),
                    confidence="HIGH",
                    evidence=[filing.source_url],
                    metrics={"chars": len(rf), "form": filing.form, "filed_date": filing.filed_date},
                )
            )
            out.claims.append(
                Claim(
                    text=f"10-K Item 1A (Risk Factors) is materially populated ({len(rf)} chars).",
                    is_material=True,
                )
            )

        # Search for active litigation / regulatory news
        queries = [
            f"{ctx.canonical_label} lawsuit settlement investigation",
            f"{ctx.canonical_label} SEC DOJ FTC charged",
        ]
        docs, used = await search_and_dedupe(ctx, queries)
        out.new_docs = docs
        out.queries_used = used

        hits: dict[str, list[str]] = {}
        for d in docs + list(ctx.seed_docs):
            text = (d.title or "") + " . " + (d.excerpt or "")
            for pat, label in _RISK_PATTERNS:
                if pat.search(text):
                    hits.setdefault(label, []).append(d.final_url or d.url)
        for label, urls in hits.items():
            conf = "MEDIUM" if len(urls) >= 2 else "LOW"
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="risk",
                    headline=f"{label} signal detected in {len(urls)} source(s)",
                    detail=(
                        f"Pattern '{label}' matched titles/excerpts in {len(urls)} doc(s). "
                        "Manual review of source pages recommended."
                    ),
                    confidence=conf,
                    evidence=urls[:4],
                    metrics={"pattern": label, "count": len(urls)},
                )
            )

        return out
