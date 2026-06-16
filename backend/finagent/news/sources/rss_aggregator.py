"""RSS aggregator for financial news.

Fetches multiple financial news RSS feeds in parallel.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.rss")

# Verified financial news RSS feeds
_RSS_FEEDS = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("Moneycontrol Markets", "https://www.moneycontrol.com/rss/markets.xml"),
    ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Livemint", "https://www.livemint.com/rss/markets"),
    ("NDTV Profit", "https://www.ndtv.com/business/rss"),
    ("CNBC TV18", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss_feeds/select_category/rss_feed.xml?category=markets"),
]


def _fetch_single_feed(name: str, url: str, max_items: int = 5) -> list[dict[str, Any]]:
    """Fetch a single RSS feed and return normalized items."""
    try:
        import httpx
        import xml.etree.ElementTree as ET

        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            # Try feedparser first
            try:
                import feedparser
                feed = feedparser.parse(url)
                results = []
                for entry in feed.entries[:max_items]:
                    results.append({
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "snippet": entry.get("summary", "")[:240],
                        "source": name.lower().replace(" ", ""),
                        "published": entry.get("published", ""),
                        "source_family": "rss",
                        "category": "general",
                    })
                return results
            except ImportError:
                pass

            resp = client.get(url)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)
            results = []
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item")[:max_items]:
                    title = item.find("title")
                    link = item.find("link")
                    pub_date = item.find("pubDate")
                    desc = item.find("description")
                    results.append({
                        "title": title.text if title is not None else "",
                        "url": link.text if link is not None else "",
                        "snippet": (desc.text if desc is not None else "")[:240],
                        "source": name.lower().replace(" ", ""),
                        "published": pub_date.text if pub_date is not None else "",
                        "source_family": "rss",
                        "category": "general",
                    })
            return results
    except Exception as exc:
        logger.debug("RSS feed fetch failed for %s: %s", name, exc)
        return []


def fetch_rss_news(max_results: int = 12) -> list[dict[str, Any]]:
    """Fetch all RSS feeds in parallel and merge results."""
    cache_key = "rss:combined"
    cached = cache_get(cache_key, ttl_minutes=30, source="rss")
    if cached is not None:
        return cached

    all_items: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(_RSS_FEEDS), 8)) as executor:
        futures = {executor.submit(_fetch_single_feed, name, url): name for name, url in _RSS_FEEDS}
        for future in as_completed(futures):
            items = future.result()
            all_items.extend(items)

    # Sort by recency (best effort)
    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    cache_set(cache_key, all_items, source="rss")
    return all_items[:max_results]
