"""StockTwits public stream API.

`api.stocktwits.com/api/2/streams/symbol/{TICKER}.json` returns the most
recent ~30 messages tagged with the symbol, each with a self-declared
Bullish / Bearish sentiment tag set by the author. That's a much cleaner
sentiment signal than scraping X — it's already labelled.

Heavy throttling is possible (~200 req/h per IP) but we only call it once
per session per ticker.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.stocktwits")

_STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"


@dataclass
class StockTwit:
    user: str
    body: str
    sentiment: str  # bullish | bearish | unrated
    created: str
    likes: int


@dataclass
class StockTwitsSnapshot:
    ticker: str
    company: str | None
    messages: list[StockTwit]
    bullish: int
    bearish: int
    unrated: int

    @property
    def net_sentiment(self) -> str:
        if self.bullish > self.bearish * 1.5 and self.bullish >= 3:
            return "bullish"
        if self.bearish > self.bullish * 1.5 and self.bearish >= 3:
            return "bearish"
        return "mixed"


async def fetch_stocktwits(ticker: str) -> StockTwitsSnapshot | None:
    if not ticker:
        return None
    logger.info("[MCP-USE] research_news | tool=search_web | args={'query': 'stocktwits %s'}", ticker)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("research_news")
    except ImportError:
        pass
    url = _STREAM_URL.format(ticker=ticker.upper())
    try:
        res = await fetch(url, respect_robots=False, timeout_s=10.0)
    except Exception as exc:
        logger.info("stocktwits fetch failed: %s", exc)
        return None
    if res.status != 200 or not res.text:
        return None
    try:
        payload = json.loads(res.text)
    except Exception:
        return None
    if payload.get("response", {}).get("status") != 200:
        return None
    symbol = payload.get("symbol") or {}
    msgs_raw = payload.get("messages") or []
    msgs: list[StockTwit] = []
    bull = bear = unr = 0
    for m in msgs_raw[:30]:
        sentiment_obj = (m.get("entities") or {}).get("sentiment") or {}
        sentiment = (sentiment_obj.get("basic") or "").lower() or "unrated"
        if sentiment == "bullish":
            bull += 1
        elif sentiment == "bearish":
            bear += 1
        else:
            unr += 1
        user = ((m.get("user") or {}).get("username") or "")[:60]
        likes = int((m.get("likes") or {}).get("total") or 0)
        msgs.append(
            StockTwit(
                user=user,
                body=(m.get("body") or "")[:280],
                sentiment=sentiment,
                created=(m.get("created_at") or "")[:25],
                likes=likes,
            )
        )
    if not msgs:
        return None
    return StockTwitsSnapshot(
        ticker=ticker.upper(),
        company=symbol.get("title"),
        messages=msgs,
        bullish=bull,
        bearish=bear,
        unrated=unr,
    )
