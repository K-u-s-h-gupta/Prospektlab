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


def _reason_complexity() -> str:
    """Model tier for the per-agent reasoning layer.

    This layer *is* the swarm's analytical intelligence (it interprets the
    grounded floor into claims). "simple" routes to the cheapest model, which
    caps answer quality. Default to "moderate"; override per-deployment via
    FINAGENT_SWARM_REASON_COMPLEXITY (simple|moderate|complex).
    """
    val = (os.environ.get("FINAGENT_SWARM_REASON_COMPLEXITY") or "moderate").strip().lower()
    return val if val in {"simple", "moderate", "complex"} else "moderate"


def _build_subagent_context(task: SubTask, ctx: SwarmContext):
    from finagent.agents.base import SubAgentContext
    from finagent.synthesis import EnrichmentBundle

    # NOTE: SubAgentContext has no user_email/tenant_id fields — passing them
    # here raised TypeError and crashed EVERY grounded specialist in the deep
    # swarm (the swarm fell back to bundle-only synthesis with no specialist
    # findings). resolved_entity must be the ResolvedEntity object the
    # specialists expect, not the dict the swarm context stores.
    from finagent.geo.entity_resolver import ResolvedEntity

    resolved = ctx.resolved_entity
    if isinstance(resolved, dict):
        try:
            resolved = ResolvedEntity(**resolved)
        except Exception:
            resolved = None

    return SubAgentContext(
        target=ctx.target,
        canonical_label=ctx.target,
        objective=task.objective,
        bundle=ctx.extra.get("bundle") or EnrichmentBundle(),
        seed_docs=ctx.extra.get("seed_docs") or [],
        session_id=ctx.session_id,
        emit=ctx.emit,
        deadline_ms=task.budget_ms,
        resolved_entity=resolved,
        ikg_bundle=ctx.extra.get("ikg_bundle"),
        portfolio_symbols=ctx.portfolio_symbols,
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
                complexity=_reason_complexity(),
                json_mode=True,
                max_tokens=900,
            ),
            timeout=max(8.0, min(task.budget_ms / 1000.0, 25.0)),
        )
        from finagent.swarm.llm import loads_lenient
        data = loads_lenient(content)
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


async def _grounded_once(task: SubTask, ctx: SwarmContext, sub_ctx, cls) -> tuple:
    """Run the deterministic specialist once per skill per swarm session.

    A Kimi-style deep plan fans many subtasks onto the same skill (e.g. 8
    distinct financials angles). The deterministic specialists, however, ignore
    the per-task objective and read only the shared enrichment/IKG bundle — so
    re-running them per subtask produces N identical grounded findings and (for
    the 5 web-bound specialists) N redundant search passes. We memoise the
    grounded floor per skill behind a per-skill lock: the first caller produces
    it, later callers reuse it.

    Returns (findings, claims, docs, status, error, elapsed_ms, is_producer).
    Only the producer should emit the grounded floor downstream; reuse tasks
    carry it as reasoning context but must not re-add it to the blackboard.
    """
    cache: dict = ctx.extra.setdefault("_grounded_cache", {})
    locks: dict = ctx.extra.setdefault("_grounded_locks", {})
    lock = locks.setdefault(task.agent_id, asyncio.Lock())
    async with lock:
        cached = cache.get(task.agent_id)
        if cached is not None:
            return (cached["findings"], cached["claims"], cached["docs"],
                    cached["status"], cached["error"], cached["elapsed_ms"], False)
        findings: list = []
        claims: list = []
        docs: list = []
        status, error, elapsed_ms = "ok", None, 0
        try:
            # .run() (not .execute()) so preconditions, per-agent timeout, and
            # subagent_started/done SSE events fire.
            result = await asyncio.wait_for(
                cls().run(sub_ctx),
                timeout=task.budget_ms / 1000.0 + 2.0,
            )
            findings = list(result.findings)
            claims = list(result.claims or [])
            docs = list(result.new_docs or [])
            status = result.status
            error = result.error
            elapsed_ms = result.elapsed_ms
        except Exception as exc:
            logger.exception("[RUNNER] grounded specialist %s failed", task.agent_id)
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        cache[task.agent_id] = {
            "findings": findings, "claims": claims, "docs": docs,
            "status": status, "error": error, "elapsed_ms": elapsed_ms,
        }
        return findings, claims, docs, status, error, elapsed_ms, True


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
    cls = _legacy_map().get(task.agent_id)

    grounded_findings: list = []
    grounded_claims: list = []
    new_docs: list = []
    status = "ok"
    error = None
    elapsed_ms = 0
    is_producer = True

    if cls is not None:
        (grounded_findings, grounded_claims, new_docs,
         status, error, elapsed_ms, is_producer) = await _grounded_once(task, ctx, sub_ctx, cls)

    # Layer 2: per-task skill-prompt LLM reasoning. This is objective-specific,
    # so it is what makes many subtasks of one skill diverge instead of merely
    # duplicating the shared grounded floor. Also the only output for
    # reasoning-only skills (e.g. causal_war_gamer) that have no specialist.
    reasoned: list = []
    if _agent_llm_enabled():
        reasoned = await _llm_reason(skill, task, ctx, grounded_findings)

    # Only the task that produced the grounded floor emits it downstream; reuse
    # tasks carried it as reasoning context but contribute reasoned claims only,
    # keeping the blackboard + synthesis input free of N duplicate copies.
    contributed_findings = (grounded_findings if is_producer else []) + reasoned
    contributed_claims = grounded_claims if is_producer else []

    if contributed_findings:
        status = "ok"
    elif not is_producer:
        # A duplicate of an already-grounded skill that added no new reasoning
        # contributes nothing — skip it rather than fail (no pointless retry).
        status = "skipped"
    elif status == "ok":
        status = "partial"

    return SubTaskResult(
        task_id=task.task_id,
        agent_id=task.agent_id,
        status=status,
        findings=[f.to_dict() for f in contributed_findings],
        claims=[c.to_dict() for c in contributed_claims] if contributed_claims else [],
        elapsed_ms=elapsed_ms,
        error=error,
        # Raw objects for the strong-model synthesis pass (charts/tables/memo).
        extra={"raw_findings": contributed_findings, "raw_docs": new_docs if is_producer else []},
    )


__all__ = ["run_subtask_with_skill"]
