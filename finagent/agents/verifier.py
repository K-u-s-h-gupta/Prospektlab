"""Verifier agent — cross-checks findings before synthesis.

Runs **after** all specialist subagents complete. Responsibilities:

1. **Tier-1 enforcement** — every HIGH-confidence finding should have at
   least one SEC / IR / regulator source in `evidence`. Findings that
   fail this get demoted to MEDIUM and flagged.

2. **Cross-source corroboration** — finds claims that appear in
   multiple specialists' outputs and bumps their confidence. Finds
   claims that only appear once and flags them for the user.

3. **Numeric sanity** — re-uses `detect_conflicts` on the aggregated
   doc pool, surfaces high-spread metrics as `conflict` findings on
   the verifier itself so the synthesis layer treats them as
   first-class signals.

4. **AccuracyValidator passthrough** — feeds every Claim collected
   from subagents into the validator and returns assessments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from datetime import datetime, timezone

from finagent.accuracy_validator import AccuracyValidator, Claim, Source
from finagent.agents.base import AgentTaskResult, BaseSubAgent, Finding, SubAgentContext
from finagent.analysis.conflicts import detect_conflicts
from finagent.tools.web.scraper import ScrapedDoc

logger = logging.getLogger("finagent.agents.verifier")


_TIER1_HOST_HINTS = (
    "sec.gov",
    "investor.gov",
    "federalreserve.gov",
    "ir.",
    "investor.",
)


def _is_tier1(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _TIER1_HOST_HINTS)


@dataclass
class VerifierReport:
    promoted: list[dict] = field(default_factory=list)
    demoted: list[dict] = field(default_factory=list)
    corroborated: list[dict] = field(default_factory=list)
    singletons: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    accuracy_assessments: list[dict] = field(default_factory=list)
    tier1_coverage_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "promoted": self.promoted,
            "demoted": self.demoted,
            "corroborated": self.corroborated,
            "singletons": self.singletons,
            "conflicts": self.conflicts,
            "accuracy_assessments": self.accuracy_assessments,
            "tier1_coverage_pct": round(self.tier1_coverage_pct, 1),
        }


class Verifier:
    def __init__(self, validator: AccuracyValidator | None = None) -> None:
        self.validator = validator or AccuracyValidator()

    def run(
        self,
        *,
        findings: list[Finding],
        docs: list[ScrapedDoc],
        emit: Callable[..., None] | None = None,
    ) -> VerifierReport:
        emit = emit or (lambda *_a, **_kw: None)
        report = VerifierReport()
        emit("verifier_started", findings=len(findings), docs=len(docs))

        # 1) Tier-1 enforcement
        high_conf = [f for f in findings if f.confidence == "HIGH"]
        n_high_with_tier1 = 0
        for f in high_conf:
            has_tier1 = any(_is_tier1(u) for u in f.evidence)
            if has_tier1:
                n_high_with_tier1 += 1
                report.promoted.append({
                    "agent": f.agent, "headline": f.headline, "reason": "tier-1 source confirmed",
                })
            else:
                f.confidence = "MEDIUM"
                report.demoted.append({
                    "agent": f.agent, "headline": f.headline, "reason": "HIGH without tier-1 evidence",
                })
        report.tier1_coverage_pct = (
            (n_high_with_tier1 / len(high_conf)) * 100.0 if high_conf else 100.0
        )

        # 2) Cross-source corroboration on headlines (lightweight: token
        # overlap on the first 40 chars per finding)
        seen_keys: dict[str, list[Finding]] = {}
        for f in findings:
            key = " ".join(f.headline.lower().split()[:6])
            seen_keys.setdefault(key, []).append(f)
        for key, group in seen_keys.items():
            if len(group) >= 2:
                agents = sorted({g.agent for g in group})
                if len(agents) >= 2:
                    # Promote the highest-confidence in the group
                    for g in group:
                        if g.confidence == "MEDIUM":
                            g.confidence = "HIGH"
                    report.corroborated.append({
                        "key": key,
                        "agents": agents,
                        "count": len(group),
                    })
            else:
                if group[0].confidence == "HIGH":
                    report.singletons.append({
                        "agent": group[0].agent,
                        "headline": group[0].headline,
                        "reason": "single-agent HIGH finding",
                    })

        # 3) Numeric conflicts across the doc pool
        try:
            conflicts = detect_conflicts(docs)
        except Exception as exc:
            logger.warning("conflict detection failed: %s", exc)
            conflicts = []
        for c in conflicts:
            report.conflicts.append({
                "metric": c.metric,
                "spread_pct": round(c.spread_pct, 1),
                "note": c.note,
                "observations": [
                    {"domain": o.domain, "tier": o.tier, "raw": o.raw, "value": o.value, "url": o.url}
                    for o in c.observations
                ],
            })

        # 4) AccuracyValidator passthrough on every finding-as-claim.
        agent_claims: list[Claim] = []
        for f in findings:
            agent_claims.append(
                Claim(
                    text=f.headline,
                    is_material=(f.kind in ("financial", "risk", "governance") and f.confidence == "HIGH"),
                )
            )
        # Build Source pool from the doc corpus
        now = datetime.now(timezone.utc)
        sources: list[Source] = []
        for d in docs:
            url = d.final_url or d.url or ""
            try:
                sources.append(
                    Source(
                        name=getattr(d, "domain", "") or url,
                        tier=getattr(d, "tier", 7),
                        retrieved_at=now,
                        is_primary_financial=_is_tier1(url),
                    )
                )
            except Exception:
                continue
        for claim in agent_claims[:60]:  # cap for speed
            try:
                result = self.validator.validate(claim, sources, min_sources=2)
                report.accuracy_assessments.append({
                    "claim": claim.text[:160],
                    "confidence": result.confidence_level.value,
                    "conflicts": result.conflicts,
                    "staleness": result.staleness_warnings,
                    "requires_gate": result.requires_gate,
                })
            except Exception as exc:
                logger.debug("accuracy validate failed: %s", exc)
                continue

        emit(
            "verifier_done",
            promoted=len(report.promoted),
            demoted=len(report.demoted),
            corroborated=len(report.corroborated),
            singletons=len(report.singletons),
            conflicts=len(report.conflicts),
            tier1_coverage_pct=round(report.tier1_coverage_pct, 1),
            accuracy_count=len(report.accuracy_assessments),
        )
        return report


class VerifierAgent(BaseSubAgent):
    """Adapter so the verifier can run inside the orchestrator graph
    after all specialists finish. Stores its report in `extra`.
    """

    name = "verifier"
    display = "Verifier"
    priority = 100  # runs last
    skippable = False

    def __init__(self, *, results_ref: dict, all_findings_ref: list, all_docs_ref: list) -> None:
        super().__init__()
        self._results_ref = results_ref
        self._findings_ref = all_findings_ref
        self._docs_ref = all_docs_ref
        self.verifier = Verifier()

    async def execute(self, ctx: SubAgentContext) -> AgentTaskResult:
        out = AgentTaskResult(agent_name=self.name)
        emit = ctx.emit
        report = self.verifier.run(
            findings=self._findings_ref,
            docs=self._docs_ref + list(ctx.seed_docs),
            emit=emit,
        )
        out.extra["verifier_report"] = report.to_dict()
        # Surface the verifier's findings as Findings for the synthesis
        # layer so they're rendered alongside specialist output.
        if report.conflicts:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="risk",
                    headline=f"{len(report.conflicts)} cross-source disagreement(s) flagged",
                    detail="; ".join(
                        f"{c['metric']} spread {c['spread_pct']:.0f}%" for c in report.conflicts[:4]
                    ),
                    confidence="MEDIUM",
                )
            )
        if report.demoted:
            out.findings.append(
                Finding(
                    agent=self.name,
                    kind="governance",
                    headline=f"{len(report.demoted)} finding(s) demoted for missing tier-1 evidence",
                    detail="; ".join(d["headline"][:80] for d in report.demoted[:3]),
                    confidence="LOW",
                )
            )
        return out
