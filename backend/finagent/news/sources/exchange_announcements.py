"""Cross-exchange announcement orchestrator.

Public entry point that tries NSE first, falls back to BSE on failure or
empty result, and merges results from both when both succeed. Handles the
common case where a caller only knows ONE of {symbol, scrip_code} and the
other has to be resolved.
"""
from __future__ import annotations

import logging
from typing import Any

from finagent.news.sources.bse_announcements import fetch_bse_announcements
from finagent.news.sources.nse_announcements import fetch_nse_announcements

logger = logging.getLogger("finagent.news.sources.exchange")


def fetch_exchange_announcements(
    *,
    nse_symbol: str | None = None,
    bse_scrip_code: str | None = None,
    isin: str | None = None,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """Fetch corporate announcements from both NSE and BSE.

    Tries NSE first (richer category metadata), falls through to BSE,
    and merges by deduplicating on (date, normalized title).

    Caller can pass any combination of identifiers; missing ones are
    resolved lazily via the IKG symbol mapper when available.
    """
    nse_symbol = nse_symbol or isin or ""
    if not bse_scrip_code and nse_symbol:
        bse_scrip_code = _resolve_bse_scrip(nse_symbol)

    nse_items: list[dict[str, Any]] = []
    bse_items: list[dict[str, Any]] = []

    if nse_symbol:
        try:
            nse_items = fetch_nse_announcements(nse_symbol, max_results=max_results)
        except Exception as exc:
            logger.debug("NSE fetch failed for %s: %s", nse_symbol, exc)

    if bse_scrip_code:
        try:
            bse_items = fetch_bse_announcements(bse_scrip_code, max_results=max_results)
        except Exception as exc:
            logger.debug("BSE fetch failed for %s: %s", bse_scrip_code, exc)

    # Merge with dedup. Same filing appears on both exchanges within minutes;
    # we keep the NSE copy (richer metadata) but record bse_corroborated=True.
    merged = _merge_dedup(nse_items, bse_items)
    if not merged:
        logger.debug("Exchange announcements: no results from NSE or BSE for symbol=%s scrip=%s",
                     nse_symbol, bse_scrip_code)
    return merged[:max_results]


def _merge_dedup(nse_items: list[dict], bse_items: list[dict]) -> list[dict]:
    """Merge NSE + BSE lists, dedup by normalized title + date.
    Marks items found on both with bse_corroborated/nse_corroborated flags."""
    seen: dict[str, dict[str, Any]] = {}
    for item in nse_items:
        key = _dedup_key(item)
        if key:
            seen[key] = {**item, "nse_corroborated": True}
    for item in bse_items:
        key = _dedup_key(item)
        if not key:
            continue
        if key in seen:
            seen[key]["bse_corroborated"] = True
        else:
            seen[key] = {**item, "bse_corroborated": True}
    # Sort by publication date descending
    return sorted(
        seen.values(),
        key=lambda x: str(x.get("published") or ""),
        reverse=True,
    )


def _dedup_key(item: dict) -> str:
    title = str(item.get("title") or "").lower().strip()
    date = str(item.get("published") or "")[:10]
    # Normalize: first 50 chars of title + date
    title_norm = " ".join(title.split())[:50]
    return f"{date}|{title_norm}" if title_norm else ""


def _resolve_bse_scrip(symbol_or_isin: str) -> str:
    """Look up BSE scrip code for an NSE symbol or ISIN via IKG.
    Returns '' if not found — caller will skip BSE in that case."""
    try:
        from finagent.ikg.db import get_company_by_symbol  # type: ignore
        rec = get_company_by_symbol(symbol_or_isin)
        if rec and isinstance(rec, dict):
            return str(rec.get("bse_scrip_code") or rec.get("scrip_code") or "")
    except Exception:
        pass
    return ""
