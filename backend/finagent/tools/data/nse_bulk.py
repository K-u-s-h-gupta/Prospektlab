"""NSE bulk market-data fallback (no broker token required).

Provides a *near* real-time layer for Indian **indices** by polling NSE's public
`allIndices` JSON — one call returns ~140 indices (Nifty 50, Bank, IT, 500, …)
with live last price + change during market hours. This feeds the same
`market_feed` cache, so dashboards show live indices even when no Upstox token
is configured.

NOTE: NSE's `equity-stockIndices` (bulk index constituents) endpoint now returns
404 — there is no working free bulk endpoint for individual stock prices, so
stock breadth without a token stays on the existing per-symbol NSE/Yahoo poll.

NSE protects these endpoints with Akamai; a Chrome-impersonated curl_cffi session
+ homepage cookie warm-up is required, and datacenter IPs are usually blocked
(set PROSPEKT_PROXY_ENABLED / PROSPEKT_PROXY_URL to route through a residential
proxy in production).
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("finagent.tools.data.nse_bulk")

_ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
_WARMUP_URLS = (
    "https://www.nseindia.com",
    "https://www.nseindia.com/market-data/live-equity-market",
)
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/live-equity-market",
}

# Cached session + last warm-up time (cookies expire, so re-warm periodically).
_session: Any = None
_session_warmed_at: float = 0.0
_WARM_TTL_S = 600.0


def _proxies() -> dict | None:
    try:
        from finagent.tools.web.proxy_pool import get_proxy_for_httpx
        p = get_proxy_for_httpx()
        if p:
            return {"http": p, "https": p}
    except Exception:
        pass
    return None


def _get_session() -> Any:
    """Return a Chrome-impersonated curl_cffi session, re-warming cookies on TTL."""
    global _session, _session_warmed_at
    try:
        from curl_cffi import requests as creq
    except ImportError:
        logger.warning("curl_cffi not installed — NSE bulk fallback disabled")
        return None
    now = time.time()
    if _session is None or (now - _session_warmed_at) > _WARM_TTL_S:
        try:
            sess = creq.Session(impersonate="chrome")
            proxies = _proxies()
            for url in _WARMUP_URLS:
                sess.get(url, headers=_HEADERS, timeout=12, proxies=proxies)
            _session = sess
            _session_warmed_at = now
        except Exception as exc:
            logger.debug("NSE session warm-up failed: %s", exc)
            return None
    return _session


def _f(val: Any) -> float | None:
    try:
        f = float(val)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


async def fetch_nse_indices() -> list[dict]:
    """Fetch NSE `allIndices` and return normalised index rows:
        [{symbol, price, change, change_pct, open, previousClose}, ...]
    Returns [] on any failure (caller treats as a no-op)."""
    import asyncio

    def _blocking() -> list[dict]:
        sess = _get_session()
        if sess is None:
            return []
        try:
            resp = sess.get(_ALL_INDICES_URL, headers=_HEADERS, timeout=12, proxies=_proxies())
            if resp.status_code != 200:
                logger.debug("NSE allIndices status %s", resp.status_code)
                # Force re-warm next call.
                global _session
                _session = None
                return []
            data = resp.json()
        except Exception as exc:
            logger.debug("NSE allIndices fetch failed: %s", exc)
            return []
        out: list[dict] = []
        for row in (data.get("data") or []):
            sym = str(row.get("indexSymbol") or row.get("index") or "").strip().upper()
            price = _f(row.get("last"))
            if not sym or price is None:
                continue
            prev = _f(row.get("previousClose"))
            change = _f(row.get("variation"))
            if change is None and prev is not None:
                change = price - prev
            out.append({
                "symbol": sym,
                "price": price,
                "change": change if change is not None else 0.0,
                "change_pct": _f(row.get("percentChange")) or 0.0,
                "open": _f(row.get("open")),
                "previousClose": prev,
            })
        return out

    return await asyncio.get_event_loop().run_in_executor(None, _blocking)
