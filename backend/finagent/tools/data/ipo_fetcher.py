"""IPO document discovery and download (SEBI, BSE, NSE).

Tier 1 pipeline: watch regulatory indexes daily, download new DRHP/RHP PDFs to
``FINAGENT_HOME/drhp_cache/{company_slug}/{filing_date}.pdf``.
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
from urllib.parse import urljoin, urlparse

import httpx

from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.tools.data.ipo_fetcher")

_SEBI_PUBLIC_ISSUES_URL = "https://www.sebi.gov.in/filings/public-issues.html"
_BSE_PUBLIC_ISSUES_URL = "https://www.bseindia.com/markets/publicIssues/publicIssues.aspx"
_NSE_PUBLIC_ISSUES_URL = "https://www.nseindia.com/market-data/new-public-issues"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_NSE_HEADERS = {
    **_HEADERS,
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}
_BSE_HEADERS = {
    **_HEADERS,
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

_DOC_TYPE_KEYWORDS = {
    "drhp": ("drhp", "draft red herring prospectus", "draft prospectus"),
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


def _parse_date(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%b %d, %Y"):
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


def _extract_pdf_links(html: str, base_url: str) -> list[tuple[str, str, str]]:
    """Return (company_hint, date_hint, pdf_url) tuples from HTML."""
    rows: list[tuple[str, str, str]] = []
    for match in re.finditer(
        r'href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)<',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        href = unescape(match.group(1)).strip()
        label = re.sub(r"<[^>]+>", " ", match.group(2))
        label = unescape(re.sub(r"\s+", " ", label)).strip()
        pdf_url = urljoin(base_url, href)
        date_hint = ""
        date_match = re.search(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}-[A-Za-z]{3}-\d{4})\b", label)
        if date_match:
            date_hint = date_match.group(1)
        company_hint = re.sub(r"\b(drhp|rhp|prospectus|pdf)\b", "", label, flags=re.IGNORECASE).strip(" -")
        rows.append((company_hint or label or "Unknown Company", date_hint, pdf_url))
    return rows


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


async def scrape_sebi_public_issues(limit: int = 50) -> list[IpoFilingRecord]:
    """Scrape SEBI Public Issues page for DRHP/RHP PDF links."""
    records: list[IpoFilingRecord] = []
    try:
        html = await _fetch_text(_SEBI_PUBLIC_ISSUES_URL, headers={**_HEADERS, "Referer": "https://www.sebi.gov.in/"})
    except Exception as exc:
        logger.warning("SEBI public issues scrape failed: %s", exc)
        return records

    seen: set[str] = set()
    for company_hint, date_hint, pdf_url in _extract_pdf_links(html, _SEBI_PUBLIC_ISSUES_URL):
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        company_name = company_hint or "Unknown Company"
        doc_type = _detect_doc_type(f"{company_name} {pdf_url}")
        records.append(
            IpoFilingRecord(
                company_name=company_name,
                slug=slugify_company(company_name),
                doc_type=doc_type,
                filing_date=_parse_date(date_hint),
                pdf_url=pdf_url,
                source="sebi",
                exchange="NSE",
            )
        )
        if len(records) >= limit:
            break
    return records


async def scrape_bse_public_issues(limit: int = 50) -> list[IpoFilingRecord]:
    records: list[IpoFilingRecord] = []
    try:
        html = await _fetch_text(_BSE_PUBLIC_ISSUES_URL, headers=_BSE_HEADERS)
    except Exception as exc:
        logger.warning("BSE public issues scrape failed: %s", exc)
        return records

    seen: set[str] = set()
    for company_hint, date_hint, pdf_url in _extract_pdf_links(html, _BSE_PUBLIC_ISSUES_URL):
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        company_name = company_hint or "Unknown Company"
        exchange = "BSE SME" if "sme" in html.lower() or "sme" in company_name.lower() else "BSE"
        records.append(
            IpoFilingRecord(
                company_name=company_name,
                slug=slugify_company(company_name),
                doc_type=_detect_doc_type(f"{company_name} {pdf_url}"),
                filing_date=_parse_date(date_hint),
                pdf_url=pdf_url,
                source="bse",
                exchange=exchange,
            )
        )
        if len(records) >= limit:
            break
    return records


async def scrape_nse_public_issues(limit: int = 50) -> list[IpoFilingRecord]:
    records: list[IpoFilingRecord] = []
    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=_NSE_HEADERS) as client:
            await client.get("https://www.nseindia.com/")
            response = await client.get(_NSE_PUBLIC_ISSUES_URL)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("NSE public issues scrape failed: %s", exc)
        return records

    items = payload if isinstance(payload, list) else payload.get("data") or payload.get("issues") or []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        company_name = (
            item.get("companyName")
            or item.get("company")
            or item.get("symbol")
            or item.get("issuerName")
            or "Unknown Company"
        )
        pdf_url = item.get("drhpLink") or item.get("rhpLink") or item.get("prospectusLink") or item.get("link") or ""
        if not pdf_url:
            continue
        records.append(
            IpoFilingRecord(
                company_name=str(company_name),
                slug=slugify_company(str(company_name)),
                doc_type=_detect_doc_type(str(pdf_url) + " " + str(item.get("issueType", ""))),
                filing_date=_parse_date(str(item.get("issueStartDate") or item.get("filedDate") or "")),
                pdf_url=str(pdf_url),
                source="nse",
                exchange="NSE Emerge" if "emerge" in str(item.get("series", "")).lower() else "NSE",
                metadata={"raw": item},
            )
        )
    return records


def drhp_cache_dir(company_slug: str) -> Path:
    return finagent_data_path("drhp_cache", company_slug)


async def download_drhp(record: IpoFilingRecord, *, force: bool = False) -> IpoFilingRecord:
    """Download a DRHP/RHP PDF to the local cache."""
    cache_dir = drhp_cache_dir(record.slug)
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{record.filing_date}_{record.doc_type}.pdf"
    target = cache_dir / filename
    if target.exists() and not force:
        record.local_path = str(target)
        return record

    headers = _BSE_HEADERS if "bse" in record.source else _HEADERS
    content = await _fetch_bytes(record.pdf_url, headers=headers)
    if not content.startswith(b"%PDF"):
        raise ValueError(f"Downloaded content is not a PDF: {record.pdf_url}")
    target.write_bytes(content)
    record.local_path = str(target)
    logger.info("Cached DRHP PDF: %s -> %s", record.company_name, target)
    return record


async def discover_new_filings(*, limit_per_source: int = 50) -> list[IpoFilingRecord]:
    """Run all regulatory watchers and dedupe by slug + doc_type + filing_date."""
    batches = await asyncio.gather(
        scrape_sebi_public_issues(limit=limit_per_source),
        scrape_bse_public_issues(limit=limit_per_source),
        scrape_nse_public_issues(limit=limit_per_source),
        return_exceptions=True,
    )
    merged: dict[str, IpoFilingRecord] = {}
    for batch in batches:
        if isinstance(batch, Exception):
            logger.warning("IPO watcher batch failed: %s", batch)
            continue
        for record in batch:
            key = f"{record.slug}:{record.doc_type}:{record.filing_date}"
            merged.setdefault(key, record)
    return list(merged.values())


async def run_daily_watcher(*, download: bool = True, limit_per_source: int = 50) -> dict[str, Any]:
    """Tier-1 daily watcher: discover and optionally download new filings."""
    records = await discover_new_filings(limit_per_source=limit_per_source)
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
