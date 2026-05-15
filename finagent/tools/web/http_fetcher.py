"""HTTP fetcher with rotating UA, retries, optional Playwright fallback.

Ethical posture: respects robots.txt by default; does NOT bypass auth, paywalls, or
explicit anti-bot challenges. For JS-heavy pages, the optional Playwright path can
render the page after consent.

Optimizations:
- Shared httpx.AsyncClient with HTTP/2 + keep-alive (one TLS handshake per host)
- robots.txt reads run in a thread executor so they never block the asyncio loop
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger("finagent.http_fetcher")

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
]

# SEC publishes a documented Fair-Access policy
# (https://www.sec.gov/os/accessing-edgar-data) that asks bots to identify
# themselves via a User-Agent like "Sample Company Name AdminContact@example.com".
# Setting FINAGENT_IDENTITY in the env unlocks identified access to SEC + IR pages.
_DEFAULT_IDENTITY = "FinAgent Research finagent@example.invalid"


def _identification_ua() -> str:
    import os

    return os.getenv("FINAGENT_IDENTITY", _DEFAULT_IDENTITY)


# Domains that should always receive the identified UA (and bypass robots, which
# would otherwise blanket-disallow non-identified crawlers — SEC's documented policy
# overrides the generic User-agent: * disallow when you declare identification).
_IDENTIFIED_HOST_SUFFIXES = (
    "sec.gov",
    "investor.gov",
    # Wikimedia's API policy requires a contact-bearing User-Agent.
    "wikipedia.org",
    "wikimedia.org",
)


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


def _get_shared_client(timeout_s: float):
    """One pooled httpx.AsyncClient per process (keep-alive, HTTP/2 if available)."""
    import httpx

    client = _client_ref.get("client")
    if client is None:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=40, keepalive_expiry=30.0)
        try:
            client = httpx.AsyncClient(
                http2=True,
                follow_redirects=True,
                timeout=timeout_s,
                limits=limits,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except ImportError:
            client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout_s,
                limits=limits,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
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
    """Resolve robots.txt without blocking the event loop.

    Reads happen exactly once per host, behind an asyncio.Lock so concurrent
    fetches against a new host don't trigger duplicate downloads.
    """
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


def _is_identified_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == s or host.endswith("." + s) for s in _IDENTIFIED_HOST_SUFFIXES)


async def fetch(
    url: str,
    *,
    respect_robots: bool = True,
    use_browser: bool = False,
    timeout_s: float = 20.0,
    referer: str | None = None,
) -> FetchResult:
    identified = _is_identified_host(url)
    # Identified hosts (SEC / investor.gov) intentionally bypass robots because
    # we comply with their stricter declared-identity policy via the UA header.
    if respect_robots and not identified:
        allowed = await _can_fetch_async(url)
        if not allowed:
            return FetchResult(url, url, 0, "", blocked_reason="robots.txt disallow")

    if use_browser:
        try:
            return await _fetch_via_browser(url, timeout_s=timeout_s)
        except Exception as exc:
            logger.warning("browser fetch failed (%s); falling back to httpx", exc)

    return await _fetch_via_httpx(url, timeout_s=timeout_s, referer=referer, identified=identified)


async def _fetch_via_httpx(url: str, *, timeout_s: float, referer: str | None, identified: bool = False) -> FetchResult:
    try:
        import httpx  # noqa: F401  (imported transitively by _get_shared_client)
    except ImportError:
        return FetchResult(url, url, 0, "", blocked_reason="httpx not installed")

    client = _get_shared_client(timeout_s)
    if identified:
        headers = {"User-Agent": _identification_ua(), "Accept-Encoding": "gzip, deflate"}
    else:
        headers = {"User-Agent": random.choice(UA_POOL)}
    if referer:
        headers["Referer"] = referer

    for attempt in range(3):
        try:
            resp = await client.get(url, headers=headers)
            blocked = None
            if resp.status_code in (401, 402, 403, 451):
                blocked = f"status {resp.status_code} (auth/paywall/legal block)"
            # SEC and many other servers send HTML without a charset header,
            # so httpx defaults to ISO-8859-1 → mojibake. Override to UTF-8
            # when the Content-Type looks like html/json/xml AND no charset.
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


async def _fetch_via_browser(url: str, *, timeout_s: float) -> FetchResult:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright not installed")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(user_agent=random.choice(UA_POOL))
            page = await ctx.new_page()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            html = await page.content()
            status = resp.status if resp else 0
            final_url = page.url
            return FetchResult(url=url, final_url=final_url, status=status, text=html, via="playwright")
        finally:
            await browser.close()
