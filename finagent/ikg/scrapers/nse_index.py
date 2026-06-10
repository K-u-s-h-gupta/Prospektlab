"""NSE Nifty 500 Index — company list scraper.

Downloads the latest Nifty 500 constituent list from NSE and stores it
in the ikg_company_master PostgreSQL table with NSE symbol, ISIN, and sector.

Source: https://niftyindices.com/IndexConstituent/ind_nifty500list.csv
        https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv
Rate limit: 1 req/5s

Schedule: Monthly refresh on 1st of month.
"""

from __future__ import annotations

import logging
import os
import re
import time
import csv
import io
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._engine import sync_get

logger = logging.getLogger("finagent.ikg.scrapers.nse_index")

_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.niftyindices.com/",
    "Connection": "keep-alive",
}

_NSE_NIFTY500_CSV_URLS = [
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
]
_REQUEST_DELAY_S = 5.0  # NSE rate limit: 1 req/5s


def _fetch_nse_nifty500(timeout_s: float = 30.0) -> list[dict[str, Any]]:
    """Fetch Nifty 500 constituent data from official CSV endpoints.

    Returns:
        List of CSV row dicts.
    """
    with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
        last_error: Exception | None = None
        for csv_url in _NSE_NIFTY500_CSV_URLS:
            try:
                logger.info("Fetching Nifty 500 CSV: %s", csv_url)
                resp = sync_get(csv_url, headers=_NSE_HEADERS, timeout=timeout_s)
                resp.raise_for_status()
                text = resp.text
                if "Company Name" not in text or "Symbol" not in text:
                    logger.warning("NSE CSV response from %s missing expected header", csv_url)
                    continue
                rows = list(csv.DictReader(io.StringIO(text)))
                if not rows:
                    logger.warning("NSE CSV response from %s had no rows", csv_url)
                    continue
                logger.info("NSE returned %d Nifty 500 constituents from %s", len(rows), csv_url)
                return rows
            except Exception as exc:
                last_error = exc
                logger.warning("NSE CSV fetch failed from %s: %s", csv_url, exc)
                time.sleep(1.0)
        if last_error:
            raise last_error
        raise RuntimeError("No Nifty 500 CSV endpoint returned usable data")


# Map NSE Industry names to broader GICS-style sector names.
# Industries not listed here fall back to their raw industry value.
_INDUSTRY_TO_SECTOR: dict[str, str] = {
    "Financial Services": "Financials",
    "Banks": "Financials",
    "Insurance": "Financials",
    "IT - Software": "Information Technology",
    "IT - Services": "Information Technology",
    "IT - Hardware": "Information Technology",
    "Pharmaceuticals": "Healthcare",
    "Healthcare": "Healthcare",
    "Healthcare Services": "Healthcare",
    "Automobiles": "Consumer Discretionary",
    "Auto Components": "Consumer Discretionary",
    "Consumer Durables": "Consumer Discretionary",
    "Media": "Consumer Discretionary",
    "Textiles": "Consumer Discretionary",
    "FMCG": "Consumer Staples",
    "Food Products": "Consumer Staples",
    "Tobacco Products": "Consumer Staples",
    "Oil & Gas": "Energy",
    "Petroleum Products": "Energy",
    "Power": "Utilities",
    "Utilities": "Utilities",
    "Metals & Mining": "Materials",
    "Steel": "Materials",
    "Cement & Cement Products": "Materials",
    "Construction Materials": "Materials",
    "Chemicals": "Materials",
    "Fertilizers": "Materials",
    "Construction": "Industrials",
    "Capital Goods": "Industrials",
    "Industrial Manufacturing": "Industrials",
    "Aerospace & Defense": "Industrials",
    "Services": "Industrials",
    "Telecom": "Communication Services",
    "Telecommunication": "Communication Services",
    "Realty": "Real Estate",
    "Real Estate": "Real Estate",
    "Diversified": "Industrials",
}


def _industry_to_sector(industry: str) -> str:
    """Map an NSE industry to a broader sector classification."""
    if not industry:
        return "Other"
    # Try exact match first, then substring match
    if industry in _INDUSTRY_TO_SECTOR:
        return _INDUSTRY_TO_SECTOR[industry]
    for key, sector in _INDUSTRY_TO_SECTOR.items():
        if key.lower() in industry.lower() or industry.lower() in key.lower():
            return sector
    return industry  # fallback: use industry as sector


def parse_nse_companies(raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse NSE API response into standardized company dicts.

    Args:
        raw_data: List of company dicts from NSE API.

    Returns:
        List of standardized dicts with: symbol, company_name, isin, industry, sector, series
    """
    parsed = []
    seen_symbols: set[str] = set()
    for item in raw_data:
        symbol = (item.get("Symbol") or item.get("symbol") or "").strip().upper()
        name = (item.get("Company Name") or item.get("companyName") or "").strip()
        isin = (item.get("ISIN Code") or item.get("identifier") or item.get("isin") or "").strip().upper()
        industry = (item.get("Industry") or item.get("industry") or "").strip()
        series = (item.get("Series") or item.get("series") or "EQ").strip().upper()
        sector = _industry_to_sector(industry)

        if not symbol or not name:
            continue
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)

        parsed.append({
            "nse_symbol": symbol,
            "company_name": name,
            "isin": isin or "",
            "industry": industry or "Other",
            "sector": sector,
            "series": series,
            "source": "nse_nifty500_csv",
        })

    logger.info("Parsed %d valid Nifty 500 companies", len(parsed))
    return parsed


def _normalize_company_name_for_match(name: str) -> str:
    value = (name or "").upper()
    value = value.replace("&", " AND ")
    value = re.sub(r"\b(?:THE|LIMITED|LTD|PRIVATE|PVT|PLC|CORPORATION|CORP|COMPANY|CO)\b\.?", " ", value)
    value = re.sub(r"[^A-Z0-9]+", "", value)
    return value


def upsert_nifty500_to_postgres(
    companies: list[dict[str, Any]],
    database_url: str | None = None,
) -> int:
    """Upsert Nifty 500 companies into ikg_company_master table.

    Args:
        companies: Parsed company list.
        database_url: PostgreSQL connection string.

    Returns:
        Number of records upserted.
    """
    db_url = get_database_url(database_url)
    if not db_url:
        logger.warning("No database URL configured, skipping upsert")
        return 0

    upserted = 0
    with connect_postgres(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, company_name, nse_symbol
                from ikg_company_master
                where cin is not null
                  and listing_status ilike 'listed'
                """
            )
            mca_rows = cur.fetchall()
            mca_by_normalized_name: dict[str, list[tuple[Any, str | None]]] = {}
            for row in mca_rows:
                row_id, company_name, existing_symbol = row
                normalized = _normalize_company_name_for_match(str(company_name or ""))
                if normalized:
                    mca_by_normalized_name.setdefault(normalized, []).append((row_id, existing_symbol))

            for co in companies:
                normalized_name = _normalize_company_name_for_match(co["company_name"])
                matched_id = None
                for row_id, existing_symbol in mca_by_normalized_name.get(normalized_name, []):
                    if not existing_symbol or str(existing_symbol).upper() == co["nse_symbol"]:
                        matched_id = row_id
                        break

                if matched_id is not None:
                    cur.execute(
                        "select id, cin from ikg_company_master where upper(trim(nse_symbol)) = upper(trim(%s))",
                        (co["nse_symbol"],),
                    )
                    existing_symbol_row = cur.fetchone()
                    if existing_symbol_row and existing_symbol_row[0] != matched_id:
                        existing_id, existing_cin = existing_symbol_row
                        if existing_cin:
                            cur.execute(
                                """
                                update ikg_company_master
                                set company_name = coalesce(company_name, %s),
                                    isin = coalesce(%s, isin),
                                    sector = coalesce(%s, sector),
                                    industry = coalesce(%s, industry),
                                    listing_status = 'Listed',
                                    updated_at = now()
                                where id = %s
                                """,
                                (
                                    co["company_name"],
                                    co["isin"] or None,
                                    co.get("sector") or None,
                                    co.get("industry") or None,
                                    existing_id,
                                ),
                            )
                            upserted += 1
                            continue
                        else:
                            cur.execute(
                                "delete from ikg_company_master where id = %s",
                                (existing_id,),
                            )
                    cur.execute(
                        """
                        update ikg_company_master
                        set nse_symbol = null,
                            updated_at = now()
                        where upper(trim(nse_symbol)) = upper(trim(%s))
                          and id <> %s
                          and cin is null
                        """,
                        (co["nse_symbol"], matched_id),
                    )
                    cur.execute(
                        """
                        update ikg_company_master
                        set nse_symbol = %s,
                            isin = coalesce(%s, ikg_company_master.isin),
                            sector = coalesce(%s, ikg_company_master.sector),
                            industry = coalesce(%s, ikg_company_master.industry),
                            listing_status = 'Listed',
                            updated_at = now()
                        where id = %s
                        """,
                        (
                            co["nse_symbol"],
                            co["isin"] or None,
                            co.get("sector") or None,
                            co.get("industry") or None,
                            matched_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        insert into ikg_company_master (
                          nse_symbol, company_name, isin, sector, industry, listing_status, updated_at
                        )
                        values (%s, %s, %s, %s, %s, 'Listed', now())
                        on conflict (nse_symbol) do update set
                          company_name = excluded.company_name,
                          isin = coalesce(excluded.isin, ikg_company_master.isin),
                          sector = coalesce(excluded.sector, ikg_company_master.sector),
                          industry = coalesce(excluded.industry, ikg_company_master.industry),
                          listing_status = 'Listed',
                          updated_at = now()
                        """,
                        (
                            co["nse_symbol"],
                            co["company_name"],
                            co.get("isin") or None,
                            co.get("sector") or None,
                            co.get("industry") or None,
                        ),
                    )
                upserted += 1
        conn.commit()

    logger.info("Upserted %d Nifty 500 companies to ikg_company_master", upserted)
    return upserted


def run_nse_nifty500_scraper(database_url: str | None = None) -> dict[str, Any]:
    """Full pipeline: fetch → parse → upsert.

    Returns:
        dict with: companies_fetched, companies_upserted, success, error
    """
    try:
        raw_data = _fetch_nse_nifty500()
        companies = parse_nse_companies(raw_data)
        upserted = upsert_nifty500_to_postgres(companies, database_url)
        return {
            "companies_fetched": len(raw_data),
            "companies_parsed": len(companies),
            "companies_upserted": upserted,
            "success": True,
            "error": None,
        }
    except httpx.HTTPStatusError as exc:
        logger.error("NSE HTTP error: %s", exc)
        return {"success": False, "error": str(exc), "companies_fetched": 0}
    except Exception as exc:
        logger.error("NSE scraper failed: %s", exc)
        return {"success": False, "error": str(exc), "companies_fetched": 0}


if __name__ == "__main__":
    result = run_nse_nifty500_scraper()
    print(result)
