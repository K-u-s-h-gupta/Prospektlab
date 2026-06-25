"""Lightweight IPO cover-page parser using PyMuPDF.

Reads the first ~15 pages of a SEBI DRHP / RHP / Prospectus to extract
structured fields without running the heavy MinerU pipeline:

  • price_band_low / price_band_high (₹)
  • issue_size_cr  (total offer size in ₹ crores)
  • fresh_issue_cr / ofs_cr
  • subscription_open / subscription_close  (YYYY-MM-DD)
  • listing_date  (YYYY-MM-DD, Prospectus only)
  • face_value    (₹ per share)
  • exchange      (NSE / BSE / NSE + BSE)

All extraction is best-effort.  Fields that cannot be parsed are returned
as None so callers can decide how to handle them.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("finagent.tools.data.ipo_cover_parser")

_SEBI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Referer": "https://www.sebi.gov.in/",
}

# How many pages from the front of the document to scan (cover + summary + definitions)
_SCAN_PAGES = 20

# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------
_DATE_FMTS = (
    "%B %d, %Y",   # June 5, 2026
    "%B %d,%Y",    # June 5,2026
    "%d %B %Y",    # 5 June 2026
    "%d %B, %Y",   # 5 June, 2026
    "%d/%m/%Y",    # 05/06/2026
    "%d-%m-%Y",    # 05-06-2026
    "%Y-%m-%d",    # 2026-06-05
)

_MONTH_ABBR = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May",     "jun": "June",     "jul": "July",  "aug": "August",
    "sep": "September", "oct": "October", "nov": "November", "dec": "December",
}


def _parse_date(raw: str) -> str | None:
    """Parse a date string from a SEBI document into ISO format (YYYY-MM-DD)."""
    raw = re.sub(r"\s+", " ", (raw or "").strip()).strip(".,;*#")
    # Expand abbreviated month names
    for abbr, full in _MONTH_ABBR.items():
        raw = re.sub(rf"\b{abbr}\b", full, raw, flags=re.IGNORECASE)
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Amount parsing helpers (SEBI docs use both "million" and "crore" / "lakhs")
# ---------------------------------------------------------------------------

def _to_crores(amount_str: str, unit: str) -> float | None:
    """Convert a raw amount string + unit label to crores."""
    try:
        value = float(amount_str.replace(",", ""))
    except ValueError:
        return None
    unit_lower = unit.lower().strip()
    if "million" in unit_lower:
        return round(value / 10.0, 2)      # 1 crore = 10 million INR
    if "crore" in unit_lower or "cr" in unit_lower:
        return round(value, 2)
    if "lakh" in unit_lower:
        return round(value / 100.0, 2)     # 1 crore = 100 lakh
    return None


# ---------------------------------------------------------------------------
# Core regex patterns
# ---------------------------------------------------------------------------

# ── Price Band ─────────────────────────────────────────────────────────────

_PRICE_BAND_PATTERNS = [
    # "Price Band of a minimum price of ₹42 per … maximum price of ₹45"
    re.compile(
        r"price\s+band\s+of\s+a?\s*minimum\s+price\s+of\s+(?:rs\.?|₹)\s*([\d,]+)"
        r".*?maximum\s+price\s+of\s+(?:rs\.?|₹)\s*([\d,]+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "Floor Price: ₹42 … Cap Price: ₹45"
    re.compile(
        r"floor\s+price\s+(?:being\s+)?(?:rs\.?|₹)\s*([\d,]+).*?"
        r"cap\s+price\s+(?:being\s+)?(?:rs\.?|₹)\s*([\d,]+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "price band … ₹42 to ₹45"
    re.compile(
        r"price\s*band\b[^₹\n]{0,60}(?:rs\.?|₹)\s*([\d,]+)\s*(?:to|–|-)\s*(?:rs\.?|₹)\s*([\d,]+)",
        re.IGNORECASE,
    ),
    # "PRICE BAND: ₹ 42 TO ₹ 45"
    re.compile(
        r"price\s*band\s*[:\-–]\s*(?:rs\.?|₹)\s*([\d,]+)\s*(?:to|–|-)\s*(?:rs\.?|₹)\s*([\d,]+)",
        re.IGNORECASE,
    ),
]

_FLOOR_PRICE_PATTERN = re.compile(
    r"(?:floor\s+price|lower\s+end\s+of\s+the\s+price\s+band)[^₹\n]{0,60}(?:rs\.?|₹)\s*([\d,]+)", re.IGNORECASE
)
_CAP_PRICE_PATTERN = re.compile(
    r"(?:cap\s+price|higher\s+end\s+of\s+the\s+price\s+band)[^₹\n]{0,60}(?:rs\.?|₹)\s*([\d,]+)", re.IGNORECASE
)
_ISSUE_PRICE_PATTERN = re.compile(
    r"issue\s+price[^₹\n]{0,40}(?:rs\.?|₹)\s*([\d,]+)", re.IGNORECASE
)
_OFFER_PRICE_PATTERN = re.compile(
    r"offer\s+price[^₹\n]{0,40}(?:rs\.?|₹)\s*([\d,]+)", re.IGNORECASE
)

# ── Issue sizes ────────────────────────────────────────────────────────────

# "aggregating up to ₹ 3,800.00 million"  or  "aggregating to ₹ 380.00 crores"
_AGGREGATING_PATTERN = re.compile(
    r"aggregating(?:\s+up)?\s+to\s+(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(million|crore|lakh)",
    re.IGNORECASE,
)

# Specifically fresh issue or OFS with label
_FRESH_ISSUE_PATTERN = re.compile(
    r"fresh\s+issue[^₹\n]{0,60}(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(million|crore|lakh)",
    re.IGNORECASE,
)
_OFS_PATTERN = re.compile(
    r"offer\s+for\s+sale[^₹\n]{0,60}(?:rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(million|crore|lakh)",
    re.IGNORECASE,
)

# ── Subscription / Bid dates ───────────────────────────────────────────────

# Match "BID/OFFER OPENED ON\nJune 5, 2026" — note the value is often on the NEXT line
_OPENED_INLINE = re.compile(
    r"bid[/\s]*offer\s+opened?\s+on[:\s]+([A-Za-z]+\s+\d+[,.\s]+\d{4}|\d+\s+[A-Za-z]+[,.\s]+\d{4})",
    re.IGNORECASE,
)
_CLOSED_INLINE = re.compile(
    r"bid[/\s]*offer\s+clos(?:ed|es|ing)\s+on[:\s]+([A-Za-z]+\s+\d+[,.\s]+\d{4}|\d+\s+[A-Za-z]+[,.\s]+\d{4})",
    re.IGNORECASE,
)
# "Bid/Offer Opening Date ... being Friday, June 5, 2026"
_OPENING_DATE_PATTERN = re.compile(
    r"bid[/\s]*offer\s+opening\s+date[^,]{0,60},?\s*being[^,]{0,30},?\s*"
    r"([A-Za-z]+,?\s+[A-Za-z]+\s+\d+[,.\s]+\d{4}|[A-Za-z]+\s+\d+[,.\s]+\d{4})",
    re.IGNORECASE,
)
_CLOSING_DATE_PATTERN = re.compile(
    r"bid[/\s]*offer\s+closing\s+date[^,]{0,60},?\s*being[^,]{0,30},?\s*"
    r"([A-Za-z]+,?\s+[A-Za-z]+\s+\d+[,.\s]+\d{4}|[A-Za-z]+\s+\d+[,.\s]+\d{4})",
    re.IGNORECASE,
)
# "between June 5, 2026 and June 9, 2026"
_BID_PERIOD_PATTERN = re.compile(
    r"between\s+([A-Za-z]+\s+\d+[,\s]+\d{4})\s+and\s+([A-Za-z]+\s+\d+[,\s]+\d{4})",
    re.IGNORECASE,
)

# ── Listing / commencement of trading ──────────────────────────────────────

_TRADING_DATE_PATTERN = re.compile(
    r"commencement\s+of\s+trading[^A-Za-z\d]{0,30}([A-Za-z]+\s+\d+[,.\s]+\d{4}|\d+\s+[A-Za-z]+[,.\s]+\d{4})",
    re.IGNORECASE,
)
_LISTING_DATE_PATTERN = re.compile(
    r"(?:listing|listed|listed\s+on)[^A-Za-z\d]{0,30}([A-Za-z]+\s+\d+[,.\s]+\d{4}|\d+\s+[A-Za-z]+[,.\s]+\d{4})",
    re.IGNORECASE,
)

# ── Exchange ────────────────────────────────────────────────────────────────

_EXCHANGE_PATTERNS = [
    (re.compile(r"\bNSE\b.*?\bBSE\b|\bBSE\b.*?\bNSE\b", re.IGNORECASE), "NSE + BSE"),
    (re.compile(r"\bNational\s+Stock\s+Exchange\b.*?\bBSE\b|\bBSE\b.*?\bNational\s+Stock\s+Exchange\b", re.IGNORECASE), "NSE + BSE"),
    (re.compile(r"\bNSE\s+Emerge\b|\bNSE\s+SME\b", re.IGNORECASE), "NSE SME"),
    (re.compile(r"\bBSE\s+SME\b|\bBSE\s+Emerge\b", re.IGNORECASE), "BSE SME"),
    (re.compile(r"\bNational\s+Stock\s+Exchange\b|\bNSE\b", re.IGNORECASE), "NSE"),
    (re.compile(r"\bBombay\s+Stock\s+Exchange\b|\bBSE\b", re.IGNORECASE), "BSE"),
]

# ── Face value ──────────────────────────────────────────────────────────────

_FACE_VALUE_PATTERN = re.compile(
    r"face\s+value\s+of\s+(?:rs\.?|₹)\s*([\d.]+)\s*(?:each|per)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_text_fitz(pdf_bytes: bytes, max_pages: int = _SCAN_PAGES) -> str:
    """Extract plain text from the first N pages using PyMuPDF (fitz).
    Tolerates partial / truncated PDFs by opening with repair mode.
    """
    import fitz  # type: ignore[import]
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        # Try with repair on broken / partial downloads
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf", filetype_kwargs={"repair": True})
        except Exception:
            return ""
    pages = []
    for i in range(min(max_pages, doc.page_count)):
        try:
            pages.append(doc[i].get_text())
        except Exception:
            break
    doc.close()
    return "\n".join(pages)


async def _download_first_pages(url: str, *, timeout: float = 120.0) -> bytes:
    """Download a SEBI PDF with retry logic.  Downloads the complete file since PDF
    cross-reference tables live at the end and truncated files can't be parsed.
    """
    import asyncio as _asyncio

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, headers=_SEBI_HEADERS
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
                if len(content) > 500:   # sanity-check: must have some data
                    return content
        except Exception as exc:
            if attempt < 2:
                await _asyncio.sleep(5 * (attempt + 1))
                continue
            raise
    raise ValueError(f"Failed to download after 3 attempts: {url}")


# ---------------------------------------------------------------------------
# Individual field extractors  (operate on the full text blob)
# ---------------------------------------------------------------------------

def _extract_price_band(text: str) -> tuple[int | None, int | None]:
    """Return (floor, cap) price or (None, None)."""
    # Skip lines with [●] placeholder (RHPs before price announcement)
    text_clean = re.sub(r"\[●\]", " ", text)

    # Helper: check that a number is NOT immediately followed by "million/crore/lakh"
    # (which would indicate an aggregate amount, not a per-share price)
    def _is_per_share_amount(num_str: str, text_fragment: str, num_end_pos: int) -> bool:
        after = text_fragment[num_end_pos:num_end_pos + 30].lower()
        if re.search(r"\b(million|crore|cr\.|lakh)\b", after):
            return False
        try:
            n = int(num_str.replace(",", ""))
            return 1 < n < 10_000  # share price sanity check
        except ValueError:
            return False

    for pat in _PRICE_BAND_PATTERNS:
        m = pat.search(text_clean)
        if m:
            try:
                s1 = m.group(1).replace(",", "")
                s2 = m.group(2).replace(",", "")
                lo = int(s1)
                hi = int(s2)
                if 1 < lo < hi < 10_000:
                    return lo, hi
            except (ValueError, IndexError):
                continue

    # Try floor + cap separately and pair them
    floor_m = _FLOOR_PRICE_PATTERN.search(text_clean)
    cap_m = _CAP_PRICE_PATTERN.search(text_clean)
    if floor_m and cap_m:
        try:
            lo = int(floor_m.group(1).replace(",", ""))
            hi = int(cap_m.group(1).replace(",", ""))
            if 1 < lo < hi < 10_000:
                return lo, hi
        except ValueError:
            pass

    # Prospectus / fixed-price offer: single issue/offer price
    for pat in (_ISSUE_PRICE_PATTERN, _OFFER_PRICE_PATTERN):
        m = pat.search(text_clean)
        if m:
            try:
                num_str = m.group(1).replace(",", "")
                end_pos = m.end()
                if _is_per_share_amount(num_str, text_clean, end_pos):
                    price = int(num_str)
                    return price, price
            except ValueError:
                pass

    return None, None


def _extract_issue_sizes(text: str) -> dict[str, float | None]:
    """Return fresh_issue_cr, ofs_cr, issue_size_cr."""
    # Find all "aggregating … ₹X million/crore" occurrences in order
    amounts: list[float] = []
    for m in _AGGREGATING_PATTERN.finditer(text):
        cr = _to_crores(m.group(1), m.group(2))
        if cr and cr > 0:
            amounts.append(cr)

    fresh: float | None = None
    ofs: float | None = None

    # Try labelled patterns first
    fresh_m = _FRESH_ISSUE_PATTERN.search(text)
    if fresh_m:
        v = _to_crores(fresh_m.group(1), fresh_m.group(2))
        if v and v > 0:
            fresh = v

    ofs_m = _OFS_PATTERN.search(text)
    if ofs_m:
        v = _to_crores(ofs_m.group(1), ofs_m.group(2))
        if v and v > 0:
            ofs = v

    # If we only found one aggregating amount, try to assign it based on label context
    if not fresh and not ofs and amounts:
        # The first unique significant amount is likely the total issue size
        pass

    # The largest amount found is a good candidate for total issue size
    total: float | None = max(amounts) if amounts else None
    if fresh and not ofs and total and total > fresh:
        ofs = round(total - fresh, 2)
    elif ofs and not fresh and total and total > ofs:
        fresh = round(total - ofs, 2)

    # Compute total
    if fresh is not None and ofs is not None:
        total = round(fresh + ofs, 2)
    elif fresh is not None:
        total = fresh
    elif ofs is not None:
        total = ofs

    return {"fresh_issue_cr": fresh, "ofs_cr": ofs, "issue_size_cr": total}


def _extract_dates(text: str) -> dict[str, str | None]:
    """Extract subscription open/close and listing dates."""
    sub_open: str | None = None
    sub_close: str | None = None
    listing: str | None = None

    # Normalise text: collapse newlines that split date fields
    # "BID/OFFER OPENED ON\nJune 5, 2026" — join them
    collapsed = re.sub(r"(bid[/\s]*offer\s+\w+\s+on)\s*\n+\s*", r"\1 ", text, flags=re.IGNORECASE)

    # Inline patterns (single line)
    m = _OPENED_INLINE.search(collapsed)
    if m:
        sub_open = _parse_date(m.group(1))

    m = _CLOSED_INLINE.search(collapsed)
    if m:
        sub_close = _parse_date(m.group(1))

    # Definitions-style patterns
    if not sub_open:
        m = _OPENING_DATE_PATTERN.search(text)
        if m:
            sub_open = _parse_date(m.group(1))

    if not sub_close:
        m = _CLOSING_DATE_PATTERN.search(text)
        if m:
            sub_close = _parse_date(m.group(1))

    # "between June 5, 2026 and June 9, 2026"
    if not sub_open or not sub_close:
        m = _BID_PERIOD_PATTERN.search(text)
        if m:
            if not sub_open:
                sub_open = _parse_date(m.group(1))
            if not sub_close:
                sub_close = _parse_date(m.group(2))

    # Listing / commencement of trading
    for pat in (_TRADING_DATE_PATTERN, _LISTING_DATE_PATTERN):
        m = pat.search(text)
        if m:
            d = _parse_date(m.group(1))
            if d:
                listing = d
                break

    return {
        "subscription_open": sub_open,
        "subscription_close": sub_close,
        "listing_date": listing,
    }


def _extract_exchange(text: str) -> str | None:
    for pat, label in _EXCHANGE_PATTERNS:
        if pat.search(text[:5000]):  # Exchange is mentioned early
            return label
    return None


def _extract_face_value(text: str) -> float | None:
    m = _FACE_VALUE_PATTERN.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_ipo_cover(pdf_url: str, doc_type: str = "rhp") -> dict[str, Any]:
    """Download a SEBI document and return extracted structured fields.

    Returns a dict with fields that are non-None only when successfully parsed.
    """
    result: dict[str, Any] = {}
    try:
        pdf_bytes = await _download_first_pages(pdf_url, timeout=90.0)
        text = _extract_text_fitz(pdf_bytes, max_pages=_SCAN_PAGES)
    except Exception as exc:
        logger.warning("Cover parse failed for %s: %s", pdf_url[:60], exc)
        return result

    # Price band
    lo, hi = _extract_price_band(text)
    if lo is not None:
        result["price_band_low"] = lo
    if hi is not None:
        result["price_band_high"] = hi

    # Issue sizes
    sizes = _extract_issue_sizes(text)
    for k, v in sizes.items():
        if v is not None:
            result[k] = v

    # Dates
    dates = _extract_dates(text)
    for k, v in dates.items():
        if v is not None:
            result[k] = v

    # Exchange
    exch = _extract_exchange(text)
    if exch:
        result["exchange"] = exch

    # Face value (informational)
    fv = _extract_face_value(text)
    if fv is not None:
        result["face_value"] = fv

    logger.info(
        "Cover parsed %s (%s): price=%s-%s size_cr=%s open=%s close=%s",
        pdf_url.split("/")[-1],
        doc_type,
        lo, hi,
        sizes.get("issue_size_cr"),
        dates.get("subscription_open"),
        dates.get("subscription_close"),
    )
    return result


def parse_ipo_cover_sync(pdf_bytes: bytes, doc_type: str = "rhp") -> dict[str, Any]:
    """Synchronous version — pass pre-downloaded bytes."""
    result: dict[str, Any] = {}
    try:
        text = _extract_text_fitz(pdf_bytes, max_pages=_SCAN_PAGES)
    except Exception as exc:
        logger.warning("Cover parse failed (sync): %s", exc)
        return result

    lo, hi = _extract_price_band(text)
    if lo is not None:
        result["price_band_low"] = lo
    if hi is not None:
        result["price_band_high"] = hi

    sizes = _extract_issue_sizes(text)
    for k, v in sizes.items():
        if v is not None:
            result[k] = v

    dates = _extract_dates(text)
    for k, v in dates.items():
        if v is not None:
            result[k] = v

    exch = _extract_exchange(text)
    if exch:
        result["exchange"] = exch

    fv = _extract_face_value(text)
    if fv is not None:
        result["face_value"] = fv

    return result
