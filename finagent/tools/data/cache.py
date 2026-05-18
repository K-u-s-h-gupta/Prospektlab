"""India-aware smart cache for enrichment data.

TTL varies by data type and whether we are inside NSE/BSE market hours
(Mon–Fri 09:15–15:30 IST).  During market hours, live data (price,
sentiment, news) expires very quickly; structural data (shareholding,
Wikipedia, profile) stays cached much longer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger("finagent.cache")

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

# TTL table: (market_hours_seconds, off_hours_seconds)
_TTL: dict[str, tuple[int, int]] = {
    "price":        (60,    1_800),   # 1 min live / 30 min off
    "fundamentals": (300,   3_600),   # 5 min / 1 hr
    "shareholding": (86_400, 86_400), # 24 hr always (quarterly update)
    "news":         (180,   900),     # 3 min / 15 min
    "wikipedia":    (21_600, 21_600), # 6 hr always
    "sentiment":    (300,   1_800),   # 5 min / 30 min
    "fx":           (120,   3_600),   # 2 min / 1 hr
    "quarterly":    (3_600, 21_600),  # 1 hr / 6 hr
    "profile":      (3_600, 21_600),  # company profile
    "sebi_filing":  (86_400, 86_400), # filings are static
}

# In-memory cache: key -> (value, expiry_timestamp)
_CACHE: dict[str, tuple[Any, float]] = {}
_CACHE_LOCK = asyncio.Lock()


def is_market_hours() -> bool:
    """Return True if current IST time is within NSE/BSE trading hours."""
    now = datetime.now(_IST)
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def cache_ttl(data_type: str) -> int:
    """Return the appropriate TTL (seconds) for *data_type* right now."""
    on_sec, off_sec = _TTL.get(data_type, (300, 1_800))
    return on_sec if is_market_hours() else off_sec


def _make_key(namespace: str, identifier: str) -> str:
    return f"{namespace}::{identifier.lower().strip()}"


def cache_get(namespace: str, identifier: str) -> Any | None:
    """Return cached value if still fresh, else None."""
    key = _make_key(namespace, identifier)
    entry = _CACHE.get(key)
    if entry is None:
        return None
    value, expiry = entry
    if time.monotonic() > expiry:
        _CACHE.pop(key, None)
        return None
    return value


def cache_set(namespace: str, identifier: str, value: Any, data_type: str = "fundamentals") -> None:
    """Store *value* in the cache with the appropriate TTL."""
    key = _make_key(namespace, identifier)
    ttl = cache_ttl(data_type)
    _CACHE[key] = (value, time.monotonic() + ttl)
    logger.debug("cache_set %s ttl=%ds market=%s", key, ttl, is_market_hours())


T = TypeVar("T")


async def cached_call(
    namespace: str,
    identifier: str,
    data_type: str,
    fn: Callable[[], Coroutine[Any, Any, T]],
) -> T:
    """Call *fn* only if cache is stale; otherwise return cached result."""
    hit = cache_get(namespace, identifier)
    if hit is not None:
        logger.debug("cache_hit %s::%s", namespace, identifier)
        return hit  # type: ignore[return-value]
    result = await fn()
    if result is not None:
        cache_set(namespace, identifier, result, data_type)
    return result


def cache_invalidate(namespace: str, identifier: str) -> None:
    """Force-remove a cache entry (e.g. after a user stop/reset)."""
    key = _make_key(namespace, identifier)
    _CACHE.pop(key, None)


def cache_stats() -> dict[str, int]:
    """Return basic cache statistics for debugging."""
    now = time.monotonic()
    live = sum(1 for _, (_, exp) in _CACHE.items() if exp > now)
    return {"total": len(_CACHE), "live": live, "expired": len(_CACHE) - live}
