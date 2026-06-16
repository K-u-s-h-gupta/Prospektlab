"""Annual Reports Pipeline — download, extract, and index annual reports.

Downloads annual reports from BSE corporate filings, extracts structured
data using Azure Document Intelligence, and indexes content for GraphRAG.

Source: BSE corporate filings page
        https://www.bseindia.com/corporates/annualdisplay.aspx?scripcd={scrip_code}

Pipeline:
  1. For each Nifty 500 company, fetch latest annual report PDF link from BSE
  2. Download PDF
  3. Extract text + tables via Azure Document Intelligence
  4. Store extracted data in document store for GraphRAG indexing
  5. Index key financial tables in IKG

Schedule: Annual (after AGM season, typically Oct-Nov)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.document_selector import (
    build_document_sections_from_extraction,
    extract_pdf_page_previews,
    select_useful_annual_report_pages,
)
from finagent.ikg.scrapers._engine import run_async

logger = logging.getLogger("finagent.ikg.scrapers.annual_reports")

_BSE_ANNUAL_REPORT_URLS = [
    (
    "https://www.bseindia.com/corporates/annualdisplay.aspx?scripcd={scrip_code}"
    ),
    (
        "https://www.bseindia.com/corporates/Annual_Reports.aspx?scripcode={scrip_code}"
    ),
    (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={scrip_code}"
    ),
    (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport/w?scripcode={scrip_code}"
    ),
]
_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/html, application/json, */*",
    "Referer": "https://www.bseindia.com/",
}
_BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_REPORT_CACHE_DIR = Path(os.getenv("FINAGENT_REPORT_CACHE_DIR", "cache/annual_reports"))
_REQUEST_DELAY_S = 3.0
_PARSER_VERSION = "bse_annual_reports_v2"
_DEFAULT_MAX_WORKERS = 4
_DEFAULT_REPORTS_PER_COMPANY = 3
_DEFAULT_EXTRACT_MODE = "metadata_only"
_ANNUAL_REQUIRE_TABLES = os.getenv("FINAGENT_ANNUAL_REPORT_REQUIRE_TABLES", "0").strip().lower() in {"1", "true", "yes", "on"}
_ANNUAL_BOOTSTRAP_LOCK = threading.Lock()
_ANNUAL_BOOTSTRAPPED_URLS: set[str] = set()


def _response_looks_like_pdf(*, content: bytes, content_type: str = "", content_disposition: str = "", response_url: str = "") -> bool:
    payload = (content or b"").lstrip()
    if payload.startswith(b"%PDF"):
        return True
    haystack = " ".join(part for part in [str(content_type or ""), str(content_disposition or "")] if part).lower()
    if "pdf" in haystack:
        return True
    return str(response_url or "").lower().endswith(".pdf")

_ANNUAL_REPORT_STAGING_SQL = """
create table if not exists annual_reports_raw (
    id                      bigserial primary key,
    report_uid              varchar(32) not null unique,
    scrip_code              varchar(10) not null,
    cin                     varchar(21),
    nse_symbol              varchar(20),
    company_name            varchar(500),
    report_year             varchar(20) not null,
    pdf_url                 text not null,
    pdf_local_path          text,
    source_url              text,
    parser_version          varchar(80) default 'bse_annual_reports_v2',
    extraction_status       varchar(30) not null default 'pending',
    extraction_error        text,
    full_text               text,
    full_text_length        integer default 0,
    tables_markdown         text,
    tables_count            integer default 0,
    kv_pairs_count          integer default 0,
    page_count              integer default 0,
    extracted_model         varchar(120),
    extraction_duration_s   numeric(12,3),
    raw_json                jsonb default '{}'::jsonb,
    fetched_at              timestamptz default now(),
    updated_at              timestamptz default now(),
    unique (scrip_code, report_year, pdf_url)
);
create index if not exists idx_annual_reports_raw_cin on annual_reports_raw(cin);
create index if not exists idx_annual_reports_raw_symbol on annual_reports_raw(nse_symbol, fetched_at desc);
create index if not exists idx_annual_reports_raw_scrip on annual_reports_raw(scrip_code, fetched_at desc);
create index if not exists idx_annual_reports_raw_year on annual_reports_raw(report_year);
create index if not exists idx_annual_reports_raw_status on annual_reports_raw(extraction_status, fetched_at desc);
create index if not exists idx_annual_reports_raw_fetched on annual_reports_raw(fetched_at desc);

create table if not exists annual_report_chunks (
    id                      bigserial primary key,
    report_uid              varchar(32) not null references annual_reports_raw(report_uid) on delete cascade,
    chunk_index             integer not null,
    total_chunks            integer default 0,
    chunk_id                varchar(64),
    chunk_text              text not null,
    char_count              integer default 0,
    source_file             text,
    source_type             varchar(40) default 'annual_report',
    metadata                jsonb default '{}'::jsonb,
    fetched_at              timestamptz default now(),
    unique (report_uid, chunk_index)
);
create index if not exists idx_annual_report_chunks_report on annual_report_chunks(report_uid, chunk_index);

create table if not exists document_sections (
    id                      bigserial primary key,
    document_uid            varchar(80) not null,
    source_table            varchar(80) not null,
    source_uid              varchar(80) not null,
    document_type           varchar(80) not null,
    section_type            varchar(120) not null,
    title                   text,
    page_start              integer,
    page_end                integer,
    text                    text,
    text_length             integer default 0,
    tables_markdown         text,
    confidence              numeric(4,3) default 0.800,
    source_url              text,
    metadata                jsonb default '{}'::jsonb,
    fetched_at              timestamptz default now(),
    updated_at              timestamptz default now(),
    unique (document_uid, section_type, page_start, page_end)
);
create index if not exists idx_document_sections_doc
    on document_sections(document_uid, page_start);
create index if not exists idx_document_sections_type
    on document_sections(document_type, section_type);
create index if not exists idx_document_sections_metadata
    on document_sections using gin (metadata);
"""


def _annual_report_uid(scrip_code: str, year: str, pdf_url: str) -> str:
    raw = f"{(scrip_code or '').strip()}|{(year or '').strip()}|{(pdf_url or '').strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _ensure_annual_report_tables(database_url: str) -> None:
    with _ANNUAL_BOOTSTRAP_LOCK:
        if database_url in _ANNUAL_BOOTSTRAPPED_URLS:
            return
        with connect_postgres(database_url, connect_timeout=20) as conn:
            with conn.cursor() as cur:
                cur.execute(_ANNUAL_REPORT_STAGING_SQL)
            conn.commit()
        _ANNUAL_BOOTSTRAPPED_URLS.add(database_url)


def _store_annual_report_result(
    *,
    scrip_code: str,
    cin: str | None,
    nse_symbol: str | None,
    company_name: str | None,
    year: str,
    pdf_url: str,
    source_url: str | None,
    file_path: Path | None,
    result: dict[str, Any],
    database_url: str | None,
) -> bool:
    db_url = get_database_url(database_url)
    if not db_url:
        return False

    report_uid = _annual_report_uid(scrip_code, year, pdf_url)
    extraction_status = str(
        result.get("extraction_status")
        or ("ok" if not result.get("error") and result.get("indexed") else "failed")
    )
    chunks = result.get("chunks") or []
    if not isinstance(chunks, list):
        chunks = []
    sections = result.get("sections") or []
    if not isinstance(sections, list):
        sections = []

    try:
        _ensure_annual_report_tables(db_url)
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into annual_reports_raw (
                      report_uid, scrip_code, cin, nse_symbol, company_name, report_year,
                      pdf_url, pdf_local_path, source_url, parser_version,
                      extraction_status, extraction_error, full_text, full_text_length,
                      tables_markdown, tables_count, kv_pairs_count, page_count,
                      extracted_model, extraction_duration_s, raw_json, fetched_at, updated_at
                    )
                    values (
                      %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s::jsonb, now(), now()
                    )
                    on conflict (scrip_code, report_year, pdf_url) do update set
                      cin = excluded.cin,
                      nse_symbol = excluded.nse_symbol,
                      company_name = excluded.company_name,
                      pdf_local_path = excluded.pdf_local_path,
                      source_url = excluded.source_url,
                      parser_version = excluded.parser_version,
                      extraction_status = excluded.extraction_status,
                      extraction_error = excluded.extraction_error,
                      full_text = excluded.full_text,
                      full_text_length = excluded.full_text_length,
                      tables_markdown = excluded.tables_markdown,
                      tables_count = excluded.tables_count,
                      kv_pairs_count = excluded.kv_pairs_count,
                      page_count = excluded.page_count,
                      extracted_model = excluded.extracted_model,
                      extraction_duration_s = excluded.extraction_duration_s,
                      raw_json = excluded.raw_json,
                      fetched_at = now(),
                      updated_at = now()
                    returning report_uid
                    """,
                    (
                        report_uid,
                        scrip_code,
                        cin,
                        nse_symbol,
                        company_name,
                        year,
                        pdf_url,
                        str(file_path or ""),
                        source_url,
                        _PARSER_VERSION,
                        extraction_status,
                        result.get("error"),
                        result.get("full_text") or "",
                        int(result.get("full_text_length") or 0),
                        result.get("tables_markdown") or "",
                        int(result.get("tables_count") or 0),
                        int(result.get("kv_pairs_count") or 0),
                        int(result.get("page_count") or 0),
                        result.get("model_used"),
                        float(result.get("extraction_duration_s") or 0.0),
                        json.dumps({
                            "scrip_code": scrip_code,
                            "year": year,
                            "pdf_url": pdf_url,
                            "source_url": source_url,
                            "chunks_indexed": int(result.get("chunks_indexed") or 0),
                            "sections_stored": len(sections),
                            "selected_pages": result.get("selected_pages") or "",
                            "selection_reasons": result.get("selection_reasons") or [],
                        }),
                    ),
                )
                row = cur.fetchone()
                effective_uid = str((row or [report_uid])[0] or report_uid)

                cur.execute("delete from annual_report_chunks where report_uid = %s", (effective_uid,))
                for idx, chunk in enumerate(chunks):
                    if not isinstance(chunk, dict):
                        continue
                    chunk_text = str(chunk.get("text") or "").strip()
                    if not chunk_text:
                        continue
                    cur.execute(
                        """
                        insert into annual_report_chunks (
                          report_uid, chunk_index, total_chunks, chunk_id, chunk_text,
                          char_count, source_file, source_type, metadata, fetched_at
                        )
                        values (
                          %s, %s, %s, %s, %s,
                          %s, %s, %s, %s::jsonb, now()
                        )
                        on conflict (report_uid, chunk_index) do update set
                          total_chunks = excluded.total_chunks,
                          chunk_id = excluded.chunk_id,
                          chunk_text = excluded.chunk_text,
                          char_count = excluded.char_count,
                          source_file = excluded.source_file,
                          source_type = excluded.source_type,
                          metadata = excluded.metadata,
                          fetched_at = now()
                        """,
                        (
                            effective_uid,
                            int(chunk.get("chunk_index", idx)),
                            int(chunk.get("total_chunks") or len(chunks)),
                            str(chunk.get("chunk_id") or ""),
                            chunk_text,
                            len(chunk_text),
                            str(chunk.get("source_file") or ""),
                            str(chunk.get("source_type") or "annual_report"),
                            json.dumps(chunk.get("metadata") or {}),
                        ),
                    )
                cur.execute(
                    "delete from document_sections where source_table = %s and source_uid = %s",
                    ("annual_reports_raw", effective_uid),
                )
                for section in sections:
                    if not isinstance(section, dict):
                        continue
                    section_text = str(section.get("text") or "").strip()
                    tables_markdown = str(section.get("tables_markdown") or "").strip()
                    if not section_text and not tables_markdown:
                        continue
                    doc_uid = str(section.get("document_uid") or f"annual:{effective_uid}")
                    cur.execute(
                        """
                        insert into document_sections (
                          document_uid, source_table, source_uid, document_type,
                          section_type, title, page_start, page_end, text,
                          text_length, tables_markdown, confidence, source_url,
                          metadata, fetched_at, updated_at
                        )
                        values (
                          %s, %s, %s, %s,
                          %s, %s, %s, %s, %s,
                          %s, %s, %s, %s,
                          %s::jsonb, now(), now()
                        )
                        on conflict (document_uid, section_type, page_start, page_end)
                        do update set
                          title = excluded.title,
                          text = excluded.text,
                          text_length = excluded.text_length,
                          tables_markdown = excluded.tables_markdown,
                          confidence = excluded.confidence,
                          source_url = excluded.source_url,
                          metadata = excluded.metadata,
                          updated_at = now()
                        """,
                        (
                            doc_uid,
                            "annual_reports_raw",
                            effective_uid,
                            str(section.get("document_type") or "annual_report"),
                            str(section.get("section_type") or "annual_report_selected"),
                            str(section.get("title") or ""),
                            int(section.get("page_start") or 0),
                            int(section.get("page_end") or 0),
                            section_text,
                            int(section.get("text_length") or len(section_text)),
                            tables_markdown,
                            float(section.get("confidence") or 0.8),
                            section.get("source_url") or source_url,
                            json.dumps(section.get("metadata") or {}),
                        ),
                    )
            conn.commit()
        return True
    except Exception as exc:
        logger.warning("Annual report DB store failed for %s/%s: %s", scrip_code, year, exc)
        return False


def _annual_extract_mode() -> str:
    mode = os.getenv("FINAGENT_ANNUAL_REPORT_EXTRACT_MODE", _DEFAULT_EXTRACT_MODE).strip().lower()
    if mode in {"all", "full", "extract_all"}:
        return "all"
    if mode in {"metadata", "metadata_only", "links_only"}:
        return "metadata_only"
    if mode in {"off", "none", "disabled"}:
        return "metadata_only"
    if mode in {"priority", "priority_only"}:
        return "priority_only"
    if mode in {"targeted_top100_mcap", "top100_mcap", "market_cap_top100", "targeted_mcap"}:
        return "targeted_top100_mcap"
    if mode in {"targeted", "targeted_only", "essential", "useful", "sections_only"}:
        return "targeted"
    return "metadata_only"


def _annual_reports_years_back(default: int = 8) -> int:
    raw = (os.getenv("FINAGENT_ANNUAL_REPORT_YEARS_BACK") or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid FINAGENT_ANNUAL_REPORT_YEARS_BACK=%r; using default=%d", raw, default)
        return default


def _metric_number(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value") or value.get("raw") or value.get("amount")
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1.0
    lowered = text.lower()
    if "lakh" in lowered:
        multiplier = 100_000
    elif "crore" in lowered or "cr" in lowered:
        multiplier = 10_000_000
    elif "billion" in lowered:
        multiplier = 1_000_000_000
    elif "million" in lowered:
        multiplier = 1_000_000
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) * multiplier if match else 0.0


def _load_top_market_cap_symbols(database_url: str | None, limit: int) -> set[str]:
    db_url = get_database_url(database_url)
    if not db_url or limit <= 0:
        return set()
    try:
        with connect_postgres(db_url, connect_timeout=20) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select nse_symbol, validated_metrics_json
                    from company_financials
                    where nse_symbol is not null
                    """
                )
                rows = cur.fetchall()
        ranked: list[tuple[float, str]] = []
        for symbol, metrics in rows:
            if isinstance(metrics, str):
                try:
                    metrics = json.loads(metrics)
                except Exception:
                    metrics = {}
            if not isinstance(metrics, dict):
                continue
            market_cap = (
                metrics.get("market_cap")
                or metrics.get("marketCap")
                or metrics.get("market_cap_inr")
                or metrics.get("mcap")
            )
            value = _metric_number(market_cap)
            if value > 0 and symbol:
                ranked.append((value, str(symbol).strip().upper()))
        ranked.sort(reverse=True)
        selected = {symbol for _, symbol in ranked[:limit]}
        logger.info("Annual-report market-cap target set loaded: requested=%d selected=%d", limit, len(selected))
        return selected
    except Exception as exc:
        logger.warning("Annual-report top market-cap selector unavailable: %s", exc)
        return set()


def _should_extract_annual_report(
    company_index: int,
    *,
    company: dict[str, Any] | None = None,
    top_market_cap_symbols: set[str] | None = None,
) -> bool:
    mode = _annual_extract_mode()
    if mode == "metadata_only":
        return False
    if mode in {"all", "targeted"}:
        return True
    if mode == "targeted_top100_mcap":
        symbol = str((company or {}).get("nse_symbol") or "").strip().upper()
        return bool(symbol and top_market_cap_symbols and symbol in top_market_cap_symbols)
    priority_limit = max(0, int(os.getenv("FINAGENT_ANNUAL_REPORT_PRIORITY_LIMIT", "50")))
    return company_index <= priority_limit


def _parse_exchange_datetime(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    for pattern in (
        r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b",
        r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b",
    ):
        match = re.search(pattern, value)
        if not match:
            continue
        parts = match.groups()
        if len(parts[0]) == 4:
            return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        return f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
    year_match = re.search(r"\b(20\d{2})\b", value)
    return year_match.group(1) if year_match else ""


def _annual_report_year(*parts: str) -> str:
    haystack = " ".join(part for part in parts if part)
    patterns = (
        r"(20\d{2})\s*[-/]\s*(\d{2})",
        r"(?:FY|Financial Year|F\.Y\.?)\s*[-:]?\s*(20\d{2})\s*[-/]\s*(\d{2})",
        r"\b(20\d{2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, haystack, flags=re.I)
        if match:
            if len(match.groups()) >= 2:
                return f"{match.group(1)}-{match.group(2)}"
            return match.group(1)
    return "unknown"


def _is_annual_report_announcement(*parts: str) -> bool:
    haystack = " ".join(part for part in parts if part).lower()
    return any(
        phrase in haystack
        for phrase in (
            "annual report",
            "regulation 34",
            "reg 34",
            "notice of annual general meeting",
            "notice of agm",
            "agm notice",
        )
    )


def _strip_html_tags(text: str) -> str:
    normalized = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(normalized.split())


def _normalize_bse_attachment_url(raw_url: str) -> str:
    cleaned = (raw_url or "").strip().replace("\\", "/")
    if not cleaned:
        return ""
    if cleaned.startswith(("http://", "https://", "/", "//")):
        return cleaned
    if cleaned.lower().endswith(".pdf"):
        return f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{cleaned.lstrip('/')}"
    return cleaned


class _PdfLinkParser(HTMLParser):
    def __init__(self, source_url: str) -> None:
        super().__init__()
        self.source_url = source_url
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        href = attrs_dict.get("href", "").strip()
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join(" ".join(self._text).split()) or "Annual Report"
        url = urljoin(self.source_url, self._href)
        haystack = f"{title} {url}".lower()
        if ".pdf" in haystack or "annual" in haystack:
            self.links.append({"title": title, "url": url})
        self._href = None
        self._text = []


def sanitize_annual_report_pdf_url(raw_url: str, source_url: str) -> str:
    """Normalize and validate annual report PDF URLs from BSE payloads."""
    cleaned = (raw_url or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("\\", "")
    cleaned = cleaned.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.strip()
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    base = "https://www.bseindia.com/"
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        resolved = cleaned
    else:
        resolved = urljoin(base, cleaned)
    try:
        parsed = httpx.URL(resolved)
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    candidate_url = str(parsed).lower()
    if ".pdf" not in candidate_url and ".pdf" not in parsed.path.lower():
        source_haystack = " ".join(part for part in [str(source_url or ""), candidate_url] if part).lower()
        if not any(domain in source_haystack for domain in ("bseindia.com", "nseindia.com")):
            return ""
    return str(parsed)


def fetch_annual_report_links(
    scrip_code: str,
    timeout_s: float = 30.0,
) -> list[dict[str, Any]]:
    """Fetch annual report download links from BSE.

    Args:
        scrip_code: BSE scrip code.
        timeout_s: Request timeout.

    Returns:
        List of report dicts with: year, pdf_url, title
    """
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            for url_template in _BSE_ANNUAL_REPORT_URLS:
                url = url_template.format(scrip_code=scrip_code)
                resp = client.get(url, headers=_BSE_HEADERS)
                if resp.status_code != 200:
                    continue
                content_type = resp.headers.get("content-type", "").lower()
                if "json" in content_type or resp.text.lstrip().startswith(("{", "[")):
                    reports = _parse_bse_annual_report_json(resp.json(), scrip_code, source_url=url)
                else:
                    reports = _parse_bse_annual_report_page(resp.text, scrip_code, source_url=url)
                if reports:
                    return reports
        return fetch_annual_report_links_from_bse_announcements(
            scrip_code,
            years_back=_annual_reports_years_back(),
            timeout_s=timeout_s,
        )

    except Exception as exc:
        logger.debug("BSE annual report fetch failed for %s: %s", scrip_code, exc)
        return fetch_annual_report_links_from_bse_announcements(
            scrip_code,
            years_back=_annual_reports_years_back(),
            timeout_s=timeout_s,
        )


def fetch_annual_report_links_from_bse_announcements(
    scrip_code: str,
    *,
    years_back: int = 3,
    max_pages: int | None = None,
    timeout_s: float = 30.0,
) -> list[dict[str, Any]]:
    """Discover annual report PDFs from official BSE corporate announcements."""
    today = time.strftime("%Y%m%d", time.gmtime())
    since_year = int(time.strftime("%Y", time.gmtime())) - max(1, years_back)
    since = f"{since_year}0101"
    pages = max(1, int(max_pages or os.getenv("FINAGENT_ANNUAL_REPORT_BSE_ANNOUNCEMENT_PAGES", "4")))
    reports: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            for page_no in range(1, pages + 1):
                params = {
                    "pageno": str(page_no),
                    "strCat": "-1",
                    "strPrevDate": since,
                    "strScrip": str(scrip_code),
                    "strSearch": "P",
                    "strToDate": today,
                    "strType": "C",
                    "subcategory": "-1",
                }
                resp = client.get(_BSE_ANNOUNCEMENTS_URL, headers=_BSE_HEADERS, params=params)
                if resp.status_code != 200:
                    logger.debug(
                        "BSE annual report announcements returned %s for %s page %d",
                        resp.status_code,
                        scrip_code,
                        page_no,
                    )
                    break
                payload = resp.json()
                rows = payload.get("Table") if isinstance(payload, dict) else None
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    title = _strip_html_tags(str(row.get("NEWSSUB") or row.get("HEADLINE") or "")).strip()
                    description = _strip_html_tags(str(row.get("MORE") or row.get("MORETEXT") or "")).strip()
                    category = str(row.get("CATEGORYNAME") or row.get("SUBCATNAME") or "")
                    raw_url = _normalize_bse_attachment_url(str(row.get("ATTACHMENTNAME") or row.get("NSURL") or "").strip())
                    if not raw_url or not _is_annual_report_announcement(title, description, category, raw_url):
                        continue
                    pdf_url = sanitize_annual_report_pdf_url(raw_url, _BSE_ANNOUNCEMENTS_URL)
                    if not pdf_url or pdf_url in seen_urls:
                        continue
                    seen_urls.add(pdf_url)
                    announced = _parse_exchange_datetime(str(row.get("DT_TM") or row.get("NEWS_DT") or ""))
                    reports.append({
                        "scrip_code": scrip_code,
                        "year": _annual_report_year(title, description, announced),
                        "pdf_url": pdf_url,
                        "title": title or "Annual Report",
                        "source_url": _BSE_ANNOUNCEMENTS_URL,
                        "announced_at": announced,
                        "parser_version": _PARSER_VERSION,
                    })
                if len(rows) < 50:
                    break
        return reports
    except Exception as exc:
        logger.debug("BSE annual report announcement fetch failed for %s: %s", scrip_code, exc)
        return []


def fetch_annual_report_links_from_nse_announcements(
    symbol: str,
    *,
    years_back: int | None = None,
) -> list[dict[str, Any]]:
    """Fallback annual-report discovery from NSE corporate filings."""
    years = max(1, int(years_back or _annual_reports_years_back()))
    try:
        from finagent.ikg.scrapers.sebi_corporate_filings import fetch_nse_corporate_filings

        reports: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for row in fetch_nse_corporate_filings(symbol, years_back=years):
            title = str(row.get("title") or "")
            description = str(row.get("description") or "")
            attachment_url = str(row.get("attachment_url") or "")
            if not attachment_url or attachment_url in seen_urls:
                continue
            if not _is_annual_report_announcement(title, description, "", attachment_url):
                continue
            seen_urls.add(attachment_url)
            announced = _parse_exchange_datetime(str(row.get("announced_at") or ""))
            reports.append(
                {
                    "scrip_code": str(row.get("scrip_code") or ""),
                    "year": _annual_report_year(title, description, announced),
                    "pdf_url": sanitize_annual_report_pdf_url(attachment_url, "https://www.nseindia.com/") or attachment_url,
                    "title": title or "Annual Report",
                    "source_url": str(row.get("source_url") or ""),
                    "announced_at": announced,
                    "parser_version": f"{_PARSER_VERSION}_nse_fallback",
                }
            )
        return reports
    except Exception as exc:
        logger.debug("NSE annual report fallback failed for %s: %s", symbol, exc)
        return []


def _parse_bse_annual_report_page(
    html: str,
    scrip_code: str,
    source_url: str = "https://www.bseindia.com",
) -> list[dict[str, Any]]:
    """Parse BSE annual report listing page for PDF links.

    BSE embeds PDF links in anchor tags within a table. We extract them with regex
    since BeautifulSoup may not be available.
    """
    import re

    reports = []
    # Find PDF links in the page
    pdf_pattern = re.compile(r'href="([^"]*\.pdf[^"]*)"', re.I)
    year_pattern = re.compile(r"(20\d{2}[-–]\d{2}|20\d{2}|FY\d{2})", re.I)

    for match in pdf_pattern.finditer(html):
        pdf_url = match.group(1).strip()
        pdf_url = sanitize_annual_report_pdf_url(pdf_url, source_url)
        if not pdf_url:
            continue

        # Try to extract year from surrounding context
        context_start = max(0, match.start() - 200)
        context = html[context_start : match.end() + 100]
        year_match = year_pattern.search(context)
        year = year_match.group(1) if year_match else "unknown"

        # Extract title from surrounding text
        title_match = re.search(r">([^<]+)<", context)
        title = title_match.group(1).strip() if title_match else "Annual Report"

        reports.append({
            "scrip_code": scrip_code,
            "year": year,
            "pdf_url": pdf_url,
            "title": title,
            "source_url": source_url,
            "parser_version": _PARSER_VERSION,
        })

    return reports


def _parse_bse_annual_report_json(
    data: Any,
    scrip_code: str,
    source_url: str,
) -> list[dict[str, Any]]:
    """Parse JSON-shaped BSE annual report responses."""
    reports: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        rows = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                rows.extend(item for item in value if isinstance(item, dict))

    year_pattern = re.compile(r"(20\d{2}[-/]\d{2}|20\d{2}|FY\d{2})", re.I)
    for row in rows:
        raw_url = str(
            row.get("pdf_url")
            or row.get("PDFDownload")
            or row.get("PDFURL")
            or row.get("Attachment")
            or row.get("URL")
            or row.get("url")
            or ""
        ).strip()
        if not raw_url:
            continue
        pdf_url = sanitize_annual_report_pdf_url(raw_url, source_url)
        if not pdf_url:
            continue
        title = str(row.get("title") or row.get("Title") or row.get("Description") or "Annual Report").strip()
        context = " ".join(str(v) for v in row.values())
        year_match = year_pattern.search(context)
        reports.append({
            "scrip_code": scrip_code,
            "year": year_match.group(1) if year_match else "unknown",
            "pdf_url": pdf_url,
            "title": title,
            "source_url": source_url,
            "parser_version": _PARSER_VERSION,
        })
    return reports


def download_annual_report(
    pdf_url: str,
    scrip_code: str,
    year: str = "latest",
    timeout_s: float = 120.0,
) -> Path | None:
    """Download an annual report PDF to the local cache.

    Args:
        pdf_url: Direct URL to the PDF.
        scrip_code: BSE scrip code (for cache directory naming).
        year: Report year (for filename).
        timeout_s: Download timeout.

    Returns:
        Path to the downloaded file, or None on failure.
    """
    cache_dir = _REPORT_CACHE_DIR / scrip_code
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"annual_report_{scrip_code}_{year}.pdf"
    filepath = cache_dir / filename

    # Skip if already cached
    if filepath.exists() and filepath.stat().st_size > 10000:
        logger.info("Annual report already cached: %s", filepath)
        return filepath

    try:
        normalized_url = sanitize_annual_report_pdf_url(pdf_url, "https://www.bseindia.com/")
        if not normalized_url:
            logger.warning("Annual report URL rejected by validator: %s", pdf_url)
            return None
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            resp = client.get(normalized_url, headers=_BSE_HEADERS)
            resp.raise_for_status()
            content_type = (resp.headers.get("content-type") or "").lower()
            content_disposition = (resp.headers.get("content-disposition") or "").lower()
            response_url = str(resp.url or normalized_url)
            if not _response_looks_like_pdf(
                content=resp.content or b"",
                content_type=content_type,
                content_disposition=content_disposition,
                response_url=response_url,
            ):
                logger.warning("Annual report URL did not return PDF content: %s", normalized_url)
                return None

        filepath.write_bytes(resp.content)
        logger.info("Downloaded annual report: %s (%d bytes)", filepath, len(resp.content))
        return filepath

    except Exception as exc:
        logger.warning("Annual report download failed for %s: %s", pdf_url[:100], exc)
        return None


async def process_annual_report(
    file_path: Path,
    scrip_code: str,
    cin: str | None = None,
    year: str = "latest",
    pdf_url: str | None = None,
    source_url: str | None = None,
    company_ticker: str | None = None,
    company_name: str | None = None,
    extract_mode: str | None = None,
) -> dict[str, Any]:
    """Extract and process an annual report using Document Intelligence.

    Args:
        file_path: Path to the downloaded PDF.
        scrip_code: BSE scrip code.
        cin: Company CIN.
        year: Report year.

    Returns:
        dict with: full_text, tables_count, kv_pairs_count, indexed
    """
    from finagent.ingestion.azure_doc_intel import extract_annual_report

    result: dict[str, Any] = {
        "scrip_code": scrip_code,
        "cin": cin,
        "year": year,
        "pdf_url": pdf_url,
        "source_url": source_url,
        "full_text_length": 0,
        "tables_count": 0,
        "kv_pairs_count": 0,
        "chunks_indexed": 0,
        "chunks": [],
        "full_text": "",
        "tables_markdown": "",
        "indexed": False,
        "sections": [],
        "selected_pages": "",
        "selection_reasons": [],
        "error": None,
    }

    try:
        mode = (extract_mode or _annual_extract_mode()).strip().lower()
        selection = None
        selected_pages = None
        if mode in {"targeted", "priority_only", "targeted_top100_mcap"}:
            previews = extract_pdf_page_previews(
                file_path,
                max_pages=int(os.getenv("FINAGENT_ANNUAL_REPORT_PREVIEW_MAX_PAGES", "350")),
            )
            selection = select_useful_annual_report_pages(
                previews,
                min_score=int(os.getenv("FINAGENT_ANNUAL_REPORT_SECTION_MIN_SCORE", "3")),
                context_pages=int(os.getenv("FINAGENT_ANNUAL_REPORT_SECTION_CONTEXT_PAGES", "1")),
                max_selected_pages=int(os.getenv("FINAGENT_ANNUAL_REPORT_MAX_SELECTED_PAGES", "80")),
            )
            selected_pages = selection.page_ranges
            result["selected_pages"] = selected_pages
            result["selection_reasons"] = [
                {
                    "page": page.page_number,
                    "score": page.score,
                    "categories": list(page.categories),
                    "reasons": list(page.reasons),
                    "table_like": page.table_like,
                }
                for page in selection.selected_pages
                if page.score > 0
            ]
            if not selected_pages:
                logger.warning(
                    "No useful annual-report pages selected from local preview for %s/%s; "
                    "falling back to full-document extraction",
                    scrip_code,
                    year,
                )
                selection = None
                selected_pages = None
                result["selected_pages"] = ""
                result["selection_reasons"] = []
            scanned_pages = int(getattr(selection, "total_pages", 0) or 0)
            logger.info(
                "Annual report targeted extraction selected pages: scrip=%s year=%s pages=%s scanned=%d",
                scrip_code,
                year,
                selected_pages,
                scanned_pages,
            )

        di_result = await extract_annual_report(
            file_path,
            pages=selected_pages,
            extract_financial_tables=_ANNUAL_REQUIRE_TABLES,
            allow_fallback=True,
        )
        result["full_text_length"] = len(di_result.full_text)
        result["tables_count"] = len(di_result.tables)
        result["kv_pairs_count"] = len(di_result.key_value_pairs)
        result["page_count"] = di_result.page_count
        result["model_used"] = di_result.model_used
        result["extraction_duration_s"] = di_result.duration_s
        result["extraction_status"] = "targeted" if selected_pages else "ok"

        # Store extracted text for GraphRAG indexing
        text_cache_dir = _REPORT_CACHE_DIR / scrip_code / "extracted"
        text_cache_dir.mkdir(parents=True, exist_ok=True)

        # Save full text
        text_file = text_cache_dir / f"text_{year}.txt"
        text_file.write_text(di_result.full_text, encoding="utf-8")
        result["full_text"] = di_result.full_text

        # Save tables as markdown
        if di_result.tables:
            tables_file = text_cache_dir / f"tables_{year}.md"
            tables_file.write_text(di_result.tables_markdown, encoding="utf-8")
            result["tables_markdown"] = di_result.tables_markdown

        if selection is not None:
            report_uid = _annual_report_uid(scrip_code, year, pdf_url or "")
            result["sections"] = build_document_sections_from_extraction(
                document_uid=f"annual:{report_uid}",
                document_type="annual_report",
                source_url=source_url or pdf_url,
                selection=selection,
                extracted_pages=di_result.pages,
                tables=di_result.tables,
                company_cin=cin,
                company_symbol=company_ticker,
                company_scrip_code=scrip_code,
                company_name=company_name,
            )

        # Chunk + cache for GraphRAG usage.
        try:
            from finagent.graphrag.indexer import index_document, store_chunks_to_cache

            chunks = index_document(
                di_result.full_text,
                source_file=str(file_path),
                source_type="annual_report",
                company_cin=cin,
                company_ticker=company_ticker or scrip_code,
            )
            if chunks:
                store_chunks_to_cache(chunks, str(company_ticker or scrip_code or "UNKNOWN"))
                result["chunks"] = [chunk.to_dict() for chunk in chunks]
                result["chunks_indexed"] = len(chunks)
        except Exception as exc:
            logger.warning("Annual report GraphRAG indexing failed for %s/%s: %s", scrip_code, year, exc)

        result["indexed"] = True
        logger.info(
            "Processed annual report %s/%s: %d pages, %d tables, %d chars, %d chunks",
            scrip_code,
            year,
            di_result.page_count,
            len(di_result.tables),
            len(di_result.full_text),
                int(result.get("chunks_indexed") or 0),
        )

    except Exception as exc:
        result["error"] = str(exc)
        logger.error("Annual report processing failed for %s/%s: %s", scrip_code, year, exc)

    return result


def run_annual_report_pipeline(
    companies: list[dict[str, Any]],
    database_url: str | None = None,
    max_companies: int | None = None,
    reports_per_company: int | None = None,
) -> dict[str, Any]:
    """Full annual report pipeline: fetch links → download → extract → index.

    Args:
        companies: List of company dicts with bse_scrip_code, cin.
        database_url: PostgreSQL connection string.
        max_companies: Limit for testing.

    Returns:
        dict with: companies_processed, reports_downloaded, reports_indexed,
        reports_persisted, chunks_indexed, errors
    """
    companies_subset = companies[:max_companies] if max_companies else companies
    max_reports = max(
        1,
        int(
            reports_per_company
            if reports_per_company is not None
            else os.getenv("FINAGENT_ANNUAL_REPORTS_PER_COMPANY", str(_DEFAULT_REPORTS_PER_COMPANY))
        ),
    )
    workers = max(
        1,
        int(os.getenv("FINAGENT_ANNUAL_REPORT_MAX_WORKERS", str(_DEFAULT_MAX_WORKERS))),
    )
    top_market_cap_symbols: set[str] = set()
    if _annual_extract_mode() == "targeted_top100_mcap":
        target_limit = max(1, int(os.getenv("FINAGENT_ANNUAL_REPORT_TARGETED_TOP_N", "100")))
        top_market_cap_symbols = _load_top_market_cap_symbols(database_url, target_limit)
        if not top_market_cap_symbols:
            logger.warning(
                "Annual report mode targeted_top100_mcap is active, but no market-cap ranking was found. "
                "Annual reports will be stored as metadata only until company_financials has market_cap values."
            )

    def _process_company(co: dict[str, Any], company_index: int) -> dict[str, int]:
        scrip_code = str(co.get("bse_scrip_code") or "")
        cin = co.get("cin")
        nse_symbol = str(co.get("nse_symbol") or "").strip().upper() or None
        company_name = str(co.get("company_name") or "").strip() or None
        should_extract = _should_extract_annual_report(
            company_index,
            company=co,
            top_market_cap_symbols=top_market_cap_symbols,
        )
        if not scrip_code:
            return {
                "companies_processed": 0,
                "reports_found": 0,
                "reports_downloaded": 0,
                "reports_indexed": 0,
                "reports_persisted": 0,
                "chunks_indexed": 0,
                "errors": 0,
            }

        time.sleep(_REQUEST_DELAY_S)
        links = fetch_annual_report_links(scrip_code)
        if not links and nse_symbol:
            links = fetch_annual_report_links_from_nse_announcements(nse_symbol)
        reports_found_local = len(links)
        reports_downloaded_local = 0
        reports_indexed_local = 0
        reports_persisted_local = 0
        chunks_indexed_local = 0
        errors_local = 0
        if not links:
            logger.warning(
                "Annual report metadata fetch returned no official links: company=%d scrip=%s symbol=%s cin=%s",
                company_index,
                scrip_code,
                nse_symbol or "-",
                cin or "-",
            )
            errors_local += 1

        # Keep one report per year, newest first.
        selected: list[dict[str, Any]] = []
        seen_years: set[str] = set()
        for link in links:
            year = str(link.get("year") or "unknown")
            if year in seen_years:
                continue
            seen_years.add(year)
            selected.append(link)
            if len(selected) >= max_reports:
                break

        for report in selected:
            if not should_extract:
                result = {
                    "scrip_code": scrip_code,
                    "cin": cin,
                    "year": report.get("year", "latest"),
                    "pdf_url": report.get("pdf_url"),
                    "source_url": report.get("source_url"),
                    "full_text_length": 0,
                    "tables_count": 0,
                    "kv_pairs_count": 0,
                    "chunks_indexed": 0,
                    "chunks": [],
                    "full_text": "",
                    "tables_markdown": "",
                    "indexed": False,
                    "error": None,
                    "extraction_status": "metadata_only",
                }
                stored = _store_annual_report_result(
                    scrip_code=scrip_code,
                    cin=cin,
                    nse_symbol=nse_symbol,
                    company_name=company_name,
                    year=str(report.get("year", "latest")),
                    pdf_url=str(report.get("pdf_url") or ""),
                    source_url=report.get("source_url"),
                    file_path=None,
                    result=result,
                    database_url=database_url,
                )
                if stored:
                    reports_persisted_local += 1
                    logger.info(
                        "Annual report metadata stored: company=%d scrip=%s year=%s mode=%s",
                        company_index,
                        scrip_code,
                        report.get("year", "latest"),
                        _annual_extract_mode(),
                    )
                else:
                    errors_local += 1
                continue

            downloaded = download_annual_report(
                report["pdf_url"],
                scrip_code,
                year=report.get("year", "latest"),
            )
            if not downloaded:
                continue

            reports_downloaded_local += 1
            try:
                result = run_async(
                    process_annual_report(
                        downloaded,
                        scrip_code,
                        cin=cin,
                        year=report.get("year", "latest"),
                        pdf_url=report.get("pdf_url"),
                        source_url=report.get("source_url"),
                        company_ticker=nse_symbol,
                        company_name=company_name,
                        extract_mode=_annual_extract_mode(),
                    )
                )
                if result.get("indexed"):
                    reports_indexed_local += 1
                    chunks_indexed_local += int(result.get("chunks_indexed") or 0)
                stored = _store_annual_report_result(
                    scrip_code=scrip_code,
                    cin=cin,
                    nse_symbol=nse_symbol,
                    company_name=company_name,
                    year=str(report.get("year", "latest")),
                    pdf_url=str(report.get("pdf_url") or ""),
                    source_url=report.get("source_url"),
                    file_path=downloaded,
                    result=result,
                    database_url=database_url,
                )
                if stored:
                    reports_persisted_local += 1
                else:
                    errors_local += 1
                    logger.warning(
                        "Annual report staging write failed for %s/%s (%s)",
                        scrip_code,
                        report.get("year", "latest"),
                        report.get("pdf_url"),
                    )
                if result.get("error"):
                    errors_local += 1
            except Exception as exc:
                logger.warning("Annual report processing failed for %s: %s", scrip_code, exc)
                errors_local += 1

        return {
            "companies_processed": 1,
            "reports_found": reports_found_local,
            "reports_downloaded": reports_downloaded_local,
            "reports_indexed": reports_indexed_local,
            "reports_persisted": reports_persisted_local,
            "chunks_indexed": chunks_indexed_local,
            "errors": errors_local,
        }

    companies_processed = 0
    reports_found = 0
    reports_downloaded = 0
    reports_indexed = 0
    reports_persisted = 0
    chunks_indexed = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(companies_subset)))) as executor:
        futures = {
            executor.submit(_process_company, co, idx): co
            for idx, co in enumerate(companies_subset, start=1)
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            try:
                stats = future.result()
            except Exception as exc:
                logger.warning("Annual report worker failed: %s", exc)
                errors += 1
                continue

            companies_processed += int(stats.get("companies_processed") or 0)
            reports_found += int(stats.get("reports_found") or 0)
            reports_downloaded += int(stats.get("reports_downloaded") or 0)
            reports_indexed += int(stats.get("reports_indexed") or 0)
            reports_persisted += int(stats.get("reports_persisted") or 0)
            chunks_indexed += int(stats.get("chunks_indexed") or 0)
            errors += int(stats.get("errors") or 0)

            if idx % 25 == 0:
                logger.info(
                    "Annual reports progress: %d/%d companies, %d downloaded, %d indexed",
                    idx, len(companies_subset), reports_downloaded, reports_indexed,
                )

    return {
        "companies_processed": companies_processed,
        "reports_found": reports_found,
        "reports_downloaded": reports_downloaded,
        "reports_indexed": reports_indexed,
        "reports_persisted": reports_persisted,
        "chunks_indexed": chunks_indexed,
        "errors": errors,
    }
