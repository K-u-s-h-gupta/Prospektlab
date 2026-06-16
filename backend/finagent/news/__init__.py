"""FinAgent news system.

Provides unified news fetching, scoring, deduplication, and caching.
"""
from __future__ import annotations

from finagent.news.cache import cache_get, cache_set, cache_clear_source
from finagent.news.dedupe import deduplicate, canonicalize_url, title_fingerprint
from finagent.news.scorer import score_item, tag_category, parse_published_at, VERIFIED_DOMAINS
from finagent.news.sources import fetch_all_sources, fetch_market_context

__all__ = [
    "cache_get",
    "cache_set",
    "cache_clear_source",
    "deduplicate",
    "canonicalize_url",
    "title_fingerprint",
    "score_item",
    "tag_category",
    "parse_published_at",
    "VERIFIED_DOMAINS",
    "fetch_all_sources",
    "fetch_market_context",
]
