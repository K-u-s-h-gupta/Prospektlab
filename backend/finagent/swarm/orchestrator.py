"""Swarm orchestrator: dynamic coordinator + bounded parallel executor.

The coordinator turns a user query into a plan of SubTasks, then the executor
runs them with a bounded concurrency pool, writes findings to a shared
EvidenceBlackboard, and supervises/reassigns failed or stalled tasks.

Designed to support up to 300 sub-agents for deep mode, bounded by a
configurable concurrency limit and cost/token guardrails.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from finagent.swarm.blackboard import EvidenceBlackboard
from finagent.swarm.models import SubTask, SubTaskResult, SwarmContext, SwarmPlan, SwarmStats
from finagent.swarm.skills import get_skill_registry
from finagent.swarm.supervisor import Supervisor

logger = logging.getLogger("finagent.swarm.orchestrator")


class SwarmOrchestrator:
    """Kimi-style dynamic agent swarm orchestrator."""

    def __init__(
        self,
        *,
        max_concurrency: int = 10,
        max_tasks: int = 300,
        max_wall_seconds: float = 300.0,
        default_budget_ms: int = 30_000,
        emit: Callable[..., None] | None = None,
        planner_model: str | None = None,
        runner: Callable[[SubTask, SwarmContext], Awaitable[SubTaskResult]] | None = None,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.max_tasks = max_tasks
        self.max_wall_seconds = max_wall_seconds
        self.default_budget_ms = default_budget_ms
        self.emit = emit or (lambda *_a, **_kw: None)
        self.planner_model = planner_model
        self.runner = runner or self._default_runner
        self.supervisor = Supervisor()
        self._registry = get_skill_registry()
        self._cancelled = False

    async def run(
        self,
        ctx: SwarmContext,
        *,
        prebuilt_plan: SwarmPlan | None = None,
    ) -> tuple[EvidenceBlackboard, SwarmStats]:
        """Execute the full swarm for a given context."""
        t0 = time.perf_counter()
        if ctx.blackboard is None:
            ctx.blackboard = EvidenceBlackboard(ctx.session_id)

        # 1. Plan
        self.emit("swarm_planning", phase="plan", message="Building swarm plan...")
        plan = prebuilt_plan or await self._plan(ctx)
        plan.tasks = plan.tasks[: self.max_tasks]
        stats = SwarmStats(total_tasks=len(plan.tasks), max_concurrency=self.max_concurrency)

        self.emit(
            "swarm_plan",
            plan=plan.to_dict(),
            total_tasks=len(plan.tasks),
            reasoning=plan.reasoning,
        )
        logger.info("[SWARM] plan generated | tasks=%d | max_concurrency=%d", len(plan.tasks), self.max_concurrency)

        # 2. Execute in dependency-respecting waves with bounded concurrency
        ctx.blackboard.session_id = ctx.session_id
        completed: dict[str, SubTaskResult] = {}
        pending = {t.task_id: t for t in plan.tasks}
        in_flight: dict[str, asyncio.Task] = {}
        started_at = time.perf_counter()

        while pending or in_flight:
            if self._cancelled:
                for task in in_flight.values():
                    task.cancel()
                break

            elapsed = time.perf_counter() - started_at
            if elapsed > self.max_wall_seconds:
                logger.warning("[SWARM] wall-clock budget exceeded at %.1fs", elapsed)
                for task in in_flight.values():
                    task.cancel()
                break

            # Find ready tasks (all dependencies completed)
            ready = [
                t for t in pending.values()
                if all(dep in completed for dep in t.dependencies)
            ]
            ready.sort(key=lambda t: t.priority)

            # Launch up to max_concurrency
            while ready and len(in_flight) < self.max_concurrency:
                task = ready.pop(0)
                pending.pop(task.task_id)
                in_flight[task.task_id] = asyncio.create_task(
                    self._run_task(task, ctx),
                    name=f"swarm-{task.task_id}",
                )
                self.emit(
                    "swarm_task_start",
                    task=task.to_dict(),
                    active=len(in_flight),
                    remaining=len(pending),
                )

            if not in_flight:
                # Deadlock or budget issue — release remaining pending
                if pending:
                    logger.warning("[SWARM] no in-flight tasks but %d pending — possible dependency gap", len(pending))
                    for t in list(pending.values()):
                        completed[t.task_id] = SubTaskResult(
                            task_id=t.task_id,
                            agent_id=t.agent_id,
                            status="skipped",
                            error="Dependency never satisfied or budget exceeded",
                        )
                break

            # Wait for at least one task to finish
            done, _ = await asyncio.wait(
                in_flight.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                # Remove from in_flight and collect result
                tid = None
                for k, v in in_flight.items():
                    if v is task:
                        tid = k
                        break
                if tid:
                    in_flight.pop(tid)
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    result = SubTaskResult(
                        task_id=tid or "unknown",
                        agent_id="unknown",
                        status="failed",
                        error="Cancelled",
                    )
                except Exception as exc:
                    logger.exception("[SWARM] task %s crashed", tid)
                    result = SubTaskResult(
                        task_id=tid or "unknown",
                        agent_id="unknown",
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )

                completed[result.task_id] = result
                ctx.blackboard.add_subtask_result(result)
                self._update_stats(result, stats)

                self.emit(
                    "swarm_task_done",
                    result=result.to_dict(),
                    active=len(in_flight),
                    completed=stats.completed,
                    partial=stats.partial,
                    failed=stats.failed,
                )

                # Supervisor: reassign failed/partial/empty tasks up to 1 retry
                if result.status in ("failed", "partial"):
                    original = self._find_task_in_plan(plan, result.task_id)
                    if original and not getattr(original, "_retried", False):
                        retry_task = self.supervisor.regenerate(original, result, ctx)
                        if retry_task:
                            retry_task._retried = True  # type: ignore
                            pending[retry_task.task_id] = retry_task
                            stats.retried += 1
                            self.emit(
                                "swarm_task_reassigned",
                                original_task_id=original.task_id,
                                new_task_id=retry_task.task_id,
                                reason=result.error or "partial result",
                            )

        stats.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        self.emit("swarm_done", stats=stats.to_dict(), blackboard=ctx.blackboard.to_dict())
        return ctx.blackboard, stats

    def cancel(self) -> None:
        self._cancelled = True

    async def _plan(self, ctx: SwarmContext) -> SwarmPlan:
        """Use a strong LLM to decompose the objective into SubTasks."""
        # Default deterministic plan if LLM fails or is not configured
        try:
            return await self._llm_plan(ctx)
        except Exception as exc:
            logger.warning("[SWARM] LLM planner failed, falling back to deterministic plan: %s", exc)
            return self._deterministic_plan(ctx)

    async def _llm_plan(self, ctx: SwarmContext) -> SwarmPlan:
        """LLM-driven dynamic decomposition."""
        from finagent.swarm.llm import swarm_chat

        skills = self._registry.list_skills()
        prompt = self._build_planner_prompt(ctx, skills)

        content = await swarm_chat(
            "You are a research planning coordinator. Return only JSON.",
            prompt,
            complexity="complex",
            model=self.planner_model,
            json_mode=True,
            max_tokens=4000,
        )
        import json
        data = json.loads(content or "{}")
        tasks = []
        for item in data.get("tasks", []):
            tasks.append(SubTask(
                task_id=item.get("task_id") or f"t-{uuid.uuid4().hex[:6]}",
                agent_id=item["agent_id"],
                objective=item["objective"],
                priority=item.get("priority", 50),
                dependencies=item.get("dependencies", []),
                max_steps=item.get("max_steps", 8),
                budget_ms=item.get("budget_ms", self.default_budget_ms),
                tools=item.get("tools", []),
                extra=item.get("extra", {}),
            ))
        return SwarmPlan(
            tasks=tasks,
            reasoning=data.get("reasoning", ""),
            estimated_agents=len(tasks),
        )

    def _deterministic_plan(self, ctx: SwarmContext) -> SwarmPlan:
        """Fallback plan when LLM planner is unavailable."""
        base = [
            SubTask(task_id="t-fin", agent_id="financials_analyst", objective=f"Core financials for {ctx.target}", priority=10, dependencies=[]),
            SubTask(task_id="t-gov", agent_id="governance_forensics", objective=f"Governance and forensic analysis for {ctx.target}", priority=15, dependencies=[]),
            SubTask(task_id="t-risk", agent_id="risk_redflags", objective=f"Risk and red flags for {ctx.target}", priority=20, dependencies=[]),
            SubTask(task_id="t-val", agent_id="valuation_modeler", objective=f"Valuation model for {ctx.target}", priority=25, dependencies=["t-fin"]),
            SubTask(task_id="t-comp", agent_id="competitor_moat", objective=f"Competitive moat and peer comparison for {ctx.target}", priority=30, dependencies=["t-fin"]),
            SubTask(task_id="t-news", agent_id="news_sentiment", objective=f"Latest news and sentiment for {ctx.target}", priority=20, dependencies=[]),
            SubTask(task_id="t-macro", agent_id="macro_sector", objective=f"Macro and sector overlay for {ctx.target}", priority=35, dependencies=[]),
            SubTask(task_id="t-causal", agent_id="causal_war_gamer", objective=f"Scenario analysis for {ctx.target}", priority=40, dependencies=["t-fin", "t-val"]),
        ]
        return SwarmPlan(tasks=base, reasoning="Deterministic fallback plan", estimated_agents=len(base))

    def _build_planner_prompt(self, ctx: SwarmContext, skills: list[str]) -> str:
        return (
            f"You are the coordinator of a financial research agent swarm. The user query is:\n"
            f"'{ctx.raw_query}'\n\n"
            f"Target entity: {ctx.target}\n"
            f"Portfolio context: {ctx.portfolio_symbols or 'none'}\n\n"
            f"Available agent skills:\n" + "\n".join(f"- {s}" for s in skills) + "\n\n"
            "Create a swarm plan of up to 50 subtasks. Each task must include: task_id, agent_id, "
            "objective (1-2 sentences), priority (lower = earlier), dependencies (task_ids), max_steps, "
            "and budget_ms. Prefer parallel tasks. Ensure financials/valuation run early, governance/risk "
            "run in parallel, and causal/scenario tasks depend on valuation. Return JSON with keys: reasoning, tasks."
        )

    async def _run_task(self, task: SubTask, ctx: SwarmContext) -> SubTaskResult:
        """Execute a single subtask with timeout and supervision."""
        self.emit(
            "swarm_task_running",
            task_id=task.task_id,
            agent_id=task.agent_id,
        )
        try:
            result = await asyncio.wait_for(
                self.runner(task, ctx),
                timeout=task.budget_ms / 1000.0,
            )
            result.task_id = task.task_id
            result.agent_id = task.agent_id
            return result
        except asyncio.TimeoutError:
            logger.warning("[SWARM] task %s timed out after %dms", task.task_id, task.budget_ms)
            return SubTaskResult(
                task_id=task.task_id,
                agent_id=task.agent_id,
                status="failed",
                error=f"Timeout after {task.budget_ms}ms",
            )
        except Exception as exc:
            logger.exception("[SWARM] task %s failed", task.task_id)
            return SubTaskResult(
                task_id=task.task_id,
                agent_id=task.agent_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _default_runner(self, task: SubTask, ctx: SwarmContext) -> SubTaskResult:
        """Default runner: dispatch to a generic agent runner."""
        # Prefer a registered skill; if missing, use the legacy agent bridge.
        from finagent.swarm.runner import run_subtask_with_skill
        return await run_subtask_with_skill(task, ctx)

    def _update_stats(self, result: SubTaskResult, stats: SwarmStats) -> None:
        if result.status == "ok":
            stats.completed += 1
        elif result.status == "partial":
            stats.partial += 1
        elif result.status == "failed":
            stats.failed += 1
        elif result.status == "skipped":
            stats.skipped += 1

    def _find_task_in_plan(self, plan: SwarmPlan, task_id: str) -> SubTask | None:
        for t in plan.tasks:
            if t.task_id == task_id:
                return t
        return None


__all__ = ["SwarmOrchestrator"]
