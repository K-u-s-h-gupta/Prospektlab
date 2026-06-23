"""Swarm-based research sessions: new standard (compressed deep) and deep modes.

This module replaces the legacy single-pipeline run_agent flow for standard and
deep modes with a parallel, blackboard-driven, accuracy-guaranteed swarm. Chat
mode continues to use the legacy lightweight path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from finagent.accuracy.layer import AccuracyLayer
from finagent.agents.base import SubAgentContext
from finagent.agents.specialists.accounting import AccountingAgent
from finagent.agents.specialists.competitor import CompetitorAgent
from finagent.agents.specialists.financials import FinancialsAgent
from finagent.agents.specialists.governance import GovernanceAgent
from finagent.agents.specialists.macro import MacroAgent
from finagent.agents.specialists.news import NewsAgent
from finagent.agents.specialists.risk import RiskAgent
from finagent.agents.specialists.valuation import ValuationAgent
from finagent.canvas.models import CanvasClaim, CanvasSection, CanvasSource, InteractiveResearchCanvas, SwarmTaskStatus
from finagent.canvas.store import CanvasStore
from finagent.events import BUS
from finagent.geo import resolve_entity
from finagent.ikg.service import get_ikg_service
from finagent.runtime_provider import resolve_openai_config
from finagent.synthesis import EnrichmentBundle, SynthesisResult, synthesize_memo
from finagent.swarm import EvidenceBlackboard, SubTask, SwarmContext, SwarmOrchestrator
from finagent.tools.data import (
    fetch_india_snapshot,
    fetch_news,
    fetch_sebi_filing,
    fetch_shareholding_pattern,
    fetch_yahoo_quote,
    get_usd_inr,
)
from finagent.tools.mcp.ikg_toolkit import IKGToolKit, get_ikg_toolkit
from finagent.tools.web.scraper import ScrapedDoc

logger = logging.getLogger("finagent.swarm_research")


class SwarmResearchConfig:
    """Configuration for a swarm research session."""

    def __init__(
        self,
        session_id: str | None = None,
        max_wall_seconds: float = 180.0,
        enable_canvas: bool = True,
        enable_accuracy_layer: bool = True,
        max_swarm_tasks: int = 300,
        max_swarm_concurrency: int = 15,
        enable_ikg: bool = True,
        user_email: str | None = None,
        tenant_id: str | None = None,
        portfolio_symbols: list[str] | None = None,
        peer_targets: list[str] | None = None,
        output_mode: str | None = None,
    ) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.max_wall_seconds = max_wall_seconds
        self.enable_canvas = enable_canvas
        self.enable_accuracy_layer = enable_accuracy_layer
        self.max_swarm_tasks = max_swarm_tasks
        self.max_swarm_concurrency = max_swarm_concurrency
        self.enable_ikg = enable_ikg
        self.user_email = user_email
        self.tenant_id = tenant_id
        self.portfolio_symbols = portfolio_symbols or []
        # Comparison support: peer entities to enrich + force comparison output.
        self.peer_targets = peer_targets or []
        self.output_mode = output_mode


async def _load_enrichment_and_ikg(
    target: str,
    session_id: str,
    cfg: SwarmResearchConfig,
    emit: Callable[..., None],
) -> tuple[EnrichmentBundle, dict, Any]:
    """Load market data, news, and IKG bundle in parallel."""
    emit("phase", phase="enrich", note="Loading enrichment and IKG data in parallel")

    entity = resolve_entity(target)
    ikg_toolkit = get_ikg_toolkit()
    # Yahoo needs the exchange-qualified symbol (e.g. "TCS.NS"); the bare NSE
    # label ("TCS") resolves to an unrelated US penny stock and poisons the
    # enrichment bundle with garbage price/margins. India fetches use the NSE
    # label. News uses the human-readable name for relevance.
    _yahoo_sym = entity.yahoo_ticker or (
        f"{entity.ticker_label}.NS" if getattr(entity, "country_code", "") == "IN" else entity.ticker_label
    )
    _news_query = entity.canonical_name or entity.ticker_label

    async def load_yahoo():
        try:
            return await fetch_yahoo_quote(_yahoo_sym)
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] Yahoo fetch failed: %s", exc)
            return None

    async def load_india():
        try:
            return await fetch_india_snapshot(entity.ticker_label)
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] India snapshot failed: %s", exc)
            return None

    async def load_news():
        try:
            return await fetch_news(_news_query)
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] News fetch failed: %s", exc)
            return []

    async def load_sebi():
        try:
            return await fetch_sebi_filing(entity.ticker_label)
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] SEBI fetch failed: %s", exc)
            return None

    async def load_shp():
        try:
            return await fetch_shareholding_pattern(entity.ticker_label)
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] SHP fetch failed: %s", exc)
            return None

    async def load_fx():
        try:
            return await get_usd_inr()
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] FX fetch failed: %s", exc)
            return None

    async def load_ikg():
        if not cfg.enable_ikg:
            return {}
        try:
            # Try to resolve CIN first
            resolved = await ikg_toolkit.company_bundle(identifier=entity.ticker_label, depth="deep")
            if resolved.get("status") == "ok":
                return resolved
            return {}
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] IKG bundle failed: %s", exc)
            return {}

    yahoo, india, news, sebi, shp, fx, ikg = await asyncio.gather(
        load_yahoo(), load_india(), load_news(), load_sebi(), load_shp(), load_fx(), load_ikg()
    )

    bundle = EnrichmentBundle(
        yahoo=yahoo,
        india_snap=india,
        news=news or [],
        sebi_filing=sebi,
        shareholding=shp,
        fx=fx,
        ikg=ikg,
    )
    emit("phase", phase="enrich", note="Enrichment and IKG loaded")
    return bundle, ikg, entity


def _build_subagent_context(
    target: str,
    objective: str,
    bundle: EnrichmentBundle,
    session_id: str,
    entity: Any,
    ikg: dict,
    cfg: SwarmResearchConfig,
    emit: Callable[..., None],
) -> SubAgentContext:
    """Build a SubAgentContext for legacy agent compatibility."""
    from finagent.ikg.service import IKGCompanyBundle
    ikg_bundle = None
    try:
        if ikg:
            ikg_bundle = IKGCompanyBundle(**ikg)
    except Exception:
        pass

    return SubAgentContext(
        target=target,
        canonical_label=entity.ticker_label if entity else target,
        objective=objective,
        bundle=bundle,
        seed_docs=[],
        session_id=session_id,
        emit=emit,
        deadline_ms=30_000,
        resolved_entity=entity,
        ikg_bundle=ikg_bundle,
        portfolio_symbols=cfg.portfolio_symbols,
    )


async def _run_agent_bucket(
    agents: list[Any],
    ctx: SubAgentContext,
    domain: str,
    blackboard: EvidenceBlackboard,
) -> None:
    """Run a bucket of legacy agents in parallel and ingest into blackboard."""
    # .run() (not .execute()) so preconditions + subagent SSE events fire.
    results = await asyncio.gather(*[agent.run(ctx) for agent in agents], return_exceptions=True)
    for agent, result in zip(agents, results):
        if isinstance(result, Exception):
            logger.warning("[SWARM_RESEARCH] %s failed in %s bucket: %s", agent.name, domain, result)
            continue
        try:
            result.agent_name = agent.name
            blackboard.add_subtask_result(_legacy_result_to_subtask_result(result))
        except Exception as exc:
            logger.warning("[SWARM_RESEARCH] failed to ingest %s results: %s", agent.name, exc)


def _legacy_result_to_subtask_result(result: Any) -> Any:
    """Convert legacy AgentTaskResult to SubTaskResult, preserving raw objects."""
    from finagent.swarm.models import SubTaskResult
    return SubTaskResult(
        task_id=result.agent_name,
        agent_id=result.agent_name,
        status=result.status,
        findings=[f.to_dict() for f in result.findings],
        claims=[c.to_dict() for c in result.claims] if result.claims else [],
        elapsed_ms=result.elapsed_ms,
        error=result.error,
        # Raw Finding objects + docs for the strong-model synthesis pass.
        extra={"raw_findings": list(result.findings), "raw_docs": list(result.new_docs or [])},
    )


def _to_canvas_source(s: Any, idx: int) -> CanvasSource:
    """Normalise a blackboard claim source into a CanvasSource.

    Deterministic specialists carry `evidence` as a list of URL *strings*,
    while reasoned/news findings carry dicts. Treating every source as a dict
    crashed `_synthesize_canvas` with "'str' object has no attribute 'get'"
    once grounded findings actually started flowing.
    """
    if isinstance(s, str):
        return CanvasSource(source_id=s or f"src-{idx}", source_type="url", title="", url=s)
    if isinstance(s, dict):
        url = s.get("url", "")
        return CanvasSource(
            source_id=url or f"src-{idx}",
            source_type=s.get("source_type", s.get("source", "unknown")),
            title=s.get("title", ""),
            url=url,
        )
    return CanvasSource(source_id=f"src-{idx}", source_type="unknown", title="", url=str(s or ""))


async def _synthesize_canvas(
    target: str,
    objective: str,
    blackboard: EvidenceBlackboard,
    cfg: SwarmResearchConfig,
    emit: Callable[..., None],
) -> InteractiveResearchCanvas:
    """Synthesize the blackboard into a canvas and a memo fallback."""
    canvas = InteractiveResearchCanvas(
        session_id=cfg.session_id,
        query=objective,
        target=target,
        status="synthesizing",
        current_phase="synthesize",
    )

    # Map domains to section titles
    domain_sections = {
        "financials": "Financial Analysis",
        "valuation": "Valuation",
        "governance": "Governance & Forensics",
        "risk": "Risks & Red Flags",
        "macro": "Macro & Sector Overlay",
        "news": "News & Sentiment",
        "competitors": "Competitive Landscape",
        "sentiment": "Sentiment",
        "scenarios": "Scenario Analysis",
    }

    for domain, title in domain_sections.items():
        claims = blackboard.list_claims(domain)
        if not claims:
            continue
        section = canvas.add_section(title)
        for claim in claims:
            section.claims.append(CanvasClaim(
                claim_id=claim.claim_id,
                text=claim.text,
                agent=claim.agent,
                confidence=claim.confidence,
                verified=claim.verified,
                sources=[_to_canvas_source(s, i) for i, s in enumerate(claim.sources)],
                metrics=claim.metrics,
                uncertainty_note=claim.uncertainty_note,
                contradiction_id=claim.contradiction_id,
            ))
        section.summary = f"{len(section.claims)} claims, {sum(1 for c in section.claims if c.confidence == 'HIGH')} high-confidence"

    # Generate memo fallback from the canvas
    memo_lines = [f"# Research: {target}\n\n"]
    for section in canvas.sections:
        memo_lines.append(f"## {section.title}\n")
        for claim in section.claims:
            badge = f"[{claim.confidence}]"
            memo_lines.append(f"- {badge} {claim.text}")
        memo_lines.append("")
    canvas.memo_md = "\n".join(memo_lines)

    canvas.status = "done"
    canvas.current_phase = "done"

    # Save memo fallback to the standard memos directory
    try:
        from finagent.paths import finagent_data_path
        memos_dir = finagent_data_path("memos")
        memos_dir.mkdir(parents=True, exist_ok=True)
        (memos_dir / f"{cfg.session_id}.md").write_text(canvas.memo_md, encoding="utf-8")
    except Exception:
        logger.exception("[SWARM_RESEARCH] failed to save memo fallback")

    # Save canvas
    if cfg.enable_canvas:
        CanvasStore().save(canvas)

    emit("canvas_update", canvas=canvas.to_dict())
    return canvas


async def _run_real_synthesis(
    target: str,
    objective: str,
    blackboard: EvidenceBlackboard,
    bundle: EnrichmentBundle,
    entity: Any,
    cfg: SwarmResearchConfig,
    emit: Callable[..., None],
    *,
    response_depth: str,
    deep: bool,
    timeout_s: float,
) -> SynthesisResult | None:
    """Run the strong-model synthesis over the blackboard's raw findings.

    Reuses the proven synthesize_memo engine so the swarm gets real prose,
    charts, tables, metric cards, citation grounding, and token streaming —
    instead of a bullet-list concatenation. Returns None if no LLM provider is
    configured (caller falls back to the canvas bullet memo).
    """
    from finagent.state.checkpoint import empty_checkpoint

    findings = list(blackboard.raw_findings)
    docs = list(blackboard.raw_docs)
    if not findings and not docs and not bundle.has_any():
        return None

    def _on_token(chunk: str) -> None:
        emit("memo_token", chunk=chunk)

    synth_model = (
        (os.getenv("FINAGENT_SYNTH_MODEL_STRONG") if deep else None)
        or os.getenv("FINAGENT_SYNTH_MODEL")
        or "gpt-5.4-mini"
    )
    emit("phase", phase="synthesis", note="Composing grounded research answer")
    try:
        synthesis = await synthesize_memo(
            target,
            objective,
            docs,
            empty_checkpoint(),
            timeout_s=timeout_s,
            conflicts=[],
            on_token=_on_token,
            enrichment=bundle,
            synth_model=synth_model,
            output_mode=cfg.output_mode,
            response_depth=response_depth,
            entity=entity,
            specialist_findings=findings,
            session_id=cfg.session_id,
            user_email=cfg.user_email,
            is_deep_lite=False,
            peer_targets=cfg.peer_targets or None,
        )
    except Exception as exc:
        logger.warning("[SWARM_RESEARCH] real synthesis failed, falling back to canvas memo: %s", exc)
        return None

    # Persist the real memo (overwrites the canvas fallback written earlier).
    try:
        from finagent.paths import finagent_data_path
        memos_dir = finagent_data_path("memos")
        memos_dir.mkdir(parents=True, exist_ok=True)
        (memos_dir / f"{cfg.session_id}.md").write_text(synthesis.memo, encoding="utf-8")
    except Exception:
        logger.exception("[SWARM_RESEARCH] failed to persist synthesized memo")
    return synthesis


def _emit_final(
    emit: Callable[..., None],
    target: str,
    canvas: InteractiveResearchCanvas,
    synthesis: SynthesisResult | None,
    response_depth: str,
    elapsed_ms: int,
) -> None:
    """Emit the memo + final events, preferring the real synthesis output."""
    if synthesis is not None:
        memo_text = (synthesis.memo or "").strip()
        rich = synthesis.rich or {
            "title": f"Research: {target}",
            "markdown_body": memo_text,
        }
        via = synthesis.via
    else:
        memo_text = (canvas.memo_md or "").strip()
        rich = {
            "title": f"Research: {target}",
            "markdown_body": memo_text,
            "charts": [],
            "tables": [],
            "metric_cards": [],
            "sections": [
                {"title": s.title, "summary": s.summary, "claim_count": len(s.claims)}
                for s in canvas.sections
            ],
        }
        via = "swarm_canvas"

    memo_preview = memo_text[:2400]
    emit(
        "memo",
        target=target,
        memo=memo_text,
        preview=memo_preview,
        via=via,
        elapsed_ms=elapsed_ms,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    emit(
        "final",
        target=target,
        canonical=target,
        output_mode="deep_research_report",
        response_depth=response_depth,
        memo=memo_text,
        memo_preview=memo_preview,
        elapsed_ms=elapsed_ms,
        quality_score=None,
        rich=rich,
        canvas=canvas.to_dict(),
    )


async def run_standard_v2_research_session(
    target: str,
    objective: str,
    *,
    cfg: SwarmResearchConfig | None = None,
) -> InteractiveResearchCanvas:
    """New standard mode: compressed deep research with parallel evidence buckets."""
    cfg = cfg or SwarmResearchConfig(max_wall_seconds=90.0)
    session_id = cfg.session_id
    emit = lambda event_type, **kwargs: BUS.emit(session_id, event_type, **kwargs)
    started_at = time.perf_counter()


    emit("phase", phase="standard_v2", note="Starting compressed deep research")

    # 1. Load enrichment and IKG in parallel
    bundle, ikg, entity = await _load_enrichment_and_ikg(target, session_id, cfg, emit)

    blackboard = EvidenceBlackboard(session_id)
    ctx = _build_subagent_context(target, objective, bundle, session_id, entity, ikg, cfg, emit)

    # 2. Run 3 parallel buckets
    emit("phase", phase="swarm", note="Running 3 parallel evidence buckets")

    bucket_a = [FinancialsAgent(), ValuationAgent()]
    bucket_b = [GovernanceAgent(), RiskAgent(), CompetitorAgent()]
    bucket_c = [NewsAgent(), MacroAgent()]

    await asyncio.gather(
        _run_agent_bucket(bucket_a, ctx, "financials", blackboard),
        _run_agent_bucket(bucket_b, ctx, "governance", blackboard),
        _run_agent_bucket(bucket_c, ctx, "news", blackboard),
    )

    # 3. Accuracy layer
    if cfg.enable_accuracy_layer:
        emit("phase", phase="verify", note="Running accuracy verification")
        accuracy = AccuracyLayer(blackboard).run()
        emit("accuracy_report", report=accuracy.to_dict())

    # 4. Build the UI canvas (also writes a fallback memo to disk)
    canvas = await _synthesize_canvas(target, objective, blackboard, cfg, emit)

    # 5. Real strong-model synthesis (prose + charts + tables + streaming)
    synthesis = await _run_real_synthesis(
        target, objective, blackboard, bundle, entity, cfg, emit,
        response_depth="standard", deep=False,
        timeout_s=min(max(20.0, cfg.max_wall_seconds * 0.5), 40.0),
    )

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    _emit_final(emit, target, canvas, synthesis, "standard", elapsed_ms)
    emit("done", message="Standard v2 research complete")
    return canvas


async def run_deep_swarm_research_session(
    target: str,
    objective: str,
    *,
    cfg: SwarmResearchConfig | None = None,
) -> InteractiveResearchCanvas:
    """New deep mode: Kimi-style dynamic swarm up to 300 sub-agents."""
    cfg = cfg or SwarmResearchConfig(max_swarm_tasks=300, max_swarm_concurrency=20, max_wall_seconds=300.0)
    session_id = cfg.session_id
    emit = lambda event_type, **kwargs: BUS.emit(session_id, event_type, **kwargs)

    emit("phase", phase="deep_swarm", note=f"Starting deep swarm (max {cfg.max_swarm_tasks} agents)")

    # 1. Load enrichment and IKG in parallel
    bundle, ikg, entity = await _load_enrichment_and_ikg(target, session_id, cfg, emit)

    # 2. Build swarm context
    swarm_ctx = SwarmContext(
        session_id=session_id,
        target=target,
        raw_query=objective,
        objective=objective,
        resolved_entity=entity.__dict__ if entity else None,
        blackboard=EvidenceBlackboard(session_id),
        emit=emit,
        user_email=cfg.user_email,
        tenant_id=cfg.tenant_id,
        portfolio_symbols=cfg.portfolio_symbols,
        extra={"bundle": bundle, "ikg_bundle": ikg},
    )

    # 3. Run swarm
    orchestrator = SwarmOrchestrator(
        max_concurrency=cfg.max_swarm_concurrency,
        max_tasks=cfg.max_swarm_tasks,
        max_wall_seconds=cfg.max_wall_seconds,
        emit=emit,
    )
    blackboard, stats = await orchestrator.run(swarm_ctx)

    emit("swarm_stats", stats=stats.to_dict())

    # 4. Accuracy layer
    if cfg.enable_accuracy_layer:
        emit("phase", phase="verify", note="Running accuracy verification")
        accuracy = AccuracyLayer(blackboard).run()
        emit("accuracy_report", report=accuracy.to_dict())

    # 5. Build the UI canvas (also writes a fallback memo to disk)
    canvas = await _synthesize_canvas(target, objective, blackboard, cfg, emit)

    # 6. Real strong-model synthesis (deep report: prose + charts + tables)
    synthesis = await _run_real_synthesis(
        target, objective, blackboard, bundle, entity, cfg, emit,
        response_depth="deep", deep=True,
        timeout_s=min(max(40.0, cfg.max_wall_seconds * 0.3), 90.0),
    )

    _emit_final(emit, target, canvas, synthesis, "deep", stats.elapsed_ms)
    emit("done", message="Deep swarm research complete")
    return canvas


__all__ = [
    "SwarmResearchConfig",
    "run_standard_v2_research_session",
    "run_deep_swarm_research_session",
]
