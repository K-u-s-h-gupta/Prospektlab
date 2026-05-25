"""Tavily news source wrapper.

Query templating per holding kind, cached per-tenant.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.tavily")

def _get_tavily_client():
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY not set")
    from tavily import TavilyClient
    return TavilyClient(api_key=key)


def _build_query(name: str, symbol: str, kind: str) -> str:
    if kind == "mf":
        return f"{name} mutual fund NAV India news"
    return f"{name or symbol} stock news India"


def fetch_tavily_news(
    name: str,
    symbol: str,
    kind: str = "equity",
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Fetch news for a single holding via Tavily."""
    query = _build_query(name, symbol, kind)
    qhash = hashlib.sha256(("tavily:" + query).encode()).hexdigest()[:16]
    cached = cache_get(qhash, ttl_minutes=30, source="tavily")
    if cached is not None:
        return cached

    try:
        client = _get_tavily_client()
        resp = client.search(query=query, max_results=max_results, search_depth="basic")
        results = []
        for r in resp.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:240],
                "source": r.get("source", ""),
                "published": "",  # Tavily basic doesn't always return date
                "source_family": "tavily",
            })
        cache_set(qhash, results, source="tavily")
        return results
    except Exception as exc:
        logger.warning("Tavily search failed for '%s': %s", query, exc)
        return []
