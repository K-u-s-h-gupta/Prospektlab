"""Authoritative API-backed data sources (SEC EDGAR, Yahoo Finance, Wikipedia,
Reddit, Hacker News, StockTwits, FX).

Scraping is brittle. APIs are not. When the target is identifiable (a public
ticker or a well-known company name), we route through documented JSON
endpoints first and fall back to scraping only for context the APIs don't
cover. Community / social signals come from Reddit + StockTwits + HN —
they're labelled, structured, and stable.
"""

from finagent.tools.data.forex import FxRate, format_dual, format_inr, get_usd_inr
from finagent.tools.data.hackernews import HNStory, search_hackernews
from finagent.tools.data.news_feed import NewsItem, fetch_news
from finagent.tools.data.reddit import RedditPost, aggregate_sentiment, search_reddit
from finagent.tools.data.sec_edgar import (
    SECCompanySnapshot,
    SECMetric,
    SECSeriesPoint,
    SECTimeSeries,
    fetch_company_snapshot,
    resolve_ticker_or_name,
)
from finagent.tools.data.sec_filings import FilingNarrative, fetch_filing_narrative
from finagent.tools.data.stocktwits import StockTwit, StockTwitsSnapshot, fetch_stocktwits
from finagent.tools.data.wikipedia import WikipediaSummary, fetch_wikipedia_summary
from finagent.tools.data.yahoo_finance import YahooQuote, fetch_yahoo_quote

__all__ = [
    "FxRate",
    "get_usd_inr",
    "format_inr",
    "format_dual",
    "HNStory",
    "search_hackernews",
    "NewsItem",
    "fetch_news",
    "RedditPost",
    "search_reddit",
    "aggregate_sentiment",
    "SECCompanySnapshot",
    "SECMetric",
    "SECSeriesPoint",
    "SECTimeSeries",
    "fetch_company_snapshot",
    "resolve_ticker_or_name",
    "FilingNarrative",
    "fetch_filing_narrative",
    "StockTwit",
    "StockTwitsSnapshot",
    "fetch_stocktwits",
    "WikipediaSummary",
    "fetch_wikipedia_summary",
    "YahooQuote",
    "fetch_yahoo_quote",
]
