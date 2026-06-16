"""SEBI corporate filing navigation map scraper."""

from __future__ import annotations

import html
import hashlib
import json
import logging
import os
import re
import tempfile
import zipfile
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from finagent.ingestion.pdf_transformer import document_to_markdown
from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._doc_extract import (
    decode_text_bytes,
    extract_pdf_text_local,
    text_is_sufficient,
)
from finagent.ikg.scrapers._engine import run_async, sync_get
from finagent.ikg.scrapers._nse_session import apply_nse_cookies, should_skip_nse_home_visit
from finagent.ikg.scrapers.xbrl_utils import (
    extract_corporate_action_from_text,
    is_probable_xbrl,
    parse_xbrl_facts,
    summarize_xbrl_facts,
)

logger = logging.getLogger("finagent.ikg.scrapers.sebi_corporate_filings")

_SEBI_CORPORATE_FILING_URL = "https://www.sebi.gov.in/curation/corporate_filings.html"
_SEBI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.sebi.gov.in/",
}
_PARSER_VERSION = "sebi_corporate_filings_v2"
_DOCUMENT_PARSER_VERSION = "corporate_filings_documents_v1"
_XBRL_PARSER_VERSION = "corporate_xbrl_v1"
_ATTACHMENT_TIMEOUT_S = float(os.getenv("FINAGENT_CORP_FILINGS_ATTACHMENT_TIMEOUT_S", "120"))
_ATTACHMENT_LOCAL_MIN_CHARS = int(os.getenv("FINAGENT_CORP_FILINGS_LOCAL_MIN_CHARS", "1200") or "1200")
_DEFAULT_ATTACHMENT_EXTRACT_LIMIT = "25"
_DEFAULT_ATTACHMENT_HYDRATE_LIMIT = "250"
_NSE_BASE_URL = "https://www.nseindia.com"
_NSE_CORPORATE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
_BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}
_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.bseindia.com/corporates/ann.html",
    "Origin": "https://www.bseindia.com",
}

_BSE_CATEGORY_URLS: dict[str, str] = {
    "corporate_governance": "https://www.bseindia.com/corporates/corporate-governance-by-quarter",
    "shareholding_pattern": "https://www.bseindia.com/corporates/Sharehold_Searchnew",
    "brsr": "https://www.bseindia.com/corporates/xbrlBrsrDetails",
    "financial_results": "https://www.bseindia.com/corporates/financials-results",
    "investor_complaints": "https://www.bseindia.com/corporates/investorComplaint",
    "voting_results": "https://www.bseindia.com/corporates/VotingResults",
    "related_party_transactions": "https://www.bseindia.com/corporates/xbrlRelatedPartyTrans",
    "secretarial_compliance": "https://www.bseindia.com/corporates/xbrlAscrDetails",
    "insider_trading": "https://www.bseindia.com/corporates/insiderTrading",
    "corporate_actions": "https://www.bseindia.com/corporates/corporate_act.aspx",
}

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "corporate_governance": ("corporate governance", "governance", "board meeting", "board of directors"),
    "shareholding_pattern": ("shareholding pattern", "share holding", "shareholding"),
    "brsr": ("business responsibility", "sustainability report", "brsr", "sustainability"),
    "financial_results": ("financial result", "financial results", "regulation 33", "audited financial", "unaudited financial"),
    "investor_complaints": ("investor complaint", "grievance", "statement of investor complaints"),
    "voting_results": ("voting result", "voting results", "scrutinizer", "remote e-voting", "evoting"),
    "related_party_transactions": ("related party", "rpt", "regulation 23"),
    "secretarial_compliance": ("secretarial compliance", "regulation 24a"),
    "insider_trading": ("insider trading", "pit", "trading window", "sast", "promoter encumbrance"),
    "corporate_actions": (
        "corporate action",
        "bonus issue",
        "bonus share",
        "stock split",
        "split/sub-division",
        "sub-division of equity shares",
        "rights issue",
        "right issue",
        "record date",
        "book closure",
        "dividend",
    ),
}


def _classify_category(text: str) -> str:
    haystack = (text or "").lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return category
    return "other"


def _strip_html_tags(text: str) -> str:
    normalized = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(html.unescape(normalized).split())


def _sanitize_pg_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace("\x00", "")


def _is_missing_attachment_url(raw_url: str) -> bool:
    lowered = (raw_url or "").strip().lower()
    if lowered in {"", "-", "--", "na", "n/a", "null", "none", "#", "javascript:void(0)", "javascript:void(0);", "about:blank"}:
        return True
    stripped = lowered.strip("/")
    if stripped in {"", "-", "--", "na", "n/a", "null", "none"}:
        return True
    if lowered.startswith(("http://", "https://")):
        parsed = urlparse(lowered)
        path = (parsed.path or "").strip().strip("/").lower()
        if path in {"-", "--", "na", "n/a", "null", "none"}:
            return True
    return False


def _normalize_attachment_url(raw_url: str, base_url: str) -> str:
    original = (raw_url or "").strip()
    url = original.replace("\\", "/")
    if _is_missing_attachment_url(url):
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin(base_url, url)
    if url.lower().startswith(("http://", "https://")):
        return url
    if base_url.rstrip("/").endswith("bseindia.com"):
        lowered = url.lower().split("?", 1)[0]
        if "xml-data/corpfiling/" in lowered:
            return urljoin("https://www.bseindia.com/", url)
        if lowered.endswith((".pdf", ".xml", ".xbrl", ".zip", ".txt", ".csv")) or "/" not in url:
            return f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{url.lstrip('/')}"
    return urljoin(base_url, url)


def _is_structured_attachment_url(url: str) -> bool:
    lowered = str(url or "").lower().split("?", 1)[0]
    return lowered.endswith((".xml", ".xbrl", ".zip", ".csv", ".txt"))


def _attachment_candidates_for_record(
    exchange: str,
    raw_row: dict[str, Any],
    *,
    base_url: str,
    fallback_url: str,
) -> list[str]:
    candidates: list[str] = []

    def _push(raw_value: Any) -> None:
        normalized = _normalize_attachment_url(str(raw_value or ""), base_url)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    if str(exchange or "").upper() == "NSE":
        _push(raw_row.get("xbrl"))
        _push(raw_row.get("csvName"))
        _push(raw_row.get("attchmntFile"))
    else:
        _push(raw_row.get("ATTACHMENTNAME"))
        _push(raw_row.get("NSURL"))
        _push(raw_row.get("xbrl"))

    _push(fallback_url)
    structured = [url for url in candidates if _is_structured_attachment_url(url)]
    non_structured = [url for url in candidates if url not in structured]
    return structured + non_structured


def _record_attachment_candidates(record: dict[str, Any]) -> list[str]:
    """Rebuild candidate attachment URLs from the stored source payload when needed."""
    candidates: list[str] = []

    def _push(raw_value: Any, *, base_url: str) -> None:
        normalized = _normalize_attachment_url(str(raw_value or ""), base_url)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    exchange = str(record.get("exchange") or "").upper()
    base_url = _NSE_BASE_URL if exchange == "NSE" else "https://www.bseindia.com"
    attachment_url = str(record.get("attachment_url") or "").strip()

    for raw_value in list(record.get("attachment_candidates") or []):
        _push(raw_value, base_url=base_url)

    if attachment_url:
        _push(attachment_url, base_url=base_url)

    raw_json = record.get("raw_json")
    if isinstance(raw_json, dict):
        rebuilt = _attachment_candidates_for_record(
            exchange,
            raw_json,
            base_url=base_url,
            fallback_url=attachment_url,
        )
        for raw_value in rebuilt:
            _push(raw_value, base_url=base_url)

    return candidates


def _extract_with_fallback_candidates(candidate_urls: list[str], timeout_s: float = _ATTACHMENT_TIMEOUT_S) -> dict[str, Any]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw_url in candidate_urls:
        url = str(raw_url or "").strip()
        if not url or _is_missing_attachment_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    last_result: dict[str, Any] | None = None
    for url in urls:
        result = extract_attachment_content(url, timeout_s=timeout_s)
        result["resolved_attachment_url"] = url
        if result.get("attachment_extraction_status") == "ok":
            return result
        last_result = result
    return last_result or extract_attachment_content("", timeout_s=timeout_s)


def _attachment_suffix(name: str, content_type: str = "") -> str:
    lowered = str(name or "").lower().split("?", 1)[0]
    for suffix in (".xbrl", ".xml", ".xlsx", ".xls", ".csv", ".pdf", ".zip", ".txt", ".json", ".html", ".htm", ".md"):
        if lowered.endswith(suffix):
            return suffix
    ct = str(content_type or "").lower()
    if "pdf" in ct:
        return ".pdf"
    if "zip" in ct:
        return ".zip"
    if "spreadsheet" in ct or "excel" in ct:
        return ".xlsx"
    if "csv" in ct:
        return ".csv"
    if "xml" in ct:
        return ".xml"
    if ct.startswith("text/"):
        return ".txt"
    return ""


def _attachment_sufficiency(text: str, document_type: str, *, structured_facts: Any = None, tables: list[dict[str, Any]] | None = None) -> tuple[bool, str]:
    cleaned = str(text or "").strip()
    if structured_facts:
        return True, "structured_facts_extracted"
    if tables and any(str(item.get("markdown") or "").strip() for item in tables):
        return True, "tables_extracted"
    if document_type == "pdf":
        if text_is_sufficient(cleaned, min_chars=_ATTACHMENT_LOCAL_MIN_CHARS):
            return True, "pdf_text_sufficient"
        if cleaned:
            return False, "pdf_text_thin"
        return False, "pdf_empty"
    if document_type in {"spreadsheet", "zip"}:
        if len(cleaned) >= 180:
            return True, "tabular_summary_available"
        if cleaned:
            return False, "tabular_summary_thin"
        return False, "tabular_summary_empty"
    if document_type in {"xml", "xbrl"}:
        if len(cleaned) >= 120:
            return True, "structured_text_available"
        if cleaned:
            return False, "structured_text_thin"
        return False, "structured_text_empty"
    if len(cleaned) >= 140:
        return True, "text_available"
    if cleaned:
        return False, "text_thin"
    return False, "text_empty"


def _resolve_limit(
    limit: int | None,
    *,
    env_key: str,
    default_value: str,
    records_count: int = 0,
    small_batch_unlimited_threshold: int = 150,
) -> int:
    if limit is not None:
        return max(0, int(limit))
    raw = (os.getenv(env_key) or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning("Invalid %s=%r; using fallback default", env_key, raw)
    if records_count and records_count <= small_batch_unlimited_threshold:
        return 0
    return max(0, int(default_value or "0"))


def _structured_summary_to_text(summary: Any) -> str:
    if not summary:
        return ""
    try:
        return json.dumps(summary, ensure_ascii=True, default=str, indent=2)
    except Exception:
        return str(summary)


def _extract_with_docling(file_bytes: bytes, filename: str) -> tuple[str, str | None]:
    if not file_bytes:
        return "", "empty attachment"
    docling_enabled = os.getenv("FINAGENT_CORP_FILINGS_DOCLING_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if not docling_enabled:
        return "", "docling disabled by config"
    path: str | None = None
    try:
        from docling.document_converter import DocumentConverter

        suffix = _attachment_suffix(filename) or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            path = tmp.name
        result = DocumentConverter().convert(path, raises_on_error=False)
        document = getattr(result, "document", None)
        if document is None or not hasattr(document, "export_to_markdown"):
            status = getattr(result, "status", None)
            return "", f"docling returned no document ({status})"
        markdown = str(document.export_to_markdown() or "").strip()
        if not markdown:
            return "", "docling markdown output empty"
        return markdown, None
    except ImportError:
        return "", "docling_not_installed"
    except Exception as exc:
        return "", str(exc)
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _extract_spreadsheet_content(file_bytes: bytes, filename: str) -> dict[str, Any]:
    transformed = run_async(document_to_markdown(file_bytes, filename))
    markdown = str(getattr(transformed, "markdown", "") or "").strip()
    table_name = Path(filename or "attachment").name[:120]
    tables = [{"name": table_name, "markdown": markdown[:6000]}] if markdown else []
    sufficient, reason = _attachment_sufficiency(markdown, "spreadsheet", tables=tables)
    return {
        "attachment_text": markdown,
        "attachment_document_type": "spreadsheet",
        "attachment_parser": str(getattr(transformed, "transformer", "") or "pandas"),
        "attachment_page_count": 0,
        "attachment_tables": tables,
        "attachment_structured_facts": None,
        "attachment_text_sufficient": sufficient,
        "attachment_sufficiency_reason": reason,
    }


def _extract_with_azure_di_for_pdf(file_bytes: bytes, *, timeout_s: float) -> tuple[str, int, str | None, str | None]:
    """Fallback PDF extraction via Azure DI/local-first wrapper.

    Returns: (text, page_count, model_name, error_text)
    """
    try:
        from finagent.ingestion.azure_doc_intel import extract_document

        result = run_async(
            extract_document(
                file_bytes=file_bytes,
                model_id=os.getenv("AZURE_DI_CORP_FILINGS_MODEL", "prebuilt-layout"),
                allow_fallback=True,
                timeout_s=timeout_s,
            )
        )
        text = str(result.full_text or "").strip()
        model_name = str(result.model_used or "azure_document_intelligence")
        page_count = int(result.page_count or 0)
        if text:
            return text, page_count, model_name, None
        return "", page_count, model_name, "azure_di_empty_output"
    except Exception as exc:
        return "", 0, None, f"azure_di_error:{exc}"


def _extract_attachment_payload(file_bytes: bytes, filename: str, content_type: str = "") -> dict[str, Any]:
    suffix = _attachment_suffix(filename, content_type)
    lowered_name = str(filename or "").lower()
    is_pdf = suffix == ".pdf" or file_bytes.startswith(b"%PDF") or "pdf" in str(content_type or "").lower()
    is_zip = suffix == ".zip" or file_bytes.startswith(b"PK\x03\x04") or "zip" in str(content_type or "").lower()

    if is_zip:
        texts: list[str] = []
        tables: list[dict[str, Any]] = []
        structured: list[dict[str, Any]] = []
        parsers: list[str] = []
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                inner_name = str(info.filename or "").strip()
                if not inner_name:
                    continue
                inner_suffix = _attachment_suffix(inner_name)
                if inner_suffix not in {".xml", ".xbrl", ".txt", ".csv", ".xlsx", ".xls", ".pdf", ".json", ".md", ".html", ".htm"}:
                    continue
                inner_bytes = zf.read(info)
                inner_payload = _extract_attachment_payload(inner_bytes, inner_name, "")
                parser_name = str(inner_payload.get("attachment_parser") or "").strip()
                if parser_name:
                    parsers.append(parser_name)
                inner_text = str(inner_payload.get("attachment_text") or "").strip()
                if inner_text:
                    texts.append(f"[{Path(inner_name).name}]\n{inner_text}")
                inner_tables = list(inner_payload.get("attachment_tables") or [])
                if inner_tables:
                    tables.extend(inner_tables[:3])
                inner_structured = inner_payload.get("attachment_structured_facts")
                if inner_structured:
                    structured.append({"name": Path(inner_name).name[:120], "facts": inner_structured})
        combined_text = "\n\n".join(part for part in texts if part.strip()).strip()
        sufficient, reason = _attachment_sufficiency(combined_text, "zip", structured_facts=structured, tables=tables)
        return {
            "attachment_text": combined_text,
            "attachment_document_type": "zip",
            "attachment_parser": ",".join(dict.fromkeys(parsers))[:180] or "zip_bundle",
            "attachment_page_count": 0,
            "attachment_tables": tables[:6],
            "attachment_structured_facts": structured[:6] or None,
            "attachment_text_sufficient": sufficient,
            "attachment_sufficiency_reason": reason,
        }

    if suffix in {".xml", ".xbrl"} or ("xml" in str(content_type or "").lower() and not is_pdf):
        text = decode_text_bytes(file_bytes).strip()
        structured = None
        parser_name = "xml_text"
        document_type = "xml"
        if is_probable_xbrl(text, url=lowered_name, content_type=content_type):
            parsed = parse_xbrl_facts(text)
            if parsed.get("success") and parsed.get("facts"):
                structured = summarize_xbrl_facts("official_filing", list(parsed.get("facts") or []))
                parser_name = "xbrl_structured"
                document_type = "xbrl"
        summary_text = _structured_summary_to_text(structured)
        combined_text = "\n\n".join(part for part in [summary_text, text] if part.strip()).strip()
        sufficient, reason = _attachment_sufficiency(combined_text, document_type, structured_facts=structured)
        return {
            "attachment_text": combined_text,
            "attachment_document_type": document_type,
            "attachment_parser": parser_name,
            "attachment_page_count": 0,
            "attachment_tables": [],
            "attachment_structured_facts": structured,
            "attachment_text_sufficient": sufficient,
            "attachment_sufficiency_reason": reason,
        }

    if suffix in {".csv", ".xls", ".xlsx"}:
        return _extract_spreadsheet_content(file_bytes, filename)

    if is_pdf:
        local = extract_pdf_text_local(file_bytes)
        local_text = str(local.get("full_text") or "").strip()
        if text_is_sufficient(local_text, min_chars=_ATTACHMENT_LOCAL_MIN_CHARS):
            return {
                "attachment_text": local_text,
                "attachment_document_type": "pdf",
                "attachment_parser": str(local.get("model") or "pymupdf_local"),
                "attachment_page_count": int(local.get("page_count") or 0),
                "attachment_tables": [],
                "attachment_structured_facts": None,
                "attachment_text_sufficient": True,
                "attachment_sufficiency_reason": "pdf_text_sufficient",
            }
        docling_text, docling_error = _extract_with_docling(file_bytes, filename or "attachment.pdf")
        if docling_text.strip():
            sufficient, reason = _attachment_sufficiency(docling_text, "pdf")
            return {
                "attachment_text": docling_text,
                "attachment_document_type": "pdf",
                "attachment_parser": "docling_markdown",
                "attachment_page_count": int(local.get("page_count") or 0),
                "attachment_tables": [],
                "attachment_structured_facts": None,
                "attachment_text_sufficient": sufficient,
                "attachment_sufficiency_reason": reason,
                "attachment_extraction_error": None if sufficient else docling_error or "docling output thin",
            }
        azure_text, azure_pages, azure_model, azure_error = _extract_with_azure_di_for_pdf(
            file_bytes,
            timeout_s=_ATTACHMENT_TIMEOUT_S,
        )
        if azure_text.strip():
            sufficient, reason = _attachment_sufficiency(azure_text, "pdf")
            return {
                "attachment_text": azure_text,
                "attachment_document_type": "pdf",
                "attachment_parser": azure_model or "azure_document_intelligence",
                "attachment_page_count": max(int(local.get("page_count") or 0), int(azure_pages or 0)),
                "attachment_tables": [],
                "attachment_structured_facts": None,
                "attachment_text_sufficient": sufficient,
                "attachment_sufficiency_reason": reason,
                "attachment_extraction_error": None if sufficient else docling_error or azure_error or "azure output thin",
            }
        sufficient, reason = _attachment_sufficiency(local_text, "pdf")
        merged_error = "; ".join(
            part for part in [
                docling_error,
                azure_error,
                str(local.get("error") or "").strip() or None,
            ] if part
        )
        return {
            "attachment_text": local_text,
            "attachment_document_type": "pdf",
            "attachment_parser": str(local.get("model") or "pymupdf_local"),
            "attachment_page_count": int(local.get("page_count") or 0),
            "attachment_tables": [],
            "attachment_structured_facts": None,
            "attachment_text_sufficient": sufficient,
            "attachment_sufficiency_reason": reason,
            "attachment_extraction_error": merged_error or "pdf extraction produced no readable text",
        }

    text = decode_text_bytes(file_bytes).strip()
    sufficient, reason = _attachment_sufficiency(text, "text")
    return {
        "attachment_text": text,
        "attachment_document_type": "text",
        "attachment_parser": "raw_text",
        "attachment_page_count": 0,
        "attachment_tables": [],
        "attachment_structured_facts": None,
        "attachment_text_sufficient": sufficient,
        "attachment_sufficiency_reason": reason,
    }


def _parse_exchange_datetime(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    value = value.replace("Z", "")
    for fmt in (
        "%d-%b-%Y %H:%M:%S",
        "%d-%b-%Y",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(value[:26], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _category_for_announcement(*parts: str) -> str | None:
    category = _classify_category(" ".join(part for part in parts if part))
    return None if category == "other" else category


def _include_other_filings() -> bool:
    return os.getenv("FINAGENT_CORP_FILINGS_INCLUDE_OTHER", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _ensure_corporate_filings_table(database_url: str | None = None) -> None:
    db_url = get_database_url(database_url)
    if not db_url:
        return
    with connect_postgres(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists corporate_filings_raw (
                    id bigserial primary key,
                    category varchar(120) not null,
                    exchange varchar(20) not null,
                    symbol varchar(20),
                    scrip_code varchar(10),
                    cin varchar(21),
                    isin varchar(12),
                    company_name varchar(500),
                    announced_at timestamptz,
                    title text,
                    description text,
                    attachment_url text,
                    attachment_text text,
                    attachment_text_length integer default 0,
                    attachment_sha256 varchar(64),
                    attachment_content_type varchar(120),
                    attachment_extracted_model varchar(120),
                    attachment_page_count integer default 0,
                    attachment_extraction_status varchar(30) default 'pending',
                    attachment_extraction_error text,
                    source_url text,
                    source_uid text not null,
                    source_map_url text,
                    parser_version varchar(80) default 'corporate_filings_documents_v1',
                    raw_json jsonb default '{}'::jsonb,
                    fetched_at timestamptz default now(),
                    unique (exchange, source_uid)
                )
                """
            )
            cur.execute(
                "create index if not exists idx_corporate_filings_raw_category on corporate_filings_raw(category, exchange)"
            )
            cur.execute(
                "create index if not exists idx_corporate_filings_raw_symbol on corporate_filings_raw(symbol, announced_at desc)"
            )
            cur.execute(
                "create index if not exists idx_corporate_filings_raw_cin on corporate_filings_raw(cin, announced_at desc)"
            )
            for ddl in (
                "alter table corporate_filings_raw add column if not exists attachment_text text",
                "alter table corporate_filings_raw add column if not exists attachment_text_length integer default 0",
                "alter table corporate_filings_raw add column if not exists attachment_sha256 varchar(64)",
                "alter table corporate_filings_raw add column if not exists attachment_content_type varchar(120)",
                "alter table corporate_filings_raw add column if not exists attachment_extracted_model varchar(120)",
                "alter table corporate_filings_raw add column if not exists attachment_page_count integer default 0",
                "alter table corporate_filings_raw add column if not exists attachment_extraction_status varchar(30) default 'pending'",
                "alter table corporate_filings_raw add column if not exists attachment_extraction_error text",
            ):
                cur.execute(ddl)
        conn.commit()


def _ensure_xbrl_tables(database_url: str | None = None) -> None:
    db_url = get_database_url(database_url)
    if not db_url:
        return
    with connect_postgres(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists xbrl_filings_raw (
                    id bigserial primary key,
                    exchange varchar(20) not null,
                    source_uid text not null,
                    category varchar(120) not null,
                    symbol varchar(20),
                    scrip_code varchar(10),
                    cin varchar(21),
                    isin varchar(12),
                    company_name varchar(500),
                    announced_at timestamptz,
                    attachment_url text,
                    source_url text,
                    taxonomy_namespaces jsonb default '[]'::jsonb,
                    contexts_json jsonb default '{}'::jsonb,
                    facts_count integer default 0,
                    period_start date,
                    period_end date,
                    as_of_date date,
                    summary_json jsonb default '{}'::jsonb,
                    raw_xml text,
                    parser_version varchar(80) default 'corporate_xbrl_v1',
                    fetched_at timestamptz default now(),
                    unique (exchange, source_uid)
                )
                """
            )
            cur.execute(
                """
                create table if not exists corporate_xbrl_facts (
                    id bigserial primary key,
                    exchange varchar(20) not null,
                    source_uid text not null,
                    category varchar(120) not null,
                    cin varchar(21),
                    symbol varchar(20),
                    scrip_code varchar(10),
                    fact_name text not null,
                    fact_key text,
                    namespace text,
                    context_ref text,
                    unit_ref text,
                    decimals text,
                    value_text text,
                    value_numeric numeric,
                    period_start date,
                    period_end date,
                    instant date,
                    entity_identifier text,
                    attributes_json jsonb default '{}'::jsonb,
                    attachment_url text,
                    source_url text,
                    parser_version varchar(80) default 'corporate_xbrl_v1',
                    fetched_at timestamptz default now()
                )
                """
            )
            cur.execute(
                """
                create table if not exists financial_results_xbrl (
                    id bigserial primary key,
                    exchange varchar(20) not null,
                    source_uid text not null,
                    cin varchar(21),
                    symbol varchar(20),
                    scrip_code varchar(10),
                    company_name varchar(500),
                    announced_at timestamptz,
                    period_start date,
                    period_end date,
                    as_of_date date,
                    revenue_from_operations numeric,
                    total_income numeric,
                    profit_before_tax numeric,
                    profit_after_tax numeric,
                    eps_basic numeric,
                    eps_diluted numeric,
                    net_worth numeric,
                    summary_json jsonb default '{}'::jsonb,
                    attachment_url text,
                    source_url text,
                    parser_version varchar(80) default 'corporate_xbrl_v1',
                    fetched_at timestamptz default now(),
                    unique (exchange, source_uid)
                )
                """
            )
            cur.execute(
                """
                create table if not exists corporate_event_xbrl (
                    id bigserial primary key,
                    exchange varchar(20) not null,
                    source_uid text not null,
                    category varchar(120) not null,
                    cin varchar(21),
                    symbol varchar(20),
                    scrip_code varchar(10),
                    company_name varchar(500),
                    announced_at timestamptz,
                    period_start date,
                    period_end date,
                    as_of_date date,
                    summary_json jsonb default '{}'::jsonb,
                    attachment_url text,
                    source_url text,
                    parser_version varchar(80) default 'corporate_xbrl_v1',
                    fetched_at timestamptz default now(),
                    unique (exchange, source_uid, category)
                )
                """
            )
            cur.execute(
                """
                create table if not exists corporate_actions_raw (
                    id bigserial primary key,
                    exchange varchar(20) not null,
                    source_uid text not null,
                    cin varchar(21),
                    symbol varchar(20),
                    scrip_code varchar(10),
                    company_name varchar(500),
                    announced_at timestamptz,
                    action_type varchar(80) not null,
                    ratio varchar(80),
                    record_date_raw text,
                    title text,
                    attachment_url text,
                    source_url text,
                    parser_version varchar(80) default 'corporate_actions_v1',
                    raw_json jsonb default '{}'::jsonb,
                    fetched_at timestamptz default now(),
                    unique (exchange, source_uid, action_type)
                )
                """
            )
            for ddl in (
                "create index if not exists idx_xbrl_filings_cin on xbrl_filings_raw(cin, as_of_date desc)",
                "create index if not exists idx_xbrl_filings_category on xbrl_filings_raw(category, as_of_date desc)",
                "create index if not exists idx_corporate_xbrl_facts_cin on corporate_xbrl_facts(cin, category, period_end desc)",
                "create index if not exists idx_corporate_xbrl_facts_fact_key on corporate_xbrl_facts(fact_key)",
                """
                create unique index if not exists idx_corporate_xbrl_facts_unique
                    on corporate_xbrl_facts (
                      exchange, source_uid, fact_name, coalesce(context_ref, ''),
                      coalesce(unit_ref, ''), left(coalesce(value_text, ''), 500)
                    )
                """,
                "create index if not exists idx_financial_results_xbrl_cin on financial_results_xbrl(cin, period_end desc)",
                "create index if not exists idx_corporate_event_xbrl_cin on corporate_event_xbrl(cin, category, as_of_date desc)",
                "create index if not exists idx_corporate_actions_raw_cin on corporate_actions_raw(cin, announced_at desc)",
                "create index if not exists idx_corporate_actions_raw_type on corporate_actions_raw(action_type, announced_at desc)",
            ):
                cur.execute(ddl)
        conn.commit()


def fetch_sebi_corporate_filing_page(timeout_s: float = 30.0) -> tuple[str, int]:
    """Fetch the official SEBI corporate filing curation page."""
    resp = sync_get(_SEBI_CORPORATE_FILING_URL, headers=_SEBI_HEADERS, timeout=timeout_s)
    return resp.text, resp.status_code


def parse_sebi_corporate_filing_page(html_text: str) -> list[dict[str, Any]]:
    """Parse SEBI corporate filing curation table into NSE/BSE map records."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html_text or "", flags=re.I | re.S):
        row_html = match.group(1)
        row_text = _strip_html_tags(row_html)
        category = _classify_category(row_text)
        if category == "other":
            continue

        # NSE links are explicitly present in curation table rows.
        for link_match in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", row_html, flags=re.I | re.S):
            href = link_match.group(1).strip()
            url = urljoin(_SEBI_CORPORATE_FILING_URL, href)
            if "nseindia.com" not in url.lower():
                continue
            if url in seen:
                continue
            seen.add(url)
            title = _strip_html_tags(link_match.group(2)) or row_text
            records.append({
                "category": category,
                "exchange": "NSE",
                "title": title,
                "url": url,
                "source_page": _SEBI_CORPORATE_FILING_URL,
                "raw": {"parser_version": _PARSER_VERSION, "source": "sebi_curation"},
            })

        # BSE destinations are represented in row text; map to fixed official BSE endpoints.
        bse_url = _BSE_CATEGORY_URLS.get(category)
        if bse_url and bse_url not in seen:
            seen.add(bse_url)
            records.append({
                "category": category,
                "exchange": "BSE",
                "title": f"BSE {category.replace('_', ' ').title()}",
                "url": bse_url,
                "source_page": _SEBI_CORPORATE_FILING_URL,
                "raw": {"parser_version": _PARSER_VERSION, "source": "sebi_curation_row_text"},
            })

    return records


def store_corporate_filing_map(
    records: list[dict[str, Any]],
    database_url: str | None = None,
) -> int:
    """Store parsed filing map records in Supabase/Postgres."""
    if not records:
        return 0
    db_url = get_database_url(database_url)
    if not db_url:
        return 0

    import json
    stored = 0
    with connect_postgres(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for record in records:
                cur.execute(
                    """
                    insert into sebi_corporate_filing_map (
                      category, exchange, title, url, source_page, raw_json, fetched_at
                    )
                    values (%s, %s, %s, %s, %s, %s::jsonb, now())
                    on conflict (url) do update set
                      category = excluded.category,
                      exchange = excluded.exchange,
                      title = excluded.title,
                      source_page = excluded.source_page,
                      raw_json = excluded.raw_json,
                      fetched_at = now()
                    """,
                    (
                        record["category"],
                        record.get("exchange"),
                        record["title"],
                        record["url"],
                        record["source_page"],
                        json.dumps(record.get("raw") or {}),
                    ),
                )
                stored += 1
        conn.commit()
    return stored


def _load_map_url_by_category_exchange(database_url: str | None = None) -> dict[tuple[str, str], str]:
    db_url = get_database_url(database_url)
    if not db_url:
        return {}
    rows: dict[tuple[str, str], str] = {}
    try:
        with connect_postgres(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("select category, exchange, url from sebi_corporate_filing_map")
                for category, exchange, url in cur.fetchall():
                    rows[(str(category), str(exchange).upper())] = str(url)
    except Exception as exc:
        logger.debug("Corporate filing map lookup failed: %s", exc)
    return rows


def fetch_nse_corporate_filings(symbol: str, *, years_back: int = 1, timeout_s: float = 45.0) -> list[dict[str, Any]]:
    """Fetch NSE corporate announcement filings and classify SEBI curation categories."""
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=365 * max(1, years_back))
    params = {
        "index": "equities",
        "symbol": symbol.upper(),
        "from_date": since.strftime("%d-%m-%Y"),
        "to_date": today.strftime("%d-%m-%Y"),
    }
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            req_headers = apply_nse_cookies(_NSE_HEADERS)
            if not should_skip_nse_home_visit():
                client.get(_NSE_BASE_URL, headers=req_headers)
            resp = client.get(_NSE_CORPORATE_ANNOUNCEMENTS_URL, headers=req_headers, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("NSE corporate filing fetch failed for %s: %s", symbol, exc)
        return []
    if not isinstance(payload, list):
        return []

    records: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        title = str(row.get("desc") or row.get("subject") or "").strip()
        description = str(row.get("attchmntText") or row.get("details") or "").strip()
        attachment_url = _normalize_attachment_url(str(row.get("attchmntFile") or ""), _NSE_BASE_URL)
        attachment_candidates = _attachment_candidates_for_record(
            "NSE",
            row,
            base_url=_NSE_BASE_URL,
            fallback_url=attachment_url,
        )
        preferred_attachment_url = attachment_candidates[0] if attachment_candidates else attachment_url
        category = _category_for_announcement(title, description, attachment_url)
        if not category:
            if not _include_other_filings():
                continue
            category = "other"
        announced_at = _parse_exchange_datetime(str(row.get("an_dt") or row.get("sort_date") or ""))
        source_uid = str(row.get("id") or row.get("seq_id") or row.get("sm_isin") or "")
        if not source_uid:
            source_uid = f"{symbol.upper()}|{row.get('an_dt')}|{attachment_url}|{title}"
        records.append(
            {
                "category": category,
                "exchange": "NSE",
                "symbol": str(row.get("symbol") or symbol).strip().upper(),
                "scrip_code": None,
                "cin": None,
                "isin": str(row.get("sm_isin") or "").strip() or None,
                "company_name": str(row.get("sm_name") or "").strip() or None,
                "announced_at": announced_at,
                "title": title,
                "description": description,
                "attachment_url": preferred_attachment_url,
                "attachment_candidates": attachment_candidates,
                "has_xbrl_hint": str(row.get("hasXbrl") or "").strip().lower() in {"true", "1", "yes"},
                "source_url": _NSE_CORPORATE_ANNOUNCEMENTS_URL,
                "source_uid": source_uid,
                "raw_json": row,
            }
        )
    return records


def fetch_bse_corporate_filings(
    scrip_code: str,
    *,
    years_back: int = 1,
    max_pages: int | None = None,
    timeout_s: float = 45.0,
) -> list[dict[str, Any]]:
    """Fetch paginated BSE corporate announcements and classify SEBI curation categories."""
    today = datetime.now(timezone.utc).date()
    since = today - timedelta(days=365 * max(1, years_back))
    pages = max(1, int(max_pages or os.getenv("FINAGENT_CORP_FILINGS_BSE_PAGES", "2")))
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
        for page_no in range(1, pages + 1):
            params = {
                "pageno": str(page_no),
                "strCat": "-1",
                "strPrevDate": since.strftime("%Y%m%d"),
                "strScrip": str(scrip_code),
                "strSearch": "P",
                "strToDate": today.strftime("%Y%m%d"),
                "strType": "C",
                "subcategory": "-1",
            }
            try:
                resp = client.get(_BSE_ANNOUNCEMENTS_URL, headers=_BSE_HEADERS, params=params)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                logger.warning("BSE corporate filing fetch failed for %s page %d: %s", scrip_code, page_no, exc)
                break
            rows = payload.get("Table") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("NEWSSUB") or row.get("HEADLINE") or "").strip()
                description = _strip_html_tags(str(row.get("MORE") or row.get("MORETEXT") or ""))
                attachment_url = _normalize_attachment_url(str(row.get("ATTACHMENTNAME") or row.get("NSURL") or ""), "https://www.bseindia.com")
                attachment_candidates = _attachment_candidates_for_record(
                    "BSE",
                    row,
                    base_url="https://www.bseindia.com",
                    fallback_url=attachment_url,
                )
                preferred_attachment_url = attachment_candidates[0] if attachment_candidates else attachment_url
                category = _category_for_announcement(title, description, attachment_url, str(row.get("CATEGORYNAME") or ""))
                if not category:
                    if not _include_other_filings():
                        continue
                    category = "other"
                announced_at = _parse_exchange_datetime(str(row.get("DT_TM") or row.get("NEWS_DT") or ""))
                source_uid = str(row.get("NEWSID") or row.get("XML_NAME") or f"{scrip_code}|{title}|{row.get('DT_TM')}")
                records.append(
                    {
                        "category": category,
                        "exchange": "BSE",
                        "symbol": None,
                        "scrip_code": str(row.get("SCRIP_CD") or scrip_code),
                        "cin": None,
                        "isin": None,
                        "company_name": str(row.get("SLONGNAME") or "").strip() or None,
                        "announced_at": announced_at,
                        "title": title,
                        "description": description,
                        "attachment_url": preferred_attachment_url,
                        "attachment_candidates": attachment_candidates,
                        "has_xbrl_hint": False,
                        "source_url": _BSE_ANNOUNCEMENTS_URL,
                        "source_uid": source_uid,
                        "raw_json": row,
                    }
                )
            if len(rows) < 50:
                break
    return records


def extract_attachment_content(attachment_url: str, timeout_s: float = _ATTACHMENT_TIMEOUT_S) -> dict[str, Any]:
    """Download and extract corporate filing attachment content in strict mode."""
    if _is_missing_attachment_url(attachment_url):
        return {
            "attachment_text": "",
            "attachment_text_length": 0,
            "attachment_sha256": None,
            "attachment_content_type": None,
            "attachment_extracted_model": None,
            "attachment_parser": None,
            "attachment_document_type": None,
            "attachment_tables": [],
            "attachment_structured_facts": None,
            "attachment_text_sufficient": False,
            "attachment_sufficiency_reason": "missing attachment_url",
            "attachment_page_count": 0,
            "attachment_extraction_status": "missing_url",
            "attachment_extraction_error": "missing attachment_url",
        }
    try:
        headers = _BSE_HEADERS if "bseindia.com" in attachment_url.lower() else _NSE_HEADERS
        resp = sync_get(attachment_url, headers=headers, timeout=timeout_s)
        resp.raise_for_status()
        content = resp.content or b""
        content_type = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        sha = hashlib.sha256(content).hexdigest() if content else None
        if len(content) < 200:
            return {
                "attachment_text": "",
                "attachment_text_length": 0,
                "attachment_sha256": sha,
                "attachment_content_type": content_type,
                "attachment_extracted_model": None,
                "attachment_parser": None,
                "attachment_document_type": _attachment_suffix(attachment_url, content_type).lstrip(".") or None,
                "attachment_tables": [],
                "attachment_structured_facts": None,
                "attachment_text_sufficient": False,
                "attachment_sufficiency_reason": "attachment_too_small",
                "attachment_page_count": 0,
                "attachment_extraction_status": "failed",
                "attachment_extraction_error": "attachment too small",
            }
        payload = _extract_attachment_payload(content, attachment_url, content_type)
        text = _sanitize_pg_text(payload.get("attachment_text")) or ""
        parser_name = str(payload.get("attachment_parser") or "").strip() or None
        document_type = str(payload.get("attachment_document_type") or "").strip() or None
        tables = list(payload.get("attachment_tables") or [])
        structured = payload.get("attachment_structured_facts")
        sufficient = bool(payload.get("attachment_text_sufficient"))
        sufficiency_reason = str(payload.get("attachment_sufficiency_reason") or "").strip() or None
        page_count = int(payload.get("attachment_page_count") or 0)
        error_text = _sanitize_pg_text(payload.get("attachment_extraction_error"))
        return {
            "attachment_text": text,
            "attachment_text_length": len(text),
            "attachment_sha256": sha,
            "attachment_content_type": content_type or None,
            "attachment_extracted_model": parser_name,
            "attachment_parser": parser_name,
            "attachment_document_type": document_type,
            "attachment_tables": tables,
            "attachment_structured_facts": structured,
            "attachment_text_sufficient": sufficient,
            "attachment_sufficiency_reason": sufficiency_reason,
            "attachment_page_count": page_count,
            "attachment_extraction_status": "ok" if text.strip() else "failed",
            "attachment_extraction_error": None if (text.strip() and sufficient) else error_text or ("empty extraction result" if not text.strip() else sufficiency_reason),
        }
    except Exception as exc:
        logger.warning("Corporate filing attachment extraction failed for %s: %s", attachment_url, exc)
        return {
            "attachment_text": "",
            "attachment_text_length": 0,
            "attachment_sha256": None,
            "attachment_content_type": None,
            "attachment_extracted_model": None,
            "attachment_parser": None,
            "attachment_document_type": _attachment_suffix(attachment_url).lstrip(".") or None,
            "attachment_tables": [],
            "attachment_structured_facts": None,
            "attachment_text_sufficient": False,
            "attachment_sufficiency_reason": "extractor_exception",
            "attachment_page_count": 0,
            "attachment_extraction_status": "failed",
            "attachment_extraction_error": _sanitize_pg_text(exc) or "attachment extraction failed",
        }


def hydrate_attachment_content(records: list[dict[str, Any]], *, limit: int | None = None) -> dict[str, int]:
    """Extract attachment content for filing records before DB storage."""
    extracted = 0
    failed = 0
    eligible = [r for r in records if not _is_missing_attachment_url(str(r.get("attachment_url") or ""))]
    cap = _resolve_limit(
        limit,
        env_key="FINAGENT_CORP_FILINGS_EXTRACT_LIMIT",
        default_value=_DEFAULT_ATTACHMENT_EXTRACT_LIMIT,
        records_count=len(eligible),
    )
    always_extract_xbrl = os.getenv("FINAGENT_CORP_FILINGS_ALWAYS_EXTRACT_XBRL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }

    def _is_xbrl_candidate(record: dict[str, Any]) -> bool:
        candidate_urls = _record_attachment_candidates(record)
        if any(_is_structured_attachment_url(url) for url in candidate_urls):
            return True
        if record.get("has_xbrl_hint"):
            return True
        return is_probable_xbrl(
            str(record.get("attachment_text") or ""),
            url=str(record.get("attachment_url") or ""),
            content_type=str(record.get("attachment_content_type") or ""),
        )

    xbrl_eligible = [r for r in eligible if _is_xbrl_candidate(r)]
    other_eligible = [r for r in eligible if not _is_xbrl_candidate(r)]
    if cap:
        if always_extract_xbrl:
            selected = xbrl_eligible + other_eligible[:cap]
        else:
            selected = (xbrl_eligible + other_eligible)[:cap]
    else:
        selected = xbrl_eligible + other_eligible
    selected_ids = {id(r) for r in selected}
    total_to_attempt = len(selected)
    logger.info(
        "Corporate filing attachment extraction starting: records=%d, with_attachment=%d, xbrl_candidates=%d, limit=%s, will_attempt=%d",
        len(records),
        len(eligible),
        len(xbrl_eligible),
        cap or "none",
        total_to_attempt,
    )
    for record in records:
        if record.get("attachment_url") and id(record) not in selected_ids:
            record.setdefault("attachment_extraction_status", "skipped_limit")
            continue

    for idx, record in enumerate(selected, start=1):
        for key in (
            "title",
            "description",
            "attachment_text",
            "attachment_url",
            "source_url",
            "source_uid",
            "company_name",
            "attachment_content_type",
            "attachment_extracted_model",
            "attachment_extraction_status",
            "attachment_extraction_error",
        ):
            if key in record:
                record[key] = _sanitize_pg_text(record.get(key))
        attachment_url = str(record.get("attachment_url") or "")
        if not attachment_url:
            record.update(extract_attachment_content(""))
            failed += 1
            continue
        logger.info(
            "Corporate filing attachment %d/%d: exchange=%s category=%s symbol=%s scrip=%s url=%s",
            extracted + failed + 1,
            total_to_attempt,
            record.get("exchange"),
            record.get("category"),
            record.get("symbol"),
            record.get("scrip_code"),
            attachment_url[:180],
        )
        extraction = _extract_with_fallback_candidates(
            list(record.get("attachment_candidates") or [attachment_url]),
        )
        record.update(extraction)
        record["attachment_text"] = _sanitize_pg_text(record.get("attachment_text")) or ""
        record["attachment_extraction_error"] = _sanitize_pg_text(record.get("attachment_extraction_error"))
        if extraction.get("resolved_attachment_url"):
            record["attachment_url"] = extraction["resolved_attachment_url"]
        if extraction.get("attachment_extraction_status") == "ok":
            extracted += 1
        else:
            failed += 1
        logger.info(
            "Corporate filing attachment result %d/%d: status=%s text_len=%d model=%s pages=%s extracted=%d failed=%d",
            extracted + failed,
            total_to_attempt,
            extraction.get("attachment_extraction_status"),
            int(extraction.get("attachment_text_length") or 0),
            extraction.get("attachment_extracted_model"),
            extraction.get("attachment_page_count"),
            extracted,
            failed,
        )
    logger.info(
        "Corporate filing attachment extraction complete: extracted=%d failed=%d skipped=%d",
        extracted,
        failed,
        max(0, len(eligible) - len(selected)),
    )
    return {"attachments_extracted": extracted, "attachments_failed": failed}


def _date_or_none(raw: Any) -> str | None:
    value = str(raw or "").strip()
    return value[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", value) else None


def _store_xbrl_for_record(cur: Any, record: dict[str, Any]) -> int:
    text = _sanitize_pg_text(record.get("attachment_text")) or ""
    attachment_url = _sanitize_pg_text(record.get("attachment_url")) or ""
    content_type = _sanitize_pg_text(record.get("attachment_content_type")) or ""
    candidate_urls = _record_attachment_candidates(record)
    structured_candidates = [url for url in candidate_urls if _is_structured_attachment_url(url)]
    xbrl_hint = bool(record.get("has_xbrl_hint"))
    raw_json = record.get("raw_json")
    if isinstance(raw_json, dict):
        xbrl_hint = xbrl_hint or str(raw_json.get("hasXbrl") or "").strip().lower() in {"true", "1", "yes"}
    if not is_probable_xbrl(text, url=attachment_url, content_type=content_type):
        if structured_candidates or xbrl_hint:
            extraction = _extract_with_fallback_candidates(structured_candidates or candidate_urls)
            extracted_text = _sanitize_pg_text(extraction.get("attachment_text")) or ""
            if extracted_text:
                text = extracted_text
                attachment_url = _sanitize_pg_text(extraction.get("resolved_attachment_url")) or attachment_url
                content_type = _sanitize_pg_text(extraction.get("attachment_content_type")) or content_type
        if not is_probable_xbrl(text, url=attachment_url, content_type=content_type):
            return 0
    parsed = parse_xbrl_facts(text)
    if not parsed.get("success"):
        logger.warning(
            "XBRL parse failed for %s/%s: %s",
            record.get("exchange"),
            record.get("source_uid"),
            parsed.get("error"),
        )
        return 0
    facts = list(parsed.get("facts") or [])
    if not facts:
        return 0
    summary = summarize_xbrl_facts(str(record.get("category") or ""), facts)
    cur.execute(
        """
        insert into xbrl_filings_raw (
          exchange, source_uid, category, symbol, scrip_code, cin, isin,
          company_name, announced_at, attachment_url, source_url,
          taxonomy_namespaces, contexts_json, facts_count, period_start,
          period_end, as_of_date, summary_json, raw_xml, parser_version,
          fetched_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s, %s, now())
        on conflict (exchange, source_uid) do update set
          category = excluded.category,
          symbol = excluded.symbol,
          scrip_code = excluded.scrip_code,
          cin = excluded.cin,
          isin = excluded.isin,
          company_name = excluded.company_name,
          announced_at = excluded.announced_at,
          attachment_url = excluded.attachment_url,
          source_url = excluded.source_url,
          taxonomy_namespaces = excluded.taxonomy_namespaces,
          contexts_json = excluded.contexts_json,
          facts_count = excluded.facts_count,
          period_start = excluded.period_start,
          period_end = excluded.period_end,
          as_of_date = excluded.as_of_date,
          summary_json = excluded.summary_json,
          raw_xml = excluded.raw_xml,
          parser_version = excluded.parser_version,
          fetched_at = now()
        """,
        (
            record.get("exchange"),
            _sanitize_pg_text(record.get("source_uid")),
            _sanitize_pg_text(record.get("category")),
            _sanitize_pg_text(record.get("symbol")),
            _sanitize_pg_text(record.get("scrip_code")),
            _sanitize_pg_text(record.get("cin")),
            _sanitize_pg_text(record.get("isin")),
            _sanitize_pg_text(record.get("company_name")),
            record.get("announced_at"),
            attachment_url,
            _sanitize_pg_text(record.get("source_url")),
            json.dumps(parsed.get("taxonomy_namespaces") or []),
            json.dumps(parsed.get("contexts") or {}),
            len(facts),
            _date_or_none(summary.get("period_start")),
            _date_or_none(summary.get("period_end")),
            _date_or_none(summary.get("as_of_date")),
            json.dumps(summary, default=str),
            text,
            _XBRL_PARSER_VERSION,
        ),
    )
    cur.execute(
        "delete from corporate_xbrl_facts where exchange = %s and source_uid = %s",
        (record.get("exchange"), _sanitize_pg_text(record.get("source_uid"))),
    )
    for fact in facts:
        cur.execute(
            """
            insert into corporate_xbrl_facts (
              exchange, source_uid, category, cin, symbol, scrip_code,
              fact_name, fact_key, namespace, context_ref, unit_ref, decimals,
              value_text, value_numeric, period_start, period_end, instant,
              entity_identifier, attributes_json, attachment_url, source_url,
              parser_version, fetched_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb, %s, %s, %s, now())
            on conflict do nothing
            """,
            (
                record.get("exchange"),
                _sanitize_pg_text(record.get("source_uid")),
                _sanitize_pg_text(record.get("category")),
                _sanitize_pg_text(record.get("cin")),
                _sanitize_pg_text(record.get("symbol")),
                _sanitize_pg_text(record.get("scrip_code")),
                _sanitize_pg_text(fact.get("fact_name")),
                _sanitize_pg_text(fact.get("fact_key")),
                _sanitize_pg_text(fact.get("namespace")),
                _sanitize_pg_text(fact.get("context_ref")),
                _sanitize_pg_text(fact.get("unit_ref")),
                _sanitize_pg_text(fact.get("decimals")),
                _sanitize_pg_text(fact.get("value_text")),
                fact.get("value_numeric"),
                _date_or_none(fact.get("period_start")),
                _date_or_none(fact.get("period_end")),
                _date_or_none(fact.get("instant")),
                _sanitize_pg_text(fact.get("entity_identifier")),
                json.dumps(fact.get("attributes") or {}, default=str),
                attachment_url,
                _sanitize_pg_text(record.get("source_url")),
                _XBRL_PARSER_VERSION,
            ),
        )

    category = str(record.get("category") or "")
    if category == "financial_results":
        cur.execute(
            """
            insert into financial_results_xbrl (
              exchange, source_uid, cin, symbol, scrip_code, company_name,
              announced_at, period_start, period_end, as_of_date,
              revenue_from_operations, total_income, profit_before_tax,
              profit_after_tax, eps_basic, eps_diluted, net_worth,
              summary_json, attachment_url, source_url, parser_version,
              fetched_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s, %s, %s, now())
            on conflict (exchange, source_uid) do update set
              cin = excluded.cin,
              symbol = excluded.symbol,
              scrip_code = excluded.scrip_code,
              company_name = excluded.company_name,
              announced_at = excluded.announced_at,
              period_start = excluded.period_start,
              period_end = excluded.period_end,
              as_of_date = excluded.as_of_date,
              revenue_from_operations = excluded.revenue_from_operations,
              total_income = excluded.total_income,
              profit_before_tax = excluded.profit_before_tax,
              profit_after_tax = excluded.profit_after_tax,
              eps_basic = excluded.eps_basic,
              eps_diluted = excluded.eps_diluted,
              net_worth = excluded.net_worth,
              summary_json = excluded.summary_json,
              attachment_url = excluded.attachment_url,
              source_url = excluded.source_url,
              parser_version = excluded.parser_version,
              fetched_at = now()
            """,
            (
                record.get("exchange"),
                _sanitize_pg_text(record.get("source_uid")),
                _sanitize_pg_text(record.get("cin")),
                _sanitize_pg_text(record.get("symbol")),
                _sanitize_pg_text(record.get("scrip_code")),
                _sanitize_pg_text(record.get("company_name")),
                record.get("announced_at"),
                _date_or_none(summary.get("period_start")),
                _date_or_none(summary.get("period_end")),
                _date_or_none(summary.get("as_of_date")),
                summary.get("revenue_from_operations"),
                summary.get("total_income"),
                summary.get("profit_before_tax"),
                summary.get("profit_after_tax"),
                summary.get("eps_basic"),
                summary.get("eps_diluted"),
                summary.get("net_worth"),
                json.dumps(summary, default=str),
                attachment_url,
                _sanitize_pg_text(record.get("source_url")),
                _XBRL_PARSER_VERSION,
            ),
        )
        symbol = str(record.get("symbol") or "").strip().upper()
        if symbol:
            cur.execute(
                """
                insert into company_financials (
                  cin, nse_symbol, sources_used, validated_metrics_json,
                  income_statement_json, fetched_at, updated_at
                )
                values (%s, %s, %s, %s::jsonb, %s::jsonb, now(), now())
                on conflict (nse_symbol) do update set
                  cin = coalesce(company_financials.cin, excluded.cin),
                  sources_used = array(
                    select distinct unnest(coalesce(company_financials.sources_used, '{}') || excluded.sources_used)
                  ),
                  validated_metrics_json = company_financials.validated_metrics_json || excluded.validated_metrics_json,
                  income_statement_json = case
                    when company_financials.income_statement_json = '[]'::jsonb
                      then excluded.income_statement_json
                    else company_financials.income_statement_json
                  end,
                  updated_at = now()
                """,
                (
                    _sanitize_pg_text(record.get("cin")),
                    _sanitize_pg_text(symbol),
                    ["official_xbrl"],
                    json.dumps(summary, default=str),
                    json.dumps([summary], default=str),
                ),
            )
    elif category in {
        "related_party_transactions",
        "voting_results",
        "corporate_governance",
        "brsr",
        "insider_trading",
        "secretarial_compliance",
        "corporate_actions",
    }:
        cur.execute(
            """
            insert into corporate_event_xbrl (
              exchange, source_uid, category, cin, symbol, scrip_code,
              company_name, announced_at, period_start, period_end, as_of_date,
              summary_json, attachment_url, source_url, parser_version,
              fetched_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                    %s, %s, %s, now())
            on conflict (exchange, source_uid, category) do update set
              cin = excluded.cin,
              symbol = excluded.symbol,
              scrip_code = excluded.scrip_code,
              company_name = excluded.company_name,
              announced_at = excluded.announced_at,
              period_start = excluded.period_start,
              period_end = excluded.period_end,
              as_of_date = excluded.as_of_date,
              summary_json = excluded.summary_json,
              attachment_url = excluded.attachment_url,
              source_url = excluded.source_url,
              parser_version = excluded.parser_version,
              fetched_at = now()
            """,
            (
                record.get("exchange"),
                _sanitize_pg_text(record.get("source_uid")),
                _sanitize_pg_text(category),
                _sanitize_pg_text(record.get("cin")),
                _sanitize_pg_text(record.get("symbol")),
                _sanitize_pg_text(record.get("scrip_code")),
                _sanitize_pg_text(record.get("company_name")),
                record.get("announced_at"),
                _date_or_none(summary.get("period_start")),
                _date_or_none(summary.get("period_end")),
                _date_or_none(summary.get("as_of_date")),
                json.dumps(summary, default=str),
                attachment_url,
                _sanitize_pg_text(record.get("source_url")),
                _XBRL_PARSER_VERSION,
            ),
        )
    return len(facts)


def store_xbrl_from_filing_records(
    records: list[dict[str, Any]],
    *,
    database_url: str | None = None,
) -> dict[str, int]:
    db_url = get_database_url(database_url)
    if not db_url:
        return {"xbrl_filings": 0, "xbrl_facts": 0}
    _ensure_xbrl_tables(db_url)
    filings = 0
    facts = 0
    with connect_postgres(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for record in records:
                parsed_facts = _store_xbrl_for_record(cur, record)
                if parsed_facts:
                    filings += 1
                    facts += parsed_facts
        conn.commit()
    if filings:
        logger.info("XBRL normalization complete: filings=%d facts=%d", filings, facts)
    return {"xbrl_filings": filings, "xbrl_facts": facts}


def _store_corporate_action_for_record(cur: Any, record: dict[str, Any]) -> int:
    if str(record.get("category") or "") != "corporate_actions":
        return 0
    joined = " ".join(
        str(record.get(key) or "")
        for key in ("title", "description", "attachment_text")
    )
    extracted = extract_corporate_action_from_text(joined)
    action_type = str(extracted.get("action_type") or "other")
    cur.execute(
        """
        insert into corporate_actions_raw (
          exchange, source_uid, cin, symbol, scrip_code, company_name,
          announced_at, action_type, ratio, record_date_raw, title,
          attachment_url, source_url, parser_version, raw_json, fetched_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
        on conflict (exchange, source_uid, action_type) do update set
          cin = excluded.cin,
          symbol = excluded.symbol,
          scrip_code = excluded.scrip_code,
          company_name = excluded.company_name,
          announced_at = excluded.announced_at,
          ratio = excluded.ratio,
          record_date_raw = excluded.record_date_raw,
          title = excluded.title,
          attachment_url = excluded.attachment_url,
          source_url = excluded.source_url,
          raw_json = excluded.raw_json,
          fetched_at = now()
        """,
        (
            record.get("exchange"),
            _sanitize_pg_text(record.get("source_uid")),
            _sanitize_pg_text(record.get("cin")),
            _sanitize_pg_text(record.get("symbol")),
            _sanitize_pg_text(record.get("scrip_code")),
            _sanitize_pg_text(record.get("company_name")),
            record.get("announced_at"),
            action_type,
            extracted.get("ratio"),
            extracted.get("record_date_raw"),
            _sanitize_pg_text(record.get("title")),
            _sanitize_pg_text(record.get("attachment_url")),
            _sanitize_pg_text(record.get("source_url")),
            "corporate_actions_v1",
            json.dumps(record.get("raw_json") or {}, default=str),
        ),
    )
    return 1


def store_corporate_actions_from_records(
    records: list[dict[str, Any]],
    *,
    database_url: str | None = None,
) -> int:
    db_url = get_database_url(database_url)
    if not db_url:
        return 0
    _ensure_xbrl_tables(db_url)
    stored = 0
    with connect_postgres(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for record in records:
                stored += _store_corporate_action_for_record(cur, record)
        conn.commit()
    if stored:
        logger.info("Corporate actions normalization complete: rows=%d", stored)
    return stored


def hydrate_stored_corporate_filing_attachments(
    *,
    database_url: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Resume attachment extraction and normalize hydrated XBRL/action rows."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"attachments_extracted": 0, "attachments_failed": 0, "records_seen": 0}
    _ensure_corporate_filings_table(db_url)
    cap = _resolve_limit(
        limit,
        env_key="FINAGENT_CORP_FILINGS_HYDRATE_LIMIT",
        default_value=_DEFAULT_ATTACHMENT_HYDRATE_LIMIT,
    )
    limit_sql = "limit %s" if cap else ""
    params: list[Any] = [cap] if cap else []
    records: list[dict[str, Any]] = []
    with connect_postgres(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select category, exchange, symbol, scrip_code, cin, isin, company_name,
                       announced_at, title, description, attachment_url, attachment_text,
                       attachment_text_length, attachment_sha256, attachment_content_type,
                       attachment_extracted_model, attachment_page_count,
                       attachment_extraction_status, attachment_extraction_error,
                       source_url, source_uid, raw_json
                from corporate_filings_raw
                where attachment_url is not null
                  and not exists (
                    select 1
                    from xbrl_filings_raw x
                    where x.exchange = corporate_filings_raw.exchange
                      and x.source_uid = corporate_filings_raw.source_uid
                  )
                  and (
                    coalesce(attachment_text_length, 0) = 0
                    or lower(coalesce(attachment_url, '')) ~ '\\.(xml|xbrl|zip)(\\?|$)'
                    or coalesce(attachment_extraction_status, 'pending') in (
                      'pending', 'skipped_limit', 'failed', 'unknown'
                    )
                  )
                order by
                  case
                    when lower(coalesce(attachment_url, '')) ~ '\\.(xml|xbrl|zip)(\\?|$)' then 0
                    else 1
                  end,
                  fetched_at desc
                {limit_sql}
                """,
                params,
            )
            columns = [getattr(desc, "name", desc[0]) for desc in cur.description]
            for row in cur.fetchall():
                data = dict(zip(columns, row))
                records.append(
                    {
                        **data,
                        "raw_json": data.get("raw_json") or {},
                    }
                )
    extracted = 0
    failed = 0
    xbrl_filings = 0
    xbrl_facts = 0
    corporate_actions_stored = 0
    for idx, record in enumerate(records, start=1):
        logger.info(
            "Hydrating stored corporate filing attachment %d/%d: %s/%s",
            idx,
            len(records),
            record.get("exchange"),
            record.get("source_uid"),
        )
        extraction = _extract_with_fallback_candidates(_record_attachment_candidates(record))
        record.update(extraction)
        record["attachment_text"] = _sanitize_pg_text(record.get("attachment_text")) or ""
        record["attachment_extraction_error"] = _sanitize_pg_text(record.get("attachment_extraction_error"))
        if extraction.get("resolved_attachment_url"):
            record["attachment_url"] = extraction["resolved_attachment_url"]
        if extraction.get("attachment_text_length", 0):
            extracted += 1
        else:
            failed += 1
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update corporate_filings_raw
                    set attachment_text = %s,
                        attachment_text_length = %s,
                        attachment_sha256 = %s,
                        attachment_content_type = %s,
                        attachment_extracted_model = %s,
                        attachment_page_count = %s,
                        attachment_extraction_status = %s,
                        attachment_extraction_error = %s,
                        fetched_at = now()
                    where exchange = %s and source_uid = %s
                    """,
                    (
                        _sanitize_pg_text(extraction.get("attachment_text")) or "",
                        int(extraction.get("attachment_text_length") or 0),
                        extraction.get("attachment_sha256"),
                        _sanitize_pg_text(extraction.get("attachment_content_type")),
                        _sanitize_pg_text(extraction.get("attachment_extracted_model")),
                        int(extraction.get("attachment_page_count") or 0),
                        _sanitize_pg_text(extraction.get("attachment_extraction_status")),
                        _sanitize_pg_text(extraction.get("attachment_extraction_error")),
                        record.get("exchange"),
                        _sanitize_pg_text(record.get("source_uid")),
                    ),
                )
                parsed_facts = _store_xbrl_for_record(cur, record)
                if parsed_facts:
                    xbrl_filings += 1
                    xbrl_facts += parsed_facts
                corporate_actions_stored += _store_corporate_action_for_record(cur, record)
            conn.commit()
    return {
        "records_seen": len(records),
        "attachments_extracted": extracted,
        "attachments_failed": failed,
        "xbrl_filings": xbrl_filings,
        "xbrl_facts": xbrl_facts,
        "corporate_actions_stored": corporate_actions_stored,
    }


def store_corporate_filings(
    records: list[dict[str, Any]],
    *,
    database_url: str | None = None,
    companies_by_symbol: dict[str, dict[str, Any]] | None = None,
    companies_by_scrip: dict[str, dict[str, Any]] | None = None,
) -> int:
    if not records:
        return 0
    db_url = get_database_url(database_url)
    if not db_url:
        return 0
    _ensure_corporate_filings_table(db_url)
    map_urls = _load_map_url_by_category_exchange(db_url)
    stored = 0
    with connect_postgres(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for record in records:
                for key in (
                    "title",
                    "description",
                    "attachment_text",
                    "attachment_url",
                    "source_url",
                    "source_uid",
                    "company_name",
                    "attachment_content_type",
                    "attachment_extracted_model",
                    "attachment_extraction_status",
                    "attachment_extraction_error",
                ):
                    if key in record:
                        record[key] = _sanitize_pg_text(record.get(key))
                if isinstance(record.get("attachment_candidates"), list):
                    cleaned_candidates: list[str] = []
                    for raw_candidate in list(record.get("attachment_candidates") or []):
                        candidate = (_sanitize_pg_text(raw_candidate) or "").strip()
                        if not candidate or _is_missing_attachment_url(candidate):
                            continue
                        if candidate not in cleaned_candidates:
                            cleaned_candidates.append(candidate)
                    record["attachment_candidates"] = cleaned_candidates
                symbol = str(record.get("symbol") or "").upper()
                scrip = str(record.get("scrip_code") or "")
                company = (companies_by_symbol or {}).get(symbol) or (companies_by_scrip or {}).get(scrip) or {}
                record["cin"] = record.get("cin") or company.get("cin")
                record["isin"] = record.get("isin") or company.get("isin")
                record["company_name"] = record.get("company_name") or company.get("company_name")
                record["source_map_url"] = map_urls.get((record["category"], record["exchange"]))
                cur.execute(
                    """
                    insert into corporate_filings_raw (
                      category, exchange, symbol, scrip_code, cin, isin, company_name,
                      announced_at, title, description, attachment_url, attachment_text,
                      attachment_text_length, attachment_sha256, attachment_content_type,
                      attachment_extracted_model, attachment_page_count,
                      attachment_extraction_status, attachment_extraction_error, source_url,
                      source_uid, source_map_url, parser_version, raw_json, fetched_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                    on conflict (exchange, source_uid) do update set
                      category = excluded.category,
                      symbol = excluded.symbol,
                      scrip_code = excluded.scrip_code,
                      cin = excluded.cin,
                      isin = excluded.isin,
                      company_name = excluded.company_name,
                      announced_at = excluded.announced_at,
                      title = excluded.title,
                      description = excluded.description,
                      attachment_url = coalesce(excluded.attachment_url, corporate_filings_raw.attachment_url),
                      attachment_text = case
                        when coalesce(excluded.attachment_text_length, 0) > 0 then excluded.attachment_text
                        else corporate_filings_raw.attachment_text
                      end,
                      attachment_text_length = greatest(
                        coalesce(corporate_filings_raw.attachment_text_length, 0),
                        coalesce(excluded.attachment_text_length, 0)
                      ),
                      attachment_sha256 = coalesce(excluded.attachment_sha256, corporate_filings_raw.attachment_sha256),
                      attachment_content_type = coalesce(excluded.attachment_content_type, corporate_filings_raw.attachment_content_type),
                      attachment_extracted_model = coalesce(excluded.attachment_extracted_model, corporate_filings_raw.attachment_extracted_model),
                      attachment_page_count = greatest(
                        coalesce(corporate_filings_raw.attachment_page_count, 0),
                        coalesce(excluded.attachment_page_count, 0)
                      ),
                      attachment_extraction_status = case
                        when coalesce(excluded.attachment_text_length, 0) > 0 then excluded.attachment_extraction_status
                        when coalesce(corporate_filings_raw.attachment_text_length, 0) > 0 then corporate_filings_raw.attachment_extraction_status
                        else excluded.attachment_extraction_status
                      end,
                      attachment_extraction_error = case
                        when coalesce(excluded.attachment_text_length, 0) > 0 then excluded.attachment_extraction_error
                        when coalesce(corporate_filings_raw.attachment_text_length, 0) > 0 then corporate_filings_raw.attachment_extraction_error
                        else excluded.attachment_extraction_error
                      end,
                      source_url = excluded.source_url,
                      source_map_url = excluded.source_map_url,
                      parser_version = excluded.parser_version,
                      raw_json = excluded.raw_json,
                      fetched_at = now()
                    """,
                    (
                        record["category"],
                        record["exchange"],
                        record.get("symbol"),
                        record.get("scrip_code"),
                        record.get("cin"),
                        record.get("isin"),
                        record.get("company_name"),
                        record.get("announced_at"),
                        record.get("title"),
                        record.get("description"),
                        record.get("attachment_url"),
                        record.get("attachment_text"),
                        int(record.get("attachment_text_length") or 0),
                        record.get("attachment_sha256"),
                        record.get("attachment_content_type"),
                        record.get("attachment_extracted_model"),
                        int(record.get("attachment_page_count") or 0),
                        record.get("attachment_extraction_status", "pending"),
                        record.get("attachment_extraction_error"),
                        record.get("source_url"),
                        record["source_uid"],
                        record.get("source_map_url"),
                        _DOCUMENT_PARSER_VERSION,
                        json.dumps(record.get("raw_json") or {}, default=str),
                    ),
                )
                stored += 1
        conn.commit()
    return stored


def run_corporate_filing_documents_scraper(
    companies: list[dict[str, Any]],
    *,
    database_url: str | None = None,
    max_companies: int | None = None,
    years_back: int = 1,
) -> dict[str, Any]:
    companies_subset = companies[:max_companies] if max_companies else companies
    companies_by_symbol = {str(co.get("nse_symbol") or "").upper(): co for co in companies_subset if co.get("nse_symbol")}
    companies_by_scrip = {str(co.get("bse_scrip_code") or ""): co for co in companies_subset if co.get("bse_scrip_code")}
    records: list[dict[str, Any]] = []
    errors = 0
    attachment_stats = {"attachments_extracted": 0, "attachments_failed": 0}
    total_companies = len(companies_subset)
    companies_with_records = 0
    error_message: str | None = None
    structured_attachment_candidates = 0
    logger.info(
        "Corporate filing document scrape starting: companies=%d, years_back=%d",
        total_companies,
        years_back,
    )
    for idx, company in enumerate(companies_subset, start=1):
        symbol = str(company.get("nse_symbol") or "").strip().upper()
        scrip = str(company.get("bse_scrip_code") or "").strip()
        before = len(records)
        logger.info(
            "Corporate filing company %d/%d starting: symbol=%s, scrip=%s, cin=%s",
            idx,
            total_companies,
            symbol or "-",
            scrip or "-",
            company.get("cin") or "-",
        )
        if symbol:
            records.extend(fetch_nse_corporate_filings(symbol, years_back=years_back))
        if scrip:
            records.extend(fetch_bse_corporate_filings(scrip, years_back=years_back))
        company_records = len(records) - before
        if company_records > 0:
            companies_with_records += 1
        logger.info(
            "Corporate filing company %d/%d done: symbol=%s, fetched=%d, cumulative=%d",
            idx,
            total_companies,
            symbol or "-",
            company_records,
            len(records),
        )

    if total_companies and not records:
        errors += 1
        error_message = (
            "No corporate filings fetched from NSE/BSE for selected companies; "
            "check source connectivity, rate limiting, symbols, and BSE scrip mappings."
        )
        logger.error(error_message)
    else:
        structured_attachment_candidates = sum(
            1
            for record in records
            if any(_is_structured_attachment_url(url) for url in _record_attachment_candidates(record))
        )
        if records and structured_attachment_candidates == 0:
            logger.warning(
                "Corporate filings fetched %d records but found 0 structured XML/XBRL/ZIP attachments; XBRL tables may remain empty for this run.",
                len(records),
            )

    stored = 0
    try:
        stored = store_corporate_filings(
            records,
            database_url=database_url,
            companies_by_symbol=companies_by_symbol,
            companies_by_scrip=companies_by_scrip,
        )
        logger.info(
            "Corporate filing metadata stored before attachment hydration: fetched=%d stored=%d",
            len(records),
            stored,
        )
    except Exception as exc:
        logger.error("Corporate filings metadata store failed: %s", exc)
        errors += 1

    if os.getenv("FINAGENT_CORP_FILINGS_EXTRACT_ATTACHMENTS", "1").strip().lower() not in {"0", "false", "no"}:
        attachment_stats = hydrate_attachment_content(records)
    else:
        logger.info("Corporate filing attachment extraction disabled by FINAGENT_CORP_FILINGS_EXTRACT_ATTACHMENTS")

    try:
        hydrated_stored = store_corporate_filings(
            records,
            database_url=database_url,
            companies_by_symbol=companies_by_symbol,
            companies_by_scrip=companies_by_scrip,
        )
        stored = max(stored, hydrated_stored)
    except Exception as exc:
        logger.error("Corporate filings store failed: %s", exc)
        errors += 1
    xbrl_stats = {"xbrl_filings": 0, "xbrl_facts": 0}
    try:
        xbrl_stats = store_xbrl_from_filing_records(records, database_url=database_url)
    except Exception as exc:
        logger.error("Corporate filings XBRL normalization failed: %s", exc)
        errors += 1
    corporate_actions_stored = 0
    try:
        corporate_actions_stored = store_corporate_actions_from_records(records, database_url=database_url)
    except Exception as exc:
        logger.error("Corporate actions normalization failed: %s", exc)
        errors += 1
    logger.info(
        "Corporate filing document scrape complete: companies=%d fetched=%d stored=%d errors=%d attachments_extracted=%d attachments_failed=%d",
        total_companies,
        len(records),
        stored,
        errors,
        attachment_stats.get("attachments_extracted", 0),
        attachment_stats.get("attachments_failed", 0),
    )
    return {
        "success": errors == 0,
        "companies_processed": len(companies_subset),
        "companies_with_records": companies_with_records,
        "records_fetched": len(records),
        "records_stored": stored,
        "errors": errors,
        "error": error_message,
        **attachment_stats,
        **xbrl_stats,
        "corporate_actions_stored": corporate_actions_stored,
        "structured_attachment_candidates": structured_attachment_candidates,
        "categories": sorted({r["category"] for r in records}),
        "parser_version": _DOCUMENT_PARSER_VERSION,
    }


def run_sebi_corporate_filing_map_scraper(database_url: str | None = None) -> dict[str, Any]:
    """Fetch, parse, and store SEBI's official corporate filing navigation map."""
    try:
        page, status = fetch_sebi_corporate_filing_page()
        if status != 200:
            return {
                "success": False,
                "records_fetched": 0,
                "records_stored": 0,
                "errors": 1,
                "categories": [],
                "http_status": status,
                "error": f"SEBI corporate filings page returned {status}",
                "parser_version": _PARSER_VERSION,
            }

        records = parse_sebi_corporate_filing_page(page)
        if not records:
            return {
                "success": False,
                "records_fetched": 0,
                "records_stored": 0,
                "errors": 1,
                "categories": [],
                "http_status": status,
                "error": "SEBI corporate filings parser returned no records",
                "parser_version": _PARSER_VERSION,
            }

        stored = store_corporate_filing_map(records, database_url)
        categories = sorted({r["category"] for r in records})
        return {
            "success": stored == len(records),
            "records_fetched": len(records),
            "records_stored": stored,
            "errors": 0 if stored == len(records) else len(records) - stored,
            "categories": categories,
            "http_status": status,
            "parser_version": _PARSER_VERSION,
        }
    except Exception as exc:
        logger.error("SEBI corporate filing map scraper failed: %s", exc)
        return {
            "success": False,
            "records_fetched": 0,
            "records_stored": 0,
            "errors": 1,
            "categories": [],
            "error": str(exc),
            "parser_version": _PARSER_VERSION,
        }
