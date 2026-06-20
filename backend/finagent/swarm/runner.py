"""Runner that executes a SubTask: grounded specialist + skill-prompt reasoning.

Two layers per subtask:
  1. Grounding — run the mapped deterministic specialist (fast, source-backed
     structured findings + fresh docs). This is the factual floor.
  2. Reasoning — run the skill's own system prompt through the LLM over those
     grounded findings to produce analytical claims. This is what makes each
     subtask a real, objective-adaptive agent rather than a static formatter,
     and it is what finally *executes* the skill registry's prompts/intent.

Layer 2 is bounded (single call, cheap tier, short budget) and never fatal —
if it fails the grounded findings still flow through. Agents with no
deterministic equivalent (e.g. causal_war_gamer) are reasoning-only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from finagent.swarm.models import SubTask, SubTaskResult, SwarmContext
from finagent.swarm.skills import get_skill_registry

logger = logging.getLogger("finagent.swarm.runner")


# skill id -> deterministic specialist class providing the grounded floor.
def _legacy_map() -> dict[str, Any]:
    from finagent.agents.specialists.financials import FinancialsAgent
    from finagent.agents.specialists.governance import GovernanceAgent
    from finagent.agents.specialists.risk import RiskAgent
    from finagent.agents.specialists.valuation import ValuationAgent
    from finagent.agents.specialists.competitor import CompetitorAgent
    from finagent.agents.specialists.news import NewsAgent
    from finagent.agents.specialists.macro import MacroAgent

    return {
        "financials_analyst": FinancialsAgent,
        "governance_forensics": GovernanceAgent,
        "risk_redflags": RiskAgent,
        "valuation_modeler": ValuationAgent,
        "competitor_moat": CompetitorAgent,
        "news_sentiment": NewsAgent,
        "macro_sector": MacroAgent,
    }


# Finding.kind buckets the synthesis layer understands.
_KIND_FOR_SKILL: dict[str, str] = {
    "financials_analyst": "financial",
    "valuation_modeler": "financial",
    "governance_forensics": "governance",
    "risk_redflags": "risk",
    "competitor_moat": "competitor",
    "news_sentiment": "news",
    "macro_sector": "macro",
    "causal_war_gamer": "risk",
}


def _agent_llm_enabled() -> bool:
    return os.environ.get("FINAGENT_SWARM_LLM_AGENTS", "1") == "1"


def _build_subagent_context(task: SubTask, ctx: SwarmContext):
    from finagent.agents.base import SubAgentContext
    from finagent.synthesis import EnrichmentBundle

    return SubAgentContext(
        target=ctx.target,
        canonical_label=ctx.target,
        objective=task.objective,
        bundle=ctx.extra.get("bundle") or EnrichmentBundle(),
        seed_docs=ctx.extra.get("seed_docs") or [],
        session_id=ctx.session_id,
        emit=ctx.emit,
        deadline_ms=task.budget_ms,
        resolved_entity=ctx.resolved_entity,
        ikg_bundle=ctx.extra.get("ikg_bundle"),
        portfolio_symbols=ctx.portfolio_symbols,
        user_email=ctx.user_email,
        tenant_id=ctx.tenant_id,
    )


def _findings_digest(findings: list, limit: int = 12) -> str:
    lines = []
    for f in findings[:limit]:
        head = getattr(f, "headline", "") or ""
        detail = getattr(f, "detail", "") or ""
        conf = getattr(f, "confidence", "") or ""
        lines.append(f"- [{conf}] {head}: {detail}".strip())
    return "\n".join(lines) if lines else "(no grounded findings yet)"


async def _llm_reason(skill, task: SubTask, ctx: SwarmContext, grounded: list) -> list:
    """Run the skill's system prompt over grounded findings -> extra Findings."""
    from finagent.agents.base import Finding
    from finagent.swarm.llm import swarm_chat

    kind = _KIND_FOR_SKILL.get(task.agent_id, "macro")
    user = (
        f"Target: {ctx.target}\n"
        f"Objective: {task.objective}\n\n"
        f"Grounded evidence already gathered:\n{_findings_digest(grounded)}\n\n"
        "Using ONLY the evidence above plus widely-known context, return JSON "
        '{\"claims\": [{\"headline\": str, \"detail\": str, \"confidence\": '
        '\"HIGH\"|\"MEDIUM\"|\"LOW\"}]}. Produce 3-6 analytical, non-redundant '
        "claims that interpret the evidence (trends, implications, risks, "
        "comparisons). Do not invent specific numbers that are not supported. "
        "No buy/sell/hold or price-target language."
    )
    try:
        content = await asyncio.wait_for(
            swarm_chat(
                skill.system_prompt,
                user,
                complexity="simple",
                json_mode=True,
                max_tokens=900,
            ),
            timeout=max(8.0, min(task.budget_ms / 1000.0, 25.0)),
        )
        data = json.loads(content or "{}")
    except Exception as exc:
        logger.warning("[RUNNER] LLM reasoning failed for %s: %s", task.agent_id, exc)
        return []

    out: list = []
    for item in (data.get("claims") or [])[:6]:
        headline = (item.get("headline") or "").strip()
        if not headline:
            continue
        out.append(
            Finding(
                agent=task.agent_id,
                kind=kind,
                headline=headline,
                detail=(item.get("detail") or "").strip(),
                confidence=(item.get("confidence") or "MEDIUM").upper(),
                evidence=[],
                metrics={"source": "swarm_llm_reasoning"},
            )
        )
    return out


async def run_subtask_with_skill(task: SubTask, ctx: SwarmContext) -> SubTaskResult:
    """Execute a SubTask: grounded specialist + skill-prompt reasoning."""
    registry = get_skill_registry()
    skill = registry.get(task.agent_id)
    if skill is None:
        return SubTaskResult(
            task_id=task.task_id,
            agent_id=task.agent_id,
            status="skipped",
            error=f"Unknown skill: {task.agent_id}",
        )

    # The document producer runs after synthesis (DocumentAgent), not here.
    if task.agent_id == "document_producer":
        return SubTaskResult(
            task_id=task.task_id,
            agent_id=task.agent_id,
            status="ok",
            findings=[],
            extra={"deferred": "document_agent"},
        )

    sub_ctx = _build_subagent_context(task, ctx)
    legacy_map = _legacy_map()
    cls = legacy_map.get(task.agent_id)

    grounded_findings: list = []
    grounded_claims: list = []
    new_docs: list = []
    status = "ok"
    error = None
    elapsed_ms = 0

    if cls is not None:
        agent = cls()
        try:
            # Use .run() (not .execute()) so preconditions, per-agent timeout,
            # and subagent_started/done SSE events fire.
            result = await asyncio.wait_for(
                agent.run(sub_ctx),
                timeout=task.budget_ms / 1000.0 + 2.0,
            )
            grounded_findings = list(result.findings)
            grounded_claims = list(result.claims or [])
            new_docs = list(result.new_docs or [])
            status = result.status
            error = result.error
            elapsed_ms = result.elapsed_ms
        except Exception as exc:
            logger.exception("[RUNNER] grounded specialist %s failed", task.agent_id)
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"

    # Layer 2: skill-prompt LLM reasoning (also the only output for
    # reasoning-only skills like causal_war_gamer that have no specialist).
    reasoned: list = []
    if _agent_llm_enabled():
        reasoned = await _llm_reason(skill, task, ctx, grounded_findings)

    all_findings = grounded_findings + reasoned
    if all_findings:
        status = "ok"
    elif status == "ok":
        status = "partial"

    return SubTaskResult(
        task_id=task.task_id,
        agent_id=task.agent_id,
        status=status,
        findings=[f.to_dict() for f in all_findings],
        claims=[c.to_dict() for c in grounded_claims] if grounded_claims else [],
        elapsed_ms=elapsed_ms,
        error=error,
        # Raw objects for the strong-model synthesis pass (charts/tables/memo).
        extra={"raw_findings": all_findings, "raw_docs": new_docs},
    )


__all__ = ["run_subtask_with_skill"]
