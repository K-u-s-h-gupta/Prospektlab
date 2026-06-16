from __future__ import annotations

import re

from finagent.geo.entity_resolver import ResolvedEntity, resolve_entities
from finagent.output.contracts import OutputMode, ResponseDepth
from finagent.output.query_guards import is_portfolio_comparison_query


_COMPARE_TERMS = ("compare", " vs ", " versus ", "peer", "peers", "against")
_VALUATION_TERMS = ("valuation", "dcf", "wacc", "intrinsic", "fair value", "target price", "cagr", "capm", "ddm")
_NEWS_TERMS = ("news", "latest", "headline", "today", "recent", "update")
_PRICE_HISTORY_TERMS = ("historical price", "price history", "stock history", "share price history", "past price")
_FILING_TERMS = ("drhp", "rhp", "prospectus", "annual report", "filing", "risk factors")
_VERSION_TERMS = ("changes", "changed", "compare documents", "from drhp to rhp", "version")
_INVESTMENT_TERMS = ("should i buy", "buy", "sell", "hold", "invest", "recommendation")
_MARKET_TERMS = ("rbi", "nifty", "sensex", "sector", "market", "bond", "yield", "rupee", "inflation", "fii", "dii")
_FORENSIC_TERMS = ("forensic", "anomaly", "anomalies", "manipulation", "earnings quality", "accounting check", "red flag", "restatement")
_OWNERSHIP_TERMS = ("shareholding", "shareholding pattern", "promoter", "pledge", "pledged shares", "ownership", "fii", "dii")
_GOVERNANCE_TERMS = ("governance", "board", "director", "directors", "auditor", "auditors", "management")
_RISK_TERMS = ("risk", "regulatory", "litigation", "investigation", "controversy")
_HISTORY_TERMS = ("historical", "timeline", "last 3 years", "last 5 years", "last five years", "over the last")
_BROAD_ANALYSIS_TERMS = ("comprehensive", "deep-dive", "deep dive", "in-depth", "detailed", "full analysis")
_TEMPORAL_COMPARE_PATTERN = re.compile(
    r"\b(?:vs|versus|against|compared?\s+to)\s+"
    r"(?:the\s+)?(?:last|past|previous|prior|current|historical|history|timeline|"
    r"\d{1,2}\s*(?:-| )?(?:year|years|quarter|quarters|month|months|q[1-4]))\b",
    re.I,
)


def normalize_depth(value: str | None) -> ResponseDepth:
    lower = (value or "").strip().lower()
    if lower == "marathon":
        return ResponseDepth.DEEP
    if lower == "deep":
        return ResponseDepth.DEEP
    if lower == "standard":
        return ResponseDepth.STANDARD
    return ResponseDepth.CHAT


def classify_output_mode(
    *,
    query: str,
    target: str,
    entity: ResolvedEntity | None = None,
    depth: ResponseDepth = ResponseDepth.CHAT,
    explicit_mode: str | None = None,
) -> OutputMode:
    if explicit_mode == "chat":
        return OutputMode.CONVERSATIONAL_CHAT
        
    if explicit_mode:
        try:
            return OutputMode(explicit_mode)
        except ValueError:
            pass

    lower = f"{query or ''} {target or ''}".lower()

    # ── Comparison detection takes priority over depth override ──
    # "TCS vs Infosys" should always produce a comparison, even in deep mode
    # But portfolio-vs-benchmark queries must NOT be misclassified as company comparisons.
    if _is_company_comparison_query(query, target, lower=lower):
        return OutputMode.COMPANY_COMPARISON

    if depth == ResponseDepth.DEEP:
        return OutputMode.DEEP_RESEARCH_REPORT

    if any(term in lower for term in _PRICE_HISTORY_TERMS):
        return OutputMode.CONVERSATIONAL_CHAT
    if any(term in lower for term in _FILING_TERMS):
        filing_versions = sum(1 for term in ("drhp", "rhp", "prospectus") if term in lower)
        if filing_versions >= 2 or (any(term in lower for term in _VERSION_TERMS) and ("drhp" in lower or "rhp" in lower)):
            return OutputMode.DOCUMENT_VERSION_COMPARISON
        return OutputMode.FILING_ANALYSIS
    if any(term in lower for term in _FORENSIC_TERMS):
        return OutputMode.FORENSIC_INSIGHTS
    ownership_or_governance = any(term in lower for term in _OWNERSHIP_TERMS + _GOVERNANCE_TERMS)
    if ownership_or_governance:
        multifactor_signals = sum(
            1
            for flag in (
                any(term in lower for term in _VALUATION_TERMS),
                any(term in lower for term in _NEWS_TERMS),
                any(term in lower for term in _RISK_TERMS),
                any(term in lower for term in _HISTORY_TERMS),
            )
            if flag
        )
        broad_analysis = any(term in lower for term in _BROAD_ANALYSIS_TERMS)
        if depth in {ResponseDepth.STANDARD, ResponseDepth.DEEP} and (multifactor_signals >= 2 or broad_analysis):
            return OutputMode.COMPANY_SNAPSHOT
        return OutputMode.DIRECT_ANSWER
    if any(term in lower for term in _VALUATION_TERMS):
        return OutputMode.VALUATION_INSIGHTS
    if any(term in lower for term in _NEWS_TERMS):
        return OutputMode.NEWS_BRIEF
    if any(term in lower for term in _INVESTMENT_TERMS):
        return OutputMode.INVESTMENT_VIEW
    if any(term in lower for term in _MARKET_TERMS) and not _looks_like_bare_company(target):
        return OutputMode.MARKET_EXPLAINER
    return OutputMode.COMPANY_SNAPSHOT if _looks_like_bare_company(target) or entity else OutputMode.CONVERSATIONAL_CHAT


def extract_finance_entities(query: str, *, limit: int = 4) -> list[ResolvedEntity]:
    """Best-effort entity extraction for finance chat queries.

    This intentionally stays lightweight and deterministic. It recognizes
    known Indian aliases/tickers plus explicit exchange suffixes, then falls
    back to a bare all-caps ticker if present.
    """
    return resolve_entities(query, limit=limit)


def primary_target_from_query(query: str) -> str:
    entities = extract_finance_entities(query, limit=1)
    if entities:
        return entities[0].canonical_name
    text = (query or "").strip()
    if not text:
        return ""
    candidate = re.sub(r"^(compare|analyze|analyse|research|review)\s+", "", text, flags=re.I).strip()
    lower = candidate.lower()
    cut_points = [lower.find(marker) for marker in (" drhp", " rhp", " prospectus", " annual report", " filing", " documents", " document") if lower.find(marker) > 0]
    if cut_points:
        candidate = candidate[: min(cut_points)].strip()
    candidate = re.sub(r"\b(company|limited company)\b$", "", candidate, flags=re.I).strip(" ,.-")
    if candidate and len(candidate.split()) <= 6:
        return candidate
    return text


def _looks_like_bare_company(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if len(text.split()) <= 4 and not re.search(r"\b(what|why|how|compare|news|latest|should|valuation|analyze)\b", text, re.I):
        return True
    return False


def _is_company_comparison_query(query: str, target: str, *, lower: str | None = None) -> bool:
    text = f"{query or ''} {target or ''}".strip()
    lower_text = lower if lower is not None else text.lower()

    if not any(term in lower_text for term in _COMPARE_TERMS):
        return False
    if is_portfolio_comparison_query(query):
        return False
    if _TEMPORAL_COMPARE_PATTERN.search(lower_text):
        return False

    # "peer(s)" intent is comparison-oriented even when no explicit second
    # entity is written in the query.
    if "peer" in lower_text or "peers" in lower_text:
        return True

    entities = resolve_entities(query or text, limit=4)
    unique_entities = {
        (e.normalized_name or e.canonical_name or "").strip().lower()
        for e in entities
        if (e.normalized_name or e.canonical_name or "").strip()
    }
    if len(unique_entities) >= 2:
        return True

    # Fallback for uppercase ticker-vs-ticker phrases.
    return bool(re.search(r"\b[A-Z]{2,12}\s*(?:vs|versus|against)\s*[A-Z]{2,12}\b", query or ""))


def classify_query_complexity(query: str, objective: str = "") -> dict:
    """Classify query complexity for mode routing.

    Returns {complexity: "simple"|"moderate"|"deep", intents: [...], needs_history: bool,
             needs_macro: bool, entity_count: int}.
    """
    combined = f"{query}\n{objective}".lower()
    words = combined.split()

    intents = []
    for label, terms in (
        ("valuation", _VALUATION_TERMS),
        ("news", _NEWS_TERMS),
        ("governance", _GOVERNANCE_TERMS),
        ("ownership", _OWNERSHIP_TERMS),
        ("risk", _RISK_TERMS),
        ("comparison", _COMPARE_TERMS),
        ("forensic", _FORENSIC_TERMS),
        ("market", _MARKET_TERMS),
        ("filing", _FILING_TERMS),
        ("history", _HISTORY_TERMS),
        ("investment", _INVESTMENT_TERMS),
    ):
        if any(t in combined for t in terms):
            intents.append(label)

    entities = resolve_entities(query, limit=6)
    needs_history = "history" in intents or bool(_TEMPORAL_COMPARE_PATTERN.search(combined))
    needs_macro = "market" in intents or any(t in combined for t in ("rbi", "inflation", "gdp", "fiscal", "monetary", "trade deficit"))

    if len(intents) >= 3 or any(t in combined for t in _BROAD_ANALYSIS_TERMS):
        complexity = "deep"
    elif len(intents) >= 2 or len(words) >= 28 or len(entities) >= 2:
        complexity = "moderate"
    else:
        complexity = "simple"

    return {
        "complexity": complexity,
        "intents": intents,
        "needs_history": needs_history,
        "needs_macro": needs_macro,
        "entity_count": len(entities),
    }
