"""NSE/BSE corporate governance director scraper.

This scraper uses official exchange corporate-announcement filings as the
scalable director source for listed companies. MCA remains the legal verifier,
but the exchange governance filings are much more practical for Nifty 500
coverage because they are quarterly/public documents and do not require CAPTCHA.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._doc_extract import (
    decode_text_bytes,
    extract_pdf_text_local,
    text_is_sufficient,
)
from finagent.ikg.scrapers._engine import run_async
from finagent.ikg.scrapers._nse_session import apply_nse_cookies, should_skip_nse_home_visit

logger = logging.getLogger("finagent.ikg.scrapers.corporate_governance_directors")

_NSE_BASE_URL = "https://www.nseindia.com"
_NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
_NSE_GOVERNANCE_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-governance"
_NSE_GOVERNANCE_MASTER_URL = "https://www.nseindia.com/api/corporate-governance-master"
_NSE_GOVERNANCE_DETAIL_URL = "https://www.nseindia.com/api/corporate-governance"
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
_BSE_HEADERS = {
    "User-Agent": _NSE_HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
}

_PARSER_VERSION = "corporate_governance_directors_v1"
_DEFAULT_YEARS_BACK = 2
_DEFAULT_MAX_WORKERS = 4
_DEFAULT_FILINGS_PER_COMPANY = 4
_REQUEST_DELAY_S = float(os.getenv("FINAGENT_GOVERNANCE_DIRECTOR_REQUEST_DELAY_S", "0.35"))
_DI_MODEL = os.getenv("AZURE_DI_GOVERNANCE_MODEL", "prebuilt-layout").strip() or "prebuilt-layout"
_LOCAL_MIN_CHARS = int(os.getenv("FINAGENT_GOVERNANCE_LOCAL_MIN_CHARS", "1200") or "1200")

_GOVERNANCE_KEYWORDS = (
    "corporate governance",
    "integrated filing governance",
    "integrated governance",
    "regulation 27",
    "board composition",
)
_DIRECTOR_STOP_WORDS = {
    "category",
    "executive",
    "independent",
    "non-executive",
    "chairperson",
    "director",
    "not applicable",
    "date",
    "tenure",
    "pan",
    "din",
}


def _normalize_attachment_url(raw_url: str, base_url: str = _NSE_BASE_URL) -> str:
    url = (raw_url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin(base_url, url)
    return url


def _parse_nse_datetime(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def _fiscal_quarter_meta(ts: datetime | None) -> tuple[str, int | None]:
    if ts is None:
        return "", None
    month = ts.month
    year = ts.year
    if 4 <= month <= 6:
        return f"Q1-FY{year + 1}", year + 1
    if 7 <= month <= 9:
        return f"Q2-FY{year + 1}", year + 1
    if 10 <= month <= 12:
        return f"Q3-FY{year + 1}", year + 1
    return f"Q4-FY{year}", year


def _parse_date(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value or value in {"-", "--", "NA", "N.A.", "Not Applicable"}:
        return None
    value = value.replace("/", "-").replace(".", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _clean_name(raw: str) -> str:
    name = re.sub(r"[^A-Za-z .'-]", " ", raw or "")
    name = re.sub(r"\b(?:Mr|Mrs|Ms|Dr|Shri|Smt|CA|Prof)\.?\b", " ", name, flags=re.I)
    name = " ".join(name.split()).strip(" .'-")
    tokens = []
    for token in name.split():
        lowered = token.lower()
        if lowered in _DIRECTOR_STOP_WORDS:
            break
        tokens.append(token)
    return " ".join(tokens).strip()


def _is_plausible_director_name(name: str) -> bool:
    if not name:
        return False
    if len(name) < 4 or len(name) > 120:
        return False
    tokens = name.split()
    if len(tokens) < 2:
        return False
    lowered = name.lower()
    if any(word in lowered for word in ("committee", "shareholder", "meeting", "regulation", "compliance")):
        return False
    return True


def _infer_designation(rest: str) -> str:
    text = (rest or "").lower()
    parts: list[str] = []
    if "chair" in text:
        parts.append("Chairperson")
    if "managing director" in text or re.search(r"\bmd\b", text):
        parts.append("Managing Director")
    elif "whole time" in text or "wholetime" in text:
        parts.append("Whole-time Director")
    elif "executive" in text:
        parts.append("Executive Director")
    elif "non-executive" in text or "non executive" in text:
        parts.append("Non-Executive Director")
    if "independent" in text:
        parts.append("Independent Director")
    if "nominee" in text:
        parts.append("Nominee Director")
    return ", ".join(dict.fromkeys(parts)) or "Director"


def parse_governance_directors_from_text(
    text: str,
    *,
    cin: str,
    nse_symbol: str | None = None,
    bse_scrip_code: str | None = None,
    source_url: str = "",
    quarter: str = "",
) -> list[dict[str, Any]]:
    """Extract director rows from exchange governance text/XML/PDF text."""
    if not text or not cin:
        return []

    normalized = re.sub(r"[\t\r]+", " ", text)
    normalized = re.sub(r" +", " ", normalized)
    candidates: dict[str, dict[str, Any]] = {}

    xmlish_rows = re.findall(
        r"<[^>]*(?:Director|Board)[^>]*>.*?</[^>]*(?:Director|Board)[^>]*>",
        normalized,
        flags=re.I | re.S,
    )
    for row in xmlish_rows:
        din_match = re.search(r"<[^>]*(?:DIN|DirectorIdentificationNumber)[^>]*>\s*(\d{8})\s*</", row, re.I)
        name_match = re.search(r"<[^>]*(?:NameOfDirector|DirectorName|Name)[^>]*>\s*([^<]{4,160})\s*</", row, re.I)
        if not din_match or not name_match:
            continue
        din = din_match.group(1)
        name = _clean_name(name_match.group(1))
        if not _is_plausible_director_name(name):
            continue
        candidates[din] = {
            "cin": cin,
            "din": din,
            "name": name,
            "designation": _infer_designation(row),
            "appointment_date": _parse_date(row),
            "cessation_date": None,
            "source": "exchange_corporate_governance",
            "source_url": source_url,
            "quarter": quarter,
            "nse_symbol": nse_symbol,
            "bse_scrip_code": bse_scrip_code,
        }

    lines = [line.strip() for line in re.split(r"\n+", normalized) if line.strip()]
    joined_windows: list[str] = []
    for idx, line in enumerate(lines):
        joined_windows.append(line)
        if idx + 1 < len(lines):
            joined_windows.append(f"{line} {lines[idx + 1]}")

    for line in joined_windows:
        if not re.search(r"\b\d{8}\b", line):
            continue
        for match in re.finditer(r"\b(\d{8})\b", line):
            din = match.group(1)
            left = line[: match.start()].strip(" :-|")
            right = line[match.end() :].strip(" :-|")
            name = _clean_name(left[-150:])
            rest = right
            if not _is_plausible_director_name(name):
                name_match = re.match(r"([A-Za-z .'-]{4,120})", right)
                name = _clean_name(name_match.group(1) if name_match else "")
                rest = right[name_match.end() :] if name_match else right
            if not _is_plausible_director_name(name):
                continue
            dates = re.findall(r"\b\d{1,2}[-/.][A-Za-z]{3}[-/.]\d{4}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}\b", line)
            candidates[din] = {
                "cin": cin,
                "din": din,
                "name": name,
                "designation": _infer_designation(rest),
                "appointment_date": _parse_date(dates[0]) if dates else None,
                "cessation_date": _parse_date(dates[-1]) if len(dates) > 1 else None,
                "source": "exchange_corporate_governance",
                "source_url": source_url,
                "quarter": quarter,
                "nse_symbol": nse_symbol,
                "bse_scrip_code": bse_scrip_code,
            }

    return sorted(candidates.values(), key=lambda row: row["din"])


def parse_governance_directors_from_payload(
    payload: dict[str, Any],
    *,
    cin: str,
    nse_symbol: str | None = None,
    bse_scrip_code: str | None = None,
    source_url: str = "",
    quarter: str = "",
) -> list[dict[str, Any]]:
    """Extract board-composition rows from NSE corporate-governance JSON."""
    if not payload or not cin:
        return []

    board_rows: list[dict[str, Any]] = []
    for container in payload.get("cobod") or []:
        data = container.get("data") if isinstance(container, dict) else {}
        rows = data.get("CompositionBOD") if isinstance(data, dict) else []
        if isinstance(rows, list):
            board_rows.extend(row for row in rows if isinstance(row, dict))

    directors: dict[str, dict[str, Any]] = {}
    for row in board_rows:
        din = re.sub(r"\D", "", str(row.get("din") or ""))
        if len(din) != 8:
            continue
        name = _clean_name(str(row.get("directorName") or ""))
        if not _is_plausible_director_name(name):
            continue
        category = str(row.get("category") or "Director").strip() or "Director"
        directors[din] = {
            "cin": cin,
            "din": din,
            "name": name,
            "designation": category,
            "appointment_date": _parse_date(
                str(row.get("dateOfAppointment") or row.get("dateOfInitialAppo") or row.get("date") or "")
            ),
            "cessation_date": _parse_date(str(row.get("dateOfCessation") or "")),
            "source": "exchange_corporate_governance",
            "source_url": source_url,
            "quarter": quarter,
            "nse_symbol": nse_symbol,
            "bse_scrip_code": bse_scrip_code,
            "raw": {
                "category": category,
                "status": row.get("status"),
                "committee_memberships": row.get("membershipinCommofCompany"),
                "no_of_directorships": row.get("noOfDirShp"),
                "no_of_independent_directorships": row.get("noOfindpntDirShp"),
                "dir_is_disqualified": row.get("dirIsdisqualified"),
                "tenure": row.get("tenure"),
            },
        }

    return sorted(directors.values(), key=lambda row: row["din"])


def _is_governance_announcement(item: dict[str, Any]) -> bool:
    attachment = _normalize_attachment_url(str(item.get("attchmntFile") or ""))
    if not attachment:
        return False
    desc = str(item.get("desc") or "")
    text = str(item.get("attchmntText") or "")
    haystack = f"{desc} {text} {attachment}".lower()
    return any(keyword in haystack for keyword in _GOVERNANCE_KEYWORDS)


def fetch_nse_governance_filings(
    symbol: str,
    *,
    years_back: int = _DEFAULT_YEARS_BACK,
    timeout_s: float = 45.0,
) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            req_headers = apply_nse_cookies(_NSE_HEADERS)
            if not should_skip_nse_home_visit():
                client.get(_NSE_GOVERNANCE_PAGE, headers=req_headers)
            resp = client.get(
                _NSE_GOVERNANCE_MASTER_URL,
                headers=req_headers,
                params={"index": "equities", "symbol": symbol.upper()},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.debug("NSE governance filing fetch failed for %s: %s", symbol, exc)
        return []

    rows = payload.get("data") if isinstance(payload, dict) else []
    records: list[dict[str, Any]] = []
    min_date = datetime.now(UTC) - timedelta(days=365 * max(1, int(years_back)))
    for item in rows:
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("recordId") or "").strip()
        if not record_id:
            continue
        announced_at = _parse_nse_datetime(str(item.get("submissionDate") or item.get("cgTimeStamp") or ""))
        if announced_at and announced_at < min_date:
            continue
        quarter, fiscal_year = _fiscal_quarter_meta(announced_at)
        xbrl_url = _normalize_attachment_url(str(item.get("xbrl") or ""), base_url=_NSE_BASE_URL)
        detail_url = f"{_NSE_GOVERNANCE_DETAIL_URL}?recId={record_id}"
        records.append(
            {
                "exchange": "NSE",
                "symbol": symbol.upper(),
                "title": f"Corporate Governance - {item.get('date') or item.get('submissionDate') or record_id}",
                "category": "Corporate Governance",
                "announced_at": announced_at.isoformat() if announced_at else "",
                "quarter": quarter,
                "fiscal_year": fiscal_year,
                "record_id": record_id,
                "attachment_url": detail_url,
                "xbrl_url": xbrl_url,
                "raw": item,
            }
        )

    records.sort(key=lambda row: row.get("announced_at") or "", reverse=True)
    return records


def fetch_nse_governance_detail(record_id: str, timeout_s: float = 45.0) -> dict[str, Any]:
    if not record_id:
        return {}
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            req_headers = apply_nse_cookies(_NSE_HEADERS)
            if not should_skip_nse_home_visit():
                client.get(_NSE_GOVERNANCE_PAGE, headers=req_headers)
            resp = client.get(_NSE_GOVERNANCE_DETAIL_URL, headers=req_headers, params={"recId": record_id})
            resp.raise_for_status()
            payload = resp.json()
            return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.debug("NSE governance detail fetch failed for recId=%s: %s", record_id, exc)
        return {}


def _extract_document_text(url: str, timeout_s: float = 180.0) -> dict[str, Any]:
    if not url:
        return {"full_text": "", "model": None, "page_count": 0, "error": "missing url"}
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            h = apply_nse_cookies(_NSE_HEADERS) if "nseindia" in url else _BSE_HEADERS
            resp = client.get(url, headers=h)
            resp.raise_for_status()
            file_bytes = resp.content
            if len(file_bytes) < 512:
                return {"full_text": "", "model": None, "page_count": 0, "error": "attachment too small"}
    except Exception as exc:
        return {"full_text": "", "model": None, "page_count": 0, "error": str(exc)}

    lowered = url.lower().split("?")[0]
    if lowered.endswith((".xml", ".xbrl", ".txt", ".csv")):
        try:
            return {"full_text": decode_text_bytes(file_bytes), "model": "raw_text", "page_count": 0, "error": None}
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
                model_id=_DI_MODEL,
                allow_fallback=True,
                timeout_s=timeout_s,
            )
        )
        if result.full_text and result.full_text.strip():
            return {
                "full_text": result.full_text or "",
                "model": result.model_used,
                "page_count": result.page_count,
                "error": None,
            }
    except Exception as exc:
        logger.debug("Azure DI governance extraction failed for %s: %s", url, exc)
    if local_text.strip():
        return {
            "full_text": local_text,
            "model": local.get("model") or "pymupdf_local",
            "page_count": int(local.get("page_count") or 0),
            "error": local.get("error"),
        }
    return {"full_text": "", "model": None, "page_count": 0, "error": str(local.get("error") or "extraction failed")}


def _ensure_director_tables(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            alter table directors_raw
              add column if not exists source varchar(80),
              add column if not exists source_url text,
              add column if not exists quarter varchar(20),
              add column if not exists nse_symbol varchar(20),
              add column if not exists bse_scrip_code varchar(10),
              add column if not exists confidence_score numeric(5,2)
            """
        )
        cur.execute(
            """
            create table if not exists director_source_records (
                id bigserial primary key,
                source varchar(80) not null,
                cin varchar(21),
                nse_symbol varchar(20),
                bse_scrip_code varchar(10),
                quarter varchar(20),
                filing_url text not null,
                title text,
                raw_json jsonb default '{}'::jsonb,
                extracted_text text,
                parser_version varchar(80) default 'corporate_governance_directors_v1',
                status varchar(40) not null,
                error text,
                fetched_at timestamptz default now(),
                unique (source, filing_url)
            )
            """
        )
        cur.execute(
            "create index if not exists idx_director_source_records_cin on director_source_records(cin)"
        )
        cur.execute(
            "create index if not exists idx_director_source_records_status on director_source_records(status, fetched_at desc)"
        )
    conn.commit()


def _store_source_record(record: dict[str, Any], database_url: str | None = None) -> int:
    db_url = get_database_url(database_url)
    if not db_url:
        return 0
    with connect_postgres(db_url, connect_timeout=30) as conn:
        _ensure_director_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into director_source_records (
                    source, cin, nse_symbol, bse_scrip_code, quarter, filing_url,
                    title, raw_json, extracted_text, parser_version, status, error, fetched_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, now())
                on conflict (source, filing_url) do update set
                    cin = excluded.cin,
                    nse_symbol = excluded.nse_symbol,
                    bse_scrip_code = excluded.bse_scrip_code,
                    quarter = excluded.quarter,
                    title = excluded.title,
                    raw_json = excluded.raw_json,
                    extracted_text = excluded.extracted_text,
                    parser_version = excluded.parser_version,
                    status = excluded.status,
                    error = excluded.error,
                    fetched_at = now()
                """,
                (
                    record["source"],
                    record.get("cin"),
                    record.get("nse_symbol"),
                    record.get("bse_scrip_code"),
                    record.get("quarter"),
                    record["filing_url"],
                    record.get("title"),
                    json.dumps(record.get("raw_json") or {}, default=str),
                    record.get("extracted_text"),
                    _PARSER_VERSION,
                    record.get("status") or "unknown",
                    record.get("error"),
                ),
            )
        conn.commit()
    return 1


def store_governance_directors_to_postgres(
    directors: list[dict[str, Any]],
    database_url: str | None = None,
) -> int:
    db_url = get_database_url(database_url)
    if not db_url or not directors:
        return 0

    upserted = 0
    with connect_postgres(db_url, connect_timeout=30) as conn:
        _ensure_director_tables(conn)
        with conn.cursor() as cur:
            for d in directors:
                cur.execute(
                    """
                    insert into directors_raw (
                        cin, din, name, designation, appointment_date, cessation_date,
                        source, source_url, quarter, nse_symbol, bse_scrip_code,
                        confidence_score, fetched_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    on conflict (cin, din) do update set
                        name = excluded.name,
                        designation = excluded.designation,
                        appointment_date = coalesce(excluded.appointment_date, directors_raw.appointment_date),
                        cessation_date = coalesce(excluded.cessation_date, directors_raw.cessation_date),
                        source = excluded.source,
                        source_url = excluded.source_url,
                        quarter = excluded.quarter,
                        nse_symbol = excluded.nse_symbol,
                        bse_scrip_code = excluded.bse_scrip_code,
                        confidence_score = excluded.confidence_score,
                        fetched_at = now()
                    """,
                    (
                        d["cin"],
                        d["din"],
                        d["name"],
                        d.get("designation") or "Director",
                        d.get("appointment_date"),
                        d.get("cessation_date"),
                        d.get("source") or "exchange_corporate_governance",
                        d.get("source_url"),
                        d.get("quarter"),
                        d.get("nse_symbol"),
                        d.get("bse_scrip_code"),
                        0.85,
                    ),
                )
                upserted += 1
        conn.commit()
    return upserted


def _process_company(
    company: dict[str, Any],
    *,
    database_url: str | None,
    years_back: int,
    filings_per_company: int,
) -> dict[str, int]:
    symbol = str(company.get("nse_symbol") or "").strip().upper()
    cin = str(company.get("cin") or "").strip()
    if not symbol or not cin:
        return {"companies_processed": 0, "filings_found": 0, "filings_processed": 0, "directors_found": 0, "directors_stored": 0, "errors": 0}

    time.sleep(_REQUEST_DELAY_S)
    filings = fetch_nse_governance_filings(symbol, years_back=years_back)
    selected = filings[: max(1, filings_per_company)]
    directors_by_din: dict[str, dict[str, Any]] = {}
    errors = 0
    processed = 0

    for filing in selected:
        url = str(filing.get("attachment_url") or "")
        detail_payload = fetch_nse_governance_detail(str(filing.get("record_id") or ""))
        status = "parsed"
        error = ""
        if not detail_payload:
            status = "extract_failed"
            error = "empty governance detail payload"
            errors += 1

        quarter = str(filing.get("quarter") or "")
        directors = parse_governance_directors_from_payload(
            detail_payload,
            cin=cin,
            nse_symbol=symbol,
            bse_scrip_code=company.get("bse_scrip_code"),
            source_url=url,
            quarter=quarter,
        )
        if status == "parsed" and not directors:
            status = "no_directors_parsed"

        _store_source_record(
            {
                "source": "NSE_corporate_governance",
                "cin": cin,
                "nse_symbol": symbol,
                "bse_scrip_code": company.get("bse_scrip_code"),
                "quarter": quarter,
                "filing_url": url,
                "title": filing.get("title"),
                "raw_json": {"filing": filing, "detail": detail_payload},
                "extracted_text": "",
                "status": status,
                "error": str(error or ""),
            },
            database_url,
        )

        processed += 1
        for director in directors:
            directors_by_din[director["din"]] = director

    stored = store_governance_directors_to_postgres(list(directors_by_din.values()), database_url)
    return {
        "companies_processed": 1,
        "filings_found": len(filings),
        "filings_processed": processed,
        "directors_found": len(directors_by_din),
        "directors_stored": stored,
        "errors": errors,
    }


def run_corporate_governance_director_scraper(
    companies: list[dict[str, Any]],
    database_url: str | None = None,
    max_companies: int | None = None,
    years_back: int = _DEFAULT_YEARS_BACK,
    filings_per_company: int | None = None,
) -> dict[str, Any]:
    """Fetch official exchange governance filings and store directors."""
    companies_subset = companies[:max_companies] if max_companies else companies
    max_filings = max(
        1,
        int(
            filings_per_company
            if filings_per_company is not None
            else os.getenv("FINAGENT_GOVERNANCE_FILINGS_PER_COMPANY", str(_DEFAULT_FILINGS_PER_COMPANY))
        ),
    )
    workers = max(
        1,
        int(os.getenv("FINAGENT_GOVERNANCE_DIRECTOR_MAX_WORKERS", str(_DEFAULT_MAX_WORKERS))),
    )

    totals = {
        "companies_processed": 0,
        "filings_found": 0,
        "filings_processed": 0,
        "directors_found": 0,
        "directors_stored": 0,
        "errors": 0,
        "success": True,
    }

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(companies_subset)))) as executor:
        futures = {
            executor.submit(
                _process_company,
                company,
                database_url=database_url,
                years_back=years_back,
                filings_per_company=max_filings,
            ): company
            for company in companies_subset
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            try:
                stats = future.result()
            except Exception as exc:
                logger.warning("Governance director worker failed: %s", exc)
                totals["errors"] += 1
                continue
            for key in ("companies_processed", "filings_found", "filings_processed", "directors_found", "directors_stored", "errors"):
                totals[key] += int(stats.get(key) or 0)
            if idx % 25 == 0:
                logger.info(
                    "Governance directors progress: %d/%d companies, %d directors stored",
                    idx,
                    len(companies_subset),
                    totals["directors_stored"],
                )

    totals["success"] = totals["companies_processed"] > 0 and (
        totals["errors"] == 0 or totals["directors_stored"] > 0
    )
    return totals


if __name__ == "__main__":
    import argparse

    from finagent.ikg.scrapers.mca_companies import get_listed_companies

    parser = argparse.ArgumentParser(description="Fetch exchange corporate-governance director data")
    parser.add_argument("--max-companies", type=int, help="Limit companies")
    parser.add_argument("--years-back", type=int, default=_DEFAULT_YEARS_BACK)
    parser.add_argument("--filings-per-company", type=int, default=_DEFAULT_FILINGS_PER_COMPANY)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    companies_arg = get_listed_companies(nifty500_only=True)
    print(
        run_corporate_governance_director_scraper(
            companies_arg,
            max_companies=args.max_companies,
            years_back=args.years_back,
            filings_per_company=args.filings_per_company,
        )
    )
