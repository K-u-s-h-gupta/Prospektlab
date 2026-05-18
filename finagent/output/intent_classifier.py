from __future__ import annotations

import re

from finagent.geo.entity_resolver import ResolvedEntity, resolve_entity
from finagent.geo.ticker_mapper import _ALIAS_TICKERS
from finagent.output.contracts import OutputMode, ResponseDepth


_COMPARE_TERMS = ("compare", " vs ", " versus ", "peer", "peers", "against")
_VALUATION_TERMS = ("valuation", "dcf", "wacc", "intrinsic", "fair value", "target price", "cagr", "capm", "ddm")
_NEWS_TERMS = ("news", "latest", "headline", "today", "recent", "update")
_FILING_TERMS = ("drhp", "rhp", "prospectus", "annual report", "filing", "risk factors")
_VERSION_TERMS = ("changes", "changed", "compare documents", "from drhp to rhp", "version")
_INVESTMENT_TERMS = ("should i buy", "buy", "sell", "hold", "invest", "recommendation")
_MARKET_TERMS = ("rbi", "nifty", "sensex", "sector", "market", "bond", "yield", "rupee", "inflation", "fii", "dii")


def normalize_depth(value: str | None) -> ResponseDepth:
    lower = (value or "").strip().lower()
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
        return OutputMode.DIRECT_ANSWER
        
    if explicit_mode:
        try:
            return OutputMode(explicit_mode)
        except ValueError:
            pass

    lower = f"{query or ''} {target or ''}".lower()

    # ── Comparison detection takes priority over depth override ──
    # "TCS vs Infosys" should always produce a comparison, even in deep mode
    if any(term in lower for term in _COMPARE_TERMS):
        return OutputMode.COMPANY_COMPARISON

    if depth == ResponseDepth.DEEP:
        return OutputMode.DEEP_RESEARCH_REPORT

    if any(term in lower for term in _FILING_TERMS):
        filing_versions = sum(1 for term in ("drhp", "rhp", "prospectus") if term in lower)
        if filing_versions >= 2 or (any(term in lower for term in _VERSION_TERMS) and ("drhp" in lower or "rhp" in lower)):
            return OutputMode.DOCUMENT_VERSION_COMPARISON
        return OutputMode.FILING_ANALYSIS
    if any(term in lower for term in _VALUATION_TERMS):
        return OutputMode.VALUATION_MODEL
    if any(term in lower for term in _NEWS_TERMS):
        return OutputMode.NEWS_BRIEF
    if any(term in lower for term in _INVESTMENT_TERMS):
        return OutputMode.INVESTMENT_VIEW
    if any(term in lower for term in _MARKET_TERMS) and not _looks_like_bare_company(target):
        return OutputMode.MARKET_EXPLAINER
    return OutputMode.COMPANY_SNAPSHOT if _looks_like_bare_company(target) or entity else OutputMode.DIRECT_ANSWER


def extract_finance_entities(query: str, *, limit: int = 4) -> list[ResolvedEntity]:
    """Best-effort entity extraction for finance chat queries.

    This intentionally stays lightweight and deterministic. It recognizes
    known Indian aliases/tickers plus explicit exchange suffixes, then falls
    back to a bare all-caps ticker if present.
    """
    text = query or ""
    lower = f" {text.lower()} "
    candidates: list[tuple[int, str]] = []

    for alias in sorted(_ALIAS_TICKERS, key=len, reverse=True):
        pattern = r"(?<![a-z0-9&])" + re.escape(alias.lower()) + r"(?![a-z0-9])"
        match = re.search(pattern, lower)
        if match:
            candidates.append((match.start(), alias))

    for match in re.finditer(r"\b[A-Z]{2,12}(?:\.(?:NS|BO|NSE|BSE))?\b", text):
        token = match.group(0)
        if token.lower() in {"NSE", "BSE", "SEBI", "RBI", "DCF", "WACC", "CAGR"}:
            continue
        candidates.append((match.start(), token))

    out: list[ResolvedEntity] = []
    seen: set[str] = set()
    for _, raw in sorted(candidates, key=lambda item: item[0]):
        entity = resolve_entity(raw)
        key = entity.yahoo_ticker or entity.normalized_name
        if key in seen:
            continue
        seen.add(key)
        out.append(entity)
        if len(out) >= limit:
            break
    return out


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
