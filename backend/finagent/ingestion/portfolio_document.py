from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from finagent.ingestion.cas_adapter import cas_adapter
from finagent.ingestion.pdf_transformer import DocumentTransformError, document_to_markdown
from finagent.ingestion.markdown_extractor import extract_positions_from_markdown
from finagent.ingestion.portfolio_schema import PortfolioExtractionSchema

logger = logging.getLogger("finagent.ingestion.portfolio_document")


async def parse_portfolio_document(data: bytes, filename: str, password: str = "") -> PortfolioExtractionSchema:
    """Convert an uploaded portfolio document to PortfolioExtractionSchema.

    For PDFs:
    1. Try casparser v0.9.0 (CAS/eCAS from CAMS/KFintech/CDSL/NSDL)
    2. Fall back to document_to_markdown (PyMuPDF fitz for broker PDFs)

    For CSV/XLSX:
    - Use document_to_markdown with pandas fallback

    Args:
        data: File bytes
        filename: Original filename
        password: PDF password if encrypted

    Returns:
        PortfolioExtractionSchema with positions and metadata
    """
    source_ext = Path(filename).suffix.lower()

    # Try casparser first for CAS PDFs
    if source_ext == ".pdf":
        logger.info("Attempting casparser (CAS/eCAS) parsing for %s", filename)
        # casparser.read_cas_pdf is a synchronous, CPU/IO-heavy call. Run it in a
        # worker thread so it never blocks the event loop (which would stall every
        # other in-flight request — quotes, analytics, news — and surface as
        # client-side timeouts during an upload).
        extraction = await asyncio.to_thread(cas_adapter, data, password)
        extraction.diagnostics["filename"] = filename

        # If casparser succeeded, return it
        if extraction.status != "INGESTION_FAILED":
            logger.info("casparser succeeded; returning CAS extraction")
            return extraction

        logger.info("casparser failed (status=%s); falling back to markdown extraction", extraction.status)

    # Fallback to markdown extraction (fitz + markdown_extractor)
    try:
        transformed = await document_to_markdown(data, filename, password=password)
    except DocumentTransformError as exc:
        return PortfolioExtractionSchema(
            status="INGESTION_FAILED",
            source_type="unknown",
            positions=[],
            warnings=[exc.message],
            confidence=0.0,
            diagnostics={"code": exc.code, "filename": filename, **exc.diagnostics},
        )
    except Exception as exc:
        logger.exception("Unexpected document transform failure for %s", filename)
        return PortfolioExtractionSchema(
            status="INGESTION_FAILED",
            source_type="unknown",
            positions=[],
            warnings=["Unexpected document conversion failure."],
            confidence=0.0,
            diagnostics={"code": "UNEXPECTED_TRANSFORM_ERROR", "filename": filename, "error": str(exc)},
        )

    extraction = extract_positions_from_markdown(
        transformed.markdown,
        source_type=transformed.source_type,
        broker_or_vendor="",
        diagnostics=transformed.diagnostics,
    )
    extraction.diagnostics["transformer"] = transformed.transformer
    extraction.diagnostics["filename"] = filename
    return extraction


def extraction_to_position_dicts(extraction: PortfolioExtractionSchema) -> list[dict[str, Any]]:
    return [pos.model_dump() | {"active": True} for pos in extraction.positions]


def extraction_to_transaction_dicts(extraction: PortfolioExtractionSchema) -> list[dict[str, Any]]:
    return [txn.model_dump() for txn in extraction.transactions]

