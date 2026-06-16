"""Core agent loop.

Pipeline:
1. identify   — resolve target to SEC ticker / CIK if it's a US-listed entity
2. enrichment — pull authoritative JSON APIs in parallel (SEC EDGAR companyfacts,
                Yahoo Finance chart, Wikipedia REST summary)
3. breadth-survey — layered DuckDuckGo search across 4 angles
4. deep-dive — iterative targeted second-pass queries to fill gaps
5. analysis — cross-source conflict detection, viral scoring
6. synthesis — OpenAI / template memo using the *facts*, not just excerpts

CANARY: portfolio_context injection code is present in this file.
"""

from __future__ import annotations

import sys
print("[RUN_AGENT_LOADED]", __file__, "via", sys.executable, file=sys.stderr)

import asyncio
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from datetime import datetime, timezone

from finagent.accuracy_validator import AccuracyValidator, Claim, Source
from finagent.agent.reflection import ReflectionLoop
from finagent.agents import Orchestrator, SubAgentContext, Verifier, detect_blind_spots
from finagent.agents.context_loaders import load_agent_context
from finagent.agents.specialists import default_roster
from finagent.analysis.conflicts import detect_conflicts
from finagent.analysis.quality import score_research
from finagent.events import BUS
from finagent.geo import resolve_entity
from finagent.geo.query_localizer import localize_search_query
from finagent.geo.source_policy import preferred_domains_for_entity
from finagent.harness import Harness, HarnessConfig, compress_context_stub
from finagent.harness.context_manager import should_compress
from finagent.ikg.service import get_ikg_service, metric_observations_from_bundle
from finagent.memory import MemoryFact, get_memory_store
from finagent.memory.store import normalize_target
from finagent.paths import finagent_data_path
from finagent.playbooks import apply_playbook_to_queries, maybe_promote_playbook, retrieve_playbook
from finagent.prompt_builder import default_system_prompt
from finagent.retrieval import build_retrieval_plan
from finagent.research_planner import ResearchPlan, build_default_plan
from finagent.router import route_objective
from finagent.output.intent_classifier import classify_output_mode, normalize_depth
from finagent.output.contracts import ResponseDepth
from finagent.state.checkpoint import Checkpoint, StepResult, empty_checkpoint
from finagent.state.citation_log import Citation
from finagent.synthesis import EnrichmentBundle, SynthesisResult, synthesize_memo
from finagent.tools.data import (
    FilingNarrative,
    FxRate,
    HNStory,
    IndiaCompanySnapshot,
    NewsItem,
    RedditPost,
    SEBIFiling,
    SECCompanySnapshot,
    SECTimeSeries,
    StockTwitsSnapshot,
    WikipediaSummary,
    YahooQuote,
    fetch_company_snapshot,
    fetch_filing_narrative,
    fetch_india_snapshot,
    fetch_sebi_filing,
    fetch_shareholding_pattern,
    fetch_news,
    fetch_stocktwits,
    fetch_wikipedia_summary,
    fetch_yahoo_quote,
    get_usd_inr,
    search_hackernews,
    search_reddit,
)
from finagent.tools.social.viral_verifier import score_text_for_pump_and_dump
from finagent.tools.web.http_fetcher import aclose_shared_client
from finagent.tools.web.scraper import ScrapedDoc, search_layered, search_web

logger = logging.getLogger("finagent.run_agent")

# Global semaphore to cap concurrent outbound enrichment calls (prevents FD exhaustion)
_ENRICHMENT_SEMAPHORE = asyncio.Semaphore(4)


def _finite_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _has_number(value) -> bool:
    return _finite_float(value) is not None


def _format_inr_short(value: float | int | None) -> str:
    n = _finite_float(value)
    if n is None:
        return "n/a"
    sign = "-" if n < 0 else ""
    n_abs = abs(n)
    if n_abs >= 10_000_000:
        return f"{sign}₹{n_abs / 10_000_000:.2f} Cr"
    if n_abs >= 100_000:
        return f"{sign}₹{n_abs / 100_000:.2f} L"
    return f"{sign}₹{n_abs:,.0f}"


def _format_pct(value: float | int | None, *, already_percent: bool = False) -> str:
    n = _finite_float(value)
    if n is None:
        return "n/a"
    if not already_percent:
        n *= 100
    return f"{n:+.2f}%"


def _normalize_series(prices: list[float] | None, max_points: int = 40) -> tuple[list[int], list[float]]:
    if not prices:
        return [], []
    clean = []
    for p in prices:
        n = _finite_float(p)
        if n is not None and n > 0:
            clean.append(n)
    if not clean:
        return [], []
    step = max(1, len(clean) // max_points)
    sampled = clean[::step]
    if sampled[-1] != clean[-1]:
        sampled.append(clean[-1])
    base = sampled[0] or 1.0
    return list(range(1, len(sampled) + 1)), [round((p / base) * 100, 2) for p in sampled]


def _build_portfolio_rich_payload(portfolio: dict, *, benchmark: str = "NIFTY50") -> dict:
    risk = portfolio.get("risk") or {}
    sector_breakdown = portfolio.get("sector_breakdown") or {}
    kind_breakdown = portfolio.get("kind_breakdown") or {}
    positions = sorted(portfolio.get("positions") or [], key=lambda p: p.get("market_value") or 0, reverse=True)
    history = portfolio.get("history") or {}
    port_hist = (history.get("portfolio") or {}).get("prices") or []
    bench_hist = (history.get("benchmark") or {}).get("prices") or []
    x_idx, port_series = _normalize_series(port_hist)
    _, bench_series = _normalize_series(bench_hist, max_points=len(x_idx) or 40)
    if x_idx and bench_series:
        min_len = min(len(x_idx), len(port_series), len(bench_series))
        x_idx = x_idx[-min_len:]
        port_series = port_series[-min_len:]
        bench_series = bench_series[-min_len:]

    charts = []
    if sector_breakdown:
        sector_items = [(k, _finite_float(v)) for k, v in sector_breakdown.items()]
        sector_items = [(k, v) for k, v in sector_items if v is not None and v > 0]
    else:
        sector_items = []
    if sector_items:
        charts.append({
            "kind": "donut",
            "title": "Sector Allocation",
            "valueKind": "percent",
            "x_labels": [k for k, _ in sector_items],
            "series": [{
                "name": "Weight",
                "values": [round(v * 100, 2) for _, v in sector_items],
                "unit": "%",
            }],
        })
    if kind_breakdown:
        kind_items = [(k, _finite_float(v)) for k, v in kind_breakdown.items()]
        kind_items = [(k, v) for k, v in kind_items if v is not None and v > 0]
    else:
        kind_items = []
    if kind_items:
        charts.append({
            "kind": "donut",
            "title": "Asset Allocation",
            "valueKind": "percent",
            "x_labels": [k for k, _ in kind_items],
            "series": [{
                "name": "Weight",
                "values": [round(v * 100, 2) for _, v in kind_items],
                "unit": "%",
            }],
        })
    if x_idx and port_series and bench_series:
        charts.append({
            "kind": "line",
            "title": f"Portfolio vs {benchmark}",
            "y_unit": "indexed",
            "x_labels": [str(i) for i in x_idx],
            "series": [
                {"name": "Portfolio", "values": port_series, "unit": "index"},
                {"name": benchmark, "values": bench_series, "unit": "index"},
            ],
        })

    tables = []
    holding_rows = []
    for p in positions[:8]:
        market_value = _finite_float(p.get("market_value"))
        weight = _finite_float(p.get("weight"))
        pnl_pct = _finite_float(p.get("unrealized_pnl_pct"))
        if market_value is None and weight is None and pnl_pct is None:
            continue
        holding_rows.append([
            p.get("name") or p.get("symbol") or "-",
            _format_inr_short(market_value),
            f"{(weight or 0) * 100:.2f}%" if weight is not None else "n/a",
            _format_pct(pnl_pct),
        ])
    if holding_rows:
        tables.append({
            "title": "Top Holdings",
            "headers": ["Holding", "Value", "Weight", "P&L"],
            "rows": holding_rows,
        })

    risk_rows = []
    if _has_number(risk.get("hhi")):
        risk_rows.append(["HHI concentration", f"{_finite_float(risk.get('hhi')):.4f}"])
    if _has_number(risk.get("beta_vs_nifty")):
        risk_rows.append([f"Beta vs {benchmark}", f"{_finite_float(risk.get('beta_vs_nifty')):.2f}"])
    if _has_number(risk.get("annualized_volatility_pct")):
        risk_rows.append(["Annualized volatility", f"{_finite_float(risk.get('annualized_volatility_pct')):.2f}%"])
    if _has_number(risk.get("max_drawdown_pct")):
        risk_rows.append(["Max drawdown", f"{_finite_float(risk.get('max_drawdown_pct')):.2f}%"])
    if risk_rows:
        tables.append({
            "title": "Risk Metrics",
            "headers": ["Metric", "Value"],
            "rows": risk_rows,
        })

    metric_cards = []
    if _has_number(portfolio.get("total_market_value")):
        metric_cards.append({"label": "Total Market Value", "value": _format_inr_short(portfolio.get("total_market_value")), "change_type": "neutral"})
    if _has_number(portfolio.get("unrealized_pnl")):
        pnl = _finite_float(portfolio.get("unrealized_pnl")) or 0.0
        card = {"label": "Unrealized P&L", "value": _format_inr_short(pnl), "change_type": "positive" if pnl >= 0 else "negative"}
        if _has_number(portfolio.get("unrealized_pnl_pct")):
            card["change"] = _format_pct(portfolio.get("unrealized_pnl_pct"))
        metric_cards.append(card)
    if _has_number(risk.get("hhi")):
        hhi = _finite_float(risk.get("hhi")) or 0.0
        metric_cards.append({"label": "HHI Concentration", "value": f"{hhi:.4f}", "change_type": "negative" if hhi >= 0.25 else "positive"})
    if _has_number(risk.get("annualized_volatility_pct")):
        metric_cards.append({"label": "Annualized Volatility", "value": f"{_finite_float(risk.get('annualized_volatility_pct')):.2f}%", "change_type": "neutral"})
    if _has_number(risk.get("max_drawdown_pct")):
        metric_cards.append({"label": "Max Drawdown", "value": f"{_finite_float(risk.get('max_drawdown_pct')):.2f}%", "change_type": "negative"})

    return {
        "mode": "portfolio",
        "title": "Portfolio Mirror Analytics",
        "subtitle": f"{portfolio.get('count', 0)} synchronized holding(s) vs {benchmark}",
        "metric_cards": metric_cards,
        "charts": charts,
        "tables": tables,
        "data_sources": [{"label": "position_mirrors", "url": None}, {"label": "portfolio analytics", "url": None}],
        "disclaimer": "Portfolio analytics are computed from the synchronized local mirror. Not investment advice.",
    }


def _build_portfolio_memo(portfolio: dict, *, benchmark: str = "NIFTY50") -> str:
    risk = portfolio.get("risk") or {}
    sectors = sorted((portfolio.get("sector_breakdown") or {}).items(), key=lambda x: x[1], reverse=True)
    positions = sorted(portfolio.get("positions") or [], key=lambda p: p.get("market_value") or 0, reverse=True)

    lines = [
        "## Portfolio Performance Snapshot",
        (
            f"Your synchronized portfolio is valued at **{_format_inr_short(portfolio.get('total_market_value'))}** "
            f"with unrealized P&L of **{_format_inr_short(portfolio.get('unrealized_pnl'))} "
            f"({_format_pct(portfolio.get('unrealized_pnl_pct'))})**.")
    ]
    risk_parts = []
    if _has_number(risk.get("hhi")):
        risk_parts.append(f"HHI concentration is **{_finite_float(risk.get('hhi')):.4f}**")
    if _has_number(risk.get("beta_vs_nifty")):
        risk_parts.append(f"beta vs {benchmark} is **{_finite_float(risk.get('beta_vs_nifty')):.2f}**")
    if _has_number(risk.get("annualized_volatility_pct")):
        risk_parts.append(f"annualized volatility is **{_finite_float(risk.get('annualized_volatility_pct')):.2f}%**")
    if _has_number(risk.get("max_drawdown_pct")):
        risk_parts.append(f"max drawdown is **{_finite_float(risk.get('max_drawdown_pct')):.2f}%**")
    if risk_parts:
        lines.extend(["## Risk Read", ", ".join(risk_parts) + "."])
    else:
        lines.extend(["## Risk Read", "Risk metrics were not available from the synchronized analytics payload for this run."])
    if sectors:
        sector_bits = ", ".join(
            f"{name}: {weight_num * 100:.1f}%"
            for name, weight in sectors[:5]
            if (weight_num := _finite_float(weight)) is not None
        )
        if sector_bits:
            lines.extend(["## Sector Allocation", f"Largest sector weights are {sector_bits}."])
    if positions:
        holding_bits = ", ".join(
            f"{p.get('name') or p.get('symbol')} ({weight_num * 100:.1f}%)"
            for p in positions[:5]
            if (weight_num := _finite_float(p.get("weight"))) is not None
        )
        if holding_bits:
            lines.extend(["## Top Holdings", f"Top holdings by market value are {holding_bits}."])
    lines.extend([
        "## Bottom Line",
        (
            "The charts and tables below are generated from backend portfolio analytics, not from model-estimated values. "
            "Use the concentration, drawdown, and sector weights as the primary decision anchors."
        ),
    ])
    return "\n\n".join(lines)


@dataclass
class AgentLoopConfig:
    max_steps: int = 40
    enable_scraping: bool = True
    enable_enrichment: bool = True
    enable_deep_dive: bool = True
    session_id: str | None = None
    # When the caller doesn't specify max_steps, we auto-pick based on
    # how complex the objective text looks (see _auto_max_steps).
    auto_depth: bool = True
    # ── Memory ──
    enable_memory: bool = True
    memory_recall_limit: int = 12
    # ── Self-improvement (Hermes-style reflection) ──
    enable_reflection: bool = True
    reflection_max_rounds: int = 5
    quality_threshold: float = 75.0
    reflection_per_query_limit: int = 6
    reflection_per_query_timeout: float = 25.0
    reflection_max_new_docs: int = 80
    reflection_max_queries_per_round: int = 4
    reflection_wall_clock_seconds: float | None = 45.0
    reflection_early_accept_margin: float = 2.0
    reflection_min_score_gain: float = 0.75
    breadth_search_timeout: float = 90.0
    followup_search_timeout: float = 45.0
    news_timeout: float = 25.0
    # ── Multi-agent orchestration ──
    enable_multi_agent: bool = True
    agent_deadline_ms: int = 45_000
    # Blind-spot pass: auto-dispatches follow-up queries for missing topics
    enable_blindspot: bool = True
    blindspot_max_queries: int = 8
    blindspot_per_query_timeout: float = 18.0
    # ── Synthesis ──
    synth_model: str | None = None
    response_depth: str = "chat"
    output_mode: str | None = None
    emit_memo: bool = True
    close_bus_on_finish: bool = True
    chat_history: list[dict[str, str]] | None = None
    # ── User isolation for per-user memory recall / persist ──
    user_email: str | None = None
    tenant_id: str | None = None
    # ── Comparison: when set, synthesis fetches rich enrichment for peers ──
    peer_targets: list[str] = field(default_factory=list)
    fast_mode: bool = False


STANDARD_PRESET = dict(
    max_steps=12,
    auto_depth=False,
    enable_reflection=False,
    reflection_max_rounds=0,
    enable_multi_agent=False,
    enable_blindspot=False,
    enable_deep_dive=False,
    fast_mode=True,
    response_depth="standard",
    breadth_search_timeout=12.0,
    followup_search_timeout=8.0,
    news_timeout=6.0,
    agent_deadline_ms=12_000,
)

STANDARD_PLUS_PRESET = dict(
    max_steps=18,
    auto_depth=False,
    enable_reflection=True,
    reflection_max_rounds=1,
    reflection_per_query_limit=6,
    reflection_max_queries_per_round=4,
    reflection_wall_clock_seconds=30.0,
    enable_multi_agent=True,
    enable_blindspot=True,
    blindspot_max_queries=8,
    enable_deep_dive=True,
    fast_mode=False,
    response_depth="standard",
    breadth_search_timeout=20.0,
    followup_search_timeout=12.0,
    news_timeout=10.0,
    agent_deadline_ms=15_000,
)


def _auto_max_steps(objective: str, base: int) -> int:
    """Scale total step budget by objective complexity. Defaults err big --
    research quality matters more than wall-clock here."""
    obj = (objective or "").lower()
    complexity = 1.0
    if any(k in obj for k in ("deep", "comprehensive", "exhaustive", "investigative", "due diligence")):
        complexity += 0.8
    if any(k in obj for k in ("risk", "fraud", "controversy", "lawsuit", "investigation")):
        complexity += 0.3
    if any(k in obj for k in ("compare", "vs", "peer", "competitor")):
        complexity += 0.3
    # Chat-mode callers pass a smaller base; keep those runs responsive while
    # preserving the larger floor for standard/deep research sessions.
    floor = 24 if base < 40 else 40
    return max(floor, int(base * complexity))


def _objective_needs_fresh_web(objective: str) -> bool:
    text = (objective or "").lower()
    freshness_markers = (
        "latest",
        "today",
        "recent",
        "current",
        "breaking",
        "news",
        "headline",
        "update",
        "this week",
        "this month",
        "announcement",
        "announced",
        "appointed",
        "appointment",
        "resigned",
        "resignation",
        "stepped down",
        "ceased",
        "cessation",
        "board change",
        "ceo",
        "cfo",
        "kmp",
        "order",
        "penalty",
        "settlement",
        "show cause",
    )
    if any(marker in text for marker in freshness_markers):
        return True
    ownership_change_markers = (
        "increased promoter",
        "decreased promoter",
        "promoter change",
        "change in promoter",
        "pledge change",
        "changed shareholding",
    )
    return any(marker in text for marker in ownership_change_markers)


def _ikg_grounding_is_sufficient(bundle: EnrichmentBundle | None) -> bool:
    ikg = getattr(bundle, "ikg", None)
    if ikg is None or ikg.status not in {"ok", "partial"}:
        return False
    if ikg.confidence < 0.6:
        return False
    if not getattr(ikg, "source_refs", None):
        return False
    needed = ("governance", "ownership", "risk", "financials")
    available = sum(1 for key in needed if ikg.coverage.get(key) != "missing")
    return available >= 3


def _ikg_can_answer_objective(bundle: EnrichmentBundle | None, objective: str, output_mode: str) -> bool:
    ikg = getattr(bundle, "ikg", None)
    if ikg is None or ikg.status not in {"ok", "partial"}:
        return False
    coverage = getattr(ikg, "coverage", {}) or {}
    if coverage.get("identity") == "missing":
        return False
    lower = (objective or "").lower()
    ownership_terms = ("shareholding", "shareholding pattern", "promoter", "pledge", "ownership", "fii", "dii")
    governance_terms = ("governance", "board", "director", "auditor", "management")
    wants_ownership = any(term in lower for term in ownership_terms)
    wants_governance = any(term in lower for term in governance_terms)
    if output_mode not in {"direct_answer", "conversational_chat"} and not (wants_ownership or wants_governance):
        return False
    if wants_ownership and coverage.get("ownership") != "missing":
        return True
    if wants_governance and coverage.get("governance") != "missing":
        return True
    return False


def _tier_to_kind(tier: int) -> str:
    if tier <= 2:
        return "primary"
    if tier <= 6:
        return "secondary"
    return "tertiary"


def _emit_source_event(session_id: str, doc: ScrapedDoc, step: int, confidence: str, viral, kind: str) -> None:
    BUS.emit(
        session_id,
        "source",
        url=doc.final_url,
        title=doc.title,
        domain=doc.domain,
        tier=doc.tier,
        kind=kind,
        confidence=confidence,
        viral_score=viral.score,
        viral_flags=viral.flags,
        blocked=doc.blocked_reason,
        excerpt=doc.excerpt[:400],
        step=step,
    )


async def _run_enrichment(
    target: str,
    session_id: str,
    *,
    entity,
    news_timeout: float = 25.0,
    fast_mode: bool = False,
) -> EnrichmentBundle:
    """Fan-out to Yahoo, Wikipedia, and Indian sources. None failures are non-fatal."""
    BUS.emit(session_id, "phase", phase="enrichment", note="Pulling authoritative APIs (NSE/BSE, Yahoo Finance, Moneycontrol)")

    async def _yahoo(ticker: str | None) -> YahooQuote | None:
        if not ticker:
            return None
        BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="running", note=f"Fetching market and fundamentals data for {ticker}")
        try:
            q = await asyncio.wait_for(
                fetch_yahoo_quote(ticker),
                timeout=(8.0 if fast_mode else 10.0),
            )
            has_financials = bool(q and (q.financial_metrics or q.annual_revenue or q.annual_net_income))
            if q is None or (q.price is None and not has_financials):
                BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="warning", note="No quote or fundamentals (rate-limited or unlisted)")
                return None
            chg = f"{q.change_pct:+.2f}%" if q.change_pct is not None else "n/a"
            metric_note = ""
            if has_financials:
                metric_note = f", {len(q.financial_metrics)} metrics, rev years {len(q.annual_revenue)}, ni years {len(q.annual_net_income)}"
            BUS.emit(
                session_id,
                "agent_task",
                task="Yahoo Finance",
                status="done",
                note=(
                    f"{(q.currency + ' ') if q.currency and q.price is not None else ''}"
                    f"{f'{q.price:,.2f}' if q.price is not None else 'quote unavailable'} "
                    f"({chg}) on {q.exchange or 'exchange'}{metric_note}"
                ),
            )
            return q
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="warning", note="Timed out (>10s)")
            return None
        except Exception as exc:
            logger.warning("Yahoo enrichment failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="error", note=str(exc))
            return None

    async def _wiki(canonical: str | None) -> WikipediaSummary | None:
        """Try several candidate titles, ranked by likelihood of being the
        company article. Reject obvious wrong matches (court cases, fruit
        species, surname pages, etc.)."""
        candidates: list[str] = []

        def _strip_suffixes(name: str) -> str:
            n = name.strip()
            for suf in (" Inc.", " Inc", " Corp.", " Corp", " Corporation", " Company", " Co.", " plc", " Ltd.", " Ltd", " Holdings", " Group", " Limited"):
                if n.lower().endswith(suf.lower()):
                    n = n[: -len(suf)].rstrip(" ,.")
                    break
            return n

        # For Indian short-ticker aliases (e.g. "TCS"), try the full company
        # name FIRST so Wikipedia resolves to the company, not a tech acronym.
        _INDIA_FULL_NAMES: dict[str, list[str]] = {
            "tcs": ["Tata Consultancy Services"],
            "hdfcbank": ["HDFC Bank"],
            "sbin": ["State Bank of India"],
            "lici": ["Life Insurance Corporation of India"],
            "wipro": ["Wipro"],
            "infy": ["Infosys"],
            "reliance": ["Reliance Industries"],
            "itc": ["ITC Limited"],
            "hul": ["Hindustan Unilever"],
            "ongc": ["Oil and Natural Gas Corporation"],
            "ntpc": ["NTPC Limited"],
            "bhel": ["Bharat Heavy Electricals Limited"],
            "bel": ["Bharat Electronics Limited"],
            "sail": ["Steel Authority of India"],
            "gail": ["GAIL India"],
            "hpcl": ["Hindustan Petroleum"],
            "ioc": ["Indian Oil Corporation"],
            "bpcl": ["Bharat Petroleum"],
            "nmdc": ["NMDC Limited"],
            "pfc": ["Power Finance Corporation"],
            "pnb": ["Punjab National Bank"],
            "sbi": ["State Bank of India"],
            "hul": ["Hindustan Unilever"],
            "mrf": ["MRF Limited"],
            "m&m": ["Mahindra and Mahindra"],
            "lt": ["Larsen and Toubro"],
        }
        canonical_lower = (canonical or "").lower().strip()
        target_lower = target.lower().strip()
        for alias_key, full_names in _INDIA_FULL_NAMES.items():
            if canonical_lower == alias_key or target_lower == alias_key:
                for fn in full_names:
                    if fn not in candidates:
                        candidates.append(fn)

        if canonical:
            # 1) Bare company name (best for big names: "Microsoft", "Apple Inc." -> "Apple")
            bare = _strip_suffixes(canonical)
            if bare:
                candidates.append(bare)
            # 2) Disambiguation hint
            if bare:
                candidates.append(f"{bare} (company)")
            # 3) Full canonical
            candidates.append(canonical)
        # 4) User-supplied target + disambiguators
        bare_target = _strip_suffixes(target)
        if bare_target and bare_target not in candidates:
            candidates.append(bare_target)
        if bare_target:
            candidates.append(f"{bare_target} (company)")
        BUS.emit(
            session_id,
            "agent_task",
            task="Wikipedia",
            status="running",
            note=f"Trying {', '.join(candidates[:3])}",
        )
        wiki_started = time.monotonic()
        wiki_total_timeout_s = 8.0 if not fast_mode else 4.0
        wiki_per_candidate_timeout_s = 2.5 if not fast_mode else 1.5
        wiki_max_candidates = 3 if not fast_mode else 2

        def _is_bad_match(summary: WikipediaSummary) -> bool:
            desc = (summary.description or "").lower()
            title = (summary.title or "").lower()
            extract_snippet = (summary.extract or "").lower()[:400]
            bad_substrings = (
                "fruit",
                "given name",
                "surname",
                "disambiguation",
                "court case",
                " v. ",
                "vs.",
                "supreme court",
                "village in",
                "town in",
                "wikimedia disambiguation",
                # Tech/OS articles that share names with Indian company tickers
                "unix shell",
                "command shell",
                "programming language",
                "operating system kernel",
                "computer program",
                "shell scripting",
                "backward compatible",
                "open-source software",
                # Geographic non-company
                "river in",
                "mountain in",
                # Food / snack / recipe articles (e.g. "bhel puri" != BHEL the company)
                "savoury snack",
                "street food",
                "puffed rice",
                "chaat",
                "tamarind chutney",
                "gujarati cuisine",
                "indian cuisine",
                "recipe",
                "type of food",
                "type of dish",
                "food dish",
                "alcoholic beverage",
            )
            bad_extract = (
                "unix shell",
                "backward compatible with the c shell",
                "is a unix",
                "tcsh is",
                "shell scripting language",
                # Food items
                "puffed rice",
                "bhel puri",
                "tamarind chutney",
                "savoury snack",
                "street food in",
                "is a type of food",
            )
            if any(b in desc for b in bad_substrings) or any(b in title for b in bad_substrings):
                return True
            if any(b in extract_snippet for b in bad_extract):
                return True
            if extract_snippet.strip().startswith("may refer to"):
                return True
            return False

        for cand in candidates[:wiki_max_candidates]:
            if (time.monotonic() - wiki_started) >= wiki_total_timeout_s:
                logger.info("Wikipedia enrichment budget exhausted after %.1fs", time.monotonic() - wiki_started)
                break
            try:
                w = await asyncio.wait_for(
                    fetch_wikipedia_summary(cand),
                    timeout=wiki_per_candidate_timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning("Wikipedia enrichment timed out for %r", cand)
                continue
            except Exception as exc:
                logger.warning("Wikipedia enrichment failed for %r: %s", cand, exc)
                continue
            if not w:
                continue
            if _is_bad_match(w):
                logger.info("Wikipedia rejected %r -> %r (%r)", cand, w.title, w.description)
                continue
            BUS.emit(
                session_id,
                "agent_task",
                task="Wikipedia",
                status="done",
                note=f"{w.title} — {w.description or ''}",
            )
            return w
        BUS.emit(session_id, "agent_task", task="Wikipedia", status="warning", note="No matching company article")
        return None

    async def _fx() -> FxRate | None:
        BUS.emit(session_id, "agent_task", task="FX (USD/INR)", status="running", note="Fetching live USD-INR")
        try:
            r = await asyncio.wait_for(
                get_usd_inr(),
                timeout=(4.0 if fast_mode else 6.0),
            )
            BUS.emit(
                session_id,
                "agent_task",
                task="FX (USD/INR)",
                status="done",
                note=f"1 USD = ₹{r.rate:.4f} ({r.source})",
            )
            return r
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="FX (USD/INR)", status="warning", note="Timed out (>6s)")
            return None
        except Exception as exc:
            logger.warning("FX fetch failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="FX (USD/INR)", status="warning", note=str(exc))
            return None

    async def _reddit() -> list[RedditPost]:
        query = canonical_name or entity.search_label or target
        BUS.emit(session_id, "agent_task", task="Reddit", status="running", note=f"r/wsb + 4 subs for {query!r}")
        try:
            posts = await asyncio.wait_for(search_reddit(query), timeout=20.0)
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="Reddit", status="warning", note="Timed out (>20s)")
            return []
        except Exception as exc:
            logger.warning("reddit fetch failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="Reddit", status="error", note=str(exc))
            return []
        if not posts:
            BUS.emit(session_id, "agent_task", task="Reddit", status="warning", note="No qualifying posts")
            return []
        sent = {"bullish": 0, "bearish": 0, "hype": 0, "neutral": 0}
        for p in posts:
            sent[p.sentiment] = sent.get(p.sentiment, 0) + 1
        BUS.emit(
            session_id,
            "agent_task",
            task="Reddit",
            status="done",
            note=f"{len(posts)} posts — bullish {sent['bullish']} / bearish {sent['bearish']} / hype {sent['hype']}",
        )
        return posts

    async def _hn() -> list[HNStory]:
        query = canonical_name or entity.search_label or target
        BUS.emit(session_id, "agent_task", task="Hacker News", status="running", note=f"Algolia search for {query!r}")
        try:
            stories = await asyncio.wait_for(search_hackernews(query), timeout=15.0)
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="Hacker News", status="warning", note="Timed out (>15s)")
            return []
        except Exception as exc:
            logger.warning("HN fetch failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="Hacker News", status="error", note=str(exc))
            return []
        if not stories:
            BUS.emit(session_id, "agent_task", task="Hacker News", status="warning", note="No story matches")
            return []
        BUS.emit(
            session_id,
            "agent_task",
            task="Hacker News",
            status="done",
            note=f"{len(stories)} stories (top {stories[0].points} pts)",
        )
        return stories

    async def _stocktwits(ticker_: str | None) -> StockTwitsSnapshot | None:
        if not ticker_:
            return None
        BUS.emit(session_id, "agent_task", task="StockTwits", status="running", note=f"${ticker_} stream")
        try:
            snap = await asyncio.wait_for(fetch_stocktwits(ticker_), timeout=15.0)
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="StockTwits", status="warning", note="Timed out (>15s)")
            return None
        except Exception as exc:
            logger.warning("stocktwits fetch failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="StockTwits", status="error", note=str(exc))
            return None
        if not snap:
            BUS.emit(session_id, "agent_task", task="StockTwits", status="warning", note="Stream empty or rate-limited")
            return None
        BUS.emit(
            session_id,
            "agent_task",
            task="StockTwits",
            status="done",
            note=f"{snap.bullish} bull / {snap.bearish} bear / {snap.unrated} unrated — net {snap.net_sentiment}",
        )
        return snap

    async def _news() -> list[NewsItem]:
        query = canonical_name or entity.search_label or target
        BUS.emit(session_id, "agent_task", task="News headlines", status="running", note=f"Google News RSS for {query!r}")
        try:
            items = await asyncio.wait_for(
                fetch_news(
                    query,
                    hl=entity.profile.news_hl,
                    gl=entity.profile.news_gl,
                    ceid=entity.profile.news_ceid,
                ),
                timeout=news_timeout,
            )
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="News headlines", status="warning", note=f"Timed out (>{news_timeout:.0f}s)")
            return []
        except Exception as exc:
            logger.warning("news fetch failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="News headlines", status="error", note=str(exc))
            return []
        if not items:
            BUS.emit(session_id, "agent_task", task="News headlines", status="warning", note="No headlines returned")
            return []
        BUS.emit(
            session_id,
            "agent_task",
            task="News headlines",
            status="done",
            note=f"{len(items)} headlines (top: {items[0].source})",
        )
        return items

    # ── India-specific data fetchers ─────────────────────────────────────────
    # These are only called for IN-country entities; they run in parallel with
    # the main gather below to avoid blocking the Yahoo/Wikipedia fetches.

    _is_india = (entity.country_code == "IN")
    # NSE symbol is the short ticker label (e.g. "TCS", "INFY")
    _nse_sym: str = (entity.ticker_label or target.upper().split()[0])[:12]

    async def _india_snap() -> IndiaCompanySnapshot | None:
        if not _is_india:
            return None
        BUS.emit(session_id, "agent_task", task="NSE/Screener", status="running",
                 note=f"Fetching India fundamentals for {_nse_sym}")
        try:
            snap = await asyncio.wait_for(
                fetch_india_snapshot(_nse_sym),
                timeout=(5.0 if fast_mode else 8.0),
            )
            if snap:
                BUS.emit(session_id, "agent_task", task="NSE/Screener", status="done",
                         note=f"{snap.company_name or _nse_sym} — {len(snap.metrics)} metrics via {snap.source}")
            else:
                BUS.emit(session_id, "agent_task", task="NSE/Screener", status="warning",
                         note=f"No fundamentals data returned for {_nse_sym}")
            return snap
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="NSE/Screener", status="warning", note="Timed out (>8s)")
            return None
        except Exception as exc:
            logger.warning("India snapshot fetch failed for %s: %s", _nse_sym, exc)
            BUS.emit(session_id, "agent_task", task="NSE/Screener", status="error", note=str(exc))
            return None

    async def _sebi_filing_fetch() -> SEBIFiling | None:
        if not _is_india:
            return None
        BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="running",
                 note=f"Fetching analysis filing for {_nse_sym}")
        try:
            filing_data = await asyncio.wait_for(
                fetch_sebi_filing(_nse_sym),
                timeout=(5.0 if fast_mode else 8.0),
            )
            if filing_data:
                present = ", ".join(
                    k for k, v in [
                        ("overview", filing_data.business_overview),
                        ("risks", filing_data.risk_factors),
                        ("financials", filing_data.financial_summary),
                        ("MDA", filing_data.management_discussion),
                    ] if v
                )
                BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="done",
                         note=f"Sections: {present or 'none'}")
            else:
                BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="warning",
                         note=f"No analysis sections found for {_nse_sym}")
            return filing_data
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="warning", note="Timed out (>8s)")
            return None
        except Exception as exc:
            logger.warning("SEBI filing fetch failed for %s: %s", _nse_sym, exc)
            BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="error", note=str(exc))
            return None

    async def _shareholding_fetch() -> dict | None:
        if not _is_india:
            return None
        try:
            data = await asyncio.wait_for(
                fetch_shareholding_pattern(_nse_sym),
                timeout=(4.0 if fast_mode else 6.0),
            )
            if data:
                p = data.get("promoter") or 0
                f = data.get("fii") or 0
                d = data.get("dii") or 0
                BUS.emit(session_id, "agent_task", task="Shareholding", status="done",
                         note=f"Promoter {p:.1f}% · FII {f:.1f}% · DII {d:.1f}%")
            return data
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="Shareholding", status="warning", note="Timed out (>6s)")
            return None
        except Exception as exc:
            logger.warning("Shareholding fetch failed for %s: %s", _nse_sym, exc)
            return None

    # ── Derive ticker (best-effort without blocking on SEC) ────────────────
    # SEC snap runs in the parallel gather below, so we derive ticker early
    # from the already-resolved entity. US-only SEC data supplements later.
    if entity.yahoo_ticker:
        ticker: str | None = entity.yahoo_ticker
    elif _is_india and _nse_sym:
        ticker = _nse_sym + ".NS"
    elif target.replace(" ", "").isalpha() and len(target) <= 5:
        ticker = target.upper()
    else:
        ticker = None

    canonical_name = entity.canonical_name

    # ── Parallel fan-out: ALL enrichment ────────────────────
    # Semaphore prevents unbounded outbound connection burst.
    async with _ENRICHMENT_SEMAPHORE:
        if fast_mode:
            (
                india_snap_result,
                shareholding_result,
                yahoo_quote,
                news_items,
            ) = await asyncio.gather(
                _india_snap(),
                _shareholding_fetch(),
                _yahoo(ticker),
                _news(),
                return_exceptions=True,
            )
            sebi_filing_result = None
            wiki = None
            fx = None
        else:
            (
                india_snap_result,
                sebi_filing_result,
                shareholding_result,
                yahoo_quote,
                wiki,
                fx,
                news_items,
            ) = await asyncio.gather(
                _india_snap(),
                _sebi_filing_fetch(),
                _shareholding_fetch(),
                _yahoo(ticker),
                _wiki(canonical_name),
                _fx(),
                _news(),
                return_exceptions=True,
            )

    sec_snap = None
    sec_filing = None

    # Resolve any gather exceptions to None
    def _safe(v):
        return None if isinstance(v, Exception) else v

    india_snap_result   = _safe(india_snap_result)
    sebi_filing_result  = _safe(sebi_filing_result)
    shareholding_result = _safe(shareholding_result)
    yahoo_quote         = _safe(yahoo_quote)
    wiki                = _safe(wiki)
    fx                  = _safe(fx)
    news_items          = _safe(news_items) or []

    # Backfill canonical_name from India snapshot if available
    if india_snap_result and india_snap_result.company_name:
        canonical_name = india_snap_result.company_name

    # India snap is the primary structured data source for Indian companies;
    # sec_snap is used for US companies. The bundle.india_snap field holds both.
    primary_snap: IndiaCompanySnapshot | SECCompanySnapshot | None = (
        india_snap_result or sec_snap
    )
    # sebi_filing takes precedence for India; sec_filing for US
    resolved_filing = sebi_filing_result or sec_filing

    bundle = EnrichmentBundle(
        india_snap=primary_snap,
        sebi_filing=resolved_filing if isinstance(resolved_filing, SEBIFiling) else None,
        shareholding=shareholding_result,
        yahoo=yahoo_quote,
        wikipedia=wiki,
        fx=fx,
        news=news_items,
    )

    BUS.emit(
        session_id,
        "intel",
        sec=_serialize_india_snap(india_snap_result) if _is_india else _serialize_sec(sec_snap),
        yahoo=_serialize_yahoo(yahoo_quote),
        wikipedia=_serialize_wiki(wiki),
        filing=_serialize_filing(sec_filing),
        fx=_serialize_fx(fx),
        news=_serialize_news(news_items),
        india_snap=_serialize_india_snap(india_snap_result),
        shareholding=shareholding_result,
    )
    return bundle


def _serialize_filing(f: FilingNarrative | None) -> dict | None:
    if not f:
        return None
    return {
        "form": f.form,
        "filed_date": f.filed_date,
        "source_url": f.source_url,
        "business": f.business,
        "risk_factors": f.risk_factors,
        "mdna": f.mdna,
    }


def _serialize_india_snap(snap: "IndiaCompanySnapshot | None") -> dict | None:
    """Serialize an IndiaCompanySnapshot for the intel SSE event."""
    if not snap:
        return None
    return {
        "symbol": snap.symbol,
        "isin": snap.isin,
        "name": snap.company_name,
        "exchange": snap.exchange,
        "sector": snap.sector,
        "industry": snap.industry,
        "source": snap.source,
        "source_url": snap.source_url,
        "current_price": snap.current_price,
        "change_pct": snap.change_pct,
        "week_52_high": snap.week_52_high,
        "week_52_low": snap.week_52_low,
        "market_cap_cr": snap.market_cap_cr,
        "pe_ratio": snap.pe_ratio,
        "pb_ratio": snap.pb_ratio,
        "eps": snap.eps,
        "book_value": snap.book_value,
        "dividend_yield": snap.dividend_yield,
        "roe": snap.roe,
        "roce": snap.roce,
        "debt_to_equity": snap.debt_to_equity,
        "current_ratio": snap.current_ratio,
        "promoter_holding": snap.promoter_holding,
        "fii_holding": snap.fii_holding,
        "dii_holding": snap.dii_holding,
        "promoter_pledge_pct": snap.promoter_pledge_pct,
        # Flat metrics dict for easy frontend consumption
        "metrics": snap.metrics,
    }


def _serialize_sec(snap: "SECCompanySnapshot | None") -> dict | None:
    if not snap:
        return None
    # Guard: if this is actually an IndiaCompanySnapshot (back-compat shim),
    # delegate to the India serializer to avoid attribute errors.
    if isinstance(snap, IndiaCompanySnapshot):
        return _serialize_india_snap(snap)
    return {
        "ticker": snap.ticker,
        "name": snap.name,
        "cik": snap.cik,
        "sic_description": snap.sic_description,
        "exchanges": snap.exchanges,
        "metrics": {
            k: {
                "label": m.label,
                "display": m.display_value(),
                "value": m.value,
                "unit": m.unit,
                "end": m.end,
                "fy": m.fy,
                "fp": m.fp,
                "form": m.form,
                "accn": m.accn,
            }
            for k, m in snap.metrics.items()
        },
        "history": {
            k: {
                "concept": s.concept,
                "label": s.label,
                "unit": s.unit,
                "annual": [
                    {"end": p.end, "value": p.value, "fy": p.fy, "fp": p.fp, "form": p.form}
                    for p in s.annual
                ],
                "quarterly": [
                    {"end": p.end, "value": p.value, "fy": p.fy, "fp": p.fp, "form": p.form}
                    for p in s.quarterly
                ],
            }
            for k, s in (snap.history or {}).items()
        },
        "recent_filings": [
            {"form": f.form, "filed": f.filing_date, "report": f.report_date, "url": f.url, "accession": f.accession}
            for f in snap.recent_filings
        ],
    }


def _serialize_news(items: list[NewsItem]) -> list[dict]:
    return [
        {
            "title": n.title,
            "link": n.link,
            "source": n.source,
            "published": n.published,
            "description": n.description,
        }
        for n in items
    ]


def _serialize_yahoo(q: YahooQuote | None) -> dict | None:
    if not q:
        return None
    return {
        "ticker": q.ticker,
        "name": q.name,
        "currency": q.currency,
        "exchange": q.exchange,
        "price": q.price,
        "previous_close": q.previous_close,
        "change_pct": q.change_pct,
        "market_cap": q.market_cap,
        "fifty_two_week_high": q.fifty_two_week_high,
        "fifty_two_week_low": q.fifty_two_week_low,
        "series_dates": q.series_dates,
        "series_closes": q.series_closes,
        "financial_metrics": q.financial_metrics,
        "annual_revenue": q.annual_revenue,
        "annual_revenue_dates": q.annual_revenue_dates,
        "annual_net_income": q.annual_net_income,
        "annual_net_income_dates": q.annual_net_income_dates,
        "business_summary": q.business_summary,
        "source_url": q.source_url,
    }


def _serialize_wiki(w: WikipediaSummary | None) -> dict | None:
    if not w:
        return None
    return {
        "title": w.title,
        "description": w.description,
        "extract": w.extract,
        "url": w.url,
    }


def _serialize_fx(fx: FxRate | None) -> dict | None:
    if not fx:
        return None
    return {"pair": fx.pair, "rate": fx.rate, "source": fx.source, "as_of": fx.as_of}


def _serialize_reddit(posts: list[RedditPost]) -> list[dict]:
    return [
        {
            "subreddit": p.subreddit,
            "title": p.title,
            "score": p.score,
            "num_comments": p.num_comments,
            "sentiment": p.sentiment,
            "created": p.created,
            "permalink": p.permalink,
            "url": p.url,
            "author": p.author,
        }
        for p in posts
    ]


def _serialize_hn(stories: list[HNStory]) -> list[dict]:
    return [
        {
            "title": s.title,
            "url": s.url,
            "hn_url": s.hn_url,
            "points": s.points,
            "num_comments": s.num_comments,
            "author": s.author,
            "created": s.created,
        }
        for s in stories
    ]


def _serialize_stocktwits(snap: StockTwitsSnapshot | None) -> dict | None:
    if not snap:
        return None
    return {
        "ticker": snap.ticker,
        "company": snap.company,
        "bullish": snap.bullish,
        "bearish": snap.bearish,
        "unrated": snap.unrated,
        "net_sentiment": snap.net_sentiment,
        "messages": [
            {
                "user": m.user,
                "body": m.body,
                "sentiment": m.sentiment,
                "created": m.created,
                "likes": m.likes,
            }
            for m in snap.messages[:12]
        ],
    }


def _identify_gaps(docs: list[ScrapedDoc], sec_snap: SECCompanySnapshot | None) -> list[str]:
    """Heuristic gap finder: returns follow-up queries the breadth pass missed."""
    queries: list[str] = []
    domains = {d.domain for d in docs}
    text_blob = " ".join((d.excerpt or "")[:500].lower() for d in docs)
    has_news = any(d.endswith("reuters.com") or d.endswith("wsj.com") or d.endswith("ft.com") or d.endswith("bloomberg.com") for d in domains)
    has_competition = "competit" in text_blob or "market share" in text_blob
    has_risk = "risk" in text_blob or "headwind" in text_blob
    has_analyst = "analyst" in text_blob or "price target" in text_blob or "upgraded" in text_blob

    # Always exercise targeted angles on the second pass.
    if sec_snap and sec_snap.ticker:
        target_label = sec_snap.ticker
    elif sec_snap and sec_snap.name:
        target_label = sec_snap.name
    else:
        target_label = ""

    return queries  # filled in by caller after passing target


_TIER1_NEWS = (
    # Indian tier-1 financial sources
    "economictimes.indiatimes.com", "livemint.com", "business-standard.com",
    "thehindubusinessline.com", "financialexpress.com", "ndtvprofit.com",
    "moneycontrol.com",
    # Global wire services
    "reuters.com", "bloomberg.com", "ft.com",
)


def _build_followup_queries(
    target: str,
    docs: list[ScrapedDoc],
    sec_snap: SECCompanySnapshot | None,
    *,
    round_index: int = 0,
) -> list[str]:
    """Generate India-focused targeted follow-up queries based on what previous passes missed.

    Each round shifts emphasis: round 0 -> coverage gaps, round 1 -> entity
    expansion (competitors, suppliers, customers harvested from earlier docs),
    round 2 -> SEBI/regulatory + concall detail, round 3 -> shareholding/governance.
    """
    canonical = (sec_snap.name if sec_snap else target).strip()
    ticker = (sec_snap.ticker if sec_snap else "").strip()
    industry = sec_snap.sic_description if (sec_snap and sec_snap.sic_description) else ""
    domains = {d.domain for d in docs}
    text_blob = " ".join((d.excerpt or "")[:600].lower() for d in docs)

    # India-aware: strip .NS / .BO suffix for readable queries
    display_ticker = ticker.replace(".NS", "").replace(".BO", "") if ticker else ""

    candidate: list[tuple[str, str]] = []

    if round_index == 0:
        # Check for Indian financial press coverage
        has_india_news = any(
            any(d.endswith(src) for src in _TIER1_NEWS)
            for d in domains
        )
        if not has_india_news:
            candidate.append((f"{canonical} NSE quarterly results earnings moneycontrol", "missing Indian tier-1 news"))
        if "competit" not in text_blob and "market share" not in text_blob:
            if industry:
                candidate.append((f"{canonical} competitors India {industry} market share", "competitive landscape"))
            else:
                candidate.append((f"{canonical} top competitors India market share analysis", "competitive landscape"))
        if "risk" not in text_blob and "headwind" not in text_blob:
            candidate.append((f"{canonical} SEBI risk factors regulatory concerns India", "risk discussion"))
        if "analyst" not in text_blob and "price target" not in text_blob:
            if display_ticker:
                candidate.append((f"{display_ticker} NSE analyst coverage broking report consensus estimate", "analyst coverage"))
            else:
                candidate.append((f"{canonical} analyst coverage consensus estimate NSE India", "analyst coverage"))
        if "guidance" not in text_blob and "forecast" not in text_blob:
            candidate.append((f"{canonical} management guidance revenue outlook FY2026", "forward guidance"))

    elif round_index == 1:
        # Entity expansion: pull capitalised proper nouns from earlier excerpts
        entities = _extract_entities(docs, exclude=(canonical, ticker))[:3]
        for ent in entities:
            candidate.append((f"{ent} vs {canonical} comparison quarterly results India", f"peer deep-dive: {ent}"))
        candidate.append((f"{canonical} concall transcript Q&A management commentary", "concall transcript"))
        if industry:
            candidate.append((f"{industry} India sector outlook FY2026 trends SEBI", "sector outlook"))

    elif round_index == 2:
        # India-specific: insider trading disclosures, bulk/block deals, SEBI actions
        candidate.append((f"{canonical} insider trading disclosure SEBI bulk deal", "insider activity"))
        candidate.append((f"{canonical} SEBI investigation order regulatory action", "regulatory action"))
        candidate.append((f"{canonical} ESG sustainability report controversy India", "ESG & legal"))
        if display_ticker:
            candidate.append((f"{display_ticker} NSE F&O options OI unusual activity", "F&O activity"))

    else:  # round 3+
        # Indian shareholding pattern, FII/DII holdings, promoter pledging
        candidate.append((f"{canonical} shareholding pattern FII DII promoter stake", "institutional ownership"))
        candidate.append((f"{canonical} promoter pledge shares NSE BSE disclosure", "promoter pledging"))
        candidate.append((f"{canonical} capex expansion plan India 2025 2026", "capital allocation"))
        if display_ticker:
            candidate.append((f"{display_ticker} quarterly results beat miss EPS history NSE", "earnings history"))

    return [q for q, _ in candidate][:5]


_ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z&]{2,}(?:\s+[A-Z][a-zA-Z&]{2,}){0,2})\b")


def _extract_entities(docs: list[ScrapedDoc], *, exclude: tuple[str, ...] = ()) -> list[str]:
    """Pull capitalised multi-word entities from doc excerpts. Used to seed
    peer-company queries in the second deep-dive round."""
    exclude_lc = {x.lower() for x in exclude if x}
    counts: dict[str, int] = {}
    blacklist = {
        "United States", "New York", "San Francisco", "Wall Street", "Federal Reserve",
        "Securities Exchange", "Securities Exchange Commission", "Annual Report", "Form",
        "Company", "Inc", "Corp", "Group", "Holdings", "Ltd", "Plc",
    }
    for d in docs:
        if not d.excerpt:
            continue
        for m in _ENTITY_RE.finditer(d.excerpt[:1500]):
            ent = m.group(1).strip()
            if len(ent) < 4 or ent in blacklist or ent.lower() in exclude_lc:
                continue
            # Skip if it's just a single common word
            if " " not in ent and ent.lower() in {"the", "this", "that", "with", "from"}:
                continue
            counts[ent] = counts.get(ent, 0) + 1
    # Rank by frequency, prefer multi-word over single
    ranked = sorted(counts.items(), key=lambda kv: (kv[1] + (1 if " " in kv[0] else 0)), reverse=True)
    return [e for e, _ in ranked[:8]]


async def _process_doc(
    doc: ScrapedDoc,
    step: int,
    cp: Checkpoint,
    harness: Harness,
    validator: AccuracyValidator,
    session_id: str,
    *,
    enrichment_corroborates: bool = False,
) -> None:
    cp.step = step
    viral = score_text_for_pump_and_dump(doc.excerpt, source_domain=doc.domain)
    kind = _tier_to_kind(doc.tier)
    cp.citation_log.append(
        Citation(url=doc.final_url, title=doc.title or doc.domain, date_accessed=cp.timestamp.isoformat(), kind=kind)
    )
    material = doc.tier <= 6 and not doc.blocked_reason and doc.text_len > 200
    # Build the source list the validator expects so it can compute a real
    # confidence rather than always defaulting to LOW with an empty list.
    src_self = Source(
        name=doc.domain,
        tier=doc.tier,
        retrieved_at=datetime.now(timezone.utc),
        is_primary_financial=doc.tier <= 2,
    )
    sources_for_validator = [src_self]
    if enrichment_corroborates:
        # Treat Screener.in data as a corroborating primary-financial source.
        sources_for_validator.append(
            Source(name="screener.in", tier=1, retrieved_at=datetime.now(timezone.utc), is_primary_financial=True)
        )
    try:
        result = validator.validate(
            Claim(text=doc.excerpt[:200], is_material=material),
            sources=sources_for_validator,
            min_sources=harness.settings.min_sources_for_material_claim,
        )
        confidence = result.confidence_level.value
    except Exception:
        confidence = "LOW"
    # Confidence floor: any blocked or empty doc can't be high; any tier-1
    # primary doc with real content should never be LOW.
    if doc.blocked_reason or doc.text_len < 50:
        if confidence == "HIGH":
            confidence = "MEDIUM"
    elif doc.tier <= 2 and confidence == "LOW":
        confidence = "MEDIUM"
    if viral.score >= 5 or (viral.is_social_only and viral.needs_triangulation):
        confidence = viral.confidence_floor
    summary_bits = [f"{doc.domain} (tier {doc.tier})", f"confidence={confidence}", viral.to_marker()]
    if doc.blocked_reason:
        summary_bits.append(f"[BLOCKED: {doc.blocked_reason}]")
    cp.completed_steps.append(StepResult(name=f"step_{step}", summary=" | ".join(summary_bits), ok=not doc.blocked_reason))
    cp.confidence_summary[doc.domain] = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3, "DERIVED": 0.5}.get(confidence, 0.5)
    _emit_source_event(session_id, doc, step, confidence, viral, kind)
    logger.info("Step %d: Processed doc from %s (tier %d) | Title: %r | Confidence: %s | Viral score: %d (flags: %s)",
                step, doc.domain, doc.tier, doc.title[:60] if doc.title else "No Title", confidence, viral.score, viral.flags)
    harness.maybe_persist_checkpoint(step, cp)


async def _persist_session_memory(
    memory_store,
    *,
    session_id: str,
    target: str,
    canonical_label: str,
    bundle: EnrichmentBundle,
    docs: list[ScrapedDoc],
    cp: Checkpoint,
    conflicts: list,
    quality_score: float,
    user_email: str | None = None,
) -> None:
    """Extract durable facts from this run under the canonical target key."""
    new_facts: list[MemoryFact] = []
    sec = bundle.sec
    if sec:
        # Identity fact
        identity_bits = [f"ticker={sec.ticker}", f"cik={sec.cik}", f"name={sec.name}"]
        if sec.sic_description:
            identity_bits.append(f"sic={sec.sic_description}")
        if sec.exchanges:
            identity_bits.append(f"exchanges={'/'.join(sec.exchanges)}")
        new_facts.append(
            MemoryFact(
                target_key=target,
                kind="identity",
                body="; ".join(identity_bits),
                confidence="HIGH",
                source_url=sec.source_url if sec.source_url else f"https://www.screener.in/company/{sec.ticker}/",
                session_id=session_id,
                user_email=user_email,
            )
        )
        # Financial facts from the latest metrics
        for k, m in (sec.metrics or {}).items():
            # m may be a plain dict if the EnrichmentBundle was rehydrated from
            # a JSON/pickle cache rather than freshly constructed as a SECMetric.
            if isinstance(m, dict):
                label = m.get("label", k)
                value = m.get("value", "n/a")
                form  = m.get("form", "n/a")
                end   = m.get("end", "n/a")
                line  = f"{label} = {value} (form {form}, period ending {end})"
            else:
                line = f"{m.label} = {m.display_value()} (form {m.form}, period ending {m.end})"
            new_facts.append(
                MemoryFact(
                    target_key=target,
                    kind="financial",
                    body=line,
                    confidence="HIGH",
                    source_url=sec.source_url if sec.source_url else f"https://www.screener.in/company/{sec.ticker}/",
                    session_id=session_id,
                    user_email=user_email,
                )
            )
    if bundle.filing and getattr(bundle.filing, "risk_factors", None):
        rf = bundle.filing.risk_factors.strip()
        # First ~600 chars of risk factors as a memorable digest
        new_facts.append(
            MemoryFact(
                target_key=target,
                kind="risk",
                body=f"Item 1A digest from {bundle.filing.form} filed {bundle.filing.filed_date}: {rf[:600]}",
                confidence="HIGH",
                source_url=bundle.filing.source_url,
                session_id=session_id,
                user_email=user_email,
            )
        )
    # India snapshot (Screener/NSE) is the primary structured source for Indian
    # listed companies — persist its ratios so they survive to follow-up turns
    # instead of going N/A when live enrichment is later rate-limited.
    india_snap = getattr(bundle, "india_snap", None)
    if india_snap is not None and hasattr(india_snap, "market_cap_cr"):
        s = india_snap
        ratio_bits: list[str] = []
        for label, attr, fmt in (
            ("Market cap", "market_cap_cr", "₹{:,.0f} Cr"),
            ("P/E", "pe_ratio", "{:.2f}x"),
            ("P/B", "pb_ratio", "{:.2f}x"),
            ("ROE", "roe", "{:.1f}%"),
            ("ROCE", "roce", "{:.1f}%"),
            ("EPS", "eps", "₹{:.2f}"),
            ("Book value", "book_value", "₹{:.2f}"),
            ("Div yield", "dividend_yield", "{:.2f}%"),
            ("D/E", "debt_to_equity", "{:.2f}"),
            ("Promoter", "promoter_holding", "{:.1f}%"),
            ("FII", "fii_holding", "{:.1f}%"),
            ("DII", "dii_holding", "{:.1f}%"),
            ("Promoter pledge", "promoter_pledge_pct", "{:.1f}%"),
        ):
            val = getattr(s, attr, None)
            if val is not None:
                try:
                    ratio_bits.append(f"{label} {fmt.format(val)}")
                except Exception:
                    ratio_bits.append(f"{label} {val}")
        if ratio_bits:
            new_facts.append(
                MemoryFact(
                    target_key=target,
                    kind="financial",
                    body=f"India market data ({getattr(s, 'source', 'Screener/NSE')}): " + ", ".join(ratio_bits),
                    confidence="HIGH",
                    source_url=getattr(s, "source_url", None) or f"https://www.screener.in/company/{getattr(s, 'symbol', target)}/",
                    session_id=session_id,
                    user_email=user_email,
                )
            )
    if bundle.yahoo:
        y = bundle.yahoo
        new_facts.append(
            MemoryFact(
                target_key=target,
                kind="market_data",
                body=(
                    f"Last quote ${getattr(y, 'price', 'n/a')} on {getattr(y, 'as_of', '')}, "
                    f"52w {getattr(y, 'low_52w', 'n/a')}–{getattr(y, 'high_52w', 'n/a')}, "
                    f"market cap {getattr(y, 'market_cap', 'n/a')}"
                ),
                confidence="MEDIUM",
                source_url=f"https://finance.yahoo.com/quote/{getattr(y, 'symbol', target)}",
                session_id=session_id,
                user_email=user_email,
            )
        )
    if bundle.news:
        # Top 3 headline events as discrete facts so they're searchable
        for n in bundle.news[:3]:
            # Defensive: handle both Pydantic model objects and raw dicts
            if isinstance(n, dict):
                _n_source = n.get("source", "")
                _n_title = n.get("title", "")
                _n_published = n.get("published", "")
                _n_link = n.get("link") or n.get("url")
            else:
                _n_source = getattr(n, "source", "")
                _n_title = getattr(n, "title", "")
                _n_published = getattr(n, "published", "")
                _n_link = getattr(n, "link", None) or getattr(n, "url", None)
            new_facts.append(
                MemoryFact(
                    target_key=target,
                    kind="news_event",
                    body=f"{_n_source}: {_n_title} ({_n_published})",
                    confidence="MEDIUM",
                    source_url=_n_link,
                    session_id=session_id,
                    user_email=user_email,
                )
            )
    for c in conflicts or []:
        # Defensive: handle both Pydantic model objects and raw dicts
        if isinstance(c, dict):
            _c_metric = c.get("metric", "unknown")
            _c_spread = float(c.get("spread_pct", 0))
            _c_note = c.get("note", "")
        else:
            _c_metric = getattr(c, "metric", "unknown")
            _c_spread = float(getattr(c, "spread_pct", 0))
            _c_note = getattr(c, "note", "") or ""
        new_facts.append(
            MemoryFact(
                target_key=target,
                kind="conflict",
                body=f"Cross-source disagreement on {_c_metric}: spread {_c_spread:.1f}% — {_c_note}",
                confidence="MEDIUM",
                source_url=None,
                session_id=session_id,
                user_email=user_email,
            )
        )
    await memory_store.remember_many(new_facts)

    # Save a one-paragraph summary for "what was this run about?"
    n_docs = len(docs)
    n_domains = len({(d.final_url or d.url or "").split("/")[2] for d in docs if (d.final_url or d.url)})
    n_metrics = len(sec.metrics) if sec else 0
    summary = (
        f"Run for {canonical_label}: ingested {n_docs} docs from {n_domains} domains, "
        f"resolved {n_metrics} SEC metrics, scored {quality_score:.1f}/100 on the coverage rubric. "
        f"{len(conflicts or [])} cross-source conflicts. "
        f"{len(bundle.news or [])} news headlines."
    )
    metrics_dict = {
        "docs": n_docs,
        "domains": n_domains,
        "sec_metrics": n_metrics,
        "conflicts": len(conflicts or []),
        "news": len(bundle.news or []),
    }
    await memory_store.save_session_summary(
        session_id=session_id,
        target_key=target,
        target_display=canonical_label,
        summary=summary,
        metrics=metrics_dict,
        citation_count=len(cp.citation_log),
        quality_score=quality_score,
        user_email=user_email,
    )


async def run_research_session(
    target: str,
    objective: str,
    *,
    plan: ResearchPlan | None = None,
    loop_config: AgentLoopConfig | None = None,
    is_followup: bool = False,
) -> tuple[ResearchPlan, Checkpoint]:
    try:
        from finagent.state.session_context import init_session_context
        init_session_context()
    except ImportError:
        pass
    _ = default_system_prompt()
    pl = plan or build_default_plan(target, objective)
    cfg = loop_config or AgentLoopConfig()
    if cfg.auto_depth:
        cfg.max_steps = _auto_max_steps(objective, cfg.max_steps)
    session_id = cfg.session_id or str(uuid.uuid4())
    loop = asyncio.get_running_loop()

    def _cleanup_on_task_done(_task: asyncio.Task) -> None:
        if cfg.close_bus_on_finish:
            BUS.close(session_id)
        try:
            loop.create_task(aclose_shared_client())
        except RuntimeError:
            pass

    current_task = asyncio.current_task()
    if current_task is not None:
        current_task.add_done_callback(_cleanup_on_task_done)

    harness = Harness(HarnessConfig(session_id=session_id))
    cp = empty_checkpoint()
    validator = AccuracyValidator()
    entity = resolve_entity(target)
    preferred_domains = preferred_domains_for_entity(entity)
    logger.info("Initializing research session | Target: '%s' | Objective: '%s' | Session ID: %s", target, objective, session_id)
    logger.info("Resolved Entity: %s (Country: %s, Ticker: %s, Search Label: %s)",
                entity.canonical_name, entity.country_code, entity.ticker_label, entity.search_label)
    try:
        playbook = retrieve_playbook(geography=entity.country_code, objective=objective)
    except Exception as exc:
        logger.warning("playbook retrieval failed: %s", exc)
        playbook = None
        BUS.emit(session_id, "warning", message=f"playbook retrieval failed: {exc}")
    retrieval_plan = build_retrieval_plan(entity, objective)
    retrieval_plan.breadth_queries = apply_playbook_to_queries(
        retrieval_plan.breadth_queries,
        playbook,
        target_label=(getattr(entity, "search_label", "") or entity.canonical_name or target),
    )
    routing = route_objective(
        objective,
        entity,
        playbook_agents=(playbook.selected_agents if playbook else None),
        has_prior_entity=is_followup,
    )

    response_depth = normalize_depth(cfg.response_depth)

    # Depth policy: chat is intentionally lightweight; standard preserves the
    # bounded research config supplied by the gateway; deep forces every phase.
    if response_depth == ResponseDepth.DEEP:
        cfg.enable_multi_agent = True
        cfg.enable_scraping = True
        cfg.enable_reflection = True
        cfg.enable_blindspot = True
        cfg.enable_deep_dive = True
        cfg.max_steps = min(max(cfg.max_steps, 16), 32)
        cfg.breadth_search_timeout = min(cfg.breadth_search_timeout, 35.0)
        cfg.followup_search_timeout = min(cfg.followup_search_timeout, 15.0)
        cfg.news_timeout = min(cfg.news_timeout, 10.0)
        cfg.agent_deadline_ms = min(cfg.agent_deadline_ms, 18_000)
        cfg.blindspot_max_queries = min(cfg.blindspot_max_queries, 4)
        cfg.blindspot_per_query_timeout = min(cfg.blindspot_per_query_timeout, 8.0)
        # Deep mode: allow up to 3 reflection rounds when adaptive budget permits.
        # The actual rounds run is constrained at runtime by remaining wall-clock.
        cfg.reflection_max_rounds = min(max(cfg.reflection_max_rounds, 3), 3)
        cfg.reflection_per_query_limit = min(cfg.reflection_per_query_limit, 3)
        cfg.reflection_per_query_timeout = min(cfg.reflection_per_query_timeout, 10.0)
        cfg.reflection_max_new_docs = min(cfg.reflection_max_new_docs, 16)
        # Per-round wall budget; total Deep budget set later via adaptive_wall_budget
        cfg.reflection_wall_clock_seconds = max(cfg.reflection_wall_clock_seconds or 30.0, 30.0)
    elif response_depth == ResponseDepth.CHAT:
        cfg.enable_multi_agent = False
        cfg.enable_blindspot = False
        cfg.enable_reflection = False
        cfg.enable_deep_dive = False
        cfg.max_steps = min(cfg.max_steps, 8)
        cfg.breadth_search_timeout = min(cfg.breadth_search_timeout, 10.0)
        cfg.followup_search_timeout = min(cfg.followup_search_timeout, 6.0)
        cfg.news_timeout = min(cfg.news_timeout, 6.0)
        if routing.query_complexity == "simple":
            cfg.enable_scraping = False
        if retrieval_plan and retrieval_plan.breadth_queries:
            retrieval_plan.breadth_queries = retrieval_plan.breadth_queries[:2]
    elif response_depth == ResponseDepth.STANDARD:
        # Improved complexity classifier: numeric / comparative / governance-
        # sensitive queries enable verification phases even in Standard mode,
        # instead of relying on whatever the caller happened to set.
        from finagent.agent.query_analysis import classify_query_complexity
        _complexity = classify_query_complexity(objective)
        caller_deep_lite = any(
            (
                cfg.enable_multi_agent,
                cfg.enable_blindspot,
                cfg.enable_reflection,
                cfg.enable_deep_dive,
            )
        )
        standard_deep_lite = caller_deep_lite or _complexity.enable_verification
        if standard_deep_lite and not caller_deep_lite:
            # Query earned verification — turn the phases on (clamped below).
            cfg.enable_reflection = True
            cfg.enable_deep_dive = True
            if _complexity.tier == "complex":
                cfg.enable_multi_agent = True
                cfg.enable_blindspot = True
        if standard_deep_lite:
            # Preserve caller-enabled "deep-lite" phases, but clamp them hard so
            # standard mode stays latency-bounded.
            cfg.fast_mode = False
            cfg.max_steps = min(max(cfg.max_steps, 12), 18)
            cfg.breadth_search_timeout = min(cfg.breadth_search_timeout, 22.0)
            cfg.followup_search_timeout = min(cfg.followup_search_timeout, 13.0)
            cfg.news_timeout = min(cfg.news_timeout, 8.0)
            cfg.agent_deadline_ms = min(cfg.agent_deadline_ms, 12_000)
            cfg.blindspot_max_queries = min(cfg.blindspot_max_queries, 3)
            cfg.blindspot_per_query_timeout = min(cfg.blindspot_per_query_timeout, 7.0)
            cfg.reflection_max_rounds = min(max(cfg.reflection_max_rounds, 1), 1)
            cfg.reflection_per_query_limit = min(max(cfg.reflection_per_query_limit, 2), 3)
            cfg.reflection_per_query_timeout = min(max(cfg.reflection_per_query_timeout, 6.0), 8.0)
            cfg.reflection_max_new_docs = min(max(cfg.reflection_max_new_docs, 8), 16)
            cfg.reflection_wall_clock_seconds = min(cfg.reflection_wall_clock_seconds or 12.0, 12.0)
            if routing.intent_key == "PORTFOLIO_AUDIT":
                cfg.enable_scraping = False
            elif retrieval_plan and retrieval_plan.breadth_queries:
                retrieval_plan.breadth_queries = retrieval_plan.breadth_queries[:3]
        else:
            cfg.fast_mode = True
            cfg.enable_multi_agent = False
            cfg.enable_blindspot = False
            cfg.enable_reflection = False
            cfg.enable_deep_dive = False
            cfg.max_steps = min(max(cfg.max_steps, 8), 12)
            cfg.breadth_search_timeout = min(cfg.breadth_search_timeout, 10.0)
            cfg.followup_search_timeout = min(cfg.followup_search_timeout, 8.0)
            cfg.news_timeout = min(cfg.news_timeout, 8.0)
            if routing.intent_key == "PORTFOLIO_AUDIT":
                cfg.enable_scraping = False
            elif retrieval_plan and retrieval_plan.breadth_queries:
                retrieval_plan.breadth_queries = retrieval_plan.breadth_queries[:1]
    output_mode = classify_output_mode(
        query=objective,
        target=target,
        entity=entity,
        depth=response_depth,
        explicit_mode=cfg.output_mode,
    )
    if routing.deep_research and response_depth == ResponseDepth.DEEP:
        cfg.max_steps = min(max(cfg.max_steps, 20), 36)

    # ============================================================
    # DETAILED AGENT STEP LOGGING — every major decision point
    # ============================================================
    logger.info("[AGENT-START] run_research_session BEGIN | session_id=%s | target=%s | objective=%s",
                session_id, target, objective)
    logger.info("[AGENT-CONFIG] max_steps=%d | enable_enrichment=%s | enable_scraping=%s | enable_reflection=%s | enable_multi_agent=%s | depth=%s",
                cfg.max_steps, cfg.enable_enrichment, cfg.enable_scraping, cfg.enable_reflection, cfg.enable_multi_agent, cfg.response_depth)

    logger.info("[AGENT-PLAN] ResearchPlan: %s", pl.to_prompt_block()[:800] if pl else "default")

    BUS.emit(session_id, "session_started", target=target, objective=objective, plan=pl.to_prompt_block())
    BUS.emit(
        session_id,
        "output_plan",
        mode=output_mode.value,
        depth=response_depth.value,
        title=f"{output_mode.value.replace('_', ' ').title()}",
    )
    BUS.emit(session_id, "entity_resolved", **entity.to_event_payload())
    if playbook is not None:
        BUS.emit(
            session_id,
            "playbook_loaded",
            name=playbook.name,
            geography=playbook.geography,
            selected_agents=playbook.selected_agents,
            preferred_domains=playbook.preferred_domains,
        )
        for domain in playbook.preferred_domains:
            if domain not in preferred_domains:
                preferred_domains.append(domain)
    BUS.emit(
        session_id,
        "routing",
        selected_agents=routing.selected_agents,
        intent_key=routing.intent_key,
        country_code=entity.country_code,
        preferred_domains=preferred_domains[:8],
        deep_research=routing.deep_research,
    )

    logger.info("[AGENT-ROUTING] Selected agents: %s | deep_research=%s | country=%s | preferred_domains=%s",
                routing.selected_agents, routing.deep_research, entity.country_code, preferred_domains[:8])

    portfolio_sentinel = None
    if routing.intent_key == "PORTFOLIO_AUDIT":
        BUS.emit(session_id, "phase", phase="portfolio_identify", note="Loading tenant-scoped active holdings")
        if not cfg.tenant_id:
            BUS.emit(session_id, "warning", message="Portfolio audit requires a verified tenant_id.")
        else:
            try:
                from finagent.portfolio_sentinel import run_portfolio_sentinel

                portfolio_sentinel = await run_portfolio_sentinel(cfg.tenant_id)
                BUS.emit(
                    session_id,
                    "portfolio_identify",
                    tenant_id=cfg.tenant_id,
                    positions_found=portfolio_sentinel.positions_found,
                    symbols=portfolio_sentinel.symbols,
                    weights=portfolio_sentinel.weights,
                    error=portfolio_sentinel.error,
                )
                BUS.emit(
                    session_id,
                    "portfolio_sentinel",
                    risk=portfolio_sentinel.risk,
                    rules=portfolio_sentinel.rules,
                    concentration_alert=portfolio_sentinel.concentration_alert,
                    error=portfolio_sentinel.error,
                )
            except Exception as exc:
                logger.warning("Portfolio Sentinel preflight failed: %s", exc)
                BUS.emit(session_id, "warning", message=f"Portfolio Sentinel failed: {exc}")

    logger.info("[AGENT-RETRIEVAL-PLAN] Breadth queries (%d): %s",
                len(retrieval_plan.breadth_queries), retrieval_plan.breadth_queries[:6])

    t0 = time.perf_counter()
    standard_deep_lite_runtime = response_depth == ResponseDepth.STANDARD and not cfg.fast_mode
    if response_depth == ResponseDepth.CHAT:
        session_budget_s = 18.0
    elif response_depth == ResponseDepth.STANDARD:
        # Deep-lite keeps richer phases enabled, so it needs a wider wall-clock
        # envelope to preserve a meaningful final synthesis pass.
        session_budget_s = 55.0 if standard_deep_lite_runtime else 30.0
    else:
        # Deep mode: query-adaptive wall budget instead of a fixed 55s cap.
        # Governance / comparative / numeric / multi-entity queries earn more
        # wall-clock time so reflection rounds can actually run.
        from finagent.agent.query_analysis import adaptive_wall_budget
        session_budget_s = adaptive_wall_budget(
            objective,
            base_seconds=55.0,
            min_seconds=55.0,
            max_seconds=300.0,
        )
    synthesis_reserve_s = (
        20.0
        if standard_deep_lite_runtime
        else (10.0 if response_depth == ResponseDepth.STANDARD else 14.0)
    )

    def _budget_exceeded() -> bool:
        return (time.perf_counter() - t0) >= session_budget_s

    def _remaining_budget_s() -> float:
        return max(0.0, session_budget_s - (time.perf_counter() - t0))

    def _remaining_after_synthesis_s() -> float:
        return max(0.0, _remaining_budget_s() - synthesis_reserve_s)

    last_compression_step = 0
    docs: list[ScrapedDoc] = []
    step = 0

    # ── Phase 0: memory recall ─────────────────────────────────────────────
    memory_enabled = bool(cfg.enable_memory and cfg.user_email)
    memory_store = get_memory_store() if memory_enabled else None
    recalled_facts: list[MemoryFact] = []
    last_summary: dict | None = None
    if memory_store is not None:
        BUS.emit(session_id, "phase", phase="memory", note="Recalling prior facts and last session summary")
        try:
            recalled_facts = await memory_store.recall(target, limit=cfg.memory_recall_limit, user_email=cfg.user_email)
            last_summary = await memory_store.last_summary(target, user_email=cfg.user_email)
        except Exception as exc:
            logger.warning("memory recall failed: %s", exc)
            recalled_facts = []
            last_summary = None
        logger.info("Phase 0 (Memory): recalled %d facts for target '%s' | Prior summary present: %s",
                    len(recalled_facts), target, last_summary is not None)
        BUS.emit(
            session_id,
            "memory_recall",
            target=target,
            target_key=normalize_target(target),
            fact_count=len(recalled_facts),
            facts=[
                {
                    "kind": f.kind,
                    "body": f.body[:280],
                    "confidence": f.confidence,
                    "source_url": f.source_url,
                    "created_at": f.created_at,
                }
                for f in recalled_facts[:8]
            ],
            last_summary=(
                {
                    "session_id": last_summary["session_id"],
                    "summary": last_summary["summary"][:600],
                    "quality_score": last_summary.get("quality_score"),
                    "created_at": last_summary["created_at"],
                }
                if last_summary
                else None
            ),
        )

    bundle = EnrichmentBundle()
    if cfg.enable_enrichment:
        logger.info("[AGENT-PHASE] === PHASE: ENRICHMENT (Yahoo + Wiki + India/SEC) ===")
        logger.info("[AGENT-ENRICH] Starting parallel enrichment for target=%s", target)
        bundle = await _run_enrichment(
            target,
            session_id,
            entity=entity,
            news_timeout=cfg.news_timeout,
            fast_mode=cfg.fast_mode,
        )
        logger.info("[AGENT-ENRICH] Done | Yahoo=%s | Wiki=%s | News=%d | India/SEC=%s",
                    bundle.yahoo is not None, bundle.wikipedia is not None, len(bundle.news), bundle.sec is not None)

    ikg_enabled_for_standard = os.getenv("FINAGENT_STANDARD_USE_IKG", "0").strip().lower() in {"1", "true", "yes", "on"}
    if response_depth == ResponseDepth.STANDARD and not ikg_enabled_for_standard:
        logger.info("[IKG] Disabled for standard mode (FINAGENT_STANDARD_USE_IKG=0)")
        BUS.emit(
            session_id,
            "warning",
            message="Skipping IKG grounding in standard mode to preserve latency.",
        )
        bundle.ikg = None
    else:
        ikg_service = get_ikg_service()
        ikg_aliases = [
            target,
            entity.canonical_name,
            entity.ticker_label,
            entity.yahoo_ticker,
            bundle.sec.symbol if bundle.sec else None,
            bundle.sec.company_name if bundle.sec else None,
            bundle.sec.isin if bundle.sec else None,
            bundle.yahoo.ticker if bundle.yahoo else None,
            bundle.yahoo.name if bundle.yahoo else None,
        ]
        ikg_depth = "extended" if response_depth == ResponseDepth.DEEP else "standard"
        remaining_before_ikg = _remaining_after_synthesis_s()
        if response_depth == ResponseDepth.STANDARD and remaining_before_ikg < (6.0 if standard_deep_lite_runtime else 4.0):
            logger.info(
                "[IKG] Skipping IKG grounding in standard mode due to low remaining budget | remaining=%.1fs",
                remaining_before_ikg,
            )
            BUS.emit(
                session_id,
                "warning",
                message="Skipping IKG grounding in standard mode to preserve answer quality and latency budget.",
            )
            bundle.ikg = None
        else:
            ikg_cap = 16.0 if response_depth == ResponseDepth.DEEP else (10.0 if standard_deep_lite_runtime else 8.0)
            ikg_timeout_s = max(0.0, min(ikg_cap, _remaining_after_synthesis_s()))
            if ikg_timeout_s < 3.0:
                logger.info("[IKG] Skipping IKG grounding due to low remaining latency budget | remaining=%.1fs", _remaining_after_synthesis_s())
                BUS.emit(
                    session_id,
                    "warning",
                    message="Skipping IKG grounding to preserve synthesis latency budget.",
                )
                bundle.ikg = None
            else:
                try:
                    bundle.ikg = await asyncio.wait_for(
                        ikg_service.build_company_bundle(
                            identifier=target,
                            ticker=(bundle.sec.symbol if bundle.sec else None) or entity.ticker_label,
                            isin=(bundle.sec.isin if bundle.sec else None),
                            name=(bundle.sec.company_name if bundle.sec else None) or (bundle.yahoo.name if bundle.yahoo else None),
                            aliases=[alias for alias in ikg_aliases if alias],
                            depth=ikg_depth,
                        ),
                        timeout=ikg_timeout_s,
                    )
                    BUS.emit(
                        session_id,
                        "ikg_grounded",
                        status=bundle.ikg.status,
                        depth=bundle.ikg.depth,
                        confidence=round(bundle.ikg.confidence, 3),
                        as_of_date=bundle.ikg.as_of_date,
                        coverage=bundle.ikg.coverage,
                        warnings=bundle.ikg.warnings[:4],
                        entity=bundle.ikg.entity,
                    )
                except asyncio.TimeoutError:
                    logger.warning("IKG grounding timed out after %.1fs", ikg_timeout_s)
                    BUS.emit(session_id, "warning", message=f"IKG grounding timed out after {ikg_timeout_s:.1f}s")
                    bundle.ikg = None
                except Exception as exc:
                    logger.warning("IKG grounding failed: %s", exc)
                    BUS.emit(session_id, "warning", message=f"IKG grounding failed: {exc}")
                    bundle.ikg = None

    if bundle.ikg and bundle.ikg.entity:
        ikg_name = str(bundle.ikg.entity.get("name") or "").strip()
        ikg_ticker = str(bundle.ikg.entity.get("nse_symbol") or "").strip() or entity.ticker_label
        should_upgrade_entity = bool(
            ikg_name
            and ikg_name.lower() != entity.canonical_name.lower()
            and (
                entity.confidence != "high"
                or " " not in entity.canonical_name
                or len(ikg_name) > len(entity.canonical_name) + 3
            )
        )
        if should_upgrade_entity:
            entity = replace(
                entity,
                canonical_name=ikg_name,
                normalized_name=ikg_name.lower(),
                ticker_label=ikg_ticker,
                search_aliases=tuple(
                    dict.fromkeys(
                        alias
                        for alias in (
                            ikg_name,
                            ikg_ticker,
                            entity.yahoo_ticker,
                            *entity.search_aliases,
                        )
                        if alias
                    )
                ),
                confidence="high" if bundle.ikg.entity.get("cin") else entity.confidence,
            )
            preferred_domains = preferred_domains_for_entity(entity)
            retrieval_plan = build_retrieval_plan(entity, objective)
            retrieval_plan.breadth_queries = apply_playbook_to_queries(
                retrieval_plan.breadth_queries,
                playbook,
                target_label=(getattr(entity, "search_label", "") or entity.canonical_name or target),
            )
            logger.info(
                "[AGENT-ENTITY-UPGRADE] Rebuilt retrieval plan using IKG identity | canonical_name=%s | ticker=%s",
                entity.canonical_name,
                entity.ticker_label,
            )
            BUS.emit(
                session_id,
                "phase",
                phase="ikg-entity-upgrade",
                note=f"Using canonical identity '{entity.canonical_name}' for search planning.",
            )

    if response_depth == ResponseDepth.STANDARD and cfg.enable_scraping:
        if (
            _ikg_grounding_is_sufficient(bundle)
            or _ikg_can_answer_objective(bundle, objective, output_mode.value)
        ) and not _objective_needs_fresh_web(objective):
            cfg.enable_scraping = False
            BUS.emit(
                session_id,
                "phase",
                phase="ikg-fast-path",
                note="Skipping broad web scraping because IKG coverage is sufficient for a standard-depth answer.",
            )
            logger.info("[AGENT-FASTPATH] Standard mode using IKG-first path; broad scraping disabled")
    elif response_depth == ResponseDepth.DEEP and _ikg_grounding_is_sufficient(bundle):
        if retrieval_plan and retrieval_plan.breadth_queries:
            retrieval_plan.breadth_queries = retrieval_plan.breadth_queries[:2]
        if not _objective_needs_fresh_web(objective):
            cfg.enable_blindspot = False
            BUS.emit(
                session_id,
                "phase",
                phase="ikg-deep-guardrail",
                note="Reducing blindspot fanout because IKG already covers the core entity graph.",
            )
            logger.info("[AGENT-FASTPATH] Deep mode reducing blindspot fanout via IKG coverage")

    # ── Phase 3: breadth survey ───────────────────────────────────────────
    sec_name = ""
    if bundle.sec:
        sec_name = (getattr(bundle.sec, "name", "") or "").strip()
    canonical_label = sec_name or (
        bundle.ikg.entity.get("name") if bundle.ikg and bundle.ikg.entity.get("name")
        else (bundle.yahoo.name if bundle.yahoo and bundle.yahoo.name else entity.canonical_name or target)
    )
    if cfg.enable_scraping and response_depth == ResponseDepth.STANDARD:
        min_scrape_budget = 10.0 if standard_deep_lite_runtime else 6.0
        remaining_after_synthesis = _remaining_after_synthesis_s()
        if remaining_after_synthesis < min_scrape_budget:
            cfg.enable_scraping = False
            BUS.emit(
                session_id,
                "warning",
                message="Skipping breadth scraping to preserve synthesis quality under tight latency budget.",
            )
            logger.info(
                "[AGENT-SEARCH] Skipping breadth survey in standard mode | remaining_after_synthesis=%.1f < %.1f",
                remaining_after_synthesis,
                min_scrape_budget,
            )

    if cfg.enable_scraping:
        BUS.emit(session_id, "phase", phase="breadth-survey", note="Checking filings, market data, news, and peer context")
        logger.info("[AGENT-PHASE] === PHASE: BREADTH SURVEY (search_layered) ===")
        logger.info("[AGENT-SEARCH] Dispatching %d breadth queries for %s | preferred_domains=%s",
                    len(retrieval_plan.breadth_queries), canonical_label, preferred_domains[:6])

        def _on_query(q: str, status: str, count: int) -> None:
            BUS.emit(session_id, "query", query=q, status=status, count=count)

        try:
            # Pass timeout_s directly to search_layered so it can return whatever docs are compiled so far
            timeout_s = max(5.0, cfg.breadth_search_timeout - 2.0)
            docs = await search_layered(
                canonical_label,
                on_query=_on_query,
                queries=retrieval_plan.breadth_queries,
                preferred_domains=preferred_domains,
                entity=entity,
                timeout_s=timeout_s,
                bypass_crawl4ai=(response_depth != ResponseDepth.DEEP),
                lite_crawl=(response_depth == ResponseDepth.STANDARD),
            )
            logger.info("[AGENT-SEARCH] Breadth survey COMPLETE | docs_returned=%d", len(docs))
        except Exception as exc:
            logger.warning("search_layered failed: %s", exc)
            BUS.emit(session_id, "warning", message=f"search failed: {exc}")
            docs = []

    # ── Process round 1 (parallel batched) ────────────────────────────
    initial_cap = max(cfg.max_steps // 2, 6) if cfg.enable_deep_dive else cfg.max_steps
    enrichment_present = bundle.sec is not None
    _doc_sem = asyncio.Semaphore(5)

    async def _process_doc_parallel(doc, base_step):
        async with _doc_sem:
            await _process_doc(
                doc, base_step, cp, harness, validator, session_id,
                enrichment_corroborates=enrichment_present,
            )

    batch = docs[:initial_cap]
    if batch:
        await asyncio.gather(
            *(_process_doc_parallel(doc, step + i + 1) for i, doc in enumerate(batch))
        )
        step += len(batch)
        if should_compress(step, harness.settings.compression_interval_steps):
            _ = await compress_context_stub([d.excerpt for d in docs[:step]], cp)
            last_compression_step = step
            BUS.emit(session_id, "compression", step=step)

    # ── Phase 4: deep-dive (multi-round iterative search) ─────────────────
    if cfg.enable_scraping and cfg.enable_deep_dive and step < cfg.max_steps and not _budget_exceeded():
        BUS.emit(session_id, "phase", phase="deep-dive", note="Iterative gap-driven queries")
        logger.info("[AGENT-PHASE] === PHASE: DEEP DIVE (iterative follow-ups) ===")
        logger.info("[AGENT-DEEP] Starting deep-dive | current_step=%d | max_steps=%d", step, cfg.max_steps)

        def _on_query(q: str, status: str, count: int) -> None:
            BUS.emit(session_id, "query", query=q, status=status, count=count)

        seen_urls = {(d.final_url or d.url).split("#", 1)[0] for d in docs}

        async def _one(q: str) -> list[ScrapedDoc]:
            _on_query(q, "running", 0)
            try:
                localized_q = localize_search_query(q, entity)
                results = await asyncio.wait_for(
                    search_web(
                        localized_q,
                        max_results=6,
                        preferred_domains=preferred_domains,
                        entity=entity,
                        bypass_crawl4ai=(response_depth != ResponseDepth.DEEP),
                        lite_crawl=(response_depth == ResponseDepth.STANDARD),
                    ),
                    timeout=cfg.followup_search_timeout,
                )
                _on_query(q, "done", len(results))
                return results
            except asyncio.TimeoutError:
                _on_query(q, "timeout", 0)
                logger.warning("followup query %r timed out", q)
                return []
            except Exception as exc:
                _on_query(q, "error", 0)
                logger.warning("followup query %r failed: %s", q, exc)
                return []

        async def _staggered_one(q: str, delay: float) -> list[ScrapedDoc]:
            if delay > 0:
                await asyncio.sleep(delay)
            return await _one(q)

        _dive_doc_sem = asyncio.Semaphore(5)

        # Up to 4 rounds, gated by remaining step budget. Each round harvests
        # entities/gaps from the *cumulative* doc pool so coverage compounds.
        for round_index in range(4):
            if step >= cfg.max_steps or _budget_exceeded():
                break
            remaining_budget_s = _remaining_after_synthesis_s()
            if remaining_budget_s < max((12.0 if standard_deep_lite_runtime else 8.0), cfg.followup_search_timeout + (6.0 if standard_deep_lite_runtime else 3.0)):
                BUS.emit(
                    session_id,
                    "warning",
                    message="Deep-dive time budget is nearly exhausted; moving to analysis and synthesis.",
                )
                logger.info(
                    "[AGENT-DEEP] Stopping deep-dive early | remaining_budget_s=%.1f | step=%d/%d",
                    remaining_budget_s,
                    step,
                    cfg.max_steps,
                )
                break
            followups = _build_followup_queries(canonical_label, docs, bundle.sec, round_index=round_index)
            if not followups:
                continue
            max_followups = 2 if remaining_budget_s < 16.0 else 3
            followups = followups[:max_followups]
            logger.info("Phase 4 (Deep Dive): Round %d | Generated follow-up queries: %s", round_index + 1, followups)
            BUS.emit(
                session_id,
                "phase",
                phase="deep-dive",
                note=f"Round {round_index + 1}: {len(followups)} targeted queries",
            )
            followup_results = await asyncio.gather(
                *(_staggered_one(q, i * 0.1) for i, q in enumerate(followups))
            )
            # Collect new docs first, then process in parallel
            new_docs_in_round = []
            for batch in followup_results:
                for d in batch:
                    key = (d.final_url or d.url).split("#", 1)[0]
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    docs.append(d)
                    if step + len(new_docs_in_round) + 1 >= cfg.max_steps:
                        break
                    new_docs_in_round.append(d)

            # Process collected docs in parallel
            if new_docs_in_round:
                async def _dive_process(doc, s):
                    async with _dive_doc_sem:
                        await _process_doc(
                            doc, s, cp, harness, validator, session_id,
                            enrichment_corroborates=enrichment_present,
                        )
                await asyncio.gather(
                    *(_dive_process(d, step + i + 1) for i, d in enumerate(new_docs_in_round))
                )
                step += len(new_docs_in_round)
                logger.info("Phase 4 (Deep Dive): Round %d finished | Found %d new documents | Total documents: %d | Step: %d/%d",
                            round_index + 1, len(new_docs_in_round), len(docs), step, cfg.max_steps)
                if _budget_exceeded():
                    logger.info("[AGENT-DEEP] Time budget reached immediately after round %d processing", round_index + 1)
                    break

            if not new_docs_in_round:
                break

    if step == 0:
        for synthetic_step in range(1, min(cfg.max_steps, 3) + 1):
            cp.step = synthetic_step
            cp.completed_steps.append(StepResult(name=f"step_{synthetic_step}", summary="no scraping results", ok=False))
            harness.maybe_persist_checkpoint(synthetic_step, cp)
            step = synthetic_step

    # ── Phase 4.5: reflection loop (Hermes-style self-improvement) ────────
    reflection_payload = None
    min_reflection_budget = 16.0 if standard_deep_lite_runtime else 12.0
    if cfg.enable_reflection and cfg.enable_scraping and not _budget_exceeded() and _remaining_after_synthesis_s() >= min_reflection_budget:
        BUS.emit(
            session_id,
            "phase",
            phase="reflection",
            note=f"Reflection loop - target >={cfg.quality_threshold:.0f} quality",
        )
        logger.info("Phase 4.5 (Reflection): Starting coverage reflection loop | Target Quality: >=%.1f", cfg.quality_threshold)
        step_ref: dict = {"v": step}

        async def _process_for_reflection(doc: ScrapedDoc, _i: int) -> None:
            step_ref["v"] += 1
            await _process_doc(
                doc,
                step_ref["v"],
                cp,
                harness,
                validator,
                session_id,
                enrichment_corroborates=(bundle.sec is not None),
            )

        async def _search_for_reflection(query: str, max_results: int) -> list:
            localized_q = localize_search_query(query, entity)
            return await search_web(
                localized_q,
                max_results=max_results,
                preferred_domains=preferred_domains,
                entity=entity,
                bypass_crawl4ai=(response_depth != ResponseDepth.DEEP),
                lite_crawl=(response_depth == ResponseDepth.STANDARD),
            )

        def _conflicts(d: list) -> list:
            return detect_conflicts(d)

        def _emit_event(event_type: str, **payload) -> None:
            BUS.emit(session_id, event_type, **payload)

        try:
            loop = ReflectionLoop(
                target=canonical_label,
                session_id=session_id,
                max_rounds=cfg.reflection_max_rounds,
                score_threshold=cfg.quality_threshold,
                per_query_limit=cfg.reflection_per_query_limit,
                per_query_timeout=cfg.reflection_per_query_timeout,
                max_total_new_docs=cfg.reflection_max_new_docs,
                max_queries_per_round=cfg.reflection_max_queries_per_round,
                max_wall_clock_seconds=cfg.reflection_wall_clock_seconds,
                early_accept_margin=cfg.reflection_early_accept_margin,
                min_score_gain=cfg.reflection_min_score_gain,
            )
            ref_result = await loop.run(
                bundle=bundle,
                docs=docs,
                checkpoint=cp,
                entity=entity,
                conflicts_callable=_conflicts,
                search_callable=_search_for_reflection,
                process_doc_callable=_process_for_reflection,
                emit_callable=_emit_event,
                budget_exceeded=_budget_exceeded,
            )
            step = step_ref["v"]
            reflection_payload = ref_result.to_dict()
            logger.info("[AGENT-PHASE] === PHASE: REFLECTION COMPLETE ===")
            logger.info("[AGENT-REFLECTION] QualityScore=%.1f | rounds=%s", reflection_payload.get("final_score", 0.0), reflection_payload.get("rounds_run", 0))
            BUS.emit(session_id, "reflection_done", **reflection_payload)
        except Exception as exc:
            logger.warning("reflection loop failed: %s", exc)
            BUS.emit(session_id, "warning", message=f"reflection loop failed: {exc}")
    elif cfg.enable_reflection and cfg.enable_scraping:
        BUS.emit(
            session_id,
            "warning",
            message="Skipping reflection to preserve response latency budget.",
        )
        logger.info(
            "[AGENT-REFLECTION] Skipped | budget_exceeded=%s | remaining_after_synthesis=%.1f",
            _budget_exceeded(),
            _remaining_after_synthesis_s(),
        )

    # ── Phase 4.7: Multi-agent dispatch (parallel specialists + verifier) ──
    orchestration_payload = None
    blindspot_payload = None
    orchestration_findings: list = []
    min_multi_agent_budget = 14.0 if standard_deep_lite_runtime else 10.0
    if cfg.enable_multi_agent and cfg.enable_scraping and not _budget_exceeded() and _remaining_after_synthesis_s() >= min_multi_agent_budget:
        BUS.emit(
            session_id,
            "phase",
            phase="multi-agent",
            note="Dispatching specialist subagents in parallel + verifier pass",
        )
        logger.info("[AGENT-PHASE] === PHASE: MULTI-AGENT SPECIALISTS (orchestrator) ===")

        def _emit_event(event_type: str, **payload) -> None:
            BUS.emit(session_id, event_type, **payload)

        seen_urls = {(d.final_url or d.url or "").split("#", 1)[0] for d in docs}
        ikg_entity = bundle.ikg.entity if bundle.ikg else {}
        agent_contexts: dict[str, dict] = {}
        try:
            selected_agent_names = sorted(set(routing.selected_agents))
            context_tasks = [
                load_agent_context(
                    agent_name,
                    ticker=ikg_entity.get("nse_symbol") or (bundle.sec.symbol if bundle.sec else None) or entity.ticker_label,
                    cin=ikg_entity.get("cin"),
                    sector=ikg_entity.get("sector") or (bundle.sec.sector if bundle.sec else None),
                    ikg_bundle=bundle.ikg,
                )
                for agent_name in selected_agent_names
            ]
            if context_tasks:
                context_results = await asyncio.gather(*context_tasks, return_exceptions=True)
                for agent_name, context_result in zip(selected_agent_names, context_results):
                    if isinstance(context_result, Exception):
                        logger.debug("Agent context load failed for %s: %s", agent_name, context_result)
                        continue
                    agent_contexts[agent_name] = context_result or {}
        except Exception as exc:
            logger.warning("agent-specific IKG context load failed: %s", exc)

        ctx = SubAgentContext(
            target=target,
            canonical_label=canonical_label,
            objective=objective,
            bundle=bundle,
            seed_docs=docs,
            session_id=session_id,
            seen_urls=seen_urls,
            resolved_entity=entity,
            ikg_bundle=bundle.ikg,
            agent_contexts=agent_contexts,
            preferred_domains=preferred_domains,
            bypass_crawl4ai=(response_depth != ResponseDepth.DEEP),
            lite_crawl=(response_depth == ResponseDepth.STANDARD),
            portfolio_symbols=(portfolio_sentinel.symbols if portfolio_sentinel else []),
            portfolio_risk=(portfolio_sentinel.risk if portfolio_sentinel else {}),
            runtime_rules=(portfolio_sentinel.rules if portfolio_sentinel else []),
            budget_exceeded=_budget_exceeded,
        )

        try:
            allowed_agents = set(routing.selected_agents)
            roster = [agent for agent in default_roster() if agent.name in allowed_agents] or default_roster()
            logger.info("[AGENT-SPECIALISTS] Running %d specialists: %s | allowed_from_router=%s",
                        len(roster), [a.name for a in roster], list(allowed_agents))
            orchestrator = Orchestrator(
                roster,
                emit=_emit_event,
                per_agent_deadline_ms=cfg.agent_deadline_ms,
            )
            orch_result = await orchestrator.run(ctx)
            orchestration_findings = list(orch_result.findings)
            orchestration_payload = orch_result.to_dict()
            logger.info("[AGENT-SPECIALISTS] Orchestrator DONE | findings=%d | new_docs_from_specialists=%d | waves=%d",
                        len(orchestration_findings), len(orch_result.new_docs), orch_result.waves)

            # Merge new docs from subagents into the main pool +
            # process them through the citation log so they count toward
            # confidence/conflicts.
            _orch_new = []
            _orch_keys = {(x.final_url or x.url or "").split("#", 1)[0] for x in docs}
            for d in orch_result.new_docs:
                key = (d.final_url or d.url or "").split("#", 1)[0]
                if not key or key in _orch_keys:
                    continue
                _orch_keys.add(key)
                docs.append(d)
                _orch_new.append(d)
            if _orch_new:
                _orch_sem = asyncio.Semaphore(5)
                async def _orch_proc(doc, s):
                    async with _orch_sem:
                        await _process_doc(doc, s, cp, harness, validator, session_id, enrichment_corroborates=(bundle.sec is not None))
                await asyncio.gather(*(_orch_proc(d, step + i + 1) for i, d in enumerate(_orch_new)))
                step += len(_orch_new)

            # Verifier — cross-checks all findings, demotes/promotes, runs
            # AccuracyValidator on each finding.
            verifier = Verifier(validator=validator)
            ikg_metric_observations = metric_observations_from_bundle(bundle.ikg)
            verifier_report = verifier.run(
                findings=orchestration_findings,
                docs=docs,
                extra_metric_observations=ikg_metric_observations,
                emit=_emit_event,
            )
            orchestration_payload["verifier"] = verifier_report.to_dict()

            # Stream each finding so the UI can render them in real time
            for f in orchestration_findings:
                _emit_event(
                    "finding",
                    agent=f.agent,
                    kind=f.kind,
                    headline=f.headline,
                    detail=f.detail[:600],
                    confidence=f.confidence,
                    evidence=f.evidence[:5],
                    metrics=f.metrics,
                )
        except Exception as exc:
            logger.warning("multi-agent dispatch failed: %s", exc)
            _emit_event("warning", message=f"multi-agent dispatch failed: {exc}")

        # ── Blind-spot generator + optional auto-dispatch ─────────────
        if cfg.enable_blindspot and orchestration_findings:
            try:
                if _budget_exceeded() or _remaining_after_synthesis_s() < (10.0 if standard_deep_lite_runtime else 8.0):
                    logger.info(
                        "[AGENT-BLINDSPOT] Skipped | budget_exceeded=%s | remaining_after_synthesis=%.1f",
                        _budget_exceeded(),
                        _remaining_after_synthesis_s(),
                    )
                    _emit_event(
                        "warning",
                        message="Skipping blindspot fanout to preserve response latency budget.",
                    )
                    spots = []
                    blindspot_payload = {"blindspots": [], "new_docs": 0, "skipped": True, "reason": "latency_budget"}
                else:
                    spots = detect_blind_spots(
                        target_label=canonical_label,
                        findings=orchestration_findings,
                        seed_docs=docs,
                        top_n=6,
                    )
                    logger.info("Phase 4.7 (Multi-Agent): Blind-spot generation detected %d spots", len(spots))
                    blindspot_payload = {"blindspots": [s.to_dict() for s in spots]}
                    _emit_event(
                        "blindspot",
                        blindspot_count=len(spots),
                        blindspots=blindspot_payload["blindspots"],
                    )
                if spots:
                    if routing.intent_key == "PORTFOLIO_AUDIT":
                        # Portfolio deep runs already carry holdings/risk context; blindspot web fanout
                        # is high-latency and often low-signal here. Skip it to guarantee forward progress.
                        logger.info("Phase 4.7 (Multi-Agent): Skipping blindspot auto-dispatch for portfolio audit scope")
                        blindspot_payload["new_docs"] = 0
                        _emit_event(
                            "blindspot_dispatched",
                            new_docs=0,
                            queries=0,
                            skipped=True,
                            reason="portfolio_scope",
                        )
                        spots = []
                    if not spots:
                        pass
                    BUS.emit(
                        session_id,
                        "phase",
                        phase="blindspot",
                        note=f"Auto-dispatching {sum(len(s.queries) for s in spots[:3])} queries to cover {len(spots[:3])} blind spots",
                    )
                    # Auto-dispatch the queries for the top-3 highest-severity
                    # blind spots — capped by max_queries
                    fanout: list[str] = []
                    for s in spots[:3]:
                        for q in s.queries:
                            if len(fanout) >= cfg.blindspot_max_queries:
                                break
                            fanout.append(q)
                        if len(fanout) >= cfg.blindspot_max_queries:
                            break
                    logger.info("Phase 4.7 (Multi-Agent): Auto-dispatching %d blindspot queries: %s",
                                len(fanout), fanout)

                    async def _bs_one(q: str):
                        _emit_event("query", query=q, status="running", count=0)
                        try:
                            localized_q = localize_search_query(q, entity)
                            r = await asyncio.wait_for(
                                search_web(
                                    localized_q,
                                    max_results=4,
                                    preferred_domains=preferred_domains,
                                    entity=entity,
                                    bypass_crawl4ai=(response_depth != ResponseDepth.DEEP),
                                    lite_crawl=(response_depth == ResponseDepth.STANDARD),
                                ),
                                timeout=cfg.blindspot_per_query_timeout,
                            )
                            _emit_event("query", query=q, status="done", count=len(r))
                            return r
                        except asyncio.TimeoutError:
                            _emit_event("query", query=q, status="timeout", count=0)
                            return []
                        except Exception as exc:
                            _emit_event("query", query=q, status="error", count=0)
                            logger.warning("blindspot query %r failed: %s", q, exc)
                            return []

                    # Hard global wall clock for the blindspot fanout so we never block synthesis.
                    dispatch_budget_s = max(8.0, min(45.0, cfg.blindspot_per_query_timeout + 6.0))
                    task_to_query = {
                        asyncio.create_task(_bs_one(q)): q
                        for q in fanout
                    }
                    if task_to_query:
                        done, pending = await asyncio.wait(
                            task_to_query.keys(),
                            timeout=dispatch_budget_s,
                        )
                    else:
                        done, pending = set(), set()
                    if pending:
                        logger.warning(
                            "Phase 4.7 (Multi-Agent): Blindspot auto-dispatch exceeded %.1fs budget; continuing with %d/%d completed",
                            dispatch_budget_s,
                            len(done),
                            len(task_to_query),
                        )
                        _emit_event(
                            "warning",
                            message=f"Blindspot dispatch timed out; continuing with {len(done)}/{len(task_to_query)} completed queries.",
                        )
                        for task in pending:
                            q = task_to_query.get(task, "")
                            if q:
                                _emit_event("query", query=q, status="timeout", count=0)
                            task.cancel()

                    batches = []
                    for task in done:
                        q = task_to_query.get(task, "")
                        try:
                            batches.append(task.result())
                        except Exception as exc:
                            if q:
                                _emit_event("query", query=q, status="error", count=0)
                            logger.warning("blindspot query task %r failed: %s", q, exc)
                    existing_keys = {(d.final_url or d.url or "").split("#", 1)[0] for d in docs}
                    _bs_docs = []
                    for batch in batches:
                        for d in batch:
                            key = (d.final_url or d.url or "").split("#", 1)[0]
                            if not key or key in existing_keys:
                                continue
                            existing_keys.add(key)
                            docs.append(d)
                            _bs_docs.append(d)
                    bs_new = len(_bs_docs)
                    if _bs_docs:
                        _bs_sem = asyncio.Semaphore(5)
                        async def _bs_proc(doc, s):
                            async with _bs_sem:
                                await _process_doc(doc, s, cp, harness, validator, session_id, enrichment_corroborates=(bundle.sec is not None))
                        await asyncio.gather(*(_bs_proc(d, step + i + 1) for i, d in enumerate(_bs_docs)))
                        step += bs_new
                        logger.info("Phase 4.7 (Multi-Agent): Blindspot dispatch complete | Ingested %d new documents | Total step: %d",
                                    bs_new, step)
                    blindspot_payload["new_docs"] = bs_new
                    _emit_event("blindspot_dispatched", new_docs=bs_new, queries=len(fanout))
            except Exception as exc:
                logger.warning("blindspot pass failed: %s", exc)
    elif cfg.enable_multi_agent and cfg.enable_scraping:
        BUS.emit(
            session_id,
            "warning",
            message="Skipping multi-agent pass to preserve response latency budget.",
        )
        logger.info(
            "[AGENT-SPECIALISTS] Skipped | budget_exceeded=%s | remaining_after_synthesis=%.1f",
            _budget_exceeded(),
            _remaining_after_synthesis_s(),
        )

    # ── Phase 5: analysis ─────────────────────────────────────────────────
    BUS.emit(session_id, "phase", phase="analysis", note="Cross-source conflict detection")
    logger.info("Phase 5 (Analysis): Starting conflict detection on %d documents", len(docs))
    conflicts = detect_conflicts(
        docs,
        external_observations=metric_observations_from_bundle(bundle.ikg),
    )
    logger.info("Phase 5 (Analysis): Completed conflict detection | Found %d cross-source conflicts", len(conflicts))
    for conflict in conflicts:
        logger.info("  Conflict on metric '%s': spread %.1f%% | Note: %s",
                    conflict.metric, conflict.spread_pct, conflict.note)
    for conflict in conflicts:
        BUS.emit(
            session_id,
            "conflict",
            metric=conflict.metric,
            spread_pct=round(conflict.spread_pct, 1),
            note=conflict.note,
            observations=[
                {
                    "domain": o.domain,
                    "tier": o.tier,
                    "raw": o.raw,
                    "value": o.value,
                    "url": o.url,
                    "context": o.context,
                }
                for o in conflict.observations
            ],
        )

    # ── Phase 6: synthesis ────────────────────────────────────────────────
    logger.info("[AGENT-PHASE] === PHASE: SYNTHESIS (final LLM memo generation) ===")
    final_quality = score_research(
        target=canonical_label,
        bundle=bundle,
        docs=docs,
        checkpoint=cp,
        entity=entity,
        conflicts=conflicts,
    )

    synthesis = None
    memo_path = None
    portfolio_analytics: dict | None = None
    if cfg.emit_memo:
        BUS.emit(
            session_id,
            "phase",
            phase="synthesis",
            note=f"Composing {output_mode.value.replace('_', ' ')} answer",
        )
        logger.info("[AGENT-SYNTH] Starting final LLM synthesis | docs=%d | specialist_findings=%d | conflicts=%d | quality=%.1f",
                    len(docs), len(orchestration_findings), len(conflicts), final_quality.score)
        logger.info("[AGENT-SYNTH] Passing to synthesize_memo: specialist_findings_count=%d | peer_targets=%s",
                    len(orchestration_findings), cfg.peer_targets)

        def _on_memo_token(chunk: str) -> None:
            BUS.emit(session_id, "memo_token", chunk=chunk)

        # ── Fetch live portfolio analytics for portfolio-scoped queries ──
        portfolio_analytics = None
        try:
            from finagent.router.intent_router import is_portfolio_scope_query
            if is_portfolio_scope_query(objective):
                from finagent.portfolio.analytics import compute_portfolio_analytics
                from finagent.portfolio_mirrors import load_active_positions
                tenant_id = getattr(cfg, "tenant_id", None)
                if tenant_id:
                    positions = await load_active_positions(tenant_id)
                    if positions:
                        portfolio_analytics = compute_portfolio_analytics(positions, period="1y", benchmark="NIFTY50")
                        logger.info("[PORTFOLIO-INJECT] Injecting live portfolio analytics | holdings=%d | value=%.0f",
                                    len(positions), portfolio_analytics.get('total_market_value', 0))
        except Exception as exc:
            logger.warning("[PORTFOLIO-INJECT] Failed to fetch portfolio analytics: %s", exc)

        standard_deep_lite = response_depth == ResponseDepth.STANDARD and not cfg.fast_mode
        synthesis_timeout_cap = 36.0 if standard_deep_lite else (15.0 if response_depth == ResponseDepth.STANDARD else 22.0)
        synthesis_timeout_floor = 18.0 if standard_deep_lite else (8.0 if response_depth == ResponseDepth.STANDARD else 10.0)
        synthesis = await synthesize_memo(
            target,
            objective,
            docs,
            cp,
            timeout_s=max(synthesis_timeout_floor, min(_remaining_budget_s() + (8.0 if standard_deep_lite else 6.0), synthesis_timeout_cap)),
            conflicts=conflicts,
            on_token=_on_memo_token,
            enrichment=bundle,
            synth_model=cfg.synth_model,
            output_mode=output_mode.value,
            response_depth=response_depth.value,
            entity=entity,
            specialist_findings=orchestration_findings,
            quality_report=final_quality,
            chat_history=cfg.chat_history,
            session_id=session_id,
            peer_targets=cfg.peer_targets,
            user_email=cfg.user_email,
            portfolio_context=portfolio_analytics,
            is_deep_lite=standard_deep_lite,
        )
        memos_dir = finagent_data_path("memos")
        memos_dir.mkdir(parents=True, exist_ok=True)
        memo_path = memos_dir / f"{session_id}.md"
        memo_path.write_text(synthesis.memo, encoding="utf-8")
        logger.info("[AGENT-SYNTH] Memo synthesis COMPLETE | via=%s | length=%d chars | quality=%.1f | path=%s",
                    synthesis.via, len(synthesis.memo), final_quality.score, memo_path)

        BUS.emit(
            session_id,
            "memo",
            via=synthesis.via,
            used_sources=synthesis.used_sources,
            chars=len(synthesis.memo),
            path=str(memo_path),
            preview=synthesis.memo[:2400],
            output_mode=output_mode.value,
            response_depth=response_depth.value,
        )
    else:
        BUS.emit(
            session_id,
            "phase",
            phase="synthesis",
            note="Skipping memo for intermediate deep-research pass",
        )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    # ── Persist learnings to long-term memory ─────────────────────────────
    if memory_store is not None:
        try:
            await _persist_session_memory(
                memory_store,
                session_id=session_id,
                target=target,
                canonical_label=canonical_label,
                bundle=bundle,
                docs=docs,
                cp=cp,
                conflicts=conflicts,
                quality_score=final_quality.score,
                user_email=cfg.user_email,
            )
        except Exception as exc:
            logger.warning("memory persist failed: %s", exc)
    try:
        promoted = maybe_promote_playbook(
            quality_score=final_quality.score,
            geography=entity.country_code,
            objective=objective,
            target=target,
            selected_agents=routing.selected_agents,
            preferred_domains=preferred_domains,
            query_templates=retrieval_plan.breadth_queries,
        )
        if promoted is not None:
            BUS.emit(
                session_id,
                "playbook_promoted",
                name=promoted.name,
                geography=promoted.geography,
                selected_agents=promoted.selected_agents,
            )
    except Exception as exc:
        logger.warning("playbook promotion failed: %s", exc)

    primary_count = sum(1 for c in cp.citation_log if c.kind == "primary")
    runtime_meta = {
        "ikg_sufficient": _ikg_grounding_is_sufficient(bundle),
        "can_answer_objective": _ikg_can_answer_objective(bundle, objective, output_mode.value),
        "objective_needs_fresh_web": _objective_needs_fresh_web(objective),
        "doc_count": len(docs),
        "conflict_count": len(conflicts),
        "primary_citations": primary_count,
        "news_item_count": len(bundle.news or []),
        "ikg_coverage": dict(getattr(bundle.ikg, "coverage", {}) or {}),
        "response_depth": response_depth.value,
    }
    setattr(cp, "runtime_meta", runtime_meta)

    citation_sources: list[dict[str, str]] = []
    seen_citation_urls: set[str] = set()
    for citation in cp.citation_log:
        url = str(getattr(citation, "url", "") or "").strip()
        if not url or url in seen_citation_urls:
            continue
        seen_citation_urls.add(url)
        citation_sources.append(
            {
                "title": str(getattr(citation, "title", "") or "")[:220],
                "url": url[:1200],
                "kind": str(getattr(citation, "kind", "") or "secondary"),
            }
        )
        if len(citation_sources) >= 40:
            break

    _final_payload = dict(
        target=target,
        canonical=canonical_label,
        steps=cp.step,
        citations=len(cp.citation_log),
        primary_citations=primary_count,
        citation_sources=citation_sources,
        confidence_summary=cp.confidence_summary,
        compressed_at=last_compression_step,
        memo_path=str(memo_path) if memo_path else "",
        memo_via=synthesis.via if synthesis else "suppressed",
        memo=synthesis.memo if synthesis else "",
        memo_preview=(synthesis.memo[:2400] if synthesis else ""),
        output_mode=output_mode.value,
        response_depth=response_depth.value,
        conflicts=len(conflicts),
        has_sec=bundle.sec is not None,
        has_yahoo=bundle.yahoo is not None,
        has_wiki=bundle.wikipedia is not None,
        elapsed_ms=elapsed_ms,
        quality_score=round(final_quality.score, 1),
        quality_gaps=final_quality.gaps[:6],
        reflection=reflection_payload,
        memory_recalled=len(recalled_facts),
        memory_seeded=last_summary is not None,
        orchestration=orchestration_payload,
        blindspot=blindspot_payload,
        resolved_entity=entity.to_event_payload(),
        ikg=(bundle.ikg.to_public_payload() if bundle.ikg else None),
    )
    # Attach rich structured data (comparison tables, charts) so the frontend
    # final handler can render them even if visual_data_ready was insufficient.
    if synthesis and getattr(synthesis, "rich", None):
        _final_payload["rich"] = synthesis.rich

    # ── Deterministic portfolio rich payload ──
    # Re-attached to final event so RichResponse fallback renders visuals.
    # Inline visuals are a separate enhancement that will be injected into memo text.
    if portfolio_analytics:
        try:
            rich = _build_portfolio_rich_payload(portfolio_analytics, benchmark="NIFTY50")
            _final_payload["rich"] = rich
            logger.info("[PORTFOLIO] portfolio rich payload attached to final event | mode=%s cards=%d charts=%d tables=%d",
                        rich.get("mode"), len(rich.get("metric_cards", [])), len(rich.get("charts", [])), len(rich.get("tables", [])))
        except Exception as e:
            logger.warning("[PORTFOLIO] failed to compute rich payload: %s", e)

    if cfg.emit_memo:
        # Only emit "final" for the true synthesis pass — intermediate deep-research
        # passes use "pass_done" so the frontend never renders duplicate export blocks.
        BUS.emit(session_id, "final", **_final_payload)
    else:
        # Lightweight completion signal for non-synthesis passes; frontend ignores this
        # for UI rendering but it lets the orchestrator track progress.
        BUS.emit(session_id, "pass_done", **_final_payload)

    if cfg.close_bus_on_finish:
        BUS.close(session_id)

    logger.info(
        "Session finished successfully at step %s with %d citations; memo via %s",
        cp.step,
        len(cp.citation_log),
        synthesis.via if synthesis else "suppressed",
    )
    try:
        from finagent.state.session_context import active_agents, active_mcps, active_websites
        agents_list = sorted(list(active_agents.get() or set()))
        mcps_list = sorted(list(active_mcps.get() or set()))
        websites_list = sorted(list(active_websites.get() or set()))

        logger.info("================================================================================")
        logger.info("[SESSION-SUMMARY] Resources Used for Generated Output:")
        logger.info("  AGENTS:   %s", ", ".join(agents_list) if agents_list else "None")
        logger.info("  MCPS:     %s", ", ".join(mcps_list) if mcps_list else "None")
        logger.info("  WEBSITES: %s", ", ".join(websites_list) if websites_list else "None")
        logger.info("================================================================================")
    except Exception as exc:
        logger.warning("Failed to print session summary: %s", exc)

    await aclose_shared_client()
    return pl, cp


async def run_finagent_session(
    message: str,
    cfg: AgentLoopConfig,
) -> tuple[str, list[str], RichResponse | None]:
    """Resolve entities, execute a research session, read the memo, and retrieve visual/agent results."""
    from finagent.geo.entity_resolver import resolve_entities, resolve_entity
    from finagent.rich_builder import RichResponse
    from finagent.events import BUS
    import json
    
    logger.info("[AGENT-ENTRY] run_finagent_session called | session_id=%s | user_query=%r", cfg.session_id, message)
    logger.info("[AGENT-ENTRY] Full user message length=%d chars", len(message))
    
    # 1. Resolve entities from the message
    try:
        entities = resolve_entities(message)
    except Exception as e:
        logger.warning("resolve_entities failed: %s. Falling back to single resolve_entity.", e)
        entities = []
        
    if entities:
        target = entities[0].canonical_name
        logger.info("Resolved target entity: %s", target)
        if len(entities) > 1:
            cfg.peer_targets = [e.canonical_name for e in entities[1:]]
            logger.info("Resolved peer target entities: %s", cfg.peer_targets)
    else:
        try:
            ent = resolve_entity(message)
            target = ent.canonical_name
            logger.info("Fallback resolved target entity: %s", target)
        except Exception as e:
            logger.error("Fallback resolve_entity failed: %s. Using message directly as target.", e)
            target = message
            
    # 2. Run the research session
    try:
        await run_research_session(target, message, loop_config=cfg)
    except Exception as e:
        logger.error("Error during run_research_session execution: %s", e, exc_info=True)
        raise e
        
    # 3. Read the final memo text from disk
    memo_path = finagent_data_path("memos") / f"{cfg.session_id}.md"
    reply = ""
    if memo_path.exists():
        try:
            reply = memo_path.read_text(encoding="utf-8")
            logger.info("Successfully loaded memo from %s (length: %d)", memo_path, len(reply))
        except Exception as e:
            logger.error("Failed to read memo file %s: %s", memo_path, e)
            reply = "Failed to load generated memo."
    else:
        logger.warning("Memo file not found at %s", memo_path)
        reply = "Research session completed, but memo was not saved."
        
    # 4. Scan BUS.history to recover agents_used and rich payload
    agents_used = []
    rich_payload = None
    try:
        history_events = BUS.history(cfg.session_id, limit=1000)
        logger.info("Scanning %d events from session %s history to extract agents and rich visual data.", len(history_events), cfg.session_id)
        for seq, ev in history_events:
            if ev.type == "routing":
                agents_used = ev.payload.get("selected_agents", [])
                logger.info("Found agents_used in routing event: %s", agents_used)
            elif ev.type == "final":
                rich_payload = ev.payload.get("rich", None)
                logger.info("Found rich visual payload in final event.")
    except Exception as e:
        logger.error("Failed to retrieve or scan BUS history: %s", e)
        
    # 5. Reconstruct the validated RichResponse model
    rich = None
    if rich_payload is not None:
        try:
            rich = RichResponse.model_validate(rich_payload)
            logger.info("Successfully validated and reconstructed RichResponse model.")
        except Exception as e:
            logger.error("Failed to validate RichResponse from payload: %s", e, exc_info=True)
            rich = None
            
    return reply, agents_used, rich
