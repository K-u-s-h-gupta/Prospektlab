"""SearXNG async HTTP client for web search.

Provides async search interface to self-hosted SearXNG or falls back to
DDG + Bing HTML scrapers when SearXNG URL not configured.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("finagent.tools.web.searxng_client")

# Environment variable for SearXNG base URL
SEARXNG_URL_ENV = "FINAGENT_SEARXNG_URL"


class SearXNGClient:
    """Async HTTP client for SearXNG search engine."""

    def __init__(self, base_url: str | None = None):
        """Initialize SearXNG client.

        Args:
            base_url: SearXNG base URL (e.g., http://localhost:8888).
                     If None, uses FINAGENT_SEARXNG_URL env var.
                     If env var not set, falls back to DDG/Bing scrapers.
        """
        self.base_url = base_url or os.getenv(SEARXNG_URL_ENV)
        self.available = bool(self.base_url)

    async def search(
        self,
        query: str,
        num_results: int = 10,
        language: str = "en-US",
        timeout: float = 15.0,
    ) -> list[dict[str, str]]:
        """Search using SearXNG (or return fallback empty if not available).

        Args:
            query: Search query
            num_results: Number of results to return (try to fetch)
            language: Language code (e.g., en-US)
            timeout: Request timeout in seconds

        Returns:
            List of search results with keys: title, url, snippet
        """
        if not self.available:
            logger.info("SearXNG URL not configured (FINAGENT_SEARXNG_URL). Falling back to DDG + Bing.")
            # Fallback to direct scrapers
            try:
                from finagent.tools.web.scraper import _search_ddg, _search_bing
                ddg = asyncio.run(_search_ddg(query, max_results=num_results))
                bing = asyncio.run(_search_bing(query, max_results=num_results))
                combined = (ddg or []) + (bing or [])
                # Dedup and format
                seen = set()
                results = []
                for url, title in combined:
                    if url not in seen:
                        seen.add(url)
                        results.append({"title": title or "", "url": url, "snippet": ""})
                    if len(results) >= num_results:
                        break
                return results
            except Exception as e:
                logger.warning("Fallback DDG/Bing search also failed: %s", e)
                return []

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "language": language,
                        "num_results": num_results,
                    },
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                    })

                logger.info("SearXNG search returned %d results for query: %s", len(results), query)
                return results

        except asyncio.TimeoutError:
            logger.warning("SearXNG search timeout for query: %s", query)
            return []
        except Exception as exc:
            logger.error("SearXNG search failed for query '%s': %s", query, exc)
            return []

    async def search_batch(
        self,
        queries: list[str],
        num_results: int = 10,
        language: str = "en-US",
        timeout: float = 15.0,
        max_concurrent: int = 5,
    ) -> dict[str, list[dict[str, str]]]:
        """Search multiple queries concurrently.

        Args:
            queries: List of search queries
            num_results: Results per query
            language: Language code
            timeout: Timeout per request
            max_concurrent: Max concurrent requests

        Returns:
            Dict mapping query -> list of results
        """
        if not self.available:
            return {q: [] for q in queries}

        semaphore = asyncio.Semaphore(max_concurrent)

        async def bounded_search(q: str) -> tuple[str, list[dict[str, str]]]:
            async with semaphore:
                results = await self.search(q, num_results, language, timeout)
                return q, results

        tasks = [bounded_search(q) for q in queries]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        results_dict = {}
        for result in results_list:
            if isinstance(result, Exception):
                logger.error("Batch search error: %s", result)
                continue
            q, res = result
            results_dict[q] = res

        return results_dict


async def search(
    query: str,
    num_results: int = 10,
    language: str = "en-US",
) -> list[dict[str, str]]:
    """Convenience async function for single search query.

    Args:
        query: Search query
        num_results: Number of results
        language: Language code

    Returns:
        List of search results
    """
    client = SearXNGClient()
    return await client.search(query, num_results, language)


async def search_batch(
    queries: list[str],
    num_results: int = 10,
    language: str = "en-US",
) -> dict[str, list[dict[str, str]]]:
    """Convenience async function for batch search.

    Args:
        queries: List of search queries
        num_results: Results per query
        language: Language code

    Returns:
        Dict mapping query -> results
    """
    client = SearXNGClient()
    return await client.search_batch(queries, num_results, language)
