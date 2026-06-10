"""RiskAgent — Item 1A digest + active litigation / regulatory scan."""

from __future__ import annotations

import re

from finagent.accuracy_validator import Claim
from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext, search_and_dedupe


_RISK_PATTERNS = (
    (re.compile(r"\bclass[- ]action\b|\blawsuit\b|\bcomplaint filed\b", re.I), "Litigation exposure"),
    (re.compile(r"\bsubpoena\b|\binvestigation\b|\bprobe\b|\bSEBI\b|\bexchange surveillance\b|\bregulatory action\b", re.I), "Regulatory inquiry"),
    (re.compile(r"\brecall\b|\bdefect\b|\bsafety issue\b", re.I), "Product safety"),
    (re.compile(r"\bbreach\b|\bhack\b|\bdata leak\b|\bransomware\b", re.I), "Cyber incident"),
    (re.compile(r"\bgoing concern\b|\baccount(ing|s) restate\b|\bmaterial weakness\b", re.I), "Accounting concern"),
)


def _needs_fresh_signals(objective: str) -> bool:
    text = (objective or "").lower()
    return any(token in text for token in ("latest", "recent", "today", "news", "announcement", "update"))


class RiskAgent(BaseSubAgent):
    name = "risk"
    display = "Risk & Litigation"
    priority = 20

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        filing = ctx.bundle.filing if ctx.bundle else None
        ikg_ctx = ctx.agent_context(self.name)
        pledge_pct = ikg_ctx.get("pledge_pct")
        risk_flags = ikg_ctx.get("risk_flags") or []
        enforcement = []
        if ctx.ikg_bundle:
            enforcement = ctx.ikg_bundle.risk.get("enforcement_actions") or []

        # Risk Factors / management discussion digest from exchange filings.
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
                    text=f"Risk factors section is materially populated ({len(rf)} chars).",
                    is_material=True,
                )
            )

        if pledge_pct is not None:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="risk",
                    headline=f"IKG pledge-risk baseline: {float(pledge_pct):.2f}%",
                    detail="Promoter pledge is treated as a structural balance-sheet and governance risk until cross-checked against the latest shareholding pattern.",
                    confidence="HIGH" if float(pledge_pct) >= 25 else "MEDIUM",
                    evidence=(ctx.ikg_bundle.source_refs[:3] if ctx.ikg_bundle else []),
                    metrics={"pledge_pct": pledge_pct, "risk_flags": risk_flags},
                )
            )
        if enforcement:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="risk",
                    headline=f"IKG records {len(enforcement)} enforcement-linked event(s)",
                    detail="These graph-linked actions should be validated against official SEBI / exchange documents before being treated as decisive.",
                    confidence="HIGH",
                    evidence=(ctx.ikg_bundle.source_refs[:4] if ctx.ikg_bundle else []),
                    metrics={"enforcement_count": len(enforcement)},
                )
            )

        if (
            ctx.ikg_bundle
            and ctx.ikg_bundle.coverage.get("risk") != "missing"
            and ctx.ikg_bundle.coverage.get("ownership") != "missing"
            and not _needs_fresh_signals(ctx.objective)
        ):
            return out

        # Search for active litigation / regulatory news
        queries = [
            f"{ctx.canonical_label} lawsuit settlement investigation",
            f"{ctx.canonical_label} SEBI exchange surveillance penalty regulatory action",
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
