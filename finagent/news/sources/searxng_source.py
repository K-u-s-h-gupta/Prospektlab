"""News source using SearXNG for portfolio holding queries.

Replaces tavily_source.py with self-hosted SearXNG backend.
Supports Phase 2 Crawl4AI enhancement for snippet/date extraction.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from finagent.tools.web.searxng_client import SearXNGClient

logger = logging.getLogger("finagent.news.sources.searxng_source")


def fetch_searxng_news(
    query: str,
    kind: str = "equity",
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Fetch news via SearXNG for a holding (sync wrapper).

    Args:
        query: Search query (symbol or fund name)
        kind: Asset kind ('equity' or 'mf')
        max_results: Max results to return

    Returns:
        List of news items with keys: title, url, snippet, published_at, source_family
    """
    try:
        results = asyncio.run(_fetch_searxng_async(query, kind, max_results))
        return results
    except Exception as exc:
        logger.error("SearXNG news fetch failed for query '%s': %s", query, exc)
        return []


async def _fetch_searxng_async(
    query: str,
    kind: str = "equity",
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Async SearXNG news fetch with optional Crawl4AI enrichment.

    Args:
        query: Search query
        kind: Asset kind ('equity' or 'mf')
        max_results: Max results

    Returns:
        List of enriched news items
    """
    client = SearXNGClient()

    # Build query based on asset kind
    if kind == "mf":
        search_query = f"{query} mutual fund news"
    else:
        search_query = f"{query} stock news"

    # Fetch from SearXNG
    results = await client.search(search_query, num_results=max_results * 2)

    # Convert to news item format
    items = []
    for result in results[:max_results]:
        item = {
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "snippet": result.get("snippet", ""),
            "published_at": None,  # SearXNG doesn't provide published date; Phase 2 can use Crawl4AI
            "source_family": "searxng",
            "source": "searxng",
        }
        items.append(item)

    # Phase 2 enhancement: Use Crawl4AI to extract dates from top URLs
    if items:
        top_urls = [item["url"] for item in items[:3]]
        try:
            dates = await _fetch_publish_dates_crawl4ai(top_urls)
            for idx, item in enumerate(items[:3]):
                if idx < len(dates):
                    item["published_at"] = dates[idx]
        except Exception as exc:
            logger.debug("Crawl4AI date extraction failed: %s", exc)

    logger.info("SearXNG returned %d news items for query: %s", len(items), search_query)
    return items


async def _fetch_publish_dates_crawl4ai(
    urls: list[str],
    timeout: float = 30.0,
) -> list[str | None]:
    """Phase 2 enhancement: Extract publish dates from URLs using Crawl4AI.

    Args:
        urls: List of URLs to crawl
        timeout: Timeout for crawl operations

    Returns:
        List of publish dates (ISO format) or None if not found
    """
    try:
        from finagent.tools.web.scraper import _crawl4ai_fetch_batch

        results = await _crawl4ai_fetch_batch(urls, timeout=timeout)
        dates = []
        for content in results:
            # Simple heuristic: look for date patterns in content
            # Phase 2 can use ML-based date extraction or schema.org parsing
            date_str = _extract_date_from_content(content)
            dates.append(date_str)
        return dates
    except Exception as exc:
        logger.debug("Crawl4AI batch fetch failed: %s", exc)
        return [None] * len(urls)


def _extract_date_from_content(content: str) -> str | None:
    """Simple heuristic for extracting publish date from content.

    Phase 2 can enhance with ML or schema.org parsing.

    Args:
        content: HTML/markdown content

    Returns:
        ISO date string or None
    """
    import re

    # Look for common date patterns (e.g., 2024-01-15, Jan 15, 2024)
    patterns = [
        r"(\d{4}-\d{2}-\d{2})",  # ISO format
        r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            try:
                # Simple normalization to ISO format
                return match.group(1)
            except Exception:
                pass

    return None
