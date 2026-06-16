"""Document section selection helpers for IKG ingestion.

The selector is intentionally deterministic: it performs a cheap local page
scan first, selects whole page ranges, and expands table-like runs so Azure DI
does not receive partial pages or broken table continuations.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("finagent.ikg.document_selector")


@dataclass(frozen=True)
class PagePreview:
    page_number: int
    text: str


@dataclass(frozen=True)
class SelectedPage:
    page_number: int
    score: int
    categories: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    table_like: bool = False


@dataclass(frozen=True)
class PageSelection:
    pages: tuple[int, ...]
    page_ranges: str
    selected_pages: tuple[SelectedPage, ...]
    total_pages: int

    @property
    def empty(self) -> bool:
        return not self.pages


_ANNUAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "board_and_kmp": (
        "board of directors", "composition of board", "key managerial personnel",
        "kmp", "chief executive officer", "managing director", "whole-time director",
        "chief financial officer", "company secretary",
    ),
    "governance": (
        "corporate governance", "regulation 27", "board committees",
        "audit committee", "nomination and remuneration committee",
        "stakeholders relationship committee",
    ),
    "ownership": (
        "shareholding pattern", "promoter and promoter group", "promoter group",
        "substantial shareholders", "holding company", "shareholding",
        "pledge", "encumbrance",
    ),
    "group_structure": (
        "subsidiaries", "subsidiary companies", "associate companies",
        "joint ventures", "joint venture", "step-down subsidiary",
        "list of subsidiaries", "form aoc-1",
    ),
    "related_party": (
        "related party transactions", "related party", "regulation 23",
        "transactions with related parties",
    ),
    "audit_and_risk": (
        "auditor", "statutory auditors", "audit qualification",
        "qualified opinion", "emphasis of matter", "internal financial controls",
        "contingent liabilities", "litigation", "risk management",
        "management discussion and analysis", "md&a",
    ),
    "financial_highlights": (
        "financial highlights", "standalone financial statements",
        "consolidated financial statements", "profit and loss", "balance sheet",
        "cash flow statement", "notes to accounts",
    ),
}

_FILLER_KEYWORDS = (
    "corporate information",
    "notice is hereby given",
    "route map",
    "proxy form",
    "attendance slip",
    "e-voting instructions",
    "safe harbor",
    "forward-looking statement",
    "awards and recognition",
    "photo gallery",
)

_TABLE_HINTS = (
    "particulars", "amount", "inr", "rs.", "crore", "lakhs", "year ended",
    "standalone", "consolidated", "total", "assets", "liabilities", "equity",
    "continued", "contd", "note no", "schedule",
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def page_has_table_signal(text: str) -> bool:
    """Best-effort table continuation signal from local PDF text extraction."""
    normalized = _normalize_text(text)
    if not normalized:
        return False
    numeric_tokens = re.findall(r"(?:\d{1,3}(?:,\d{2,3})+|\d+\.\d+|\d{4})", normalized)
    hint_count = sum(1 for hint in _TABLE_HINTS if hint in normalized)
    line_count = len([line for line in (text or "").splitlines() if line.strip()])
    dense_numeric_page = len(numeric_tokens) >= 8 and line_count >= 12
    return hint_count >= 2 or dense_numeric_page


def score_annual_report_page(text: str) -> SelectedPage:
    normalized = _normalize_text(text)
    categories: list[str] = []
    reasons: list[str] = []
    score = 0

    for category, phrases in _ANNUAL_KEYWORDS.items():
        matches = [phrase for phrase in phrases if phrase in normalized]
        if not matches:
            continue
        categories.append(category)
        reasons.extend(matches[:3])
        score += 2 + min(len(matches), 3)

    if page_has_table_signal(text):
        score += 1

    if any(phrase in normalized for phrase in _FILLER_KEYWORDS):
        score -= 2

    return SelectedPage(
        page_number=0,
        score=max(score, 0),
        categories=tuple(dict.fromkeys(categories)),
        reasons=tuple(dict.fromkeys(reasons)),
        table_like=page_has_table_signal(text),
    )


def pages_to_ranges(pages: list[int] | tuple[int, ...] | set[int]) -> str:
    ordered = sorted({int(p) for p in pages if int(p) > 0})
    if not ordered:
        return ""
    ranges: list[str] = []
    start = prev = ordered[0]
    for page in ordered[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = page
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(ranges)


def extract_pdf_page_previews(file_path: str | Path, *, max_pages: int | None = None) -> list[PagePreview]:
    """Extract per-page text for cheap section selection.

    Uses PyMuPDF when available because it tends to preserve page text better,
    then falls back to pypdf which is already part of the project dependencies.
    """
    path = Path(file_path)
    previews: list[PagePreview] = []
    try:
        import fitz  # type: ignore

        doc = fitz.open(path)
        limit = min(len(doc), max_pages or len(doc))
        for idx in range(limit):
            previews.append(PagePreview(page_number=idx + 1, text=doc[idx].get_text("text") or ""))
        doc.close()
        return previews
    except Exception as exc:
        logger.debug("PyMuPDF page preview failed for %s: %s", path, exc)

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        limit = min(len(reader.pages), max_pages or len(reader.pages))
        for idx in range(limit):
            try:
                text = reader.pages[idx].extract_text() or ""
            except Exception:
                text = ""
            previews.append(PagePreview(page_number=idx + 1, text=text))
    except Exception as exc:
        logger.warning("PDF page preview failed for %s: %s", path, exc)
    return previews


def select_useful_annual_report_pages(
    previews: list[PagePreview],
    *,
    min_score: int = 3,
    context_pages: int = 1,
    max_selected_pages: int = 80,
) -> PageSelection:
    """Select high-value annual-report pages and preserve table continuations."""
    if not previews:
        return PageSelection(pages=(), page_ranges="", selected_pages=(), total_pages=0)

    by_page = {preview.page_number: preview for preview in previews}
    scored: dict[int, SelectedPage] = {}
    selected: set[int] = set()
    table_like_pages = {p.page_number for p in previews if page_has_table_signal(p.text)}

    for preview in previews:
        base = score_annual_report_page(preview.text)
        scored_page = SelectedPage(
            page_number=preview.page_number,
            score=base.score,
            categories=base.categories,
            reasons=base.reasons,
            table_like=base.table_like,
        )
        scored[preview.page_number] = scored_page
        if scored_page.score >= min_score:
            selected.add(preview.page_number)

    expanded = set(selected)
    max_page = max(by_page)
    for page in list(selected):
        for context in range(page - context_pages, page + context_pages + 1):
            if 1 <= context <= max_page:
                expanded.add(context)

        # If a selected page is table-like, include the contiguous table run so
        # multi-page schedules are extracted as complete whole-page ranges.
        if page in table_like_pages:
            prev_page = page - 1
            while prev_page in table_like_pages:
                expanded.add(prev_page)
                prev_page -= 1
            next_page = page + 1
            while next_page in table_like_pages:
                expanded.add(next_page)
                next_page += 1

    selected_sorted = sorted(expanded)
    if len(selected_sorted) > max_selected_pages:
        ranked = sorted(
            selected_sorted,
            key=lambda page: (scored.get(page, SelectedPage(page, 0)).score, -page),
            reverse=True,
        )[:max_selected_pages]
        selected_sorted = sorted(ranked)

    selected_pages = tuple(scored.get(page, SelectedPage(page, 0)) for page in selected_sorted)
    return PageSelection(
        pages=tuple(selected_sorted),
        page_ranges=pages_to_ranges(selected_sorted),
        selected_pages=selected_pages,
        total_pages=len(previews),
    )


def build_document_sections_from_extraction(
    *,
    document_uid: str,
    document_type: str,
    source_url: str | None,
    selection: PageSelection,
    extracted_pages: list[Any],
    tables: list[Any],
    company_cin: str | None = None,
    company_symbol: str | None = None,
    company_scrip_code: str | None = None,
    company_name: str | None = None,
) -> list[dict[str, Any]]:
    """Create section rows for selected page ranges from an Azure DI result."""
    page_text = {
        int(getattr(page, "page_number", 0) or 0): str(getattr(page, "text", "") or "")
        for page in extracted_pages
    }
    selected_by_page = {page.page_number: page for page in selection.selected_pages}
    sections: list[dict[str, Any]] = []

    for raw_range in selection.page_ranges.split(","):
        raw_range = raw_range.strip()
        if not raw_range:
            continue
        if "-" in raw_range:
            start_s, end_s = raw_range.split("-", 1)
            page_start, page_end = int(start_s), int(end_s)
        else:
            page_start = page_end = int(raw_range)
        pages = list(range(page_start, page_end + 1))
        text = "\n\n".join(page_text.get(page, "") for page in pages).strip()
        categories: list[str] = []
        reasons: list[str] = []
        for page in pages:
            scored = selected_by_page.get(page)
            if not scored:
                continue
            categories.extend(scored.categories)
            reasons.extend(scored.reasons)

        tables_markdown: list[str] = []
        for table in tables:
            table_pages = set(getattr(table, "page_numbers", None) or [getattr(table, "page_number", 0)])
            if table_pages.intersection(pages):
                markdown = getattr(table, "markdown", "")
                if markdown:
                    tables_markdown.append(markdown)

        category_list = list(dict.fromkeys(categories)) or ["annual_report_selected"]
        title = f"Annual report selected section pages {page_start}-{page_end}"
        metadata = {
            "categories": category_list,
            "matched_reasons": list(dict.fromkeys(reasons)),
            "selection_ranges": selection.page_ranges,
            "total_pages_scanned": selection.total_pages,
        }
        identifier = (company_cin or company_symbol or company_scrip_code or "").strip()
        if identifier:
            metadata["company_identifier"] = identifier
        if company_cin:
            metadata["cin"] = company_cin
            metadata["company_cin"] = company_cin
        if company_symbol:
            metadata["nse_symbol"] = company_symbol
        if company_scrip_code:
            metadata["bse_scrip_code"] = company_scrip_code
        if company_name:
            metadata["company_name"] = company_name
        sections.append({
            "document_uid": document_uid,
            "document_type": document_type,
            "section_type": category_list[0],
            "title": title,
            "page_start": page_start,
            "page_end": page_end,
            "text": text,
            "text_length": len(text),
            "tables_markdown": "\n\n".join(tables_markdown),
            "confidence": 0.85 if text else 0.5,
            "source_url": source_url,
            "metadata": metadata,
        })

    return sections
