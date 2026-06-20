"""Swarm data models and contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class SubTask:
    """One unit of work delegated by the SwarmCoordinator."""

    task_id: str
    agent_id: str  # skill name, e.g. "financials_analyst"
    objective: str
    priority: int = 50
    dependencies: list[str] = field(default_factory=list)
    max_steps: int = 8
    budget_ms: int = 30_000
    tools: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "objective": self.objective,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "max_steps": self.max_steps,
            "budget_ms": self.budget_ms,
            "tools": self.tools,
            "extra": self.extra,
        }


@dataclass
class SubTaskResult:
    """Result returned by a swarm agent for a single SubTask."""

    task_id: str
    agent_id: str
    status: str = "ok"  # ok | partial | failed | skipped
    findings: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "findings_count": len(self.findings),
            "claims_count": len(self.claims),
            "citations_count": len(self.citations),
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "extra": self.extra,
        }


SubTaskRunner = Callable[[SubTask, "SwarmContext"], Awaitable[SubTaskResult]]


@dataclass
class SwarmContext:
    """Shared context passed to every swarm agent."""

    session_id: str
    target: str
    raw_query: str
    objective: str
    resolved_entity: dict | None = None
    blackboard: "EvidenceBlackboard" | None = None
    emit: Callable[..., None] = field(default=lambda *_a, **_kw: None)
    user_email: str | None = None
    tenant_id: str | None = None
    portfolio_symbols: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "target": self.target,
            "raw_query": self.raw_query,
            "objective": self.objective,
            "resolved_entity": self.resolved_entity,
            "user_email": self.user_email,
            "tenant_id": self.tenant_id,
            "portfolio_symbols": self.portfolio_symbols,
        }


@dataclass
class SwarmPlan:
    """Plan produced by the SwarmCoordinator."""

    tasks: list[SubTask] = field(default_factory=list)
    reasoning: str = ""
    estimated_agents: int = 0

    def to_dict(self) -> dict:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "reasoning": self.reasoning,
            "estimated_agents": len(self.tasks),
        }


@dataclass
class SwarmStats:
    """Runtime statistics for a swarm run."""

    total_tasks: int = 0
    completed: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0
    retried: int = 0
    elapsed_ms: int = 0
    max_concurrency: int = 0

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "completed": self.completed,
            "partial": self.partial,
            "failed": self.failed,
            "skipped": self.skipped,
            "retried": self.retried,
            "elapsed_ms": self.elapsed_ms,
            "max_concurrency": self.max_concurrency,
        }


__all__ = [
    "SubTask",
    "SubTaskResult",
    "SubTaskRunner",
    "SwarmContext",
    "SwarmPlan",
    "SwarmStats",
]
