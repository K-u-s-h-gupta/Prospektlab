"""Free public proxy pool + rotation glue.

Sources free proxies from TheSpeedX/PROXY-List and exposes them two ways:

  1. Direct Python rotation — `get_proxy_for_httpx()` returns one live proxy
     URL per call (random), for callers that set the proxy themselves.
  2. mubeng rotating front-end — `write_mubeng_file()` writes the live list in
     mubeng's `protocol://ip:port` format; a local `mubeng` process then load-
     balances across them and our fetchers point at ONE local address
     (`PROSPEKT_PROXY_URL`, e.g. http://127.0.0.1:8089).

Everything is OFF unless `PROSPEKT_PROXY_ENABLED` is truthy, so existing
behaviour is unchanged until a proxy layer is explicitly turned on.

NOTE: free public proxies are unreliable, slow, and mostly datacenter IPs.
Health-checking is mandatory; expect a low live ratio. This is a zero-cost
starting layer — swap `SOURCES` for a paid residential endpoint for real
NSE/BSE WAF bypass.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger("finagent.tools.web.proxy_pool")

# ── In-memory live-list cache ─────────────────────────────────────────────────
# Re-reading live.txt on every get_random_proxy() call is wasteful under load and
# races with mark_proxy_dead rewrites. We cache the parsed list plus the file's
# mtime; the cache is invalidated when mark_proxy_dead mutates it or when the
# on-disk mtime changes (e.g. the rotator daemon rewrote live.txt). All reads and
# writes to the cache + the file go through this module-level lock so a rewrite
# is never interleaved with a read.
_pool_lock = threading.Lock()
_pool_cache: dict[str, object] = {"proxies": None, "mtime": None}

# ── Sources (raw ip:port per line, no scheme; we prepend the scheme) ──────────
# iplocate is validated every ~30 min ("working, tested") → far higher live
# ratio than TheSpeedX, which is larger but mostly stale. iplocate's `https`
# list = HTTP proxies that allow CONNECT to :443 (what NSE/BSE need), so it is
# tagged "http" for httpx addressing.
_SPEEDX = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master"
_IPLOCATE = "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols"
_VAKHOV = "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master"
# (raw_url, scheme) — order matters: curated first so they win on dedupe.
SOURCES: list[tuple[str, str]] = [
    (f"{_VAKHOV}/https.txt", "http"),     # CONNECT-capable — best for NSE
    (f"{_VAKHOV}/http.txt", "http"),
    (f"{_IPLOCATE}/https.txt", "http"),
    (f"{_IPLOCATE}/http.txt", "http"),
    (f"{_IPLOCATE}/socks5.txt", "socks5"),
    (f"{_SPEEDX}/http.txt", "http"),
    (f"{_SPEEDX}/socks5.txt", "socks5"),
]

# Health-check probes — first is HTTPS (CONNECT tunnel, what NSE/BSE need), the
# second a fast HTTP echo. Kept fast/light so dead proxies fail quickly.
_CHECK_URLS = ("https://api.ipify.org?format=text", "http://ip-api.com/line/?fields=query")


def _proxy_dir() -> Path:
    env = os.getenv("PROSPEKT_PROXY_DIR")
    if env:
        base = Path(env)
    else:
        # backend/finagent/tools/web/proxy_pool.py -> repo root is parents[4]
        base = Path(__file__).resolve().parents[4] / ".proxy"
    base.mkdir(parents=True, exist_ok=True)
    return base


def raw_file_path() -> Path:
    return _proxy_dir() / "proxies_raw.txt"


def live_file_path() -> Path:
    return _proxy_dir() / "live.txt"


def proxy_enabled() -> bool:
    return os.getenv("PROSPEKT_PROXY_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


# ── Acquisition ───────────────────────────────────────────────────────────────

async def refresh_raw_lists(*, protocols: tuple[str, ...] = ("http", "socks4", "socks5")) -> int:
    """Download proxy lists, normalise to `scheme://ip:port`, dedupe, persist."""
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for url, scheme in SOURCES:
            if scheme not in protocols:
                continue
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("proxy source %s (%s) failed: %s", url, scheme, exc)
                continue
            for line in resp.text.splitlines():
                hostport = line.strip()
                if not hostport or ":" not in hostport:
                    continue
                # Strip any scheme already present, re-tag with ours.
                hostport = hostport.split("://", 1)[-1]
                seen.add(f"{scheme}://{hostport}")
    path = raw_file_path()
    path.write_text("\n".join(sorted(seen)), encoding="utf-8")
    logger.info("proxy_pool: wrote %d raw proxies -> %s", len(seen), path)
    return len(seen)


# ── Health check ──────────────────────────────────────────────────────────────
# Thread-based on purpose. The async/httpx version storms the Windows Proactor
# loop when thousands of dead-host connects pile up — handle-cleanup deadlocks
# for HOURS. `requests` in a bounded ThreadPoolExecutor with a per-call socket
# timeout AND an overall as_completed deadline can never hang: a stuck worker is
# abandoned when the wall clock expires.

def _check_one_sync(proxy_url: str, timeout: float) -> bool:
    """Live ONLY if it tunnels HTTPS via CONNECT — that's what NSE/BSE need.

    HTTP-only proxies are useless for the exchanges, so they don't count as
    live even though they'd pass a plain-HTTP probe.
    """
    import requests  # lazy: keep module import cheap
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        resp = requests.get("https://api.ipify.org?format=text", proxies=proxies, timeout=timeout)
        return resp.status_code == 200 and bool(resp.text.strip())
    except Exception:
        return False


def health_check_sync(
    *,
    max_check: int = 400,
    workers: int = 50,
    timeout: float = 6.0,
    wall_seconds: float = 120.0,
    protocols: tuple[str, ...] = ("http",),
) -> int:
    """Probe a sample of raw proxies in threads; write live ones to `live.txt`.

    Bounded by `wall_seconds` — returns whatever passed before the deadline,
    never hangs. Defaults to http only (free socks rarely tunnel HTTPS and are
    the worst hang offenders).
    """
    import concurrent.futures as cf

    raw = raw_file_path()
    if not raw.exists():
        return 0
    candidates = [
        p for p in raw.read_text(encoding="utf-8").splitlines()
        if p.strip() and p.split("://", 1)[0] in protocols
    ]
    random.shuffle(candidates)
    candidates = candidates[:max_check]

    live: list[str] = []
    started = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_check_one_sync, p, timeout): p for p in candidates}
        try:
            for fut in cf.as_completed(futs, timeout=wall_seconds):
                try:
                    if fut.result():
                        live.append(futs[fut])
                except Exception:
                    pass
        except cf.TimeoutError:
            logger.warning("proxy_pool: health check hit %.0fs wall — partial result", wall_seconds)

    live_file_path().write_text("\n".join(live), encoding="utf-8")
    logger.info(
        "proxy_pool: health check %d/%d live in %.1fs -> %s",
        len(live), len(candidates), time.perf_counter() - started, live_file_path(),
    )
    return len(live)


async def health_check(
    *,
    max_check: int = 400,
    concurrency: int = 60,
    timeout: float = 6.0,
    protocols: tuple[str, ...] = ("http",),
) -> int:
    """Async-friendly wrapper — runs the thread-based checker off the loop."""
    return await asyncio.to_thread(
        health_check_sync,
        max_check=max_check,
        workers=concurrency,
        timeout=timeout,
        protocols=protocols,
    )


# ── Consumption ───────────────────────────────────────────────────────────────

def _read_live_from_disk() -> list[str]:
    path = live_file_path()
    if not path.exists():
        return []
    return [p for p in path.read_text(encoding="utf-8").splitlines() if p.strip()]


def _cached_live_proxies() -> list[str]:
    """Return the live list from the in-memory cache, refreshing it from disk
    only when live.txt's mtime changed (or the cache is cold). Lock-held."""
    path = live_file_path()
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None
    cached = _pool_cache.get("proxies")
    if cached is None or _pool_cache.get("mtime") != mtime:
        cached = _read_live_from_disk()
        _pool_cache["proxies"] = cached
        _pool_cache["mtime"] = mtime
    return list(cached)  # caller gets a copy; never mutate the cached list


def get_live_proxies() -> list[str]:
    with _pool_lock:
        return _cached_live_proxies()


def get_random_proxy() -> str | None:
    pool = get_live_proxies()
    return random.choice(pool) if pool else None


def mark_proxy_dead(proxy_url: str) -> bool:
    """Evict a proxy that just failed mid-request: drop it from the in-memory
    cache AND rewrite live.txt without it, so neither this process nor a fresh
    reader hands it out again. Thread-safe. Returns True if it was present.

    No-op for an empty/None url or when PROSPEKT_PROXY_URL is the active hop
    (callers must not prune a stable explicit proxy — that's not pool-managed).
    """
    if not proxy_url:
        return False
    explicit = os.getenv("PROSPEKT_PROXY_URL", "").strip()
    if explicit and proxy_url == explicit:
        return False
    with _pool_lock:
        current = _cached_live_proxies()
        if proxy_url not in current:
            return False
        remaining = [p for p in current if p != proxy_url]
        path = live_file_path()
        try:
            path.write_text("\n".join(remaining), encoding="utf-8")
            new_mtime = path.stat().st_mtime if path.exists() else None
        except OSError as exc:
            logger.warning("mark_proxy_dead: could not rewrite %s: %s", path, exc)
            # Still evict from the in-memory cache so we stop handing it out.
            new_mtime = _pool_cache.get("mtime")
        _pool_cache["proxies"] = remaining
        _pool_cache["mtime"] = new_mtime
        logger.info("proxy_pool: evicted dead proxy %s (%d live remain)", proxy_url, len(remaining))
        return True


# Exceptions that mean "this proxy hop is bad", not "the target rejected us".
# Used to decide when to prune-and-rotate vs. surface the error.
def _is_proxy_failure(exc: BaseException) -> bool:
    # httpx proxy/connect/timeout
    proxy_err = getattr(httpx, "ProxyError", None)
    connect_err = getattr(httpx, "ConnectError", None)
    timeout_err = getattr(httpx, "TimeoutException", None)
    for cls in (proxy_err, connect_err, timeout_err):
        if cls is not None and isinstance(exc, cls):
            return True
    # requests proxy/connection/timeout (lazy import — requests is optional)
    try:
        import requests.exceptions as rexc
        if isinstance(exc, (rexc.ProxyError, rexc.ConnectionError, rexc.Timeout)):
            return True
    except Exception:
        pass
    # stdlib socket timeout + any class literally named like a proxy/timeout error
    if isinstance(exc, (TimeoutError, OSError)):
        name = type(exc).__name__.lower()
        if "proxy" in name or "timeout" in name or "connect" in name:
            return True
    name = type(exc).__name__.lower()
    return "proxy" in name


def fetch_with_proxy_retry(make_request, *, max_attempts: int = 3):
    """Run `make_request(proxy_url)` with prune-and-rotate retry on proxy failure.

    `make_request` receives the proxy URL to use for one attempt (or None to go
    direct) and must RAISE on a proxy-level failure. On a ProxyError/ConnectError/
    timeout we:
      * when rotating the free pool (PROSPEKT_PROXY_URL unset): mark that proxy
        dead and pull a fresh one for the next attempt;
      * when a stable explicit hop is configured (PROSPEKT_PROXY_URL set): keep
        the same hop and just retry (never prune a hop we don't own).
    Non-proxy exceptions propagate immediately. Returns the successful result,
    or re-raises the last proxy error after `max_attempts`.

    When proxying is disabled this is effectively `make_request(None)` once.
    """
    explicit = os.getenv("PROSPEKT_PROXY_URL", "").strip() if proxy_enabled() else ""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        proxy = get_proxy_for_httpx()
        try:
            return make_request(proxy)
        except BaseException as exc:  # noqa: BLE001 — we re-raise below
            if not _is_proxy_failure(exc):
                raise
            last_exc = exc
            # Only prune free-pool proxies; never the stable explicit hop.
            if proxy and not explicit:
                mark_proxy_dead(proxy)
            logger.debug(
                "fetch_with_proxy_retry: attempt %d/%d via %s failed: %s",
                attempt + 1, max_attempts, proxy or "direct", exc,
            )
    if last_exc is not None:
        raise last_exc
    # max_attempts <= 0 guard — make one direct attempt rather than silently None.
    return make_request(get_proxy_for_httpx())


def get_proxy_for_httpx() -> str | None:
    """Resolve the proxy URL a fetcher should use, or None to go direct.

    Priority:
      1. PROSPEKT_PROXY_URL  (e.g. the local mubeng rotator) — one stable hop.
      2. A random live proxy from the pool (Python-side rotation fallback).
    Returns None when proxying is disabled or no proxy is available.
    """
    if not proxy_enabled():
        return None
    explicit = os.getenv("PROSPEKT_PROXY_URL", "").strip()
    if explicit:
        return explicit
    return get_random_proxy()


def write_mubeng_file() -> Path:
    """Live list is already in mubeng's `scheme://ip:port` format."""
    return live_file_path()
