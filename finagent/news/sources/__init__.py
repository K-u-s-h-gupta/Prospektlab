"""News sources public API.

Provides unified fetch_all_sources() for pulling news across all source families.
"""
from __future__ import annotations

from typing import Any

from finagent.news.sources.tavily_source import fetch_tavily_news
from finagent.news.sources.nse_announcements import fetch_nse_announcements
from finagent.news.sources.bse_announcements import fetch_bse_announcements
from finagent.news.sources.amfi_source import fetch_amfi_updates
from finagent.news.sources.sebi_rss import fetch_sebi_news
from finagent.news.sources.rss_aggregator import fetch_rss_news


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

    Returns a flat list of items from all sources, each tagged with
    'source_family' for downstream filtering.
    """
    all_items: list[dict[str, Any]] = []

    # Tavily (general news)
    all_items.extend(fetch_tavily_news(name, symbol, kind=kind, max_results=max_per_source))

    # NSE corporate announcements (equity only)
    if kind == "equity" and isin:
        all_items.extend(fetch_nse_announcements(isin, max_results=max_per_source))

    # BSE corporate announcements (equity only)
    if kind == "equity" and scrip_code:
        all_items.extend(fetch_bse_announcements(scrip_code, max_results=max_per_source))

    # AMFI updates (MF only)
    if kind == "mf" and amfi:
        all_items.extend(fetch_amfi_updates(amfi, scheme_name=name))

    return all_items


def fetch_market_context(max_results: int = 6) -> list[dict[str, Any]]:
    """Fetch general market news (SEBI + RSS feeds) for portfolio-wide context."""
    all_items: list[dict[str, Any]] = []
    all_items.extend(fetch_sebi_news(max_results=max_results))
    all_items.extend(fetch_rss_news(max_results=max_results))
    return all_items
