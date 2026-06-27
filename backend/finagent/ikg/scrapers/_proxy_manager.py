"""Free proxy pool manager — sourced from well-maintained public GitHub lists.

Sources (updated hourly/daily by community bots):
  - monosans/proxy-list  — HTTP + SOCKS5, anonymity-filtered
  - TheSpeedX/PROXY-List — HTTP
  - ShiftyTR/Proxy-List  — HTTP
  - clarketm/proxy-list  — HTTP with status

Features:
  - Fetches from multiple sources, deduplicates
  - Background validity check (httpbin.org/ip, 5s timeout)
  - Round-robin rotation with failure-count tracking
  - Auto-removes dead proxies; auto-refreshes every 30 min
  - Falls back to direct connection when pool is exhausted
  - Thread-safe via asyncio.Lock

Usage:
    pool = ProxyPool()
    await pool.bootstrap()
    proxy_url = pool.next()      # e.g. "http://1.2.3.4:8080"
    pool.mark_failure("http://1.2.3.4:8080")
    pool.mark_success("http://1.2.3.4:8080")
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections import defaultdict
from typing import Optional

import httpx

logger = logging.getLogger("finagent.ikg.scrapers._proxy_manager")

# ─── Public proxy list sources ────────────────────────────────────────────────
_PROXY_SOURCES: list[tuple[str, str]] = [
    # (url, protocol)
    # vakhov/fresh-proxy-list — refreshed ~hourly via GitHub Actions; largest HTTP pool.
    ("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/https.txt", "http"),
    ("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "http"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", "http"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt", "socks5"),
    ("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-status.txt", "http"),
]

# Validation endpoint — fast, reliable, returns JSON with {"origin": "x.x.x.x"}
_VALIDATION_URL = "https://httpbin.org/ip"
_VALIDATION_TIMEOUT = 6.0
_MAX_FAILURES = 3         # remove proxy after this many consecutive failures
_REFRESH_INTERVAL_S = 1800  # refresh source lists every 30 min
_MIN_POOL_SIZE = 5          # trigger refresh when pool drops below this
# Free-proxy liveness is ~5-10%, so a 30-sample yields only ~2 live. Validate a
# much larger sample (concurrently, sem=20) so the usable pool is tens not single
# digits. Override via FINAGENT_PROXY_VALIDATE_SAMPLE.
_VALIDATE_SAMPLE_SIZE = int(os.getenv("FINAGENT_PROXY_VALIDATE_SAMPLE", "250"))


class ProxyPool:
    """Thread-safe rotating free proxy pool with automatic refresh and validation."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled and os.getenv("SCRAPER_USE_PROXIES", "1") not in {"0", "false", "no"}
        self._pool: list[str] = []          # validated proxy URLs ("http://host:port")
        self._failures: dict[str, int] = defaultdict(int)
        self._successes: dict[str, int] = defaultdict(int)
        self._index: int = 0
        self._lock = asyncio.Lock()
        self._last_refresh: float = 0.0
        self._bootstrapped: bool = False
        self._refresh_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── Public interface ──────────────────────────────────────────────────────

    async def bootstrap(self) -> None:
        """Initial fetch + validation. Call once at startup."""
        if self._bootstrapped or not self._enabled:
            return
        await self._refresh()
        self._bootstrapped = True
        # Launch background refresh task
        try:
            loop = asyncio.get_running_loop()
            self._refresh_task = loop.create_task(self._background_refresh())
        except RuntimeError:
            pass

    def next(self) -> str | None:
        """Return next proxy URL in rotation, or None for direct connection."""
        if not self._enabled or not self._pool:
            return None
        proxy = self._pool[self._index % len(self._pool)]
        self._index += 1
        return proxy

    def mark_failure(self, proxy_url: str) -> None:
        """Record a failure; remove proxy if it exceeds max failure threshold."""
        if not proxy_url:
            return
        self._failures[proxy_url] += 1
        if self._failures[proxy_url] >= _MAX_FAILURES:
            self._remove(proxy_url)
            logger.debug("Proxy removed after %d failures: %s", _MAX_FAILURES, proxy_url)

    def mark_success(self, proxy_url: str) -> None:
        """Record a successful request through this proxy."""
        if proxy_url:
            self._failures[proxy_url] = 0  # reset failure counter on success
            self._successes[proxy_url] += 1

    def pool_size(self) -> int:
        return len(self._pool)

    def is_enabled(self) -> bool:
        return self._enabled

    def get_httpx_proxies(self, proxy_url: str | None) -> dict[str, str] | None:
        """Convert proxy URL to httpx-compatible proxies dict."""
        if not proxy_url:
            return None
        return {"http://": proxy_url, "https://": proxy_url}

    # ── Internal ─────────────────────────────────────────────────────────────

    def _remove(self, proxy_url: str) -> None:
        try:
            self._pool.remove(proxy_url)
        except ValueError:
            pass

    async def _fetch_raw_proxies(self) -> list[str]:
        """Download and parse proxy lists from all sources."""
        raw: list[str] = []
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, trust_env=False) as client:
            for url, protocol in _PROXY_SOURCES:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    for line in resp.text.splitlines():
                        line = line.strip()
                        # clarketm list has format "host:port OK" or "host:port DEAD"
                        if " " in line:
                            parts = line.split()
                            if len(parts) >= 2 and parts[1].upper() == "DEAD":
                                continue
                            line = parts[0]
                        if ":" not in line:
                            continue
                        host_port = line.strip()
                        if not host_port or len(host_port) > 50:
                            continue
                        if protocol == "socks5":
                            raw.append(f"socks5://{host_port}")
                        else:
                            raw.append(f"http://{host_port}")
                    logger.debug("Fetched %d proxies from %s", len(raw), url[:60])
                except Exception as exc:
                    logger.debug("Proxy source fetch failed %s: %s", url[:60], exc)
        # Deduplicate
        return list(set(raw))

    async def _validate_proxy(self, proxy_url: str, client: httpx.AsyncClient) -> bool:
        """Test a proxy against httpbin. Returns True if proxy works."""
        try:
            proxies = {"http://": proxy_url, "https://": proxy_url}
            resp = await client.get(
                _VALIDATION_URL,
                timeout=_VALIDATION_TIMEOUT,
                extensions={"proxy": proxy_url.encode()},
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def _validate_batch(self, candidates: list[str]) -> list[str]:
        """Validate a batch of proxies concurrently (max 20 at a time)."""
        valid: list[str] = []
        semaphore = asyncio.Semaphore(20)

        async def _check(proxy: str) -> None:
            async with semaphore:
                try:
                    transport = httpx.AsyncHTTPTransport(proxy=proxy)  # type: ignore[arg-type]
                    async with httpx.AsyncClient(
                        transport=transport,
                        timeout=_VALIDATION_TIMEOUT,
                        follow_redirects=False,
                        trust_env=False,
                    ) as client:
                        resp = await client.get(_VALIDATION_URL)
                        if resp.status_code == 200:
                            valid.append(proxy)
                except Exception:
                    pass

        await asyncio.gather(*[_check(p) for p in candidates], return_exceptions=True)
        return valid

    async def _refresh(self) -> None:
        """Fetch new proxies, validate a sample, update pool."""
        logger.info("Refreshing proxy pool...")
        async with self._lock:
            raw = await self._fetch_raw_proxies()
            logger.info("Fetched %d raw proxies from all sources", len(raw))

            if not raw:
                logger.warning("No proxies fetched; will use direct connection")
                self._last_refresh = time.monotonic()
                return

            # Shuffle and sample for validation
            random.shuffle(raw)
            sample = raw[:_VALIDATE_SAMPLE_SIZE]
            validated = await self._validate_batch(sample)
            logger.info(
                "Validated %d/%d proxies from sample of %d total",
                len(validated), len(sample), len(raw),
            )

            if validated:
                # Add validated to pool, also keep surviving existing ones
                existing_valid = [p for p in self._pool if self._failures.get(p, 0) < _MAX_FAILURES]
                combined = list(set(validated + existing_valid))
                random.shuffle(combined)
                self._pool = combined
                self._index = 0
            elif not self._pool:
                # Fall back to unvalidated proxies as last resort
                self._pool = raw[:50]
                logger.warning("No proxies validated; adding %d unvalidated as fallback", len(self._pool))

            self._last_refresh = time.monotonic()
            logger.info("Proxy pool size: %d", len(self._pool))

    async def _background_refresh(self) -> None:
        """Periodic background refresh task."""
        while True:
            await asyncio.sleep(_REFRESH_INTERVAL_S)
            try:
                await self._refresh()
            except Exception as exc:
                logger.warning("Background proxy refresh failed: %s", exc)
            # Also refresh if pool is critically small
            while len(self._pool) < _MIN_POOL_SIZE:
                await asyncio.sleep(60)
                try:
                    await self._refresh()
                except Exception:
                    break


# ── Module-level singleton ────────────────────────────────────────────────────
_global_pool: ProxyPool | None = None


def get_proxy_pool() -> ProxyPool:
    """Get or create the global proxy pool singleton."""
    global _global_pool
    if _global_pool is None:
        _global_pool = ProxyPool()
    return _global_pool


async def bootstrap_proxy_pool() -> ProxyPool:
    """Initialize and return the global proxy pool."""
    pool = get_proxy_pool()
    await pool.bootstrap()
    return pool
