"""Reddit search via the public JSON API (no auth, generous rate limit).

We hit r/wallstreetbets, r/stocks, r/investing, and r/SecurityAnalysis with
the company name + ticker. Each post returns title / selftext / score / num
comments — we keep only posts with score >= 5 to filter the noise, then
heuristically tag for sentiment (bullish / bearish / hype / accusation).

This is one of the inputs the agent uses to corroborate or contradict the
"viral falsify info" angle: a stock with 50 high-upvote WSB posts in 48h
but no real news coverage is a classic pump signal.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote_plus

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.reddit")

_SUBS = (
    "wallstreetbets",
    "stocks",
    "investing",
    "SecurityAnalysis",
    "ValueInvesting",
)
_SEARCH_URL = "https://www.reddit.com/r/{sub}/search.json?q={q}&restrict_sr=1&sort=new&limit=8&t=year"


@dataclass
class RedditPost:
    subreddit: str
    title: str
    selftext: str
    score: int
    num_comments: int
    created: str
    permalink: str
    url: str
    author: str
    sentiment: str  # bullish | bearish | hype | neutral


_BULLISH_TOKENS = ("rocket", "moon", "100x", "10x", "bullish", "long", "buy the dip", "diamond hands", "yolo")
_BEARISH_TOKENS = ("puts", "short", "crash", "bagholder", "rugpull", "scam", "fraud", "overvalued")
_HYPE_TOKENS = ("squeeze", "pump", "going parabolic", "to the moon", "gamma", "easy money", "free money")


def _classify(text: str) -> str:
    t = text.lower()
    hype = sum(1 for tok in _HYPE_TOKENS if tok in t)
    bull = sum(1 for tok in _BULLISH_TOKENS if tok in t)
    bear = sum(1 for tok in _BEARISH_TOKENS if tok in t)
    if hype >= 2:
        return "hype"
    if bear > bull:
        return "bearish"
    if bull > bear:
        return "bullish"
    return "neutral"


async def _fetch_sub(sub: str, query: str) -> list[RedditPost]:
    url = _SEARCH_URL.format(sub=sub, q=quote_plus(query))
    try:
        res = await fetch(url, respect_robots=False, timeout_s=10.0)
    except Exception as exc:
        logger.info("reddit fetch failed (%s): %s", sub, exc)
        return []
    if res.status != 200 or not res.text:
        return []
    try:
        payload = json.loads(res.text)
    except Exception:
        return []
    posts: list[RedditPost] = []
    for child in (payload.get("data") or {}).get("children") or []:
        d = child.get("data") or {}
        if not isinstance(d, dict):
            continue
        score = int(d.get("score") or 0)
        if score < 5:
            continue
        title = (d.get("title") or "").strip()
        selftext = (d.get("selftext") or "").strip()[:500]
        sent = _classify(f"{title} {selftext}")
        created_ts = d.get("created_utc")
        created = (
            datetime.fromtimestamp(int(created_ts), tz=timezone.utc).isoformat()
            if created_ts
            else ""
        )
        posts.append(
            RedditPost(
                subreddit=sub,
                title=title[:240],
                selftext=selftext,
                score=score,
                num_comments=int(d.get("num_comments") or 0),
                created=created,
                permalink=f"https://www.reddit.com{d.get('permalink', '')}",
                url=d.get("url") or "",
                author=(d.get("author") or "")[:60],
                sentiment=sent,
            )
        )
    return posts


async def search_reddit(query: str, *, max_total: int = 20) -> list[RedditPost]:
    """Query each sub serially with a small concurrency cap — Reddit's free
    JSON endpoint 429s if you parallel-fan too aggressively."""
    import asyncio

    sem = asyncio.Semaphore(2)

    async def _bound(sub: str) -> list[RedditPost]:
        async with sem:
            return await _fetch_sub(sub, query)

    batches = await asyncio.gather(*(_bound(s) for s in _SUBS), return_exceptions=True)
    out: list[RedditPost] = []
    for b in batches:
        if isinstance(b, Exception):
            continue
        out.extend(b)
    out.sort(key=lambda p: (p.score, p.num_comments), reverse=True)
    return out[:max_total]


def aggregate_sentiment(posts: list[RedditPost]) -> dict[str, int]:
    counts = {"bullish": 0, "bearish": 0, "hype": 0, "neutral": 0}
    for p in posts:
        counts[p.sentiment] = counts.get(p.sentiment, 0) + 1
    return counts
