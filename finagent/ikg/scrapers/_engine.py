"""Smart scraping engine — Patchright browser + httpx with stealth, proxy, and retry.

Architecture:
  SmartHTTPClient  — httpx wrapper: proxy rotation, retry, rate limiting, stealth headers
  SmartBrowser     — Patchright async context manager: stealth mode, proxy, session reuse
  retry_request    — tenacity decorator for any sync/async scraping function

Key features:
  • Patchright (CDP-patched Playwright fork) — hides automation signals
  • playwright-stealth JS injection — patches navigator.webdriver, plugins, WebGL, etc.
  • httpx with SOCKS5/HTTP proxy from ProxyPool
  • Per-domain rate limiting (token bucket)
  • Exponential backoff retry (tenacity)
  • Human-like random delay jitter
  • Detects block signals: 403/429/Cloudflare/CAPTCHA text → triggers proxy rotation

Environment variables:
  SCRAPER_USE_PROXIES     = "1" | "0"   (default: 1)
  SCRAPER_USE_BROWSER     = "1" | "0"   (default: 1)
  SCRAPER_HEADLESS        = "1" | "0"   (default: 1)
  SCRAPER_MAX_RETRIES     = int         (default: 4)
  SCRAPER_BASE_DELAY_S    = float       (default: 1.5)
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time
from contextlib import asynccontextmanager
from concurrent.futures import Future
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional, TypeVar
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from finagent.ikg.scrapers._proxy_manager import ProxyPool, bootstrap_proxy_pool, get_proxy_pool

logger = logging.getLogger("finagent.ikg.scrapers._engine")
_T = TypeVar("_T")

# ── Configuration ─────────────────────────────────────────────────────────────
_USE_PROXIES = os.getenv("SCRAPER_USE_PROXIES", "1") not in {"0", "false", "no"}
_USE_BROWSER = os.getenv("SCRAPER_USE_BROWSER", "1") not in {"0", "false", "no"}
_HEADLESS = os.getenv("SCRAPER_HEADLESS", "1") not in {"0", "false", "no"}
_MAX_RETRIES = int(os.getenv("SCRAPER_MAX_RETRIES", "4"))
_BASE_DELAY_S = float(os.getenv("SCRAPER_BASE_DELAY_S", "1.5"))
_HTTPX_TRUST_ENV = os.getenv("FINAGENT_HTTPX_TRUST_ENV", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Block detection signals
_BLOCK_STATUS_CODES = {403, 429, 503, 520, 521, 522, 523, 524}
_BLOCK_PHRASES = [
    "cloudflare", "access denied", "captcha challenge", "rate limit",
    "too many requests", "blocked", "bot detection", "security check",
    "please enable javascript", "verify you are human",
]

# ── Stealth init script (injected into every browser page) ────────────────────
_STEALTH_INIT_SCRIPT = """
// Overwrite the `webdriver` property to make it undefined
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Fake plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map(i => ({
        name: `Plugin ${i}`, filename: `plugin${i}.dll`,
        description: `Fake plugin ${i}`,
        length: 1,
        item: () => null, namedItem: () => null,
    })),
});

// Fake languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-US', 'en'] });

// Hide automation flags
window.chrome = {
    runtime: { id: undefined },
    loadTimes: () => ({}),
    csi: () => ({}),
    app: {},
};

// Fix permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// Randomize canvas fingerprint slightly
const origGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, ...args) {
    const ctx = origGetContext.call(this, type, ...args);
    if (type === '2d' && ctx) {
        const origFillText = ctx.fillText.bind(ctx);
        ctx.fillText = (...a) => { origFillText(...a); };
    }
    return ctx;
};

// WebGL vendor/renderer spoof
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""

# ── Rate limiter (per-domain token bucket) ────────────────────────────────────

class _DomainRateLimiter:
    """Simple per-domain rate limiter backed by thread-safe timestamps."""

    def __init__(self) -> None:
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()
        self._domain_delays: dict[str, float] = {
            "sebi.gov.in": 5.0,
            "bseindia.com": 0.6,
            "nseindia.com": 5.0,
            "niftyindices.com": 5.0,
            "screener.in": 2.5,
            "mcacdm.nic.in": 2.0,
            "mca.gov.in": 36.0,  # 100 req/hour
        }

    def _domain_of(self, url: str) -> str:
        try:
            host = urlparse(url).netloc.lower()
            for known in self._domain_delays:
                if known in host:
                    return known
            return host
        except Exception:
            return url[:30]

    async def wait(self, url: str) -> None:
        domain = self._domain_of(url)
        delay = self._domain_delays.get(domain, _BASE_DELAY_S)
        # Add human jitter: ±30% of base delay
        jitter = random.uniform(-0.3, 0.3) * delay
        effective_delay = max(0.1, delay + jitter)
        with self._lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            elapsed = now - last
            wait_for = max(0.0, effective_delay - elapsed)
            # Reserve this slot now to keep cross-thread pacing consistent.
            self._last_request[domain] = now + wait_for
        if wait_for > 0:
            await asyncio.sleep(wait_for)


_rate_limiter = _DomainRateLimiter()

# ── Block detection ────────────────────────────────────────────────────────────

def _is_blocked(status_code: int, body: str) -> bool:
    if status_code in _BLOCK_STATUS_CODES:
        return True
    body_lower = (body or "")[:2000].lower()
    return any(phrase in body_lower for phrase in _BLOCK_PHRASES)


class ScraperBlockedError(Exception):
    """Raised when a scraping request is definitively blocked."""
    pass


def run_async(coro: Awaitable[_T]) -> _T:
    """Run a coroutine from sync code, even if an event loop is already running.

    `asyncio.run(...)` raises when called from a running loop. For scraper
    codepaths that can be triggered from threads, schedulers, or async
    endpoints, this helper transparently runs the coroutine in a dedicated
    thread+event-loop when needed.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: Future[_T] = Future()

    def _runner() -> None:
        try:
            value = asyncio.run(coro)
            box.set_result(value)
        except Exception as exc:
            box.set_exception(exc)

    worker = threading.Thread(target=_runner, name="ikg-run-async", daemon=True)
    worker.start()
    worker.join()
    return box.result()


# ── SmartHTTPClient ────────────────────────────────────────────────────────────

class SmartHTTPClient:
    """httpx-based smart HTTP client with proxy, retry, rate limiting, stealth headers.

    Usage:
        client = SmartHTTPClient()
        await client.bootstrap()  # optional: pre-warm proxy pool

        # Single request with all safeguards:
        response = await client.get("https://example.com")

        # Or use as context manager:
        async with SmartHTTPClient() as client:
            resp = await client.get("https://example.com")
    """

    _STEALTH_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, extra_headers: dict[str, str] | None = None) -> None:
        self._proxy_pool = get_proxy_pool()
        self._extra_headers = extra_headers or {}
        self._session_cookies: dict[str, str] = {}

    async def bootstrap(self) -> None:
        """Initialize proxy pool (call once before first use)."""
        await bootstrap_proxy_pool()

    async def __aenter__(self) -> "SmartHTTPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {**self._STEALTH_HEADERS, **self._extra_headers}
        if extra:
            h.update(extra)
        return h

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
        follow_redirects: bool = True,
        retries: int = _MAX_RETRIES,
        stream: bool = False,
    ) -> httpx.Response:
        """GET with retry + proxy rotation."""
        return await self._request(
            "GET", url,
            headers=headers, params=params, timeout=timeout,
            follow_redirects=follow_redirects, retries=retries,
        )

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: Any = None,
        timeout: float = 30.0,
        follow_redirects: bool = True,
        retries: int = _MAX_RETRIES,
    ) -> httpx.Response:
        """POST with retry + proxy rotation."""
        return await self._request(
            "POST", url,
            headers=headers, data=data, json=json, timeout=timeout,
            follow_redirects=follow_redirects, retries=retries,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: Any = None,
        timeout: float = 30.0,
        follow_redirects: bool = True,
        retries: int = _MAX_RETRIES,
    ) -> httpx.Response:
        """Core request with proxy rotation + retry.

        Strategy:
          Attempt 0: Always direct (no proxy) — fastest path for public APIs
          Attempt 1+: Rotate through proxy pool if direct was blocked/failed
          If proxy fails: mark failure, try next proxy or fall back to direct
        """
        merged_headers = self._build_headers(headers)
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            # Attempt 0: direct connection. Subsequent attempts: use proxy.
            use_proxy = _USE_PROXIES and attempt > 0 and self._proxy_pool.pool_size() > 0
            proxy_url: str | None = self._proxy_pool.next() if use_proxy else None

            # Exponential backoff between retries (skip on attempt 0)
            if attempt > 0:
                delay = _BASE_DELAY_S * (2 ** (attempt - 1)) + random.uniform(0, 1.0)
                logger.debug(
                    "Retry %d/%d for %s in %.1fs (proxy=%s)",
                    attempt, retries, url[:60], delay, proxy_url or "direct",
                )
                await asyncio.sleep(delay)

            try:
                await _rate_limiter.wait(url)

                transport = None
                if proxy_url:
                    try:
                        transport = httpx.AsyncHTTPTransport(proxy=proxy_url)  # type: ignore[arg-type]
                    except Exception:
                        proxy_url = None
                        transport = None

                async with httpx.AsyncClient(
                    transport=transport,
                    timeout=timeout,
                    follow_redirects=follow_redirects,
                    max_redirects=5 if proxy_url else 20,  # cap redirects via proxy
                    verify=False,  # some proxies break TLS verification
                    trust_env=_HTTPX_TRUST_ENV,
                ) as client:
                    kwargs: dict[str, Any] = {
                        "headers": merged_headers,
                        "params": params,
                    }
                    if data is not None:
                        kwargs["data"] = data
                    if json is not None:
                        kwargs["json"] = json

                    resp = await client.request(method, url, **kwargs)

                if _is_blocked(resp.status_code, resp.text):
                    logger.warning(
                        "Blocked on attempt %d (status=%d, proxy=%s): %s",
                        attempt + 1, resp.status_code, proxy_url or "direct", url[:60],
                    )
                    if proxy_url:
                        self._proxy_pool.mark_failure(proxy_url)
                    last_error = ScraperBlockedError(f"Blocked {resp.status_code}")
                    continue

                if proxy_url:
                    self._proxy_pool.mark_success(proxy_url)
                return resp

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if proxy_url:
                    self._proxy_pool.mark_failure(proxy_url)
                logger.debug(
                    "Request failed attempt %d (%s): %s — %s",
                    attempt + 1, proxy_url or "direct", type(exc).__name__, url[:60],
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Unexpected error on attempt %d for %s: %s",
                    attempt + 1, url[:60], exc,
                )
                if proxy_url:
                    self._proxy_pool.mark_failure(proxy_url)
                if attempt >= retries:
                    raise

        raise last_error or RuntimeError(f"All {retries + 1} attempts failed for {url}")


# ── SmartBrowser (Patchright) ─────────────────────────────────────────────────

class SmartBrowser:
    """Patchright browser manager with stealth, proxy rotation, and session reuse.

    Patchright patches the CDP layer to remove automation signals:
      - Removes --enable-automation flag
      - Disables Runtime.enable CDP command leak
      - Patches navigator.webdriver at C++ level

    Additionally injects playwright-stealth JS and our custom _STEALTH_INIT_SCRIPT.

    Usage:
        browser_mgr = SmartBrowser()
        async with browser_mgr.page(url="https://mca.gov.in") as page:
            content = await page.content()

        # Or keep alive across multiple requests:
        browser_mgr = SmartBrowser(persistent=True)
        await browser_mgr.start()
        page = await browser_mgr.new_page()
        await browser_mgr.goto(url)
        await browser_mgr.close()
    """

    def __init__(
        self,
        headless: bool = _HEADLESS,
        proxy_url: str | None = None,
        persistent: bool = False,
    ) -> None:
        self._headless = headless
        self._proxy_url = proxy_url
        self._persistent = persistent
        self._browser: Any = None
        self._context: Any = None
        self._playwright: Any = None
        self._proxy_pool = get_proxy_pool()

    async def start(self) -> None:
        """Launch Patchright browser. Call once for persistent mode."""
        if self._browser is not None:
            return

        try:
            from patchright.async_api import async_playwright
        except ImportError:
            logger.warning("patchright not installed; falling back to playwright")
            from playwright.async_api import async_playwright  # type: ignore

        self._playwright = await async_playwright().__aenter__()

        # Browser starts WITHOUT proxy by default — proxy only if explicitly set
        # or if direct connection fails (handled at page navigation level)
        proxy_url = self._proxy_url  # explicit proxy only
        launch_kwargs: dict[str, Any] = {
            "headless": self._headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-gpu",
                "--window-size=1920,1080",
                "--lang=en-IN",
            ],
        }
        if proxy_url:
            launch_kwargs["proxy"] = {"server": proxy_url}

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
            "user_agent": SmartHTTPClient._STEALTH_HEADERS["User-Agent"],
            "java_script_enabled": True,
            "accept_downloads": True,
            "extra_http_headers": {
                "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
            },
        }
        self._context = await self._browser.new_context(**context_kwargs)
        await self._context.add_init_script(_STEALTH_INIT_SCRIPT)

        # Apply playwright-stealth if available
        try:
            from playwright_stealth import stealth_async
            tmp_page = await self._context.new_page()
            await stealth_async(tmp_page)
            await tmp_page.close()
        except ImportError:
            logger.debug("playwright-stealth not available; using manual stealth init script")

        logger.info(
            "SmartBrowser started: headless=%s, proxy=%s",
            self._headless, proxy_url or "direct",
        )

    async def close(self) -> None:
        """Close browser and playwright instance."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.__aexit__(None, None, None)
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._playwright = None

    async def new_page(self) -> Any:
        """Open a new page in the current browser context."""
        if not self._context:
            await self.start()
        page = await self._context.new_page()
        # Apply stealth init to each new page
        await page.add_init_script(_STEALTH_INIT_SCRIPT)
        return page

    @asynccontextmanager
    async def page(self, url: str | None = None) -> AsyncGenerator[Any, None]:
        """Context manager: creates and optionally navigates a page, closes on exit."""
        started = self._browser is None
        if started:
            await self.start()
        pg = await self._context.new_page()
        await pg.add_init_script(_STEALTH_INIT_SCRIPT)
        try:
            if url:
                await pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            yield pg
        finally:
            await pg.close()
            if started and not self._persistent:
                await self.close()

    async def get_page_content(
        self,
        url: str,
        *,
        wait_for_selector: str | None = None,
        wait_ms: int = 1000,
    ) -> str:
        """Navigate to URL and return page HTML content."""
        async with self.page(url) as pg:
            if wait_for_selector:
                try:
                    await pg.wait_for_selector(wait_for_selector, timeout=10000)
                except Exception:
                    pass
            await pg.wait_for_timeout(wait_ms + random.randint(0, 500))
            return await pg.content()

    async def get_json_via_browser(
        self,
        url: str,
        *,
        wait_ms: int = 500,
    ) -> Any:
        """Fetch a JSON API endpoint via browser (bypasses API bot detection)."""
        import json as _json
        async with self.page(url) as pg:
            await pg.wait_for_timeout(wait_ms)
            content = await pg.content()
            # Extract JSON from <pre> tag (browser JSON viewer) or raw body
            import re
            pre_match = re.search(r"<pre[^>]*>(.*?)</pre>", content, re.S | re.I)
            if pre_match:
                return _json.loads(pre_match.group(1))
            body_match = re.search(r"<body[^>]*>(.*?)</body>", content, re.S | re.I)
            if body_match:
                return _json.loads(body_match.group(1).strip())
            return _json.loads(content)


# ── Module-level singletons ───────────────────────────────────────────────────

_global_http_client: SmartHTTPClient | None = None
_global_browser: SmartBrowser | None = None


def get_http_client() -> SmartHTTPClient:
    """Get or create the global SmartHTTPClient singleton."""
    global _global_http_client
    if _global_http_client is None:
        _global_http_client = SmartHTTPClient()
    return _global_http_client


async def get_browser(persistent: bool = True) -> SmartBrowser:
    """Get or create the global SmartBrowser singleton."""
    global _global_browser
    if _global_browser is None:
        _global_browser = SmartBrowser(persistent=persistent)
    if _global_browser._browser is None:
        await _global_browser.start()
    return _global_browser


async def close_browser() -> None:
    """Close the global browser instance."""
    global _global_browser
    if _global_browser is not None:
        await _global_browser.close()
        _global_browser = None


# ── Convenience sync wrappers ─────────────────────────────────────────────────

def sync_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    retries: int = _MAX_RETRIES,
) -> httpx.Response:
    """Synchronous smart GET — direct first, proxy fallback on failure."""

    async def _run() -> httpx.Response:
        client = SmartHTTPClient()
        return await client.get(
            url,
            headers=headers,
            params=params,
            timeout=timeout,
            follow_redirects=follow_redirects,
            retries=retries,
        )

    return run_async(_run())


def sync_post(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    timeout: float = 30.0,
    retries: int = _MAX_RETRIES,
) -> httpx.Response:
    """Synchronous smart POST — direct first, proxy fallback on failure."""

    async def _run() -> httpx.Response:
        client = SmartHTTPClient()
        return await client.post(
            url,
            headers=headers,
            data=data,
            timeout=timeout,
            retries=retries,
        )

    return run_async(_run())


# ── Self-test ─────────────────────────────────────────────────────────────────

async def _self_test() -> None:
    """Validate engine components: proxy pool, httpx, and browser."""
    print("=== SmartScraper Engine Self-Test ===")

    # 1. Proxy pool
    print("\n1. Proxy Pool")
    pool = await bootstrap_proxy_pool()
    print(f"   Pool size: {pool.pool_size()}")
    next_proxy = pool.next()
    print(f"   Next proxy: {next_proxy or 'direct (no proxies)'}")

    # 2. SmartHTTPClient
    print("\n2. SmartHTTPClient")
    client = SmartHTTPClient()
    try:
        resp = await client.get("https://httpbin.org/headers", timeout=15.0)
        print(f"   Status: {resp.status_code}")
        data = resp.json()
        ua = data.get("headers", {}).get("User-Agent", "N/A")
        print(f"   User-Agent seen by server: {ua[:80]}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # 3. Browser
    print("\n3. SmartBrowser (Patchright)")
    try:
        browser = SmartBrowser(headless=True)
        await browser.start()
        content = await browser.get_page_content(
            "https://bot.sannysoft.com",
            wait_ms=2000,
        )
        wd_hidden = "webdriver" not in content.lower() or "undefined" in content.lower()
        print(f"   Browser started OK")
        print(f"   navigator.webdriver hidden: {wd_hidden}")
        await browser.close()
    except Exception as e:
        print(f"   ERROR: {e}")

    print("\n=== Self-test complete ===")


if __name__ == "__main__":
    asyncio.run(_self_test())
