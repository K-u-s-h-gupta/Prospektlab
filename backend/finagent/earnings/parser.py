"""PDF/text parser for earnings documents.

PyMuPDF is the primary extractor. When local extraction is too weak for
financial tables, the shared Document Intelligence helper escalates to Azure DI
if credentials are configured.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from finagent.earnings.analysis import (
    METRIC_SPECS,
    build_document_payload,
    build_financial_comparison_rows,
    compact_summary,
    extract_financial_metrics,
    infer_call_timing,
    infer_quarter_ref,
    parse_date,
    parse_datetime,
    sanitize_text,
)

logger = logging.getLogger("finagent.earnings.parser")

_PARSER_VERSION = "earnings_parser_v2"
_MIN_TEXT_CHARS = int(os.getenv("FINAGENT_EARNINGS_MIN_TEXT_CHARS", "800") or "800")
_MAX_TABLES_IN_PAYLOAD = int(os.getenv("FINAGENT_EARNINGS_MAX_TABLES", "3") or "3")
_NUMBER_RE = re.compile(r"\(?[-+]?\d[\d,]*(?:\.\d+)?\)?")


# Patterns found in pre-meeting intimation notices (no results yet)
_INTIMATION_TEXT_PATTERNS: tuple[str, ...] = (
    "board meeting is scheduled",
    "board meeting will be held",
    "board of directors will consider",
    "to inter-alia consider",
    "inter alia consider",
    "to consider and approve",
    "prior intimation",
    "intimation of board meeting",
    "meeting is scheduled to be held",
    "pursuant to regulation 29",
    "regulation 29 of the sebi",
    "notice is hereby given",
    "intimation under regulation",
)
# Patterns that confirm actual results are present
_RESULT_CONFIRMED_PATTERNS: tuple[str, ...] = (
    "outcome of board meeting",
    "approved the financial results",
    "audited financial results",
    "unaudited financial results",
    "financial results for the quarter",
    "consolidated financial results",
    "profit after tax",
    "revenue from operations",
    "earnings per share",
    "total income",
)


def _run_async(coro_factory: Callable[[], Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    if not loop.is_running():
        return loop.run_until_complete(coro_factory())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


def _extraction_quality_ok(extraction: dict[str, Any], require_tables: bool) -> bool:
    """Return True if PyMuPDF extraction looks good enough to use directly.

    Checks:
      - meaningful text length (> 800 chars)
      - contains financial keywords (revenue, profit, eps, etc.)
      - either tables found or financial metrics extracted
      - not flagged as an intimation-only document
    """
    text = str(extraction.get("text") or "")
    tables = extraction.get("tables") or []
    if len(text) < 800:
        return False
    lower = text.lower()
    financial_keywords = (
        "revenue", "profit", "eps", "earnings per share", "ebitda", "pat",
        "total income", "net profit", "profit after tax", "financial results",
    )
    has_financial_keywords = any(kw in lower for kw in financial_keywords)
    if not has_financial_keywords:
        return False
    if require_tables and len(tables) < 1:
        # Even without tables, if we have clear numbers and section headers, accept
        if not any(r in lower for r in ("standalone", "consolidated", "quarter ended", "year ended")):
            return False
    if _is_intimation_text(text):
        return False
    return True


def extract_pdf_text(pdf_bytes: bytes, *, require_tables: bool = True) -> dict[str, Any]:
    """Extract text and tables from a PDF with PyMuPDF primary, Azure DI fallback.

    Strategy:
      1. Run PyMuPDF first (fast, local).
      2. Check quality/accuracy of extraction.
      3. If quality is poor, escalate to Azure DI (prebuilt-layout).
      4. If Azure DI also fails, return the best PyMuPDF result we have.
    """
    if not pdf_bytes:
        return {"text": "", "page_count": 0, "model": None, "tables": [], "error": "empty pdf"}

    local = _extract_pdf_local_only(pdf_bytes)
    if local.get("error"):
        logger.debug("PyMuPDF extraction error: %s", local.get("error"))

    if _extraction_quality_ok(local, require_tables):
        logger.info("PyMuPDF extraction accepted (quality ok): %d chars, %d tables", len(local.get("text", "")), len(local.get("tables", [])))
        local["fallback_used"] = False
        return local

    logger.info(
        "PyMuPDF extraction quality insufficient (%d chars, %d tables, error=%s); escalating to Azure DI",
        len(local.get("text", "")), len(local.get("tables", [])), local.get("error") or "none",
    )

    try:
        from finagent.ingestion.azure_doc_intel import extract_document

        timeout_s = float(os.getenv("FINAGENT_EARNINGS_DI_TIMEOUT_S", "120") or "120")
        result = _run_async(
            lambda: extract_document(
                file_bytes=pdf_bytes,
                model_id="prebuilt-layout",
                timeout_s=timeout_s,
                allow_fallback=False,
                require_tables=require_tables,
            )
        )
        di = {
            "text": sanitize_text(getattr(result, "full_text", "") or ""),
            "page_count": int(getattr(result, "page_count", 0) or 0),
            "model": getattr(result, "model_used", None),
            "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
            "fallback_used": True,
            "tables": _tables_from_document_result(result),
            "error": None,
        }
        if di.get("text") or di.get("tables"):
            logger.info("Azure DI fallback accepted: %d chars, %d tables", len(di.get("text", "")), len(di.get("tables", [])))
            return di
        logger.debug("Azure DI returned empty; falling back to PyMuPDF result")
    except Exception as exc:
        logger.debug("Azure DI fallback failed: %s", exc)

    local["fallback_used"] = True
    local["error"] = local.get("error") or "azure_di_fallback_failed"
    return local



def _extract_pdf_local_only(pdf_bytes: bytes) -> dict[str, Any]:
    text_parts: list[str] = []
    tables: list[dict[str, Any]] = []
    page_count = 0
    try:
        import fitz

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page_count = len(doc)
            for page_number, page in enumerate(doc, start=1):
                page_text = page.get_text("text") or ""
                if page_text.strip():
                    text_parts.append(f"--- Page {page_number} ---\n{page_text}")
                try:
                    found = page.find_tables()
                    for table in getattr(found, "tables", []) or []:
                        rows = [[str(cell or "") for cell in row] for row in table.extract()]
                        if rows:
                            tables.append(
                                {
                                    "page_number": page_number,
                                    "rows": rows,
                                    "confidence": 0.5,
                                    "page_text": page_text,
                                }
                            )
                except Exception:
                    pass
        text = sanitize_text("\n\n".join(text_parts).strip())
        return {
            "text": text,
            "page_count": page_count,
            "model": "pymupdf_local",
            "confidence": 0.5,
            "fallback_used": False,
            "tables": tables,
            "error": None if text or tables else "no text extracted",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("PyMuPDF local extraction failed: %s", exc)
        return {
            "text": "",
            "page_count": page_count,
            "model": None,
            "confidence": 0.0,
            "fallback_used": False,
            "tables": [],
            "error": str(exc),
        }


def _tables_from_document_result(result: Any) -> list[dict[str, Any]]:
    pages = {
        int(getattr(page, "page_number", 0) or 0): str(getattr(page, "text", "") or "")
        for page in (getattr(result, "pages", None) or [])
    }
    tables: list[dict[str, Any]] = []
    for table in getattr(result, "tables", None) or []:
        rows = [[sanitize_text(str(cell or "")) for cell in row] for row in (getattr(table, "rows", None) or [])]
        if not rows:
            continue
        page_number = int(getattr(table, "page_number", 0) or 0)
        tables.append(
            {
                "page_number": page_number,
                "rows": rows,
                "confidence": float(getattr(table, "confidence", 0.0) or 0.0),
                "page_text": sanitize_text(pages.get(page_number, "")),
            }
        )
    return tables


def _is_intimation_text(text: str) -> bool:
    """Return True if extracted text is a pre-meeting intimation with no actual results."""
    lower = text[:3000].lower()
    has_intimation = any(kw in lower for kw in _INTIMATION_TEXT_PATTERNS)
    has_results = any(kw in lower for kw in _RESULT_CONFIRMED_PATTERNS)
    return has_intimation and not has_results


def parse_earnings_document(
    *,
    text: str | None = None,
    pdf_bytes: bytes | None = None,
    metadata: dict[str, Any] | None = None,
    previous_metrics: dict[str, Any] | None = None,
    year_ago_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured earnings details from text or PDF bytes."""
    metadata = metadata or {}
    extraction = {"text": text or "", "page_count": 0, "model": "provided_text", "tables": [], "error": None}
    if pdf_bytes:
        extraction = extract_pdf_text(pdf_bytes, require_tables=_should_require_financial_tables(text, metadata))

    extracted_text = str(extraction.get("text") or "").strip()
    supplied_text = str(text or "").strip()
    text_parts = [part for part in (supplied_text, extracted_text) if part]
    full_text = "\n\n".join(dict.fromkeys(text_parts)).strip()
    tables = _normalise_tables(extraction.get("tables") or [])
    tables_by_type = _select_financial_tables_by_type(tables)
    selected_tables = tables_by_type.get("consolidated") or tables_by_type.get("standalone") or []
    standalone_tables = tables_by_type.get("standalone") or []
    table_text = "\n\n".join(_table_to_text(table) for table in selected_tables)
    analysis_text = f"{full_text}\n\n{table_text}".strip()

    source_url = str(metadata.get("source_url") or metadata.get("attachment_url") or "").strip()
    table_current, table_previous, table_year_ago = _metrics_from_tables(selected_tables, full_text=full_text)
    free_text_metrics = extract_financial_metrics(analysis_text)

    # Indian results PDFs often lose table structure in PyMuPDF, but the text
    # still preserves the P&L section as label + sequential values. Prefer that
    # section-level extraction over whole-document regexes so EPS is not confused
    # with face value and EBITDA is not picked from cash-flow working-capital rows.
    standalone_current, standalone_previous, standalone_year_ago = _extract_metric_periods_from_labeled_section(
        full_text,
        "standalone",
    )
    consolidated_current, consolidated_previous, consolidated_year_ago = _extract_metric_periods_from_labeled_section(
        full_text,
        "consolidated",
    )

    consolidated_tables = tables_by_type.get("consolidated") or []
    standalone_tables_only = tables_by_type.get("standalone") or []

    if not consolidated_current and consolidated_tables:
        consolidated_current, consolidated_previous, consolidated_year_ago = _metrics_from_tables(
            consolidated_tables,
            full_text=full_text,
        )

    if not standalone_current and standalone_tables_only:
        cons_pages = {t.get("page_number") for t in consolidated_tables}
        stand_pages = {t.get("page_number") for t in standalone_tables_only}
        if stand_pages != cons_pages:
            standalone_current, standalone_previous, standalone_year_ago = _metrics_from_tables(
                standalone_tables_only,
                full_text=full_text,
            )

    if consolidated_current:
        current_metrics = consolidated_current
        detected_previous = consolidated_previous
        detected_year_ago = consolidated_year_ago
    elif standalone_current:
        current_metrics = standalone_current
        detected_previous = standalone_previous
        detected_year_ago = standalone_year_ago
    elif table_current:
        current_metrics = table_current
        detected_previous = table_previous
        detected_year_ago = table_year_ago
    else:
        current_metrics = free_text_metrics
        detected_previous = {}
        detected_year_ago = {}

    comparison_previous = previous_metrics or detected_previous
    comparison_year_ago = year_ago_metrics or detected_year_ago
    financial_rows = build_financial_comparison_rows(
        current_metrics,
        comparison_previous,
        comparison_year_ago,
    )
    metric_highlights = _build_metric_highlights(financial_rows, source_url)

    # Detect pre-meeting intimation: text looks like a notice with no actual financial data
    is_intimation = (
        bool(pdf_bytes)
        and _is_intimation_text(full_text)
        and not bool(current_metrics)
    )

    payload = build_document_payload(
        text=analysis_text,
        source_url=source_url,
        current_metrics=current_metrics,
        previous_metrics=comparison_previous,
        year_ago_metrics=comparison_year_ago,
    )

    title_text = " ".join(
        str(metadata.get(key) or "")
        for key in ("title", "subject", "category", "company_name", "symbol")
    )
    fallback_date = parse_date(metadata.get("meeting_date") or metadata.get("announced_at"))
    announced_at = parse_datetime(metadata.get("announced_at"))
    quarter = str(metadata.get("quarter_ref") or "").strip() or infer_quarter_ref(
        f"{title_text} {analysis_text[:2000]}",
        fallback_date,
    )
    timing = str(metadata.get("timing") or "").strip() or infer_call_timing(
        f"{title_text} {analysis_text[:1000]}",
        announced_at,
    )

    commentary = metric_highlights[:] or payload["highlights"][:]
    if analysis_text and not commentary:
        commentary = [
            {
                "text": compact_summary(analysis_text, 180),
                "url": source_url,
                "source_label": "official filing" if source_url else "",
            }
        ]

    standalone_metrics_raw = standalone_current
    consolidated_metrics_raw = consolidated_current

    # Log what we found for debugging
    logger.debug(
        "Metrics extraction: standalone=%s, consolidated=%s, main=%s",
        list(standalone_metrics_raw.keys()) if standalone_metrics_raw else None,
        list(consolidated_metrics_raw.keys()) if consolidated_metrics_raw else None,
        list(current_metrics.keys()) if current_metrics else None,
    )

    # === Subsidiary Cash-Drain Matrix Analysis ===
    subsidiary_analysis = None
    # Compute if we have BOTH standalone and consolidated with different values
    if (standalone_metrics_raw and consolidated_metrics_raw):
        # Check if they're meaningfully different
        has_difference = any(
            standalone_metrics_raw.get(k) != consolidated_metrics_raw.get(k)
            for k in ['revenue', 'pat', 'ebitda']
            if standalone_metrics_raw.get(k) is not None and consolidated_metrics_raw.get(k) is not None
        )
        if has_difference:
            try:
                from finagent.earnings.subsidiary_analysis import extract_subsidiary_analysis
                subsidiary_analysis = extract_subsidiary_analysis(standalone_metrics_raw, consolidated_metrics_raw)
            except Exception as sub_exc:
                logger.debug("Subsidiary analysis failed: %s", sub_exc)

    # === NEW: Footnote extraction (diff computed at service layer with previous quarter) ===
    footnotes_text = None
    try:
        from finagent.earnings.footnote_analysis import extract_footnotes_section
        footnotes_text = extract_footnotes_section(full_text)
    except Exception as fn_exc:
        logger.debug("Footnote extraction failed: %s", fn_exc)

    return {
        "parser_version": _PARSER_VERSION,
        "is_intimation": is_intimation,
        "extraction": {
            "status": "ok" if analysis_text else "failed",
            "model": extraction.get("model"),
            "page_count": int(extraction.get("page_count") or 0),
            "text_length": len(full_text),
            "tables_count": len(tables),
            "selected_tables_count": len(selected_tables),
            "confidence": extraction.get("confidence"),
            "fallback_used": extraction.get("fallback_used"),
            "error": extraction.get("error"),
        },
        "quarter": quarter,
        "timing": timing,
        "highlights": metric_highlights or payload["highlights"],
        "management_commentary": commentary,
        "transcript": payload["transcript"],
        "financials": {
            "metrics": current_metrics,
            "rows": financial_rows,
            "unit_note": "Absolute values are in Rs crore except EPS and margins.",
            "source": extraction.get("model") or "provided_text",
            "consolidated_tables": [_compact_table(table) for table in selected_tables[:_MAX_TABLES_IN_PAYLOAD]],
            "standalone_tables": [_compact_table(table) for table in standalone_tables[:_MAX_TABLES_IN_PAYLOAD]] if standalone_tables != selected_tables else [],
            "standalone_metrics": standalone_metrics_raw or None,
            "consolidated_metrics": consolidated_metrics_raw or None,
        },
        "subsidiary_analysis": subsidiary_analysis,
        "footnotes_text": footnotes_text[:8000] if footnotes_text else None,
        "text_excerpt": analysis_text[:6000],
    }


def _should_require_financial_tables(text: str | None, metadata: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            metadata.get("title"),
            metadata.get("category"),
            metadata.get("announcement_type"),
            metadata.get("summary"),
            text,
        )
    ).lower()
    notice_terms = (
        "board meeting",
        "to consider",
        "prior intimation",
        "intimation of",
        "meeting of the board",
    )
    actual_result_terms = (
        "outcome of board meeting",
        "approved the financial results",
        "audited financial results",
        "unaudited financial results",
        "financial results for the quarter",
        "financial results for quarter",
        "standalone and consolidated",
        "consolidated financial results",
    )
    if any(term in haystack for term in notice_terms) and not any(term in haystack for term in actual_result_terms):
        return False
    return True
def _normalise_tables(raw_tables: list[Any]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for item in raw_tables:
        if isinstance(item, dict):
            rows = item.get("rows") or []
            page_number = item.get("page_number")
            confidence = item.get("confidence")
            page_text = item.get("page_text") or ""
        else:
            rows = getattr(item, "rows", []) or []
            page_number = getattr(item, "page_number", 0)
            confidence = getattr(item, "confidence", 0.0)
            page_text = ""
        clean_rows = [[str(cell or "").strip() for cell in row] for row in rows if row]
        if clean_rows:
            tables.append(
                {
                    "page_number": int(page_number or 0),
                    "rows": clean_rows,
                    "confidence": float(confidence or 0.0),
                    "page_text": str(page_text or ""),
                }
            )
    return tables





def _select_financial_tables_by_type(tables: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Classify and return both consolidated and standalone financial tables.

    Returns:
        {
            "consolidated": [list of consolidated tables],
            "standalone": [list of standalone tables],
        }
    """
    consolidated_tables: list[tuple[int, int, dict[str, Any]]] = []
    standalone_tables: list[tuple[int, int, dict[str, Any]]] = []
    unclassified_tables: list[tuple[int, int, dict[str, Any]]] = []

    for index, table in enumerate(tables):
        table_text = _table_to_text(table).lower()
        page_text = str(table.get("page_text") or "").lower()
        combined_context = table_text + " " + page_text

        # Check if table has financial metrics
        metric_hits = sum(1 for spec in METRIC_SPECS if _contains_metric_alias(table_text, spec.aliases))
        if metric_hits == 0:
            continue

        score = metric_hits * 3
        rows = table.get("rows") or []
        if len(rows) >= 4 and max((len(row) for row in rows), default=0) >= 3:
            score += 2

        first_rows = " ".join(" ".join(row) for row in rows[:5]).lower()

        # Enhanced classification - check multiple indicators
        consolidated_indicators = [
            "consolidated" in combined_context,
            "group" in combined_context and "financial" in combined_context,
            "consolidated statement" in combined_context,
            "consolidated results" in combined_context,
        ]
        standalone_indicators = [
            "standalone" in combined_context,
            "standalone results" in combined_context,
            "standalone statement" in combined_context,
            "unconsolidated" in combined_context,
        ]

        is_consolidated = any(consolidated_indicators)
        is_standalone = any(standalone_indicators)

        # If both flags are set, determine based on context proximity
        if is_consolidated and is_standalone:
            # Check which keyword appears first in table text (closer = more relevant)
            cons_pos = combined_context.find("consolidated")
            stand_pos = combined_context.find("standalone")
            if cons_pos >= 0 and stand_pos >= 0:
                is_consolidated = cons_pos < stand_pos
                is_standalone = not is_consolidated

        if is_consolidated:
            consolidated_tables.append((score, index, table))
        elif is_standalone:
            standalone_tables.append((score, index, table))
        else:
            # Unclassified tables - save for later
            unclassified_tables.append((score, index, table))

    # Sort by score descending, then by index (original order)
    consolidated_tables.sort(key=lambda item: (-item[0], item[1]))
    standalone_tables.sort(key=lambda item: (-item[0], item[1]))
    unclassified_tables.sort(key=lambda item: (-item[0], item[1]))

    # If we have consolidated but no standalone, use highest-scoring unclassified as standalone
    # (Many companies report consolidated first, then standalone without explicit label)
    if consolidated_tables and not standalone_tables and unclassified_tables:
        # Find tables that DON'T appear in consolidated (different pages typically)
        cons_pages = {t[2].get("page_number") for t in consolidated_tables}
        other_page_tables = [t for t in unclassified_tables if t[2].get("page_number") not in cons_pages]
        if other_page_tables:
            standalone_tables = other_page_tables[:_MAX_TABLES_IN_PAYLOAD]

    # If no classification worked, treat unclassified as consolidated (most common default)
    if not consolidated_tables and unclassified_tables:
        consolidated_tables = unclassified_tables

    return {
        "consolidated": [table for _, _, table in consolidated_tables][:_MAX_TABLES_IN_PAYLOAD],
        "standalone": [table for _, _, table in standalone_tables][:_MAX_TABLES_IN_PAYLOAD],
    }





def _contains_metric_alias(text: str, aliases: tuple[str, ...]) -> bool:
    for alias in aliases:
        alias_l = alias.lower()
        if len(alias_l) <= 4:
            if re.search(rf"\b{re.escape(alias_l)}\b", text):
                return True
        elif alias_l in text:
            return True
    return False


def _table_to_text(table: dict[str, Any]) -> str:
    rows = table.get("rows") or []
    return "\n".join(" | ".join(str(cell or "") for cell in row) for row in rows)


def _detect_unit_scale(tables: list[dict[str, Any]], full_text: str = "") -> float:
    """Detect the currency unit used in financial tables and return Rs Crore scale factor.

    Indian companies use different units:
      Rs Crores    -> scale = 1.0   (most common for large companies)
      Rs Millions  -> scale = 0.1   (1 Crore = 10 Millions)
      Rs Lakhs     -> scale = 0.01  (1 Crore = 100 Lakhs)

    Searches the FULL extracted text, all table headers, and page text.
    """
    # Use the full document text (not just first N chars) for reliable unit detection
    sample = full_text.lower()
    for table in tables:
        sample += (" ".join(
            " ".join(str(c or "") for c in row) for row in (table.get("rows") or [])[:4]
        ) + str(table.get("page_text") or "")).lower()

    # Check for millions - must be specific enough to not collide with "crore"
    if any(p in sample for p in (
        "rs. in millions", "rs in millions", "rupees in millions",
        "rs in millions", "in millions", "rs. mn", "rs mn",
        "inr millions", "amount in millions", "all amounts are in millions",
        "(millions)", "million rupees",
    )):
        return 0.1

    if any(p in sample for p in (
        "rs. in lakhs", "rs in lakhs", "rupees in lakhs",
        "rs in lakhs", "in lakhs", "rs. lacs", "rs lacs",
        "in lacs", "amount in lakhs", "(lakhs)", "lakh rupees",
    )):
        return 0.01

    return 1.0  # default: assume Rs Crore


def _is_annual_column_header(cell_text: str) -> bool:
    """Return True if a column header looks like a full-year period (not a quarter).

    Annual columns (e.g., "Year Ended 31-Mar-2026") should be skipped when
    building the quarterly comparison so we don't pick up 12-month values as
    "previous quarter".
    """
    lower = cell_text.lower().strip()
    annual_patterns = (
        "year ended",
        "year ending",
        "twelve months",
        "12 months",
        "12months",
        "annual",
        "full year",
        "fy 20",
        "f.y. 20",
        # Indian financial reporting - year-to-date patterns
        "nine months",
        "six months",
        "half year",
        "ytd",
        "h1 fy",
        "h2 fy",
    )
    return any(p in lower for p in annual_patterns)


def _quarterly_column_indices(header_row: list[str]) -> list[int]:
    """Return indices of non-annual columns from a table header row.

    Annual columns (e.g. "Year Ended 31-Mar-2026") are excluded so we don't
    pick up 12-month figures as "previous quarter".  Returns [] if the row
    doesn't look like a header.
    """
    if not header_row:
        return []
    date_like = sum(
        1 for cell in header_row
        if re.search(r"\b(20\d\d|quarter|ended|ending|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
                     str(cell or "").lower())
    )
    if date_like < 2:
        return []  # not a header row - no filtering
    # Keep all non-annual column indices (annual columns stripped)
    return [i for i, c in enumerate(header_row) if not _is_annual_column_header(str(c or ""))]


def _metrics_from_tables(
    tables: list[dict[str, Any]],
    full_text: str = "",
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Extract financial metrics from tables.

    Uses two strategies:
    1. Structured row-by-row extraction from well-formed tables
    2. Text-based extraction from table cell contents (handles merged cells)
    """
    scale = _detect_unit_scale(tables, full_text)
    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    year_ago: dict[str, float] = {}

    # Strategy 1: Structured extraction (original logic)
    for table in tables:
        rows = table.get("rows") or []
        if not rows:
            continue

        # Detect if the first substantive row is a column-header row
        # and extract which columns correspond to quarterly figures (skip annual columns)
        col_filter: list[int] = []
        for header_candidate in rows[:3]:
            col_filter = _quarterly_column_indices(header_candidate)
            if col_filter:
                break

        for row in rows:
            spec = _metric_spec_for_row(row)
            if not spec or spec.key in current:
                continue

            values = _metric_values_from_row(row, spec.aliases, col_filter if col_filter else None)
            if not values:
                continue

            # Apply unit scale for absolute metrics (not % or EPS)
            def _scaled(v: float) -> float:
                if spec.unit in ("%",):
                    return round(v, 2)
                if spec.key == "eps":
                    return round(v, 2)  # EPS already in Rs
                return round(v * scale, 2)

            current[spec.key] = _scaled(values[0])
            if len(values) > 1:
                previous[spec.key] = _scaled(values[1])
            if len(values) > 2:
                year_ago[spec.key] = _scaled(values[2])

    # Strategy 2: Text-based extraction from all table cell content
    # This handles complex merged cells common in Indian filings
    if not current.get("revenue") or not current.get("pat") or not current.get("ebitda"):
        all_table_text = ""
        for table in tables:
            for row in table.get("rows") or []:
                all_table_text += " ".join(str(cell) for cell in row) + "\n"

        # Also search full document text for better coverage
        combined_text = all_table_text + "\n" + full_text

        # Define extraction patterns for common Indian financial statement formats
        # Patterns are ordered by specificity - more specific patterns first
        extraction_patterns = [
            # Revenue patterns (more specific first)
            (r"Revenue from Operations[^\d]*(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?)", "revenue"),
            (r"Total Income[^\d]*(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?)", "revenue"),
            (r"Net Sales[^\d]*(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?)", "revenue"),
            (r"Gross Revenue[^\d]*(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?)", "revenue"),
            (r"Total Revenue[^\d]*(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?)", "revenue"),
            (r"Operating Income[^\d]*(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?)", "revenue"),

            # PAT patterns (comprehensive coverage for Indian formats)
            (r"Profit After Tax[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),
            (r"Net Profit[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),
            (r"Profit for the (?:Period|Quarter|Year)[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),
            (r"Profit/\(Loss\) After Tax[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),
            (r"PAT[^\da-zA-Z]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),
            (r"Total Comprehensive Income[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),
            (r"Profit Attributable[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),
            (r"Net Profit/\(Loss\)[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "pat"),

            # EBITDA patterns
            (r"EBITDA[^\da-zA-Z]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),
            (r"Total Segment Profit[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),
            (r"Operating Profit[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),
            (r"Operating EBITDA[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),
            (r"Profit from Operations[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),
            (r"Profit before (?:Interest|Finance)[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),
            (r"PBDIT[^\da-zA-Z]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),
            (r"Earnings before Interest[^\d]*(\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?)", "ebitda"),

            # EPS patterns
            (r"(?:Basic|Diluted)\s+EPS[^\d]*(\(?-?\d+\.?\d*\)?)", "eps"),
            (r"Earnings (?:per|Per) (?:Share|Equity Share)[^\d]*(\(?-?\d+\.?\d*\)?)", "eps"),
            (r"EPS\s*\((?:Basic|Diluted)\)[^\d]*(\(?-?\d+\.?\d*\)?)", "eps"),
            (r"EPS[^\da-zA-Z]*(\(?-?\d+\.?\d*\)?)", "eps"),
        ]

        for pattern, key in extraction_patterns:
            if key in current:
                continue
            match = re.search(pattern, combined_text, re.IGNORECASE)
            if match:
                try:
                    raw_value = match.group(1).replace(",", "").strip()
                    # Handle negative values in parentheses
                    is_negative = raw_value.startswith("(") and raw_value.endswith(")")
                    raw_value = raw_value.strip("()")
                    value = float(raw_value)
                    if is_negative:
                        value = -value
                    # Apply scale for non-percentage, non-EPS metrics
                    if key not in ("eps",):
                        value = round(value * scale, 2)
                    else:
                        value = round(value, 2)
                    current[key] = value
                except (ValueError, TypeError):
                    pass

    # Compute margins if components available
    if "pat_margin" not in current and current.get("pat") is not None and current.get("revenue"):
        margin = (current["pat"] / current["revenue"]) * 100
        if abs(margin) <= 100:
            current["pat_margin"] = round(margin, 2)
    if "ebitda_margin" not in current and current.get("ebitda") is not None and current.get("revenue"):
        margin = (current["ebitda"] / current["revenue"]) * 100
        if abs(margin) <= 100:
            current["ebitda_margin"] = round(margin, 2)

    return current, previous, year_ago


def _metric_spec_for_row(row: list[str]) -> Any | None:
    label_text = " ".join(str(cell or "") for cell in row[:3]).lower()
    full_text = " ".join(str(cell or "") for cell in row).lower()
    for spec in METRIC_SPECS:
        if _contains_metric_alias(label_text, spec.aliases) or _contains_metric_alias(full_text[:160], spec.aliases):
            return spec
    return None


def _metric_values_from_row(
    row: list[str],
    aliases: tuple[str, ...],
    col_filter: list[int] | None = None,
) -> list[float]:
    """Extract numeric values from a table row, optionally filtering to specific column indices."""
    label_index = 0
    for idx, cell in enumerate(row):
        if _contains_metric_alias(str(cell or "").lower(), aliases):
            label_index = idx
            break

    # If col_filter provided, only consider those column indices (skip annual columns)
    if col_filter:
        data_cells = [row[i] for i in col_filter if i < len(row) and i > label_index]
        if not data_cells:
            data_cells = row[label_index + 1:] or row[1:]
    else:
        data_cells = row[label_index + 1:] or row[1:]

    values: list[float] = []
    for cell in data_cells:
        value = _number_from_cell(cell)
        if value is not None:
            values.append(value)
        if len(values) >= 3:  # current, previous, year-ago
            break
    return values


def _number_from_cell(cell: Any) -> float | None:
    text = str(cell or "").strip()
    if not text or text in {"-", "--", "na", "n.a."}:
        return None
    if re.search(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", text):
        return None
    match = _NUMBER_RE.search(text.replace("Rs.", "").replace("INR", ""))
    if not match:
        return None
    raw = match.group(0)
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return -value if negative else value


def _compact_table(table: dict[str, Any]) -> dict[str, Any]:
    rows = table.get("rows") or []
    return {
        "page_number": table.get("page_number") or 0,
        "confidence": table.get("confidence") or 0.0,
        "rows": [row[:8] for row in rows[:24]],
    }



_SECTION_HEADER_PATTERNS: dict[str, tuple[str, ...]] = {
    "standalone": (
        r"(?:part\s*[i1]|section\s*[i1a])?[^\n]*standalone[^\n]*(?:financial\s+)?results?",
        r"standalone\s+statement\s+of\s+(?:profit|assets|financial)",
        r"standalone\s+(?:audited|unaudited)\s+financial",
        r"statement\s+of\s+standalone",
    ),
    "consolidated": (
        r"(?:part\s*[ii2]|section\s*[ii2b])?[^\n]*consolidated[^\n]*(?:financial\s+)?results?",
        r"consolidated\s+statement\s+of\s+(?:profit|assets|financial)",
        r"consolidated\s+(?:audited|unaudited)\s+financial",
        r"statement\s+of\s+consolidated",
    ),
}

_SECTION_TERMINATORS: tuple[str, ...] = (
    r"\n\s*notes?\s+to\s+(?:the\s+)?(?:financial|standalone|consolidated)",
    r"\n\s*for\s+and\s+on\s+behalf",
    r"\n\s*place\s*:",
    r"\n\s*date\s*:",
    r"\n\s*(?:sd/-|director|chairman)\b",
    r"\n\s*(?:part\s+(?:iii|iv|3|4)|section\s+(?:iii|iv|c|d|3|4))\b",
)

_PERIOD_METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "revenue": (
        r"\brevenue\s+from\s+operations\b",
        r"\bnet\s+sales\b",
        r"\bturnover\b",
        r"\boperating\s+revenue\b",
    ),
    "pat": (
        r"\bnet\s+profit\s*/?\s*\(?\s*loss\s*\)?\s+for\s+the\s+(?:period|quarter|year)\b",
        r"\bprofit\s*/?\s*\(?\s*loss\s*\)?\s+(?:after|for)\s+tax\b",
        r"\bprofit\s+(?:after|for)\s+(?:tax|the\s+(?:period|quarter|year))\b",
    ),
    "ebitda": (
        r"\bebitda\b",
        r"\boperating\s+ebitda\b",
        r"\bpbd(?:i)?t\b",
    ),
    "eps": (
        r"\beps\b",
        r"\bearnings\s+per\s+(?:equity\s+)?share\b",
    ),
    "pbt": (
        r"\bprofit\s*/?\s*\(?\s*loss\s*\)?\s+before\s+(?:exceptional\s+items\s+and\s+)?tax\b",
        r"\bprofit\s+before\s+tax\b",
    ),
    "finance_cost": (r"\bfinance\s+costs?\b",),
    "depreciation": (r"\bdepreciation\s+and\s+amortization\s+expenses?\b", r"\bdepreciation\b"),
}


def _slice_labeled_financial_section(full_text: str, section_type: str) -> str:
    if not full_text:
        return ""
    text_lower = full_text.lower()
    patterns = _SECTION_HEADER_PATTERNS.get(section_type, ())
    section_start = -1
    for pattern in patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            section_start = match.start()
            break

    if section_start < 0 and section_type == "standalone":
        generic = re.search(
            r"statement\s+of\s+(?:audited\s+|unaudited\s+)?(?:standalone\s+)?financial\s+results",
            text_lower,
            re.IGNORECASE,
        )
        if generic:
            section_start = generic.start()

    if section_start < 0:
        return ""

    section_end = len(full_text)
    other_type = "consolidated" if section_type == "standalone" else "standalone"
    for pattern in _SECTION_HEADER_PATTERNS.get(other_type, ()):
        match = re.search(pattern, text_lower[section_start + 100 :], re.IGNORECASE)
        if match:
            section_end = min(section_end, section_start + 100 + match.start())
            break

    for pattern in _SECTION_TERMINATORS:
        match = re.search(pattern, text_lower[section_start + 100 :], re.IGNORECASE)
        if match:
            section_end = min(section_end, section_start + 100 + match.start())

    return full_text[section_start : min(section_end, section_start + 18000)]


def _statement_number_from_token(token: str) -> float | None:
    raw = str(token or "").strip().rstrip("'|]")
    if not raw or raw in {"-", "--"}:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace(",", "")
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    digits_only = cleaned.isdigit()
    if digits_only and "." not in raw and "," not in raw:
        if len(cleaned) >= 5:
            value = value / 100.0
        elif len(cleaned) == 3 and cleaned.startswith("0"):
            value = value / 100.0
    return -value if negative else value


def _line_looks_like_period_header(line: str) -> bool:
    lower = line.lower()
    return bool(
        re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", lower)
        or re.search(r"\b(?:quarter|year|nine\s+months|six\s+months)\s+ended\b", lower)
    )


def _numbers_from_statement_line(line: str) -> list[float]:
    if _line_looks_like_period_header(line):
        return []
    values: list[float] = []
    for match in _NUMBER_RE.finditer(line):
        value = _statement_number_from_token(match.group(0))
        if value is not None:
            values.append(value)
    return values


def _line_matches_any(line: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns)


def _is_new_statement_row(line: str) -> bool:
    lower = line.lower().strip()
    if not lower:
        return False
    row_signals = (
        "revenue", "income", "expenses", "cost of", "finance cost", "depreciation",
        "profit", "tax", "comprehensive", "paid-up", "other equity", "eps", "earnings per",
    )
    return any(signal in lower for signal in row_signals)


def _collect_statement_values(lines: list[str], index: int, metric_key: str, patterns: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    line = lines[index]
    lower = line.lower()

    if not (metric_key == "eps" and "face value" in lower):
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                values.extend(_numbers_from_statement_line(line[match.end() :]))
                break

    for next_line in lines[index + 1 : index + 16]:
        clean = next_line.strip()
        if not clean:
            continue
        clean_lower = clean.lower()
        if metric_key == "eps" and "face value" in clean_lower:
            continue
        if values and re.search(r"[A-Za-z]", clean) and _is_new_statement_row(clean):
            break
        if metric_key == "eps" and re.fullmatch(r"[-\s]*(basic|diluted)\s*", clean_lower):
            continue
        nums = _numbers_from_statement_line(clean)
        if nums:
            values.extend(nums)
            if len(values) >= 5:
                break
            continue
        if values and re.search(r"[A-Za-z]", clean):
            break

    return values[:3]


def _first_statement_metric_values(section_text: str, metric_key: str) -> list[float]:
    patterns = _PERIOD_METRIC_PATTERNS[metric_key]
    lines = [line.strip() for line in section_text.splitlines()]
    for idx, line in enumerate(lines):
        if not line or not _line_matches_any(line, patterns):
            continue
        if metric_key == "pat" and re.search(r"before\s+tax", line, re.IGNORECASE):
            continue
        values = _collect_statement_values(lines, idx, metric_key, patterns)
        if values:
            return values
    return []


def _value_at(values: list[float], index: int) -> float | None:
    return values[index] if index < len(values) else None


def _scaled_statement_value(value: float | None, *, scale: float, is_absolute: bool) -> float | None:
    if value is None:
        return None
    result = value * scale if is_absolute else value
    return round(result, 2)


def _add_margin_metrics(metrics: dict[str, float]) -> None:
    revenue = metrics.get("revenue")
    if not revenue:
        return
    pat = metrics.get("pat")
    if pat is not None and "pat_margin" not in metrics:
        margin = (pat / revenue) * 100
        if abs(margin) <= 100:
            metrics["pat_margin"] = round(margin, 2)
    ebitda = metrics.get("ebitda")
    if ebitda is not None and "ebitda_margin" not in metrics:
        margin = (ebitda / revenue) * 100
        if abs(margin) <= 100:
            metrics["ebitda_margin"] = round(margin, 2)


def _extract_metric_periods_from_labeled_section(
    full_text: str,
    section_type: str,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    section_text = _slice_labeled_financial_section(full_text, section_type)
    if len(section_text) < 120:
        return {}, {}, {}

    scale = _detect_unit_scale([], section_text)
    raw_periods: dict[str, list[float]] = {}
    for key in ("revenue", "pat", "ebitda", "eps", "pbt", "finance_cost", "depreciation"):
        values = _first_statement_metric_values(section_text, key)
        if values:
            raw_periods[key] = values

    if "ebitda" not in raw_periods and raw_periods.get("pbt"):
        derived: list[float] = []
        for idx in range(3):
            pbt = _value_at(raw_periods.get("pbt", []), idx)
            finance = _value_at(raw_periods.get("finance_cost", []), idx) or 0.0
            depreciation = _value_at(raw_periods.get("depreciation", []), idx) or 0.0
            if pbt is None:
                continue
            derived.append(pbt + finance + depreciation)
        if derived:
            raw_periods["ebitda"] = derived

    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    year_ago: dict[str, float] = {}
    period_targets = (current, previous, year_ago)
    for key in ("revenue", "pat", "ebitda", "eps"):
        values = raw_periods.get(key) or []
        is_absolute = key != "eps"
        for idx, target in enumerate(period_targets):
            scaled = _scaled_statement_value(_value_at(values, idx), scale=scale, is_absolute=is_absolute)
            if scaled is not None:
                target[key] = scaled

    for target in period_targets:
        _add_margin_metrics(target)

    return current, previous, year_ago


def _format_metric_for_highlight(value: Any, unit: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "not disclosed"
    if unit == "%":
        return f"{number:.1f}%"
    if unit == "Rs":
        return f"Rs {number:.2f}"
    return f"Rs {number:,.2f} Cr"


def _change_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, label in (("qoq_pct", "QoQ"), ("yoy_pct", "YoY")):
        value = row.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        direction = "up" if number >= 0 else "down"
        parts.append(f"{direction} {abs(number):.1f}% {label}")
    return ", ".join(parts)


def _build_metric_highlights(rows: list[dict[str, Any]], source_url: str) -> list[dict[str, str]]:
    by_key = {str(row.get("key") or ""): row for row in rows if row.get("current") is not None}
    highlights: list[str] = []

    revenue = by_key.get("revenue")
    if revenue:
        change = _change_text(revenue)
        tail = f", {change}" if change else ""
        highlights.append(f"Revenue came in at {_format_metric_for_highlight(revenue.get('current'), revenue.get('unit') or 'Rs Cr')}{tail}.")

    pat = by_key.get("pat")
    if pat:
        change = _change_text(pat)
        tail = f", {change}" if change else ""
        highlights.append(f"Profit after tax was {_format_metric_for_highlight(pat.get('current'), pat.get('unit') or 'Rs Cr')}{tail}.")

    ebitda = by_key.get("ebitda")
    margin = by_key.get("ebitda_margin")
    if ebitda:
        change = _change_text(ebitda)
        margin_text = ""
        if margin and margin.get("current") is not None:
            margin_text = f", implying an EBITDA margin of {_format_metric_for_highlight(margin.get('current'), '%')}"
        tail = f"; {change}" if change else ""
        highlights.append(f"EBITDA was {_format_metric_for_highlight(ebitda.get('current'), ebitda.get('unit') or 'Rs Cr')}{margin_text}{tail}.")

    eps = by_key.get("eps")
    if eps:
        change = _change_text(eps)
        tail = f", {change}" if change else ""
        highlights.append(f"EPS was {_format_metric_for_highlight(eps.get('current'), eps.get('unit') or 'Rs')}{tail}.")

    return [
        {
            "text": item,
            "url": source_url or "",
            "source_label": "official filing" if source_url else "",
        }
        for item in highlights[:4]
    ]


def _extract_metrics_from_labeled_section(full_text: str, section_type: str) -> dict[str, Any]:
    """Extract current-period metrics from a standalone/consolidated P&L section."""
    current, _, _ = _extract_metric_periods_from_labeled_section(full_text, section_type)
    return current


def _extract_metrics_from_text_section(full_text: str, section_type: str) -> dict[str, Any]:
    """Legacy wrapper - use _extract_metrics_from_labeled_section instead."""
    return _extract_metrics_from_labeled_section(full_text, section_type)
