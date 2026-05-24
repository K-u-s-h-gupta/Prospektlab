"""Parallel subagent orchestrator.

Runs a roster of subagents in dependency-aware waves:
- Wave 0: all agents with no dependencies fire concurrently
- Wave N: agents whose dependencies are all met from prior waves

Within a wave we use `asyncio.gather` for true parallelism. Each agent
has its own timeout (`SubAgentContext.deadline_ms`) so one slow agent
doesn't block the whole wave.

This is the "many minds, one brain" pattern from Hermes: each subagent
is a small specialist; the orchestrator is the synthesizer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from finagent.agents.base import (
    AgentTaskResult,
    BaseSubAgent,
    Finding,
    SubAgentContext,
)
from finagent.tools.web.scraper import ScrapedDoc

logger = logging.getLogger("finagent.agents.orchestrator")


@dataclass
class OrchestrationResult:
    results: dict[str, AgentTaskResult] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    new_docs: list[ScrapedDoc] = field(default_factory=list)
    elapsed_ms: int = 0
    waves: int = 0

    @property
    def status_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results.values():
            out[r.status] = out.get(r.status, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "agents_total": len(self.results),
            "findings_total": len(self.findings),
            "new_docs_total": len(self.new_docs),
            "elapsed_ms": self.elapsed_ms,
            "waves": self.waves,
            "status_counts": self.status_counts,
            "agents": {n: r.summary_dict() for n, r in self.results.items()},
        }


def _waves(agents: list[BaseSubAgent]) -> list[list[BaseSubAgent]]:
    """Topological grouping by dependency. Each returned list is a wave
    runnable in parallel."""
    name_to_agent = {a.name: a for a in agents}
    completed: set[str] = set()
    remaining: dict[str, BaseSubAgent] = {a.name: a for a in agents}
    waves: list[list[BaseSubAgent]] = []
    while remaining:
        ready = [
            a for a in remaining.values()
            if all(dep in completed or dep not in name_to_agent for dep in a.dependencies)
        ]
        if not ready:
            # Break the cycle defensively rather than spinning forever.
            logger.warning("dependency cycle detected, releasing remaining agents into one wave")
            ready = list(remaining.values())
        ready.sort(key=lambda a: a.priority)
        waves.append(ready)
        for a in ready:
            completed.add(a.name)
            remaining.pop(a.name, None)
    return waves


class Orchestrator:
    def __init__(
        self,
        agents: list[BaseSubAgent],
        *,
        emit: Callable[..., None] | None = None,
        per_agent_deadline_ms: int = 45_000,
    ) -> None:
        self.agents = agents
        self.emit = emit or (lambda *_a, **_kw: None)
        self.per_agent_deadline_ms = per_agent_deadline_ms

    async def run(self, ctx: SubAgentContext) -> OrchestrationResult:
        t0 = time.perf_counter()
        out = OrchestrationResult()
        ctx.emit = self.emit
        ctx.deadline_ms = self.per_agent_deadline_ms

        waves = _waves(self.agents)
        out.waves = len(waves)

        logger.info("[ORCHESTRATOR] Starting | total_agents=%d | waves=%d | agents=%s",
                    len(self.agents), len(waves), [a.name for a in self.agents])
        logger.info("[ORCHESTRATOR] Wave plan: %s", [[a.name for a in w] for w in waves])

        self.emit(
            "orchestrator_started",
            agents=[a.name for a in self.agents],
            waves=[[a.name for a in w] for w in waves],
            per_agent_deadline_ms=self.per_agent_deadline_ms,
        )

        for wave_idx, wave in enumerate(waves):
            if getattr(ctx, "budget_exceeded", None) and ctx.budget_exceeded():
                logger.info("[ORCHESTRATOR] Stopping wave %s: time budget exceeded", wave_idx + 1)
                break

            logger.info("[ORCHESTRATOR] === WAVE %d/%d === agents=%s", wave_idx + 1, len(waves), [a.name for a in wave])

            self.emit(
                "orchestrator_wave",
                wave=wave_idx + 1,
                wave_total=len(waves),
                agents=[a.name for a in wave],
            )

            results = await asyncio.gather(
                *(a.run(ctx) for a in wave),
                return_exceptions=False,
            )
            for r in results:
                out.results[r.agent_name] = r
                out.findings.extend(r.findings)
                out.new_docs.extend(r.new_docs)
                logger.info("[ORCHESTRATOR] Agent %s finished | status=%s | findings=%d | new_docs=%d",
                            r.agent_name, r.status, len(r.findings), len(r.new_docs))

        out.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("[ORCHESTRATOR] ALL WAVES COMPLETE | total_findings=%d | total_new_docs=%d | elapsed_ms=%d",
                    len(out.findings), len(out.new_docs), out.elapsed_ms)
        self.emit("orchestrator_done", **out.to_dict())
        return out
