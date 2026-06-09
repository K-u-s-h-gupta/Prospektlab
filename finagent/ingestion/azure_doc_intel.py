"""Document extraction — local-first with Azure DI as last resort.

Extraction priority:
  1. PyMuPDF (fitz)  — fast, free, good for digitally readable PDFs
  2. pypdf           — fallback when PyMuPDF quality is insufficient
  3. Azure DI        — only when local extraction is not good enough (costly)

Configuration:
  FINAGENT_DI_PROVIDER = "local_first" (default) | "azure_first" | "azure_only" | "local_only"
  AZURE_DI_ENDPOINT    = "https://your-resource.cognitiveservices.azure.com/"
  AZURE_DI_KEY         = your API key
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finagent.env import load_finagent_env

load_finagent_env()

logger = logging.getLogger("finagent.ingestion.azure_doc_intel")

_DI_ENDPOINT = os.getenv("AZURE_DI_ENDPOINT", "")
_DI_KEY = os.getenv("AZURE_DI_KEY", "")


def _parse_page_selector(pages: str | list[int] | list[str] | None) -> set[int] | None:
    if not pages:
        return None
    raw = pages if isinstance(pages, str) else ",".join(str(page) for page in pages)
    selected: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            try:
                start, end = int(start_s), int(end_s)
            except ValueError:
                continue
            selected.update(range(min(start, end), max(start, end) + 1))
            continue
        try:
            selected.add(int(part))
        except ValueError:
            continue
    return selected or None


@dataclass
class ExtractedTable:
    """A table extracted from a document."""
    page_number: int
    rows: list[list[str]]  # list of rows, each row is list of cell strings
    header_row: list[str] = field(default_factory=list)
    confidence: float = 0.0
    page_numbers: list[int] = field(default_factory=list)

    @property
    def markdown(self) -> str:
        """Render table as Markdown."""
        if not self.rows:
            return ""
        headers = self.header_row or self.rows[0]
        data_rows = self.rows[1:] if not self.header_row else self.rows
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in data_rows:
            # Pad short rows
            padded = row + [""] * (len(headers) - len(row))
            lines.append("| " + " | ".join(padded[:len(headers)]) + " |")
        return "\n".join(lines)


@dataclass
class ExtractedKeyValuePair:
    """A key-value pair extracted from a document."""
    key: str
    value: str
    confidence: float = 0.0
    page_number: int = 0


@dataclass
class ExtractedPage:
    """Page-level text extracted from a document."""
    page_number: int
    text: str = ""


@dataclass
class DocumentIntelligenceResult:
    """Result of Azure Document Intelligence extraction."""
    full_text: str = ""
    pages: list[ExtractedPage] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    key_value_pairs: list[ExtractedKeyValuePair] = field(default_factory=list)
    page_count: int = 0
    model_used: str = "prebuilt-layout"
    confidence: float = 0.0
    duration_s: float = 0.0
    fallback_used: bool = False  # True if fell back to PyMuPDF

    @property
    def tables_markdown(self) -> str:
        return "\n\n".join(t.markdown for t in self.tables if t.rows)


def is_azure_di_configured() -> bool:
    """Check if Azure Document Intelligence credentials are configured."""
    return bool(_DI_ENDPOINT and _DI_KEY)


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _di_provider_mode() -> str:
    mode = os.getenv("FINAGENT_DI_PROVIDER", "local_first").strip().lower()
    if mode in {"azure", "azure_only", "strict_azure"}:
        return "azure_only"
    if mode in {"local", "local_only", "free"}:
        return "local_only"
    if mode in {"azure_first"}:
        return "azure_first"
    return "local_first"


def _selected_page_count(pages: str | list[int] | list[str] | None, result_page_count: int | None = None) -> int:
    selected = _parse_page_selector(pages)
    if selected:
        return len(selected)
    return int(result_page_count or 0)


def _local_result_is_good(
    result: DocumentIntelligenceResult,
    *,
    require_tables: bool,
) -> bool:
    if _truthy_env("FINAGENT_DI_TRUST_LOCAL_TEXT", False) and result.page_count > 0 and result.full_text.strip():
        return True
    if result.page_count <= 0:
        return False
    min_chars_per_page = int(os.getenv("FINAGENT_DI_LOCAL_MIN_CHARS_PER_PAGE", "250") or "250")
    min_total_chars = int(os.getenv("FINAGENT_DI_LOCAL_MIN_TOTAL_CHARS", "400") or "400")
    text_len = len(result.full_text or "")
    if text_len < min_total_chars:
        return False
    if text_len / max(result.page_count, 1) < min_chars_per_page:
        return False
    if require_tables and not result.tables:
        return False
    return True


def _log_azure_di_usage(
    *,
    model_id: str,
    pages: str | list[int] | list[str] | None,
    result: DocumentIntelligenceResult | None = None,
    error: str | None = None,
) -> None:
    try:
        log_dir = Path(os.getenv("FINAGENT_PIPELINE_LOG_DIR", "pipeline_logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        usage_file = log_dir / f"azure_di_usage_{time.strftime('%Y%m%d')}.jsonl"
        page_count = _selected_page_count(pages, result.page_count if result else None)
        usage = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_id": model_id,
            "pages_requested": pages or "",
            "pages_billed_estimate": page_count,
            "tables_count": len(result.tables) if result else 0,
            "text_length": len(result.full_text or "") if result else 0,
            "success": error is None,
            "error": error,
        }
        with usage_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(usage, default=str) + "\n")
    except Exception as exc:
        logger.debug("Failed to write Azure DI usage log: %s", exc)


async def extract_document(
    file_path: str | Path | None = None,
    file_bytes: bytes | None = None,
    *,
    model_id: str = "prebuilt-layout",
    timeout_s: float = 120.0,
    allow_fallback: bool = True,
    pages: str | list[int] | list[str] | None = None,
    require_tables: bool = False,
) -> DocumentIntelligenceResult:
    """Extract text, tables, and key-value pairs from a document.

    Uses Azure Document Intelligence as primary, PyMuPDF as fallback.

    Args:
        file_path: Path to the PDF/image file.
        file_bytes: Raw file bytes (alternative to file_path).
        model_id: Azure DI model to use. Options:
            - "prebuilt-layout" — general layout extraction (default)
            - "prebuilt-document" — key-value pairs + tables
            - "prebuilt-invoice" — invoice-specific extraction
        timeout_s: Maximum time to wait for Azure DI response.
        pages: Optional comma-delimited page/range selector, e.g. "3-6,10".

    Returns:
        DocumentIntelligenceResult with full text, tables, and KV pairs.
    """
    start_t = time.time()

    # Get file bytes
    if file_bytes is None and file_path:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")
        file_bytes = file_path.read_bytes()

    if not file_bytes:
        raise ValueError("Either file_path or file_bytes must be provided")

    provider_mode = _di_provider_mode()

    local_result: DocumentIntelligenceResult | None = None
    if provider_mode in {"local_first", "local_only"}:
        # Step 1: Try PyMuPDF (fastest, best quality for digital PDFs)
        local_result = _pymupdf_extract(file_bytes, pages=pages)
        local_result.model_used = "pymupdf_local"
        local_result.fallback_used = False
        local_result.duration_s = round(time.time() - start_t, 2)
        if _local_result_is_good(local_result, require_tables=require_tables):
            logger.info(
                "[DOC-LOCAL] PyMuPDF extracted %d pages, %d tables, %d chars in %.1fs",
                local_result.page_count,
                len(local_result.tables),
                len(local_result.full_text or ""),
                local_result.duration_s,
            )
            return local_result

        # Step 2: PyMuPDF quality insufficient — try pypdf before Azure DI
        logger.info(
            "[DOC-LOCAL] PyMuPDF quality insufficient (pages=%d chars=%d), trying pypdf...",
            local_result.page_count,
            len(local_result.full_text or ""),
        )
        pypdf_result = _pypdf_fallback(file_bytes, pages=pages)
        pypdf_result.duration_s = round(time.time() - start_t, 2)
        if _local_result_is_good(pypdf_result, require_tables=require_tables):
            logger.info(
                "[DOC-LOCAL] pypdf extracted %d pages, %d chars in %.1fs",
                pypdf_result.page_count,
                len(pypdf_result.full_text or ""),
                pypdf_result.duration_s,
            )
            return pypdf_result

        # Keep the better local result for potential Azure DI fallback
        if len(pypdf_result.full_text or "") > len(local_result.full_text or ""):
            local_result = pypdf_result

        if provider_mode == "local_only":
            logger.warning(
                "[DOC-LOCAL] Returning best local extraction in local_only mode: pages=%d chars=%d tables=%d model=%s",
                local_result.page_count,
                len(local_result.full_text or ""),
                len(local_result.tables),
                local_result.model_used,
            )
            return local_result

        logger.info(
            "[DOC-LOCAL] Both PyMuPDF and pypdf insufficient, escalating to Azure DI"
        )

    # Try Azure DI when local extraction is not good enough or Azure is preferred.
    if provider_mode != "local_only" and is_azure_di_configured():
        try:
            result = await _azure_di_extract(file_bytes, model_id=model_id, timeout_s=timeout_s, pages=pages)
            result.duration_s = round(time.time() - start_t, 2)
            _log_azure_di_usage(model_id=model_id, pages=pages, result=result)
            logger.info(
                "[AZURE-DI] Extracted %d pages, %d tables, %d KV pairs in %.1fs",
                result.page_count, len(result.tables), len(result.key_value_pairs), result.duration_s,
            )
            return result
        except Exception as exc:
            _log_azure_di_usage(model_id=model_id, pages=pages, error=str(exc))
            if not allow_fallback:
                if local_result is not None and _truthy_env("FINAGENT_DI_STRICT_ALLOW_LOCAL_ON_AZURE_FAILURE", True):
                    logger.warning("[AZURE-DI] Strict Azure failed; using prior local extraction due cost guard: %s", exc)
                    return local_result
                raise RuntimeError(f"Azure DI extraction failed in strict mode: {exc}") from exc
            logger.warning("[AZURE-DI] Extraction failed, using best local result: %s", exc)
    elif not allow_fallback:
        if local_result is not None and _truthy_env("FINAGENT_DI_STRICT_ALLOW_LOCAL_ON_AZURE_FAILURE", True):
            return local_result
        raise RuntimeError("Azure DI is not configured and strict mode disallows fallback")

    # Final fallback: return best local result (already tried PyMuPDF + pypdf)
    result = local_result or _pymupdf_extract(file_bytes, pages=pages)
    result.duration_s = round(time.time() - start_t, 2)
    return result


async def _azure_di_extract(
    file_bytes: bytes,
    model_id: str = "prebuilt-layout",
    timeout_s: float = 120.0,
    pages: str | list[int] | list[str] | None = None,
) -> DocumentIntelligenceResult:
    """Extract using Azure Document Intelligence API."""
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:
        raise RuntimeError(
            "azure-ai-documentintelligence required. "
            "Install: pip install azure-ai-documentintelligence"
        ) from exc

    import asyncio

    credential = AzureKeyCredential(_DI_KEY)
    client = DocumentIntelligenceClient(endpoint=_DI_ENDPOINT, credential=credential)

    # Run sync client in thread pool
    def _analyze():
        kwargs: dict[str, Any] = {}
        if pages:
            if isinstance(pages, str):
                kwargs["pages"] = pages
            else:
                kwargs["pages"] = ",".join(str(page) for page in pages)
        poller = client.begin_analyze_document(
            model_id,
            body=file_bytes,
            content_type="application/pdf",
            **kwargs,
        )
        return poller.result()

    analyze_result = await asyncio.wait_for(
        asyncio.to_thread(_analyze),
        timeout=timeout_s,
    )

    result = DocumentIntelligenceResult(model_used=model_id)

    # Extract full text
    result.full_text = analyze_result.content or ""
    result.page_count = len(analyze_result.pages) if analyze_result.pages else 0
    if analyze_result.pages:
        for page in analyze_result.pages:
            lines = getattr(page, "lines", None) or []
            text = "\n".join((getattr(line, "content", "") or "").strip() for line in lines if getattr(line, "content", ""))
            result.pages.append(ExtractedPage(page_number=int(getattr(page, "page_number", 0) or 0), text=text))

    # Extract tables
    if analyze_result.tables:
        for table in analyze_result.tables:
            rows: list[list[str]] = []
            if table.cells:
                max_row = max(c.row_index for c in table.cells) + 1
                max_col = max(c.column_index for c in table.cells) + 1
                grid = [[""] * max_col for _ in range(max_row)]
                for cell in table.cells:
                    grid[cell.row_index][cell.column_index] = (cell.content or "").strip()
                rows = grid

            table_pages = [
                int(region.page_number)
                for region in (table.bounding_regions or [])
                if getattr(region, "page_number", None)
            ]
            result.tables.append(ExtractedTable(
                page_number=table_pages[0] if table_pages else 0,
                rows=rows,
                header_row=rows[0] if rows else [],
                confidence=getattr(table, "confidence", 0.0) or 0.8,
                page_numbers=table_pages,
            ))

    # Extract key-value pairs
    if analyze_result.key_value_pairs:
        for kvp in analyze_result.key_value_pairs:
            key = kvp.key.content if kvp.key else ""
            value = kvp.value.content if kvp.value else ""
            if key.strip():
                result.key_value_pairs.append(ExtractedKeyValuePair(
                    key=key.strip(),
                    value=value.strip(),
                    confidence=kvp.confidence or 0.0,
                ))

    if analyze_result.pages:
        confidences = [p.confidence for p in analyze_result.pages if hasattr(p, "confidence") and p.confidence]
        result.confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return result


def _pymupdf_extract(
    file_bytes: bytes,
    pages: str | list[int] | list[str] | None = None,
) -> DocumentIntelligenceResult:
    """Primary extraction using PyMuPDF (fitz). Returns empty result on failure."""
    result = DocumentIntelligenceResult(
        model_used="pymupdf_local",
        fallback_used=False,
    )

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        full_text_parts = []
        selected_pages = _parse_page_selector(pages)
        processed_pages = 0
        for page_num, page in enumerate(doc, 1):
            if selected_pages and page_num not in selected_pages:
                continue
            processed_pages += 1
            text = page.get_text("text")
            result.pages.append(ExtractedPage(page_number=page_num, text=text or ""))
            if text.strip():
                full_text_parts.append(f"--- Page {page_num} ---\n{text}")

            try:
                tabs = page.find_tables()
                if tabs and tabs.tables:
                    for tab in tabs.tables:
                        rows = [list(row) for row in tab.extract()]
                        if rows:
                            result.tables.append(ExtractedTable(
                                page_number=page_num,
                                rows=rows,
                                header_row=rows[0] if rows else [],
                                confidence=0.5,
                                page_numbers=[page_num],
                            ))
            except Exception:
                pass

        result.page_count = processed_pages
        result.full_text = "\n\n".join(full_text_parts)
        result.confidence = 0.5
        doc.close()

    except ImportError:
        logger.info("PyMuPDF not installed, returning empty result")
    except Exception as exc:
        logger.warning("PyMuPDF extraction failed: %s", exc)

    return result


def _pypdf_fallback(
    file_bytes: bytes,
    pages: str | list[int] | list[str] | None = None,
) -> DocumentIntelligenceResult:
    """Free local text extraction using pypdf for digitally readable PDFs."""
    result = DocumentIntelligenceResult(
        model_used="pypdf_local",
        fallback_used=True,
    )
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        selected_pages = _parse_page_selector(pages)
        full_text_parts: list[str] = []
        processed_pages = 0
        for idx, page in enumerate(reader.pages, start=1):
            if selected_pages and idx not in selected_pages:
                continue
            processed_pages += 1
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            result.pages.append(ExtractedPage(page_number=idx, text=text))
            if text.strip():
                full_text_parts.append(f"--- Page {idx} ---\n{text}")
        result.page_count = processed_pages
        result.full_text = "\n\n".join(full_text_parts)
        result.confidence = 0.45
    except Exception as exc:
        logger.error("pypdf fallback failed: %s", exc)
    return result


async def extract_annual_report(
    file_path: str | Path,
    *,
    extract_financial_tables: bool = True,
    allow_fallback: bool = False,
    pages: str | list[int] | list[str] | None = None,
) -> DocumentIntelligenceResult:
    """Specialized extraction for Indian annual reports.

    Uses "prebuilt-document" model for better key-value pair extraction
    from structured annual report sections.

    Args:
        file_path: Path to the annual report PDF.
        extract_financial_tables: If True, uses prebuilt-document for richer extraction.

    Returns:
        DocumentIntelligenceResult with tables and KV pairs.
    """
    model = "prebuilt-layout" if extract_financial_tables else "prebuilt-layout"
    return await extract_document(
        file_path=file_path,
        model_id=model,
        allow_fallback=allow_fallback,
        pages=pages,
        require_tables=extract_financial_tables,
    )
