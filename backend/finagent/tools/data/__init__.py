"""Authoritative API-backed data sources for Indian financial markets.

Primary sources: Moneycontrol / Screener.in (pre-parsed, rarely rate-limited)
Secondary: NSE India API (live quote, corporate actions)
Fallback: BSE India API (BSE-only listings / NSE down)
Supplementary: Yahoo Finance (.NS/.BO tickers), Wikipedia, Google News RSS,
               Reddit (r/IndianStreetBets), Hacker News, StockTwits, FX rates.

This data layer is India-only at runtime.
"""

from finagent.tools.data.cache import (
    cache_ttl,
    cache_get,
    cache_set,
    cache_stats,
    is_market_hours,
)
from finagent.tools.data.forex import FxRate, format_dual, format_inr, get_usd_inr
from finagent.tools.data.hackernews import HNStory, search_hackernews
from finagent.tools.data.india import (
    IndiaCompanySnapshot,
    SEBIFiling,
    fetch_india_snapshot,
    fetch_nse_delivery_snapshot,
    fetch_nse_snapshot,
    fetch_sebi_filing,
    fetch_shareholding_pattern,
)
from finagent.tools.data.news_feed import NewsItem, fetch_news
from finagent.tools.data.reddit import RedditPost, aggregate_sentiment, search_reddit
from finagent.tools.data.stocktwits import StockTwit, StockTwitsSnapshot, fetch_stocktwits
from finagent.tools.data.wikipedia import WikipediaSummary, fetch_wikipedia_summary
from finagent.tools.data.yahoo_finance import YahooQuote, fetch_yahoo_chart, fetch_yahoo_quote
FilingNarrative = SEBIFiling
SECCompanySnapshot = IndiaCompanySnapshot
SECTimeSeries = dict


async def fetch_company_snapshot(query: str, *args, **kwargs) -> IndiaCompanySnapshot | None:
    return await fetch_india_snapshot(query)


async def fetch_filing_narrative(*args, **kwargs):
    return None

__all__ = [
    # Cache helpers
    "cache_ttl",
    "cache_get",
    "cache_set",
    "cache_stats",
    "is_market_hours",
    # FX
    "FxRate",
    "get_usd_inr",
    "format_inr",
    "format_dual",
    # India-specific
    "IndiaCompanySnapshot",
    "SEBIFiling",
    "fetch_india_snapshot",
    "fetch_nse_delivery_snapshot",
    "fetch_nse_snapshot",
    "fetch_sebi_filing",
    "fetch_shareholding_pattern",
    # Social / community
    "HNStory",
    "search_hackernews",
    "NewsItem",
    "fetch_news",
    "RedditPost",
    "search_reddit",
    "aggregate_sentiment",
    "StockTwit",
    "StockTwitsSnapshot",
    "fetch_stocktwits",
    # Reference
    "WikipediaSummary",
    "fetch_wikipedia_summary",
    # Market data
    "YahooQuote",
    "fetch_yahoo_quote",
    "fetch_yahoo_chart",
    # Filing compatibility aliases
    "FilingNarrative",
    "fetch_filing_narrative",
    "SECCompanySnapshot",
    "SECTimeSeries",
    "fetch_company_snapshot",
]
