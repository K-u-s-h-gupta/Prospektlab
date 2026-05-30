"""
ORACLE FIOS - Intent Detection
==============================
Keyword sets and routing heuristics shared between api.py and rich_builder.py.

The goal is a single source of truth for "what kind of question is this?" so the
sub-agent planner and the structured rich-output builder agree on the response
mode (comparison / snapshot / valuation / news / filing / chat).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Keyword sets (kept lowercase, matched against query.lower())
# ---------------------------------------------------------------------------

VALUATION_TRIGGER_TERMS = {
    "valuation",
    "valued",
    "overvalued",
    "undervalued",
    "fair value",
    "intrinsic value",
    "dcf",
    "discounted cash flow",
    "wacc",
    "cagr",
    "graham",
    "piotroski",
    "altman",
    "z-score",
    "ev/ebitda",
    "dividend discount",
    "ddm",
    "dupont",
    "ratio scorecard",
}
CALCULATION_HINT_TERMS = {"calculate", "calculation", "model", "valuation model"}
VALUATION_CONTEXT_TERMS = {"stock", "share", "company", "equity", "ticker", "price", "return", "financial"}

NEWS_TRIGGER_TERMS = {"recent news", "latest news", "fetch news", "news", "headlines", "updates"}

EVENT_EXPLAINER_TRIGGER_TERMS = {
    "explain",
    "what happened",
    "case",
    "issue",
    "controversy",
    "lawsuit",
    "legal",
    "investigation",
    "fraud",
    "allegation",
    "hearing",
    "judgment",
    "order",
    "dispute",
    "scam",
    "why did",
    "reason for",
}

OFFER_DOCUMENT_TRIGGER_TERMS = {
    "drhp",
    "draft red herring prospectus",
    "rhp",
    "prospectus",
    "ipo",
    "offer document",
}

FUNDAMENTAL_TRIGGER_TERMS = {
    "financials",
    "fundamentals",
    "income statement",
    "balance sheet",
    "cash flow",
    "quarterly results",
    "shareholding",
    "dividend history",
    "roe",
    "margin",
    "margins",
}

DOCUMENT_ANALYSIS_TRIGGER_TERMS = {
    "risk",
    "risk factors",
    "business fundamentals",
    "business overview",
    "objects of the issue",
    "financial summary",
    "red flags",
}

MARKET_DATA_TRIGGER_TERMS = {"price", "quote", "market cap", "traded", "52-week"}
VISUAL_TRIGGER_TERMS = {"historical", "history", "trend", "chart", "graph", "visual", "show data", "show historical"}

FULL_ANALYSIS_TRIGGER_TERMS = {"full analysis", "complete analysis", "detailed analysis", "proper analysis"}

FORECAST_TRIGGER_TERMS = {"forecast", "forcast", "future", "outlook", "guidance", "target price"}

# Word-boundary matched comparison terms. Fixes recall hole where
# "TCS vs Infosys" (no surrounding spaces in match) used to miss.
_COMPARISON_REGEX = re.compile(
    r"\b(?:compare|comparison|compares|comparing|vs|versus|against|head[- ]to[- ]head)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Agent planning (mirrors api.py original behaviour but cleaner)
# ---------------------------------------------------------------------------

AGENT_SERVER_DEPENDENCIES: dict[str, list[str]] = {
    "market_data_agent": ["nse_india"],
    "fundamental_analysis_agent": ["fundamentals"],
    "comparison_agent": ["fundamentals"],
    "news_and_research_agent": ["research_news"],
    "document_retrieval_agent": ["docs_pipeline", "research_news"],
    "valuation_agent": ["valuation_engine"],
}


from finagent.output.query_guards import is_portfolio_comparison_query


def is_comparison_query(message: str) -> bool:
    return bool(_COMPARISON_REGEX.search(message or "")) and not is_portfolio_comparison_query(message)


def is_calculation_valuation_query(message: str) -> bool:
    lower = (message or "").lower()
    if any(term in lower for term in VALUATION_TRIGGER_TERMS):
        return True
    if re.search(r"\bp/?e\b", lower):
        return True
    return any(term in lower for term in CALCULATION_HINT_TERMS) and any(
        term in lower for term in VALUATION_CONTEXT_TERMS
    )


def planned_agents_for_message(message: str) -> list[str]:
    """Heuristic plan of which sub-agents will be needed.

    The supervisor LLM is free to deviate from this, but the plan is also
    used by rich_builder to choose which output mode to render. So even if
    a tool happens not to be called, we still announce a plausible plan.
    """
    lower = (message or "").lower()
    required_agents: list[str] = []
    is_offer_document_query = any(term in lower for term in OFFER_DOCUMENT_TRIGGER_TERMS)
    asks_for_news = any(term in lower for term in NEWS_TRIGGER_TERMS)
    asks_for_fundamentals = any(term in lower for term in FUNDAMENTAL_TRIGGER_TERMS)
    asks_for_document_analysis = any(term in lower for term in DOCUMENT_ANALYSIS_TRIGGER_TERMS)
    asks_for_full_analysis = any(term in lower for term in FULL_ANALYSIS_TRIGGER_TERMS)
    asks_for_forecast = any(term in lower for term in FORECAST_TRIGGER_TERMS)

    if is_comparison_query(message) and not is_offer_document_query:
        required_agents.append("comparison_agent")
    if is_calculation_valuation_query(message):
        required_agents.append("valuation_agent")
    if asks_for_forecast:
        required_agents.extend(["valuation_agent", "news_and_research_agent"])
    if asks_for_news:
        required_agents.append("news_and_research_agent")
    if is_offer_document_query:
        required_agents.append("document_retrieval_agent")
        if asks_for_document_analysis:
            required_agents.append("fundamental_analysis_agent")
    if asks_for_full_analysis:
        required_agents.extend(
            ["market_data_agent", "fundamental_analysis_agent", "news_and_research_agent"]
        )
    elif asks_for_fundamentals:
        required_agents.append("fundamental_analysis_agent")
    if asks_for_document_analysis:
        required_agents.append("document_retrieval_agent")
    if any(term in lower for term in MARKET_DATA_TRIGGER_TERMS):
        required_agents.append("market_data_agent")

    deduped: list[str] = []
    seen: set[str] = set()
    for agent in required_agents:
        if agent not in seen:
            seen.add(agent)
            deduped.append(agent)
    return deduped


# ---------------------------------------------------------------------------
# Output-mode classification for the rich builder
# ---------------------------------------------------------------------------

# Modes the frontend knows how to render. "chat" means rich=None and the
# frontend falls back to plain markdown only.
RICH_MODE_COMPARISON = "comparison"
RICH_MODE_SNAPSHOT = "snapshot"
RICH_MODE_VALUATION = "valuation"
RICH_MODE_NEWS = "news"
RICH_MODE_FILING = "filing"
RICH_MODE_DOC_COMPARE = "doc_compare"
RICH_MODE_CHAT = "chat"
PRIMARY_INTENT_COMPARISON = "comparison"
PRIMARY_INTENT_VALUATION = "valuation"
PRIMARY_INTENT_EVENT_EXPLAINER = "event_explainer"
PRIMARY_INTENT_NEWS = "news"
PRIMARY_INTENT_FILING = "filing"
PRIMARY_INTENT_SNAPSHOT = "snapshot"
PRIMARY_INTENT_VISUAL_ANALYSIS = "visual_analysis"
PRIMARY_INTENT_CHAT = "chat"


def detect_primary_intent(message: str) -> str:
    lower = (message or "").lower().strip()
    is_offer_document_query = any(term in lower for term in OFFER_DOCUMENT_TRIGGER_TERMS)

    if is_offer_document_query:
        return PRIMARY_INTENT_FILING
    if is_comparison_query(message):
        return PRIMARY_INTENT_COMPARISON
    if is_calculation_valuation_query(message):
        return PRIMARY_INTENT_VALUATION
    if any(term in lower for term in EVENT_EXPLAINER_TRIGGER_TERMS):
        return PRIMARY_INTENT_EVENT_EXPLAINER
    if any(term in lower for term in NEWS_TRIGGER_TERMS) and not any(term in lower for term in FULL_ANALYSIS_TRIGGER_TERMS):
        return PRIMARY_INTENT_NEWS
    if any(term in lower for term in VISUAL_TRIGGER_TERMS):
        return PRIMARY_INTENT_VISUAL_ANALYSIS
    if any(term in lower for term in FULL_ANALYSIS_TRIGGER_TERMS) or any(term in lower for term in FUNDAMENTAL_TRIGGER_TERMS) or any(term in lower for term in MARKET_DATA_TRIGGER_TERMS):
        return PRIMARY_INTENT_SNAPSHOT
    return PRIMARY_INTENT_CHAT


def classify_rich_mode(message: str) -> str:
    """Pick which RichResponse variant to assemble."""
    lower = (message or "").lower()
    primary_intent = detect_primary_intent(message)
    is_offer_document_query = any(term in lower for term in OFFER_DOCUMENT_TRIGGER_TERMS)
    if is_offer_document_query:
        # Document version comparison (DRHP vs RHP vs prospectus)
        filing_versions = sum(1 for term in ("drhp", "rhp", "prospectus") if term in lower)
        if filing_versions >= 2 or "changes" in lower or "compare documents" in lower:
            return RICH_MODE_DOC_COMPARE
        return RICH_MODE_FILING

    if primary_intent == PRIMARY_INTENT_COMPARISON:
        return RICH_MODE_COMPARISON

    if primary_intent == PRIMARY_INTENT_VALUATION:
        return RICH_MODE_VALUATION

    if primary_intent == PRIMARY_INTENT_EVENT_EXPLAINER:
        return RICH_MODE_CHAT

    if primary_intent == PRIMARY_INTENT_NEWS:
        return RICH_MODE_NEWS

    if primary_intent in {PRIMARY_INTENT_SNAPSHOT, PRIMARY_INTENT_VISUAL_ANALYSIS}:
        return RICH_MODE_SNAPSHOT

    return RICH_MODE_CHAT


def _looks_like_bare_company(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if len(text.split()) <= 4 and not re.search(
        r"\b(what|why|how|when|where|tell|explain|case|issue|news|compare|valuation|dcf|chart|graph|historical)\b", text, re.IGNORECASE
    ):
        return True
    return False


__all__ = [
    "AGENT_SERVER_DEPENDENCIES",
    "VALUATION_TRIGGER_TERMS",
    "CALCULATION_HINT_TERMS",
    "VALUATION_CONTEXT_TERMS",
    "NEWS_TRIGGER_TERMS",
    "EVENT_EXPLAINER_TRIGGER_TERMS",
    "OFFER_DOCUMENT_TRIGGER_TERMS",
    "FUNDAMENTAL_TRIGGER_TERMS",
    "DOCUMENT_ANALYSIS_TRIGGER_TERMS",
    "MARKET_DATA_TRIGGER_TERMS",
    "VISUAL_TRIGGER_TERMS",
    "FULL_ANALYSIS_TRIGGER_TERMS",
    "FORECAST_TRIGGER_TERMS",
    "RICH_MODE_COMPARISON",
    "RICH_MODE_SNAPSHOT",
    "RICH_MODE_VALUATION",
    "RICH_MODE_NEWS",
    "RICH_MODE_FILING",
    "RICH_MODE_DOC_COMPARE",
    "RICH_MODE_CHAT",
    "PRIMARY_INTENT_COMPARISON",
    "PRIMARY_INTENT_VALUATION",
    "PRIMARY_INTENT_EVENT_EXPLAINER",
    "PRIMARY_INTENT_NEWS",
    "PRIMARY_INTENT_FILING",
    "PRIMARY_INTENT_SNAPSHOT",
    "PRIMARY_INTENT_VISUAL_ANALYSIS",
    "PRIMARY_INTENT_CHAT",
    "is_comparison_query",
    "is_calculation_valuation_query",
    "detect_primary_intent",
    "planned_agents_for_message",
    "classify_rich_mode",
]
