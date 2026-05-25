"""Document classifier for CAS/eCAS PDF uploads.

Determines whether an uploaded PDF is a valid CAS statement or something else
(bank statement, payslip, invoice, etc.). Uses byte-level checks, encryption
detection, text extraction, and signature-based classification.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any

logger = logging.getLogger("finagent.ingestion.classifier")

# Known CAS/eCAS vendor signatures
_VENDOR_SIGNATURES: list[tuple[str, str]] = [
    ("computer age management services", "CAMS"),
    ("cams", "CAMS"),
    ("kfintech", "KFINTECH"),
    ("karvy", "KFINTECH"),
    ("nsdl", "NSDL_ECAS"),
    ("national securities depository", "NSDL_ECAS"),
    ("cdsl", "CDSL_ECAS"),
    ("central depository services", "CDSL_ECAS"),
    (" consolidated account statement", "CAS"),
    ("cas for mutual funds", "CAS"),
]

# ISIN regex pattern (Indian INE/INF + 9 alphanumeric + 2 check digits)
_ISIN_RE = re.compile(r"IN[A-Z0-9]{10}")


def classify_pdf(pdf_bytes: bytes, password: str) -> dict[str, Any]:
    """Classify a PDF and return a decision envelope.

    Returns:
        {
            "is_cas": bool,
            "vendor": str | None,  # CAMS, KFINTECH, NSDL_ECAS, CDSL_ECAS, UNKNOWN
            "isin_count": int,
            "text_sample": str,  # first 2000 chars of extracted text
            "diagnostics": {
                "byte_size": int,
                "is_encrypted": bool,
                "has_text": bool,
                "vendor_hits": list[str],
            }
        }
    """
    result: dict[str, Any] = {
        "is_cas": False,
        "vendor": None,
        "isin_count": 0,
        "text_sample": "",
        "diagnostics": {
            "byte_size": len(pdf_bytes),
            "is_encrypted": False,
            "has_text": False,
            "vendor_hits": [],
        },
    }

    if not pdf_bytes:
        return result

    # Byte-level: encryption check (common PDF encryption marker)
    # /Encrypt is typically in the trailer near the END of the file, so scan the last 8KB
    trailer_scan = pdf_bytes[max(0, len(pdf_bytes) - 8192):]
    if b"/Encrypt" in trailer_scan:
        result["diagnostics"]["is_encrypted"] = True

    # Try to extract text
    text_sample = ""
    try:
        import pdfplumber as _pdfplumber
        with _pdfplumber.open(io.BytesIO(pdf_bytes), password=password or None) as pdf:
            for page in pdf.pages[:3]:
                txt = page.extract_text() or ""
                text_sample += txt + "\n"
                if len(text_sample) > 4000:
                    break
    except Exception as exc:
        logger.debug("Text extraction failed during classification: %s", exc)
        # If password protected and no password given, mark encrypted
        if "password" in str(exc).lower() or "incorrect" in str(exc).lower():
            result["diagnostics"]["is_encrypted"] = True

    result["text_sample"] = text_sample[:2000]
    result["diagnostics"]["has_text"] = bool(text_sample.strip())

    # Count ISINs
    isins = set(_ISIN_RE.findall(text_sample.upper()))
    result["isin_count"] = len(isins)

    # Vendor signature detection
    lower_text = text_sample.lower()
    vendor_hits: list[str] = []
    detected_vendor: str | None = None
    for signature, vendor in _VENDOR_SIGNATURES:
        if signature in lower_text:
            vendor_hits.append(f"{vendor}:{signature}")
            detected_vendor = vendor
    result["diagnostics"]["vendor_hits"] = vendor_hits
    result["vendor"] = detected_vendor

    # Decision rules
    # A document is CAS if:
    # 1. Vendor signature detected, OR
    # 2. >= 3 ISIN codes found in text
    if detected_vendor or len(isins) >= 3:
        result["is_cas"] = True

    return result
