"""Shared document extraction helpers for IKG scrapers.

Policy:
  1) Try local extraction first (PyMuPDF, then pypdf).
  2) Escalate to Azure DI only when local extraction quality is insufficient.
"""

from __future__ import annotations

import logging
import io
import re
from typing import Any

logger = logging.getLogger("finagent.ikg.scrapers.doc_extract")


def decode_text_bytes(content: bytes) -> str:
    """Decode text-like payloads using UTF-8 with replacement."""
    if not content:
        return ""
    return content.decode("utf-8", errors="replace")


def text_is_sufficient(
    text: str,
    *,
    min_chars: int = 1000,
    min_alpha_ratio: float = 0.2,
) -> bool:
    """Check whether extracted text quality is good enough to skip DI."""
    cleaned = (text or "").strip()
    if len(cleaned) < max(1, int(min_chars)):
        return False
    alpha = len(re.findall(r"[A-Za-z]", cleaned))
    ratio = float(alpha) / float(max(len(cleaned), 1))
    return ratio >= float(min_alpha_ratio)


def extract_pdf_text_local(file_bytes: bytes) -> dict[str, Any]:
    """Extract PDF text locally using PyMuPDF, then pypdf as fallback."""
    if not file_bytes:
        return {"full_text": "", "page_count": 0, "model": None, "error": "empty document bytes"}

    try:
        import fitz  # type: ignore

        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            pages = [page.get_text("text") or "" for page in doc]
            text = "\n".join(pages).strip()
            return {
                "full_text": text,
                "page_count": int(doc.page_count),
                "model": "pymupdf_local",
                "error": None,
            }
    except Exception as exc:
        logger.debug("PyMuPDF local extraction failed: %s", exc)

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        return {
            "full_text": text,
            "page_count": len(reader.pages),
            "model": "pypdf_local",
            "error": None,
        }
    except Exception as exc:
        logger.debug("pypdf local extraction failed: %s", exc)
        return {
            "full_text": "",
            "page_count": 0,
            "model": None,
            "error": str(exc),
        }
