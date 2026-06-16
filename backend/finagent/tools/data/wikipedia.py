"""Wikipedia REST API client.

`https://en.wikipedia.org/api/rest_v1/page/summary/<URL-encoded title>`
returns a JSON object with `extract` (lead paragraph), `description`,
and `content_urls.desktop.page`. Robots is unrestricted for this endpoint and
the rate limit is generous.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import quote

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.wikipedia")

_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_SEARCH_URL = "https://en.wikipedia.org/w/api.php?action=opensearch&search={q}&limit=1&namespace=0&format=json"


@dataclass
class WikipediaSummary:
    title: str
    description: str | None
    extract: str
    url: str


async def _search_title(query: str, timeout_s: float) -> str | None:
    res = await fetch(_SEARCH_URL.format(q=quote(query)), respect_robots=False, timeout_s=timeout_s)
    if res.status != 200 or not res.text:
        return None
    try:
        data = json.loads(res.text)
        if isinstance(data, list) and len(data) >= 2 and data[1]:
            return data[1][0]
    except Exception as exc:
        logger.warning("wikipedia search parse failed: %s", exc)
    return None


async def fetch_wikipedia_summary(query: str, *, timeout_s: float = 12.0) -> WikipediaSummary | None:
    """Try direct title; if 404, opensearch then retry."""
    logger.info("[MCP-USE] research_news | tool=search_web | args={'query': 'wikipedia %s'}", query)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("research_news")
    except ImportError:
        pass
    # First try the query as-is (covers exact matches like "Apple Inc.")
    title_candidates = [query]
    direct = await fetch(
        _SUMMARY_URL.format(title=quote(query.replace(" ", "_"))),
        respect_robots=False,
        timeout_s=timeout_s,
    )
    if direct.status == 200 and direct.text:
        return _parse_summary(direct.text)
    # Else, opensearch to disambiguate.
    title = await _search_title(query, timeout_s)
    if not title or title in title_candidates:
        return None
    res = await fetch(
        _SUMMARY_URL.format(title=quote(title.replace(" ", "_"))),
        respect_robots=False,
        timeout_s=timeout_s,
    )
    if res.status != 200 or not res.text:
        return None
    return _parse_summary(res.text)


def _parse_summary(raw: str) -> WikipediaSummary | None:
    try:
        data = json.loads(raw)
    except Exception:
        return None
    extract = (data.get("extract") or "").strip()
    if not extract:
        return None
    return WikipediaSummary(
        title=data.get("title") or "",
        description=data.get("description"),
        extract=extract,
        url=(data.get("content_urls", {}).get("desktop", {}) or {}).get("page", ""),
    )
