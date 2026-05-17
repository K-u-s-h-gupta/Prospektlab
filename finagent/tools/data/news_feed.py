"""Google News RSS — broad news headline coverage, no API key required.

The `news.google.com/rss/search` endpoint takes a query and returns an RSS
2.0 feed with `<item>` blocks containing title / link / pubDate / source.
We parse with the stdlib (xml.etree), normalise Google's redirect links to
the publisher domain when possible, and emit a clean dataclass list.

This gives the agent live financial press coverage without depending on a
paid feed (Reuters / Bloomberg / WSJ all surface through Google News).
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote_plus

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.news_feed")

_RSS_URL = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str
    description: str


_SOURCE_TAG = re.compile(r"\s+-\s+([^-]+)$")


def _extract_source_from_title(title: str) -> tuple[str, str]:
    """Google News titles end with ' - Source Name'. Split that off."""
    m = _SOURCE_TAG.search(title)
    if not m:
        return title, ""
    return title[: m.start()].strip(), m.group(1).strip()


_NS = {"media": "http://search.yahoo.com/mrss/"}


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


async def fetch_news(
    query: str,
    *,
    limit: int = 12,
    hl: str = "en-IN",
    gl: str = "IN",
    ceid: str = "IN:en",
) -> list[NewsItem]:
    # ProspektLab is India-focused: append "NSE" for cleaner Indian results
    india_query = f"{query} NSE" if gl == "IN" and "nse" not in query.lower() else query
    url = _RSS_URL.format(q=quote_plus(india_query), hl=hl, gl=gl, ceid=ceid)
    try:
        res = await fetch(url, respect_robots=False, timeout_s=12.0)
    except Exception as exc:
        logger.warning("news rss fetch failed: %s", exc)
        try:
            from finagent.events import BUS
            BUS.emit("global", "agent_task", agent="news_feed", status="error", error=str(exc))
        except Exception:
            pass
        return []
    if res.status != 200 or not res.text:
        return []
    try:
        root = ET.fromstring(res.text)
    except ET.ParseError as exc:
        logger.warning("news rss parse failed: %s", exc)
        try:
            from finagent.events import BUS
            BUS.emit("global", "agent_task", agent="news_feed", status="error", error=str(exc))
        except Exception:
            pass
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    items: list[NewsItem] = []
    for item in channel.findall("item")[: limit * 2]:
        title_raw = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = _strip_html(item.findtext("description") or "")
        title, source = _extract_source_from_title(title_raw)
        if not title or not link:
            continue
        items.append(
            NewsItem(
                title=title,
                link=link,
                source=source or "Google News",
                published=pub,
                description=desc[:240],
            )
        )
        if len(items) >= limit:
            break
    return items
