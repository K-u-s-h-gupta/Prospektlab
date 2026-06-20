"""Accuracy layer: source verification, contradiction detection, uncertainty quantification, and gap filling.

This layer runs after a swarm or standard bucket pass. It treats every claim as
 guilty until proven cited, detects conflicts, resolves them, and triggers
additional probes for missing evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from finagent.swarm.blackboard import BlackboardClaim, EvidenceBlackboard

logger = logging.getLogger("finagent.accuracy.layer")


@dataclass
class AccuracyReport:
    verified_count: int = 0
    unverified_count: int = 0
    contradictions_resolved: int = 0
    gaps_filled: int = 0
    low_confidence_count: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verified_count": self.verified_count,
            "unverified_count": self.unverified_count,
            "contradictions_resolved": self.contradictions_resolved,
            "gaps_filled": self.gaps_filled,
            "low_confidence_count": self.low_confidence_count,
            "notes": self.notes,
        }


class AccuracyLayer:
    """End-to-end accuracy and trust layer for a research session."""

    def __init__(self, blackboard: EvidenceBlackboard) -> None:
        self.blackboard = blackboard

    def run(self) -> AccuracyReport:
        report = AccuracyReport()

        # 1. Source verification: a claim without a source is downgraded to LOW.
        for claim in self.blackboard.list_claims():
            if not claim.sources:
                claim.confidence = "LOW"
                claim.uncertainty_note = "No source cited."
                report.unverified_count += 1
            else:
                claim.verified = True
                report.verified_count += 1

        # 2. Contradiction detection: simple textual overlap for numeric claims.
        self._detect_numeric_contradictions(report)

        # 3. Gap detection: look for empty domains and open questions.
        self._detect_gaps(report)

        # 4. Uncertainty quantification: re-label confidence based on source diversity.
        self._quantify_uncertainty(report)

        return report

    def _detect_numeric_contradictions(self, report: AccuracyReport) -> None:
        """Find pairs of claims with the same numeric metric but different values."""
        import re

        def extract_number(text: str) -> float | None:
            # Look for currency/percentage numbers
            m = re.search(r"(?:₹|Rs\.?|\$)?\s*([\d,]+(?:\.\d+)?)\s*(?:%|Cr|Lakh|Mn|Bn)?", text)
            if not m:
                return None
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                return None

        # Group claims by metric keyword
        metric_groups: dict[str, list[BlackboardClaim]] = {}
        for claim in self.blackboard.list_claims():
            text_lower = claim.text.lower()
            for metric in ["revenue", "profit", "margin", "eps", "debt", "cash", "roce", "ebitda"]:
                if metric in text_lower:
                    metric_groups.setdefault(metric, []).append(claim)

        for metric, claims in metric_groups.items():
            for i, a in enumerate(claims):
                for b in claims[i + 1 :]:
                    val_a = extract_number(a.text)
                    val_b = extract_number(b.text)
                    if val_a is None or val_b is None:
                        continue
                    # 5% relative difference is a contradiction
                    if abs(val_a - val_b) / max(abs(val_a), abs(val_b), 1) > 0.05:
                        contradiction = self.blackboard.add_contradiction(
                            a, b,
                            reason=f"Numeric mismatch for {metric}: {val_a} vs {val_b}",
                        )
                        # Prefer claim with more diverse sources
                        score_a = len(a.sources) + (1 if a.verified else 0)
                        score_b = len(b.sources) + (1 if b.verified else 0)
                        winner, loser = (a, b) if score_a >= score_b else (b, a)
                        contradiction.resolution = f"Preferred {winner.claim_id} based on stronger sourcing."
                        loser.confidence = "LOW"
                        loser.uncertainty_note = f"Contradicted by {winner.claim_id}; see {contradiction.contradiction_id}."
                        report.contradictions_resolved += 1

    def _detect_gaps(self, report: AccuracyReport) -> None:
        """Add gap tasks for empty or thin domains."""
        required_domains = ["financials", "governance", "risk", "valuation", "news"]
        for domain in required_domains:
            claims = self.blackboard.list_claims(domain)
            if len(claims) < 2:
                gap = self.blackboard.add_gap(
                    topic=f"Insufficient {domain} coverage",
                    reason=f"Only {len(claims)} claims in {domain}",
                    assigned_agent=f"{domain}_agent" if domain != "risk" else "risk_redflags",
                )
                report.gaps_filled += 1
                report.notes.append(f"Gap {gap['gap_id']}: {gap['topic']}")

    def _quantify_uncertainty(self, report: AccuracyReport) -> None:
        """Adjust confidence based on source diversity and domain heuristics."""
        for claim in self.blackboard.list_claims():
            sources = len(claim.sources)
            if sources >= 2 and claim.verified and not claim.contradiction_id:
                claim.confidence = "HIGH"
            elif sources == 1 and claim.verified:
                claim.confidence = "MEDIUM"
            else:
                claim.confidence = "LOW"
                report.low_confidence_count += 1

            # Add an uncertainty note for derived/modeled claims
            if "dcf" in claim.text.lower() or "scenario" in claim.text.lower():
                claim.uncertainty_note = claim.uncertainty_note or "Model-based estimate; assumptions are explicit."


__all__ = ["AccuracyLayer", "AccuracyReport"]
