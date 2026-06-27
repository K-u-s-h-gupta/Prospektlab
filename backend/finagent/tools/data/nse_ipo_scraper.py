"""NSE IPO data scraper — fetches live and upcoming IPO data from NSE APIs.

This module provides authoritative IPO data directly from NSE:
- Current issues (live bidding)
- Upcoming/forthcoming issues
- Subscription status and times subscribed

NSE API endpoints:
- /api/ipo-current-issue — live IPOs with subscription data
- /api/all-upcoming-issues?category=ipo — current + forthcoming IPOs
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("finagent.nse_ipo_scraper")

# NSE API endpoints
NSE_BASE = "https://www.nseindia.com"
NSE_CURRENT_ISSUES = f"{NSE_BASE}/api/ipo-current-issue"
NSE_UPCOMING_ISSUES = f"{NSE_BASE}/api/all-upcoming-issues?category=ipo"

# Headers to mimic browser request (NSE blocks non-browser user agents)
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
    "Origin": "https://www.nseindia.com",
}


@dataclass
class NseIpoRecord:
    """IPO record from NSE API."""

    company_name: str
    symbol: str
    series: str  # "EQ" for mainboard, "SME" for SME
    status: str  # "Active", "Forthcoming"
    issue_start_date: str | None = None  # DD-MMM-YYYY
    issue_end_date: str | None = None
    issue_price: str | None = None  # "Rs.107 to Rs.113"
    issue_size_shares: int | None = None
    times_subscribed: float | None = None
    shares_bid: int | None = None
    is_bse_only: bool = False  # Some SMEs are BSE-only


def _parse_nse_date(date_str: str | None) -> str | None:
    """Convert NSE date format (DD-MMM-YYYY) to ISO (YYYY-MM-DD)."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_price_band(price_str: str | None) -> tuple[float | None, float | None]:
    """Extract low and high from price string like 'Rs.107 to Rs.113'."""
    if not price_str:
        return None, None
    # Remove "Rs." and split
    cleaned = re.sub(r"Rs\.?\s*", "", price_str, flags=re.IGNORECASE)
    parts = re.split(r"\s*to\s*", cleaned, flags=re.IGNORECASE)
    try:
        low = float(parts[0].strip().replace(",", ""))
        high = float(parts[-1].strip().replace(",", "")) if len(parts) > 1 else low
        return low, high
    except (ValueError, IndexError):
        return None, None



def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None

def _parse_record(raw: dict[str, Any]) -> NseIpoRecord:
    """Parse raw NSE API response into NseIpoRecord."""
    issue_size = _to_int(raw.get("issueSize") or raw.get("noOfSharesOffered"))
    shares_bid = _to_int(raw.get("noOfsharesBid"))
    times_sub = _to_float(raw.get("noOfTime"))

    return NseIpoRecord(
        company_name=str(raw.get("companyName") or "").strip(),
        symbol=str(raw.get("symbol") or "").strip(),
        series=str(raw.get("series") or "EQ").strip() or "EQ",
        status=str(raw.get("status") or "Active").strip() or "Active",
        issue_start_date=raw.get("issueStartDate"),
        issue_end_date=raw.get("issueEndDate"),
        issue_price=raw.get("issuePrice"),
        issue_size_shares=issue_size,
        times_subscribed=times_sub,
        shares_bid=shares_bid,
        is_bse_only=raw.get("isBse") == "1",
    )


def _rows_from_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("data", "issues", "records", "result"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


async def _fetch_with_session(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    """Fetch JSON from NSE API with proper session handling."""
    # NSE requires a valid session cookie — first hit the main page
    try:
        await client.get(NSE_BASE, timeout=10)
    except Exception:
        pass  # Cookie may already be set

    try:
        resp = await client.get(url, headers=NSE_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning("NSE API returned %d for %s", resp.status_code, url)
            return []
        return _rows_from_payload(resp.json())
    except Exception as exc:
        logger.warning("NSE API error for %s: %s", url, exc)
        return []


async def fetch_nse_current_issues() -> list[NseIpoRecord]:
    """Fetch current (live) IPO issues from NSE with subscription data."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        data = await _fetch_with_session(client, NSE_CURRENT_ISSUES)
    return [_parse_record(r) for r in data if r.get("companyName")]


async def fetch_nse_upcoming_issues() -> list[NseIpoRecord]:
    """Fetch all upcoming IPO issues from NSE (current + forthcoming)."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        data = await _fetch_with_session(client, NSE_UPCOMING_ISSUES)
    return [_parse_record(r) for r in data if r.get("companyName")]


async def fetch_nse_ipo_data() -> dict[str, list[NseIpoRecord]]:
    """Fetch both current and upcoming IPO data from NSE.

    Returns:
        Dict with "current" and "upcoming" lists of NseIpoRecord
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # First get a session cookie
        try:
            await client.get(NSE_BASE, timeout=10)
        except Exception:
            pass

        current_task = _fetch_with_session(client, NSE_CURRENT_ISSUES)
        upcoming_task = _fetch_with_session(client, NSE_UPCOMING_ISSUES)
        current_data, upcoming_data = await asyncio.gather(current_task, upcoming_task)

    current = [_parse_record(r) for r in current_data if r.get("companyName")]
    upcoming = [_parse_record(r) for r in upcoming_data if r.get("companyName")]

    return {"current": current, "upcoming": upcoming}


def nse_record_to_enrichment(record: NseIpoRecord) -> dict[str, Any]:
    """Convert NSE record to enrichment dict for merging with filings.

    Returns dict with:
    - subscription_open, subscription_close (ISO dates)
    - price_band_low, price_band_high
    - issue_size_shares
    - subscription_times (times subscribed)
    - nse_symbol
    - is_sme (True if SME series)
    """
    low, high = _parse_price_band(record.issue_price)
    issue_size_cr = None
    if record.issue_size_shares and high:
        issue_size_cr = round((record.issue_size_shares * high) / 10_000_000, 2)
    subscription_status = (
        f"{record.times_subscribed:.2f}x subscribed"
        if record.times_subscribed is not None
        else None
    )
    return {
        "subscription_open": _parse_nse_date(record.issue_start_date),
        "subscription_close": _parse_nse_date(record.issue_end_date),
        "price_band_low": low,
        "price_band_high": high,
        "issue_size_shares": record.issue_size_shares,
        "issue_size_cr": issue_size_cr,
        "subscription_times": record.times_subscribed,
        "subscription_status": subscription_status,
        "nse_symbol": record.symbol,
        "exchange": "NSE SME" if record.series == "SME" else "NSE",
        "is_sme": record.series == "SME",
        "nse_status": "live" if record.status == "Active" else "forthcoming",
        "source_url": NSE_CURRENT_ISSUES if record.status == "Active" else NSE_UPCOMING_ISSUES,
    }


def build_nse_enrichment_map(
    nse_records: list[NseIpoRecord],
    filings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build slug → enrichment map by fuzzy matching company names.

    Args:
        nse_records: Records from NSE API
        filings: Existing filings from store

    Returns:
        Dict mapping filing slug to enrichment data
    """
    from finagent.tools.data.ipo_fetcher import slugify_company

    # Build lookup by NSE company name slug
    # Important: don't overwrite records that have subscription data with ones that don't
    nse_by_slug: dict[str, NseIpoRecord] = {}
    for rec in nse_records:
        # Clean company name for matching
        name = rec.company_name
        # Remove common suffixes
        for suffix in ("Limited", "Ltd", "Private", "Pvt", "Issue postponed"):
            name = re.sub(rf"\s*-?\s*{suffix}\.?\s*$", "", name, flags=re.IGNORECASE)
        slug = slugify_company(name.strip())
        
        # Only overwrite if new record has more data (subscription times)
        existing = nse_by_slug.get(slug)
        if existing:
            # Keep record with subscription data
            if existing.times_subscribed is not None and rec.times_subscribed is None:
                continue  # Keep existing, skip new
        nse_by_slug[slug] = rec

    # Match against existing filings
    enrichment_map: dict[str, dict[str, Any]] = {}
    for filing in filings:
        slug = filing.get("slug") or ""
        # Try exact match first
        if slug in nse_by_slug:
            enrichment_map[slug] = nse_record_to_enrichment(nse_by_slug[slug])
            continue
        # Try matching on company name
        company = filing.get("company_name") or ""
        for suffix in ("Limited", "Ltd", "Private", "Pvt"):
            company = re.sub(rf"\s*{suffix}\.?\s*$", "", company, flags=re.IGNORECASE)
        company_slug = slugify_company(company.strip())
        if company_slug in nse_by_slug:
            enrichment_map[slug] = nse_record_to_enrichment(nse_by_slug[company_slug])

    return enrichment_map


# --- CLI for testing ---
if __name__ == "__main__":
    import json

    async def main():
        print("Fetching NSE IPO data...")
        data = await fetch_nse_ipo_data()
        print(f"\nCurrent issues ({len(data['current'])}):")
        for rec in data["current"]:
            low, high = _parse_price_band(rec.issue_price)
            print(f"  - {rec.company_name} ({rec.symbol}): ₹{low}-{high}, "
                  f"{rec.times_subscribed:.2f}x subscribed" if rec.times_subscribed else "")
        print(f"\nUpcoming issues ({len(data['upcoming'])}):")
        for rec in data["upcoming"]:
            low, high = _parse_price_band(rec.issue_price)
            status = "LIVE" if rec.status == "Active" else "Forthcoming"
            print(f"  - [{status}] {rec.company_name}: ₹{low}-{high}")

    asyncio.run(main())
