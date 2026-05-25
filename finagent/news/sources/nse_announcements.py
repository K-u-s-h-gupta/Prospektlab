"""NSE corporate announcements fetcher.

Uses the public NSE corporate announcements API.
Falls back gracefully on rate-limit / schema changes.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.nse")

_NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"


def fetch_nse_announcements(isin: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Fetch corporate announcements for an ISIN from NSE.

    Note: NSE API often requires session cookies; we attempt a simple fetch.
    If blocked, returns empty list gracefully.
    """
    if not isin:
        return []
    cache_key = f"nse:{isin}"
    cached = cache_get(cache_key, ttl_minutes=15, source="nse")
    if cached is not None:
        return cached

    try:
        import httpx
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            # NSE may require specific headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            }
            resp = client.get(_NSE_ANNOUNCEMENTS_URL, headers=headers, params={"symbol": isin})
            if resp.status_code != 200:
                logger.debug("NSE announcements returned %d for %s", resp.status_code, isin)
                return []
            data = resp.json()
            results = []
            for item in (data if isinstance(data, list) else data.get("data", [])):
                if not isinstance(item, dict):
                    continue
                results.append({
                    "title": item.get("desc", item.get("subject", "Corporate Announcement")),
                    "url": item.get("attchmntFile", ""),
                    "snippet": item.get("desc", "")[:240],
                    "source": "nseindia.com",
                    "published": item.get("an_dt", ""),
                    "source_family": "nse",
                    "category": _classify_nse_category(item),
                })
            cache_set(cache_key, results, source="nse")
            return results[:max_results]
    except Exception as exc:
        logger.debug("NSE announcements fetch failed for %s: %s", isin, exc)
        return []


def _classify_nse_category(item: dict[str, Any]) -> str:
    desc = (item.get("desc", "") + item.get("subject", "")).lower()
    if any(w in desc for w in ("dividend", "interim dividend", "final dividend")):
        return "corporate_action"
    if any(w in desc for w in ("bonus", "split", "rights", "buyback")):
        return "corporate_action"
    if any(w in desc for w in ("board meeting", "results", "earnings")):
        return "earnings"
    if any(w in desc for w in ("agm", "egm", "voting")):
        return "corporate_action"
    if any(w in desc for w in ("sebi", "regulatory", "compliance")):
        return "regulatory"
    return "corporate_action"
