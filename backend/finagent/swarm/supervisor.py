"""Supervisor: detect failures, stalls, and low-quality results and regenerate tasks."""

from __future__ import annotations

import logging
import uuid

from finagent.swarm.models import SubTask, SubTaskResult, SwarmContext

logger = logging.getLogger("finagent.swarm.supervisor")


# When an agent fails outright (not just thin results), reassign the objective
# to a different specialist that can cover overlapping ground rather than
# re-running the same failing agent. web-bound agents fall back to graph/data
# bound ones and vice-versa.
_FALLBACK_AGENT: dict[str, str] = {
    "governance_forensics": "risk_redflags",
    "risk_redflags": "governance_forensics",
    "news_sentiment": "macro_sector",
    "macro_sector": "news_sentiment",
    "competitor_moat": "financials_analyst",
    "valuation_modeler": "financials_analyst",
    "causal_war_gamer": "risk_redflags",
}


class Supervisor:
    """Monitors swarm task results and regenerates failed or weak tasks."""

    def __init__(self, max_retries: int = 1) -> None:
        self.max_retries = max_retries

    def should_regenerate(self, task: SubTask, result: SubTaskResult, ctx: SwarmContext) -> bool:
        if getattr(task, "_retried", False):
            return False
        if result.status == "failed":
            return True
        if result.status == "partial":
            return True
        if result.status == "ok" and not result.findings and not result.claims:
            return True
        return False

    def regenerate(self, task: SubTask, result: SubTaskResult, ctx: SwarmContext) -> SubTask | None:
        if not self.should_regenerate(task, result, ctx):
            return None

        new_objective = task.objective
        if "retry" not in new_objective.lower():
            new_objective = f"[Retry] {new_objective}. Focus on finding verifiable, source-backed evidence."

        # On a hard failure, reassign to a different specialist that overlaps
        # the same ground; on a thin/partial result, retry the same agent.
        new_agent_id = task.agent_id
        if result.status == "failed":
            fallback = _FALLBACK_AGENT.get(task.agent_id)
            if fallback:
                new_agent_id = fallback
                logger.info("[SUPERVISOR] reassigning failed %s -> %s", task.agent_id, fallback)

        # Tighten scope and add a hint
        new_task = SubTask(
            task_id=f"{task.task_id}-retry-{uuid.uuid4().hex[:4]}",
            agent_id=new_agent_id,
            objective=new_objective,
            priority=task.priority + 1,
            dependencies=task.dependencies,
            max_steps=max(4, task.max_steps - 2),
            budget_ms=min(task.budget_ms, 20_000),
            tools=task.tools,
            extra={**task.extra, "retry_reason": result.error or "partial result", "original_task_id": task.task_id},
        )
        logger.info(
            "[SUPERVISOR] regenerated task %s -> %s (reason=%s)",
            task.task_id, new_task.task_id, result.error or "partial"
        )
        return new_task


__all__ = ["Supervisor"]
