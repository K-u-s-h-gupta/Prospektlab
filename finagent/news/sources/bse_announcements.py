"""BSE corporate announcements fetcher.

Uses the public BSE corporate announcements API endpoint.
Graceful degradation on failure.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.bse")

_BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"


def fetch_bse_announcements(scrip_code: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Fetch corporate announcements for a BSE scrip code."""
    if not scrip_code:
        return []
    cache_key = f"bse:{scrip_code}"
    cached = cache_get(cache_key, ttl_minutes=15, source="bse")
    if cached is not None:
        return cached

    try:
        import httpx
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            }
            resp = client.get(
                _BSE_ANNOUNCEMENTS_URL,
                headers=headers,
                params={
                    "scripcode": scrip_code,
                    "strCat": "-1",
                    "strPrevDate": "",
                    "strCurDate": "",
                    "strSearch": "P",
                },
            )
            if resp.status_code != 200:
                logger.debug("BSE announcements returned %d for %s", resp.status_code, scrip_code)
                return []
            data = resp.json()
            results = []
            for item in (data if isinstance(data, list) else data.get("Table", [])):
                if not isinstance(item, dict):
                    continue
                results.append({
                    "title": item.get("HEADLINE", item.get("Subject", "Corporate Announcement")),
                    "url": item.get("ATTACHMENTNAME", ""),
                    "snippet": item.get("HEADLINE", "")[:240],
                    "source": "bseindia.com",
                    "published": item.get("NEWS_DT", ""),
                    "source_family": "bse",
                    "category": _classify_bse_category(item),
                })
            cache_set(cache_key, results, source="bse")
            return results[:max_results]
    except Exception as exc:
        logger.debug("BSE announcements fetch failed for %s: %s", scrip_code, exc)
        return []


def _classify_bse_category(item: dict[str, Any]) -> str:
    desc = (item.get("HEADLINE", "") + item.get("Subject", "")).lower()
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
