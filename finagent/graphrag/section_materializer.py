"""Materialize extracted source documents into canonical IKG document sections."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row

from finagent.ikg.db import connect_postgres, ensure_ikg_runtime_tables, get_database_url

logger = logging.getLogger("finagent.graphrag.section_materializer")

_CHUNK_CHARS = 6500
_CHUNK_OVERLAP = 600


@dataclass
class MaterializeStats:
    corporate_filings: int = 0
    enforcement_orders: int = 0
    concalls: int = 0
    director_sources: int = 0
    sections_written: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "corporate_filings": self.corporate_filings,
            "enforcement_orders": self.enforcement_orders,
            "concalls": self.concalls,
            "director_sources": self.director_sources,
            "sections_written": self.sections_written,
            "errors": self.errors,
        }


def _stable_uid(*parts: Any, size: int = 24) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:size]


def _clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", (text or "").replace("\x00", " ")).strip()


def _chunk_text(text: str, *, chunk_chars: int = _CHUNK_CHARS, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        if end < len(text):
            boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if boundary > start + int(chunk_chars * 0.55):
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _insert_sections(cur: Any, sections: list[dict[str, Any]]) -> int:
    written = 0
    for section in sections:
        text = _clean_text(str(section.get("text") or ""))
        tables = _clean_text(str(section.get("tables_markdown") or ""))
        if not text and not tables:
            continue
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
              metadata = document_sections.metadata || excluded.metadata,
              updated_at = now()
            """,
            (
                section["document_uid"],
                section["source_table"],
                section["source_uid"],
                section["document_type"],
                section["section_type"],
                section.get("title") or "",
                int(section.get("page_start") or 0),
                int(section.get("page_end") or section.get("page_start") or 0),
                text,
                len(text),
                tables,
                float(section.get("confidence") or 0.8),
                section.get("source_url"),
                json.dumps(section.get("metadata") or {}, default=str),
            ),
        )
        written += 1
    return written


def _sections_for_text(
    *,
    document_uid: str,
    source_table: str,
    source_uid: str,
    document_type: str,
    section_type: str,
    title: str,
    text: str,
    source_url: str | None,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    chunks = _chunk_text(text)
    sections: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        sections.append(
            {
                "document_uid": document_uid,
                "source_table": source_table,
                "source_uid": source_uid,
                "document_type": document_type,
                "section_type": section_type,
                "title": title[:500],
                "page_start": idx,
                "page_end": idx,
                "text": chunk,
                "tables_markdown": "",
                "confidence": 0.82,
                "source_url": source_url,
                "metadata": {
                    **metadata,
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "section_materializer_version": "document_sections_v1",
                },
            }
        )
    return sections


def materialize_document_sections(
    *,
    database_url: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Create canonical document_sections rows from extracted raw document tables."""
    db_url = get_database_url(database_url)
    if not db_url:
        return MaterializeStats(errors=1).to_dict()

    ensure_ikg_runtime_tables(db_url)
    stats = MaterializeStats()
    limit_sql = "limit %s" if limit else ""
    limit_params = [int(limit)] if limit else []

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"""
                    select category, exchange, symbol, scrip_code, cin, isin, company_name,
                           announced_at, title, description, attachment_url, attachment_text,
                           attachment_text_length, source_url, source_uid, source_map_url,
                           parser_version, fetched_at
                    from corporate_filings_raw
                    where coalesce(attachment_text_length, 0) > 0
                    order by fetched_at desc
                    {limit_sql}
                    """,
                    limit_params,
                )
                rows = cur.fetchall()
                for row in rows:
                    raw_uid = str(row.get("source_uid") or "")
                    source_uid = _stable_uid("corporate_filings_raw", row.get("exchange"), raw_uid)
                    sections = _sections_for_text(
                        document_uid=f"filing:{row.get('exchange')}:{source_uid}",
                        source_table="corporate_filings_raw",
                        source_uid=source_uid,
                        document_type="corporate_filing",
                        section_type=str(row.get("category") or "corporate_filing").lower().replace(" ", "_")[:120],
                        title=str(row.get("title") or row.get("description") or "Corporate filing"),
                        text=str(row.get("attachment_text") or ""),
                        source_url=row.get("attachment_url") or row.get("source_url"),
                        metadata={
                            "original_source_uid": raw_uid,
                            "exchange": row.get("exchange"),
                            "symbol": row.get("symbol"),
                            "scrip_code": row.get("scrip_code"),
                            "cin": row.get("cin"),
                            "isin": row.get("isin"),
                            "company_name": row.get("company_name"),
                            "announced_at": str(row.get("announced_at") or ""),
                            "source_map_url": row.get("source_map_url"),
                            "parser_version": row.get("parser_version"),
                        },
                    )
                    stats.sections_written += _insert_sections(cur, sections)
                stats.corporate_filings = len(rows)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                stats.errors += 1
                logger.warning("Corporate filing section materialization skipped: %s", exc)

            try:
                cur.execute(
                    f"""
                    select order_number, regulator, violation_type, penalty_amount_inr,
                           order_date, pdf_url, full_text, entities_json, status, fetched_at
                    from enforcement_raw
                    where coalesce(full_text, '') <> ''
                    order by fetched_at desc
                    {limit_sql}
                    """,
                    limit_params,
                )
                rows = cur.fetchall()
                for row in rows:
                    raw_uid = str(row.get("order_number") or "")
                    source_uid = _stable_uid("enforcement_raw", raw_uid)
                    sections = _sections_for_text(
                        document_uid=f"sebi_order:{source_uid}",
                        source_table="enforcement_raw",
                        source_uid=source_uid,
                        document_type="sebi_enforcement_order",
                        section_type="enforcement_order_text",
                        title=f"SEBI order {raw_uid}",
                        text=str(row.get("full_text") or ""),
                        source_url=row.get("pdf_url"),
                        metadata={
                            "original_order_number": raw_uid,
                            "regulator": row.get("regulator"),
                            "violation_type": row.get("violation_type"),
                            "penalty_amount_inr": str(row.get("penalty_amount_inr") or ""),
                            "order_date": str(row.get("order_date") or ""),
                            "entities": row.get("entities_json") or [],
                            "status": row.get("status"),
                        },
                    )
                    stats.sections_written += _insert_sections(cur, sections)
                stats.enforcement_orders = len(rows)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                stats.errors += 1
                logger.warning("SEBI enforcement section materialization skipped: %s", exc)

            try:
                cur.execute(
                    f"""
                    select symbol, company_name, cin, isin, exchange, announced_at,
                           quarter_label, fiscal_year, subject, description, attachment_url,
                           transcript_text, text_length, extracted_model, extraction_status,
                           sentiment_label, sentiment_score, intent_tags_json, source_url,
                           parser_version, fetched_at
                    from concall_transcripts_raw
                    where coalesce(text_length, 0) > 0
                    order by announced_at desc
                    {limit_sql}
                    """,
                    limit_params,
                )
                rows = cur.fetchall()
                for row in rows:
                    source_uid = _stable_uid(
                        "concall_transcripts_raw",
                        row.get("symbol"),
                        row.get("announced_at"),
                        row.get("attachment_url"),
                    )
                    sections = _sections_for_text(
                        document_uid=f"concall:{row.get('symbol')}:{source_uid}",
                        source_table="concall_transcripts_raw",
                        source_uid=source_uid,
                        document_type="concall_transcript",
                        section_type="concall_transcript_text",
                        title=str(row.get("subject") or row.get("description") or "Concall transcript"),
                        text=str(row.get("transcript_text") or ""),
                        source_url=row.get("attachment_url") or row.get("source_url"),
                        metadata={
                            "symbol": row.get("symbol"),
                            "company_name": row.get("company_name"),
                            "cin": row.get("cin"),
                            "isin": row.get("isin"),
                            "exchange": row.get("exchange"),
                            "announced_at": str(row.get("announced_at") or ""),
                            "quarter_label": row.get("quarter_label"),
                            "fiscal_year": row.get("fiscal_year"),
                            "sentiment_label": row.get("sentiment_label"),
                            "sentiment_score": str(row.get("sentiment_score") or ""),
                            "intent_tags": row.get("intent_tags_json") or [],
                            "extracted_model": row.get("extracted_model"),
                            "parser_version": row.get("parser_version"),
                        },
                    )
                    stats.sections_written += _insert_sections(cur, sections)
                stats.concalls = len(rows)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                stats.errors += 1
                logger.warning("Concall section materialization skipped: %s", exc)

            try:
                cur.execute(
                    f"""
                    select source, cin, nse_symbol, bse_scrip_code, quarter, filing_url,
                           title, extracted_text, parser_version, status, fetched_at
                    from director_source_records
                    where coalesce(extracted_text, '') <> ''
                    order by fetched_at desc
                    {limit_sql}
                    """,
                    limit_params,
                )
                rows = cur.fetchall()
                for row in rows:
                    source_uid = _stable_uid("director_source_records", row.get("source"), row.get("filing_url"))
                    sections = _sections_for_text(
                        document_uid=f"director_source:{source_uid}",
                        source_table="director_source_records",
                        source_uid=source_uid,
                        document_type="director_governance_document",
                        section_type="director_governance_text",
                        title=str(row.get("title") or "Director governance source document"),
                        text=str(row.get("extracted_text") or ""),
                        source_url=row.get("filing_url"),
                        metadata={
                            "source": row.get("source"),
                            "cin": row.get("cin"),
                            "nse_symbol": row.get("nse_symbol"),
                            "symbol": row.get("nse_symbol"),
                            "bse_scrip_code": row.get("bse_scrip_code"),
                            "quarter": row.get("quarter"),
                            "status": row.get("status"),
                            "parser_version": row.get("parser_version"),
                        },
                    )
                    stats.sections_written += _insert_sections(cur, sections)
                stats.director_sources = len(rows)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                stats.errors += 1
                logger.warning("Director source section materialization skipped: %s", exc)

    logger.info("Document section materialization complete: %s", stats.to_dict())
    return stats.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize extracted source docs into document_sections")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(json.dumps(materialize_document_sections(limit=args.limit), indent=2, default=str))


if __name__ == "__main__":
    main()
