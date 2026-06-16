"""NSE corporate announcements fetcher.

Uses the resilient multi-tier exchange_fetcher (warmed httpx session,
stealth-browser fallback). When NSE fails entirely the call returns []
and the caller is expected to try the BSE equivalent.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set
from finagent.tools.web.exchange_fetcher import fetch_nse_json

logger = logging.getLogger("finagent.news.sources.nse")


def fetch_nse_announcements(isin: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Fetch corporate announcements for an ISIN/symbol from NSE.

    Accepts either ISIN or symbol (NSE accepts both via the same endpoint
    with different query params). Empty list on hard failure.
    """
    if not isin:
        return []
    cache_key = f"nse:{isin}"
    cached = cache_get(cache_key, ttl_minutes=15, source="nse")
    if cached is not None:
        return cached

    # NSE corporate announcements endpoint takes 'symbol' (ISIN also accepted).
    data = fetch_nse_json(
        "/api/corporate-announcements",
        params={"index": "equities", "symbol": isin},
        referer_path=f"/get-quotes/equity?symbol={isin}",
    )
    if data is None:
        # Final fallback: try the corporates filter endpoint (returns same shape on some accounts)
        data = fetch_nse_json(
            "/api/corporate-announcements",
            params={"symbol": isin},
            referer_path="/companies-listing/corporate-filings-announcements",
        )

    results: list[dict[str, Any]] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data") or data.get("rows") or []
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        desc = item.get("desc") or item.get("subject") or "Corporate Announcement"
        results.append({
            "title": desc,
            "url": item.get("attchmntFile") or item.get("attachmentFile") or "",
            "snippet": (item.get("desc") or item.get("attchmntText") or "")[:240],
            "source": "nseindia.com",
            "published": item.get("an_dt") or item.get("sortDate") or "",
            "source_family": "nse",
            "category": _classify_nse_category(item),
        })

    cache_set(cache_key, results, source="nse")
    return results[:max_results]


def _classify_nse_category(item: dict[str, Any]) -> str:
    desc = (str(item.get("desc", "")) + " " + str(item.get("subject", ""))).lower()
    if any(w in desc for w in ("dividend", "interim dividend", "final dividend")):
        return "corporate_action"
    if any(w in desc for w in ("bonus", "split", "rights", "buyback")):
        return "corporate_action"
    if any(w in desc for w in ("board meeting", "results", "earnings", "financial result")):
        return "earnings"
    if any(w in desc for w in ("agm", "egm", "voting", "postal ballot")):
        return "corporate_action"
    if any(w in desc for w in ("sebi", "regulatory", "compliance", "show cause", "adjudication")):
        return "regulatory"
    if any(w in desc for w in ("acquisition", "merger", "scheme of arrangement", "amalgamation")):
        return "ma"
    return "corporate_action"
