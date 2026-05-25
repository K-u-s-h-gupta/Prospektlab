"""Corporate actions calendar.

Pulls upcoming events from NSE/BSE corporate-actions APIs for each holding's ISIN.
Graceful degradation if APIs fail.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from finagent.portfolio_mirrors import PositionMirror
from finagent.news.sources.nse_announcements import fetch_nse_announcements
from finagent.news.sources.bse_announcements import fetch_bse_announcements

logger = logging.getLogger("finagent.portfolio.corporate_actions")

_EVENT_CATEGORIES = {
    "ex-dividend": ["ex-dividend", "dividend"],
    "results": ["results", "earnings"],
    "board_meeting": ["board meeting"],
    "agm": ["agm", "annual general meeting"],
    "stock_split": ["stock split", "split"],
    "bonus": ["bonus"],
    "rights": ["rights issue", "rights"],
    "buyback": ["buyback", "share buyback"],
}


def _classify_event(title: str) -> str:
    t = title.lower()
    for cat, keywords in _EVENT_CATEGORIES.items():
        if any(kw in t for kw in keywords):
            return cat
    return "other"


def _parse_event_date(pub_str: str) -> datetime | None:
    if not pub_str:
        return None
    formats = ["%d-%b-%Y", "%Y-%m-%d", "%d %b %Y", "%a, %d %b %Y %H:%M:%S %Z"]
    for fmt in formats:
        try:
            return datetime.strptime(pub_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(pub_str)
    except ValueError:
        pass
    return None


def fetch_corporate_actions(positions: list[PositionMirror], days: int = 30) -> list[dict[str, Any]]:
    """Fetch upcoming corporate actions for all holdings."""
    if not positions:
        return []

    all_events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pos in positions:
        items: list[dict[str, Any]] = []
        if pos.isin:
            items.extend(fetch_nse_announcements(pos.isin, max_results=5))
        if pos.symbol and pos.exchange == "BSE":
            items.extend(fetch_bse_announcements(pos.symbol, max_results=5))

        for item in items:
            title = item.get("title", "")
            url = item.get("url", "")
            key = f"{title}|{url}"
            if key in seen:
                continue
            seen.add(key)

            dt = _parse_event_date(item.get("published", ""))
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # Only include future/near-future events
            if dt and dt > datetime.now(timezone.utc) - timedelta(days=1):
                all_events.append({
                    "title": title,
                    "url": url,
                    "category": _classify_event(title),
                    "date": dt.isoformat(),
                    "date_label": dt.strftime("%d %b %Y"),
                    "days_remaining": max(0, (dt - datetime.now(timezone.utc)).days),
                    "related_symbol": pos.exchange_symbol,
                    "related_name": pos.name,
                })

    # Sort by date ascending
    all_events.sort(key=lambda x: x.get("date", ""))
    return all_events[:50]  # cap
