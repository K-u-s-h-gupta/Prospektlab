"""Test PyMuPDF on real BSE PDFs with correct URL construction."""
import httpx
import fitz
import os
import re
import logging
logging.basicConfig(level=logging.WARNING)

MIN_CHARS_PER_PAGE = int(os.getenv("FINAGENT_DI_LOCAL_MIN_CHARS_PER_PAGE", "250"))
MIN_TOTAL_CHARS = int(os.getenv("FINAGENT_DI_LOCAL_MIN_TOTAL_CHARS", "400"))

BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Referer": "https://www.bseindia.com/",
}

BSE_ATTACH_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"

def normalize_bse_url(raw):
    url = (raw or "").strip().replace("\\", "/")
    if not url:
        return ""
    if url.lower().startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.bseindia.com" + url
    return BSE_ATTACH_BASE + url

print("=== Thresholds: %d chars/page, %d total ===" % (MIN_CHARS_PER_PAGE, MIN_TOTAL_CHARS))

# Get live BSE filing URLs for Infosys + Reliance + TCS
test_urls = []
for scrip in ["500209", "500325", "532540"]:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        params = {
            "pageno": "1", "strCat": "-1", "strPrevDate": "20250101",
            "strScrip": scrip, "strSearch": "P", "strToDate": "20260607",
            "strType": "C", "subcategory": "-1",
        }
        resp = client.get(
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
            headers=BSE_HEADERS, params=params,
        )
        if resp.status_code == 200:
            payload = resp.json()
            rows = payload.get("Table", []) if isinstance(payload, dict) else []
            for row in rows[:15]:
                att = (row.get("ATTACHMENTNAME") or "").strip()
                if att and ".pdf" in att.lower():
                    url = normalize_bse_url(att)
                    sub = (row.get("NEWSSUB") or "")[:60]
                    test_urls.append((url, sub))
                    if len(test_urls) >= 15:
                        break
        if len(test_urls) >= 15:
            break

print("Testing %d real BSE PDFs (correct URLs)\n" % len(test_urls))

local_count = 0
azure_count = 0
error_count = 0

for i, (url, subject) in enumerate(test_urls, 1):
    short = url.split("/")[-1][:40]
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url, headers=BSE_HEADERS)
            if resp.status_code != 200:
                print("[%02d] SKIP  HTTP %d  %s" % (i, resp.status_code, short))
                continue
            pdf_bytes = resp.content
            if len(pdf_bytes) < 500:
                print("[%02d] SKIP  too small %d bytes  %s" % (i, len(pdf_bytes), short))
                continue
    except Exception as e:
        print("[%02d] SKIP  download error  %s" % (i, short))
        continue

    # Check if it's actually a PDF
    is_pdf = pdf_bytes[:5] == b"%PDF-"
    if not is_pdf:
        print("[%02d] SKIP  not a PDF (%s)  %s" % (i, pdf_bytes[:20], short))
        continue

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_text = ""
        for pg in doc:
            total_text += pg.get_text("text") or ""
        pages = doc.page_count
        chars = len(total_text.strip())
        cpp = chars / max(pages, 1)
        doc.close()

        pass_total = chars >= MIN_TOTAL_CHARS
        pass_cpp = cpp >= MIN_CHARS_PER_PAGE
        if pass_total and pass_cpp:
            local_count += 1
            print("[%02d] LOCAL  %dpg %5dch %3dch/pg  %s" % (i, pages, chars, int(cpp), subject[:50]))
        else:
            azure_count += 1
            print("[%02d] AZURE  %dpg %5dch %3dch/pg  %s" % (i, pages, chars, int(cpp), subject[:50]))
    except Exception as e:
        error_count += 1
        print("[%02d] ERROR  %s  %s" % (i, str(e)[:50], short))

print("\n=== SUMMARY ===")
print("  Would use PyMuPDF (local): %d" % local_count)
print("  Would use Azure DI:        %d" % azure_count)
print("  Errors:                     %d" % error_count)
total = local_count + azure_count
if total > 0:
    pct = 100.0 * local_count / total
    print("  Local extraction rate:      %.0f%%" % pct)
    if pct > 50:
        print("  >> PyMuPDF handles majority of PDFs successfully!")
    elif pct > 0:
        print("  >> Mix of digital and scanned PDFs")
    else:
        print("  >> All scanned/image PDFs - Azure DI needed")
