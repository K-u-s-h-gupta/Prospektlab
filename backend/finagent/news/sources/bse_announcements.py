"""BSE corporate announcements fetcher.

Uses the resilient exchange_fetcher with warmed session + stealth fallback.
BSE rarely blocks datacenter IPs, but cookies + browser headers still raise
success rate from 80% → 99% in practice.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set
from finagent.tools.web.exchange_fetcher import fetch_bse_json

logger = logging.getLogger("finagent.news.sources.bse")

_BSE_ANN_PATH = "/BseIndiaAPI/api/AnnSubCategoryGetData/w"


def fetch_bse_announcements(scrip_code: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Fetch corporate announcements for a BSE scrip code via the current endpoint.

    BSE's `AnnGetData/w` endpoint was deprecated and returns "No Record Found".
    The working endpoint is `AnnSubCategoryGetData/w` with `strScrip` + `strType=C`.
    """
    if not scrip_code:
        return []
    cache_key = f"bse:{scrip_code}"
    cached = cache_get(cache_key, ttl_minutes=15, source="bse")
    if cached is not None:
        return cached

    data = fetch_bse_json(
        _BSE_ANN_PATH,
        params={
            "pageno": "1",
            "strCat": "-1",
            "strPrevDate": "",
            "strScrip": str(scrip_code),
            "strSearch": "P",
            "strToDate": "",
            "strType": "C",
        },
        referer_path=f"/corporates/ann.html?scrip={scrip_code}",
    )

    results: list[dict[str, Any]] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("Table") or data.get("data") or []
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        title = (
            item.get("NEWSSUB")
            or item.get("HEADLINE")
            or item.get("Subject")
            or "Corporate Announcement"
        )
        attach = item.get("ATTACHMENTNAME") or ""
        # BSE attachments are relative paths; expand to absolute URL
        if attach and not attach.startswith("http"):
            attach = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attach}"
        results.append({
            "title": str(title)[:300],
            "url": attach,
            "snippet": (str(item.get("NEWSSUB") or item.get("MORE") or ""))[:240],
            "source": "bseindia.com",
            "published": item.get("NEWS_DT") or item.get("DT_TM") or "",
            "source_family": "bse",
            "category": _classify_bse_category(item),
        })

    cache_set(cache_key, results, source="bse")
    return results[:max_results]


def _classify_bse_category(item: dict[str, Any]) -> str:
    desc = (
        str(item.get("NEWSSUB", ""))
        + " " + str(item.get("HEADLINE", ""))
        + " " + str(item.get("Subject", ""))
    ).lower()
    if any(w in desc for w in ("dividend", "interim dividend", "final dividend")):
        return "corporate_action"
    if any(w in desc for w in ("bonus", "split", "rights", "buyback")):
        return "corporate_action"
    if any(w in desc for w in ("board meeting", "results", "earnings", "financial result")):
        return "earnings"
    if any(w in desc for w in ("agm", "egm", "voting", "postal ballot")):
        return "corporate_action"
    if any(w in desc for w in ("sebi", "regulatory", "compliance")):
        return "regulatory"
    if any(w in desc for w in ("acquisition", "merger", "scheme of arrangement")):
        return "ma"
    return "corporate_action"
