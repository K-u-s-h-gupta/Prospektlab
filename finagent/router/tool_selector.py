"""Intent-driven tool selector for India-focused FinAgent.

Maps the user's query intent (from the router) to the minimal set of
enrichment tools needed.  This prevents running Reddit/HN/StockTwits
for a simple PE-ratio lookup, dramatically cutting latency.
"""

from __future__ import annotations

from finagent.router.intent_router import RoutingDecision

# ── Tool sets ─────────────────────────────────────────────────────────────────

_ALL = frozenset([
    "india_snap", "yahoo", "shareholding", "sebi_filing",
    "news", "reddit", "hackernews", "stocktwits", "wikipedia", "fx",
])

_PRICE_ONLY        = frozenset(["india_snap", "yahoo"])
_FUNDAMENTALS      = frozenset(["india_snap", "yahoo", "wikipedia"])
_EARNINGS          = frozenset(["india_snap", "yahoo", "news"])
_RISK              = frozenset(["india_snap", "sebi_filing", "news", "reddit"])
_GOVERNANCE        = frozenset(["india_snap", "shareholding", "sebi_filing", "news"])
_SENTIMENT         = frozenset(["india_snap", "yahoo", "reddit", "stocktwits", "news"])
_SECTOR            = frozenset(["india_snap", "yahoo", "news", "hackernews"])
_NEWS_UPDATE       = frozenset(["news", "reddit", "hackernews"])
_COMPARISON        = frozenset(["india_snap", "yahoo", "news", "wikipedia"])
_FULL_RESEARCH     = _ALL
_IPO               = frozenset(["india_snap", "sebi_filing", "news", "wikipedia"])

# Keyword → tool-set mapping (ordered — first match wins)
_INTENT_RULES: list[tuple[tuple[str, ...], frozenset[str]]] = [
    # Price / quote only
    (("current price", "stock price", "share price", "live price",
      "what is the price", "nse price", "bse price"), _PRICE_ONLY),
    # Simple ratio lookups
    (("pe ratio", "p/e", "pb ratio", "p/b", "eps", "dividend yield",
      "book value", "market cap", "52 week", "52-week"), _FUNDAMENTALS),
    # Earnings / quarterly
    (("quarterly results", "earnings", "q4", "q3", "q2", "q1",
      "fy2025", "fy2026", "revenue growth", "profit growth",
      "net profit", "ebitda", "operating profit"), _EARNINGS),
    # Risk / regulatory
    (("risk", "sebi", "penalty", "investigation", "fraud",
      "lawsuit", "insider trading", "promoter pledge", "pledged"), _RISK),
    # Governance / shareholding
    (("shareholding", "fii", "dii", "promoter stake", "promoter holding",
      "institutional holding", "board", "management", "corporate governance"), _GOVERNANCE),
    # Sentiment / community
    (("sentiment", "reddit", "retail", "community", "stocktwits",
      "social media", "buzz"), _SENTIMENT),
    # News only
    (("news", "latest news", "recent news", "headline", "update",
      "announcement", "press release"), _NEWS_UPDATE),
    # Sector / macro
    (("sector", "industry", "macro", "interest rate", "rbi", "inflation",
      "crude", "commodity", "nifty", "sensex"), _SECTOR),
    # Comparison
    (("compare", "vs", "versus", "peer", "competitor"), _COMPARISON),
    # IPO
    (("ipo", "drhp", "rhp", "listing", "grey market premium",
      "gmp", "allotment", "issue price"), _IPO),
]


def select_tools(objective: str, routing: RoutingDecision) -> frozenset[str]:
    """Return the minimal tool set needed for this query.

    Always starts with the intent-matched set, then expands if the router
    has detected complex agents (risk, governance, community).
    """
    lower = (objective or "").lower()

    # Check intent rules
    for keywords, tool_set in _INTENT_RULES:
        if any(kw in lower for kw in keywords):
            selected = set(tool_set)
            # Expand if routing adds specialist agents
            if "risk" in routing.selected_agents:
                selected |= {"sebi_filing", "news", "reddit"}
            if "governance" in routing.selected_agents:
                selected |= {"shareholding", "sebi_filing"}
            if "community" in routing.selected_agents:
                selected |= {"reddit", "stocktwits", "hackernews"}
            if routing.deep_research or routing.query_complexity == "complex":
                selected = set(_FULL_RESEARCH)
            return frozenset(selected)

    # No specific intent detected — use complexity to decide
    if routing.query_complexity == "simple":
        return _FUNDAMENTALS
    if routing.query_complexity == "moderate":
        return _EARNINGS | _RISK
    return _FULL_RESEARCH
