#!/usr/bin/env python
"""Test the document extraction pipeline end-to-end."""
import logging
import os
import asyncio

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

import fitz

# Create a multi-page PDF with realistic text
doc = fitz.open()
for i in range(5):
    page = doc.new_page()
    page.insert_text(
        (50, 50),
        "Page %d of test document. This is a sample corporate filing document "
        "with sufficient text content for extraction quality checks. The company "
        "reported strong Q3 results with revenue growth of 15 percent year over "
        "year. Operating margins expanded by 200 basis points driven by operational "
        "efficiencies. Management guided for continued momentum in the coming "
        "quarters with healthy order book and robust pipeline visibility across "
        "key verticals and geographies." % (i + 1),
    )
pdf_bytes = doc.tobytes()
doc.close()
print("Test PDF: %d bytes, 5 pages" % len(pdf_bytes))

# 1) Test _doc_extract.py (used by concall_transcripts)
from finagent.ikg.scrapers._doc_extract import extract_pdf_text_local, text_is_sufficient

result = extract_pdf_text_local(pdf_bytes)
model = result.get("model")
pc = result.get("page_count")
tl = len(result.get("full_text") or "")
err = result.get("error")
suf = text_is_sufficient(result.get("full_text") or "")
print("\n=== _doc_extract.extract_pdf_text_local ===")
print("  model:      %s" % model)
print("  page_count: %s" % pc)
print("  text_len:   %d" % tl)
print("  error:      %s" % err)
print("  sufficient: %s" % suf)

# 2) Test azure_doc_intel.py pipeline
print("\n=== azure_doc_intel pipeline ===")
print("  FINAGENT_DI_PROVIDER: %s" % os.getenv("FINAGENT_DI_PROVIDER", "NOT SET"))

from finagent.ingestion.azure_doc_intel import (
    _di_provider_mode,
    _local_result_is_good,
    _pymupdf_extract,
    _pypdf_fallback,
    is_azure_di_configured,
    extract_document,
)

mode = _di_provider_mode()
print("  Resolved mode: %s" % mode)
print("  Azure DI configured: %s" % is_azure_di_configured())

local_res = _pymupdf_extract(pdf_bytes)
print("\n  _pymupdf_extract:")
print("    model:   %s" % local_res.model_used)
print("    pages:   %d" % local_res.page_count)
print("    text:    %d chars" % len(local_res.full_text or ""))
print("    tables:  %d" % len(local_res.tables))

min_cpp = int(os.getenv("FINAGENT_DI_LOCAL_MIN_CHARS_PER_PAGE", "250"))
min_tc = int(os.getenv("FINAGENT_DI_LOCAL_MIN_TOTAL_CHARS", "400"))
good = _local_result_is_good(local_res, require_tables=False)
print("    min_chars_per_page: %d" % min_cpp)
print("    min_total_chars:    %d" % min_tc)
print("    actual chars/page:  %.0f" % (len(local_res.full_text or "") / max(local_res.page_count, 1)))
print("    is_good:            %s" % good)

# 3) Full end-to-end: call extract_document (should use PyMuPDF, NOT Azure DI)
print("\n=== Full extract_document (should use local, NOT Azure DI) ===")
full_result = asyncio.run(extract_document(file_bytes=pdf_bytes, allow_fallback=True))
print("  model_used:    %s" % full_result.model_used)
print("  page_count:    %d" % full_result.page_count)
print("  text_len:      %d" % len(full_result.full_text or ""))
print("  tables:        %d" % len(full_result.tables))
print("  fallback_used: %s" % full_result.fallback_used)

if "azure" in (full_result.model_used or "").lower():
    print("\n  *** PROBLEM: Azure DI was used instead of PyMuPDF! ***")
else:
    print("\n  OK: Local extraction used (no Azure DI cost)")

# 4) Test with a scanned/image PDF (low text) — should escalate to Azure DI
doc2 = fitz.open()
page = doc2.new_page()
page.insert_text((50, 50), "X")  # minimal text
scan_bytes = doc2.tobytes()
doc2.close()
print("\n=== Scanned/low-text PDF (should escalate to Azure DI) ===")
scan_result = asyncio.run(extract_document(file_bytes=scan_bytes, allow_fallback=True))
print("  model_used:    %s" % scan_result.model_used)
print("  text_len:      %d" % len(scan_result.full_text or ""))
print("  fallback_used: %s" % scan_result.fallback_used)
if "azure" in (scan_result.model_used or "").lower():
    print("  OK: Azure DI correctly used for low-quality local extraction")
else:
    print("  Local result returned (Azure DI not needed or not available)")
