"""NSE session cookie helper.

NSE India blocks requests from cloud/datacenter IPs (Azure, AWS, GCP, etc.).
All NSE scrapers now have automatic BSE fallback, so the 403 is handled
gracefully without manual intervention.

Optional: inject a browser cookie via NSE_COOKIE_STRING to get NSE data
directly (cookies expire every 1-4 hours).

This module also installs a logging filter to suppress the noisy httpx
"HTTP Request: GET https://www.nseindia.com ... 403 Forbidden" INFO messages.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger("finagent.ikg.scrapers._nse_session")


# ---------------------------------------------------------------------------
# Suppress httpx INFO logs for expected NSE 403 responses
# ---------------------------------------------------------------------------
class _NSE403LogFilter(logging.Filter):
    """Drop httpx log records that match expected NSE 403 responses."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "nseindia.com" in msg and "403" in msg:
            return False
        return True


logging.getLogger("httpx").addFilter(_NSE403LogFilter())
logging.getLogger("httpcore").addFilter(_NSE403LogFilter())

# Cache the parsed cookies so we don't re-parse every request
_cached_cookie_string: str | None = None
_cache_loaded_at: float = 0.0
_CACHE_TTL_S = 60.0  # re-read env var every 60 s in case it's updated


def get_nse_cookie_string() -> str | None:
    """Return the NSE cookie string from env var, or None if not set."""
    global _cached_cookie_string, _cache_loaded_at
    now = time.monotonic()
    if now - _cache_loaded_at > _CACHE_TTL_S:
        raw = (os.getenv("NSE_COOKIE_STRING") or "").strip()
        _cached_cookie_string = raw if raw else None
        _cache_loaded_at = now
        if _cached_cookie_string:
            # Log just the first 60 chars so we know it's set without exposing the full value
            logger.debug("NSE_COOKIE_STRING loaded (%d chars): %s...", len(_cached_cookie_string), _cached_cookie_string[:60])
    return _cached_cookie_string


def apply_nse_cookies(headers: dict[str, Any]) -> dict[str, Any]:
    """Add Cookie header to NSE request headers if NSE_COOKIE_STRING is set.

    Returns a new headers dict — does not mutate the input.
    """
    cookie_string = get_nse_cookie_string()
    if not cookie_string:
        return headers
    return {**headers, "Cookie": cookie_string}


def should_skip_nse_home_visit() -> bool:
    """Return True if NSE_COOKIE_STRING is set — home-page visit not needed."""
    return bool(get_nse_cookie_string())


def nse_cookie_status() -> str:
    """Human-readable status string for logging."""
    cookie = get_nse_cookie_string()
    if not cookie:
        return "NSE_COOKIE_STRING not set — will attempt direct session (may fail on cloud IPs)"
    return f"NSE_COOKIE_STRING set ({len(cookie)} chars) — using injected cookies"
