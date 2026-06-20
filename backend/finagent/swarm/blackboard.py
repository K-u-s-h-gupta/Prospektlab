"""Shared evidence blackboard for the swarm.

All agents read from and write to a single blackboard so that findings can be
cross-checked, contradictions detected, and gaps filled without re-running full
research loops.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("finagent.swarm.blackboard")


# Map an agent/skill id (or legacy specialist name) to a canonical blackboard
# domain. `agent_id.split("_")[0]` was silently dropping competitor_moat ->
# "competitor" (domain is plural "competitors") and causal_war_gamer ->
# "causal" (no such domain) into the unrendered "metadata" bin.
_DOMAIN_ALIAS: dict[str, str] = {
    # skill ids
    "financials_analyst": "financials",
    "valuation_modeler": "valuation",
    "governance_forensics": "governance",
    "risk_redflags": "risk",
    "competitor_moat": "competitors",
    "news_sentiment": "news",
    "macro_sector": "macro",
    "causal_war_gamer": "scenarios",
    "document_producer": "documents",
    # legacy specialist .name values
    "financials": "financials",
    "valuation": "valuation",
    "governance": "governance",
    "risk": "risk",
    "competitor": "competitors",
    "competitors": "competitors",
    "news": "news",
    "macro": "macro",
    "accounting": "financials",
    "technical": "valuation",
    "community": "sentiment",
    "sentiment": "sentiment",
    "scenarios": "scenarios",
    "causal": "scenarios",
}


def domain_for_agent(agent_id: str) -> str:
    """Resolve an agent/skill id to a canonical blackboard domain."""
    if not agent_id:
        return "metadata"
    if agent_id in _DOMAIN_ALIAS:
        return _DOMAIN_ALIAS[agent_id]
    head = agent_id.split("_")[0]
    return _DOMAIN_ALIAS.get(head, head if head else "metadata")


@dataclass
class BlackboardClaim:
    """One structured claim on the blackboard."""

    claim_id: str
    text: str
    agent: str
    domain: str
    confidence: str = "MEDIUM"  # HIGH | MEDIUM | LOW
    sources: list[dict] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    contradiction_id: str | None = None
    uncertainty_note: str = ""

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "agent": self.agent,
            "domain": self.domain,
            "confidence": self.confidence,
            "sources": self.sources,
            "metrics": self.metrics,
            "verified": self.verified,
            "contradiction_id": self.contradiction_id,
            "uncertainty_note": self.uncertainty_note,
        }


@dataclass
class Contradiction:
    """Detected conflict between two claims."""

    contradiction_id: str
    claim_a_id: str
    claim_b_id: str
    reason: str
    resolution: str | None = None
    arbitrator: str = ""

    def to_dict(self) -> dict:
        return {
            "contradiction_id": self.contradiction_id,
            "claim_a_id": self.claim_a_id,
            "claim_b_id": self.claim_b_id,
            "reason": self.reason,
            "resolution": self.resolution,
            "arbitrator": self.arbitrator,
        }


class EvidenceBlackboard:
    """Thread/async-safe in-memory blackboard for one research session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.domains: dict[str, list[BlackboardClaim]] = {
            "financials": [],
            "valuation": [],
            "governance": [],
            "risk": [],
            "macro": [],
            "news": [],
            "competitors": [],
            "sentiment": [],
            "scenarios": [],
            "documents": [],
            "metadata": [],
        }
        self.contradictions: list[Contradiction] = []
        self.gaps: list[dict] = []
        self._claim_counter = 0
        # Raw specialist outputs preserved verbatim for the strong-model
        # synthesis pass (synthesize_memo wants Finding objects + ScrapedDocs,
        # not the lossy claim dicts the canvas/UI use).
        self.raw_findings: list = []
        self.raw_docs: list = []

    def _next_claim_id(self) -> str:
        self._claim_counter += 1
        return f"c-{self._claim_counter:04d}"

    def add_claim(
        self,
        text: str,
        agent: str,
        domain: str,
        confidence: str = "MEDIUM",
        sources: list[dict] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> BlackboardClaim:
        if domain not in self.domains:
            domain = "metadata"
        claim = BlackboardClaim(
            claim_id=self._next_claim_id(),
            text=text,
            agent=agent,
            domain=domain,
            confidence=confidence,
            sources=sources or [],
            metrics=metrics or {},
        )
        self.domains[domain].append(claim)
        logger.debug("[BLACKBOARD] claim %s added to %s by %s", claim.claim_id, domain, agent)
        return claim

    def add_findings(self, agent: str, domain: str, findings: list[dict]) -> list[BlackboardClaim]:
        claims: list[BlackboardClaim] = []
        for f in findings:
            claim = self.add_claim(
                text=f.get("headline", f.get("text", "")),
                agent=agent,
                domain=domain,
                confidence=f.get("confidence", "MEDIUM"),
                sources=f.get("sources") or f.get("evidence") or [],
                metrics=f.get("metrics", {}),
            )
            claims.append(claim)
        return claims

    def add_subtask_result(self, result: "SubTaskResult") -> list[BlackboardClaim]:
        """Ingest a SubTaskResult into the blackboard."""
        agent = result.agent_id
        domain = domain_for_agent(agent)
        claims: list[BlackboardClaim] = []
        for f in result.findings:
            claims.extend(self.add_findings(agent, domain, [f]))
        for c in result.claims:
            claims.extend(self.add_findings(agent, domain, [c]))
        # Preserve raw Finding objects + docs (stashed in extra by the runner)
        # so the synthesis pass can reuse the proven artifact/chart machinery.
        extra = getattr(result, "extra", None) or {}
        raw = extra.get("raw_findings")
        if raw:
            self.raw_findings.extend(raw)
        docs = extra.get("raw_docs")
        if docs:
            self.raw_docs.extend(docs)
        return claims

    def list_claims(self, domain: str | None = None) -> list[BlackboardClaim]:
        if domain is None:
            return [c for lst in self.domains.values() for c in lst]
        return self.domains.get(domain, [])

    def add_contradiction(self, claim_a: BlackboardClaim, claim_b: BlackboardClaim, reason: str) -> Contradiction:
        cid = f"contra-{len(self.contradictions)+1:03d}"
        contradiction = Contradiction(
            contradiction_id=cid,
            claim_a_id=claim_a.claim_id,
            claim_b_id=claim_b.claim_id,
            reason=reason,
        )
        self.contradictions.append(contradiction)
        claim_a.contradiction_id = cid
        claim_b.contradiction_id = cid
        logger.info("[BLACKBOARD] contradiction %s: %s vs %s", cid, claim_a.claim_id, claim_b.claim_id)
        return contradiction

    def add_gap(self, topic: str, reason: str, assigned_agent: str | None = None) -> dict:
        gap = {
            "gap_id": f"gap-{len(self.gaps)+1:03d}",
            "topic": topic,
            "reason": reason,
            "assigned_agent": assigned_agent,
            "status": "open",
        }
        self.gaps.append(gap)
        return gap

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "domains": {k: [c.to_dict() for c in v] for k, v in self.domains.items()},
            "contradictions": [c.to_dict() for c in self.contradictions],
            "gaps": self.gaps,
            "total_claims": sum(len(v) for v in self.domains.values()),
        }

    def fingerprint(self) -> str:
        """Simple fingerprint for change detection."""
        payload = self.to_dict()
        return hashlib.md5(str(payload).encode()).hexdigest()[:12]


__all__ = ["EvidenceBlackboard", "BlackboardClaim", "Contradiction"]
