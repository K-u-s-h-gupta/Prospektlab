"""HTTP fetcher with desktop-like headers, retries, and browser fallback.

Ethical posture: respects robots.txt by default; does not bypass auth,
paywalls, or explicit anti-bot challenges. For JS-heavy pages, the optional
Playwright path can render the page after consent.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

# Serialize all Crawl4AI single-page browser launches on Windows to avoid
# NotImplementedError from SelectorEventLoop + subprocess.
_SINGLE_CRAWLER_THREAD_LOCK = threading.Lock()

logger = logging.getLogger("finagent.http_fetcher")


def _ensure_crawl4ai_base_dir() -> str:
    base = (
        os.getenv("CRAWL4_AI_BASE_DIRECTORY")
        or os.getenv("CRAWL4AI_BASE_DIRECTORY")
        or os.path.join(tempfile.gettempdir(), "prospektlab-crawl4ai")
    )
    os.environ["CRAWL4_AI_BASE_DIRECTORY"] = base
    os.environ["CRAWL4AI_BASE_DIRECTORY"] = base
    os.makedirs(base, exist_ok=True)
    os.makedirs(os.path.join(base, "cache"), exist_ok=True)
    return base



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


def _get_shared_client(timeout_s: float, *, force_new: bool = False):
    """One pooled httpx.AsyncClient per process, bound to the current running event loop.

    `force_new=True` discards any cached client and rebuilds — used after a proxy
    is evicted so the new client binds a fresh egress proxy. The proxy this client
    was built with is recorded in `_client_ref['proxy']` so the caller can prune it.
    """

    import httpx

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    client = _client_ref.get("client")
    cached_loop = _client_ref.get("loop")

    if force_new or client is None or cached_loop is not loop or (client.is_closed if hasattr(client, 'is_closed') else False):
        if client is not None:
            try:
                # Discard/close the old client asynchronously
                if loop and loop.is_running():
                    loop.create_task(client.aclose())
            except Exception:
                pass
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
            from finagent.tools.web.proxy_pool import get_proxy_for_httpx
            _proxy = get_proxy_for_httpx()
        except Exception:
            _proxy = None
        if _proxy:
            kwargs["proxy"] = _proxy
        try:
            client = httpx.AsyncClient(http2=True, **kwargs)
        except (ImportError, TypeError):
            # http2 extra missing, or this httpx wants `proxies=` not `proxy=`.
            if "proxy" in kwargs:
                kwargs["proxies"] = kwargs.pop("proxy")
            client = httpx.AsyncClient(**kwargs)
        _client_ref["client"] = client
        _client_ref["loop"] = loop
        _client_ref["proxy"] = _proxy
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


import ipaddress


# SSRF blocklist: private IP ranges, metadata endpoints, and non-http(s) schemes
_BLOCKED_SCHEMES = {"file", "ftp", "ftps", "gopher", "dict", "ldap", "ldaps", "tftp", "sftp", "ssh", "smtp", "imap", "pop3"}
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]", "169.254.169.254"}
_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::1/128"),
]


def _is_url_safe(url: str) -> tuple[bool, str]:
    """Return (is_safe, reason) after checking for SSRF vectors."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return False, f"blocked scheme: {scheme}"
    hostname = (parsed.hostname or "").lower()
    if hostname in _BLOCKED_HOSTS:
        return False, f"blocked host: {hostname}"
    # Resolve IP if hostname is an IP literal
    try:
        addr = ipaddress.ip_address(hostname)
        for net in _BLOCKED_IP_NETWORKS:
            if addr in net:
                return False, f"blocked IP: {hostname}"
    except ValueError:
        pass
    return True, ""


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

    safe, reason = _is_url_safe(url)
    if not safe:
        logger.warning("SSRF block triggered for URL %s: %s", url[:80], reason)
        return FetchResult(url, url, 0, "", blocked_reason=f"ssrf: {reason}")

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

    # Proxy-pool plumbing — all no-ops when proxying is OFF (egress proxy is None,
    # so the eviction branch below never fires and behaviour is byte-identical).
    try:
        from finagent.tools.web import proxy_pool
        _proxy_enabled = proxy_pool.proxy_enabled()
        _explicit_hop = (os.getenv("PROSPEKT_PROXY_URL", "") or "").strip()
    except Exception:
        proxy_pool = None  # type: ignore[assignment]
        _proxy_enabled = False
        _explicit_hop = ""

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
            # When proxying is on and the failure is proxy-level, evict the dead
            # egress proxy and rebuild the shared client on a fresh one before
            # the next attempt.
            if _proxy_enabled and proxy_pool is not None and attempt < 2:
                used = _client_ref.get("proxy")
                if used and proxy_pool._is_proxy_failure(exc):
                    if not _explicit_hop:
                        proxy_pool.mark_proxy_dead(used)
                    client = _get_shared_client(timeout_s, force_new=True)
            await asyncio.sleep(0.5 * (2**attempt))
    return FetchResult(url, url, 0, "", blocked_reason="all attempts failed")


# ──────────────────────────────────────────────────────────────────────────────
# Crawl4AI Single-Page Browser Fetch (replaces Playwright)
# ──────────────────────────────────────────────────────────────────────────────

_C4_PROXY_SENTINEL = object()


async def _crawl4ai_single_inner(url: str, *, timeout_s: float, proxy=_C4_PROXY_SENTINEL) -> FetchResult:
    """Actual Crawl4AI single-page logic (must be called on a Proactor loop on Windows).

    `proxy` defaults to the sentinel → resolve from the pool (legacy behaviour).
    Pass an explicit value (str or None) to pin the egress for proxy-rotation
    retries driven by `_fetch_via_crawl4ai_single`."""
    _ensure_crawl4ai_base_dir()
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    except ImportError:
        raise RuntimeError("crawl4ai not installed. Run: pip install crawl4ai")

    _bcfg_kwargs: dict = dict(
        headless=True,
        browser_type="chromium",
        enable_stealth=True,
        verbose=False,
    )
    if proxy is _C4_PROXY_SENTINEL:
        try:
            from finagent.tools.web.proxy_pool import get_proxy_for_httpx
            _c4_proxy = get_proxy_for_httpx()
        except Exception:
            _c4_proxy = None
    else:
        _c4_proxy = proxy
    if _c4_proxy:
        try:
            browser_cfg = BrowserConfig(proxy=_c4_proxy, **_bcfg_kwargs)
        except TypeError:
            # Older/newer crawl4ai expects a structured proxy_config instead.
            browser_cfg = BrowserConfig(proxy_config={"server": _c4_proxy}, **_bcfg_kwargs)
    else:
        browser_cfg = BrowserConfig(**_bcfg_kwargs)

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


def _run_crawl4ai_single_in_proactor_thread(url: str, timeout_s: float, proxy=_C4_PROXY_SENTINEL) -> FetchResult:
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
            _crawl4ai_single_inner(url, timeout_s=timeout_s, proxy=proxy)
        )
    finally:
        new_loop.close()


def _is_browser_proxy_failure(exc: BaseException) -> bool:
    """True when a crawl4ai/browser error looks like a dead egress proxy."""
    s = str(exc).lower()
    return any(m in s for m in (
        "err_proxy", "err_tunnel", "proxy", "err_connection",
        "err_timed_out", "timeout", "net::err", "tunnel connection failed",
    ))


async def _fetch_via_crawl4ai_single(url: str, *, timeout_s: float = 20.0) -> FetchResult:
    """Fetch a single URL via Crawl4AI's headless Chromium with built-in stealth.

    On Windows this is always executed in a dedicated thread with ProactorEventLoop
    to avoid NotImplementedError when the caller is using SelectorEventLoop
    (common under uvicorn reload=True).

    When proxying is ON, a browser-level (proxy) failure evicts the dead egress
    proxy and retries on a fresh one, bounded to 3. When OFF, this is a single
    attempt with the sentinel proxy — byte-identical to the pre-retry path.
    """
    async def _one(proxy):
        if sys.platform == "win32":
            def run_with_lock():
                with _SINGLE_CRAWLER_THREAD_LOCK:
                    return _run_crawl4ai_single_in_proactor_thread(url, timeout_s, proxy)
            return await asyncio.to_thread(run_with_lock)
        return await _crawl4ai_single_inner(url, timeout_s=timeout_s, proxy=proxy)

    try:
        from finagent.tools.web import proxy_pool
        _enabled = proxy_pool.proxy_enabled()
    except Exception:
        proxy_pool = None  # type: ignore[assignment]
        _enabled = False

    if not _enabled:
        # Legacy path: sentinel → inner resolves a (None) proxy itself.
        return await _one(_C4_PROXY_SENTINEL)

    explicit = (os.getenv("PROSPEKT_PROXY_URL", "") or "").strip()
    last_exc: BaseException | None = None
    for attempt in range(3):
        proxy = proxy_pool.get_proxy_for_httpx()
        try:
            return await _one(proxy)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_browser_proxy_failure(exc):
                raise
            if proxy and not explicit:
                proxy_pool.mark_proxy_dead(proxy)
            logger.debug("crawl4ai attempt %d via %s failed: %s", attempt + 1, proxy or "direct", exc)
    if last_exc is not None:
        raise last_exc
    return await _one(_C4_PROXY_SENTINEL)
