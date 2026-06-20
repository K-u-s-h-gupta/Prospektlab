"""Interactive research canvas data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CanvasSource:
    source_id: str
    source_type: str
    title: str = ""
    url: str = ""
    page: str | None = None
    paragraph: str | None = None
    accessed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "title": self.title,
            "url": self.url,
            "page": self.page,
            "paragraph": self.paragraph,
            "accessed_at": self.accessed_at,
        }


@dataclass
class CanvasClaim:
    claim_id: str
    text: str
    agent: str
    confidence: str = "MEDIUM"
    verified: bool = False
    sources: list[CanvasSource] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    uncertainty_note: str = ""
    contradiction_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "agent": self.agent,
            "confidence": self.confidence,
            "verified": self.verified,
            "sources": [s.to_dict() for s in self.sources],
            "metrics": self.metrics,
            "uncertainty_note": self.uncertainty_note,
            "contradiction_id": self.contradiction_id,
        }


@dataclass
class CanvasSection:
    section_id: str
    title: str
    status: str = "draft"  # draft | final | user_edited
    claims: list[CanvasClaim] = field(default_factory=list)
    charts: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "status": self.status,
            "claims": [c.to_dict() for c in self.claims],
            "charts": self.charts,
            "tables": self.tables,
            "summary": self.summary,
        }


@dataclass
class SwarmTaskStatus:
    task_id: str
    agent_id: str
    display: str
    status: str = "pending"  # pending | running | done | failed | skipped
    findings_count: int = 0
    elapsed_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "display": self.display,
            "status": self.status,
            "findings_count": self.findings_count,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


@dataclass
class InteractiveResearchCanvas:
    """Living document model for a research session."""

    session_id: str
    query: str = ""
    target: str = ""
    status: str = "pending"  # pending | running | verifying | synthesizing | done | error
    current_phase: str = "plan"
    phases: list[str] = field(default_factory=lambda: ["plan", "enrich", "swarm", "verify", "synthesize", "export"])
    tasks: list[SwarmTaskStatus] = field(default_factory=list)
    sections: list[CanvasSection] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    citations: list[CanvasSource] = field(default_factory=list)
    user_steers: list[dict] = field(default_factory=list)
    version: int = 1
    memo_md: str = ""  # backwards-compatible fallback

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "target": self.target,
            "status": self.status,
            "current_phase": self.current_phase,
            "phases": self.phases,
            "tasks": [t.to_dict() for t in self.tasks],
            "sections": [s.to_dict() for s in self.sections],
            "contradictions": self.contradictions,
            "gaps": self.gaps,
            "citations": [c.to_dict() for c in self.citations],
            "user_steers": self.user_steers,
            "version": self.version,
            "memo_md": self.memo_md,
        }

    def add_section(self, title: str) -> CanvasSection:
        section = CanvasSection(
            section_id=f"s-{len(self.sections)+1:03d}",
            title=title,
        )
        self.sections.append(section)
        return section

    def get_or_add_section(self, title: str) -> CanvasSection:
        for s in self.sections:
            if s.title == title:
                return s
        return self.add_section(title)

    def add_claim(self, section_title: str, claim: CanvasClaim) -> None:
        section = self.get_or_add_section(section_title)
        section.claims.append(claim)

    def add_task(self, task: SwarmTaskStatus) -> None:
        self.tasks.append(task)

    def update_task(self, task_id: str, **kwargs: Any) -> None:
        for t in self.tasks:
            if t.task_id == task_id:
                for k, v in kwargs.items():
                    setattr(t, k, v)
                break

    def bump_version(self) -> None:
        self.version += 1


__all__ = [
    "InteractiveResearchCanvas",
    "CanvasSection",
    "CanvasClaim",
    "CanvasSource",
    "SwarmTaskStatus",
]
