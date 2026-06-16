"""SEBI press release RSS fetcher.

Fetches and parses SEBI RSS feed for regulatory news.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.sebi")

_SEBI_RSS_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes"
_SEBI_RSS_FALLBACK = "https://www.sebi.gov.in/rss/sebi_pressreleases.xml"


def fetch_sebi_news(max_results: int = 6) -> list[dict[str, Any]]:
    """Fetch latest SEBI press releases via RSS."""
    cache_key = "sebi:press"
    cached = cache_get(cache_key, ttl_minutes=60, source="sebi")
    if cached is not None:
        return cached

    try:
        import httpx
        import xml.etree.ElementTree as ET

        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            # Try feedparser first if available
            try:
                import feedparser
                feed = feedparser.parse(_SEBI_RSS_FALLBACK)
                results = []
                for entry in feed.entries[:max_results]:
                    results.append({
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "snippet": entry.get("summary", "")[:240],
                        "source": "sebi.gov.in",
                        "published": entry.get("published", ""),
                        "source_family": "sebi",
                        "category": "regulatory",
                    })
                cache_set(cache_key, results, source="sebi")
                return results
            except ImportError:
                pass

            # Raw XML fallback
            resp = client.get(_SEBI_RSS_FALLBACK)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)
            results = []
            # RSS 2.0
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item")[:max_results]:
                    title = item.find("title")
                    link = item.find("link")
                    pub_date = item.find("pubDate")
                    desc = item.find("description")
                    results.append({
                        "title": title.text if title is not None else "",
                        "url": link.text if link is not None else "",
                        "snippet": (desc.text if desc is not None else "")[:240],
                        "source": "sebi.gov.in",
                        "published": pub_date.text if pub_date is not None else "",
                        "source_family": "sebi",
                        "category": "regulatory",
                    })
            cache_set(cache_key, results, source="sebi")
            return results
    except Exception as exc:
        logger.debug("SEBI RSS fetch failed: %s", exc)
        return []
