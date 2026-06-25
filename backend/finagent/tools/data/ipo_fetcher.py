"""IPO document discovery and download from SEBI official pages.

Tier 1 pipeline: watch SEBI Public Issues listing pages daily, download the
full DRHP/RHP/Prospectus PDFs from the SEBI detail pages to
``FINAGENT_HOME/drhp_cache/{company_slug}/{filing_date}.pdf``.

Sources:
  - DRHP: https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10
  - RHP:  https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=11
  - Prospectus: https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=12
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.tools.data.ipo_fetcher")

_SEBI_DRHP_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10"
_SEBI_RHP_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=11"
_SEBI_PROSPECTUS_URL = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=12"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sebi.gov.in/",
    "Origin": "https://www.sebi.gov.in",
}

# Skip document titles / PDF names containing these (case-insensitive).
_SKIP_TITLE_KEYWORDS = (
    "abridged",
    "addendum",
    "corrigendum",
    "revised",
    "supplementary",
    "errata",
    "draft abridged prospectus",
)

_DOC_TYPE_KEYWORDS = {
    "drhp": ("drhp", "draft red herring prospectus", "draft prospectus", "udrhp"),
    "rhp": ("rhp", "red herring prospectus"),
    "prospectus": ("prospectus", "final prospectus"),
}


@dataclass
class IpoFilingRecord:
    company_name: str
    slug: str
    doc_type: str
    filing_date: str
    pdf_url: str
    source: str
    exchange: str = "NSE"
    sector: str | None = None
    local_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def slugify_company(name: str) -> str:
    text = unescape(name or "").strip().lower()
    text = re.sub(r"\blimited\b|\bltd\.?\b|\bprivate\b|\bpvt\.?\b|\bcompany\b|\bco\.?\b", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or hashlib.md5(name.encode()).hexdigest()[:12]


def _parse_sebi_date(raw: str) -> str:
    raw = (raw or "").strip()
    # SEBI lists dates as "Jun 19, 2026"
    for fmt in ("%b %d, %Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return date.today().isoformat()


def _detect_doc_type(text: str) -> str:
    lower = (text or "").lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return doc_type
    return "drhp"


def _should_skip(text: str) -> bool:
    lower = (text or "").lower()
    return any(keyword in lower for keyword in _SKIP_TITLE_KEYWORDS)


def _clean_title(text: str) -> str:
    # Remove nested HTML and collapse whitespace
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    return text


def _document_title(title_attr: str) -> str:
    """Return the actual document title (before the embedded <br> PDF link)."""
    text = (title_attr or "").split("<br>")[0].split("<br/>")[0].split("<br />")[0]
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _extract_company_name(title: str) -> str:
    # Remove doc-type suffixes like "- DRHP", "- RHP", "- Prospectus" to get a clean company name
    text = _document_title(title)
    text = re.sub(r"\s*[-_]\s*(drhp|rhp|prospectus|final offer document|red herring)\b.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(udrhp\s*\d+)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text or text


async def _fetch_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers or _HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def _fetch_bytes(url: str, *, headers: dict[str, str] | None = None) -> bytes:
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True, headers=headers or _HEADERS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _extract_attribute(html: str, name: str) -> str | None:
    """Extract an HTML attribute value, handling both single and double quotes."""
    for quote in ('"', "'"):
        pattern = rf"\s{name}\s*=\s*{re.escape(quote)}(.*?){re.escape(quote)}"
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_rows_from_listing(html: str, base_url: str) -> list[tuple[str, str, str]]:
    """Return (date, title, detail_url) tuples from a SEBI listing page HTML."""
    rows: list[tuple[str, str, str]] = []
    # Each record is in a <tr role='row' class='odd'> block
    for tr_match in re.finditer(r"<tr[^>]*role=['\"]row['\"][^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL):
        tr = tr_match.group(1)
        date_match = re.search(r"<td[^>]*>([^<]+)</td>", tr)
        if not date_match:
            continue
        date_str = date_match.group(1).strip()

        # Extract href and title separately. SEBI uses double quotes for both; the title
        # value may contain HTML (<br>, <a>) but not unescaped double quotes, so a simple
        # non-greedy match up to the next double quote is sufficient.
        detail_url = _extract_attribute(tr, "href")
        title_attr = _extract_attribute(tr, "title")
        if not detail_url or not title_attr:
            continue

        detail_url = unescape(detail_url).strip()
        title_attr = unescape(title_attr).strip()
        detail_url = urljoin(base_url, detail_url)

        # Use the actual document title (before the embedded PDF link) for skip detection
        # and company name extraction. The embedded link text often contains "Abridged
        # Prospectus" even for the full DRHP/RHP document, so we must not skip based on it.
        doc_title = _document_title(title_attr)
        if not doc_title or _should_skip(doc_title):
            continue

        rows.append((date_str, title_attr, detail_url))
    return rows


def _extract_full_pdf_url(detail_html: str, base_url: str) -> str | None:
    """Extract the full PDF URL from the SEBI detail page.

    The full document is usually rendered in an iframe under sebi_data/attachdocs/.
    Fallback to the first .pdf link that is not an abridged/commondocs file.
    """
    # 1. Look for the iframe viewer that loads the full PDF from attachdocs
    iframe_match = re.search(
        r"<iframe[^>]*src=['\"]([^'\"]*\?file=([^'\"]+))['\"]",
        detail_html,
        flags=re.IGNORECASE,
    )
    if iframe_match:
        file_url = unquote(iframe_match.group(2)).strip()
        file_url = urljoin(base_url, file_url)
        if file_url.lower().endswith(".pdf") and not _should_skip(file_url):
            return file_url

    # 2. Fallback: any direct .pdf link in the page (prefer attachdocs over commondocs)
    pdf_links: list[str] = []
    for match in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', detail_html, flags=re.IGNORECASE):
        href = unescape(match.group(1)).strip()
        href = urljoin(base_url, href)
        if not _should_skip(href):
            pdf_links.append(href)

    # Prefer attachdocs (full document) over commondocs (abridged/prospectus)
    for link in pdf_links:
        if "/attachdocs/" in link:
            return link
    for link in pdf_links:
        if "/commondocs/" not in link:
            return link
    return pdf_links[0] if pdf_links else None


async def _scrape_sebi_page(url: str, doc_type: str, *, limit: int | None = None) -> list[IpoFilingRecord]:
    """Scrape a single SEBI listing page and resolve full PDF URLs via detail pages."""
    records: list[IpoFilingRecord] = []
    try:
        html = await _fetch_text(url)
    except Exception as exc:
        logger.warning("SEBI %s listing page scrape failed: %s", doc_type, exc)
        return records

    rows = _extract_rows_from_listing(html, url)
    seen: set[str] = set()

    for date_str, title, detail_url in rows:
        if detail_url in seen:
            continue
        seen.add(detail_url)

        filing_date = _parse_sebi_date(date_str)
        company_name = _extract_company_name(title)
        slug = slugify_company(company_name)

        # Resolve the full PDF from the detail page
        pdf_url = ""
        try:
            detail_html = await _fetch_text(detail_url)
            pdf_url = _extract_full_pdf_url(detail_html, detail_url) or ""
        except Exception as exc:
            logger.warning("Failed to resolve PDF for %s: %s", company_name, exc)

        if not pdf_url or _should_skip(pdf_url):
            logger.debug("Skipping %s: resolved PDF is abridged/addendum/corrigendum", company_name)
            continue

        records.append(
            IpoFilingRecord(
                company_name=company_name,
                slug=slug,
                doc_type=doc_type,
                filing_date=filing_date,
                pdf_url=pdf_url,
                source="sebi",
                exchange="NSE",
                metadata={"sebi_detail_url": detail_url, "sebi_title": title},
            )
        )
        if limit is not None and len(records) >= limit:
            break

    return records


async def scrape_sebi_drhp(limit: int = 3) -> list[IpoFilingRecord]:
    """Scrape SEBI DRHP listing page.

    Top 2-3 most recent filings are returned for the upcoming IPO radar.
    """
    return await _scrape_sebi_page(_SEBI_DRHP_URL, "drhp", limit=limit)


async def scrape_sebi_rhp(limit: int = 50) -> list[IpoFilingRecord]:
    """Scrape SEBI RHP listing page."""
    return await _scrape_sebi_page(_SEBI_RHP_URL, "rhp", limit=limit)


async def scrape_sebi_prospectus(limit: int = 50) -> list[IpoFilingRecord]:
    """Scrape SEBI Prospectus listing page."""
    return await _scrape_sebi_page(_SEBI_PROSPECTUS_URL, "prospectus", limit=limit)


def drhp_cache_dir(company_slug: str) -> Path:
    return finagent_data_path("drhp_cache", company_slug)


async def download_drhp(record: IpoFilingRecord, *, force: bool = False) -> IpoFilingRecord:
    """Download a DRHP/RHP/Prospectus PDF to the local cache."""
    cache_dir = drhp_cache_dir(record.slug)
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{record.filing_date}_{record.doc_type}.pdf"
    target = cache_dir / filename
    if target.exists() and not force:
        record.local_path = str(target)
        return record

    content = await _fetch_bytes(record.pdf_url)
    if not content.startswith(b"%PDF"):
        raise ValueError(f"Downloaded content is not a PDF: {record.pdf_url}")
    target.write_bytes(content)
    record.local_path = str(target)
    logger.info("Cached SEBI IPO PDF: %s -> %s", record.company_name, target)
    return record


async def discover_new_filings(*, drhp_limit: int = 3, rhp_limit: int = 50, prospectus_limit: int = 50) -> list[IpoFilingRecord]:
    """Run SEBI watchers and dedupe by slug + doc_type + filing_date.

    DRHP is intentionally limited to the top N most recent filings so only the
    freshest upcoming IPOs appear on the radar.
    """
    batches = await asyncio.gather(
        scrape_sebi_drhp(limit=drhp_limit),
        scrape_sebi_rhp(limit=rhp_limit),
        scrape_sebi_prospectus(limit=prospectus_limit),
        return_exceptions=True,
    )
    merged: dict[str, IpoFilingRecord] = {}
    for batch in batches:
        if isinstance(batch, Exception):
            logger.warning("SEBI watcher batch failed: %s", batch)
            continue
        for record in batch:
            key = f"{record.slug}:{record.doc_type}:{record.filing_date}"
            merged.setdefault(key, record)
    return list(merged.values())


async def run_daily_watcher(*, download: bool = True, drhp_limit: int = 3, rhp_limit: int = 50, prospectus_limit: int = 50) -> dict[str, Any]:
    """Tier-1 daily watcher: discover and optionally download new SEBI filings."""
    records = await discover_new_filings(
        drhp_limit=drhp_limit,
        rhp_limit=rhp_limit,
        prospectus_limit=prospectus_limit,
    )
    downloaded: list[str] = []
    errors: list[dict[str, str]] = []
    if download:
        for record in records:
            try:
                await download_drhp(record)
                if record.local_path:
                    downloaded.append(record.local_path)
            except Exception as exc:
                errors.append({"company": record.company_name, "error": str(exc)})

    return {
        "discovered": len(records),
        "downloaded": len(downloaded),
        "records": [record.__dict__ for record in records],
        "errors": errors,
        "as_of": datetime.utcnow().isoformat() + "Z",
    }


def load_cached_pdf(slug: str, filing_date: str | None = None, doc_type: str = "drhp") -> Path | None:
    cache_dir = drhp_cache_dir(slug)
    if not cache_dir.exists():
        return None
    if filing_date:
        candidate = cache_dir / f"{filing_date}_{doc_type}.pdf"
        if candidate.exists():
            return candidate
    pdfs = sorted(cache_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pdfs[0] if pdfs else None
