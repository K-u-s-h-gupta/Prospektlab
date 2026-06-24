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


def extract_pdf_text(pdf_bytes: bytes, *, require_tables: bool = True) -> dict[str, Any]:
    """Extract text and tables from a PDF with PyMuPDF first, Azure DI on poor quality."""
    if not pdf_bytes:
        return {"text": "", "page_count": 0, "model": None, "tables": [], "error": "empty pdf"}

    try:
        from finagent.ingestion.azure_doc_intel import extract_document

        timeout_s = float(os.getenv("FINAGENT_EARNINGS_DI_TIMEOUT_S", "120") or "120")
        result = _run_async(
            lambda: extract_document(
                file_bytes=pdf_bytes,
                model_id="prebuilt-layout",
                timeout_s=timeout_s,
                allow_fallback=True,
                require_tables=require_tables,
            )
        )
        return {
            "text": getattr(result, "full_text", "") or "",
            "page_count": int(getattr(result, "page_count", 0) or 0),
            "model": getattr(result, "model_used", None),
            "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
            "fallback_used": bool(getattr(result, "fallback_used", False)),
            "tables": _tables_from_document_result(result),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Document extraction helper failed, using local PyMuPDF only: %s", exc)
        local = _extract_pdf_local_only(pdf_bytes)
        local["error"] = local.get("error") or str(exc)
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
        text = "\n\n".join(text_parts).strip()
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
        rows = [[str(cell or "") for cell in row] for row in (getattr(table, "rows", None) or [])]
        if not rows:
            continue
        page_number = int(getattr(table, "page_number", 0) or 0)
        tables.append(
            {
                "page_number": page_number,
                "rows": rows,
                "confidence": float(getattr(table, "confidence", 0.0) or 0.0),
                "page_text": pages.get(page_number, ""),
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
    selected_tables = _select_financial_tables(tables)
    table_text = "\n\n".join(_table_to_text(table) for table in selected_tables)
    analysis_text = f"{full_text}\n\n{table_text}".strip()

    source_url = str(metadata.get("source_url") or metadata.get("attachment_url") or "").strip()
    table_current, table_previous, table_year_ago = _metrics_from_tables(selected_tables)
    current_metrics = extract_financial_metrics(analysis_text)
    current_metrics.update(table_current)
    comparison_previous = previous_metrics or table_previous
    comparison_year_ago = year_ago_metrics or table_year_ago

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

    commentary = payload["highlights"][:]
    if analysis_text and not commentary:
        commentary = [
            {
                "text": compact_summary(analysis_text, 180),
                "url": source_url,
                "source_label": "official filing" if source_url else "",
            }
        ]

    financial_rows = payload["financial_comparison"]
    if table_current:
        financial_rows = build_financial_comparison_rows(table_current, comparison_previous, comparison_year_ago)

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
        "highlights": payload["highlights"],
        "management_commentary": commentary,
        "transcript": payload["transcript"],
        "financials": {
            "metrics": current_metrics,
            "rows": financial_rows,
            "unit_note": "Absolute values are in Rs crore except EPS and margins. Tables prefer consolidated results when present.",
            "source": extraction.get("model") or "provided_text",
            "consolidated_tables": [_compact_table(table) for table in selected_tables[:_MAX_TABLES_IN_PAYLOAD]],
        },
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


def _select_financial_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, table in enumerate(tables):
        table_text = _table_to_text(table).lower()
        page_text = str(table.get("page_text") or "").lower()
        metric_hits = sum(1 for spec in METRIC_SPECS if _contains_metric_alias(table_text, spec.aliases))
        if metric_hits == 0:
            continue
        score = metric_hits * 3
        if "consolidated" in table_text:
            score += 12
        elif "consolidated" in page_text:
            score += 4
        first_rows = " ".join(" ".join(row) for row in table.get("rows", [])[:4]).lower()
        if "standalone" in first_rows and "consolidated" not in first_rows:
            score -= 6
        rows = table.get("rows") or []
        if len(rows) >= 4 and max((len(row) for row in rows), default=0) >= 3:
            score += 2
        scored.append((score, index, table))
    scored.sort(key=lambda item: (-item[0], item[1]))
    consolidated = [table for score, _, table in scored if score >= 10 and _is_consolidated(table)]
    return consolidated or [table for _, _, table in scored]


def _is_consolidated(table: dict[str, Any]) -> bool:
    return "consolidated" in _table_to_text(table).lower() or "consolidated" in str(table.get("page_text") or "").lower()


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


def _metrics_from_tables(tables: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    year_ago: dict[str, float] = {}
    for table in tables:
        for row in table.get("rows") or []:
            spec = _metric_spec_for_row(row)
            if not spec or spec.key in current:
                continue
            values = _metric_values_from_row(row, spec.aliases)
            if not values:
                continue
            current[spec.key] = values[0]
            if len(values) > 1:
                previous[spec.key] = values[1]
            if len(values) > 2:
                year_ago[spec.key] = values[2]
    if "pat_margin" not in current and current.get("pat") is not None and current.get("revenue"):
        current["pat_margin"] = round((current["pat"] / current["revenue"]) * 100, 2)
    if "ebitda_margin" not in current and current.get("ebitda") is not None and current.get("revenue"):
        current["ebitda_margin"] = round((current["ebitda"] / current["revenue"]) * 100, 2)
    return current, previous, year_ago


def _metric_spec_for_row(row: list[str]) -> Any | None:
    label_text = " ".join(str(cell or "") for cell in row[:3]).lower()
    full_text = " ".join(str(cell or "") for cell in row).lower()
    for spec in METRIC_SPECS:
        if _contains_metric_alias(label_text, spec.aliases) or _contains_metric_alias(full_text[:160], spec.aliases):
            return spec
    return None


def _metric_values_from_row(row: list[str], aliases: tuple[str, ...]) -> list[float]:
    label_index = 0
    for idx, cell in enumerate(row):
        if _contains_metric_alias(str(cell or "").lower(), aliases):
            label_index = idx
            break
    cells = row[label_index + 1 :] or row[1:]
    values: list[float] = []
    for cell in cells:
        value = _number_from_cell(cell)
        if value is not None:
            values.append(value)
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