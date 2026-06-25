"""Scraper for ipowatch.in — server-rendered HTML with live IPO data.

Two-stage scraper:
  Stage 1: /upcoming-ipo/ listing page → price band, dates, size, company URLs
  Stage 2: Individual company pages  → fresh/OFS split, GMP, allotment date,
           listing date, financials (revenue/PAT/assets), KPIs

Public API:
    fetch_ipowatch_data(include_details=True) -> list[IpowatchRecord]
    build_enrichment_map(records, filings) -> dict[slug, enrichment_fields]
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger("finagent.tools.data.ipowatch_scraper")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://ipowatch.in/",
}

_UPCOMING_URL = "https://ipowatch.in/upcoming-ipo/"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class IpowatchRecord:
    name: str
    name_key: str
    date_label: str
    page_url: str | None              # ipowatch individual page URL
    subscription_open: str | None
    subscription_close: str | None
    issue_size_cr: float | None
    price_band_low: int | None
    price_band_high: int | None
    # Filled in by stage-2 individual page scrape
    fresh_issue_cr: float | None = None
    ofs_cr: float | None = None
    ofs_shares: int | None = None
    gmp: int | None = None
    allotment_date: str | None = None
    listing_date: str | None = None
    lot_size: int | None = None
    exchange: str | None = None
    # Financials from company page
    financials: dict[str, Any] = field(default_factory=dict)
    kpis: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_FMTS = (
    "%B %d, %Y",   # June 5, 2026
    "%B %d,%Y",
    "%d %B %Y",
    "%d %B, %Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
)


def _parse_iso(raw: str) -> str | None:
    raw = re.sub(r"\s+", " ", (raw or "").strip()).strip(".,;*#")
    for abbr, full in _MONTHS.items():
        raw = re.sub(rf"\b{abbr}\b", [k for k, v in _MONTHS.items() if v == full][0].capitalize()
                     + raw[raw.lower().find(abbr) + len(abbr):],
                     raw, flags=re.IGNORECASE)
    # simpler: just try strptime with month expansion
    _MONTH_NAMES = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    for fmt in _DATE_FMTS:
        try:
            from datetime import datetime as _dt
            return _dt.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_date_range(raw: str) -> tuple[str | None, str | None]:
    raw = (raw or "").strip()
    today = date.today()
    year = today.year

    m = re.match(r"(\d{1,2})-(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?", raw)
    if m:
        d1_s, d2_s, month_str, yr_s = m.groups()
        yr = int(yr_s) if yr_s else year
        mo = _MONTHS.get(month_str[:3].lower())
        if mo:
            try:
                d1, d2 = int(d1_s), int(d2_s)
                if d1 > d2:
                    prev_mo = mo - 1 if mo > 1 else 12
                    prev_yr = yr if mo > 1 else yr - 1
                    return date(prev_yr, prev_mo, d1).isoformat(), date(yr, mo, d2).isoformat()
                return date(yr, mo, d1).isoformat(), date(yr, mo, d2).isoformat()
            except ValueError:
                pass

    m2 = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?", raw)
    if m2:
        d1, mo1_s, d2, mo2_s, yr_s = m2.groups()
        yr = int(yr_s) if yr_s else year
        mo1 = _MONTHS.get(mo1_s[:3].lower())
        mo2 = _MONTHS.get(mo2_s[:3].lower())
        if mo1 and mo2:
            try:
                return date(yr, mo1, int(d1)).isoformat(), date(yr, mo2, int(d2)).isoformat()
            except ValueError:
                pass
    return None, None


# ---------------------------------------------------------------------------
# Amount helpers
# ---------------------------------------------------------------------------

def _parse_crores(raw: str) -> float | None:
    raw = (raw or "").replace("₹", "").replace("Rs.", "").replace(",", "").strip()
    m = re.search(r"([\d.]+)\s*(?:Cr|crore|lakh|million)?", raw, re.IGNORECASE)
    if not m:
        return None
    try:
        val = float(m.group(1))
        rest = raw[m.end():].lower() + raw[:m.start()].lower()
        if "lakh" in rest:
            return round(val / 100, 2)
        if "million" in rest:
            return round(val / 10, 2)
        return round(val, 2)
    except ValueError:
        return None


def _parse_shares(raw: str) -> int | None:
    """Parse Indian-format share count like '35,00,000' → 3500000.
    Strips commas (Indian number grouping: 35,00,000 = 3,500,000 Western = 3.5M).
    """
    # Remove everything except digits and commas, then strip commas
    num_str = re.sub(r"[^\d,]", "", (raw or "")).replace(",", "")
    if num_str:
        try:
            v = int(num_str)
            # Sanity: share count should be between 1,000 and 5 billion
            if 1_000 <= v <= 5_000_000_000:
                return v
        except ValueError:
            pass
    return None


def _parse_price_band(raw: str) -> tuple[int | None, int | None]:
    raw = re.sub(r"[₹Rs\.,]", "", raw or "").strip()
    m = re.search(r"(\d+)\s+to\s+(\d+)", raw, re.IGNORECASE)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 1 < lo <= hi < 100_000:
            return lo, hi
    m2 = re.search(r"(\d+)", raw)
    if m2:
        p = int(m2.group(1))
        if 1 < p < 100_000:
            return p, p
    return None, None


# ---------------------------------------------------------------------------
# Name normalisation for matching
# ---------------------------------------------------------------------------

_STRIP_WORDS = re.compile(
    r"\b(limited|ltd|pvt|private|co|company|inc|industries|technologies|"
    r"tech|solutions|services|ventures|enterprises|group|india|ipo)\b",
    re.IGNORECASE,
)


def _name_key(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = _STRIP_WORDS.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def _match_score(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def find_best_match(ipowatch_name: str, slugs_and_names: list[tuple[str, str]], min_score: float = 0.4) -> str | None:
    key = _name_key(ipowatch_name)
    best_slug, best_score = None, 0.0
    for slug, company_name in slugs_and_names:
        score = _match_score(key, _name_key(company_name))
        if score > best_score:
            best_score = score
            best_slug = slug
    return best_slug if best_score >= min_score else None


# ---------------------------------------------------------------------------
# Stage 1: Main listing page
# ---------------------------------------------------------------------------

def _scrape_listing(html: str) -> list[IpowatchRecord]:
    """Parse the /upcoming-ipo/ table → IpowatchRecord list with URLs."""
    records: list[IpowatchRecord] = []

    # Table rows with URL in company column:
    # <td class="column-1"><a href="URL">Name</a></td><td>Date</td><td>Size</td><td>Band</td>
    row_pat = re.compile(
        r"<tr[^>]*>\s*"
        r'<td[^>]*><a\s+href="([^"]+)"[^>]*>([^<]+)</a></td>'
        r"<td[^>]*>([^<]*)</td>"
        r"<td[^>]*>([^<]*)</td>"
        r"<td[^>]*>([^<]*)</td>",
        re.IGNORECASE | re.DOTALL,
    )

    for m in row_pat.finditer(html):
        page_url = m.group(1).strip()
        name_raw = m.group(2).strip()
        date_raw = m.group(3).strip()
        size_raw = m.group(4).strip()
        band_raw = m.group(5).strip()

        if not name_raw or name_raw.lower() in ("company", "ipo", "name"):
            continue

        open_iso, close_iso = _parse_date_range(date_raw)
        size_cr = _parse_crores(size_raw)
        lo, hi = _parse_price_band(band_raw)

        records.append(IpowatchRecord(
            name=name_raw,
            name_key=_name_key(name_raw),
            date_label=date_raw,
            page_url=page_url if "ipowatch.in" in page_url else None,
            subscription_open=open_iso,
            subscription_close=close_iso,
            issue_size_cr=size_cr,
            price_band_low=lo,
            price_band_high=hi,
        ))

    return records


# ---------------------------------------------------------------------------
# Stage 2: Individual company page parser
# ---------------------------------------------------------------------------

def _parse_key_value_table(html: str) -> dict[str, str]:
    """Extract all 2-column key→value table rows from an ipowatch company page."""
    kv: dict[str, str] = {}
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        if len(cells) >= 2:
            k = re.sub(r"<[^>]+>", "", cells[0]).replace("\xa0", " ").strip().rstrip(":").strip()
            v = re.sub(r"<[^>]+>", "", cells[1]).replace("\xa0", " ").strip()
            if k:
                kv[k] = v
    return kv


def _parse_financials(html: str) -> dict[str, Any]:
    """Extract financial tables (Revenue, Expense, PAT, Assets by year)."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    years: list[str] = []
    metrics: dict[str, list[float]] = {}

    in_fin_table = False
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        clean = [re.sub(r"<[^>]+>", " ", c).replace("\xa0", " ").strip() for c in cells]
        clean = [re.sub(r"\s+", " ", c).strip() for c in clean]

        if not clean:
            continue

        # Detect header row: Period Ended, Revenue, Expense, ...
        if clean[0].lower() in ("period ended", "period", "year"):
            in_fin_table = True
            continue

        if in_fin_table and clean[0]:
            # Check if it's a year row: starts with 4-digit year or "Dec YYYY" etc.
            year_m = re.match(r"(\d{4}|[A-Za-z]{3}\s+\d{4})", clean[0])
            if year_m and len(clean) >= 4:
                yr_label = clean[0]
                if yr_label not in years:
                    years.append(yr_label)
                # Columns: Period | Revenue | Expense | PAT | Assets
                for col_name, col_idx in [("revenue", 1), ("pat", 3), ("assets", 4)]:
                    raw_val = clean[col_idx] if len(clean) > col_idx else ""
                    # Strip ₹ and parse
                    num = re.sub(r"[₹,\s]", "", raw_val)
                    try:
                        val = float(num)
                        metrics.setdefault(col_name, []).append(val)
                    except ValueError:
                        metrics.setdefault(col_name, []).append(None)
            else:
                in_fin_table = False

    if years and metrics:
        return {"years": years, "metrics": metrics}
    return {}


def _parse_kpis(kv: dict[str, str]) -> dict[str, Any]:
    """Extract KPI values from key-value dict."""
    kpi_map = {
        "roe": "roe_pct",
        "roce": "roce_pct",
        "ebitda margin": "ebitda_margin_pct",
        "pat margin": "pat_margin_pct",
        "debt to equity": "debt_equity_ratio",
        "earning per share": "eps",
        "price/earning": "pe_ratio",
        "return on net worth": "ronw_pct",
        "net asset value": "nav",
    }
    result: dict[str, Any] = {}
    for k, v in kv.items():
        k_lower = k.lower()
        for key_fragment, field_name in kpi_map.items():
            if key_fragment in k_lower:
                num = re.sub(r"[₹%,\s]", "", v or "")
                try:
                    result[field_name] = float(num)
                except ValueError:
                    result[field_name] = v
    return result


def _scrape_company_detail(html: str, price_band_high: int | None = None) -> dict[str, Any]:
    """Parse an ipowatch company page into structured detail fields."""
    kv = _parse_key_value_table(html)
    result: dict[str, Any] = {}

    # Subscription dates (prefer detailed table over listing table)
    for k, v in kv.items():
        k_lower = k.lower()
        if "open date" in k_lower:
            d = _parse_iso(v)
            if d:
                result["subscription_open"] = d
        elif "close date" in k_lower:
            d = _parse_iso(v)
            if d:
                result["subscription_close"] = d
        elif "allotment" in k_lower or "basis of" in k_lower:
            d = _parse_iso(v)
            if d:
                result["allotment_date"] = d
        elif "listing date" in k_lower:
            d = _parse_iso(v)
            if d:
                result["listing_date"] = d
        elif "price band" in k_lower:
            lo, hi = _parse_price_band(v)
            if lo:
                result["price_band_low"] = lo
            if hi:
                result["price_band_high"] = hi
        elif "issue size" in k_lower and "fresh" not in k_lower and "offer" not in k_lower:
            cr = _parse_crores(v)
            if cr:
                result["issue_size_cr"] = cr
        elif "fresh issue" in k_lower:
            # "Approx ₹380 Crores, 2,23,52,941 Equity Shares"
            if any(w in v.lower() for w in ["crore", "cr.", " cr"]):
                cr = _parse_crores(v)
                if cr and cr > 0:
                    result["fresh_issue_cr"] = cr
            # else: if no crore mention, skip (might just be shares)
        elif "offer for sale" in k_lower:
            v_lower = v.lower()
            if any(w in v_lower for w in ["crore", "cr.", " cr"]):
                # Explicit crore amount
                cr = _parse_crores(v)
                if cr and cr > 0:
                    result["ofs_cr"] = cr
            elif any(w in v_lower for w in ["share", "equity"]):
                # Share count — convert to crores using price band
                shares = _parse_shares(v)
                if shares and shares > 0:
                    result["ofs_shares"] = shares
                    if price_band_high and price_band_high > 0:
                        result["ofs_cr"] = round(shares * price_band_high / 10_000_000, 2)
        elif "ipo listing" in k_lower and "date" not in k_lower:
            # Exchange info: "BSE, NSE" or "NSE SME"
            v_clean = v.strip()
            if "BSE" in v_clean and "NSE" in v_clean:
                result["exchange"] = "NSE + BSE"
            elif "NSE SME" in v_clean or "NSE Emerge" in v_clean:
                result["exchange"] = "NSE SME"
            elif "BSE SME" in v_clean:
                result["exchange"] = "BSE SME"
            elif "NSE" in v_clean:
                result["exchange"] = "NSE"
            elif "BSE" in v_clean:
                result["exchange"] = "BSE"
        elif "lot size" in k_lower or ("minimum" in k_lower and "retail" in k_lower):
            # Retail Minimum: lot=1, shares=88
            shares = _parse_shares(v)
            if shares:
                result["lot_size"] = shares
        elif k_lower == "retail minimum":
            # From lot size table: key="Retail Minimum", values=[lot, shares, amount]
            pass  # handled by shares parsing above

    # GMP — shown as "+₹25 (15%)" or "₹25" near the term
    gmp_pattern = re.compile(
        r"(?:GMP|Grey Market Premium)[^<]{0,200}?([+-]?\s*(?:₹|Rs\.?)\s*(\d+))",
        re.IGNORECASE | re.DOTALL,
    )
    gmp_m = gmp_pattern.search(html[:30000])
    if gmp_m:
        try:
            result["gmp"] = int(re.sub(r"[^\d-]", "", gmp_m.group(2)))
        except ValueError:
            pass

    # Also try explicit GMP table
    for k, v in kv.items():
        if "gmp" in k.lower() or "grey market" in k.lower():
            gmp_num = re.sub(r"[^\d-]", "", v or "")
            if gmp_num:
                try:
                    result["gmp"] = int(gmp_num)
                except ValueError:
                    pass

    # Lot size from lot-size table
    lot_rows = re.findall(
        r"Retail\s+Minimum.*?<td[^>]*>(\d+)</td>.*?<td[^>]*>([\d,]+)</td>",
        html, re.DOTALL | re.IGNORECASE
    )
    if lot_rows:
        try:
            result["lot_size"] = int(lot_rows[0][1].replace(",", ""))
        except ValueError:
            pass

    # Financials
    fins = _parse_financials(html)
    if fins:
        result["financials"] = fins

    # KPIs
    kpis = _parse_kpis(kv)
    if kpis:
        result["kpis"] = kpis

    return result


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def _get(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, headers=_HEADERS)
        return r.text if r.status_code == 200 else ""
    except Exception as exc:
        logger.debug("ipowatch fetch failed %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_ipowatch_data(*, include_details: bool = True) -> list[IpowatchRecord]:
    """Fetch and parse ipowatch IPO data.

    Stage 1: Main listing (price band, dates, size).
    Stage 2 (if include_details=True): Individual company pages for
             fresh/OFS, GMP, allotment/listing dates, financials, KPIs.
    """
    records: list[IpowatchRecord] = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
        # Stage 1
        html = await _get(client, _UPCOMING_URL)
        if html:
            records = _scrape_listing(html)
            logger.info("ipowatch stage-1: %d records", len(records))

        if not include_details or not records:
            return records

        # Stage 2: individual pages (concurrency=3 to be polite)
        sem = asyncio.Semaphore(3)

        async def _fetch_detail(rec: IpowatchRecord) -> None:
            if not rec.page_url:
                return
            async with sem:
                page_html = await _get(client, rec.page_url)
                await asyncio.sleep(0.5)
            if not page_html:
                return
            detail = _scrape_company_detail(
                page_html,
                price_band_high=rec.price_band_high,
            )
            # Merge detail into record
            if detail.get("subscription_open") and not rec.subscription_open:
                rec.subscription_open = detail["subscription_open"]
            if detail.get("subscription_close") and not rec.subscription_close:
                rec.subscription_close = detail["subscription_close"]
            if detail.get("price_band_low") and not rec.price_band_low:
                rec.price_band_low = detail["price_band_low"]
            if detail.get("price_band_high") and not rec.price_band_high:
                rec.price_band_high = detail["price_band_high"]
            if detail.get("issue_size_cr") and not rec.issue_size_cr:
                rec.issue_size_cr = detail["issue_size_cr"]
            if detail.get("fresh_issue_cr"):
                rec.fresh_issue_cr = detail["fresh_issue_cr"]
            if detail.get("ofs_cr"):
                rec.ofs_cr = detail["ofs_cr"]
            if detail.get("ofs_shares"):
                rec.ofs_shares = detail["ofs_shares"]
            if detail.get("gmp") is not None:
                rec.gmp = detail["gmp"]
            if detail.get("allotment_date"):
                rec.allotment_date = detail["allotment_date"]
            if detail.get("listing_date"):
                rec.listing_date = detail["listing_date"]
            if detail.get("lot_size"):
                rec.lot_size = detail["lot_size"]
            if detail.get("exchange"):
                rec.exchange = detail["exchange"]
            if detail.get("financials"):
                rec.financials = detail["financials"]
            if detail.get("kpis"):
                rec.kpis = detail["kpis"]

        await asyncio.gather(*[_fetch_detail(r) for r in records], return_exceptions=True)
        logger.info("ipowatch stage-2: detail pages scraped for %d records",
                    sum(1 for r in records if r.page_url))

    return records


def build_enrichment_map(
    records: list[IpowatchRecord],
    filings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Match ipowatch records to store filings by fuzzy name, return enrichment map.

    Sanity checks:
    - Requires name match score ≥ 0.4
    - If issue_size_cr already in store and ipowatch value differs by > 3x, skip size update
    """
    slugs_and_names = [(f.get("slug", ""), f.get("company_name", "")) for f in filings]
    # Build a quick lookup for existing store values
    slug_to_filing = {f.get("slug", ""): f for f in filings}
    result: dict[str, dict[str, Any]] = {}

    for rec in records:
        slug = find_best_match(rec.name, slugs_and_names)
        if not slug:
            continue

        existing = slug_to_filing.get(slug, {})
        e: dict[str, Any] = {}

        for field_name, val in [
            ("price_band_low", rec.price_band_low),
            ("price_band_high", rec.price_band_high),
            ("issue_size_cr", rec.issue_size_cr),
            ("fresh_issue_cr", rec.fresh_issue_cr),
            ("ofs_cr", rec.ofs_cr),
            ("subscription_open", rec.subscription_open),
            ("subscription_close", rec.subscription_close),
            ("gmp", rec.gmp),
            ("listing_date", rec.listing_date),
            ("allotment_date", rec.allotment_date),
            ("lot_size", rec.lot_size),
            ("exchange", rec.exchange),
        ]:
            if val is None:
                continue
            # Sanity: don't overwrite issue_size if existing value differs by > 3x
            if field_name == "issue_size_cr":
                existing_size = existing.get("issue_size_cr")
                if existing_size and existing_size > 0:
                    ratio = max(float(val), float(existing_size)) / min(float(val), float(existing_size))
                    if ratio > 5:  # > 5x difference → likely wrong match
                        logger.debug(
                            "Skipping issue_size_cr update for %s: ipowatch=%s existing=%s (ratio=%.1f)",
                            slug, val, existing_size, ratio
                        )
                        continue
            # Sanity: don't overwrite fresh_issue_cr if > issue_size (impossible)
            if field_name == "fresh_issue_cr":
                size = e.get("issue_size_cr") or existing.get("issue_size_cr")
                if size and float(val) > float(size) * 1.1:
                    logger.debug("Skipping fresh_issue_cr=%s for %s (> issue_size=%s)", val, slug, size)
                    continue
            e[field_name] = val

        if rec.financials:
            e["_financials"] = rec.financials
        if rec.kpis:
            e["_kpis"] = rec.kpis
        if e:
            result[slug] = e

    return result
