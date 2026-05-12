"""
ORACLE FIOS - Research & News MCP Server (Tavily)
===================================================
Powered by Tavily API — web search, news, URL extraction, and research.

Exposes MCP tools:
  - search_web           : general web search with AI-generated answers
  - search_news          : real-time news search (stock-specific or market-wide)
  - search_financial     : finance-focused search with Indian market context
  - extract_url          : extract clean content from any URL
  - research_company     : deep multi-query research on a company

Tavily free tier: 1,000 credits/month. Each basic search = 1 credit.
Get your key at: https://app.tavily.com
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP
from tavily import TavilyClient

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("oracle.research_mcp")

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "ORACLE Research & News",
    instructions=(
        "Web search, news, and research tools powered by Tavily. "
        "Use search_news for latest market news, search_financial for "
        "finance-specific queries, extract_url to read any webpage, "
        "and research_company for deep multi-angle company research. "
        "Part of the ORACLE Financial Intelligence OS."
    ),
)

# ---------------------------------------------------------------------------
# Tavily client (lazy init)
# ---------------------------------------------------------------------------
_tavily: TavilyClient | None = None


def _get_tavily() -> TavilyClient:
    """Get or create the Tavily client."""
    global _tavily
    if _tavily is None:
        if not TAVILY_API_KEY:
            raise ValueError(
                "TAVILY_API_KEY is not configured. "
                "Set it in your .env file (get one at https://app.tavily.com)"
            )
        _tavily = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily


# ---------------------------------------------------------------------------
# Tool: search_web
# ---------------------------------------------------------------------------
@mcp.tool
def search_web(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = True,
    time_range: str | None = None,
) -> dict:
    """
    Perform a general web search using Tavily.

    Args:
        query:         The search query (e.g. "SEBI new regulations 2026").
        max_results:   Number of results to return (1-20, default 5).
        search_depth:  "basic" (1 credit) or "advanced" (2 credits).
        include_answer: Include an AI-generated answer summary.
        time_range:    Filter by time: "day", "week", "month", "year", or None.

    Returns:
        dict with: answer (AI summary), results list with title/url/content/score.
    """
    logger.info("search_web: query='%s', depth=%s, max=%d", query, search_depth, max_results)

    try:
        client = _get_tavily()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer="basic" if include_answer else False,
            topic="general",
            time_range=time_range,
        )

        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
                "score": r.get("score"),
            })

        output = {
            "query": query,
            "answer": response.get("answer"),
            "total_results": len(results),
            "results": results,
            "response_time": response.get("response_time"),
        }

        logger.info("search_web OK: %d results", len(results))
        return {"error": False, "data": output}

    except Exception as exc:
        logger.error("search_web failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: search_news
# ---------------------------------------------------------------------------
@mcp.tool
def search_news(
    query: str,
    max_results: int = 10,
    time_range: str = "week",
) -> dict:
    """
    Search for latest news articles using Tavily News topic.
    Optimised for real-time news about stocks, markets, and finance.

    Args:
        query:       News search query (e.g. "TCS quarterly results",
                     "Indian stock market today", "RBI policy update").
        max_results: Number of results (1-20, default 10).
        time_range:  "day", "week" (default), "month", or "year".

    Returns:
        dict with: answer, articles list with title/url/source/date/snippet.
    """
    logger.info("search_news: query='%s', range=%s", query, time_range)

    try:
        client = _get_tavily()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            include_answer="basic",
            topic="news",
            time_range=time_range,
        )

        articles = []
        for r in response.get("results", []):
            articles.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
                "score": r.get("score"),
                "published_date": r.get("published_date"),
            })

        output = {
            "query": query,
            "answer": response.get("answer"),
            "total_articles": len(articles),
            "articles": articles,
            "time_range": time_range,
        }

        logger.info("search_news OK: %d articles", len(articles))
        return {"error": False, "data": output}

    except Exception as exc:
        logger.error("search_news failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: search_financial
# ---------------------------------------------------------------------------
@mcp.tool
def search_financial(
    query: str,
    max_results: int = 4,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
) -> dict:
    """
    Finance-focused web search with Indian market context.
    Prioritises financial sources like MoneyControl, Economic Times,
    Screener, Trendlyne, BSE, NSE, and SEBI.

    Args:
        query:           Financial query (e.g. "Reliance Industries Q4 2026 results").
        max_results:     Number of results (1-20, default 5).
        search_depth:    "basic" or "advanced" (default, deeper extraction).
        include_domains: Optional list of domains to prioritise.

    Returns:
        dict with: answer, results with financial-source-prioritised content.
    """
    logger.info("search_financial: query='%s'", query)

    # Default Indian financial sources if not specified
    if include_domains is None:
        include_domains = [
            "moneycontrol.com",
            "economictimes.indiatimes.com",
            "screener.in",
            "trendlyne.com",
            "bseindia.com",
            "nseindia.com",
            "livemint.com",
            "businesstoday.in",
            "ndtvprofit.com",
            "sebi.gov.in",
        ]

    try:
        client = _get_tavily()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer="basic",
            topic="finance",
            include_domains=include_domains,
        )

        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
                "score": r.get("score"),
            })

        output = {
            "query": query,
            "answer": response.get("answer"),
            "total_results": len(results),
            "results": results,
            "sources_prioritised": include_domains,
        }

        logger.info("search_financial OK: %d results", len(results))
        return {"error": False, "data": output}

    except Exception as exc:
        logger.error("search_financial failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: extract_url
# ---------------------------------------------------------------------------
@mcp.tool
def extract_url(
    urls: list[str],
    extract_depth: str = "basic",
) -> dict:
    """
    Extract clean, structured content from one or more URLs.
    Useful for reading articles, reports, and web pages.

    Args:
        urls:          List of URLs to extract content from (max 20).
        extract_depth: "basic" (faster) or "advanced" (tables + embedded content).

    Returns:
        dict with: extracted content for each URL (markdown format).
    """
    logger.info("extract_url: %d URLs, depth=%s", len(urls), extract_depth)

    try:
        client = _get_tavily()
        response = client.extract(
            urls=urls,
            extract_depth=extract_depth,
        )

        results = []
        for r in response.get("results", []):
            results.append({
                "url": r.get("url"),
                "content": r.get("raw_content", ""),
            })

        failed = []
        for f in response.get("failed_results", []):
            failed.append({
                "url": f.get("url"),
                "error": f.get("error"),
            })

        output = {
            "total_extracted": len(results),
            "total_failed": len(failed),
            "results": results,
            "failed": failed,
            "response_time": response.get("response_time"),
        }

        logger.info("extract_url OK: %d extracted, %d failed", len(results), len(failed))
        return {"error": False, "data": output}

    except Exception as exc:
        logger.error("extract_url failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: research_company
# ---------------------------------------------------------------------------
@mcp.tool
def research_company(symbol: str, company_name: str | None = None) -> dict:
    """
    Perform deep multi-angle research on a company by running multiple
    targeted searches. Covers: recent news, management commentary,
    analyst views, regulatory filings, and sector outlook.

    Args:
        symbol:       Stock symbol (e.g. "RELIANCE", "TCS").
        company_name: Full company name (optional, auto-detected if omitted).

    Returns:
        dict with categorised research results across 5 dimensions.
    """
    symbol = symbol.strip().upper()
    name = company_name or symbol
    logger.info("research_company: %s (%s)", symbol, name)

    try:
        client = _get_tavily()

        # Run multiple targeted searches
        queries = {
            "recent_news": f"{name} {symbol} latest news India stock market",
            "quarterly_results": f"{name} {symbol} quarterly results earnings 2026",
            "analyst_views": f"{name} {symbol} analyst target price buy sell recommendation",
            "management": f"{name} {symbol} management commentary guidance outlook",
            "sector_outlook": f"{name} sector industry outlook India 2026",
        }

        research = {}
        for category, query in queries.items():
            try:
                response = client.search(
                    query=query,
                    max_results=3,
                    search_depth="basic",
                    include_answer="basic",
                    topic="news" if category == "recent_news" else "finance",
                    time_range="month",
                )

                research[category] = {
                    "query": query,
                    "answer": response.get("answer"),
                    "sources": [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "snippet": (r.get("content") or "")[:300],
                        }
                        for r in response.get("results", [])
                    ],
                }
            except Exception as e:
                research[category] = {"query": query, "error": str(e)}

        logger.info("research_company OK: %s - %d categories", symbol, len(research))
        return {
            "error": False,
            "data": {
                "symbol": symbol,
                "company_name": name,
                "research_date": datetime.now().isoformat(),
                "categories": research,
            },
        }

    except Exception as exc:
        logger.error("research_company failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting ORACLE Research & News MCP Server (Tavily) ...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8003)
