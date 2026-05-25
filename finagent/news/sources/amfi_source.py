"""AMFI scheme updates source.

Fetches AMFI scheme NAVAll feed and extracts updates for relevant schemes.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.news.sources.amfi")

_AMFI_NAV_URL = "https://api.mfapi.in/mf/{amfi}"


def fetch_amfi_updates(amfi: str, scheme_name: str = "") -> list[dict[str, Any]]:
    """Fetch latest NAV and meta for a single MF scheme via AMFI."""
    if not amfi:
        return []
    cache_key = f"amfi:{amfi}"
    cached = cache_get(cache_key, ttl_minutes=60, source="amfi")
    if cached is not None:
        return cached

    try:
        import httpx
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(_AMFI_NAV_URL.format(amfi=amfi))
            if resp.status_code != 200:
                return []
            data = resp.json()
            meta = data.get("meta", {})
            nav = data.get("data", [{}])[0]
            results = []
            if meta:
                results.append({
                    "title": f"{scheme_name or meta.get('scheme_name', 'MF')} NAV updated",
                    "url": f"https://www.amfiindia.com/",
                    "snippet": f"Latest NAV: ₹{nav.get('nav', 'N/A')} as of {nav.get('date', 'N/A')}. Fund house: {meta.get('fund_house', 'N/A')}.",
                    "source": "amfiindia.com",
                    "published": nav.get("date", ""),
                    "source_family": "amfi",
                    "category": "general",
                })
            cache_set(cache_key, results, source="amfi")
            return results
    except Exception as exc:
        logger.debug("AMFI fetch failed for %s: %s", amfi, exc)
        return []
