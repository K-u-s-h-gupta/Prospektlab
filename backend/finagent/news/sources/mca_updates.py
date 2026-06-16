"""MCA (Ministry of Corporate Affairs) notification fetcher.

Fetches latest MCA circulars, notifications, and company-law updates
from mca.gov.in for the content automation pipeline.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.mca")

_MCA_NOTIFICATIONS_URL = "https://www.mca.gov.in/content/mca/global/en/data-and-reports/latest-news.html"
_MCA_CIRCULARS_URL = "https://www.mca.gov.in/content/mca/global/en/acts-rules/circulars.html"
_MCA_RSS_URL = "https://www.mca.gov.in/rss/mca_circulars.xml"


def fetch_mca_updates(max_results: int = 6) -> list[dict[str, Any]]:
    """Fetch latest MCA circulars and notifications."""
    cache_key = "mca:updates"
    cached = cache_get(cache_key, ttl_minutes=180, source="mca")
    if cached is not None:
        return cached

    results: list[dict[str, Any]] = []

    try:
        import httpx

        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            try:
                import feedparser
                feed = feedparser.parse(_MCA_RSS_URL)
                for entry in feed.entries[:max_results]:
                    title = entry.get("title", "").strip()
                    if not title:
                        continue
                    results.append({
                        "title": title,
                        "url": entry.get("link", ""),
                        "snippet": (entry.get("summary", "") or "")[:300],
                        "source": "mca.gov.in",
                        "published": entry.get("published", ""),
                        "source_family": "mca",
                        "category": _classify_mca_item(title),
                    })
                if results:
                    cache_set(cache_key, results, source="mca")
                    return results
            except ImportError:
                pass

            for url in [_MCA_RSS_URL]:
                try:
                    import xml.etree.ElementTree as ET
                    resp = client.get(url)
                    if resp.status_code != 200:
                        continue
                    root = ET.fromstring(resp.text)
                    channel = root.find("channel")
                    if channel is None:
                        continue
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
                            "source": "mca.gov.in",
                            "published": pub_el.text if pub_el is not None else "",
                            "source_family": "mca",
                            "category": _classify_mca_item(title),
                        })
                except Exception:
                    continue

        cache_set(cache_key, results, source="mca")
        return results

    except Exception as exc:
        logger.debug("MCA updates fetch failed: %s", exc)
        return []


_COMPANIES_ACT_KEYWORDS = {"companies act", "company law", "section 135", "csr", "annual return", "ags", "dir-3", "agm"}
_REGULATORY_KEYWORDS = {"circular", "notification", "amendment", "rule", "regulation", "order", "penalty"}


def _classify_mca_item(title: str) -> str:
    lower = title.lower()
    if any(k in lower for k in _COMPANIES_ACT_KEYWORDS):
        return "companies_act"
    if any(k in lower for k in _REGULATORY_KEYWORDS):
        return "regulatory"
    if "llp" in lower:
        return "llp"
    return "general"
