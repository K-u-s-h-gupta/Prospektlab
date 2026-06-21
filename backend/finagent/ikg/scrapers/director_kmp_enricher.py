"""Director/KMP enricher from scalable official document sources.

Sources used:
  1. NSE/BSE governance filing text (director_source_records, corporate_filings_raw)
  2. Annual report board sections (document_sections sourced from annual_reports_raw)
  3. SEBI filing-mapped corporate filing attachments (corporate_filings_raw)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.rows import dict_row

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers.corporate_governance_directors import (
    _clean_name,
    _infer_designation,
    _is_plausible_director_name,
    parse_governance_directors_from_text,
)

logger = logging.getLogger("finagent.ikg.scrapers.director_kmp_enricher")

_PARSER_VERSION = "director_kmp_enricher_v1"
_BOARD_HINTS = (
    "board of directors",
    "key managerial personnel",
    "kmp",
    "managing director",
    "whole-time director",
    "independent director",
    "chief executive officer",
    "chief financial officer",
    "company secretary",
)
_ROLE_PATTERN = re.compile(
    r"(?i)\b("
    r"chairman|chairperson|managing director|whole[- ]?time director|executive director|"
    r"independent director|non[- ]?executive director|nominee director|"
    r"chief executive officer|ceo|chief financial officer|cfo|company secretary|kmp"
    r")\b"
)
_TITLE_NAME_PATTERN = re.compile(
    r"(?i)\b(?:mr|mrs|ms|dr|shri|smt)\.?\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,5})\b"
)
_PLAIN_NAME_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,4})\b"
)


def _norm_cin(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text[:21] if text else None


def _norm_symbol(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text[:20] if text else None


def _norm_scrip(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if digits:
        return digits[:10]
    return text[:10]


def _norm_quarter(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:20] if text else None


def _norm_source(value: Any) -> str:
    text = str(value or "document_enrichment").strip()
    return text[:80] or "document_enrichment"


def _alt_identifier(cin: str, name: str) -> str:
    # directors_raw.din is varchar(10); keep synthetic IDs within that contract.
    digest = hashlib.sha1(f"{cin.strip().upper()}|{name.strip().upper()}".encode("utf-8")).hexdigest()[:7].upper()
    return f"ALT{digest}"


def _extract_role_name_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw_line in re.split(r"[\r\n]+", text or ""):
        line = " ".join((raw_line or "").split())
        if len(line) < 15:
            continue
        role_match = _ROLE_PATTERN.search(line)
        if not role_match:
            continue
        role = _infer_designation(role_match.group(0))
        title_name = _TITLE_NAME_PATTERN.search(line)
        if title_name:
            name = _clean_name(title_name.group(1))
            if _is_plausible_director_name(name):
                pairs.append((name, role))
            continue
        for nm in _PLAIN_NAME_PATTERN.findall(line):
            name = _clean_name(nm)
            if _is_plausible_director_name(name):
                pairs.append((name, role))
                break
    return pairs


def parse_director_kmp_from_text(
    text: str,
    *,
    cin: str,
    source: str,
    source_url: str = "",
    nse_symbol: str | None = None,
    bse_scrip_code: str | None = None,
    quarter: str = "",
) -> list[dict[str, Any]]:
    """Parse directors/KMP from source text using DIN-first then role/name fallback."""
    if not text or not cin:
        return []
    lowered = text.lower()
    if not any(h in lowered for h in _BOARD_HINTS):
        return []

    by_din: dict[str, dict[str, Any]] = {}
    parsed_din = parse_governance_directors_from_text(
        text,
        cin=cin,
        nse_symbol=nse_symbol,
        bse_scrip_code=bse_scrip_code,
        source_url=source_url,
        quarter=quarter,
    )
    for row in parsed_din:
        din = str(row.get("din") or "").strip()
        if not din:
            continue
        row["source"] = source
        by_din[din] = row

    for name, role in _extract_role_name_pairs(text):
        alt_din = _alt_identifier(cin, name)
        if alt_din in by_din:
            continue
        by_din[alt_din] = {
            "cin": cin,
            "din": alt_din,
            "name": name,
            "designation": role or "Director",
            "appointment_date": None,
            "cessation_date": None,
            "source": source,
            "source_url": source_url,
            "quarter": quarter or None,
            "nse_symbol": nse_symbol,
            "bse_scrip_code": bse_scrip_code,
            "confidence_score": 0.6,
        }
    return sorted(by_din.values(), key=lambda row: str(row.get("din") or ""))


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
                parser_version varchar(80) default 'director_kmp_enricher_v1',
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


def _load_documents(
    database_url: str,
    *,
    cins: set[str] | None = None,
    years_back: int = 3,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, int(years_back)) * 365)
    cin_filter = "and cin = any(%s)" if cins else ""
    docs: list[dict[str, Any]] = []
    with connect_postgres(database_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            # 1) Annual report board sections already selected via document selector.
            cur.execute(
                f"""
                select
                  'annual_report_board_section' as source,
                  ar.report_uid::text as source_uid,
                  ar.cin,
                  ar.nse_symbol,
                  ar.scrip_code as bse_scrip_code,
                  ar.report_year as quarter,
                  coalesce(ds.source_url, ar.pdf_url) as source_url,
                  coalesce(ds.title, 'Annual report board section') as title,
                  ds.text as extracted_text,
                  jsonb_build_object(
                    'section_type', ds.section_type,
                    'metadata', ds.metadata,
                    'report_year', ar.report_year,
                    'report_uid', ar.report_uid
                  ) as raw_json
                from document_sections ds
                join annual_reports_raw ar
                  on ds.source_table = 'annual_reports_raw'
                 and ds.source_uid = ar.report_uid
                where coalesce(ds.text_length, 0) > 0
                  and (
                    ds.section_type = 'board_and_kmp'
                    or coalesce(ds.metadata::text, '') ilike '%%board_and_kmp%%'
                    or coalesce(ds.metadata::text, '') ilike '%%key managerial%%'
                  )
                  and ar.fetched_at >= %s
                  {cin_filter}
                order by ar.fetched_at desc
                """,
                [cutoff, list(cins)] if cins else [cutoff],
            )
            docs.extend(dict(row) for row in (cur.fetchall() or []))

            # 2) Corporate filing attachments from SEBI-mapped governance categories.
            cur.execute(
                f"""
                select
                  'sebi_corporate_filing_document' as source,
                  concat(exchange, ':', source_uid) as source_uid,
                  cin,
                  symbol as nse_symbol,
                  scrip_code as bse_scrip_code,
                  null::text as quarter,
                  coalesce(attachment_url, source_url) as source_url,
                  coalesce(title, description, 'Corporate filing') as title,
                  attachment_text as extracted_text,
                  raw_json
                from corporate_filings_raw
                where coalesce(attachment_text_length, 0) > 0
                  and announced_at >= %s
                  and (
                    lower(category) in (
                      'corporate_governance',
                      'insider_trading',
                      'secretarial_compliance',
                      'voting_results'
                    )
                    or coalesce(title, '') ilike '%%board%%'
                    or coalesce(title, '') ilike '%%director%%'
                    or coalesce(title, '') ilike '%%kmp%%'
                  )
                  {cin_filter}
                order by announced_at desc nulls last
                """,
                [cutoff, list(cins)] if cins else [cutoff],
            )
            docs.extend(dict(row) for row in (cur.fetchall() or []))

            # 3) Governance source documents captured by governance scraper.
            cur.execute(
                f"""
                select
                  coalesce(source, 'NSE_corporate_governance') as source,
                  filing_url as source_uid,
                  cin,
                  nse_symbol,
                  bse_scrip_code,
                  quarter,
                  filing_url as source_url,
                  coalesce(title, 'Governance source record') as title,
                  extracted_text,
                  raw_json
                from director_source_records
                where coalesce(extracted_text, '') <> ''
                  and fetched_at >= %s
                  {cin_filter}
                order by fetched_at desc
                """,
                [cutoff, list(cins)] if cins else [cutoff],
            )
            docs.extend(dict(row) for row in (cur.fetchall() or []))
    return docs


def _store_source_record(cur: Any, doc: dict[str, Any], *, status: str, error: str = "") -> None:
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
            _norm_source(doc.get("source")),
            _norm_cin(doc.get("cin")),
            _norm_symbol(doc.get("nse_symbol")),
            _norm_scrip(doc.get("bse_scrip_code")),
            _norm_quarter(doc.get("quarter")),
            doc.get("source_url") or doc.get("source_uid") or "",
            doc.get("title"),
            json.dumps(doc.get("raw_json") or {}, default=str),
            doc.get("extracted_text") or "",
            _PARSER_VERSION,
            status,
            error,
        ),
    )


def _store_directors(cur: Any, directors: list[dict[str, Any]]) -> int:
    upserted = 0
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
                confidence_score = greatest(coalesce(directors_raw.confidence_score, 0), excluded.confidence_score),
                fetched_at = now()
            """,
            (
                _norm_cin(d.get("cin")),
                d.get("din"),
                d.get("name"),
                d.get("designation") or "Director",
                d.get("appointment_date"),
                d.get("cessation_date"),
                _norm_source(d.get("source")),
                d.get("source_url"),
                _norm_quarter(d.get("quarter")),
                _norm_symbol(d.get("nse_symbol")),
                _norm_scrip(d.get("bse_scrip_code")),
                float(d.get("confidence_score") or (0.9 if str(d.get("din") or "").isdigit() else 0.6)),
            ),
        )
        upserted += 1
    return upserted


def run_director_kmp_enrichment(
    *,
    companies: list[dict[str, Any]] | None = None,
    database_url: str | None = None,
    max_companies: int | None = None,
    years_back: int = 3,
) -> dict[str, Any]:
    """Enrich directors_raw from governance docs, annual report board sections, and SEBI filing docs."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {
            "success": False,
            "companies_considered": 0,
            "documents_scanned": 0,
            "director_candidates": 0,
            "directors_stored": 0,
            "errors": 1,
            "error": "database url is not configured",
        }

    subset = companies[:max_companies] if (companies and max_companies) else (companies or [])
    cins = {str(c.get("cin") or "").strip() for c in subset if c.get("cin")}
    docs = _load_documents(db_url, cins=cins or None, years_back=years_back)

    candidates_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    errors = 0

    # directors_raw is written by several tasks; a transaction advisory lock serialises
    # them so concurrent inserts can't deadlock (observed 40P01 on parallel refresh).
    _DIRECTORS_RAW_LOCK_KEY = 778201  # arbitrary fixed key shared by directors_raw writers
    _max_attempts = 4
    for _attempt in range(1, _max_attempts + 1):
        try:
            return _run_director_kmp_enrichment_locked(
                db_url, docs, cins, _DIRECTORS_RAW_LOCK_KEY
            )
        except Exception as exc:
            if "deadlock" in str(exc).lower() and _attempt < _max_attempts:
                logger.warning("director_kmp deadlock (attempt %d); retrying", _attempt)
                time.sleep(0.5 * _attempt)
                continue
            raise


def _run_director_kmp_enrichment_locked(
    db_url: str,
    docs: list[dict[str, Any]],
    cins: set[str],
    lock_key: int,
) -> dict[str, Any]:
    candidates_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    errors = 0

    with connect_postgres(db_url, connect_timeout=30) as conn:
        _ensure_director_tables(conn)
        with conn.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(%s)", (lock_key,))
            for doc in docs:
                cin = str(doc.get("cin") or "").strip()
                text = str(doc.get("extracted_text") or "")
                if not cin or not text.strip():
                    try:
                        _store_source_record(cur, doc, status="no_text", error="missing cin/text")
                    except Exception:
                        errors += 1
                    continue
                try:
                    rows = parse_director_kmp_from_text(
                        text,
                        cin=cin,
                        source=str(doc.get("source") or "document_enrichment"),
                        source_url=str(doc.get("source_url") or ""),
                        nse_symbol=(str(doc.get("nse_symbol") or "").strip().upper() or None),
                        bse_scrip_code=(str(doc.get("bse_scrip_code") or "").strip() or None),
                        quarter=str(doc.get("quarter") or "").strip(),
                    )
                    for row in rows:
                        key = (str(row.get("cin") or ""), str(row.get("din") or ""))
                        if not key[0] or not key[1]:
                            continue
                        candidates_by_key[key] = row
                    _store_source_record(cur, doc, status="parsed" if rows else "no_directors_parsed")
                except Exception as exc:
                    errors += 1
                    logger.warning("director_kmp parse failed for source=%s cin=%s: %s", doc.get("source"), cin, exc)
                    try:
                        _store_source_record(cur, doc, status="extract_failed", error=str(exc))
                    except Exception:
                        errors += 1

            stored = _store_directors(cur, list(candidates_by_key.values()))
        conn.commit()

    stats = {
        "success": bool(cins) and (errors == 0 or bool(candidates_by_key)),
        "companies_considered": len(cins),
        "documents_scanned": len(docs),
        "director_candidates": len(candidates_by_key),
        "directors_stored": int(stored),
        "errors": errors,
        "parser_version": _PARSER_VERSION,
    }
    logger.info("Director/KMP enrichment complete: %s", stats)
    return stats
