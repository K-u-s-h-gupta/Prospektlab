"""RBI press release and notification fetcher.

Fetches latest RBI press releases, circulars, and notifications
from rbi.org.in for the content automation pipeline.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.rbi")

_RBI_PRESS_URL = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
_RBI_NOTIFICATIONS_URL = "https://www.rbi.org.in/Scripts/NotificationUser.aspx"
_RBI_RSS_URL = "https://www.rbi.org.in/rss/rbi_pressreleases.xml"


def fetch_rbi_press_releases(max_results: int = 8) -> list[dict[str, Any]]:
    """Fetch latest RBI press releases and notifications via RSS."""
    cache_key = "rbi:press"
    cached = cache_get(cache_key, ttl_minutes=120, source="rbi")
    if cached is not None:
        return cached

    results: list[dict[str, Any]] = []

    try:
        import httpx

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            try:
                import feedparser
                feed = feedparser.parse(_RBI_RSS_URL)
                for entry in feed.entries[:max_results]:
                    title = entry.get("title", "").strip()
                    if not title:
                        continue
                    results.append({
                        "title": title,
                        "url": entry.get("link", ""),
                        "snippet": (entry.get("summary", "") or "")[:300],
                        "source": "rbi.org.in",
                        "published": entry.get("published", ""),
                        "source_family": "rbi",
                        "category": _classify_rbi_item(title),
                    })
                if results:
                    cache_set(cache_key, results, source="rbi")
                    return results
            except ImportError:
                pass

            import xml.etree.ElementTree as ET
            resp = client.get(_RBI_RSS_URL)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                channel = root.find("channel")
                if channel is not None:
                    for item in channel.findall("item")[:max_results]:
                        title_el = item.find("title")
                        link_el = item.find("link")
                        pub_el = item.find("pubDate")
                        desc_el = item.find("description")
                        title = title_el.text if title_el is not None else ""
                        if not title:
                            continue
                        results.append({
                            "title": title,
                            "url": link_el.text if link_el is not None else "",
                            "snippet": ((desc_el.text if desc_el is not None else "") or "")[:300],
                            "source": "rbi.org.in",
                            "published": pub_el.text if pub_el is not None else "",
                            "source_family": "rbi",
                            "category": _classify_rbi_item(title),
                        })

        cache_set(cache_key, results, source="rbi")
        return results

    except Exception as exc:
        logger.debug("RBI press release fetch failed: %s", exc)
        return []


_MONETARY_KEYWORDS = {"repo", "reverse repo", "crr", "slr", "mpc", "monetary policy", "interest rate", "inflation"}
_REGULATORY_KEYWORDS = {"circular", "notification", "regulation", "guideline", "directive", "master direction", "penalty", "fine"}


def _classify_rbi_item(title: str) -> str:
    lower = title.lower()
    if any(k in lower for k in _MONETARY_KEYWORDS):
        return "monetary_policy"
    if any(k in lower for k in _REGULATORY_KEYWORDS):
        return "regulatory"
    if "forex" in lower or "exchange rate" in lower or "usd" in lower:
        return "forex"
    if "bank" in lower or "nbfc" in lower or "credit" in lower:
        return "banking"
    return "general"
