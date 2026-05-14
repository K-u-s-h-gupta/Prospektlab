"""Checkpoint serialization for long-running sessions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from finagent.state.citation_log import Citation


@dataclass
class StepResult:
    name: str
    summary: str
    ok: bool = True


@dataclass
class ResearchStep:
    name: str
    tool: str
    expected_output: str


@dataclass
class Checkpoint:
    step: int
    completed_steps: list[StepResult]
    pending_steps: list[ResearchStep]
    citation_log: list[Citation]
    confidence_summary: dict[str, float]
    timestamp: datetime
    context_tokens_used: int

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        d["completed_steps"] = [asdict(s) for s in self.completed_steps]
        d["pending_steps"] = [asdict(s) for s in self.pending_steps]
        d["citation_log"] = [
            {
                "url": c.url,
                "title": c.title,
                "date_accessed": c.date_accessed,
                "kind": c.kind,
            }
            for c in self.citation_log
        ]
        return d


def serialize_checkpoint(cp: Checkpoint) -> str:
    return json.dumps(cp.to_json_dict(), indent=2)


def deserialize_checkpoint(raw: str) -> Checkpoint:
    d = json.loads(raw)
    ts = datetime.fromisoformat(d["timestamp"])
    completed = [StepResult(**x) for x in d["completed_steps"]]
    pending = [ResearchStep(**x) for x in d["pending_steps"]]
    citations = [
        Citation(
            url=x["url"],
            title=x["title"],
            date_accessed=x.get("date_accessed", x.get("accessed_at", "")),
            kind=x.get("kind", x.get("source_type", "secondary")),
        )
        for x in d["citation_log"]
    ]
    return Checkpoint(
        step=d["step"],
        completed_steps=completed,
        pending_steps=pending,
        citation_log=citations,
        confidence_summary=d["confidence_summary"],
        timestamp=ts,
        context_tokens_used=d["context_tokens_used"],
    )


def empty_checkpoint(step: int = 0, tokens: int = 0) -> Checkpoint:
    return Checkpoint(
        step=step,
        completed_steps=[],
        pending_steps=[],
        citation_log=[],
        confidence_summary={},
        timestamp=datetime.now(timezone.utc),
        context_tokens_used=tokens,
    )
