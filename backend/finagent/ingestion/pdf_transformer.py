from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.ingestion.pdf_transformer")


@dataclass
class DocumentMarkdown:
    markdown: str
    source_type: str
    transformer: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


class DocumentTransformError(RuntimeError):
    def __init__(self, code: str, message: str, diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or {}


def _suffix(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def _source_type(filename: str) -> str:
    ext = _suffix(filename)
    if ext == ".pdf":
        return "pdf"
    if ext == ".csv":
        return "csv"
    if ext in {".xls", ".xlsx"}:
        return "xlsx"
    return "unknown"


def _decrypt_pdf_if_needed(data: bytes, password: str) -> bytes:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return data

    try:
        reader = PdfReader(io.BytesIO(data))
        if not reader.is_encrypted:
            return data
        if not password:
            raise DocumentTransformError(
                "PASSWORD_REQUIRED",
                "This PDF is encrypted. Enter the eCAS password and retry.",
                {"stage": "pdf_decrypt"},
            )
        result = reader.decrypt(password)
        if result == 0:
            raise DocumentTransformError(
                "INCORRECT_PASSWORD",
                "Incorrect PDF password. Please retry with the eCAS password.",
                {"stage": "pdf_decrypt"},
            )
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except DocumentTransformError:
        raise
    except Exception as exc:
        logger.debug("PDF decrypt pre-pass failed, passing bytes to transformer: %s", exc)
        return data


def _decrypt_excel_if_needed(path: str, password: str) -> str:
    if not password:
        return path
    try:
        import msoffcrypto
    except ImportError:
        return path

    try:
        with open(path, "rb") as fh:
            office = msoffcrypto.OfficeFile(fh)
            if not office.is_encrypted():
                return path
            office.load_key(password=password)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(path).suffix)
            try:
                office.decrypt(tmp)
                tmp.close()
                return tmp.name
            except Exception:
                tmp.close()
                os.unlink(tmp.name)
                raise
    except Exception as exc:
        raise DocumentTransformError(
            "EXCEL_DECRYPT_FAILED",
            "Could not decrypt the Excel workbook. Check the password or upload an unencrypted export.",
            {"stage": "excel_decrypt", "error": str(exc)},
        ) from exc


def _table_to_markdown_from_pandas(path: str, source_type: str) -> str:
    try:
        import pandas as pd
    except ImportError as exc:
        raise DocumentTransformError(
            "PANDAS_NOT_INSTALLED",
            "Pandas is required for CSV/XLSX fallback conversion.",
            {"stage": "pandas_import"},
        ) from exc

    try:
        if source_type == "csv":
            frames = [pd.read_csv(path, nrows=10000)]
        else:
            # Limit Excel to first 10 rows per sheet for header detection, then
            # read full data up to 10,000 rows per sheet to prevent memory exhaustion.
            sheets = pd.read_excel(path, sheet_name=None, nrows=10000)
            frames = [frame for frame in sheets.values()]
    except Exception as exc:
        raise DocumentTransformError(
            "TABLE_READ_FAILED",
            "Could not read the uploaded table file.",
            {"stage": "pandas_read", "error": str(exc)},
        ) from exc

    parts: list[str] = []
    for idx, frame in enumerate(frames, start=1):
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        if frame.empty:
            continue
        headers = [str(col).strip() for col in frame.columns]
        rows = frame.fillna("").astype(str).values.tolist()
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            lines.append("| " + " | ".join(cell.replace("|", " ") for cell in row) + " |")
        parts.append(f"\n\n## Sheet {idx}\n\n" + "\n".join(lines))
    if not parts:
        raise DocumentTransformError(
            "NO_TABLES_FOUND",
            "The uploaded table file did not contain readable rows.",
            {"stage": "pandas_markdown"},
        )
    return "\n".join(parts)





def _fitz_layout_to_markdown(pdf_path_or_bytes: str | bytes) -> str:
    """Fallback high-accuracy layout extraction using PyMuPDF (fitz) with table detection.
    
    Ensures that text columns and table grids do not get mixed up.
    
    Hardening:
    - Max 200 pages to prevent memory exhaustion.
    - Max 50MB input to prevent OOM.
    """
    import fitz
    
    MAX_PAGES = 200
    MAX_FILE_SIZE = 50 * 1024 * 1024
    
    if isinstance(pdf_path_or_bytes, bytes):
        if len(pdf_path_or_bytes) > MAX_FILE_SIZE:
            raise DocumentTransformError(
                "DOCUMENT_TOO_LARGE",
                f"PDF exceeds {MAX_FILE_SIZE // (1024 * 1024)} MB limit.",
            )
        doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
    else:
        size = os.path.getsize(pdf_path_or_bytes)
        if size > MAX_FILE_SIZE:
            raise DocumentTransformError(
                "DOCUMENT_TOO_LARGE",
                f"PDF exceeds {MAX_FILE_SIZE // (1024 * 1024)} MB limit.",
            )
        doc = fitz.open(pdf_path_or_bytes)
    
    if doc.page_count > MAX_PAGES:
        doc.close()
        raise DocumentTransformError(
            "DOCUMENT_TOO_LARGE",
            f"PDF exceeds {MAX_PAGES} pages.",
        )
        
    markdown_parts = []
    
    for page_idx, page in enumerate(doc):
        # Find tables
        tables = page.find_tables()
        table_bboxes = [t.bbox for t in tables.tables]
        
        # Sort tables by top Y coordinate
        sorted_tables = sorted(tables.tables, key=lambda t: t.bbox[1])
        
        # Get blocks
        blocks = page.get_text("blocks")
        sorted_blocks = sorted(blocks, key=lambda b: (b[1], b[0]))
        
        elements = []
        for block in sorted_blocks:
            # Check if this block is inside any table's bbox
            in_table = False
            bx0, by0, bx1, by1 = block[0:4]
            for tx0, ty0, tx1, ty1 in table_bboxes:
                cx = (bx0 + bx1) / 2.0
                cy = (by0 + by1) / 2.0
                if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
                    in_table = True
                    break
            if not in_table:
                # Basic header detection based on text size / styling
                text = block[4].strip()
                if text:
                    elements.append(("text", block[1], text))
                    
        for t in sorted_tables:
            data = t.extract()
            if not data or not data[0]:
                continue
            
            # Format table as Markdown
            headers = [str(cell or "").strip() for cell in data[0]]
            md_table = []
            md_table.append("| " + " | ".join(headers) + " |")
            md_table.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in data[1:]:
                row_cells = [str(cell or "").strip().replace("\n", " ").replace("|", " ") for cell in row]
                md_table.append("| " + " | ".join(row_cells) + " |")
                
            md_text = "\n".join(md_table)
            elements.append(("table", t.bbox[1], md_text))
            
        # Sort all elements on page vertically
        elements.sort(key=lambda e: e[1])
        
        page_md = []
        for etype, y, text in elements:
            page_md.append(text)
            
        if page_md:
            markdown_parts.append(f"## Page {page_idx + 1}\n\n" + "\n\n".join(page_md))
        
    doc.close()
    return "\n\n".join(markdown_parts)


def _pdf_to_markdown(path: str) -> tuple[str, str]:
    """Process a PDF using Azure Document Intelligence (primary) or PyMuPDF (fallback).

    Strategy:
      1. If AZURE_DI_ENDPOINT + AZURE_DI_KEY are configured → use Azure DI
         (better table extraction, key-value pair extraction, higher accuracy)
      2. Otherwise → use PyMuPDF fitz layout extraction

    Returns Markdown representation of the PDF content + transformer name.
    """
    # Try Azure Document Intelligence first
    try:
        from finagent.ingestion.azure_doc_intel import is_azure_di_configured, extract_document
        if is_azure_di_configured():
            import asyncio
            with open(path, "rb") as fh:
                file_bytes = fh.read()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            di_result = loop.run_until_complete(extract_document(file_bytes=file_bytes))

            if di_result.full_text and len(di_result.full_text.strip()) > 50:
                # Combine full text with any extracted tables
                parts = [di_result.full_text]
                if di_result.tables:
                    parts.append("\n\n## Extracted Tables\n")
                    parts.append(di_result.tables_markdown)
                logger.info(
                    "[PDF-DI] Azure DI extracted %d pages, %d tables, %.0fs",
                    di_result.page_count, len(di_result.tables), di_result.duration_s,
                )
                return "\n\n".join(parts), "azure_document_intelligence"
            else:
                logger.warning("[PDF-DI] Azure DI returned empty text, falling back to PyMuPDF")
    except ImportError:
        pass  # azure_doc_intel module not available
    except Exception as exc:
        logger.warning("[PDF-DI] Azure DI failed, falling back to PyMuPDF: %s", exc)

    # Fallback: PyMuPDF layout extraction
    try:
        markdown = _fitz_layout_to_markdown(path)
        return markdown, "fitz_layout"
    except ImportError as exc:
        if "fitz" in str(exc).lower() or "pymupdf" in str(exc).lower():
            logger.error("PyMuPDF (fitz) is not installed. PDF extraction requires 'pymupdf' package.")
            raise DocumentTransformError(
                "PYMUPDF_NOT_INSTALLED",
                "PDF extraction requires the 'pymupdf' package (provides the 'fitz' module). "
                "Install it with: pip install pymupdf>=1.24.0",
                {"stage": "fitz_import", "error": str(exc)},
            ) from exc
        raise
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        raise DocumentTransformError(
            "PDF_EXTRACTION_FAILED",
            "Failed to extract content from PDF.",
            {"stage": "fitz_extraction", "error": str(exc)},
        ) from exc


async def document_to_markdown(data: bytes, filename: str, password: str = "") -> DocumentMarkdown:
    source_type = _source_type(filename)
    if source_type == "unknown":
        raise DocumentTransformError(
            "UNSUPPORTED_FILE_TYPE",
            "Upload a PDF, CSV, XLS, or XLSX holdings document.",
            {"filename": filename},
        )
    if not data:
        raise DocumentTransformError("EMPTY_UPLOAD", "Uploaded file is empty.", {"filename": filename})

    payload = _decrypt_pdf_if_needed(data, password) if source_type == "pdf" else data
    suffix = ".xlsx" if source_type == "xlsx" and _suffix(filename) == ".xls" else _suffix(filename)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    fallback_tmp: str | None = None
    try:
        tmp.write(payload)
        tmp.close()
        path = _decrypt_excel_if_needed(tmp.name, password) if source_type == "xlsx" else tmp.name
        fallback_tmp = path if path != tmp.name else None

        if source_type == "pdf":
            # Offload PDF extraction to worker thread
            markdown, transformer = await asyncio.to_thread(_pdf_to_markdown, path)
        else:
            markdown = _table_to_markdown_from_pandas(path, source_type)
            transformer = "pandas"

        if not markdown or not markdown.strip():
            raise DocumentTransformError(
                "EMPTY_MARKDOWN",
                "Document conversion produced no readable Markdown.",
                {"transformer": transformer},
            )

        diag = {
            "filename": filename,
            "markdown_chars": len(markdown),
            "transformer": transformer,
        }
        return DocumentMarkdown(
            markdown=markdown,
            source_type=source_type,
            transformer=transformer,
            diagnostics=diag,
        )
    finally:
        for p in {tmp.name, fallback_tmp}:
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
