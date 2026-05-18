"""High-level scraping: search → fetch top results → parse → citation set."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import quote_plus, urlparse

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.retrieval.reranker import rerank_docs
from finagent.tools.web.http_fetcher import FetchResult, fetch

logger = logging.getLogger("finagent.scraper")

DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/?q={q}"

# Domain → tier (per Section 3.1 source hierarchy).
DOMAIN_TIER: dict[str, int] = {
    # -- Indian Regulatory and Exchange (Tier 1) --
    "nseindia.com": 1,
    "bseindia.com": 1,
    "sebi.gov.in": 1,
    "rbi.org.in": 1,
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
    # -- US / Global Regulatory (kept for cross-listed) --
    "sec.gov": 1,
    "investor.gov": 1,
    "edgar.sec.gov": 1,
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

SOCIAL_DOMAINS = {"x.com", "twitter.com", "reddit.com", "t.me", "telegram.me", "stocktwits.com", "tiktok.com"}


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


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", re.I)
_WS_RE = re.compile(r"\s+")
_SENT_SPLIT = re.compile(r"(?<=[\.\!\?])\s+")


def _alpha_ratio(s: str) -> float:
    if not s:
        return 0.0
    alpha = sum(1 for ch in s if ch.isalpha() or ch.isspace())
    return alpha / len(s)


def _narrative_excerpt(text: str, limit: int = 600) -> str:
    """Pick the first ~limit chars of *narrative* text from `text`.

    SEC 10-K HTML, IR pages, and many press releases prefix the visible body
    with header gunk (XBRL URIs, fund-IDs, table-of-contents anchors, share
    counts). A plain `text[:limit]` returns that gunk. This walks sentences
    and skips ones with a low alphabetic ratio or that are obviously metadata.
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
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = (soup.title.string or "").strip() if soup.title else ""
        text = soup.get_text(" ", strip=True)
        if prefer_narrative:
            text = _narrative_excerpt(text, limit=1200) or text
        return title, text
    except Exception:
        title_match = _TITLE_RE.search(html)
        title = title_match.group(1).strip() if title_match else ""
        body = _TAG_RE.sub(" ", html)
        text = _WS_RE.sub(" ", body).strip()
        if prefer_narrative:
            text = _narrative_excerpt(text, limit=1200) or text
        return title, text


_NARRATIVE_HOST_SUFFIXES = ("sec.gov", "investor.gov")


def _wants_narrative(domain: str) -> bool:
    return any(domain == s or domain.endswith("." + s) for s in _NARRATIVE_HOST_SUFFIXES)


async def fetch_and_parse(url: str, *, use_browser: bool = False) -> ScrapedDoc:
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


_DDG_LINK_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.I | re.S)


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
    try:
        res = await fetch(url, respect_robots=False, timeout_s=25.0)
    except Exception as exc:
        logger.warning("ddg search fetch failed: %s", exc)
        try:
            from finagent.events import BUS
            BUS.emit("global", "agent_task", task=f"ddg search {query}", status="error", error=str(exc))
        except Exception:
            pass
        return []
    if not res.text:
        return []
    out: list[tuple[str, str]] = []
    for m in _DDG_LINK_RE.finditer(res.text):
        href = _unwrap_ddg_redirector(m.group("href"))
        title = _WS_RE.sub(" ", _TAG_RE.sub("", m.group("title"))).strip()
        out.append((href, title))
        if len(out) >= max_results:
            break
    return out


# Bing HTML search — secondary backend for wider coverage. Bing returns
# a different result set from DDG (especially for finance / institutional
# sources) so combining both materially widens the net.
_BING_URL = "https://www.bing.com/search?q={q}&count=15&form=QBLH"
_BING_RESULT_RE = re.compile(
    r'<li[^>]*class="[^"]*\bb_algo\b[^"]*"[^>]*>.*?<h2>\s*<a[^>]+href="(?P<href>https?://[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.S | re.I,
)


async def _search_bing(query: str, *, max_results: int) -> list[tuple[str, str]]:
    """Bing HTML SERP. Best-effort — returns [] if Bing blocks or
    rewrites the response (e.g. an interstitial)."""
    url = _BING_URL.format(q=quote_plus(query))
    try:
        res = await fetch(url, respect_robots=False, timeout_s=20.0)
    except Exception as exc:
        logger.warning("bing search fetch failed: %s", exc)
        try:
            from finagent.events import BUS
            BUS.emit("global", "agent_task", task=f"bing search {query}", status="error", error=str(exc))
        except Exception:
            pass
        return []
    if not res.text or res.status != 200:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _BING_RESULT_RE.finditer(res.text):
        href = m.group("href").strip()
        title = _WS_RE.sub(" ", _TAG_RE.sub("", m.group("title"))).strip()
        if not href or href in seen or href.startswith("https://www.bing.com/"):
            continue
        seen.add(href)
        out.append((href, title))
        if len(out) >= max_results:
            break
    return out


async def _search_tavily(query: str, *, max_results: int) -> list[tuple[str, str, str]]:
    """Search via Tavily API — returns (url, title, snippet) tuples.

    Returns empty list if TAVILY_API_KEY is not set or the package is unavailable.
    Tavily results include pre-extracted snippets so we skip the full HTML fetch
    for these and construct ScrapedDocs directly from the API response.
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


async def search_web(
    query: str,
    *,
    max_results: int = 5,
    preferred_domains: list[str] | None = None,
    entity: ResolvedEntity | None = None,
    query_cache: dict[str, list[ScrapedDoc]] | None = None,
) -> list[ScrapedDoc]:
    """Multi-backend search: Tavily (primary) + DuckDuckGo + Bing (fallback),
    dedup, then fetch+parse the top N. Falls back gracefully when one backend fails.
    Tavily provides pre-extracted content so full HTML fetching is skipped for
    those results, making search significantly faster when the key is configured.
    """
    if query_cache is not None and query in query_cache:
        return query_cache[query]

    raw_target = max(max_results * 3, 12)

    # Run all three backends concurrently
    tavily_task = asyncio.create_task(_search_tavily(query, max_results=raw_target))
    ddg_task    = asyncio.create_task(_search_ddg(query, max_results=raw_target))
    bing_task   = asyncio.create_task(_search_bing(query, max_results=raw_target))
    tavily_raw, ddg_raw, bing_raw = await asyncio.gather(
        tavily_task, ddg_task, bing_task, return_exceptions=True
    )
    tavily_results = [] if isinstance(tavily_raw, Exception) else tavily_raw
    ddg_results    = [] if isinstance(ddg_raw, Exception) else ddg_raw
    bing_results   = [] if isinstance(bing_raw, Exception) else bing_raw

    # Build merged list — Tavily results go first (pre-ranked, higher quality)
    merged: list[tuple[str, str]] = []
    tavily_snippets: dict[str, str] = {}
    seen: set[str] = set()

    for url, title, snippet in tavily_results:
        key = url.split("#", 1)[0]
        if key not in seen:
            seen.add(key)
            merged.append((url, title))
            tavily_snippets[url] = snippet
        if len(merged) >= max_results:
            break

    # Fill remaining slots from DDG + Bing interleaved
    for pair in _zip_longest_pairs(ddg_results, bing_results):
        for href, title in pair:
            if not href:
                continue
            key = href.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            merged.append((href, title))
        if len(merged) >= max_results:
            break

    if not merged:
        return []

    title_by_url = {h: t for h, t in merged}

    async def _enriched_fetch(target_url: str) -> ScrapedDoc:
        # If Tavily already returned a snippet, skip full HTML fetch
        if target_url in tavily_snippets:
            return _tavily_to_scraped_doc(
                target_url, title_by_url.get(target_url, ""), tavily_snippets[target_url]
            )
        doc = await fetch_and_parse(target_url)
        fallback_title = title_by_url.get(target_url, "")
        if (not doc.title or doc.status >= 400 or doc.blocked_reason) and fallback_title:
            doc.title = fallback_title[:300]
            if not doc.excerpt:
                doc.excerpt = fallback_title[:600]
        return doc

    tasks: list[Awaitable[ScrapedDoc]] = [_enriched_fetch(h) for h, _ in merged]
    docs: list[ScrapedDoc] = []
    for fut in asyncio.as_completed(tasks):
        docs.append(await fut)
    final_docs = rerank_docs(query, docs, entity=entity, preferred_domains=preferred_domains)
    if query_cache is not None:
        query_cache[query] = final_docs
    return final_docs


def _zip_longest_pairs(a: list, b: list):
    n = max(len(a), len(b))
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
) -> list[ScrapedDoc]:
    """Section 4.3 layered queries: authoritative / news / competitive / social.

    All four queries fan out concurrently (~4x faster), and results are deduplicated
    by final URL so the user-facing source stream never repeats.
    """
    queries = queries or [
        f"{target} SEC filing 10-K",
        f"{target} investor relations",
        f"{target} earnings transcript",
        f"{target} competitors market share",
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
        except Exception as exc:
            logger.warning("query %r failed: %s", q, exc)
            if on_query:
                on_query(q, "error", 0)
            return q, []

    results = await asyncio.gather(*(_one(q) for q in queries))

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
    return all_docs
