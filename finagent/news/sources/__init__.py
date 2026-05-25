"""News sources public API.

Provides unified fetch_all_sources() for pulling news across all source families.

Primary: SearXNG (self-hosted)
Fallback: NSE/BSE corporate announcements, AMFI updates, SEBI RSS, general RSS, Tavily (optional)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("finagent.news.sources")

from finagent.news.sources.searxng_source import fetch_searxng_news
from finagent.news.sources.nse_announcements import fetch_nse_announcements
from finagent.news.sources.bse_announcements import fetch_bse_announcements
from finagent.news.sources.amfi_source import fetch_amfi_updates
from finagent.news.sources.sebi_rss import fetch_sebi_news
from finagent.news.sources.rss_aggregator import fetch_rss_news

# Optional Tavily fallback (gracefully skipped if not available)
try:
    from finagent.news.sources.tavily_source import fetch_tavily_news
    _TAVILY_AVAILABLE = True
except ImportError:
    _TAVILY_AVAILABLE = False
    def fetch_tavily_news(*args, **kwargs) -> list[dict]:
        return []


def fetch_all_sources(
    symbol: str = "",
    name: str = "",
    kind: str = "equity",
    isin: str = "",
    scrip_code: str = "",
    amfi: str = "",
    max_per_source: int = 5,
) -> list[dict[str, Any]]:
    """Fetch news from all available sources for a single holding.

    Priority:
    1. SearXNG (primary, self-hosted)
    2. Corporate announcements (NSE/BSE for equity, AMFI for MF)
    3. Tavily (optional, if available)

    Returns a flat list of items from all sources, each tagged with
    'source_family' for downstream filtering.
    """
    all_items: list[dict[str, Any]] = []

    # SearXNG (primary web search) - wrapped so unavailable URL doesn't break everything
    # For MF, prefer using fund name; for equity, use symbol
    try:
        query_term = name if kind == "mf" and name else symbol
        all_items.extend(fetch_searxng_news(query_term, kind=kind, max_results=max_per_source))
    except Exception as e:
        logger.warning("SearXNG news failed: %s", e)

    # Tavily (optional fallback) - only if available and if we need more results
    if _TAVILY_AVAILABLE and len(all_items) < max_per_source:
        try:
            query_term = name if kind == "mf" and name else symbol
            all_items.extend(fetch_tavily_news(query_term, kind=kind, max_results=max_per_source))
        except Exception as e:
            logger.warning("Tavily news failed (optional): %s", e)

    # NSE corporate announcements (equity only)
    if kind == "equity" and isin:
        try:
            all_items.extend(fetch_nse_announcements(isin, max_results=max_per_source))
        except Exception as e:
            logger.warning("NSE announcements failed: %s", e)

    # BSE corporate announcements (equity only)
    if kind == "equity" and scrip_code:
        try:
            all_items.extend(fetch_bse_announcements(scrip_code, max_results=max_per_source))
        except Exception as e:
            logger.warning("BSE announcements failed: %s", e)

    # AMFI updates (MF only)
    if kind == "mf" and amfi:
        try:
            all_items.extend(fetch_amfi_updates(amfi, scheme_name=name))
        except Exception as e:
            logger.warning("AMFI updates failed: %s", e)

    return all_items


def fetch_market_context(max_results: int = 6) -> list[dict[str, Any]]:
    """Fetch general market news (SEBI + RSS feeds) for portfolio-wide context."""
    all_items: list[dict[str, Any]] = []
    try:
        all_items.extend(fetch_sebi_news(max_results=max_results))
    except Exception as e:
        logger.warning("SEBI RSS failed: %s", e)
    try:
        all_items.extend(fetch_rss_news(max_results=max_results))
    except Exception as e:
        logger.warning("RSS aggregator failed: %s", e)
    return all_items
