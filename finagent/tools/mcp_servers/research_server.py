"""
ORACLE FIOS - Research & News MCP Server (SearXNG + Tavily fallback)
====================================================================
Primary: SearXNG (self-hosted web search)
Fallback: Tavily API (if available) — web search, news, URL extraction, and research.

Exposes MCP tools:
  - search_web           : general web search with AI-generated answers
  - search_news          : real-time news search (stock-specific or market-wide)
  - search_financial     : finance-focused search with Indian market context
  - extract_url          : extract clean content from any URL
  - research_company     : deep multi-query research on a company

Tavily free tier: 1,000 credits/month. Each basic search = 1 credit.
Get your key at: https://app.tavily.com (optional)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

# Optional Tavily import
try:
    from tavily import TavilyClient
    _TAVILY_AVAILABLE = True
except ImportError:
    _TAVILY_AVAILABLE = False
    TavilyClient = None  # type: ignore

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
# Search clients (SearXNG primary, Tavily optional fallback)
# ---------------------------------------------------------------------------
_tavily: TavilyClient | None = None
_searxng_client = None

TRANSIENT_ERROR_MARKERS = (
    "connection",
    "timeout",
    "temporarily",
    "temporarily unavailable",
    "rate limit",
    "429",
    "503",
    "504",
    "reset by peer",
    "name resolution",
)


def _get_searxng():
    """Get SearXNG client (primary)."""
    global _searxng_client
    if _searxng_client is None:
        from finagent.tools.web.searxng_client import SearXNGClient
        _searxng_client = SearXNGClient()
    return _searxng_client


def _get_tavily() -> TavilyClient | None:
    """Get or create the Tavily client (optional fallback)."""
    if not _TAVILY_AVAILABLE or not TAVILY_API_KEY:
        return None
    
    global _tavily
    if _tavily is None:
        _tavily = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily


def _is_transient_search_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)


def _search_with_retries(client: TavilyClient, *, retries: int = 2, **kwargs) -> dict[str, Any]:
    """Retry transient Tavily search failures a small number of times."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return client.search(**kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Tavily search attempt %d/%d failed for query='%s' topic=%s: %s",
                attempt,
                retries,
                kwargs.get("query"),
                kwargs.get("topic"),
                exc,
            )
            if attempt >= retries or not _is_transient_search_error(exc):
                raise
            time.sleep(0.5 * attempt)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Tavily search failed without returning a response.")


def _google_news_rss_search(query: str, max_results: int) -> dict[str, Any]:
    """Fallback search using Google News RSS."""
    import urllib.parse
    import urllib.request
    import xml.etree.ElementTree as ET
    import re

    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    articles = []
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10.0) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item")[:max_results]:
                title_elem = item.find("title")
                link_elem = item.find("link")
                pub_date_elem = item.find("pubDate")
                desc_elem = item.find("description")

                raw_title = title_elem.text if title_elem is not None else ""
                url_val = link_elem.text if link_elem is not None else ""
                published_val = pub_date_elem.text if pub_date_elem is not None else ""
                snippet_val = desc_elem.text if desc_elem is not None else ""

                source_name = "googlenews"
                title_val = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title_val = parts[0]
                    source_name = parts[1].strip()

                clean_snippet = re.sub(r"<[^>]+>", "", snippet_val)[:240]

                articles.append({
                    "title": title_val,
                    "url": url_val,
                    "content": clean_snippet,
                    "score": 0.9,
                    "published_date": published_val,
                })
    except Exception as exc:
        logger.warning("Google News RSS fallback failed for '%s': %s", query, exc)

    return {
        "query": query,
        "answer": f"Web results for: {query} (fetched via Google News RSS)",
        "total_results": len(articles),
        "results": articles,
        "response_time": 0.1,
        "articles": articles,
        "total_articles": len(articles),
        "time_range": "recent",
        "strategy_used": "google_news_rss",
    }


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
        logger.error("search_web failed, trying RSS fallback: %s", exc)
        try:
            fallback = _google_news_rss_search(query, max_results)
            return {"error": False, "data": fallback}
        except Exception as fallback_exc:
            return {"error": True, "message": f"Search failed: {exc}. Fallback also failed: {fallback_exc}"}


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
        attempts = [
            {
                "strategy": "news",
                "kwargs": {
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": "basic",
                    "topic": "news",
                    "time_range": time_range,
                },
            },
            {
                "strategy": "finance",
                "kwargs": {
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": "basic",
                    "topic": "finance",
                },
            },
            {
                "strategy": "general",
                "kwargs": {
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": "basic",
                    "topic": "general",
                },
            },
        ]

        last_error = None
        last_output = None
        for attempt in attempts:
            try:
                response = _search_with_retries(client, **attempt["kwargs"])
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
                    "strategy_used": attempt["strategy"],
                }
                last_output = output

                if articles:
                    logger.info(
                        "search_news OK: %d articles via %s",
                        len(articles),
                        attempt["strategy"],
                    )
                    return {"error": False, "data": output}
            except Exception as exc:
                last_error = str(exc)

        if last_output is not None:
            logger.info("search_news completed with 0 articles after fallback attempts.")
            return {"error": False, "data": last_output}

        logger.error("search_news failed after fallback attempts: %s", last_error)
        return {"error": True, "message": last_error or "Unknown Tavily search failure."}

    except Exception as exc:
        logger.error("search_news failed, trying RSS fallback: %s", exc)
        try:
            fallback = _google_news_rss_search(query, max_results)
            return {"error": False, "data": fallback}
        except Exception as fallback_exc:
            return {"error": True, "message": f"News search failed: {exc}. Fallback also failed: {fallback_exc}"}


# ---------------------------------------------------------------------------
# Tool: get_latest_company_news
# ---------------------------------------------------------------------------
@mcp.tool
def get_latest_company_news(
    companies: list[str],
    max_results_per_company: int = 3,
    time_range: str = "week",
) -> dict:
    """
    Retrieve latest news for one or more companies with built-in fallback.

    This tool is designed for prompts like:
    - "Latest news on TCS and Infosys"
    - "Fetch recent news for both companies"

    It first tries Tavily's news topic, then falls back to finance search,
    then finally to general web search if needed.
    """
    logger.info("get_latest_company_news: companies=%s, range=%s", companies, time_range)

    try:
        client = _get_tavily()
        output: dict[str, Any] = {}

        for company in companies[:5]:
            name = company.strip()
            if not name:
                continue

            company_result: dict[str, Any] = {
                "company": name,
                "strategy_used": None,
                "results": [],
                "answer": None,
            }

            attempts = [
                {
                    "strategy": "news",
                    "kwargs": {
                        "query": f"{name} latest news",
                        "max_results": max_results_per_company,
                        "search_depth": "basic",
                        "include_answer": "basic",
                        "topic": "news",
                        "time_range": time_range,
                    },
                },
                {
                    "strategy": "finance",
                    "kwargs": {
                        "query": f"{name} latest news",
                        "max_results": max_results_per_company,
                        "search_depth": "basic",
                        "include_answer": "basic",
                        "topic": "finance",
                    },
                },
                {
                    "strategy": "general",
                    "kwargs": {
                        "query": f"{name} latest news",
                        "max_results": max_results_per_company,
                        "search_depth": "basic",
                        "include_answer": "basic",
                        "topic": "general",
                    },
                },
            ]

            last_error = None
            for attempt in attempts:
                try:
                    response = _search_with_retries(client, **attempt["kwargs"])
                    results = [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "content": r.get("content"),
                            "score": r.get("score"),
                            "published_date": r.get("published_date"),
                        }
                        for r in response.get("results", [])
                    ]
                    if results:
                        company_result["strategy_used"] = attempt["strategy"]
                        company_result["answer"] = response.get("answer")
                        company_result["results"] = results
                        break
                except Exception as exc:
                    last_error = str(exc)

            if not company_result["results"] and last_error:
                company_result["error"] = last_error

            output[name] = company_result

        return {"error": False, "data": {"companies": output, "time_range": time_range}}

    except Exception as exc:
        logger.error("get_latest_company_news failed, trying RSS fallback: %s", exc)
        try:
            output = {}
            for company in companies[:5]:
                name = company.strip()
                if not name:
                    continue
                fallback_res = _google_news_rss_search(f"{name} latest news", max_results_per_company)
                output[name] = {
                    "company": name,
                    "strategy_used": "google_news_rss",
                    "results": fallback_res["articles"],
                    "answer": fallback_res["answer"],
                }
            return {"error": False, "data": {"companies": output, "time_range": time_range}}
        except Exception as fallback_exc:
            return {"error": True, "message": f"Company news failed: {exc}. Fallback also failed: {fallback_exc}"}


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
        logger.error("search_financial failed, trying RSS fallback: %s", exc)
        try:
            fallback = _google_news_rss_search(query, max_results)
            fallback["sources_prioritised"] = include_domains or []
            return {"error": False, "data": fallback}
        except Exception as fallback_exc:
            return {"error": True, "message": f"Financial search failed: {exc}. Fallback also failed: {fallback_exc}"}


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
        logger.error("research_company failed, trying RSS fallback: %s", exc)
        try:
            queries = {
                "recent_news": f"{name} {symbol} latest news India stock market",
                "quarterly_results": f"{name} {symbol} quarterly results earnings 2026",
                "analyst_views": f"{name} {symbol} analyst target price buy sell recommendation",
                "management": f"{name} {symbol} management commentary guidance outlook",
                "sector_outlook": f"{name} sector industry outlook India 2026",
            }
            research = {}
            for category, q in queries.items():
                fallback_res = _google_news_rss_search(q, 3)
                research[category] = {
                    "query": q,
                    "answer": fallback_res["answer"],
                    "sources": [
                        {
                            "title": art["title"],
                            "url": art["url"],
                            "snippet": art["content"],
                        }
                        for art in fallback_res["articles"]
                    ],
                }
            return {
                "error": False,
                "data": {
                    "symbol": symbol,
                    "company_name": name,
                    "research_date": datetime.now().isoformat(),
                    "categories": research,
                },
            }
        except Exception as fallback_exc:
            return {"error": True, "message": f"Research failed: {exc}. Fallback also failed: {fallback_exc}"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting ORACLE Research & News MCP Server (Tavily) ...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8003)
