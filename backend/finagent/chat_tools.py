"""Finance tools for the conversational chat agent (OpenAI function-calling).

These are what let chat *beat* Perplexity/Google Finance: instead of a blind
pre-fetch, the model decides which real-time source to pull — live quote,
shareholding/pledge, SEBI/exchange filings, the proprietary IKG governance
graph, recent news, or a web search — grounds its answer in the results, and
cites them. Every executor is defensive (short timeouts, never raises) and
records source URLs into a shared citation list.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("finagent.chat_tools")


# OpenAI tool schemas. Kept small and prescriptive ("call this when…") so the
# model triggers them precisely.
CHAT_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": (
                "Get the live market quote and key fundamentals (price, day change, "
                "market cap, P/E, P/B, ROE, 52-week range) for one Indian-listed "
                "company. Call this whenever the user asks about price, valuation "
                "multiples, market cap, or current fundamentals."
            ),
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string", "description": "Company name or NSE/BSE ticker, e.g. 'TCS' or 'Reliance'."}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_shareholding",
            "description": (
                "Get the shareholding pattern: promoter holding %, promoter pledge %, "
                "FII/DII holding. Call this for ownership, promoter-pledge, or "
                "institutional-holding questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_governance",
            "description": (
                "Query the proprietary IKG forensic governance graph: board/director "
                "network, promoter chain, pledge risk, related-party transactions, and "
                "SEBI enforcement history. Call this for governance, board, promoter, "
                "auditor, or regulatory-risk questions — this is data Perplexity and "
                "Google Finance do not have."
            ),
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_filings",
            "description": (
                "Fetch the latest SEBI / exchange (NSE/BSE) disclosure or filing for a "
                "company. Call this for the most recent regulatory filing, corporate "
                "action, or disclosure."
            ),
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Get recent news headlines (last ~90 days) for a company or topic. Call "
                "this for 'latest news', recent developments, concall takeaways, or "
                "sentiment."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Company name or topic."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current facts not covered by the other tools "
                "(macro data, sector trends, definitions, anything time-sensitive). "
                "Returns titled, cited results. Call this when current information "
                "would change the answer and no dedicated tool fits."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def _snippet(doc: Any, limit: int = 240) -> str:
    for attr in ("fit_markdown", "markdown", "snippet", "description", "text"):
        val = getattr(doc, attr, None) or (doc.get(attr) if isinstance(doc, dict) else None)
        if val:
            return str(val)[:limit]
    return ""


class ChatToolbox:
    """Executes chat finance tools and accumulates citations for one turn."""

    def __init__(self) -> None:
        self.citations: list[dict] = []
        self._seen_urls: set[str] = set()

    def _cite(self, title: str, url: str | None) -> None:
        if url and url not in self._seen_urls:
            self._seen_urls.add(url)
            self.citations.append({"title": (title or url)[:160], "url": url})

    async def execute(self, name: str, args: dict, timeout_s: float = 8.0) -> str:
        try:
            return await asyncio.wait_for(self._dispatch(name, args), timeout=timeout_s)
        except asyncio.TimeoutError:
            return json.dumps({"error": f"{name} timed out"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CHAT_TOOLS] %s failed: %s", name, exc)
            return json.dumps({"error": f"{name} failed: {type(exc).__name__}"})

    async def _dispatch(self, name: str, args: dict) -> str:
        if name == "get_quote":
            return await self._get_quote(args.get("symbol", ""))
        if name == "get_shareholding":
            return await self._get_shareholding(args.get("symbol", ""))
        if name == "get_governance":
            return await self._get_governance(args.get("symbol", ""))
        if name == "get_filings":
            return await self._get_filings(args.get("symbol", ""))
        if name == "get_news":
            return await self._get_news(args.get("query", ""))
        if name == "web_search":
            return await self._web_search(args.get("query", ""))
        return json.dumps({"error": f"unknown tool {name}"})

    def _label(self, symbol: str) -> str:
        from finagent.geo import resolve_entity
        try:
            ent = resolve_entity(symbol)
            return getattr(ent, "ticker_label", None) or symbol
        except Exception:
            return symbol

    async def _get_quote(self, symbol: str) -> str:
        from finagent.tools.data import fetch_india_snapshot, fetch_yahoo_quote
        label = self._label(symbol)
        quote = None
        india = None
        try:
            quote = await fetch_yahoo_quote(label)
        except Exception:
            pass
        try:
            india = await fetch_india_snapshot(label)
        except Exception:
            pass
        out: dict[str, Any] = {"symbol": symbol}
        if quote is not None:
            out["price"] = getattr(quote, "price", None)
            out["currency"] = getattr(quote, "currency", None)
            out["change_pct"] = getattr(quote, "change_pct", None)
            out["market_cap"] = getattr(quote, "market_cap", None)
            m = getattr(quote, "financial_metrics", None) or {}
            out["metrics"] = {k: m.get(k) for k in ("trailing_pe", "forward_pe", "price_to_book", "return_on_equity", "profit_margins", "debt_to_equity") if m.get(k) is not None}
            self._cite(f"{symbol} market data", getattr(quote, "source_url", None))
        if india is not None:
            summary = getattr(india, "summary", None) or getattr(india, "about", None)
            if summary:
                out["profile"] = str(summary)[:300]
        if not quote and not india:
            return json.dumps({"symbol": symbol, "error": "no quote data found"})
        return json.dumps(out, default=str)

    async def _get_shareholding(self, symbol: str) -> str:
        from finagent.tools.data import fetch_shareholding_pattern
        shp = await fetch_shareholding_pattern(self._label(symbol))
        if not shp:
            return json.dumps({"symbol": symbol, "error": "no shareholding data"})
        data = shp if isinstance(shp, dict) else getattr(shp, "__dict__", {})
        return json.dumps({"symbol": symbol, "shareholding": data}, default=str)[:2000]

    async def _get_governance(self, symbol: str) -> str:
        from finagent.tools.mcp.ikg_toolkit import get_ikg_toolkit
        bundle = await get_ikg_toolkit().company_bundle(identifier=self._label(symbol), depth="deep")
        if not bundle or bundle.get("status") != "ok":
            return json.dumps({"symbol": symbol, "error": "no IKG governance record"})
        # Trim to the governance-relevant slices to keep the payload tight.
        keep = {k: bundle.get(k) for k in ("directors", "promoter_chain", "pledge", "enforcement", "rpt", "auditors", "governance_score", "coverage") if k in bundle}
        return json.dumps({"symbol": symbol, "governance": keep}, default=str)[:3000]

    async def _get_filings(self, symbol: str) -> str:
        from finagent.tools.data import fetch_sebi_filing
        filing = await fetch_sebi_filing(self._label(symbol))
        if not filing:
            return json.dumps({"symbol": symbol, "error": "no recent filing"})
        url = getattr(filing, "url", None) or (filing.get("url") if isinstance(filing, dict) else None)
        title = getattr(filing, "title", None) or (filing.get("title") if isinstance(filing, dict) else "SEBI/exchange filing")
        self._cite(f"{symbol}: {title}", url)
        data = filing if isinstance(filing, dict) else getattr(filing, "__dict__", {})
        return json.dumps({"symbol": symbol, "filing": data}, default=str)[:2000]

    async def _get_news(self, query: str) -> str:
        from finagent.tools.data import fetch_news
        items = []
        try:
            items = await fetch_news(self._label(query)) or []
        except Exception:
            items = []
        out = []
        for it in items[:6]:
            title = getattr(it, "title", None) or (it.get("title") if isinstance(it, dict) else None)
            url = getattr(it, "url", None) or (it.get("url") if isinstance(it, dict) else None)
            date = getattr(it, "published", None) or getattr(it, "date", None) or (it.get("date") if isinstance(it, dict) else None)
            if title:
                out.append({"title": title, "date": str(date) if date else None, "url": url})
                self._cite(title, url)
        if not out:
            return json.dumps({"query": query, "error": "no recent news"})
        return json.dumps({"query": query, "news": out}, default=str)

    async def _web_search(self, query: str) -> str:
        from finagent.tools.web.scraper import search_web
        docs = await search_web(query, max_results=5)
        out = []
        for d in (docs or [])[:5]:
            title = getattr(d, "title", None) or ""
            url = getattr(d, "final_url", None) or getattr(d, "url", None)
            out.append({"title": title[:160], "url": url, "snippet": _snippet(d)})
            self._cite(title or url or query, url)
        if not out:
            return json.dumps({"query": query, "error": "no results"})
        return json.dumps({"query": query, "results": out}, default=str)[:3500]


__all__ = ["CHAT_TOOL_SPECS", "ChatToolbox"]
