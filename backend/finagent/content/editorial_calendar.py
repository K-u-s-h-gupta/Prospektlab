"""Idle-time editorial calendar engine.

When the official monitor has no breaking events, this module generates
15-20 daily articles/editorials across a LiveMint-calibrated topic mix.
Topics are drawn from market movers, IKG trending entities, scheduled
archetypes (pre-market wrap, post-close wrap), and upcoming events.

The daily target is env-tunable via FINAGENT_DAILY_EDITORIAL_TARGET (default 18).
Quality gates are never relaxed to hit quota — quota is a ceiling, not a mandate.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("finagent.content.editorial_calendar")

_IST = timezone(timedelta(hours=5, minutes=30))
_DAILY_TARGET = int(os.getenv("FINAGENT_DAILY_EDITORIAL_TARGET", "18"))
_DAILY_TARGET = max(10, min(25, _DAILY_TARGET))

# ── LiveMint-calibrated topic mix ─────────────────────────────────────────────
# Derived from LiveMint section structure: Markets, Companies, Economy, Money,
# Industry, Opinion. Each archetype has a daily quota and generation parameters.

EDITORIAL_ARCHETYPES: list[dict[str, Any]] = [
    {
        "id": "market_wrap_am",
        "name": "Pre-Market Wrap",
        "daily_quota": 1,
        "time_window": (7, 9),  # IST hours
        "content_type": "trend",
        "objective": "Pre-market outlook: global cues (US futures, Asian markets, crude, gold, USD-INR), "
                     "key events today (earnings, IPO listings, RBI MPC, expiry), SGX Nifty direction, "
                     "and sectors to watch. Data-dense, forward-looking, no filler.",
        "keywords": ["market", "nifty", "sensex", "pre-market", "sgx", "global cues"],
    },
    {
        "id": "market_wrap_pm",
        "name": "Post-Close Market Wrap",
        "daily_quota": 1,
        "time_window": (15, 17),
        "content_type": "trend",
        "objective": "Market close analysis: Nifty/Sensex levels, advance-decline, sectoral winners/losers, "
                     "FII/DII flows, top gainers/losers with reasons, VIX move, and what drove today's session. "
                     "Compare with yesterday. Include specific numbers.",
        "keywords": ["market", "close", "nifty", "sensex", "fii", "dii", "sectors"],
    },
    {
        "id": "stock_in_news",
        "name": "Stock in News",
        "daily_quota": 5,
        "time_window": (9, 18),
        "content_type": "company",
        "objective": "Deep-dive on a stock making news today — what happened (results, deal, order win, "
                     "regulatory action, block deal), historical context (3-quarter trend), peer comparison, "
                     "and what it means for the sector. Every claim must have a number and source.",
        "keywords": ["stock", "company", "results", "deal", "order", "block deal"],
    },
    {
        "id": "sector_deep_dive",
        "name": "Sector Deep Dive",
        "daily_quota": 3,
        "time_window": (10, 16),
        "content_type": "trend",
        "objective": "Sector analysis: industry dynamics, top players, recent regulatory changes, "
                     "demand-supply shifts, margin trends, capex cycles, and relative valuation vs history. "
                     "At least 3 companies compared with specific metrics.",
        "keywords": ["sector", "industry", "valuation", "margin", "capex"],
    },
    {
        "id": "economy_policy",
        "name": "Economy & Policy",
        "daily_quota": 3,
        "time_window": (8, 17),
        "content_type": "trend",
        "objective": "Macro/policy analysis: RBI monetary policy implications, inflation data, GDP trends, "
                     "fiscal deficit, GST collections, trade balance, PLI scheme progress, or regulatory "
                     "change impact. Historical comparison mandatory. Forward-looking close.",
        "keywords": ["economy", "rbi", "inflation", "gdp", "fiscal", "gst", "policy"],
    },
    {
        "id": "explainer",
        "name": "Market Explainer",
        "daily_quota": 2,
        "time_window": (10, 18),
        "content_type": "manual",
        "objective": "Educational explainer on a timely financial concept or market mechanism: "
                     "how F&O expiry works, what FII flows mean, how to read quarterly results, "
                     "SEBI regulation impact, or a sector-specific primer. Clear, jargon-defined, "
                     "with real Indian market examples.",
        "keywords": ["explainer", "how", "what", "guide", "primer"],
    },
    {
        "id": "earnings_preview",
        "name": "Earnings Preview/Review",
        "daily_quota": 2,
        "time_window": (8, 18),
        "content_type": "earnings",
        "objective": "Earnings season analysis: upcoming results to watch OR review of latest quarterly "
                     "numbers. Street expectations vs delivery, margin trajectory, guidance changes, "
                     "and sector read-through. Specific EPS/revenue/margin numbers required.",
        "keywords": ["earnings", "results", "quarterly", "revenue", "margin", "eps"],
    },
    {
        "id": "editorial_opinion",
        "name": "Editorial / Opinion",
        "daily_quota": 1,
        "time_window": (12, 18),
        "content_type": "trend",
        "objective": "Analytical editorial: a strong thesis on a market trend, regulatory shift, or "
                     "structural change with evidence-backed reasoning. Must present both sides, "
                     "use historical precedent, and end with a clear forward-looking thesis. "
                     "Written in authoritative first-person-plural voice.",
        "keywords": ["editorial", "opinion", "analysis", "thesis", "trend"],
    },
]


def get_daily_plan(
    now: datetime | None = None,
    published_today: int = 0,
    existing_slugs: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build today's editorial plan based on archetypes and remaining quota."""
    now = now or datetime.now(_IST)
    hour = now.hour
    remaining = max(0, _DAILY_TARGET - published_today)
    if remaining == 0:
        return []

    plan: list[dict[str, Any]] = []
    for archetype in EDITORIAL_ARCHETYPES:
        window_start, window_end = archetype["time_window"]
        if hour < window_start or hour > window_end:
            continue
        for _ in range(archetype["daily_quota"]):
            if len(plan) >= remaining:
                break
            plan.append({
                "archetype_id": archetype["id"],
                "name": archetype["name"],
                "content_type": archetype["content_type"],
                "objective": archetype["objective"],
                "keywords": archetype["keywords"],
            })

    random.shuffle(plan)
    return plan[:remaining]


async def pick_topic_for_archetype(
    archetype: dict[str, Any],
    *,
    market_movers: list[dict[str, Any]] | None = None,
    trending_entities: list[str] | None = None,
    upcoming_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Select a specific topic for an archetype slot using available market data."""
    archetype_id = archetype.get("archetype_id", "")
    base_objective = archetype.get("objective", "")
    content_type = archetype.get("content_type", "trend")

    target = ""
    topic_context = ""

    if archetype_id in ("stock_in_news", "earnings_preview"):
        if market_movers:
            mover = market_movers.pop(0) if market_movers else {}
            target = mover.get("symbol") or mover.get("name") or ""
            change = mover.get("change_pct") or mover.get("change") or ""
            topic_context = f"Stock moved {change}% today. " if change else ""
        elif trending_entities:
            target = trending_entities.pop(0) if trending_entities else ""
    elif archetype_id == "sector_deep_dive":
        sectors = ["IT", "Banking", "Pharma", "Auto", "FMCG", "Metals", "Energy", "Realty", "Infra", "Chemical"]
        target = random.choice(sectors) + " sector"
    elif archetype_id == "economy_policy":
        topics = [
            "RBI monetary policy implications",
            "India inflation trajectory",
            "GST collection trends",
            "India trade balance dynamics",
            "PLI scheme progress update",
            "Fiscal deficit management",
            "India GDP growth outlook",
        ]
        target = random.choice(topics)
    elif archetype_id == "editorial_opinion":
        themes = [
            "India's manufacturing renaissance",
            "Financialization of savings trend",
            "Regulatory tightening cycle",
            "India's energy transition capex",
            "Small-cap valuation premium",
        ]
        target = random.choice(themes)
    elif archetype_id in ("market_wrap_am", "market_wrap_pm"):
        target = "Indian equity markets"
    elif archetype_id == "explainer":
        concepts = [
            "F&O expiry and market impact",
            "Reading quarterly results",
            "FII vs DII flows explained",
            "Promoter pledging risks",
            "SEBI regulations for retail investors",
            "How IPO allotment works",
        ]
        target = random.choice(concepts)
    else:
        target = archetype.get("name", "market analysis")

    if not target:
        target = archetype.get("name", "Indian markets")

    objective = f"{topic_context}{base_objective}"

    return {
        "target": target,
        "objective": objective,
        "content_type": content_type,
        "archetype_id": archetype_id,
        "archetype_name": archetype.get("name", ""),
        "keywords": archetype.get("keywords", []),
    }


async def generate_editorial_batch(
    plan: list[dict[str, Any]],
    *,
    market_movers: list[dict[str, Any]] | None = None,
    trending_entities: list[str] | None = None,
    route_base: str = "insights",
    requested_by: str = "editorial_calendar",
    job_id: str = "",
) -> dict[str, Any]:
    """Generate a batch of editorial articles from the daily plan.

    Returns summary with generated/published/draft counts.
    Imports flash_engine lazily to avoid circular imports.
    """
    from finagent.content.flash_engine import FlashGenerationRequest, generate_flash_article

    movers = list(market_movers or [])
    entities = list(trending_entities or [])
    generated = 0
    published = 0
    drafts = 0
    errors = 0

    for item in plan:
        try:
            topic = await pick_topic_for_archetype(
                item,
                market_movers=movers,
                trending_entities=entities,
            )

            req = FlashGenerationRequest(
                target=topic["target"],
                content_type=topic["content_type"],
                mode="flash",
                objective=topic["objective"],
                include_image=True,
                route_base=route_base,
            )

            result = await generate_flash_article(
                req,
                job_id=job_id or f"editorial-{topic['archetype_id']}",
                requested_by=requested_by,
            )

            generated += 1
            status = getattr(result, "publish_status", "") or str(getattr(result, "status", ""))
            if status == "published":
                published += 1
            else:
                drafts += 1

            logger.info(
                "[EDITORIAL] %s | target=%s | status=%s",
                topic["archetype_name"],
                topic["target"][:50],
                status,
            )

        except Exception as exc:
            errors += 1
            logger.warning("[EDITORIAL] Failed to generate %s: %s", item.get("name", ""), exc)

    return {
        "generated": generated,
        "published": published,
        "drafts": drafts,
        "errors": errors,
        "plan_size": len(plan),
    }
