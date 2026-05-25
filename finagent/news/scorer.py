"""News scoring and categorization module.

Computes importance scores for news items based on:
- Source domain tier (T0/T1/T2/T3)
- Keyword importance (earnings, regulatory, corporate actions, etc.)
- Holding weight in portfolio
- Freshness
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("finagent.news.scorer")

# Domain tiers: lower number = higher trust
VERIFIED_DOMAINS: dict[str, int] = {
    # T0: Official / primary sources
    "sebi.gov.in": 0,
    "nseindia.com": 0,
    "bseindia.com": 0,
    "amfiindia.com": 0,
    "rbi.org.in": 0,

    # T1: Established financial media
    "economictimes.indiatimes.com": 1,
    "moneycontrol.com": 1,
    "livemint.com": 1,
    "business-standard.com": 1,
    "cnbctv18.com": 1,
    "ndtv.com": 1,
    "bloombergquint.com": 1,
    "reuters.com": 1,
    "bloomberg.com": 1,

    # T2: General business news
    "financialexpress.com": 2,
    "thehindubusinessline.com": 2,
    "timesofindia.indiatimes.com": 2,
    "hindustantimes.com": 2,
    "indiatoday.in": 2,

    # T3: SearXNG (meta-search results)
    # Tavily removed (replaced by SearXNG)
}

IMPORTANCE_KEYWORDS: dict[str, float] = {
    # Earnings / results
    "earnings": 1.2,
    "quarterly results": 1.3,
    "q1": 1.1,
    "q2": 1.1,
    "q3": 1.1,
    "q4": 1.1,
    "profit": 1.1,
    "revenue": 1.0,
    "eps": 1.1,
    "ebitda": 1.1,

    # Ratings / analyst
    "upgrade": 1.3,
    "downgrade": 1.3,
    "buy rating": 1.2,
    "sell rating": 1.2,
    "target price": 1.2,
    "outperform": 1.2,
    "underperform": 1.2,

    # Corporate actions
    "dividend": 1.2,
    "bonus": 1.2,
    "stock split": 1.2,
    "rights issue": 1.2,
    "buyback": 1.3,
    "merger": 1.3,
    "acquisition": 1.2,

    # Regulatory
    "sebi": 1.4,
    "regulatory": 1.2,
    "compliance": 1.0,
    "penalty": 1.3,
    "investigation": 1.3,
    "fraud": 1.4,

    # Market events
    "block deal": 1.1,
    "bulk deal": 1.0,
    "promoter buying": 1.2,
    "promoter selling": 1.2,
    "fii": 1.0,
    "dii": 1.0,

    # Penalty keywords
    "loss": -0.2,
    "delay": -0.1,
    "postponed": -0.1,
}


def _extract_domain(url: str) -> str:
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.split("/")[0]


def score_item(item: dict[str, Any], holding_weight_pct: float = 0.0) -> float:
    """Compute a composite score for a news item.

    Base score = 1.0
    + domain tier bonus (T0=+1.5, T1=+0.5, T2=+0.0, T3=-0.2)
    + keyword importance sum
    + holding weight bonus (max +0.5)
    + freshness bonus (max +0.5)
    """
    base = 1.0

    # Domain tier bonus
    domain = _extract_domain(item.get("url", ""))
    tier = 3
    for d, t in VERIFIED_DOMAINS.items():
        if d in domain or domain in d:
            tier = t
            break
    tier_bonus = {0: 1.5, 1: 0.5, 2: 0.0, 3: -0.2}.get(tier, -0.2)
    base += tier_bonus

    # Keyword importance
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
    keyword_score = 0.0
    for kw, weight in IMPORTANCE_KEYWORDS.items():
        if kw in text:
            keyword_score += weight
    keyword_score = max(-0.5, min(1.5, keyword_score))  # clamp
    base += keyword_score

    # Holding weight bonus
    if holding_weight_pct > 0:
        base += min(0.5, holding_weight_pct / 30.0)  # 15% weight → +0.5

    # Freshness bonus
    pub_str = item.get("published", "")
    if pub_str:
        try:
            age_hours = _parse_age_hours(pub_str)
            if age_hours is not None and age_hours < 48:
                base += min(0.5, (48 - age_hours) / 96.0)
        except Exception:
            pass

    return round(base, 2)


def tag_category(item: dict[str, Any]) -> str:
    """Tag a news item with a category based on content."""
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()

    if any(w in text for w in ("results", "earnings", "q1", "q2", "q3", "q4", "profit", "revenue", "eps")):
        return "earnings"
    if any(w in text for w in ("dividend", "bonus", "split", "rights", "buyback", "merger", "agm", "egm")):
        return "corporate_action"
    if any(w in text for w in ("sebi", "regulatory", "compliance", "penalty", "investigation", "rbi")):
        return "regulatory"
    if any(w in text for w in ("upgrade", "downgrade", "buy rating", "sell rating", "target price")):
        return "rating"
    if any(w in text for w in ("market", "sensex", "nifty", "fii", "dii", "index")):
        return "market"
    return "general"


def parse_published_at(item: dict[str, Any]) -> datetime | None:
    """Try multiple date formats from various sources."""
    pub_str = item.get("published", "")
    if not pub_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%d %b %Y",
        "%d-%b-%Y",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(pub_str, fmt)
        except ValueError:
            continue
    # Try ISO 8601 via fromisoformat
    try:
        return datetime.fromisoformat(pub_str)
    except ValueError:
        pass
    return None


def _parse_age_hours(pub_str: str) -> float | None:
    dt = parse_published_at({"published": pub_str})
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)
