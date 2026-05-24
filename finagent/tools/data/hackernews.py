"""Hacker News search via Algolia (no auth required).

HN is a strong signal for technology / product / SaaS coverage that mainstream
financial press misses. The Algolia API ranks by points + comments and
returns clean JSON. We tag each hit with the canonical hn.ycombinator.com URL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote_plus

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.hn")

_HN_API = "https://hn.algolia.com/api/v1/search?query={q}&tags=story&hitsPerPage=15"


@dataclass
class HNStory:
    title: str
    url: str
    hn_url: str
    points: int
    num_comments: int
    author: str
    created: str


async def search_hackernews(query: str, *, min_points: int = 3) -> list[HNStory]:
    logger.info("[MCP-USE] research_news | tool=search_web | args={'query': 'hackernews %s'}", query)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("research_news")
    except ImportError:
        pass
    url = _HN_API.format(q=quote_plus(query))
    try:
        res = await fetch(url, respect_robots=False, timeout_s=10.0)
    except Exception as exc:
        logger.info("hn fetch failed: %s", exc)
        return []
    if res.status != 200 or not res.text:
        return []
    try:
        payload = json.loads(res.text)
    except Exception:
        return []
    out: list[HNStory] = []
    for hit in payload.get("hits") or []:
        points = int(hit.get("points") or 0)
        if points < min_points:
            continue
        story_url = hit.get("url") or ""
        story_id = hit.get("objectID")
        hn_link = f"https://news.ycombinator.com/item?id={story_id}" if story_id else ""
        created_at = hit.get("created_at_i")
        created = (
            datetime.fromtimestamp(int(created_at), tz=timezone.utc).isoformat()
            if created_at
            else ""
        )
        out.append(
            HNStory(
                title=(hit.get("title") or "").strip()[:240],
                url=story_url,
                hn_url=hn_link,
                points=points,
                num_comments=int(hit.get("num_comments") or 0),
                author=(hit.get("author") or "")[:60],
                created=created,
            )
        )
    out.sort(key=lambda h: (h.points, h.num_comments), reverse=True)
    return out[:10]
