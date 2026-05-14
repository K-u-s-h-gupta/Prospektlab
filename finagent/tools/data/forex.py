"""USD→INR FX conversion.

Uses Yahoo Finance's `USDINR=X` chart endpoint (no auth) to fetch the live
spot rate. Result is cached for the lifetime of the process so a single
research session pays the network cost exactly once.

Failure mode is intentionally graceful: if the network call fails we fall
back to a static rate (last-known floor) so memos never crash, just lose
fidelity. The fallback is documented in the memo so the reader can verify.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.forex")

_YAHOO_FX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/USDINR=X?range=1d&interval=1d"
_FALLBACK_USD_INR = 83.4  # 2024 floor — only used if network/quote fails.
_CACHE_TTL_S = 60 * 30  # 30 min — FX moves slowly enough for a research memo


@dataclass
class FxRate:
    pair: str
    rate: float
    as_of: float
    source: str  # "yahoo" | "fallback" | "override"


_CACHE: dict[str, FxRate] = {}
_LOCK = asyncio.Lock()


async def _fetch_yahoo_usdinr() -> float | None:
    try:
        res = await fetch(_YAHOO_FX_URL, respect_robots=False, timeout_s=8.0)
    except Exception as exc:  # network completely broken
        logger.info("USDINR fetch raised: %s", exc)
        return None
    if res.status != 200 or not res.text:
        return None
    try:
        payload = json.loads(res.text)
    except Exception:
        return None
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    meta = result[0].get("meta") or {}
    rate = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
    if rate and rate > 1:  # sanity floor — USD/INR is always > 1
        return float(rate)
    return None


async def get_usd_inr() -> FxRate:
    """Return current USD→INR with caching. Never raises."""
    override = os.getenv("FINAGENT_USD_INR")
    if override:
        try:
            return FxRate(pair="USD/INR", rate=float(override), as_of=time.time(), source="override")
        except ValueError:
            pass

    cached = _CACHE.get("USD/INR")
    if cached and (time.time() - cached.as_of) < _CACHE_TTL_S:
        return cached

    async with _LOCK:
        cached = _CACHE.get("USD/INR")
        if cached and (time.time() - cached.as_of) < _CACHE_TTL_S:
            return cached
        rate = await _fetch_yahoo_usdinr()
        if rate is None:
            entry = FxRate(pair="USD/INR", rate=_FALLBACK_USD_INR, as_of=time.time(), source="fallback")
        else:
            entry = FxRate(pair="USD/INR", rate=rate, as_of=time.time(), source="yahoo")
        _CACHE["USD/INR"] = entry
        return entry


def format_inr(amount_usd: float | None, rate: float, *, compact: bool = True) -> str:
    """Format a USD amount as Indian-style INR (₹ with lakh/crore grouping).

    `compact=True` switches to ₹X.XX Cr / ₹X.XX L for big numbers so memos
    don't drown in zeros. The Indian numbering system groups by 2s after
    the first 3 digits (10,00,000 not 1,000,000) — we honour that.
    """
    if amount_usd is None:
        return "n/a"
    inr = amount_usd * rate
    sign = "-" if inr < 0 else ""
    inr = abs(inr)
    if compact:
        if inr >= 1e7:
            return f"{sign}₹{inr/1e7:,.2f} Cr"
        if inr >= 1e5:
            return f"{sign}₹{inr/1e5:,.2f} L"
    # Indian comma grouping
    s = f"{inr:,.2f}"
    # Python's locale-free grouping is western (1,234,567.89). Convert.
    if "." in s:
        whole, frac = s.split(".")
    else:
        whole, frac = s, "00"
    whole = whole.replace(",", "")
    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        rest = ",".join([rest[max(0, i - 2):i] for i in range(len(rest), 0, -2)][::-1])
        whole = f"{rest},{last3}"
    return f"{sign}₹{whole}.{frac}"


def format_dual(amount_usd: float | None, rate: float) -> str:
    """`$X.XX (₹Y.YY Cr)` — used in memo prose so the reader sees both."""
    if amount_usd is None:
        return "n/a"
    inr = format_inr(amount_usd, rate)
    # USD compact for parity
    usd_abs = abs(amount_usd)
    sign = "-" if amount_usd < 0 else ""
    if usd_abs >= 1e9:
        usd = f"{sign}${usd_abs/1e9:,.2f}B"
    elif usd_abs >= 1e6:
        usd = f"{sign}${usd_abs/1e6:,.2f}M"
    elif usd_abs >= 1e3:
        usd = f"{sign}${usd_abs/1e3:,.2f}K"
    else:
        usd = f"{sign}${usd_abs:,.2f}"
    return f"{usd} ({inr})"
