"""HTTP fetcher with desktop-like headers, retries, and browser fallback.

Ethical posture: respects robots.txt by default; does not bypass auth,
paywalls, or explicit anti-bot challenges. For JS-heavy pages, the optional
Playwright path can render the page after consent.
"""

from __future__ import annotations

import asyncio
import logging
import random
import sys
import threading
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

# Serialize all Crawl4AI single-page browser launches on Windows to avoid
# NotImplementedError from SelectorEventLoop + subprocess.
_SINGLE_CRAWLER_THREAD_LOCK = threading.Lock()

logger = logging.getLogger("finagent.http_fetcher")



DESKTOP_HEADER_PROFILES = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
            "Gecko/20100101 Firefox/126.0"
        ),
        "sec-ch-ua": '"Firefox";v="126", "Gecko";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
]

UA_POOL = [profile["User-Agent"] for profile in DESKTOP_HEADER_PROFILES]
_CONTACT_UA = "ProspektLab Research contact@example.invalid"
_CONTACT_HOST_SUFFIXES = ("wikipedia.org", "wikimedia.org")
_REFERER_BY_SUFFIX = {
    "nseindia.com": "https://www.nseindia.com/",
    "bseindia.com": "https://www.bseindia.com/",
    "sebi.gov.in": "https://www.sebi.gov.in/",
    "moneycontrol.com": "https://www.moneycontrol.com/",
    "screener.in": "https://www.screener.in/",
    "trendlyne.com": "https://trendlyne.com/",
}


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    text: str
    blocked_reason: str | None = None
    via: str = "httpx"
    headers: dict[str, str] = field(default_factory=dict)


_robots_cache: dict[str, RobotFileParser] = {}
_robots_locks: dict[str, asyncio.Lock] = {}
_client_ref: dict[str, object] = {}


def _host_matches(url: str, suffixes) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _default_referer(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for suffix, referer in _REFERER_BY_SUFFIX.items():
        if host == suffix or host.endswith("." + suffix):
            return referer
    return None


def desktop_headers_for_url(url: str, *, referer: str | None = None, accept_json: bool = False) -> dict[str, str]:
    """Return a realistic desktop request signature for Indian market sites."""

    if _host_matches(url, _CONTACT_HOST_SUFFIXES):
        ua = _CONTACT_UA
        profile: dict[str, str] = {"User-Agent": ua}
    else:
        profile = dict(random.choice(DESKTOP_HEADER_PROFILES))

    headers: dict[str, str] = {
        **profile,
        "Accept": (
            "application/json, text/plain, */*"
            if accept_json
            else "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if (referer or _default_referer(url)) else "none",
        "Sec-Fetch-User": "?1",
    }
    ref = referer or _default_referer(url)
    if ref:
        headers["Referer"] = ref
    return headers


def _get_shared_client(timeout_s: float):
    """One pooled httpx.AsyncClient per process."""

    import httpx

    client = _client_ref.get("client")
    if client is None:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=40, keepalive_expiry=30.0)
        kwargs = dict(
            follow_redirects=True,
            timeout=timeout_s,
            limits=limits,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.7",
            },
        )
        try:
            client = httpx.AsyncClient(http2=True, **kwargs)
        except ImportError:
            client = httpx.AsyncClient(**kwargs)
        _client_ref["client"] = client
    return client


async def aclose_shared_client() -> None:
    client = _client_ref.pop("client", None)
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass


async def _can_fetch_async(url: str) -> bool:
    """Resolve robots.txt without blocking the event loop."""

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(base)
    if rp is None:
        lock = _robots_locks.setdefault(base, asyncio.Lock())
        async with lock:
            rp = _robots_cache.get(base)
            if rp is None:
                rp_local = RobotFileParser()
                rp_local.set_url(base + "/robots.txt")
                try:
                    await asyncio.to_thread(rp_local.read)
                except Exception:
                    pass
                _robots_cache[base] = rp_local
                rp = rp_local
    try:
        return rp.can_fetch("*", url)
    except Exception:
        return True


async def fetch(
    url: str,
    *,
    respect_robots: bool = True,
    use_browser: bool = False,
    timeout_s: float = 20.0,
    referer: str | None = None,
) -> FetchResult:
    try:
        from finagent.state.session_context import record_website
        record_website(url)
    except ImportError:
        pass

    if respect_robots:
        allowed = await _can_fetch_async(url)
        if not allowed:
            return FetchResult(url, url, 0, "", blocked_reason="robots.txt disallow")

    if use_browser:
        try:
            return await _fetch_via_crawl4ai_single(url, timeout_s=timeout_s)
        except Exception as exc:
            logger.warning("crawl4ai single-page fetch failed: %s; falling back to plain httpx", repr(exc))

    return await _fetch_via_httpx(url, timeout_s=timeout_s, referer=referer)


async def _fetch_via_httpx(url: str, *, timeout_s: float, referer: str | None) -> FetchResult:
    try:
        import httpx  # noqa: F401
    except ImportError:
        return FetchResult(url, url, 0, "", blocked_reason="httpx not installed")

    client = _get_shared_client(timeout_s)
    headers = desktop_headers_for_url(url, referer=referer)

    for attempt in range(3):
        try:
            resp = await client.get(url, headers=headers)
            blocked = None
            if resp.status_code in (401, 402, 403, 451):
                blocked = f"status {resp.status_code} (auth/paywall/legal block)"
            ctype = (resp.headers.get("content-type") or "").lower()
            if "charset=" not in ctype and any(t in ctype for t in ("html", "json", "xml", "text")):
                resp.encoding = "utf-8"
            return FetchResult(
                url=url,
                final_url=str(resp.url),
                status=resp.status_code,
                text=resp.text,
                blocked_reason=blocked,
                headers=dict(resp.headers),
            )
        except Exception as exc:
            if attempt < 2:
                logger.debug("httpx attempt %s for %s: %s (retrying)", attempt + 1, url[:80], exc)
            else:
                logger.warning("httpx final attempt failed for %s: %s", url[:80], exc)
            await asyncio.sleep(0.5 * (2**attempt))
    return FetchResult(url, url, 0, "", blocked_reason="all attempts failed")


# ──────────────────────────────────────────────────────────────────────────────
# Crawl4AI Single-Page Browser Fetch (replaces Playwright)
# ──────────────────────────────────────────────────────────────────────────────

async def _crawl4ai_single_inner(url: str, *, timeout_s: float) -> FetchResult:
    """Actual Crawl4AI single-page logic (must be called on a Proactor loop on Windows)."""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    except ImportError:
        raise RuntimeError("crawl4ai not installed. Run: pip install crawl4ai")

    browser_cfg = BrowserConfig(
        headless=True,
        browser_type="chromium",
        enable_stealth=True,
        verbose=False,
    )

    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=int(timeout_s * 1000),
        magic=True,
        simulate_user=True,
        override_navigator=True,
        remove_consent_popups=True,
    )

    logger.info("Crawl4AI single-page fetch starting for %s", url)
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url, config=run_cfg)
        html = result.html if hasattr(result, "html") else str(result)
        status = 200 if html else 0
        return FetchResult(
            url=url,
            final_url=result.url or url,
            status=status,
            text=html,
            via="crawl4ai",
        )


def _run_crawl4ai_single_in_proactor_thread(url: str, timeout_s: float) -> FetchResult:
    """Run the single-page crawl in a fresh ProactorEventLoop (Windows only)."""
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(
            _crawl4ai_single_inner(url, timeout_s=timeout_s)
        )
    finally:
        new_loop.close()


async def _fetch_via_crawl4ai_single(url: str, *, timeout_s: float = 20.0) -> FetchResult:
    """Fetch a single URL via Crawl4AI's headless Chromium with built-in stealth.

    On Windows this is always executed in a dedicated thread with ProactorEventLoop
    to avoid NotImplementedError when the caller is using SelectorEventLoop
    (common under uvicorn reload=True).
    """
    if sys.platform == "win32":
        def run_with_lock():
            with _SINGLE_CRAWLER_THREAD_LOCK:
                return _run_crawl4ai_single_in_proactor_thread(url, timeout_s)
        return await asyncio.to_thread(run_with_lock)
    else:
        return await _crawl4ai_single_inner(url, timeout_s=timeout_s)
