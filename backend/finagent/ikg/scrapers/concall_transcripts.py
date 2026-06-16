"""Concall Transcript scraper for Nifty 500 companies.

Primary source: NSE corporate announcements API.
Fallback source: BSE corporate announcements API (used automatically when NSE
returns 0 results, e.g. when the VM IP is blocked by NSE India).

BSE API works from Azure/cloud IPs without any cookie or proxy requirement.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._doc_extract import (
    extract_pdf_text_local,
    text_is_sufficient,
)
from finagent.ikg.scrapers._engine import run_async
from finagent.ikg.scrapers._nse_session import apply_nse_cookies, should_skip_nse_home_visit, nse_cookie_status

logger = logging.getLogger("finagent.ikg.scrapers.concall_transcripts")

_NSE_BASE_URL = "https://www.nseindia.com"
_NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
}

_BSE_ANNOUNCEMENTS_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_BSE_BASE_URL = "https://www.bseindia.com"
_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
}

_PARSER_VERSION = "nse_concall_transcripts_v1"
_REQUEST_DELAY_S = 0.35
_DEFAULT_YEARS_BACK = 3
_DEFAULT_MAX_WORKERS = 4
_TRANSCRIPT_MODEL = os.getenv("AZURE_DI_TRANSCRIPT_MODEL", "prebuilt-layout").strip() or "prebuilt-layout"
_LOCAL_MIN_CHARS = int(os.getenv("FINAGENT_CONCALL_LOCAL_MIN_CHARS", "1500") or "1500")

_TRANSCRIPT_KEYWORDS = (
    "transcript",
    "con-call transcript",
    "conference call transcript",
    "earnings call transcript",
)
_CALL_KEYWORDS = (
    "conference call",
    "con call",
    "con-call",
    "earnings call",
    "analyst call",
    "investor call",
    "analyst meet",
    "institutional investor meet",
    "investor meet",
)
_POSITIVE_WORDS = (
    "growth",
    "improved",
    "strong",
    "resilient",
    "expansion",
    "margin expansion",
    "outperform",
    "robust",
    "healthy demand",
    "record",
)
_NEGATIVE_WORDS = (
    "decline",
    "weak",
    "pressure",
    "headwind",
    "challenging",
    "uncertain",
    "slowdown",
    "contraction",
    "margin pressure",
    "volatility",
)


def _parse_nse_datetime(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def _fiscal_quarter_meta(ts: datetime) -> tuple[str, int]:
    month = ts.month
    year = ts.year
    if 4 <= month <= 6:
        quarter = 1
        fy = year + 1
    elif 7 <= month <= 9:
        quarter = 2
        fy = year + 1
    elif 10 <= month <= 12:
        quarter = 3
        fy = year + 1
    else:
        quarter = 4
        fy = year
    return f"Q{quarter}-FY{fy}", fy


def _parse_size_mb(raw: str) -> float | None:
    text = (raw or "").strip().lower()
    if not text:
        return None
    num_match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not num_match:
        return None
    value = float(num_match.group(1))
    if "kb" in text:
        return round(value / 1024.0, 4)
    if "gb" in text:
        return round(value * 1024.0, 4)
    return round(value, 4)


def _normalize_attachment_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return _NSE_BASE_URL + url
    return url


def _normalize_bse_attachment_url(raw_url: str) -> str:
    """Normalize BSE attachment URL.

    BSE API returns just a filename like ``3ea0795b-...pdf``.
    The actual file lives at ``https://www.bseindia.com/xml-data/corpfiling/AttachLive/<name>``.
    """
    url = (raw_url or "").strip().replace("\\", "/")
    if not url:
        return ""
    if url.lower().startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return _BSE_BASE_URL + url
    # Bare filename — prepend the standard BSE attachment path
    return f"{_BSE_BASE_URL}/xml-data/corpfiling/AttachLive/{url}"


def _parse_bse_datetime(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y%m%d", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def _is_bse_concall_announcement(row: dict[str, Any]) -> bool:
    attachment = _normalize_bse_attachment_url(str(row.get("ATTACHMENTNAME") or row.get("NSURL") or ""))
    if not attachment or ".pdf" not in attachment.lower():
        return False
    title = str(row.get("NEWSSUB") or row.get("HEADLINE") or "")
    more = str(row.get("MORE") or row.get("MORETEXT") or "")
    haystack = f"{title} {more} {attachment}".lower()
    has_transcript = any(k in haystack for k in _TRANSCRIPT_KEYWORDS)
    has_call_context = any(k in haystack for k in _CALL_KEYWORDS)
    return has_transcript and has_call_context


def _is_transcript_announcement(item: dict[str, Any]) -> bool:
    attachment = _normalize_attachment_url(str(item.get("attchmntFile") or ""))
    if not attachment or ".pdf" not in attachment.lower():
        return False
    desc = str(item.get("desc") or "")
    text = str(item.get("attchmntText") or "")
    haystack = f"{desc} {text} {attachment}".lower()
    has_transcript = any(k in haystack for k in _TRANSCRIPT_KEYWORDS)
    has_call_context = any(k in haystack for k in _CALL_KEYWORDS)
    return has_transcript and has_call_context


def _score_sentiment(text: str) -> tuple[str, float]:
    lowered = (text or "").lower()
    if not lowered.strip():
        return "unknown", 0.0
    pos = sum(lowered.count(word) for word in _POSITIVE_WORDS)
    neg = sum(lowered.count(word) for word in _NEGATIVE_WORDS)
    score = round((pos - neg) / max(pos + neg, 1), 3)
    if score > 0.2:
        return "positive", score
    if score < -0.2:
        return "negative", score
    return "neutral", score


def _extract_intent_tags(text: str) -> list[str]:
    lowered = (text or "").lower()
    tags: set[str] = set()
    patterns = {
        "guidance_up": ("raise guidance", "upward revision", "improved outlook"),
        "guidance_down": ("lower guidance", "downward revision", "weak outlook"),
        "capex_expansion": ("capex", "capital expenditure", "capacity expansion"),
        "deleveraging": ("debt reduction", "deleveraging", "net debt"),
        "margin_focus": ("ebitda margin", "margin expansion", "operating margin"),
        "demand_softness": ("weak demand", "demand slowdown", "slowdown"),
    }
    for tag, keys in patterns.items():
        if any(key in lowered for key in keys):
            tags.add(tag)
    return sorted(tags)


def fetch_nse_concall_announcements(
    symbol: str,
    *,
    years_back: int = _DEFAULT_YEARS_BACK,
    timeout_s: float = 45.0,
) -> list[dict[str, Any]]:
    years = max(1, int(years_back))
    today = datetime.now(UTC).date()
    since = today - timedelta(days=365 * years)
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
            resp = client.get(_NSE_ANNOUNCEMENTS_URL, headers=req_headers, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.debug("NSE concall announcement fetch failed for %s: %s", symbol, exc)
        return []

    if not isinstance(payload, list):
        return []

    selected: dict[str, dict[str, Any]] = {}
    max_records = max(4, years * 4)
    for row in payload:
        if not isinstance(row, dict):
            continue
        if not _is_transcript_announcement(row):
            continue
        announced_at = _parse_nse_datetime(str(row.get("an_dt") or ""))
        if announced_at is None:
            continue
        quarter_label, fiscal_year = _fiscal_quarter_meta(announced_at)
        attachment_url = _normalize_attachment_url(str(row.get("attchmntFile") or ""))
        record = {
            "symbol": str(row.get("symbol") or symbol).strip().upper(),
            "company_name": str(row.get("sm_name") or "").strip(),
            "isin": str(row.get("sm_isin") or "").strip(),
            "announced_at": announced_at,
            "quarter_label": quarter_label,
            "fiscal_year": fiscal_year,
            "subject": str(row.get("desc") or "").strip(),
            "description": str(row.get("attchmntText") or "").strip(),
            "attachment_url": attachment_url,
            "attachment_size_mb": _parse_size_mb(str(row.get("attFileSize") or row.get("fileSize") or "")),
            "raw_json": row,
        }
        previous = selected.get(quarter_label)
        if previous is None or previous["announced_at"] < announced_at:
            selected[quarter_label] = record

    rows = sorted(selected.values(), key=lambda x: x["announced_at"], reverse=True)
    return rows[:max_records]


def fetch_bse_concall_announcements(
    scrip_code: str,
    *,
    years_back: int = _DEFAULT_YEARS_BACK,
    timeout_s: float = 45.0,
) -> list[dict[str, Any]]:
    """Fetch concall announcements from BSE API — works from cloud IPs without cookie injection."""
    years = max(1, int(years_back))
    today = datetime.now(UTC).date()
    since = today - timedelta(days=365 * years)
    max_pages = max(2, years)
    selected: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
        for page_no in range(1, max_pages + 1):
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
                resp = client.get(_BSE_ANNOUNCEMENTS_API, headers=_BSE_HEADERS, params=params)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:
                logger.debug("BSE concall fetch failed for scrip %s page %d: %s", scrip_code, page_no, exc)
                break

            rows = payload.get("Table") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                if not _is_bse_concall_announcement(row):
                    continue
                announced_at = _parse_bse_datetime(str(row.get("DT_TM") or row.get("NEWS_DT") or ""))
                if announced_at is None:
                    continue
                quarter_label, fiscal_year = _fiscal_quarter_meta(announced_at)
                attachment_url = _normalize_bse_attachment_url(str(row.get("ATTACHMENTNAME") or row.get("NSURL") or ""))
                record = {
                    "exchange": "BSE",
                    "symbol": None,
                    "company_name": str(row.get("SLONGNAME") or "").strip(),
                    "isin": None,
                    "announced_at": announced_at,
                    "quarter_label": quarter_label,
                    "fiscal_year": fiscal_year,
                    "subject": str(row.get("NEWSSUB") or row.get("HEADLINE") or "").strip(),
                    "description": "",
                    "attachment_url": attachment_url,
                    "attachment_size_mb": None,
                    "raw_json": row,
                }
                prev = selected.get(quarter_label)
                if prev is None or prev["announced_at"] < announced_at:
                    selected[quarter_label] = record

            if len(rows) < 50:
                break

    max_records = max(4, years * 4)
    return sorted(selected.values(), key=lambda x: x["announced_at"], reverse=True)[:max_records]


def _extract_transcript_text(pdf_url: str, timeout_s: float = 180.0) -> dict[str, Any]:
    if not pdf_url:
        return {"full_text": "", "model": None, "page_count": 0, "error": "missing attachment url"}

    # Use BSE headers for BSE URLs, NSE cookies+headers for NSE URLs
    if "bseindia.com" in pdf_url.lower():
        dl_headers = _BSE_HEADERS
    else:
        dl_headers = apply_nse_cookies(_NSE_HEADERS)

    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            resp = client.get(pdf_url, headers=dl_headers)
            resp.raise_for_status()
            file_bytes = resp.content
            if len(file_bytes) < 1024:
                return {"full_text": "", "model": None, "page_count": 0, "error": "attachment too small"}
    except Exception as exc:
        return {"full_text": "", "model": None, "page_count": 0, "error": str(exc)}

    local = extract_pdf_text_local(file_bytes)
    local_text = str(local.get("full_text") or "")
    if text_is_sufficient(local_text, min_chars=_LOCAL_MIN_CHARS):
        return {
            "full_text": local_text,
            "model": local.get("model") or "pymupdf_local",
            "page_count": int(local.get("page_count") or 0),
            "error": None,
        }

    try:
        from finagent.ingestion.azure_doc_intel import extract_document

        result = run_async(
            extract_document(
                file_bytes=file_bytes,
                model_id=_TRANSCRIPT_MODEL,
                allow_fallback=True,
                timeout_s=timeout_s,
            )
        )
        return {
            "full_text": result.full_text or "",
            "model": result.model_used,
            "page_count": result.page_count,
            "error": None,
        }
    except Exception as exc:
        if local_text.strip():
            return {
                "full_text": local_text,
                "model": local.get("model") or "pymupdf_local",
                "page_count": int(local.get("page_count") or 0),
                "error": str(exc),
            }
        return {"full_text": "", "model": None, "page_count": 0, "error": str(exc)}


def store_concall_transcript(
    record: dict[str, Any],
    database_url: str | None = None,
) -> bool:
    db_url = get_database_url(database_url)
    if not db_url:
        return False

    try:
        with connect_postgres(db_url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into concall_transcripts_raw (
                      symbol, company_name, cin, isin, exchange, announced_at,
                      quarter_label, fiscal_year, subject, description,
                      attachment_url, attachment_size_mb, transcript_text, text_length,
                      extracted_model, extraction_status, sentiment_label,
                      sentiment_score, intent_tags_json, raw_json, source_url,
                      parser_version, fetched_at
                    )
                    values (
                      %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s,
                      %s, %s::jsonb, %s::jsonb, %s,
                      %s, now()
                    )
                    on conflict (symbol, announced_at, attachment_url) do update set
                      subject = excluded.subject,
                      description = excluded.description,
                      transcript_text = excluded.transcript_text,
                      text_length = excluded.text_length,
                      extracted_model = excluded.extracted_model,
                      extraction_status = excluded.extraction_status,
                      sentiment_label = excluded.sentiment_label,
                      sentiment_score = excluded.sentiment_score,
                      intent_tags_json = excluded.intent_tags_json,
                      raw_json = excluded.raw_json,
                      parser_version = excluded.parser_version,
                      fetched_at = now()
                    """,
                    (
                        record.get("symbol"),
                        record.get("company_name"),
                        record.get("cin"),
                        record.get("isin"),
                        "NSE",
                        record.get("announced_at"),
                        record.get("quarter_label"),
                        record.get("fiscal_year"),
                        record.get("subject"),
                        record.get("description"),
                        record.get("attachment_url"),
                        record.get("attachment_size_mb"),
                        record.get("transcript_text") or "",
                        int(record.get("text_length") or 0),
                        record.get("extracted_model"),
                        record.get("extraction_status"),
                        record.get("sentiment_label"),
                        float(record.get("sentiment_score") or 0.0),
                        json.dumps(record.get("intent_tags") or []),
                        json.dumps(record.get("raw_json") or {}),
                        _NSE_ANNOUNCEMENTS_URL,
                        _PARSER_VERSION,
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("Concall transcript store failed for %s: %s", record.get("symbol"), exc)
        return False


def _index_concall_to_graphrag(record: dict[str, Any]) -> int:
    text = str(record.get("transcript_text") or "").strip()
    if len(text) < 80:
        return 0
    try:
        from finagent.graphrag.indexer import index_document, store_chunks_to_cache

        chunks = index_document(
            text,
            source_file=str(record.get("attachment_url") or ""),
            source_type="concall_transcript",
            company_cin=record.get("cin"),
            company_ticker=record.get("symbol"),
        )
        if not chunks:
            return 0
        store_chunks_to_cache(chunks, str(record.get("symbol") or "UNKNOWN"))
        return len(chunks)
    except Exception as exc:
        logger.warning("Concall GraphRAG indexing failed for %s: %s", record.get("symbol"), exc)
        return 0


async def _write_concall_to_ikg(record: dict[str, Any]) -> int:
    cin = str(record.get("cin") or "").strip().upper()
    if not cin:
        return 0

    from finagent.ikg.graph_client import get_graph_client

    client = get_graph_client()
    company_vertex_id = f"company:{cin}"
    company_props: dict[str, Any] = {"cin": cin}
    symbol = str(record.get("symbol") or "").strip().upper()
    if symbol:
        company_props["symbol"] = symbol
    company_name = str(record.get("company_name") or "").strip()
    if company_name:
        company_props["name"] = company_name
    # Concall scraper can run before full graph build; ensure source vertex exists
    # so edge upsert never violates FK constraints on ikg_edges.from_vertex_id.
    await client.upsert_vertex(
        company_vertex_id,
        "Company",
        company_props,
    )
    doc_key = hashlib.sha1(
        f"{record.get('symbol')}|{record.get('announced_at')}|{record.get('attachment_url')}".encode("utf-8")
    ).hexdigest()[:20]
    doc_vertex_id = f"document:concall:{doc_key}"
    await client.upsert_vertex(
        doc_vertex_id,
        "Document",
        {
            "document_type": "concall_transcript",
            "symbol": record.get("symbol"),
            "quarter": record.get("quarter_label"),
            "announced_at": str(record.get("announced_at") or ""),
            "source_url": record.get("attachment_url"),
            "sentiment_label": record.get("sentiment_label"),
            "sentiment_score": record.get("sentiment_score"),
        },
    )
    await client.upsert_edge(
        company_vertex_id,
        doc_vertex_id,
        "HAS_CONCALL_TRANSCRIPT",
        {
            "quarter": record.get("quarter_label"),
            "fiscal_year": record.get("fiscal_year"),
            "announced_at": str(record.get("announced_at") or ""),
            "sentiment_label": record.get("sentiment_label"),
            "sentiment_score": record.get("sentiment_score"),
            "source_citation": "NSE_corporate_announcements",
        },
    )
    return 1


def _process_company(
    company: dict[str, Any],
    *,
    years_back: int,
    database_url: str | None,
) -> dict[str, int]:
    symbol = str(company.get("nse_symbol") or "").strip().upper()
    scrip_code = str(company.get("bse_scrip_code") or "").strip()
    cin = str(company.get("cin") or "").strip().upper() or None
    if not symbol:
        return {
            "announcements_fetched": 0,
            "transcripts_stored": 0,
            "transcripts_failed": 0,
            "chunks_indexed": 0,
            "edges_written": 0,
        }

    announcements = fetch_nse_concall_announcements(symbol, years_back=years_back)
    # Fallback to BSE if NSE returns nothing (e.g., due to cloud IP 403 blocking)
    if not announcements and scrip_code:
        logger.info("NSE concall returned 0 results for %s — trying BSE fallback (scrip %s)", symbol, scrip_code)
        announcements = fetch_bse_concall_announcements(scrip_code, years_back=years_back)
        if announcements:
            logger.info("BSE fallback found %d concall announcements for %s", len(announcements), symbol)
            for ann in announcements:
                ann["symbol"] = symbol
    stored = 0
    failed = 0
    chunks_indexed = 0
    edges_written = 0

    for announcement in announcements:
        time.sleep(_REQUEST_DELAY_S)
        extracted = _extract_transcript_text(str(announcement.get("attachment_url") or ""))
        text = str(extracted.get("full_text") or "")
        sentiment_label, sentiment_score = _score_sentiment(text)
        intent_tags = _extract_intent_tags(text)
        record = {
            **announcement,
            "cin": cin,
            "transcript_text": text,
            "text_length": len(text),
            "extracted_model": extracted.get("model"),
            "extraction_status": "ok" if not extracted.get("error") and text.strip() else "failed",
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "intent_tags": intent_tags,
        }

        persisted = store_concall_transcript(record, database_url=database_url)
        if not persisted:
            failed += 1
            continue

        stored += 1
        chunks_indexed += _index_concall_to_graphrag(record)
        try:
            edges_written += run_async(_write_concall_to_ikg(record))
        except Exception as exc:
            logger.warning("Concall IKG write failed for %s: %s", symbol, exc)

        if record["extraction_status"] != "ok":
            failed += 1

    return {
        "announcements_fetched": len(announcements),
        "transcripts_stored": stored,
        "transcripts_failed": failed,
        "chunks_indexed": chunks_indexed,
        "edges_written": edges_written,
    }


def run_concall_transcript_scraper(
    companies: list[dict[str, Any]],
    *,
    database_url: str | None = None,
    max_companies: int | None = None,
    years_back: int = _DEFAULT_YEARS_BACK,
    max_workers: int | None = None,
) -> dict[str, Any]:
    companies_subset = companies[:max_companies] if max_companies else companies
    workers = max_workers or int(os.getenv("FINAGENT_CONCALL_MAX_WORKERS", str(_DEFAULT_MAX_WORKERS)))
    workers = max(1, workers)

    announcements_fetched = 0
    transcripts_stored = 0
    transcripts_failed = 0
    chunks_indexed = 0
    edges_written = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _process_company,
                co,
                years_back=years_back,
                database_url=database_url,
            ): co
            for co in companies_subset
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            co = futures[future]
            symbol = str(co.get("nse_symbol") or "")
            try:
                stats = future.result()
                announcements_fetched += int(stats.get("announcements_fetched") or 0)
                transcripts_stored += int(stats.get("transcripts_stored") or 0)
                transcripts_failed += int(stats.get("transcripts_failed") or 0)
                chunks_indexed += int(stats.get("chunks_indexed") or 0)
                edges_written += int(stats.get("edges_written") or 0)
            except Exception as exc:
                errors += 1
                logger.error("Concall worker failed for %s: %s", symbol, exc)

            if idx % 25 == 0:
                logger.info(
                    "Concall progress: %d/%d companies, %d transcripts stored",
                    idx, len(companies_subset), transcripts_stored,
                )

    return {
        "companies_processed": len(companies_subset),
        "announcements_fetched": announcements_fetched,
        "transcripts_stored": transcripts_stored,
        "transcripts_failed": transcripts_failed,
        "chunks_indexed": chunks_indexed,
        "edges_written": edges_written,
        "errors": errors,
        "success": errors == 0 and transcripts_failed == 0,
        "parser_version": _PARSER_VERSION,
    }


if __name__ == "__main__":
    from finagent.ikg.scrapers.mca_companies import get_listed_companies

    companies = get_listed_companies()
    print(
        run_concall_transcript_scraper(
            companies,
            max_companies=5,
            years_back=3,
        )
    )
