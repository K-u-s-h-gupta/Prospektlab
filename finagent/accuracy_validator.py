"""Post-processor: triangulation, confidence, conflicts, staleness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    DERIVED = "DERIVED"


@dataclass
class Claim:
    text: str
    is_material: bool
    as_of: datetime | None = None


@dataclass
class Source:
    name: str
    tier: int  # 1 = highest per Section 3.1
    retrieved_at: datetime
    is_primary_financial: bool = False


@dataclass
class ValidationResult:
    confidence_level: ConfidenceLevel
    conflicts: list[str]
    staleness_warnings: list[str]
    requires_gate: bool


class AccuracyValidator:
    def validate(self, claim: Claim, sources: list[Source], min_sources: int = 2) -> ValidationResult:
        conflicts = self._detect_conflicts(claim, sources)
        staleness = self._check_staleness(sources)
        confidence = self._score_sources(sources, claim)
        requires_gate = claim.is_material and len(sources) < min_sources
        return ValidationResult(
            confidence_level=confidence,
            conflicts=conflicts,
            staleness_warnings=staleness,
            requires_gate=requires_gate,
        )

    def _score_sources(self, sources: list[Source], claim: Claim) -> ConfidenceLevel:
        if not sources:
            return ConfidenceLevel.LOW
        primary = sum(1 for s in sources if s.tier <= 2 or s.is_primary_financial)
        if primary >= 2:
            return ConfidenceLevel.HIGH
        if primary == 1 and len(sources) >= 2:
            return ConfidenceLevel.MEDIUM
        if len(sources) == 1:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.MEDIUM

    def _detect_conflicts(self, claim: Claim, sources: list[Source]) -> list[str]:
        # Placeholder: integrate numeric parsers for revenue etc.
        _ = claim
        _ = sources
        return []

    def _check_staleness(self, sources: list[Source]) -> list[str]:
        now = datetime.now(timezone.utc)
        out: list[str] = []
        for s in sources:
            age_days = (now - s.retrieved_at).days
            if age_days > 90:
                out.append(f"{s.name}: data older than 90 days ({age_days}d)")
        return out
