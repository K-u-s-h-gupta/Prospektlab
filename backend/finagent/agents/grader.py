"""Outcome Rubric Grader — post-synthesis quality evaluation.

Evaluates synthesized research against a structured rubric:
  - WACC consistency (valuation vs risk sections)
  - Governance completeness (pledge % addressed if >15%?)
  - Source coverage (minimum 3 Tier 1-2 sources)
  - SEBI compliance (no advisory language leaked)
  - Internal contradiction detection

Outputs ResearchQualityScore (0-100) + specific flags that feed
into the Reflexion step (Phase 3).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("finagent.agents.grader")


# ── Rubric weights ────────────────────────────────────────────────────────────
_RUBRIC_WEIGHTS: dict[str, int] = {
    "sebi_compliance":       25,  # No advisory language — highest weight
    "source_coverage":       20,  # Minimum citations
    "governance_completeness": 15,  # Pledge/director addressed
    "assumption_explicitness": 15,  # WACC + growth stated
    "wacc_consistency":      10,  # Valuation ↔ risk sections agree
    "internal_consistency":  10,  # No contradictions
    "scenario_framing":       5,  # Scenario matrix present
}

# ── Advisory language detection (mirrors compliance.py) ──────────────────────
_ADVISORY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(strong buy|buy|accumulate|strong sell|sell|exit|dump)\b", re.I),
    re.compile(r"\b(undervalued|overvalued|fairly valued)\b", re.I),
    re.compile(r"\b(price target|target price|investment recommendation)\b", re.I),
    re.compile(r"\bshould\s+(buy|sell|hold|invest|exit|accumulate)\b", re.I),
    re.compile(r"\b(verdict|recommendation)\s*:", re.I),
)

# ── Citation detection ────────────────────────────────────────────────────────
_CITATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://[^\s\)>]+"),
    re.compile(r"\[Source:\s*[^\]]+\]", re.I),
    re.compile(r"\(BSE|NSE|MCA|SEBI|Annual\s+Report\s+\d{4}", re.I),
    re.compile(r"according\s+to\s+(?:BSE|NSE|MCA|SEBI|annual\s+report)", re.I),
)

# ── WACC / assumption patterns ────────────────────────────────────────────────
_WACC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bWACC\b", re.I),
    re.compile(r"\bdiscount\s+rate\b", re.I),
    re.compile(r"\bcost\s+of\s+(equity|capital)\b", re.I),
    re.compile(r"\bgrowth\s+rate\s+(assumption|of)\b", re.I),
    re.compile(r"\bterminal\s+growth\b", re.I),
)

_PLEDGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpledge\b", re.I),
    re.compile(r"\bpromoter\s+holding\b", re.I),
    re.compile(r"\bencumbre\b", re.I),
)

_SCENARIO_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bscenario\b", re.I),
    re.compile(r"\bunder\s+(these|stated|the\s+above)\s+assumptions\b", re.I),
    re.compile(r"\bif\s+[\w\s]+,\s+then\b", re.I),
    re.compile(r"\bbull\s+case\b|\bbear\s+case\b|\bbase\s+case\b", re.I),
)


@dataclass
class GraderFlag:
    """A specific quality issue flagged by the grader."""
    code: str         # e.g. "SEBI_ADVISORY_LANGUAGE"
    severity: str     # "critical" | "warning" | "info"
    message: str
    responsible_agent: str = "synthesis"  # which agent should fix it
    location: str = ""  # snippet of offending text


@dataclass
class ResearchQualityScore:
    """Post-synthesis quality evaluation result."""

    # Rubric scores (0-100 per dimension)
    sebi_compliance_score: int = 0
    source_coverage_score: int = 0
    governance_completeness_score: int = 0
    assumption_explicitness_score: int = 0
    wacc_consistency_score: int = 0
    internal_consistency_score: int = 0
    scenario_framing_score: int = 0

    # Aggregate
    total_score: int = 0  # weighted 0-100
    flags: list[GraderFlag] = field(default_factory=list)
    graded_at: float = field(default_factory=time.time)
    grader_version: str = "1.0.0"

    @property
    def passed(self) -> bool:
        """Research passed minimum quality bar (score ≥ 65, no critical flags)."""
        has_critical = any(f.severity == "critical" for f in self.flags)
        return self.total_score >= 65 and not has_critical

    @property
    def summary(self) -> str:
        if self.passed:
            return f"PASS ({self.total_score}/100) — {len(self.flags)} warnings"
        return f"FAIL ({self.total_score}/100) — {len(self.flags)} flags"

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "passed": self.passed,
            "summary": self.summary,
            "dimension_scores": {
                "sebi_compliance": self.sebi_compliance_score,
                "source_coverage": self.source_coverage_score,
                "governance_completeness": self.governance_completeness_score,
                "assumption_explicitness": self.assumption_explicitness_score,
                "wacc_consistency": self.wacc_consistency_score,
                "internal_consistency": self.internal_consistency_score,
                "scenario_framing": self.scenario_framing_score,
            },
            "flags": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    "responsible_agent": f.responsible_agent,
                    "location": f.location[:120],
                }
                for f in self.flags
            ],
            "graded_at": self.graded_at,
        }


def grade_research(
    synthesis_output: str,
    *,
    entity_name: str = "",
    agent_outputs: dict[str, str] | None = None,
    pledge_pct: float | None = None,
) -> ResearchQualityScore:
    """Evaluate synthesized research against the quality rubric.

    Args:
        synthesis_output: The final synthesis text (markdown).
        entity_name: Company name for context-aware checks.
        agent_outputs: Dict of agent_type → agent output for cross-check.
        pledge_pct: Known promoter pledge percentage (from IKG), if available.

    Returns:
        ResearchQualityScore with total_score and list of flags.
    """
    result = ResearchQualityScore()
    flags: list[GraderFlag] = []
    text = synthesis_output or ""

    # ── 1. SEBI Compliance (25 pts) ──────────────────────────────────────────
    advisory_hits: list[str] = []
    for pat in _ADVISORY_PATTERNS:
        for match in pat.finditer(text):
            advisory_hits.append(match.group(0))
    if not advisory_hits:
        result.sebi_compliance_score = 100
    else:
        # Each distinct advisory term costs points
        deduction = min(100, len(set(advisory_hits)) * 20)
        result.sebi_compliance_score = max(0, 100 - deduction)
        flags.append(GraderFlag(
            code="SEBI_ADVISORY_LANGUAGE",
            severity="critical" if len(advisory_hits) > 2 else "warning",
            message=f"Advisory language detected: {set(advisory_hits)}",
            responsible_agent="synthesis",
            location=", ".join(list(set(advisory_hits))[:5]),
        ))

    # ── 2. Source Coverage (20 pts) ──────────────────────────────────────────
    citation_count = sum(len(pat.findall(text)) for pat in _CITATION_PATTERNS)
    if citation_count >= 5:
        result.source_coverage_score = 100
    elif citation_count >= 3:
        result.source_coverage_score = 75
    elif citation_count >= 1:
        result.source_coverage_score = 40
        flags.append(GraderFlag(
            code="LOW_SOURCE_COVERAGE",
            severity="warning",
            message=f"Only {citation_count} citations found; minimum is 3 Tier-1/2 sources",
            responsible_agent="synthesis",
        ))
    else:
        result.source_coverage_score = 0
        flags.append(GraderFlag(
            code="NO_SOURCES",
            severity="critical",
            message="No citations or source references found in synthesis output",
            responsible_agent="synthesis",
        ))

    # ── 3. Governance Completeness (15 pts) ──────────────────────────────────
    pledge_mentioned = any(pat.search(text) for pat in _PLEDGE_PATTERNS)
    if pledge_pct is not None and pledge_pct > 15:
        if pledge_mentioned:
            result.governance_completeness_score = 100
        else:
            result.governance_completeness_score = 20
            flags.append(GraderFlag(
                code="PLEDGE_NOT_ADDRESSED",
                severity="warning",
                message=f"Promoter pledge is {pledge_pct:.1f}% but not discussed in synthesis",
                responsible_agent="governance",
            ))
    else:
        # Pledge not a concern or not known
        result.governance_completeness_score = 80 if pledge_mentioned or not pledge_pct else 60

    # ── 4. Assumption Explicitness (15 pts) ───────────────────────────────────
    wacc_hits = sum(1 for pat in _WACC_PATTERNS if pat.search(text))
    if wacc_hits >= 3:
        result.assumption_explicitness_score = 100
    elif wacc_hits >= 2:
        result.assumption_explicitness_score = 70
    elif wacc_hits >= 1:
        result.assumption_explicitness_score = 40
        flags.append(GraderFlag(
            code="IMPLICIT_ASSUMPTIONS",
            severity="warning",
            message="Valuation assumptions (WACC/growth rate) not clearly stated",
            responsible_agent="valuation",
        ))
    else:
        # No valuation section — may be OK for news/governance queries
        result.assumption_explicitness_score = 60

    # ── 5. WACC Consistency (10 pts) ─────────────────────────────────────────
    # Cross-check: does risk agent's beta match valuation agent's WACC?
    if agent_outputs:
        valuation_out = agent_outputs.get("valuation", "")
        risk_out = agent_outputs.get("risk", "")
        wacc_in_val = bool(re.search(r"WACC.*?(\d+\.?\d*%?)", valuation_out, re.I))
        wacc_in_risk = bool(re.search(r"(?:beta|discount|WACC)", risk_out, re.I))
        if wacc_in_val and wacc_in_risk:
            result.wacc_consistency_score = 90
        elif wacc_in_val or wacc_in_risk:
            result.wacc_consistency_score = 60
        else:
            result.wacc_consistency_score = 50
    else:
        result.wacc_consistency_score = 70  # No cross-check possible

    # ── 6. Internal Consistency (10 pts) ─────────────────────────────────────
    # Heuristic: check for contradictory directional signals in the same doc
    positive_signals = len(re.findall(r"\b(strong|excellent|robust|healthy|growing)\b", text, re.I))
    negative_signals = len(re.findall(r"\b(weak|declining|deteriorating|concerning|negative)\b", text, re.I))
    # Contradictions are OK if they're in different sections — only flag if in same sentence
    contradictions = re.findall(
        r"[^.]*\b(strong|excellent|robust)[^.]*\b(weak|declining|concerning)[^.]*\.",
        text, re.I
    )
    if contradictions:
        result.internal_consistency_score = 60
        flags.append(GraderFlag(
            code="INTERNAL_CONTRADICTION",
            severity="info",
            message=f"Possible contradictory signals in same sentence ({len(contradictions)} instances)",
            responsible_agent="synthesis",
            location=str(contradictions[0])[:100],
        ))
    else:
        result.internal_consistency_score = 90

    # ── 7. Scenario Framing (5 pts) ──────────────────────────────────────────
    scenario_hits = sum(1 for pat in _SCENARIO_PATTERNS if pat.search(text))
    if scenario_hits >= 2:
        result.scenario_framing_score = 100
    elif scenario_hits >= 1:
        result.scenario_framing_score = 60
    else:
        result.scenario_framing_score = 20
        flags.append(GraderFlag(
            code="NO_SCENARIO_FRAMING",
            severity="info",
            message="Scenario-conditional framing (bull/bear/base case or IF-THEN) not found",
            responsible_agent="synthesis",
        ))

    # ── Weighted aggregate ────────────────────────────────────────────────────
    total = (
        result.sebi_compliance_score * _RUBRIC_WEIGHTS["sebi_compliance"] +
        result.source_coverage_score * _RUBRIC_WEIGHTS["source_coverage"] +
        result.governance_completeness_score * _RUBRIC_WEIGHTS["governance_completeness"] +
        result.assumption_explicitness_score * _RUBRIC_WEIGHTS["assumption_explicitness"] +
        result.wacc_consistency_score * _RUBRIC_WEIGHTS["wacc_consistency"] +
        result.internal_consistency_score * _RUBRIC_WEIGHTS["internal_consistency"] +
        result.scenario_framing_score * _RUBRIC_WEIGHTS["scenario_framing"]
    ) // 100

    result.total_score = int(min(100, max(0, total)))
    result.flags = flags

    logger.info(
        "[GRADER] entity=%s total=%d/%d flags=%d passed=%s",
        entity_name, result.total_score, 100, len(flags), result.passed,
    )
    return result
