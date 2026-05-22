from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.retrieval.sparse_index import sanitize_search_query

if TYPE_CHECKING:
    from finagent.tools.web.scraper import ScrapedDoc

logger = logging.getLogger("finagent.retrieval.reranker")


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9&./-]*", re.I)
_ISO_DATE_RE = re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b")
_DMY_DATE_RE = re.compile(
    r"\b(0?[1-9]|[12]\d|3[01])\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+(20\d{2})\b",
    re.I,
)
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_LATEST_TERMS = frozenset(
    ("latest", "recent", "news", "headline", "update", "today", "announcement", "press")
)
_REGULATORY_TERMS = frozenset(
    ("lodr", "regulation", "sebi", "nse", "bse", "filing", "disclosure", "results", "shareholding")
)
_TIER_PRIOR = {
    1: 5.0,
    2: 4.0,
    3: 2.7,
    4: 2.0,
    5: 0.8,
    6: 0.4,
    7: 0.2,
    8: -3.0,
}


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")]


def _doc_text(doc: ScrapedDoc) -> str:
    return " ".join(
        str(x)
        for x in (
            getattr(doc, "title", ""),
            getattr(doc, "excerpt", ""),
            getattr(doc, "domain", ""),
            getattr(doc, "url", ""),
        )
        if x
    )


def _bm25_scores(query_terms: list[str], doc_terms: list[list[str]]) -> list[float]:
    if not query_terms or not doc_terms:
        return [0.0 for _ in doc_terms]

    n_docs = len(doc_terms)
    avgdl = sum(len(terms) for terms in doc_terms) / max(n_docs, 1)
    avgdl = max(avgdl, 1.0)
    df: Counter[str] = Counter()
    for terms in doc_terms:
        df.update(set(terms))

    k1 = 1.6
    b = 0.72
    scores: list[float] = []
    wanted = Counter(query_terms)
    for terms in doc_terms:
        tf = Counter(terms)
        dl = max(len(terms), 1)
        score = 0.0
        for term, q_weight in wanted.items():
            f = tf.get(term, 0)
            if not f:
                continue
            idf = math.log(1.0 + ((n_docs - df[term] + 0.5) / (df[term] + 0.5)))
            denom = f + k1 * (1.0 - b + b * (dl / avgdl))
            score += idf * ((f * (k1 + 1.0)) / denom) * min(q_weight, 2)
        scores.append(score)
    return scores


def _preferred_score(domain: str, preferred: list[str]) -> float:
    if not preferred:
        return 0.0
    domain = (domain or "").lower().removeprefix("www.")
    return 2.5 if any(domain == d or domain.endswith("." + d) or domain.endswith(d) for d in preferred) else 0.0


def _entity_score(text: str, aliases: tuple[str, ...] | list[str]) -> float:
    if not aliases:
        return 0.0
    haystack = f" {text.lower()} "
    best = 0.0
    for alias in aliases:
        alias_l = (alias or "").strip().lower()
        if not alias_l:
            continue
        if f" {alias_l} " in haystack:
            best = max(best, 2.0 if " " in alias_l else 1.2)
        else:
            alias_tokens = set(_tokens(alias_l))
            if alias_tokens and alias_tokens.issubset(set(_tokens(haystack))):
                best = max(best, 1.4)
    return best


def _parse_date_candidate(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value)
    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    if m := _ISO_DATE_RE.search(text):
        year, month, day = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    if m := _DMY_DATE_RE.search(text):
        day = int(m.group(1))
        month = _MONTHS[m.group(2).lower()]
        year = int(m.group(3))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _published_at(doc: ScrapedDoc, text: str) -> datetime | None:
    extra = getattr(doc, "extra", {}) or {}
    candidates: list[object] = []
    if isinstance(extra, dict):
        candidates.extend(extra.get(k) for k in ("published", "published_at", "date", "timestamp", "created_at"))
    candidates.extend(
        getattr(doc, k, None)
        for k in ("published", "published_at", "date", "timestamp", "created_at")
    )
    candidates.extend((getattr(doc, "title", ""), getattr(doc, "excerpt", ""), getattr(doc, "url", ""), text))
    for candidate in candidates:
        parsed = _parse_date_candidate(candidate)
        if parsed:
            return parsed
    return None


def _half_life_days(query_terms: set[str]) -> float:
    if query_terms & _LATEST_TERMS:
        return 7.0
    if query_terms & _REGULATORY_TERMS:
        return 120.0
    if {"historical", "history", "annual", "report"} & query_terms:
        return 730.0
    return 45.0


def _time_decay_score(doc: ScrapedDoc, text: str, query_terms: set[str], relevance_gate: float) -> float:
    published = _published_at(doc, text)
    if not published:
        return 0.0
    now = datetime.now(timezone.utc)
    age_days = max((now - published.astimezone(timezone.utc)).total_seconds() / 86400.0, 0.0)
    half_life = _half_life_days(query_terms)
    decay = math.exp(-math.log(2.0) * age_days / half_life)
    gate = 1.0 if relevance_gate > 0 else 0.25
    return 3.0 * decay * gate


def _domain_tier_score(doc: ScrapedDoc, query_terms: set[str]) -> float:
    tier = int(getattr(doc, "tier", 5) or 5)
    score = _TIER_PRIOR.get(tier, 0.0)
    if (query_terms & _REGULATORY_TERMS) and tier <= 2:
        score += 1.3
    if getattr(doc, "blocked_reason", None):
        score -= 4.0
    return score


def rerank_docs(
    query: str,
    docs: list[ScrapedDoc],
    *,
    entity: ResolvedEntity | None = None,
    preferred_domains: list[str] | None = None,
) -> list[ScrapedDoc]:
    """Three-stage self-hosted ranking for Indian-market retrieval.

    Stage 1 candidate sourcing happens in ``search_web``. This function performs
    Stage 2 structural/BM25 scoring and Stage 3 freshness re-ranking without any
    external sentiment-vector inputs.
    """
    if not docs:
        return []

    sanitized_query = sanitize_search_query(query)
    query_terms = _tokens(sanitized_query)
    query_term_set = set(query_terms)
    preferred = [d.lower().removeprefix("www.") for d in (preferred_domains or []) if d]
    aliases = tuple(entity.search_aliases if entity else ())
    texts = [_doc_text(doc) for doc in docs]
    doc_terms = [_tokens(text) for text in texts]
    bm25 = _bm25_scores(query_terms, doc_terms)

    scored_docs = []
    for idx, doc in enumerate(docs):
        text = texts[idx]
        bm25_val = bm25[idx]
        entity_boost = _entity_score(text, aliases)
        structural = _domain_tier_score(doc, query_term_set)
        preferred_boost = _preferred_score(getattr(doc, "domain", ""), preferred)
        freshness = _time_decay_score(doc, text, query_term_set, bm25_val + entity_boost)
        total = (bm25_val * 2.4) + structural + preferred_boost + entity_boost + freshness
        scored_docs.append({
            "doc": doc,
            "bm25": bm25_val,
            "entity_boost": entity_boost,
            "structural": structural,
            "preferred_boost": preferred_boost,
            "freshness": freshness,
            "total": total,
        })

    ranked_scored = sorted(scored_docs, key=lambda x: x["total"], reverse=True)

    logger.info("Document ranking completed. Query: '%s'", query)
    logger.info("Top %d ranked documents breakdown:", min(10, len(ranked_scored)))
    for idx, item in enumerate(ranked_scored[:10], 1):
        doc = item["doc"]
        logger.info(
            "  #%d. %s - Tier %s [Total: %.4f] (BM25 * 2.4: %.4f, Structural: %.4f, Preferred: %.4f, Entity: %.4f, Freshness: %.4f) URL: %s",
            idx,
            getattr(doc, "title", "No Title")[:60],
            getattr(doc, "tier", "N/A"),
            item["total"],
            item["bm25"] * 2.4,
            item["structural"],
            item["preferred_boost"],
            item["entity_boost"],
            item["freshness"],
            getattr(doc, "url", "N/A"),
        )

    return [item["doc"] for item in ranked_scored]
