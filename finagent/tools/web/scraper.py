"""High-level scraping: search → fetch top results → parse → citation set.

Architecture (post-Crawl4AI refactor):
  Phase 1 — Fan-out Search:
      Tavily, DuckDuckGo, and Bing execute concurrently via asyncio.gather.
      Tavily results are used directly (pre-enriched snippets, no re-crawl).

  Phase 2 — Domain Deduplication:
      DDG + Bing URLs are interleaved and deduplicated by URL key, then
      capped at max_per_domain=2 to suppress syndicated press-release noise
      (e.g., the same BSE announcement mirrored across 8 aggregators).

  Phase 3 — Crawl4AI Batch Crawl:
      A local headless Chromium instance (via Crawl4AI's AsyncWebCrawler)
      browser-renders the deduplicated candidate URLs concurrently.
      PruningContentFilter removes nav/footer boilerplate.
      DefaultMarkdownGenerator converts HTML tables → markdown grids natively.

  Phase 4 — Rerank:
      All docs (Tavily + Crawl4AI) are scored by source tier, query
      relevance, and entity signals, then sliced to max_results.

Defensive fallbacks (kept intact):
  _extract / _narrative_excerpt / _wants_narrative / fetch_and_parse
  activate when Crawl4AI is unavailable (ImportError) or a URL errors out.
"""

from __future__ import annotations

import asyncio
import logging
import sys

# Programmatically reconfigure stdout/stderr to utf-8 to prevent charmap codec errors on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

import os
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import quote_plus, urlparse

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.retrieval.reranker import rerank_docs
from finagent.retrieval.sparse_index import sanitize_search_query
from finagent.tools.data.units import normalize_financial_text_units
from finagent.tools.web.http_fetcher import FetchResult, fetch
from finagent.tools.web.table_parser import extract_layout_preserving_text

import threading
logger = logging.getLogger("finagent.scraper")

# Global variables for thread/loop-safe serialization
_LOOP_SEMAPHORES = {}
_LOOP_SEMAPHORES_LOCK = threading.Lock()
_CRAWLER_THREAD_LOCK = threading.Lock()

def _get_crawler_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with _LOOP_SEMAPHORES_LOCK:
        if loop not in _LOOP_SEMAPHORES:
            _LOOP_SEMAPHORES[loop] = asyncio.Semaphore(1)
        return _LOOP_SEMAPHORES[loop]


DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/?q={q}"

# Domain → tier (per Section 3.1 source hierarchy).
DOMAIN_TIER: dict[str, int] = {
    # -- Indian Regulatory and Exchange (Tier 1) --
    "nseindia.com": 1,
    "bseindia.com": 1,
    "sebi.gov.in": 1,
    "rbi.org.in": 1,
    "mca.gov.in": 1,
    # -- Indian IR / Company Filings (Tier 2) --
    "ir.": 2,
    "annualreports.com": 2,
    # -- Indian Research and Analytics (Tier 3-4) --
    "screener.in": 3,
    "trendlyne.com": 3,
    "tickertape.in": 3,
    "tijorifinance.com": 3,
    "moneycontrol.com": 4,
    "economictimes.indiatimes.com": 4,
    "livemint.com": 4,
    "ndtvprofit.com": 4,
    "businesstoday.in": 4,
    "thehindubusinessline.com": 4,
    "financialexpress.com": 4,
    "business-standard.com": 4,
    "valueresearchonline.com": 4,
    # -- Global Wire Services (Tier 6) --
    "reuters.com": 6,
    "ft.com": 6,
    "wsj.com": 6,
    "bloomberg.com": 6,
    # -- General Finance Portals (Tier 7) --
    "finance.yahoo.com": 7,
    "yahoo.com": 7,
    "macrotrends.net": 7,
    "seekingalpha.com": 3,
}

SOCIAL_DOMAINS = {
    "x.com", "twitter.com", "t.me",
    "telegram.me", "tiktok.com",
}


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ScrapedDoc:
    url: str
    final_url: str
    domain: str
    tier: int
    title: str
    excerpt: str
    text_len: int
    status: int
    blocked_reason: str | None = None
    via: str = "httpx"
    is_social: bool = False
    extra: dict[str, str] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# URL / domain helpers
# ──────────────────────────────────────────────────────────────────────────────

def _domain_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _tier_for(domain: str) -> int:
    if domain in SOCIAL_DOMAINS:
        return 8
    if domain in DOMAIN_TIER:
        return DOMAIN_TIER[domain]
    for prefix, tier in DOMAIN_TIER.items():
        if prefix.endswith(".") and domain.startswith(prefix):
            return tier
    if any(domain.endswith(s) for s in (".gov", ".edu")):
        return 1
    return 5


# ──────────────────────────────────────────────────────────────────────────────
# HTML extraction fallbacks — kept as defensive local parse chain
# ──────────────────────────────────────────────────────────────────────────────

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", re.I)
_WS_RE = re.compile(r"\s+")
_SENT_SPLIT = re.compile(r"(?<=[\.!\?])\s+")


def _alpha_ratio(s: str) -> float:
    if not s:
        return 0.0
    alpha = sum(1 for ch in s if ch.isalpha() or ch.isspace())
    return alpha / len(s)


def _narrative_excerpt(text: str, limit: int = 600) -> str:
    """Pick the first ~limit chars of *narrative* text from `text`.

    Exchange pages, filings, and press releases often prefix the visible body
    with navigation, schema links, or table-of-contents anchors. A plain
    `text[:limit]` returns that noise. This walks sentences and skips ones
    with a low alphabetic ratio or that are obviously metadata.
    """
    if not text:
        return ""
    keepers: list[str] = []
    total = 0
    for sent in _SENT_SPLIT.split(text):
        s = sent.strip()
        if len(s) < 30:
            continue
        if _alpha_ratio(s) < 0.55:
            continue
        # Skip lines dominated by URIs or schema references
        if s.count("/") >= 3 or "http" in s[:60]:
            continue
        keepers.append(s)
        total += len(s) + 1
        if total >= limit:
            break
    if not keepers:
        return text[:limit]
    joined = " ".join(keepers)
    return joined[:limit]


def _extract(html: str, *, prefer_narrative: bool = False) -> tuple[str, str]:
    """Local HTML → (title, text) extraction. Used as fallback when Crawl4AI
    is unavailable or a URL's browser session fails.

    Tables are converted to readable markdown grids by extract_layout_preserving_text
    (from table_parser.py) before the narrative filter runs.
    """
    try:
        title, text, _tables = extract_layout_preserving_text(html, prefer_narrative=prefer_narrative)
        text = normalize_financial_text_units(text)
        if prefer_narrative:
            text = _narrative_excerpt(text, limit=1200) or text
        return title, text
    except Exception:
        logger.debug("layout-preserving extraction failed; falling back to safe narrative parse", exc_info=True)
        title_match = _TITLE_RE.search(html)
        title = title_match.group(1).strip() if title_match else ""
        body = _TAG_RE.sub(" ", html)
        text = normalize_financial_text_units(_WS_RE.sub(" ", body).strip())
        if prefer_narrative:
            text = _narrative_excerpt(text, limit=1200) or text
        return title, text


_NARRATIVE_HOST_SUFFIXES = ("sebi.gov.in", "nseindia.com", "bseindia.com")


def _wants_narrative(domain: str) -> bool:
    return any(domain == s or domain.endswith("." + s) for s in _NARRATIVE_HOST_SUFFIXES)


async def fetch_and_parse(url: str, *, use_browser: bool = False) -> ScrapedDoc:
    """Defensive local fallback: httpx fetch → HTML extraction.
    Used when Crawl4AI is unavailable or errors out on a specific URL.
    """
    domain = _domain_of(url)
    if url.lower().split("?")[0].endswith(".pdf"):
        return ScrapedDoc(
            url=url,
            final_url=url,
            domain=domain,
            tier=_tier_for(domain),
            title="PDF Document Link",
            excerpt="[PDF Document: content extraction skipped to prevent hang]",
            text_len=0,
            status=200,
            via="skipped",
        )
    res: FetchResult = await fetch(url, use_browser=use_browser)
    domain = _domain_of(res.final_url or url)
    title, text = ("", "")
    if res.text:
        title, text = _extract(res.text, prefer_narrative=_wants_narrative(domain))
    return ScrapedDoc(
        url=url,
        final_url=res.final_url or url,
        domain=domain,
        tier=_tier_for(domain),
        title=title[:300],
        excerpt=text[:600],
        text_len=len(text),
        status=res.status,
        blocked_reason=res.blocked_reason,
        via=res.via,
        is_social=domain in SOCIAL_DOMAINS,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Search backends — URL discovery layer
# ──────────────────────────────────────────────────────────────────────────────

_DDG_LINK_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.I | re.S,
)


def _unwrap_ddg_redirector(href: str) -> str:
    """DDG result links arrive as `/l/?uddg=<encoded>` (relative) or full
    `https://duckduckgo.com/l/?uddg=<encoded>` (absolute). Both need to be
    unwrapped to the real destination URL."""
    from urllib.parse import parse_qs, unquote, urlparse as _urlparse

    if href.startswith("//"):
        href = "https:" + href
    parsed = _urlparse(href)
    if parsed.path.startswith("/l/") and (
        parsed.netloc == "" or parsed.netloc.endswith("duckduckgo.com")
    ):
        qs = parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    return href


async def _search_ddg(query: str, *, max_results: int) -> list[tuple[str, str]]:
    url = DUCKDUCKGO_HTML.format(q=quote_plus(query))
    res = None
    try:
        logger.info("Performing standard HTTP fetch for DDG search query: '%s'", query)
        res = await fetch(url, respect_robots=False, timeout_s=25.0)
    except Exception as exc:
        logger.warning("Standard HTTP fetch for DDG search query '%s' failed: %s. Falling back to browser-based fetch.", query, exc)
    
    # Check if standard fetch is blocked, empty, or failed
    should_fallback = False
    if res is None:
        should_fallback = True
    elif not res.text or res.status != 200:
        should_fallback = True
        logger.warning("DDG HTTP search returned status %s with empty/blocked content. Falling back to browser-based fetch.", res.status if res else None)
    
    if should_fallback:
        try:
            logger.info("Performing browser-based fetch (use_browser=True) for DDG search query: '%s'", query)
            res = await fetch(url, respect_robots=False, timeout_s=30.0, use_browser=True)
            if res and res.status == 200:
                logger.info("Browser-based fetch for DDG search query '%s' SUCCEEDED (status=%d, length=%d)", query, res.status, len(res.text or ""))
            else:
                logger.warning("Browser-based fetch for DDG search query '%s' FAILED/EMPTY (status=%s)", query, res.status if res else None)
        except Exception as exc:
            logger.error("Browser-based fetch for DDG search query '%s' ERROR: %s", query, exc)
            res = None

    if not res or not res.text:
        logger.warning("DDG search query '%s' yielded no content after both standard and browser attempts.", query)
        return []

    out: list[tuple[str, str]] = []
    for m in _DDG_LINK_RE.finditer(res.text):
        href = _unwrap_ddg_redirector(m.group("href"))
        title = _WS_RE.sub(" ", _TAG_RE.sub("", m.group("title"))).strip()
        out.append((href, title))
        if len(out) >= max_results:
            break

    # If parsing yields zero results, it might mean the HTML format changed or we got anti-bot/empty pages. Try browser.
    if not out and not should_fallback:
        logger.warning("DDG standard HTTP search returned 0 parsed results. Retrying with browser-based fetch (use_browser=True).")
        try:
            res = await fetch(url, respect_robots=False, timeout_s=30.0, use_browser=True)
            if res and res.text:
                for m in _DDG_LINK_RE.finditer(res.text):
                    href = _unwrap_ddg_redirector(m.group("href"))
                    title = _WS_RE.sub(" ", _TAG_RE.sub("", m.group("title"))).strip()
                    out.append((href, title))
                    if len(out) >= max_results:
                        break
        except Exception as exc:
            logger.error("Browser-based retry for DDG search query '%s' failed: %s", query, exc)

    logger.info("DDG search query '%s' returned %d results.", query, len(out))
    return out


# Bing HTML search — secondary backend for wider coverage. Bing returns
# a different result set from DDG (especially for finance / institutional
# sources) so combining both materially widens the net.
_BING_URL = "https://www.bing.com/search?q={q}&count=15&form=QBLH"
_BING_RESULT_RE = re.compile(
    r'<li[^>]*class="[^"]*\bb_algo\b[^"]*"[^>]*>.*?<h2[^>]*>\s*<a[^>]+href="(?P<href>https?://[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.S | re.I,
)


def _unwrap_bing_redirector(href: str) -> str:
    """Bing result links may arrive as `https://www.bing.com/ck/a?!...&u=a1<base64_encoded_url>&...`.
    We parse the query string, extract the 'u' parameter, strip the two-character prefix (e.g. 'a1'),
    and base64 decode it to retrieve the real destination URL."""
    from urllib.parse import parse_qs, urlparse as _urlparse
    import base64

    try:
        href = href.replace("&amp;", "&")
        parsed = _urlparse(href)
        if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
            qs = parse_qs(parsed.query)
            if "u" in qs and qs["u"]:
                u_val = qs["u"][0]
                if len(u_val) > 2:
                    encoded = u_val[2:]
                    missing_padding = len(encoded) % 4
                    if missing_padding:
                        encoded += "=" * (4 - missing_padding)
                    decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                    if decoded.startswith("http://") or decoded.startswith("https://"):
                        return decoded
    except Exception:
        pass
    return href


async def _search_bing(query: str, *, max_results: int) -> list[tuple[str, str]]:
    """Bing HTML SERP. Best-effort — returns [] if Bing blocks or
    rewrites the response (e.g. an interstitial)."""
    url = _BING_URL.format(q=quote_plus(query))
    res = None
    try:
        logger.info("Performing standard HTTP fetch for Bing search query: '%s'", query)
        res = await fetch(url, respect_robots=False, timeout_s=20.0)
    except Exception as exc:
        logger.warning("Standard HTTP fetch for Bing search query '%s' failed: %s. Falling back to browser-based fetch.", query, exc)

    should_fallback = False
    if res is None:
        should_fallback = True
    elif not res.text or res.status != 200:
        should_fallback = True
        logger.warning("Bing HTTP search returned status %s with empty/blocked content. Falling back to browser-based fetch.", res.status if res else None)

    if should_fallback:
        try:
            logger.info("Performing browser-based fetch (use_browser=True) for Bing search query: '%s'", query)
            res = await fetch(url, respect_robots=False, timeout_s=25.0, use_browser=True)
            if res and res.status == 200:
                logger.info("Browser-based fetch for Bing search query '%s' SUCCEEDED (status=%d, length=%d)", query, res.status, len(res.text or ""))
            else:
                logger.warning("Browser-based fetch for Bing search query '%s' FAILED/EMPTY (status=%s)", query, res.status if res else None)
        except Exception as exc:
            logger.error("Browser-based fetch for Bing search query '%s' ERROR: %s", query, exc)
            res = None

    if not res or not res.text:
        logger.warning("Bing search query '%s' yielded no content after both attempts.", query)
        return []

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _BING_RESULT_RE.finditer(res.text):
        href = m.group("href").strip()
        href = _unwrap_bing_redirector(href)
        title = _WS_RE.sub(" ", _TAG_RE.sub("", m.group("title"))).strip()
        if not href or href in seen or href.startswith("https://www.bing.com/"):
            continue
        seen.add(href)
        out.append((href, title))
        if len(out) >= max_results:
            break

    # If parsing yields zero results, retry with browser if we haven't already.
    if not out and not should_fallback:
        logger.warning("Bing standard HTTP search returned 0 parsed results. Retrying with browser-based fetch (use_browser=True).")
        try:
            res = await fetch(url, respect_robots=False, timeout_s=25.0, use_browser=True)
            if res and res.text:
                for m in _BING_RESULT_RE.finditer(res.text):
                    href = m.group("href").strip()
                    href = _unwrap_bing_redirector(href)
                    title = _WS_RE.sub(" ", _TAG_RE.sub("", m.group("title"))).strip()
                    if not href or href in seen or href.startswith("https://www.bing.com/"):
                        continue
                    seen.add(href)
                    out.append((href, title))
                    if len(out) >= max_results:
                        break
        except Exception as exc:
            logger.error("Browser-based retry for Bing search query '%s' failed: %s", query, exc)

    logger.info("Bing search query '%s' returned %d results.", query, len(out))
    return out


async def _search_tavily(query: str, *, max_results: int) -> list[tuple[str, str, str]]:
    """Search via Tavily API — returns (url, title, snippet) tuples.

    Returns empty list if TAVILY_API_KEY is not set or the package is unavailable.
    Tavily results include pre-extracted snippets so we skip the full browser
    crawl for these and construct ScrapedDocs directly from the API response.
    """
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=key)
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.search(
                query,
                max_results=max_results,
                search_depth="advanced",
                include_answer=False,
            ),
        )
        results = resp.get("results", []) if isinstance(resp, dict) else []
        return [(r.get("url", ""), r.get("title", ""), r.get("content", "")) for r in results if r.get("url")]
    except Exception as exc:
        logger.debug("Tavily search failed for %r: %s", query, exc)
        return []


def _tavily_to_scraped_doc(url: str, title: str, snippet: str) -> ScrapedDoc:
    domain = _domain_of(url)
    return ScrapedDoc(
        url=url,
        final_url=url,
        domain=domain,
        tier=_tier_for(domain),
        title=title[:300],
        excerpt=snippet[:600],
        text_len=len(snippet),
        status=200,
        blocked_reason=None,
        via="tavily",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Markdown / text helpers
# ──────────────────────────────────────────────────────────────────────────────

def _clean_markdown_excerpt(markdown: str, limit: int = 600) -> str:
    """Strip markdown formatting noise and return a plain-text excerpt."""
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", markdown or "")
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
    text = re.sub(r"[#>*_`~-]+", " ", text)
    text = _WS_RE.sub(" ", text).strip()
    return normalize_financial_text_units(text)[:limit]


def _normalize_india_query(query: str) -> str:
    """Anchor discovery terms to Indian statutory filings and exchanges."""
    q = query or ""
    replacements = [
        (r"\bIR\s+portal(?:s)?\b", "NSE BSE corporate announcements SEBI LODR"),
        (r"\bcompany\s+website\s+disclosures?\b", "annual report corporate announcements NSE BSE"),
        (r"\bearnings transcript\b", "earnings call concall quarterly results"),
    ]
    for pattern, repl in replacements:
        q = re.sub(pattern, repl, q, flags=re.IGNORECASE)
    if not re.search(r"\b(SEBI|LODR|NSE|BSE|Moneycontrol|Screener|Trendlyne)\b", q, re.IGNORECASE):
        q = f"{q} NSE BSE SEBI LODR"
    return _WS_RE.sub(" ", q).strip()


# ──────────────────────────────────────────────────────────────────────────────
# Crawl4AI — primary content extraction engine
# ──────────────────────────────────────────────────────────────────────────────

def _crawl4ai_to_scraped_doc(
    result: object,
    *,
    title_by_url: dict[str, str] | None = None,
) -> ScrapedDoc | None:
    """Convert a Crawl4AI CrawlResult into a ScrapedDoc.

    Prefers result.markdown.fit_markdown (boilerplate pruned via PruningContentFilter)
    and falls back to result.markdown.raw_markdown. HTML tables are already converted
    to pipe-delimited markdown grids by Crawl4AI's DefaultMarkdownGenerator — no
    additional table helper is required.
    """
    url = str(getattr(result, "url", "") or "")
    if not url:
        return None

    success: bool = bool(getattr(result, "success", False))
    status_code: int = int(getattr(result, "status_code", 0) or 0)
    error_message: str | None = getattr(result, "error_message", None) if not success else None

    # --- Markdown extraction ---
    md_obj = getattr(result, "markdown", None)
    fit_md = ""
    raw_md = ""
    if isinstance(md_obj, str):
        # Older Crawl4AI versions may return a plain string
        raw_md = md_obj
    elif md_obj is not None:
        fit_md = str(getattr(md_obj, "fit_markdown", "") or "")
        raw_md = str(getattr(md_obj, "raw_markdown", "") or "")

    markdown = fit_md or raw_md  # prefer pruned version

    # --- Title ---
    meta: dict = getattr(result, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    title = str(meta.get("title", "") or "")
    if not title and title_by_url:
        title = title_by_url.get(url, "")
    if not title:
        # Extract from first markdown heading ("# Company Name")
        first_line = (markdown or "").strip().split("\n", 1)[0]
        if first_line.startswith("#"):
            title = first_line.lstrip("#").strip()

    domain = _domain_of(url)
    excerpt = _clean_markdown_excerpt(markdown) or str(meta.get("description", ""))[:600]

    return ScrapedDoc(
        url=url,
        final_url=url,  # Crawl4AI follows redirects internally
        domain=domain,
        tier=_tier_for(domain),
        title=title[:300],
        excerpt=excerpt,
        text_len=len(markdown),
        status=status_code or (200 if success else 503),
        blocked_reason=str(error_message) if error_message else None,
        via="crawl4ai",
        is_social=domain in SOCIAL_DOMAINS,
    )


async def _crawl4ai_fetch_batch_inner(
    urls: list[str],
    *,
    query: str | None = None,
    title_by_url: dict[str, str] | None = None,
    timeout_s: float = 45.0,
) -> list[ScrapedDoc]:
    """Batch-crawl a list of URLs using Crawl4AI's headless Chromium engine.

    Configuration:
    - BrowserConfig: headless Chromium, non-verbose
    - ContentFilter: BM25ContentFilter if query is provided, else PruningContentFilter
    - DefaultMarkdownGenerator: converts HTML tables to markdown grids natively
    - CrawlerRunConfig: bypasses cache, excludes structural noise tags

    Falls back gracefully to fetch_and_parse (httpx) if:
    - crawl4ai is not installed (ImportError)
    - The browser session fails entirely (Exception)
    Per-URL failures degrade to fetch_and_parse without aborting the batch.
    """
    if not urls:
        return []

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        from crawl4ai.content_filter_strategy import PruningContentFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
        try:
            from crawl4ai.content_filter_strategy import BM25ContentFilter
        except ImportError:
            BM25ContentFilter = None
        try:
            from crawl4ai.async_dispatcher import SemaphoreDispatcher
        except ImportError:
            SemaphoreDispatcher = None
    except ImportError:
        logger.warning(
            "crawl4ai not installed — run 'pip install crawl4ai && crawl4ai-setup'. "
            "Falling back to httpx fetcher for %d URL(s).",
            len(urls),
        )
        fallback_tasks = [fetch_and_parse(u) for u in urls]
        return list(await asyncio.gather(*fallback_tasks, return_exceptions=False))

    sanitized_query = sanitize_search_query(query) if query else ""
    if BM25ContentFilter and sanitized_query:
        content_filter = BM25ContentFilter(
            user_query=sanitized_query,
        )
    else:
        # Fallback Content filter: dynamically removes low-density blocks (nav, footer, ads)
        content_filter = PruningContentFilter(
            threshold=0.45,
            threshold_type="dynamic",
            min_word_threshold=10,
        )
    # Native markdown generator — turns <table> → | col | col | grids automatically
    md_gen = DefaultMarkdownGenerator(content_filter=content_filter)

    browser_cfg = BrowserConfig(
        headless=True,
        browser_type="chromium",
        verbose=False,
        enable_stealth=True,
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=md_gen,
        word_count_threshold=10,
        excluded_tags=["nav", "footer", "form", "aside", "header"],
        page_timeout=int(timeout_s * 1000),
        magic=True,
        simulate_user=True,
        override_navigator=True,
        remove_consent_popups=True,
    )

    logger.info("Crawl4AI batch starting for %d URL(s)...", len(urls))
    docs: list[ScrapedDoc] = []
    try:
        async with _get_crawler_semaphore():
            async with AsyncWebCrawler(config=browser_cfg) as crawler:
                dispatcher = SemaphoreDispatcher(semaphore_count=8) if SemaphoreDispatcher else None
                if dispatcher:
                    results = await crawler.arun_many(urls=urls, config=run_cfg, dispatcher=dispatcher)
                else:
                    results = await crawler.arun_many(urls=urls, config=run_cfg)
                success_count = 0
                for result in results:
                    if getattr(result, "success", False):
                        doc = _crawl4ai_to_scraped_doc(result, title_by_url=title_by_url)
                        if doc is not None:
                            docs.append(doc)
                            success_count += 1
                            logger.info("  Crawl4AI successfully fetched: %s", doc.url)
                    else:
                        # Per-URL failure: degrade to httpx/Playwright for this specific URL
                        err_url = getattr(result, "url", "")
                        err_msg = getattr(result, "error_message", "unknown")
                        logger.info(
                            "  Crawl4AI failed for %r (%s) — falling back to httpx/Playwright...",
                            err_url, err_msg,
                        )
                        if err_url:
                            try:
                                logger.info("  Attempting standard HTTP fallback for failed Crawl4AI URL: %s", err_url)
                                fallback_doc = await fetch_and_parse(err_url)
                                if fallback_doc.status != 200 or fallback_doc.blocked_reason or fallback_doc.text_len < 200:
                                    logger.warning(
                                        "  Standard HTTP fallback for %r returned status %s (len=%d, blocked=%s). "
                                        "Activating browser-based Playwright fallback...",
                                        err_url, fallback_doc.status, fallback_doc.text_len, fallback_doc.blocked_reason
                                    )
                                    fallback_doc = await fetch_and_parse(err_url, use_browser=True)
                                # Patch in title from search if couldn't extract one
                                if not fallback_doc.title and title_by_url:
                                    fallback_doc.title = (title_by_url.get(err_url, ""))[:300]
                                docs.append(fallback_doc)
                                logger.info("    Fallback fetch completed for: %s (via=%s)", err_url, fallback_doc.via)
                            except Exception as fe:
                                logger.warning("    Fallback fetch also failed for %r: %s", err_url, fe)
                logger.info("Crawl4AI batch finished: %d/%d fetched successfully via browser.", success_count, len(urls))
    except Exception as exc:
        logger.warning(
            "Crawl4AI batch session failed: %s — falling back to httpx/Playwright for all %d URL(s)",
            exc, len(urls),
        )
        for url in urls:
            try:
                logger.info("  Attempting standard HTTP fallback for URL: %s", url)
                fallback_doc = await fetch_and_parse(url)
                if fallback_doc.status != 200 or fallback_doc.blocked_reason or fallback_doc.text_len < 200:
                    logger.warning(
                        "  Standard HTTP fallback for %r returned status %s (len=%d, blocked=%s). "
                        "Activating browser-based Playwright fallback...",
                        url, fallback_doc.status, fallback_doc.text_len, fallback_doc.blocked_reason
                    )
                    fallback_doc = await fetch_and_parse(url, use_browser=True)
                docs.append(fallback_doc)
                logger.info("    Fallback fetch completed for: %s (via=%s)", url, fallback_doc.via)
            except Exception as fe:
                logger.warning("    Fallback fetch failed for %r: %s", url, fe)

    return docs


def _run_in_proactor_thread(
    urls: list[str],
    query: str | None,
    title_by_url: dict[str, str] | None,
    timeout_s: float,
) -> list[ScrapedDoc]:
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(
            _crawl4ai_fetch_batch_inner(
                urls,
                query=query,
                title_by_url=title_by_url,
                timeout_s=timeout_s,
            )
        )
    finally:
        new_loop.close()


async def _crawl4ai_fetch_batch(
    urls: list[str],
    *,
    query: str | None = None,
    title_by_url: dict[str, str] | None = None,
    timeout_s: float = 45.0,
) -> list[ScrapedDoc]:
    if sys.platform == "win32":
        # On Windows, run the batch crawl in a separate thread with ProactorEventLoop
        # to avoid NotImplementedError/subprocess failures caused by SelectorEventLoop
        # under Uvicorn reload mode. We serialize batch crawls using a process-wide lock.
        def run_with_lock():
            with _CRAWLER_THREAD_LOCK:
                return _run_in_proactor_thread(urls, query, title_by_url, timeout_s)
        return await asyncio.to_thread(run_with_lock)
    else:
        # On non-Windows platforms, run directly in the current event loop.
        return await _crawl4ai_fetch_batch_inner(
            urls,
            query=query,
            title_by_url=title_by_url,
            timeout_s=timeout_s,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Domain deduplication helper
# ──────────────────────────────────────────────────────────────────────────────

def _dedup_by_domain(
    candidates: list[tuple[str, str]],
    *,
    max_per_domain: int = 2,
    max_total: int = 20,
) -> list[tuple[str, str]]:
    """Filter syndicated press-release noise from candidate URL lists.

    Allows at most `max_per_domain` URLs per registrable domain so that one
    BSE announcement mirrored across 10 news aggregators doesn't flood the
    batch. Preserves the interleaved ordering so both DDG and Bing results
    contribute proportionally.
    """
    domain_count: dict[str, int] = {}
    seen_url: set[str] = set()
    out: list[tuple[str, str]] = []
    for href, title in candidates:
        canonical = href.split("#", 1)[0]
        if canonical in seen_url:
            continue
        seen_url.add(canonical)
        dom = _domain_of(href)
        if domain_count.get(dom, 0) >= max_per_domain:
            continue
        domain_count[dom] = domain_count.get(dom, 0) + 1
        out.append((href, title))
        if len(out) >= max_total:
            break
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Public search API
# ──────────────────────────────────────────────────────────────────────────────

async def search_web(
    query: str,
    *,
    max_results: int = 5,
    preferred_domains: list[str] | None = None,
    entity: ResolvedEntity | None = None,
    query_cache: dict[str, list[ScrapedDoc]] | None = None,
) -> list[ScrapedDoc]:
    """Multi-backend search with Crawl4AI as the primary content extraction engine.

    Pipeline:
    1. Stage 1 Candidate Sourcing: Tavily + DDG + Bing execute concurrently,
       widening the pre-crawl pool to 40-60 links.
       Tavily results are used directly (no browser re-crawl — snippets are sufficient).
    2. Domain Dedup:   DDG + Bing URLs are interleaved and capped at 2 per domain
                       to suppress syndicated press-release noise.
    3. Crawl4AI Crawl: Headless Chromium batch-renders candidate URLs,
                       producing clean fit_markdown with tables as markdown grids.
    4. Rerank:         All docs scored by domain tier, BM25 relevance, and recency.

    Graceful degradation:
    - If Crawl4AI is not installed → httpx fetch_and_parse per URL
    - If a URL's browser session fails → httpx per-URL fallback
    - If Tavily key is absent → DDG + Bing fill the pool
    """
    query = _normalize_india_query(query)
    if query_cache is not None and query in query_cache:
        return query_cache[query]

    stage1_target = min(60, max(40, max_results * 12))
    crawl_budget = min(30, max(6, max_results * 2))

    # ── Phase 1: Fan-out search ───────────────────────────────────────────────
    tavily_task = asyncio.create_task(_search_tavily(query, max_results=stage1_target))
    ddg_task    = asyncio.create_task(_search_ddg(query, max_results=stage1_target))
    bing_task   = asyncio.create_task(_search_bing(query, max_results=stage1_target))

    tavily_raw, ddg_raw, bing_raw = await asyncio.gather(
        tavily_task, ddg_task, bing_task, return_exceptions=True
    )
    tavily_results: list[tuple[str, str, str]] = (
        [] if isinstance(tavily_raw, Exception) else (tavily_raw or [])
    )
    ddg_results:   list[tuple[str, str]] = (
        [] if isinstance(ddg_raw, Exception) else (ddg_raw or [])
    )
    bing_results:  list[tuple[str, str]] = (
        [] if isinstance(bing_raw, Exception) else (bing_raw or [])
    )

    logger.info(
        "Stage 1 candidate sourcing hits: Tavily=%d DDG=%d Bing=%d target=%d",
        len(tavily_results), len(ddg_results), len(bing_results), stage1_target
    )

    # Tavily docs: use snippets directly — pre-enriched, no browser session needed
    tavily_docs: list[ScrapedDoc] = []
    seen_urls: set[str] = set()
    for url, title, snippet in tavily_results:
        key = url.split("#", 1)[0]
        if key not in seen_urls:
            seen_urls.add(key)
            tavily_docs.append(_tavily_to_scraped_doc(url, title, snippet))

    # ── Phase 2: Build deduplicated candidate pool from DDG + Bing ───────────
    raw_candidates: list[tuple[str, str]] = []
    for pair in _zip_longest_pairs(ddg_results, bing_results):
        for href, title in pair:
            if not href:
                continue
            key = href.split("#", 1)[0]
            if key in seen_urls:
                continue
            seen_urls.add(key)
            raw_candidates.append((href, title))

    logger.info("Raw candidate URLs before domain deduplication: %d", len(raw_candidates))

    # Cap at 2 URLs per domain — eliminates syndicated press-release floods
    candidates = _dedup_by_domain(
        raw_candidates,
        max_per_domain=2,
        max_total=stage1_target,
    )

    logger.info("Stage 1 candidates after domain deduplication: %d", len(candidates))

    # Prioritise preferred domains by sorting them to the front
    if preferred_domains:
        pref_set = {d.lower().removeprefix("www.") for d in preferred_domains if d}
        candidates.sort(key=lambda hd: 0 if _domain_of(hd[0]) in pref_set else 1)

    # ── Phase 3: Crawl4AI batch — browser-render candidate URLs ──────────────
    # Filter out PDF links to prevent browser hangs and empty extraction crashes
    crawl_urls = [
        h for h, _ in candidates[:crawl_budget]
        if not h.lower().split("?")[0].endswith(".pdf")
    ]
    title_by_url = {h: t for h, t in candidates}

    logger.info(
        "Stage 2 Crawl4AI batch selected %d URL(s) from %d candidate(s)",
        len(crawl_urls), len(candidates),
    )

    crawl4ai_docs = await _crawl4ai_fetch_batch(
        crawl_urls,
        query=query,
        title_by_url=title_by_url,
        timeout_s=25.0,
    )

    # Patch in search title for docs where Crawl4AI couldn't extract one
    for doc in crawl4ai_docs:
        if not doc.title:
            doc.title = (title_by_url.get(doc.url, "") or title_by_url.get(doc.final_url, ""))[:300]

    # ── Phase 4: Merge and rerank ─────────────────────────────────────────────
    all_docs: list[ScrapedDoc] = [*tavily_docs, *crawl4ai_docs]
    logger.info("Merging %d Tavily doc(s) and %d Crawl4AI doc(s) for reranking.", len(tavily_docs), len(crawl4ai_docs))
    final_docs = rerank_docs(query, all_docs, entity=entity, preferred_domains=preferred_domains)
    final_docs = final_docs[:max_results]
    logger.info("Reranking completed. Slicing to top %d results.", len(final_docs))

    if query_cache is not None:
        query_cache[query] = final_docs
    return final_docs


def _zip_longest_pairs(a: list, b: list):
    n = max(len(a), len(b)) if (a or b) else 0
    for i in range(n):
        pa = a[i] if i < len(a) else (None, None)
        pb = b[i] if i < len(b) else (None, None)
        yield (pa, pb)


async def search_layered(
    target: str,
    *,
    on_doc: Callable[[ScrapedDoc], None] | None = None,
    on_query: Callable[[str, str, int], None] | None = None,
    per_query: int = 4,
    queries: list[str] | None = None,
    preferred_domains: list[str] | None = None,
    entity: ResolvedEntity | None = None,
    timeout_s: float | None = None,
) -> list[ScrapedDoc]:
    """Section 4.3 layered queries: authoritative / news / competitive / narrative.

    All queries fan out concurrently (~6× faster). Under timeout constraints,
    completed queries are returned, while lagging tasks are cancelled.
    """
    queries = queries or [
        f"{target} SEBI LODR Regulation 30 corporate announcements NSE BSE",
        f"{target} SEBI LODR Regulation 33 financial results NSE BSE",
        f"{target} Regulation 31 shareholding pattern promoter pledge NSE BSE",
        f"{target} NSE Emerge BSE SME board annual report financial results",
        f"{target} Moneycontrol Screener Trendlyne quarterly results concall",
        f"{target} competitors market share India sector",
    ]

    async def _one(q: str) -> tuple[str, list[ScrapedDoc]]:
        if on_query:
            on_query(q, "running", 0)
        try:
            docs = await search_web(
                q,
                max_results=per_query,
                preferred_domains=preferred_domains,
                entity=entity,
            )
            if on_query:
                on_query(q, "done", len(docs))
            return q, docs
        except asyncio.CancelledError:
            logger.warning("query %r cancelled by outer timeout", q)
            if on_query:
                on_query(q, "timeout", 0)
            raise
        except Exception as exc:
            logger.warning("query %r failed: %s", q, exc)
            if on_query:
                on_query(q, "error", 0)
            return q, []

    tasks = [asyncio.create_task(_one(q)) for q in queries]
    
    if timeout_s is not None:
        logger.info("Fanning out %d queries with timeout of %.1f seconds", len(queries), timeout_s)
        done, pending = await asyncio.wait(tasks, timeout=timeout_s)
        # Cancel any lagging tasks
        if pending:
            logger.warning("%d search queries timed out and will be cancelled.", len(pending))
            for task in pending:
                task.cancel()
            # Wait for cancellation to propagate (best effort)
            await asyncio.gather(*pending, return_exceptions=True)
    else:
        logger.info("Fanning out %d queries with no timeout limit", len(queries))
        done, pending = await asyncio.wait(tasks)

    results = []
    for task in done:
        try:
            res = task.result()
            if res:
                results.append(res)
        except Exception as e:
            logger.error("Failed to retrieve result from search task: %s", e)

    seen_urls: set[str] = set()
    all_docs: list[ScrapedDoc] = []
    for _q, docs in results:
        for d in docs:
            key = (d.final_url or d.url).split("#", 1)[0]
            if key in seen_urls:
                continue
            seen_urls.add(key)
            all_docs.append(d)
            if on_doc:
                on_doc(d)
    logger.info("search_layered completed. Gathered %d total unique docs.", len(all_docs))
    return all_docs
