"""Action queue — "5 things you should know today".

Aggregates:
- Highest-importance news from last 24h
- Corporate actions in next 7 days
- Active alerts
- Biggest day movers

Ranked by urgency × user-impact.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from finagent.portfolio_mirrors import PositionMirror
from finagent.portfolio.alerts import compute_alerts
from finagent.portfolio.corporate_actions import fetch_corporate_actions
from finagent.portfolio.news import fetch_portfolio_news
from finagent.portfolio.analytics import _fetch_quote_cached

logger = logging.getLogger("finagent.portfolio.action_queue")


def build_action_queue(positions: list[PositionMirror], analytics: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a ranked list of up to 5 actions the user should know today."""
    if not positions:
        return []

    actions: list[dict[str, Any]] = []

    # 1. Active alerts (highest urgency)
    alerts = compute_alerts(positions, analytics)
    for alert in alerts:
        if alert.get("severity") == "danger":
            actions.append({
                "priority": 1,
                "type": "alert",
                "title": alert.get("code", "Alert"),
                "description": alert.get("message", ""),
                "action_url": None,
                "dismissible": True,
            })

    # 2. Corporate actions in next 7 days
    try:
        events = fetch_corporate_actions(positions, days=7)
        for ev in events[:3]:
            actions.append({
                "priority": 2,
                "type": "corporate_action",
                "title": ev.get("title", ""),
                "description": f"{ev.get('related_name', '')} · {ev.get('date_label', '')} · {ev.get('days_remaining', 0)} days",
                "action_url": ev.get("url"),
                "dismissible": True,
            })
    except Exception as exc:
        logger.debug("Action queue events fetch failed: %s", exc)

    # 3. Top news from last 24h (highest score)
    try:
        news_items = fetch_portfolio_news(positions, limit=5)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for item in news_items:
            pub_dt = None
            if item.get("published_at"):
                try:
                    pub_dt = datetime.fromisoformat(item["published_at"])
                except Exception:
                    pass
            if pub_dt and pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if pub_dt and pub_dt >= cutoff:
                actions.append({
                    "priority": 3,
                    "type": "news",
                    "title": item.get("title", ""),
                    "description": item.get("snippet", "")[:120],
                    "action_url": item.get("url"),
                    "dismissible": True,
                })
    except Exception as exc:
        logger.debug("Action queue news fetch failed: %s", exc)

    # 4. Biggest day movers (> 3% or < -3%)
    movers = []
    for pos in positions:
        if pos.kind != "equity":
            continue
        quote = _fetch_quote_cached(pos.exchange_symbol)
        day_pct = quote.get("day_change_pct", 0)
        if abs(day_pct) >= 0.03:
            movers.append({
                "symbol": pos.exchange_symbol,
                "name": pos.name,
                "day_change_pct": round(day_pct * 100, 2),
            })
    movers.sort(key=lambda x: abs(x.get("day_change_pct", 0)), reverse=True)
    for m in movers[:2]:
        actions.append({
            "priority": 4,
            "type": "day_mover",
            "title": f"{m['symbol']} {m['day_change_pct']:+}% today",
            "description": m.get("name", ""),
            "action_url": None,
            "dismissible": True,
        })

    # Sort by priority, dedupe by title, take top 5
    actions.sort(key=lambda x: x.get("priority", 99))
    seen: set[str] = set()
    result = []
    for a in actions:
        key = a.get("title", "") + "|" + a.get("type", "")
        if key not in seen:
            seen.add(key)
            result.append(a)
            if len(result) >= 5:
                break
    return result
