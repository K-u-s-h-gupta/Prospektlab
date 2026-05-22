from __future__ import annotations

import logging
from dataclasses import dataclass, field

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.geo.query_localizer import localize_search_query

logger = logging.getLogger("finagent.retrieval.planner")


@dataclass
class RetrievalPlan:
    objective: str
    preferred_domains: list[str] = field(default_factory=list)
    breadth_queries: list[str] = field(default_factory=list)
    routing_tags: list[str] = field(default_factory=list)


def _intent_tags(objective: str) -> list[str]:
    lower = (objective or "").lower()
    tags: list[str] = []
    if any(term in lower for term in ("compare", "vs", "competitor", "peer", "against")):
        tags.append("comparison")
    if any(term in lower for term in ("risk", "lawsuit", "investigation", "concern", "red flag")):
        tags.append("risk")
    if any(term in lower for term in ("valuation", "dcf", "overvalued", "undervalued", "intrinsic value", "multiple")):
        tags.append("valuation")
    if any(term in lower for term in ("historical price", "price history", "stock history", "share price history", "past price")):
        tags.append("price_history")
    financial_context = any(term in lower for term in ("financial", "results", "earnings", "quarterly", "profit", "revenue"))
    if (
        any(term in lower for term in ("news", "headline", "headlines", "media"))
        or (any(term in lower for term in ("update", "recent", "latest", "development")) and not financial_context)
    ):
        tags.append("news")
    if any(term in lower for term in ("governance", "board", "insider", "management")):
        tags.append("governance")
    if any(term in lower for term in ("transcript", "concall", "commentary", "earnings call")):
        tags.append("transcript")
    if any(term in lower for term in ("ipo", "drhp", "rhp", "prospectus", "red herring")):
        tags.append("filing")
    if any(term in lower for term in ("nifty", "sensex", "rbi", "inflation", "rupee", "fii", "dii", "bond", "yield")):
        tags.append("market")
    return tags


def _is_small_cap_target(entity: ResolvedEntity, objective: str) -> bool:
    lower = f"{objective or ''} {entity.canonical_name or ''} {entity.ticker_label or ''}".lower()
    if any(term in lower for term in ("sme", "emerge", "small cap", "small-cap", "microcap", "micro-cap")):
        return True
    return getattr(entity, "market_segment", "") in {"sme_or_smallcap", "mid_or_smallcap"}


def _direct_query(base: str, entity: ResolvedEntity, objective: str) -> str:
    """Avoid duplicating the company name when the follow-up is already self-contained."""

    text = (objective or "").strip()
    if not text:
        return base
    lower = text.lower()
    known_labels = {
        (base or "").lower(),
        (entity.canonical_name or "").lower(),
        (entity.normalized_name or "").lower(),
        (entity.ticker_label or "").lower(),
    }
    if any(label and label in lower for label in known_labels):
        return text
    return f"{base} {text}"


def _focused_queries(entity: ResolvedEntity, objective: str, tags: list[str]) -> list[str] | None:
    """Narrow follow-ups should not fan out into full company-research discovery."""

    base = entity.search_label
    blocking_tags = {"comparison", "risk", "filing", "market", "transcript", "governance"}
    if "news" in tags and not (blocking_tags & set(tags)):
        return [
            _direct_query(base, entity, objective),
            f"{base} latest news Moneycontrol Economic Times Mint",
            f"{base} recent developments NSE BSE corporate announcement",
            f"{base} stock exchange announcement today NSE BSE",
        ]
    if "valuation" in tags and "comparison" not in tags:
        return [
            _direct_query(base, entity, objective),
            f"{base} valuation PE PB EV EBITDA market cap Trendlyne Screener",
            f"{base} analyst target price rating Moneycontrol Economic Times",
            f"{base} peer valuation multiples India NSE BSE",
        ]
    if "price_history" in tags:
        return [
            _direct_query(base, entity, objective),
            f"{base} historical share price NSE BSE chart",
            f"{base} stock price history 1 month 1 year Yahoo Finance",
            f"{base} Moneycontrol price chart historical data",
        ]
    return None


def build_breadth_queries(entity: ResolvedEntity, objective: str) -> list[str]:
    base = entity.search_label
    tags = _intent_tags(objective)
    focused = _focused_queries(entity, objective, tags)
    if focused is not None:
        return [localize_search_query(q, entity) for q in focused[:4]]
    elif _is_small_cap_target(entity, objective):
        queries = [
            f"{base} SEBI LODR Regulation 33 financial results NSE BSE",
            f"{base} outcome of board meeting financial results NSE BSE",
            f"{base} Regulation 30 corporate announcement NSE BSE",
            f"{base} Regulation 31 shareholding pattern promoter pledge NSE BSE",
            f"{base} annual report PDF NSE BSE",
            f"{base} NSE Emerge BSE SME board financial results",
        ]
    else:
        queries = [
            f"{base} annual report NSE BSE SEBI LODR",
            f"{base} quarterly results investor presentation concall transcript",
            f"{base} NSE BSE filings shareholding pattern corporate governance",
            f"{base} Moneycontrol Screener Trendlyne financials",
        ]

    # If the objective is a specific question or phrase (not just the company name),
    # prioritize a direct search for it. This is critical for follow-up chat queries.
    if objective and objective.lower().strip() not in (base.lower(), entity.normalized_name.lower(), ""):
        direct = _direct_query(base, entity, objective)
        if direct not in queries:
            queries.insert(0, direct)


    if "risk" in tags:
        queries.append(f"{base} risk factors regulatory issues SEBI annual report")
    if "valuation" in tags:
        queries.append(f"{base} valuation multiples DCF analyst outlook peer comparison")
    if "price_history" in tags:
        queries.append(f"{base} historical share price NSE BSE chart")
    if "news" in tags:
        queries.append(f"{base} latest news Economic Times Mint Moneycontrol")
    if "comparison" in tags:
        queries.append(f"{base} peers competitors market share margins valuation")
    if "filing" in tags:
        queries.append(f"{base} DRHP RHP prospectus SEBI IPO changes")
    if "market" in tags:
        queries.append(f"{base} India market macro RBI Nifty Sensex impact")
    return [localize_search_query(q, entity) for q in queries[:8]]


def build_retrieval_plan(entity: ResolvedEntity, objective: str) -> RetrievalPlan:
    logger.info("Initializing retrieval plan for objective: '%s'", objective)
    logger.info("Resolved entity: %s (Ticker: %s, Search Label: %s)", 
                entity.canonical_name, entity.ticker_label, entity.search_label)
    
    tags = _intent_tags(objective)
    logger.info("Detected routing tags/intents: %s", tags)
    
    breadth = build_breadth_queries(entity, objective)
    logger.info("Generated %d breadth queries for research phase:", len(breadth))
    for i, q in enumerate(breadth, 1):
        logger.info("  Query %d: '%s'", i, q)
        
    pref_domains = list(entity.profile.preferred_domains)
    logger.info("Preferred domains for this entity: %s", pref_domains)
    
    return RetrievalPlan(
        objective=objective,
        preferred_domains=pref_domains,
        breadth_queries=breadth,
        routing_tags=tags,
    )
