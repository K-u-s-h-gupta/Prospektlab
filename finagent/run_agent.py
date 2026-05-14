"""Core agent loop.

Pipeline:
1. identify   — resolve target to SEC ticker / CIK if it's a US-listed entity
2. enrichment — pull authoritative JSON APIs in parallel (SEC EDGAR companyfacts,
                Yahoo Finance chart, Wikipedia REST summary)
3. breadth-survey — layered DuckDuckGo search across 4 angles
4. deep-dive — iterative targeted second-pass queries to fill gaps
5. analysis — cross-source conflict detection, viral scoring
6. synthesis — Claude / template memo using the *facts*, not just excerpts
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
from finagent.harness import Harness, HarnessConfig, compress_context_stub
from finagent.harness.context_manager import should_compress
from finagent.memory import MemoryFact, get_memory_store
from finagent.memory.store import normalize_target
from finagent.prompt_builder import default_system_prompt
from finagent.research_planner import ResearchPlan, build_default_plan
from finagent.state.checkpoint import Checkpoint, StepResult, empty_checkpoint
from finagent.state.citation_log import Citation
from finagent.synthesis import EnrichmentBundle, synthesize_memo
from finagent.tools.data import (
    FilingNarrative,
    FxRate,
    HNStory,
    NewsItem,
    RedditPost,
    SECCompanySnapshot,
    SECTimeSeries,
    StockTwitsSnapshot,
    WikipediaSummary,
    YahooQuote,
    fetch_company_snapshot,
    fetch_filing_narrative,
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
    # ── Multi-agent orchestration ──
    enable_multi_agent: bool = True
    agent_deadline_ms: int = 45_000
    # Blind-spot pass: auto-dispatches follow-up queries for missing topics
    enable_blindspot: bool = True
    blindspot_max_queries: int = 8
    blindspot_per_query_timeout: float = 18.0


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
    # Always honour at least 40 steps so the deep-dive rounds have room.
    return max(40, int(base * complexity))


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
) -> EnrichmentBundle:
    """Fan-out to SEC, Yahoo, Wikipedia. None failures are non-fatal."""
    BUS.emit(session_id, "phase", phase="enrichment", note="Pulling authoritative APIs (SEC, Yahoo, Wikipedia)")

    async def _sec() -> SECCompanySnapshot | None:
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
        BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="running", note=f"Fetching live quote for {ticker}")
        try:
            q = await fetch_yahoo_quote(ticker)
            if q is None or q.price is None:
                BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="warning", note="No quote (rate-limited or unlisted)")
                return None
            chg = f"{q.change_pct:+.2f}%" if q.change_pct is not None else "—"
            BUS.emit(
                session_id,
                "agent_task",
                task="Yahoo Finance",
                status="done",
                note=f"{q.currency or ''} {q.price:,.2f} ({chg}) on {q.exchange or 'exchange'}",
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
            for suf in (" Inc.", " Inc", " Corp.", " Corp", " Corporation", " Company", " Co.", " plc", " Ltd.", " Ltd", " Holdings", " Group"):
                if n.lower().endswith(suf.lower()):
                    n = n[: -len(suf)].rstrip(" ,.")
                    break
            return n

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
            )
            return any(b in desc for b in bad_substrings) or any(b in title for b in bad_substrings)

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
        query = canonical_name or target
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
        query = canonical_name or target
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
        query = canonical_name or target
        BUS.emit(session_id, "agent_task", task="News headlines", status="running", note=f"Google News RSS for {query!r}")
        try:
            items = await asyncio.wait_for(fetch_news(query), timeout=15.0)
        except asyncio.TimeoutError:
            BUS.emit(session_id, "agent_task", task="News headlines", status="warning", note="Timed out (>15s)")
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

    sec_snap = await _sec()
    ticker = sec_snap.ticker if sec_snap else target.upper() if target.isalpha() and len(target) <= 5 else None
    canonical_name = sec_snap.name if sec_snap else None
    yahoo_quote, wiki, filing, fx, reddit_posts, hn_stories, stocktwits_snap, news_items = await asyncio.gather(
        _yahoo(ticker),
        _wiki(canonical_name),
        _filing(sec_snap),
        _fx(),
        _reddit(),
        _hn(),
        _stocktwits(ticker),
        _news(),
    )

    bundle = EnrichmentBundle(
        sec=sec_snap,
        yahoo=yahoo_quote,
        wikipedia=wiki,
        filing=filing,
        fx=fx,
        reddit=reddit_posts,
        hackernews=hn_stories,
        stocktwits=stocktwits_snap,
        news=news_items,
    )

    BUS.emit(
        session_id,
        "intel",
        sec=_serialize_sec(sec_snap),
        yahoo=_serialize_yahoo(yahoo_quote),
        wikipedia=_serialize_wiki(wiki),
        filing=_serialize_filing(filing),
        fx=_serialize_fx(fx),
        reddit=_serialize_reddit(reddit_posts),
        hackernews=_serialize_hn(hn_stories),
        stocktwits=_serialize_stocktwits(stocktwits_snap),
        news=_serialize_news(news_items),
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


def _serialize_sec(snap: SECCompanySnapshot | None) -> dict | None:
    if not snap:
        return None
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


_TIER1_NEWS = ("reuters.com", "wsj.com", "ft.com", "bloomberg.com", "cnbc.com", "barrons.com", "marketwatch.com")


def _build_followup_queries(
    target: str,
    docs: list[ScrapedDoc],
    sec_snap: SECCompanySnapshot | None,
    *,
    round_index: int = 0,
) -> list[str]:
    """Generate targeted follow-up queries based on what previous passes missed.

    Each round shifts emphasis: round 0 -> coverage gaps, round 1 -> entity
    expansion (competitors, suppliers, customers harvested from earlier docs),
    round 2 -> sentiment/community + earnings call detail.
    """
    canonical = (sec_snap.name if sec_snap else target).strip()
    ticker = (sec_snap.ticker if sec_snap else "").strip()
    industry = sec_snap.sic_description if (sec_snap and sec_snap.sic_description) else ""
    domains = {d.domain for d in docs}
    text_blob = " ".join((d.excerpt or "")[:600].lower() for d in docs)

    candidate: list[tuple[str, str]] = []

    if round_index == 0:
        if not any(d for d in domains if d.endswith(_TIER1_NEWS)):
            candidate.append((f"{canonical} latest news earnings reuters", "missing tier-1 news"))
        if "competit" not in text_blob and "market share" not in text_blob:
            if industry:
                candidate.append((f"{canonical} competitors in {industry}", "competitive landscape"))
            else:
                candidate.append((f"{canonical} competitors market share analysis", "competitive landscape"))
        if "risk" not in text_blob and "headwind" not in text_blob:
            candidate.append((f"{canonical} risk factors regulatory headwinds", "risk discussion"))
        if "analyst" not in text_blob and "price target" not in text_blob:
            if ticker:
                candidate.append((f"{ticker} analyst rating price target consensus", "analyst coverage"))
            else:
                candidate.append((f"{canonical} analyst outlook recommendation", "analyst coverage"))
        if "guidance" not in text_blob and "forecast" not in text_blob:
            candidate.append((f"{canonical} guidance forecast 2026", "forward guidance"))

    elif round_index == 1:
        # Entity expansion: pull capitalised proper nouns from earlier excerpts
        # and run targeted searches on the ones that look like peer companies.
        entities = _extract_entities(docs, exclude=(canonical, ticker))[:3]
        for ent in entities:
            candidate.append((f"{ent} vs {canonical} comparison earnings", f"peer deep-dive: {ent}"))
        candidate.append((f"{canonical} earnings call transcript Q&A", "earnings transcript"))
        if industry:
            candidate.append((f"{industry} industry outlook 2026 trends", "industry outlook"))

    elif round_index == 2:
        candidate.append((f"{canonical} insider trading SEC form 4", "insider activity"))
        candidate.append((f"{canonical} short interest data NASDAQ", "short interest"))
        candidate.append((f"{canonical} ESG controversy lawsuit settlement", "legal & ESG"))
        if ticker:
            candidate.append((f"{ticker} options unusual activity flow", "options flow"))

    else:  # round 3+
        candidate.append((f"{canonical} institutional holdings 13F", "institutional ownership"))
        candidate.append((f"{canonical} supply chain customers segments", "supply chain"))
        candidate.append((f"{canonical} R&D capex capital allocation", "capital allocation"))
        if ticker:
            candidate.append((f"{ticker} earnings beat miss surprise history", "earnings history"))

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
            new_facts.append(
                MemoryFact(
                    target_key=target,
                    kind="news_event",
                    body=f"{n.source}: {n.title} ({n.published})",
                    confidence="MEDIUM",
                    source_url=n.link,
                    session_id=session_id,
                )
            )
    for c in conflicts or []:
        new_facts.append(
            MemoryFact(
                target_key=target,
                kind="conflict",
                body=f"Cross-source disagreement on {c.metric}: spread {c.spread_pct:.1f}% — {c.note or ''}",
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

    BUS.emit(session_id, "session_started", target=target, objective=objective, plan=pl.to_prompt_block())
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
        bundle = await _run_enrichment(target, session_id)

    # ── Phase 3: breadth survey ───────────────────────────────────────────
    canonical_label = bundle.sec.name if bundle.sec else target
    if cfg.enable_scraping:
        BUS.emit(session_id, "phase", phase="breadth-survey", note="Layered DuckDuckGo: filings / IR / earnings / competitors")

        def _on_query(q: str, status: str, count: int) -> None:
            BUS.emit(session_id, "query", query=q, status=status, count=count)

        try:
            docs = await asyncio.wait_for(
                search_layered(canonical_label, on_query=_on_query),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            logger.warning("search_layered timed out")
            BUS.emit(session_id, "warning", message="breadth-survey timed out after 45s")
            docs = []
        except Exception as exc:
            logger.warning("search_layered failed: %s", exc)
            BUS.emit(session_id, "warning", message=f"search failed: {exc}")
            docs = []

    # ── Process round 1 ───────────────────────────────────────────────────
    initial_cap = max(cfg.max_steps // 2, 6) if cfg.enable_deep_dive else cfg.max_steps
    enrichment_present = bundle.sec is not None
    for doc in docs[:initial_cap]:
        step += 1
        await _process_doc(
            doc, step, cp, harness, validator, session_id,
            enrichment_corroborates=enrichment_present,
        )
        if should_compress(step, harness.settings.compression_interval_steps):
            _ = await compress_context_stub([d.excerpt for d in docs[:step]], cp)
            last_compression_step = step
            BUS.emit(session_id, "compression", step=step)
        await asyncio.sleep(0)

    # ── Phase 4: deep-dive (multi-round iterative search) ─────────────────
    if cfg.enable_scraping and cfg.enable_deep_dive and step < cfg.max_steps:
        BUS.emit(session_id, "phase", phase="deep-dive", note="Iterative gap-driven queries")

        def _on_query(q: str, status: str, count: int) -> None:
            BUS.emit(session_id, "query", query=q, status=status, count=count)

        seen_urls = {(d.final_url or d.url).split("#", 1)[0] for d in docs}

        async def _one(q: str) -> list[ScrapedDoc]:
            _on_query(q, "running", 0)
            try:
                results = await asyncio.wait_for(search_web(q, max_results=6), timeout=25.0)
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
                *(_staggered_one(q, i * 0.3) for i, q in enumerate(followups))
            )
            new_in_round = 0
            for batch in followup_results:
                for d in batch:
                    key = (d.final_url or d.url).split("#", 1)[0]
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    docs.append(d)
                    if step >= cfg.max_steps:
                        break
                    step += 1
                    new_in_round += 1
                    await _process_doc(
                        d, step, cp, harness, validator, session_id,
                        enrichment_corroborates=enrichment_present,
                    )
                    await asyncio.sleep(0)
            # If a round yielded nothing fresh, stop iterating
            if new_in_round == 0:
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
            return await search_web(query, max_results=max_results)

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
        )

        try:
            roster = default_roster()
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
            for d in orch_result.new_docs:
                key = (d.final_url or d.url or "").split("#", 1)[0]
                if not key or key in {(x.final_url or x.url or "").split("#", 1)[0] for x in docs}:
                    continue
                docs.append(d)
                step += 1
                await _process_doc(
                    d, step, cp, harness, validator, session_id,
                    enrichment_corroborates=(bundle.sec is not None),
                )

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
                            r = await asyncio.wait_for(
                                search_web(q, max_results=4),
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
                    bs_new = 0
                    existing_keys = {(d.final_url or d.url or "").split("#", 1)[0] for d in docs}
                    for batch in batches:
                        for d in batch:
                            key = (d.final_url or d.url or "").split("#", 1)[0]
                            if not key or key in existing_keys:
                                continue
                            existing_keys.add(key)
                            docs.append(d)
                            step += 1
                            bs_new += 1
                            await _process_doc(
                                d, step, cp, harness, validator, session_id,
                                enrichment_corroborates=(bundle.sec is not None),
                            )
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
    BUS.emit(session_id, "phase", phase="synthesis", note="Composing memo")

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
    )
    memos_dir = Path.home() / ".finagent" / "memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    memo_path = memos_dir / f"{session_id}.md"
    memo_path.write_text(synthesis.memo, encoding="utf-8")

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    BUS.emit(
        session_id,
        "memo",
        via=synthesis.via,
        used_sources=synthesis.used_sources,
        chars=len(synthesis.memo),
        path=str(memo_path),
        preview=synthesis.memo[:2400],
    )
    # ── Persist learnings to long-term memory ─────────────────────────────
    final_quality = score_research(
        target=canonical_label,
        bundle=bundle,
        docs=docs,
        checkpoint=cp,
        conflicts=conflicts,
    )
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

    primary_count = sum(1 for c in cp.citation_log if c.kind == "primary")
    BUS.emit(
        session_id,
        "final",
        target=target,
        canonical=canonical_label,
        steps=cp.step,
        citations=len(cp.citation_log),
        primary_citations=primary_count,
        confidence_summary=cp.confidence_summary,
        compressed_at=last_compression_step,
        memo_path=str(memo_path),
        memo_via=synthesis.via,
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
    )
    BUS.close(session_id)

    logger.info(
        "Session finished at step %s with %d citations; memo via %s",
        cp.step,
        len(cp.citation_log),
        synthesis.via,
    )
    return pl, cp
