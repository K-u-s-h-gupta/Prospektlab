"""PyMuPDF-first extraction for IPO DRHP/RHP PDFs."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("finagent.ingestion.ipo_pdf_extractor")

IPO_PDF_MAX_FILE_MB = int(os.getenv("IPO_PDF_MAX_FILE_MB", "150"))


@dataclass
class IpoPdfExtraction:
    markdown: str
    page_count: int
    tables_extracted: int
    extractor_used: str = "pymupdf"
    duration_s: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _rows_to_markdown(rows: list[list[Any]]) -> str:
    if not rows or not rows[0]:
        return ""
    headers = [str(cell or "").strip().replace("|", " ") for cell in rows[0]]
    if not any(headers):
        return ""

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows[1:]:
        cells = [str(cell or "").strip().replace("\n", " ").replace("|", " ") for cell in row]
        if len(cells) < len(headers):
            cells.extend("" for _ in range(len(headers) - len(cells)))
        lines.append("| " + " | ".join(cells[: len(headers)]) + " |")
    return "\n".join(lines)


def _extract_markdown_sync(file_bytes: bytes, filename: str) -> IpoPdfExtraction:
    start_t = time.time()
    if not file_bytes:
        raise ValueError(f"Empty PDF payload for {filename}")

    max_file_bytes = IPO_PDF_MAX_FILE_MB * 1024 * 1024
    if len(file_bytes) > max_file_bytes:
        raise ValueError(
            f"PDF exceeds {IPO_PDF_MAX_FILE_MB} MB limit for IPO extraction ({filename})"
        )

    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - environment dependency
        raise RuntimeError("PyMuPDF is required for IPO PDF extraction") from exc

    page_markdown: list[str] = []
    total_tables = 0

    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        page_count = int(doc.page_count or 0)
        for page_idx, page in enumerate(doc, start=1):
            page_parts: list[str] = []
            table_bboxes: list[tuple[float, float, float, float]] = []

            try:
                found = page.find_tables()
                for table in getattr(found, "tables", []) or []:
                    data = table.extract()
                    table_md = _rows_to_markdown(data)
                    if table_md:
                        page_parts.append(table_md)
                        table_bboxes.append(table.bbox)
                        total_tables += 1
            except Exception as exc:
                logger.debug("[IPO-PDF] Table extraction failed on page %d of %s: %s", page_idx, filename, exc)

            try:
                blocks = sorted(page.get_text("blocks"), key=lambda b: (b[1], b[0]))
            except Exception as exc:
                logger.debug("[IPO-PDF] Block extraction failed on page %d of %s: %s", page_idx, filename, exc)
                blocks = []

            text_blocks: list[str] = []
            for block in blocks:
                if len(block) < 5:
                    continue
                raw_text = str(block[4] or "").strip()
                if not raw_text:
                    continue

                bx0, by0, bx1, by1 = block[0:4]
                cx = (bx0 + bx1) / 2.0
                cy = (by0 + by1) / 2.0
                in_table = False
                for tx0, ty0, tx1, ty1 in table_bboxes:
                    if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
                        in_table = True
                        break
                if in_table:
                    continue

                cleaned_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
                if cleaned_lines:
                    text_blocks.append("\n".join(cleaned_lines))

            combined_parts: list[str] = []
            if text_blocks:
                combined_parts.append("\n\n".join(text_blocks))
            if page_parts:
                combined_parts.extend(page_parts)

            if combined_parts:
                page_markdown.append(f"## Page {page_idx}\n\n" + "\n\n".join(combined_parts))

    markdown = "\n\n".join(page_markdown).strip()
    duration_s = time.time() - start_t
    logger.info(
        "[IPO-PDF] Extracted %d pages, %d tables, %d chars from %s in %.1fs",
        page_count,
        total_tables,
        len(markdown),
        filename,
        duration_s,
    )
    return IpoPdfExtraction(
        markdown=markdown,
        page_count=page_count,
        tables_extracted=total_tables,
        duration_s=duration_s,
        diagnostics={
            "filename": filename,
            "page_count": page_count,
            "tables_extracted": total_tables,
            "markdown_chars": len(markdown),
        },
    )


async def extract_ipo_pdf_markdown(file_bytes: bytes, filename: str = "document.pdf") -> IpoPdfExtraction:
    return await asyncio.to_thread(_extract_markdown_sync, file_bytes, filename)
