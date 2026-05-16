from __future__ import annotations

from dataclasses import dataclass, field

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.geo.query_localizer import localize_search_query


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
    if any(term in lower for term in ("news", "headline", "update", "recent", "latest")):
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


def build_breadth_queries(entity: ResolvedEntity, objective: str) -> list[str]:
    base = entity.search_label
    cc = entity.country_code
    if cc == "IN":
        queries = [
            f"{base} annual report investor relations NSE BSE",
            f"{base} quarterly results investor presentation concall transcript",
            f"{base} NSE BSE filings shareholding pattern corporate governance",
            f"{base} Moneycontrol Screener Trendlyne financials",
        ]
    elif cc == "US":
        queries = [
            f"{base} SEC filing 10-K",
            f"{base} investor relations",
            f"{base} earnings transcript",
            f"{base} competitors market share",
        ]
    else:
        queries = [
            f"{base} annual report",
            f"{base} investor relations",
            f"{base} earnings transcript",
            f"{base} competitors market share",
        ]

    tags = _intent_tags(objective)
    if "risk" in tags:
        queries.append(f"{base} risk factors regulatory issues SEBI annual report")
    if "valuation" in tags:
        queries.append(f"{base} valuation multiples DCF analyst outlook peer comparison")
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
    return RetrievalPlan(
        objective=objective,
        preferred_domains=list(entity.profile.preferred_domains),
        breadth_queries=build_breadth_queries(entity, objective),
        routing_tags=_intent_tags(objective),
    )
