"""Core agent loop.

Pipeline:
1. identify   — resolve target to SEC ticker / CIK if it's a US-listed entity
2. enrichment — pull authoritative JSON APIs in parallel (SEC EDGAR companyfacts,
                Yahoo Finance chart, Wikipedia REST summary)
3. breadth-survey — layered DuckDuckGo search across 4 angles
4. deep-dive — iterative targeted second-pass queries to fill gaps
5. analysis — cross-source conflict detection, viral scoring
6. synthesis — OpenAI / template memo using the *facts*, not just excerpts
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from datetime import datetime, timezone

from finagent.accuracy_validator import AccuracyValidator, Claim, Source
from finagent.agent.reflection import ReflectionLoop
from finagent.agents import Orchestrator, SubAgentContext, Verifier, detect_blind_spots
from finagent.agents.specialists import default_roster
from finagent.analysis.conflicts import detect_conflicts
from finagent.analysis.quality import score_research
from finagent.events import BUS
from finagent.geo import resolve_entity
from finagent.geo.query_localizer import localize_search_query
from finagent.geo.source_policy import preferred_domains_for_entity
from finagent.harness import Harness, HarnessConfig, compress_context_stub
from finagent.harness.context_manager import should_compress
from finagent.memory import MemoryFact, get_memory_store
from finagent.memory.store import normalize_target
from finagent.paths import finagent_data_path
from finagent.playbooks import apply_playbook_to_queries, maybe_promote_playbook, retrieve_playbook
from finagent.prompt_builder import default_system_prompt
from finagent.retrieval import build_retrieval_plan
from finagent.research_planner import ResearchPlan, build_default_plan
from finagent.router import route_objective
from finagent.output.intent_classifier import classify_output_mode, normalize_depth
from finagent.state.checkpoint import Checkpoint, StepResult, empty_checkpoint
from finagent.state.citation_log import Citation
from finagent.synthesis import EnrichmentBundle, synthesize_memo
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
from finagent.tools.web.scraper import ScrapedDoc, search_layered, search_web

logger = logging.getLogger("finagent.run_agent")


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
    # ── Comparison: when set, synthesis fetches rich enrichment for peers ──
    peer_targets: list[str] = field(default_factory=list)


def _auto_max_steps(objective: str, base: int) -> int:
    """Scale total step budget by objective complexity. Defaults err big —
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
) -> EnrichmentBundle:
    """Fan-out to SEC, Yahoo, Wikipedia. None failures are non-fatal."""
    BUS.emit(session_id, "phase", phase="enrichment", note="Pulling authoritative APIs (NSE/BSE, Yahoo Finance, Moneycontrol)")

    async def _sec() -> SECCompanySnapshot | None:
        if entity.country_code not in ("US", "GLOBAL"):
            BUS.emit(
                session_id,
                "agent_task",
                task="SEC EDGAR",
                status="warning",
                note=f"Skipped for {entity.country_name}; using local-market retrieval instead",
            )
            return None
        BUS.emit(session_id, "agent_task", task="SEC EDGAR", status="running", note=f"Resolving {target} -> CIK")
        try:
            snap = await fetch_company_snapshot(target)
            if snap is None:
                BUS.emit(session_id, "agent_task", task="SEC EDGAR", status="warning", note="No SEC match (private or non-US)")
                return None
            BUS.emit(
                session_id,
                "agent_task",
                task="SEC EDGAR",
                status="done",
                note=f"{snap.ticker} / {snap.name} (CIK {snap.cik}) — {len(snap.metrics)} metrics, {len(snap.recent_filings)} filings",
            )
            return snap
        except Exception as exc:
            logger.warning("SEC enrichment failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="SEC EDGAR", status="error", note=str(exc))
            return None

    async def _yahoo(ticker: str | None) -> YahooQuote | None:
        if not ticker:
            return None
        BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="running", note=f"Fetching market and fundamentals data for {ticker}")
        try:
            q = await fetch_yahoo_quote(ticker)
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
            return False

        for cand in candidates:
            try:
                w = await fetch_wikipedia_summary(cand)
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

    async def _filing(snap: SECCompanySnapshot | None) -> FilingNarrative | None:
        if not snap:
            return None
        target_filing = next((f for f in snap.recent_filings if f.form in ("10-K", "20-F")), None)
        if not target_filing:
            target_filing = next((f for f in snap.recent_filings if f.form == "10-Q"), None)
        if not target_filing:
            return None
        BUS.emit(
            session_id,
            "agent_task",
            task="SEC filing",
            status="running",
            note=f"Fetching {target_filing.form} filed {target_filing.filing_date}",
        )
        try:
            nar = await asyncio.wait_for(
                fetch_filing_narrative(
                    target_filing.url, form=target_filing.form, filed_date=target_filing.filing_date
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="SEC filing", status="warning", note="Timed out (>30s)")
            return None
        except Exception as exc:
            logger.warning("Filing narrative fetch failed: %s", exc)
            BUS.emit(session_id, "agent_task", task="SEC filing", status="error", note=str(exc))
            return None
        if not nar or not nar.has_any():
            BUS.emit(session_id, "agent_task", task="SEC filing", status="warning", note="Sections not located")
            return None
        present = ", ".join(
            n for n in (("Item 1" if nar.business else None), ("Item 1A" if nar.risk_factors else None), ("Item 7" if nar.mdna else None)) if n
        )
        BUS.emit(
            session_id,
            "agent_task",
            task="SEC filing",
            status="done",
            note=f"{target_filing.form} sections extracted: {present}",
        )
        return nar

    async def _fx() -> FxRate | None:
        BUS.emit(session_id, "agent_task", task="FX (USD/INR)", status="running", note="Fetching live USD-INR")
        try:
            r = await get_usd_inr()
            BUS.emit(
                session_id,
                "agent_task",
                task="FX (USD/INR)",
                status="done",
                note=f"1 USD = ₹{r.rate:.4f} ({r.source})",
            )
            return r
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
            snap = await fetch_india_snapshot(_nse_sym)
            if snap:
                BUS.emit(session_id, "agent_task", task="NSE/Screener", status="done",
                         note=f"{snap.company_name or _nse_sym} — {len(snap.metrics)} metrics via {snap.source}")
            else:
                BUS.emit(session_id, "agent_task", task="NSE/Screener", status="warning",
                         note=f"No fundamentals data returned for {_nse_sym}")
            return snap
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
            filing_data = await fetch_sebi_filing(_nse_sym)
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
        except Exception as exc:
            logger.warning("SEBI filing fetch failed for %s: %s", _nse_sym, exc)
            BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="error", note=str(exc))
            return None

    async def _shareholding_fetch() -> dict | None:
        if not _is_india:
            return None
        try:
            data = await fetch_shareholding_pattern(_nse_sym)
            if data:
                p = data.get("promoter") or 0
                f = data.get("fii") or 0
                d = data.get("dii") or 0
                BUS.emit(session_id, "agent_task", task="Shareholding", status="done",
                         note=f"Promoter {p:.1f}% · FII {f:.1f}% · DII {d:.1f}%")
            return data
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

    # ── Parallel fan-out: ALL enrichment including SEC ────────────────────
    (
        sec_snap,
        india_snap_result,
        sebi_filing_result,
        shareholding_result,
        yahoo_quote,
        wiki,
        fx,
        reddit_posts,
        hn_stories,
        stocktwits_snap,
        news_items,
    ) = await asyncio.gather(
        _sec(),
        _india_snap(),
        _sebi_filing_fetch(),
        _shareholding_fetch(),
        _yahoo(ticker),
        _wiki(canonical_name),
        _fx(),
        _reddit(),
        _hn(),
        _stocktwits(ticker),
        _news(),
        return_exceptions=True,
    )

    # Resolve gather exceptions
    def _safe_sec(v):
        return None if isinstance(v, Exception) else v
    sec_snap = _safe_sec(sec_snap)

    # Upgrade ticker/canonical_name from SEC snap if available (US companies)
    if sec_snap:
        if sec_snap.ticker:
            ticker = sec_snap.ticker
        if sec_snap.name:
            canonical_name = sec_snap.name

    # Fetch SEC filing now that we have sec_snap (fast — just an HTTP call)
    sec_filing = None
    if sec_snap:
        try:
            sec_filing = await _filing(sec_snap)
        except Exception:
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
    reddit_posts        = _safe(reddit_posts) or []
    hn_stories          = _safe(hn_stories) or []
    stocktwits_snap     = _safe(stocktwits_snap)
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
        reddit=reddit_posts,
        hackernews=hn_stories,
        stocktwits=stocktwits_snap,
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
        reddit=_serialize_reddit(reddit_posts),
        hackernews=_serialize_hn(hn_stories),
        stocktwits=_serialize_stocktwits(stocktwits_snap),
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
                candidate.append((f"{display_ticker} NSE analyst target price broking report", "analyst coverage"))
            else:
                candidate.append((f"{canonical} analyst recommendation target price NSE India", "analyst coverage"))
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
        # Treat SEC EDGAR companyfacts as a corroborating primary-financial source.
        sources_for_validator.append(
            Source(name="data.sec.gov", tier=1, retrieved_at=datetime.now(timezone.utc), is_primary_financial=True)
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
    harness.maybe_persist_checkpoint(step, cp)


def _persist_session_memory(
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
) -> None:
    """Extract durable facts from this run and store them under the
    canonical target key so the next run starts smarter.

    We deliberately store *structured* facts (e.g. "FY2026 revenue =
    $215.94B per 10-K filed 2026-02-25") rather than full prose so
    recall is cheap and unambiguous.
    """
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
                source_url=f"https://data.sec.gov/submissions/CIK{sec.cik}.json",
                session_id=session_id,
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
                    source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sec.cik}",
                    session_id=session_id,
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
            )
        )
    memory_store.remember_many(new_facts)

    # Save a one-paragraph summary for "what was this run about?"
    n_docs = len(docs)
    n_domains = len({(d.final_url or d.url or "").split("/")[2] for d in docs if (d.final_url or d.url)})
    n_metrics = len(sec.metrics) if sec else 0
    summary = (
        f"Run for {canonical_label}: ingested {n_docs} docs from {n_domains} domains, "
        f"resolved {n_metrics} SEC metrics, scored {quality_score:.1f}/100 on the coverage rubric. "
        f"{len(conflicts or [])} cross-source conflicts. "
        f"{len(bundle.news or [])} news headlines, "
        f"{len(bundle.reddit or [])} Reddit posts, "
        f"{len(bundle.hackernews or [])} HN stories."
    )
    metrics_dict = {
        "docs": n_docs,
        "domains": n_domains,
        "sec_metrics": n_metrics,
        "conflicts": len(conflicts or []),
        "news": len(bundle.news or []),
        "reddit": len(bundle.reddit or []),
        "hackernews": len(bundle.hackernews or []),
    }
    memory_store.save_session_summary(
        session_id=session_id,
        target_key=target,
        target_display=canonical_label,
        summary=summary,
        metrics=metrics_dict,
        citation_count=len(cp.citation_log),
        quality_score=quality_score,
    )


async def run_research_session(
    target: str,
    objective: str,
    *,
    plan: ResearchPlan | None = None,
    loop_config: AgentLoopConfig | None = None,
) -> tuple[ResearchPlan, Checkpoint]:
    _ = default_system_prompt()
    pl = plan or build_default_plan(target, objective)
    cfg = loop_config or AgentLoopConfig()
    if cfg.auto_depth:
        cfg.max_steps = _auto_max_steps(objective, cfg.max_steps)
    session_id = cfg.session_id or str(uuid.uuid4())
    harness = Harness(HarnessConfig(session_id=session_id))
    cp = empty_checkpoint()
    validator = AccuracyValidator()
    entity = resolve_entity(target)
    preferred_domains = preferred_domains_for_entity(entity)
    try:
        playbook = retrieve_playbook(geography=entity.country_code, objective=objective)
    except Exception as exc:
        logger.warning("playbook retrieval failed: %s", exc)
        playbook = None
        BUS.emit(session_id, "warning", message=f"playbook retrieval failed: {exc}")
    retrieval_plan = build_retrieval_plan(entity, objective)
    retrieval_plan.breadth_queries = apply_playbook_to_queries(retrieval_plan.breadth_queries, playbook)
    routing = route_objective(
        objective,
        entity,
        playbook_agents=(playbook.selected_agents if playbook else None),
    )
    response_depth = normalize_depth(cfg.response_depth)
    output_mode = classify_output_mode(
        query=objective,
        target=target,
        entity=entity,
        depth=response_depth,
        explicit_mode=cfg.output_mode,
    )
    if routing.deep_research:
        cfg.max_steps = max(cfg.max_steps, 80)
        cfg.reflection_max_rounds = max(cfg.reflection_max_rounds, 6)
        cfg.blindspot_max_queries = max(cfg.blindspot_max_queries, 10)

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
        country_code=entity.country_code,
        preferred_domains=preferred_domains[:8],
        deep_research=routing.deep_research,
    )
    t0 = time.perf_counter()

    last_compression_step = 0
    docs: list[ScrapedDoc] = []
    step = 0

    # ── Phase 0: memory recall ─────────────────────────────────────────────
    memory_store = get_memory_store() if cfg.enable_memory else None
    recalled_facts: list[MemoryFact] = []
    last_summary: dict | None = None
    if memory_store is not None:
        BUS.emit(session_id, "phase", phase="memory", note="Recalling prior facts and last session summary")
        try:
            recalled_facts = memory_store.recall(target, limit=cfg.memory_recall_limit)
            last_summary = memory_store.last_summary(target)
        except Exception as exc:
            logger.warning("memory recall failed: %s", exc)
            recalled_facts = []
            last_summary = None
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
        bundle = await _run_enrichment(target, session_id, entity=entity, news_timeout=cfg.news_timeout)

    # ── Phase 3: breadth survey ───────────────────────────────────────────
    canonical_label = bundle.sec.name if bundle.sec else (bundle.yahoo.name if bundle.yahoo and bundle.yahoo.name else entity.canonical_name or target)
    if cfg.enable_scraping:
        BUS.emit(session_id, "phase", phase="breadth-survey", note="Layered DuckDuckGo: filings / IR / earnings / competitors")

        def _on_query(q: str, status: str, count: int) -> None:
            BUS.emit(session_id, "query", query=q, status=status, count=count)

        try:
            docs = await asyncio.wait_for(
                search_layered(
                    canonical_label,
                    on_query=_on_query,
                    queries=retrieval_plan.breadth_queries,
                    preferred_domains=preferred_domains,
                    entity=entity,
                ),
                timeout=cfg.breadth_search_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("search_layered timed out")
            BUS.emit(session_id, "warning", message=f"breadth-survey timed out after {cfg.breadth_search_timeout:.0f}s")
            docs = []
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
    if cfg.enable_scraping and cfg.enable_deep_dive and step < cfg.max_steps:
        BUS.emit(session_id, "phase", phase="deep-dive", note="Iterative gap-driven queries")

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
            if step >= cfg.max_steps:
                break
            followups = _build_followup_queries(canonical_label, docs, bundle.sec, round_index=round_index)
            if not followups:
                continue
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
    if cfg.enable_reflection and cfg.enable_scraping:
        BUS.emit(
            session_id,
            "phase",
            phase="reflection",
            note=f"Self-critique loop · target ≥{cfg.quality_threshold:.0f} quality",
        )
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
            )
            step = step_ref["v"]
            reflection_payload = ref_result.to_dict()
            BUS.emit(session_id, "reflection_done", **reflection_payload)
        except Exception as exc:
            logger.warning("reflection loop failed: %s", exc)
            BUS.emit(session_id, "warning", message=f"reflection loop failed: {exc}")

    # ── Phase 4.7: Multi-agent dispatch (parallel specialists + verifier) ──
    orchestration_payload = None
    blindspot_payload = None
    orchestration_findings: list = []
    if cfg.enable_multi_agent and cfg.enable_scraping:
        BUS.emit(
            session_id,
            "phase",
            phase="multi-agent",
            note="Dispatching specialist subagents in parallel + verifier pass",
        )

        def _emit_event(event_type: str, **payload) -> None:
            BUS.emit(session_id, event_type, **payload)

        seen_urls = {(d.final_url or d.url or "").split("#", 1)[0] for d in docs}
        ctx = SubAgentContext(
            target=target,
            canonical_label=canonical_label,
            objective=objective,
            bundle=bundle,
            seed_docs=docs,
            session_id=session_id,
            seen_urls=seen_urls,
            resolved_entity=entity,
            preferred_domains=preferred_domains,
        )

        try:
            allowed_agents = set(routing.selected_agents)
            roster = [agent for agent in default_roster() if agent.name in allowed_agents] or default_roster()
            orchestrator = Orchestrator(
                roster,
                emit=_emit_event,
                per_agent_deadline_ms=cfg.agent_deadline_ms,
            )
            orch_result = await orchestrator.run(ctx)
            orchestration_findings = list(orch_result.findings)
            orchestration_payload = orch_result.to_dict()

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
            verifier_report = verifier.run(
                findings=orchestration_findings,
                docs=docs,
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
                spots = detect_blind_spots(
                    target_label=canonical_label,
                    findings=orchestration_findings,
                    seed_docs=docs,
                    top_n=6,
                )
                blindspot_payload = {"blindspots": [s.to_dict() for s in spots]}
                _emit_event(
                    "blindspot",
                    blindspot_count=len(spots),
                    blindspots=blindspot_payload["blindspots"],
                )
                if spots:
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

                    batches = await asyncio.gather(*(_bs_one(q) for q in fanout))
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
                    blindspot_payload["new_docs"] = bs_new
                    _emit_event("blindspot_dispatched", new_docs=bs_new, queries=len(fanout))
            except Exception as exc:
                logger.warning("blindspot pass failed: %s", exc)

    # ── Phase 5: analysis ─────────────────────────────────────────────────
    BUS.emit(session_id, "phase", phase="analysis", note="Cross-source conflict detection")
    conflicts = detect_conflicts(docs)
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
    if cfg.emit_memo:
        BUS.emit(
            session_id,
            "phase",
            phase="synthesis",
            note=f"Composing {output_mode.value.replace('_', ' ')} answer",
        )

        def _on_memo_token(chunk: str) -> None:
            BUS.emit(session_id, "memo_token", chunk=chunk)

        synthesis = await synthesize_memo(
            target,
            objective,
            docs,
            cp,
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
        )
        memos_dir = finagent_data_path("memos")
        memos_dir.mkdir(parents=True, exist_ok=True)
        memo_path = memos_dir / f"{session_id}.md"
        memo_path.write_text(synthesis.memo, encoding="utf-8")

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
            _persist_session_memory(
                memory_store,
                session_id=session_id,
                target=target,
                canonical_label=canonical_label,
                bundle=bundle,
                docs=docs,
                cp=cp,
                conflicts=conflicts,
                quality_score=final_quality.score,
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

    _final_payload = dict(
        target=target,
        canonical=canonical_label,
        steps=cp.step,
        citations=len(cp.citation_log),
        primary_citations=primary_count,
        confidence_summary=cp.confidence_summary,
        compressed_at=last_compression_step,
        memo_path=str(memo_path) if memo_path else "",
        memo_via=synthesis.via if synthesis else "suppressed",
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
    )
    # Attach rich structured data (comparison tables, charts) so the frontend
    # final handler can render them even if visual_data_ready was insufficient.
    if synthesis and getattr(synthesis, "rich", None):
        _final_payload["rich"] = synthesis.rich

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
        "Session finished at step %s with %d citations; memo via %s",
        cp.step,
        len(cp.citation_log),
        synthesis.via if synthesis else "suppressed",
    )
    return pl, cp
