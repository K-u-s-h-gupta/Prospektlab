"""BSE India IPO data scraper — fetches live and upcoming IPO data.

NOTE: BSE deprecated their IPO API endpoints in 2024-2025. This module now uses
NSE's IPO API as the primary data source since most IPOs are dual-listed on both
exchanges. The data is normalized to the BseIpoRecord format for compatibility.

Data sources:
- Primary: NSE IPO API (https://www.nseindia.com/api/ipo-current-issue)
- Fallback: Empty results (BSE APIs no longer available)

The original BSE endpoints that used to work:
- /download/BhsSmallFMIPO_new.aspx — Now returns Angular SPA shell
- /static/markets/PublicIssues/IPOLIVE — Now returns Angular SPA shell  
- api.bseindia.com/BseIndiaAPI/api/IPOData/w — Returns 404 HTML page
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("finagent.bse_ipo_scraper")

# NSE URLs (primary source since BSE deprecated their API)
NSE_BASE = "https://www.nseindia.com"
NSE_IPO_CURRENT = f"{NSE_BASE}/api/ipo-current-issue"

# Headers for NSE requests (requires proper headers and cookies)
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


@dataclass
class BseIpoRecord:
    """IPO record (sourced from NSE API, normalized for compatibility)."""
    
    company_name: str
    scrip_code: str = ""  # NSE symbol used as identifier
    series: str = "EQ"  # "EQ" for mainboard, "SME" for SME
    status: str = "Forthcoming"  # "Active", "Forthcoming", "Closed"
    issue_start_date: str | None = None  # ISO format (YYYY-MM-DD)
    issue_end_date: str | None = None
    price_band_low: float | None = None
    price_band_high: float | None = None
    issue_size_cr: float | None = None
    lot_size: int | None = None
    times_subscribed: float | None = None
    listing_date: str | None = None
    nse_symbol: str | None = None  # NSE trading symbol


def _parse_nse_date(date_str: str | None) -> str | None:
    """Convert NSE date formats to ISO (YYYY-MM-DD).
    
    NSE uses format like "24-Jun-2026".
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    
    # Try various formats
    formats = [
        "%d-%b-%Y",  # 15-Jan-2024 (NSE standard)
        "%d/%m/%Y",  # 15/01/2024
        "%d-%m-%Y",  # 15-01-2024
        "%Y-%m-%d",  # Already ISO
        "%d %b %Y",  # 15 Jan 2024
        "%d %B %Y",  # 15 January 2024
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None


def _parse_nse_price(price_str: str | None) -> tuple[float | None, float | None]:
    """Extract low and high from NSE price string.
    
    NSE format: "Rs.107 to Rs.113" or "Rs.100"
    """
    if not price_str:
        return None, None
    
    # Remove currency symbols and extra spaces
    cleaned = re.sub(r"[₹Rs\.INR\s]+", " ", price_str, flags=re.IGNORECASE).strip()
    
    # Try to find range (e.g., "107 to 113" or "107-113")
    range_match = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:to|-)\s*([\d,]+(?:\.\d+)?)", cleaned)
    if range_match:
        try:
            low = float(range_match.group(1).replace(",", ""))
            high = float(range_match.group(2).replace(",", ""))
            return low, high
        except ValueError:
            pass
    
    # Single price
    single_match = re.search(r"([\d,]+(?:\.\d+)?)", cleaned)
    if single_match:
        try:
            price = float(single_match.group(1).replace(",", ""))
            return price, price
        except ValueError:
            pass
    
    return None, None


def _parse_issue_size(size_str: str | None) -> float | None:
    """Parse issue size from NSE (in shares) and convert to crores if needed."""
    if not size_str:
        return None
    
    try:
        # NSE returns issue size as number of shares (e.g., "11130880")
        shares = float(str(size_str).replace(",", ""))
        # Cannot convert to crores without price, so return raw shares
        return shares
    except (ValueError, TypeError):
        return None


def _parse_subscription_times(times_str: str | None) -> float | None:
    """Parse subscription times from NSE response."""
    if times_str is None or times_str == "":
        return None
    
    try:
        return float(times_str)
    except (ValueError, TypeError):
        return None


def _nse_record_to_bse_record(nse_data: dict[str, Any]) -> BseIpoRecord | None:
    """Convert NSE IPO API response to BseIpoRecord format."""
    company_name = nse_data.get("companyName")
    if not company_name:
        return None
    
    # Clean company name (remove status annotations like "-Issue postponed")
    clean_name = re.sub(r"-Issue postponed.*$", "", company_name, flags=re.IGNORECASE).strip()
    
    # Parse dates
    start_date = _parse_nse_date(nse_data.get("issueStartDate"))
    end_date = _parse_nse_date(nse_data.get("issueEndDate"))
    
    # Parse price band
    price_low, price_high = _parse_nse_price(nse_data.get("issuePrice"))
    
    # Parse issue size (NSE returns number of shares)
    issue_size = _parse_issue_size(nse_data.get("issueSize"))
    
    # Parse subscription times
    times_subscribed = _parse_subscription_times(nse_data.get("noOfTime"))
    
    # Determine status from NSE status field
    nse_status = nse_data.get("status", "").lower()
    if nse_status == "active":
        status = "Active"
    elif nse_status == "closed":
        status = "Closed"
    else:
        # Fallback: determine from dates
        status = "Forthcoming"
        today = datetime.now().strftime("%Y-%m-%d")
        if start_date and end_date:
            if start_date <= today <= end_date:
                status = "Active"
            elif today > end_date:
                status = "Closed"
    
    # Determine series (EQ for mainboard, SME for SME issues)
    series = nse_data.get("series", "EQ")
    if series not in ("EQ", "SME"):
        series = "EQ"
    
    symbol = nse_data.get("symbol", "")
    
    return BseIpoRecord(
        company_name=clean_name,
        scrip_code=symbol,  # Use NSE symbol as identifier
        series=series,
        status=status,
        issue_start_date=start_date,
        issue_end_date=end_date,
        price_band_low=price_low,
        price_band_high=price_high,
        issue_size_cr=issue_size,  # Note: this is shares, not crores
        times_subscribed=times_subscribed,
        nse_symbol=symbol,
    )


async def _fetch_nse_ipo_data(client: httpx.AsyncClient) -> list[BseIpoRecord]:
    """Fetch IPO data from NSE API.
    
    NSE requires:
    1. First visit the main page to get cookies
    2. Then call the API with proper headers and cookies
    """
    records: list[BseIpoRecord] = []
    
    try:
        # Step 1: Visit main page to establish session and get cookies
        await client.get(NSE_BASE, headers=NSE_HEADERS, timeout=15)
        
        # Step 2: Fetch IPO data
        resp = await client.get(NSE_IPO_CURRENT, headers=NSE_HEADERS, timeout=20)
        
        if resp.status_code != 200:
            logger.warning("NSE IPO API returned %d", resp.status_code)
            return records
        
        # Check content type - should be JSON
        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type.lower():
            # NSE sometimes returns HTML for blocked requests
            if "<html" in resp.text.lower()[:100]:
                logger.warning("NSE returned HTML instead of JSON (possible rate limit)")
                return records
        
        data = resp.json()
        
        if not isinstance(data, list):
            logger.warning("NSE IPO API returned unexpected format: %s", type(data))
            return records
        
        for item in data:
            record = _nse_record_to_bse_record(item)
            if record:
                records.append(record)
        
        logger.info("NSE IPO API returned %d records", len(records))
        
    except httpx.TimeoutException:
        logger.warning("NSE IPO API request timed out")
    except httpx.HTTPError as exc:
        logger.warning("NSE IPO API HTTP error: %s", exc)
    except Exception as exc:
        logger.warning("NSE IPO API error: %s", exc)
    
    return records


async def fetch_bse_current_issues() -> list[BseIpoRecord]:
    """Fetch current (live) IPO issues.
    
    Uses NSE API as primary data source since BSE deprecated their IPO APIs.
    Most IPOs are dual-listed on both NSE and BSE.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        records = await _fetch_nse_ipo_data(client)
    
    # Filter to active only
    return [r for r in records if r.status == "Active"]


async def fetch_bse_upcoming_issues() -> list[BseIpoRecord]:
    """Fetch all upcoming IPO issues (current + forthcoming).
    
    Uses NSE API as primary data source since BSE deprecated their IPO APIs.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        records = await _fetch_nse_ipo_data(client)
    
    return [r for r in records if r.status in ("Active", "Forthcoming")]


async def fetch_bse_ipo_data() -> dict[str, list[BseIpoRecord]]:
    """Fetch both current and upcoming IPO data.
    
    Uses NSE API as primary data source since BSE deprecated their IPO APIs.
    The function name is kept for backward compatibility.
    
    Returns:
        Dict with "current" and "upcoming" lists of BseIpoRecord
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        all_records = await _fetch_nse_ipo_data(client)
    
    current = [r for r in all_records if r.status == "Active"]
    upcoming = [r for r in all_records if r.status in ("Active", "Forthcoming")]
    
    logger.info("IPO fetch: %d total, %d current, %d upcoming",
                len(all_records), len(current), len(upcoming))
    
    return {"current": current, "upcoming": upcoming}


def bse_record_to_enrichment(record: BseIpoRecord) -> dict[str, Any]:
    """Convert IPO record to enrichment dict for merging with filings."""
    return {
        "subscription_open": record.issue_start_date,
        "subscription_close": record.issue_end_date,
        "price_band_low": record.price_band_low,
        "price_band_high": record.price_band_high,
        "issue_size_cr": record.issue_size_cr,
        "lot_size": record.lot_size,
        "nse_symbol": record.nse_symbol,
        "scrip_code": record.scrip_code,
        "is_sme": record.series == "SME",
        "ipo_status": "live" if record.status == "Active" else "forthcoming",
        "listing_date": record.listing_date,
        "times_subscribed": record.times_subscribed,
    }


def build_bse_enrichment_map(
    bse_records: list[BseIpoRecord],
    filings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build slug → enrichment map by fuzzy matching company names.
    
    Args:
        bse_records: Records from BSE scraping
        filings: Existing filings from store
    
    Returns:
        Dict mapping filing slug to enrichment data
    """
    from finagent.tools.data.ipo_fetcher import slugify_company
    
    # Build lookup by BSE company name slug
    bse_by_slug: dict[str, BseIpoRecord] = {}
    for rec in bse_records:
        name = rec.company_name
        for suffix in ("Limited", "Ltd", "Private", "Pvt"):
            name = re.sub(rf"\s*-?\s*{suffix}\.?\s*$", "", name, flags=re.IGNORECASE)
        slug = slugify_company(name.strip())
        
        existing = bse_by_slug.get(slug)
        if existing:
            # Keep record with more data
            if existing.times_subscribed is not None and rec.times_subscribed is None:
                continue
        bse_by_slug[slug] = rec
    
    # Match against existing filings
    enrichment_map: dict[str, dict[str, Any]] = {}
    for filing in filings:
        slug = filing.get("slug") or ""
        
        # Try exact match
        if slug in bse_by_slug:
            enrichment_map[slug] = bse_record_to_enrichment(bse_by_slug[slug])
            continue
        
        # Try company name match
        company = filing.get("company_name") or ""
        for suffix in ("Limited", "Ltd", "Private", "Pvt"):
            company = re.sub(rf"\s*{suffix}\.?\s*$", "", company, flags=re.IGNORECASE)
        company_slug = slugify_company(company.strip())
        if company_slug in bse_by_slug:
            enrichment_map[slug] = bse_record_to_enrichment(bse_by_slug[company_slug])
    
    return enrichment_map


# CLI for testing
if __name__ == "__main__":
    async def main():
        print("Fetching IPO data (via NSE API)...")
        data = await fetch_bse_ipo_data()
        print(f"\nCurrent issues ({len(data['current'])}):")
        for rec in data["current"]:
            price = f"Rs.{rec.price_band_low}-{rec.price_band_high}" if rec.price_band_low else "N/A"
            subs = f" ({rec.times_subscribed:.2f}x subscribed)" if rec.times_subscribed else ""
            print(f"  - {rec.company_name} ({rec.series}): {price}{subs}")
        print(f"\nUpcoming issues ({len(data['upcoming'])}):")
        for rec in data["upcoming"]:
            status = "LIVE" if rec.status == "Active" else "Forthcoming"
            price = f"Rs.{rec.price_band_low}-{rec.price_band_high}" if rec.price_band_low else "N/A"
            dates = f"{rec.issue_start_date} to {rec.issue_end_date}" if rec.issue_start_date else "TBD"
            print(f"  - [{status}] {rec.company_name}: {price} | {dates}")
    
    asyncio.run(main())
