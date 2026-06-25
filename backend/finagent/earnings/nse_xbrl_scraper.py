"""NSE XBRL-based quarterly financial data scraper.

NSE mandates XBRL filing for all quarterly results.  The
/api/corporates-financial-results endpoint exposes these filings with direct
XBRL XML links — giving us perfectly structured Revenue, PAT, EBITDA, EPS
figures without any PDF parsing.

Used to populate historical QoQ/YoY comparison data in earnings_details.
Coverage: all quarters indexed by NSE (typically current FY and the previous
2–3 fiscal years).

Value units in XBRL are raw INR.  We convert to Rs Crore (÷ 1e7).
EPS is already in Rs (no conversion needed).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from finagent.earnings.analysis import fiscal_quarter_from_date, parse_date

logger = logging.getLogger("finagent.earnings.nse_xbrl_scraper")

_NSE_FIN_RESULTS = "https://www.nseindia.com/api/corporates-financial-results"
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# In-memory cache for XBRL financial results. Key: symbol.upper().
# Values are cached for 6 hours so repeated earnings detail calls don't hit NSE.
_XBRL_CACHE: dict[str, tuple[list[dict[str, Any]], float]] = {}
_XBRL_CACHE_TTL_SECONDS = 6 * 60 * 60
_XBRL_CACHE_LOCK = threading.Lock()


def _get_cached_xbrl(symbol: str) -> list[dict[str, Any]] | None:
    with _XBRL_CACHE_LOCK:
        entry = _XBRL_CACHE.get(symbol.upper())
    if not entry:
        return None
    results, cached_at = entry
    if time.monotonic() - cached_at > _XBRL_CACHE_TTL_SECONDS:
        with _XBRL_CACHE_LOCK:
            _XBRL_CACHE.pop(symbol.upper(), None)
        return None
    return results


def _set_cached_xbrl(symbol: str, results: list[dict[str, Any]]) -> None:
    with _XBRL_CACHE_LOCK:
        _XBRL_CACHE[symbol.upper()] = (results, time.monotonic())

# XBRL element local-names that map to our metric keys.
# contextRef="OneD" = current quarter (3-month).  "FourD" = YTD (usually 9-month).
_XBRL_METRIC_MAP: dict[str, str] = {
    "RevenueFromOperations": "revenue",
    "ProfitLossForPeriod": "pat",
    "ProfitLossForPeriodFromContinuingOperations": "pat",  # fallback
    "BasicEarningsLossPerShareFromContinuingOperations": "eps",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations": "eps",
    "DepreciationDepletionAndAmortisationExpense": "_da",   # internal use for EBITDA
    "ProfitBeforeExceptionalItemsAndTax": "_ebit",          # internal use for EBITDA
    "ProfitBeforeTax": "_pbt",
}
# Metrics whose values are in Rs (not INR raw) — skip ÷1e7
_NO_SCALE_METRICS: frozenset[str] = frozenset({"eps"})
_INR_TO_CR = 1e7  # 1 Crore = 10,000,000


def _nse_session() -> httpx.Client:
    client = httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        client.get("https://www.nseindia.com/", headers=_NSE_HEADERS)
    except Exception:
        pass
    return client


def fetch_nse_quarterly_xbrl_list(
    symbol: str,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Return raw NSE financial-results records for a symbol (with XBRL URLs)."""
    own_client = client is None
    if own_client:
        client = _nse_session()
    try:
        r = client.get(
            _NSE_FIN_RESULTS,
            params={"symbol": symbol.upper(), "index": "equities", "period": "Q"},
            headers={
                **_NSE_HEADERS,
                "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
            },
        )
        data = r.json() if r.status_code == 200 else []
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.debug("fetch_nse_quarterly_xbrl_list failed for %s: %s", symbol, exc)
        return []
    finally:
        if own_client:
            client.close()


def parse_xbrl_quarterly(xml_bytes: bytes) -> dict[str, float | None]:
    """Parse XBRL XML and return quarterly (OneD context) financial metrics.

    Returns dict with keys: revenue, pat, ebitda, eps (all in Rs Crore or Rs).
    """
    metrics: dict[str, Any] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        logger.debug("XBRL XML parse error: %s", exc)
        return {}

    for elem in root.iter():
        tag = elem.tag
        local = tag.split("}")[-1] if "}" in tag else tag
        metric_key = _XBRL_METRIC_MAP.get(local)
        if not metric_key:
            continue
        # Only use OneD context (current quarter figures)
        ctx = elem.get("contextRef", "")
        if ctx != "OneD":
            continue
        text = (elem.text or "").strip()
        if not text:
            continue
        try:
            raw_val = float(text)
        except ValueError:
            continue

        # Convert raw INR to Crore (except EPS which is already in Rs)
        if metric_key in _NO_SCALE_METRICS:
            value = round(raw_val, 2)
        else:
            value = round(raw_val / _INR_TO_CR, 2)

        # Only overwrite if not already set (first match wins per key)
        if metric_key.startswith("_"):
            # Internal helper metric (for EBITDA computation)
            if metric_key not in metrics:
                metrics[metric_key] = value
        else:
            if metric_key not in metrics:
                metrics[metric_key] = value

    # Compute EBITDA = EBIT + D&A
    if "_ebit" in metrics and "_da" in metrics:
        metrics["ebitda"] = round(metrics["_ebit"] + metrics["_da"], 2)
    elif "_pbt" in metrics and "_da" in metrics:
        # Fallback: PBT + D&A (ignores interest but better than nothing)
        metrics["ebitda"] = round(metrics["_pbt"] + metrics["_da"], 2)

    # Compute margins
    if metrics.get("revenue") and metrics.get("pat"):
        metrics["pat_margin"] = round(
            metrics["pat"] / metrics["revenue"] * 100, 2
        )
    if metrics.get("revenue") and metrics.get("ebitda"):
        metrics["ebitda_margin"] = round(
            metrics["ebitda"] / metrics["revenue"] * 100, 2
        )

    # Strip internal helpers
    return {k: v for k, v in metrics.items() if not k.startswith("_")}


def fetch_xbrl_metrics_for_quarter(
    xbrl_url: str,
    client: httpx.Client | None = None,
) -> dict[str, float | None]:
    """Download and parse the XBRL file for a single quarter."""
    if not xbrl_url:
        return {}
    # Normalise URL
    if xbrl_url.startswith("//"):
        xbrl_url = f"https:{xbrl_url}"
    elif xbrl_url.startswith("/"):
        xbrl_url = f"https://nsearchives.nseindia.com{xbrl_url}"

    own_client = client is None
    if own_client:
        client = _nse_session()
    try:
        r = client.get(xbrl_url, headers=_NSE_HEADERS, timeout=30.0)
        if r.status_code != 200 or not r.content:
            return {}
        return parse_xbrl_quarterly(r.content)
    except Exception as exc:
        logger.debug("XBRL download/parse failed for %s: %s", xbrl_url, exc)
        return {}
    finally:
        if own_client:
            client.close()


def fetch_nse_quarterly_financials(
    symbol: str,
    *,
    consolidated_only: bool = True,
    max_quarters: int = 8,
) -> list[dict[str, Any]]:
    """Return last N quarters of structured financial data for a symbol from NSE XBRL.

    Each record:
      {symbol, from_date, to_date, fiscal_quarter, consolidated, audited,
       revenue, pat, ebitda, eps, pat_margin, ebitda_margin, xbrl_url}

    All monetary values in Rs Crore; EPS in Rs.
    """
    cached = _get_cached_xbrl(symbol)
    if cached is not None:
        return cached[:max_quarters]

    records: list[dict[str, Any]] = []

    client = _nse_session()
    try:
        raw_list = fetch_nse_quarterly_xbrl_list(symbol, client=client)
        if not raw_list:
            _set_cached_xbrl(symbol, [])
            return []

        # Filter: quarterly (not annual), consolidated if requested
        filtered = [
            item for item in raw_list
            if item.get("xbrl")
            and str(item.get("period") or "").lower() == "quarterly"
            and (not consolidated_only or str(item.get("consolidated") or "") == "Consolidated")
        ]

        # Sort newest first by toDate
        def _sort_key(item: dict[str, Any]) -> str:
            td = str(item.get("toDate") or "")
            # Convert "31-Mar-2024" → "2024-03-31" for reliable string sort
            try:
                return datetime.strptime(td, "%d-%b-%Y").strftime("%Y-%m-%d")
            except ValueError:
                return td

        filtered.sort(key=_sort_key, reverse=True)
        seen_quarters: set[str] = set()

        for item in filtered:
            if len(records) >= max_quarters:
                break

            xbrl_url = str(item.get("xbrl") or "")
            from_date_str = str(item.get("fromDate") or "")
            to_date_str = str(item.get("toDate") or "")

            # Dedup by quarter end date
            dedup_key = to_date_str
            if dedup_key in seen_quarters:
                continue
            seen_quarters.add(dedup_key)

            # Parse dates
            from_dt = _parse_nse_date(from_date_str)
            to_dt = _parse_nse_date(to_date_str)
            fiscal_quarter = fiscal_quarter_from_date(to_dt) if to_dt else ""

            # Download and parse XBRL
            metrics = fetch_xbrl_metrics_for_quarter(xbrl_url, client=client)
            if not metrics:
                continue

            records.append(
                {
                    "symbol": symbol.upper(),
                    "from_date": from_dt.isoformat() if from_dt else from_date_str,
                    "to_date": to_dt.isoformat() if to_dt else to_date_str,
                    "fiscal_quarter": fiscal_quarter,
                    "consolidated": str(item.get("consolidated") or ""),
                    "audited": str(item.get("audited") or ""),
                    "xbrl_url": xbrl_url,
                    **metrics,
                }
            )

    finally:
        client.close()

    _set_cached_xbrl(symbol, records)
    return records


def _parse_nse_date(raw: str) -> date | None:
    """Parse NSE date strings like '31-Mar-2024'."""
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return parse_date(raw)
