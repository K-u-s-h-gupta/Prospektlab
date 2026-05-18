import os

file_path = "finagent/synthesis.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update docstring
old_doc = '''"""LLM synthesis pass — turn the full evidence pool into a readable memo.

When OPENAI_API_KEY is set we stream tokens from OpenAI. When it isn't
we still produce a polished prose memo (proper paragraphs, no bullet
clutter, no boilerplate disclosures) from the same fact bundle.

All USD figures are duplicated in INR using the live USDINR Yahoo quote
fetched at session start. The memo never invents numbers — every figure
is sourced from the SEC EDGAR companyfacts API, the 10-K narrative we
pulled directly, the live Yahoo quote, or one of the community signals.
"""'''
new_doc = '''"""LLM synthesis pass — turn the full evidence pool into a readable memo.

When OPENAI_API_KEY is set we stream tokens from OpenAI. When it isn't
we still produce a polished prose memo from the same fact bundle.

All monetary figures are presented in INR (crore/lakh notation) first.
The memo never invents numbers — every figure is sourced from NSE/BSE,
Moneycontrol, Screener.in, SEBI filings, the live Yahoo quote (.NS/.BO),
or community signals.
"""'''
content = content.replace(old_doc, new_doc)

# 2. Imports
old_imports = '''from finagent.tools.data import (
    FilingNarrative,
    FxRate,
    HNStory,
    NewsItem,
    RedditPost,
    SECCompanySnapshot,
    StockTwitsSnapshot,
    WikipediaSummary,
    YahooQuote,
    format_dual,
    format_inr,
    fetch_yahoo_quote,
)'''
new_imports = '''from finagent.tools.data import (
    FxRate,
    HNStory,
    IndiaCompanySnapshot,
    NewsItem,
    RedditPost,
    SEBIFiling,
    StockTwitsSnapshot,
    WikipediaSummary,
    YahooQuote,
    format_dual,
    format_inr,
    fetch_yahoo_quote,
)'''
content = content.replace(old_imports, new_imports)

# 3. EnrichmentBundle class
old_bundle = '''@dataclass
class EnrichmentBundle:
    sec: SECCompanySnapshot | None = None
    yahoo: YahooQuote | None = None
    wikipedia: WikipediaSummary | None = None
    filing: FilingNarrative | None = None
    fx: FxRate | None = None
    reddit: list[RedditPost] = field(default_factory=list)
    hackernews: list[HNStory] = field(default_factory=list)
    stocktwits: StockTwitsSnapshot | None = None
    news: list[NewsItem] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(
            self.sec
            or self.yahoo
            or self.wikipedia
            or self.filing
            or self.reddit
            or self.hackernews
            or self.stocktwits
            or self.news
        )'''
new_bundle = '''@dataclass
class EnrichmentBundle:
    # India-specific data sources
    india_snap: IndiaCompanySnapshot | None = None
    sebi_filing: SEBIFiling | None = None
    shareholding: dict | None = None
    # Universal sources
    yahoo: YahooQuote | None = None
    wikipedia: WikipediaSummary | None = None
    fx: FxRate | None = None
    reddit: list[RedditPost] = field(default_factory=list)
    hackernews: list[HNStory] = field(default_factory=list)
    stocktwits: StockTwitsSnapshot | None = None
    news: list[NewsItem] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(
            self.india_snap
            or self.yahoo
            or self.wikipedia
            or self.sebi_filing
            or self.reddit
            or self.hackernews
            or self.stocktwits
            or self.news
        )

    # Back-compat shims for older synthesis logic
    @property
    def sec(self) -> IndiaCompanySnapshot | None:       # type: ignore[override]
        return self.india_snap

    @property
    def filing(self) -> SEBIFiling | None:              # type: ignore[override]
        return self.sebi_filing'''
content = content.replace(old_bundle, new_bundle)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Synthesis replace complete.")
