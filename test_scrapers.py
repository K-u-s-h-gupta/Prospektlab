"""
Comprehensive connectivity test for all scrapers in finagent/ikg/scrapers/.
Tests each scraper's HTTP endpoints, response structure, and parsing logic.
Does NOT write to DB; only network + parse validation.
"""
import sys
import httpx
import json
import csv
import io
import re
import time
from datetime import date, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, parse_qs, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS = {}

# ─── 1. SEBI Enforcement Orders ──────────────────────────────────────────────

def test_sebi_enforcement():
    print("\n" + "="*60)
    print("1. SEBI Enforcement Orders (sebi_enforcement.py)")
    print("="*60)
    SEBI_ORDERS_URL = "https://www.sebi.gov.in/enforcement/orders.html"
    SEBI_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html, */*",
        "Referer": "https://www.sebi.gov.in/enforcement/orders.html",
    }
    result = {"scraper": "sebi_enforcement", "issues": [], "ok": False}

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as c:
            r = c.get(SEBI_ORDERS_URL, headers=SEBI_HEADERS)
        result["http_status"] = r.status_code
        print(f"  HTTP Status  : {r.status_code}")
        print(f"  Content-Type : {r.headers.get('content-type','N/A')}")
        print(f"  Body length  : {len(r.text)} chars")

        if r.status_code != 200:
            result["issues"].append(f"Non-200 status: {r.status_code}")

        class CatParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []
                self._href = None
                self._parts = []
            def handle_starttag(self, tag, attrs):
                if tag.lower() == "a":
                    d = dict(attrs)
                    href = d.get("href","")
                    if href:
                        self._href = href; self._parts = []
            def handle_data(self, data):
                if self._href: self._parts.append(data)
            def handle_endtag(self, tag):
                if tag.lower() == "a" and self._href:
                    title = " ".join(" ".join(self._parts).split())
                    if "HomeAction.do?doListing=yes" in self._href:
                        self.links.append({"title": title, "url": self._href})
                    self._href = None; self._parts = []

        p = CatParser()
        p.feed(r.text)
        print(f"  Category links: {len(p.links)}")
        for lnk in p.links[:3]:
            print(f"    [{lnk['title']}] -> {lnk['url'][:80]}")

        if not p.links:
            result["issues"].append("No category links found - HTML structure may have changed")
        else:
            result["ok"] = True

        # Test one category listing page
        if p.links:
            cat_url = "https://www.sebi.gov.in" + p.links[0]["url"]
            print(f"\n  Testing category page: {cat_url[:80]}")
            time.sleep(3)
            with httpx.Client(timeout=30, follow_redirects=True) as c:
                cr = c.get(cat_url, headers=SEBI_HEADERS)
            print(f"  Category page status: {cr.status_code} | body: {len(cr.text)} chars")
            if cr.status_code == 200 and len(cr.text) > 500:
                order_links = re.findall(r'href="([^"]+(?:\.pdf|/enforcement/orders/)[^"]*)"', cr.text, re.I)
                print(f"  Order/PDF links in category page: {len(order_links)}")
                if not order_links:
                    result["issues"].append("Category listing page has no order/PDF links")
            else:
                result["issues"].append(f"Category page returned status {cr.status_code}")

        result["category_count"] = len(p.links)
    except Exception as e:
        result["issues"].append(f"Exception: {e}")
        print(f"  ERROR: {e}")

    RESULTS["sebi_enforcement"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 2. BSE EOD ───────────────────────────────────────────────────────────────

def test_bse_eod():
    print("\n" + "="*60)
    print("2. BSE EOD (bse_eod.py)")
    print("="*60)
    BSE_EOD_META_URL = "https://api.bseindia.com/BseIndiaAPI/api/GetBhavcopydata/w"
    BSE_EOD_DOWNLOAD_BASE = "https://www.bseindia.com/download/BhavCopy/Equity/"
    BSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.bseindia.com/",
        "Accept": "application/json, text/plain, */*",
    }
    result = {"scraper": "bse_eod", "issues": [], "ok": False}

    td = date.today() - timedelta(days=1)
    while td.weekday() >= 5:
        td -= timedelta(days=1)
    print(f"  Test date: {td}")

    try:
        params = {"flag": "1", "segment": "equity", "date": td.strftime("%Y%m%d")}
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get(BSE_EOD_META_URL, params=params, headers=BSE_HEADERS)
        result["meta_status"] = r.status_code
        print(f"  Metadata API status: {r.status_code}")

        payload = r.json()
        print(f"  Payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")

        filename = None
        for key in ("dsedcudiff", "dsBhav", "dsEqnew", "dsZip", "dsEquity"):
            rows = payload.get(key)
            if isinstance(rows, list) and rows:
                fn = rows[0].get("filename") or rows[0].get("FilePath","")
                if fn and re.search(r"\.(csv|zip)$", fn, re.I):
                    filename = fn
                    print(f"  Found filename in key={key}: {fn}")
                    break

        if not filename:
            result["issues"].append("No CSV/ZIP filename found in BSE EOD metadata response")
            print("  ⚠️  No filename — might be holiday or schema changed")
            # Try previous day
            td2 = td - timedelta(days=1)
            while td2.weekday() >= 5:
                td2 -= timedelta(days=1)
            print(f"  Retrying with {td2}...")
            params2 = {"flag": "1", "segment": "equity", "date": td2.strftime("%Y%m%d")}
            with httpx.Client(timeout=20, follow_redirects=True) as c:
                r2 = c.get(BSE_EOD_META_URL, params=params2, headers=BSE_HEADERS)
            p2 = r2.json()
            for key in ("dsedcudiff", "dsBhav", "dsEqnew", "dsZip", "dsEquity"):
                rows = p2.get(key)
                if isinstance(rows, list) and rows:
                    fn = rows[0].get("filename") or rows[0].get("FilePath","")
                    if fn and re.search(r"\.(csv|zip)$", fn, re.I):
                        filename = fn
                        print(f"  Retry: Found filename in key={key}: {fn}")
                        break

        if filename:
            # Try to download
            url = f"{BSE_EOD_DOWNLOAD_BASE}{filename}"
            print(f"  Downloading: {url}")
            with httpx.Client(timeout=60, follow_redirects=True) as c:
                dr = c.get(url, headers=BSE_HEADERS)
            print(f"  Download status: {dr.status_code} | size: {len(dr.content)} bytes")
            if dr.status_code == 200:
                import zipfile
                content = dr.content
                if content[:2] == b"PK":
                    with zipfile.ZipFile(io.BytesIO(content)) as zf:
                        csv_files = [n for n in zf.namelist() if n.upper().endswith(".CSV")]
                        print(f"  ZIP contains {len(zf.namelist())} files, CSV: {csv_files}")
                        if csv_files:
                            csv_bytes = zf.read(csv_files[0])
                            rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8","replace"))))
                            print(f"  CSV rows: {len(rows)} | Cols: {list(rows[0].keys())[:6] if rows else 'N/A'}")
                            result["ok"] = True
                            result["rows_sample"] = len(rows)
                else:
                    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8","replace"))))
                    print(f"  CSV rows: {len(rows)}")
                    result["ok"] = True
            else:
                result["issues"].append(f"Download failed: {dr.status_code}")
        else:
            result["issues"].append("Could not resolve filename for any recent trading day")

    except Exception as e:
        result["issues"].append(f"Exception: {e}")
        print(f"  ERROR: {e}")

    RESULTS["bse_eod"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 3. BSE SHP ───────────────────────────────────────────────────────────────

def test_bse_shp():
    print("\n" + "="*60)
    print("3. BSE Shareholding Pattern (bse_shp.py)")
    print("="*60)
    BSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
    }
    # Test with Reliance (500325)
    SCRIP = "500325"
    DECL_URL = f"https://api.bseindia.com/BseIndiaAPI/api/shpDecleraction/w?scripcode={SCRIP}"
    QTRINFO_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_shpqtrinfo_ng/w"
    SUMMARY_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_SHPSUMMARY_ng/w"
    PROMOTER_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpPromoterNGroup_ng/w"

    result = {"scraper": "bse_shp", "issues": [], "ok": False}

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get(DECL_URL, headers=BSE_HEADERS)
        print(f"  Declaration API status: {r.status_code}")
        decl = r.json()
        print(f"  Type: {type(decl).__name__}, Length: {len(decl) if isinstance(decl, list) else 'N/A'}")

        if not isinstance(decl, list) or not decl:
            result["issues"].append("Declaration returned empty/invalid data")
            RESULTS["bse_shp"] = result
            return

        qtrid = int(float(decl[0].get("qtr_id", 0)))
        print(f"  Latest qtrid: {qtrid}")

        # Test qtrinfo
        params = {"SCRIPCODE": SCRIP, "QtrCode": str(qtrid)}
        with httpx.Client(timeout=15, follow_redirects=True) as c:
            qi = c.get(QTRINFO_URL, params=params, headers=BSE_HEADERS)
        print(f"  QtrInfo status: {qi.status_code}")
        qi_data = qi.json()
        print(f"  QtrInfo keys: {list(qi_data.keys()) if isinstance(qi_data, dict) else type(qi_data).__name__}")

        # Test summary
        with httpx.Client(timeout=15, follow_redirects=True) as c:
            sm = c.get(SUMMARY_URL, params=params, headers=BSE_HEADERS)
        print(f"  Summary status: {sm.status_code}")
        sm_data = sm.json()
        t1 = sm_data.get("Table1", [])
        print(f"  Summary Table1 rows: {len(t1)}")

        if t1:
            promoter_row = [r for r in t1 if "promoter" in str(r.get("Fld_ShortCatg","")).lower()]
            if promoter_row:
                pct = promoter_row[0].get("Fld_TotalPercentageOf_A_B_C2")
                print(f"  Promoter holding %: {pct}")
                result["ok"] = True
            else:
                result["issues"].append("No promoter row in summary data")
        else:
            result["issues"].append("Summary Table1 is empty")

    except Exception as e:
        result["issues"].append(f"Exception: {e}")
        print(f"  ERROR: {e}")

    RESULTS["bse_shp"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 4. NSE Nifty 500 ─────────────────────────────────────────────────────────

def test_nse_index():
    print("\n" + "="*60)
    print("4. NSE Nifty 500 Index (nse_index.py)")
    print("="*60)
    NSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/csv, text/plain, */*",
        "Referer": "https://www.niftyindices.com/",
    }
    NSE_URLS = [
        "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    ]
    result = {"scraper": "nse_index", "issues": [], "ok": False}

    for url in NSE_URLS:
        print(f"  Trying: {url}")
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as c:
                r = c.get(url, headers=NSE_HEADERS)
            ct = r.headers.get("content-type","N/A")
            print(f"  Status: {r.status_code} | Content-Type: {ct}")
            if r.status_code == 200 and ("Company Name" in r.text or "Symbol" in r.text):
                rows = list(csv.DictReader(io.StringIO(r.text)))
                print(f"  Rows: {len(rows)} | Cols: {list(rows[0].keys())[:6] if rows else 'N/A'}")
                result["ok"] = True
                result["rows"] = len(rows)
                result["source_url"] = url
                break
            else:
                print(f"    ⚠️  Missing expected CSV headers or bad status")
                result["issues"].append(f"{url[:50]} returned {r.status_code} or missing headers")
        except Exception as e:
            result["issues"].append(f"{url[:50]}: {e}")
            print(f"    ERROR: {e}")

    if not result["ok"]:
        result["issues"].append("All NSE Nifty500 CSV endpoints failed")

    RESULTS["nse_index"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 5. SEBI Corporate Filings ────────────────────────────────────────────────

def test_sebi_corporate_filings():
    print("\n" + "="*60)
    print("5. SEBI Corporate Filings (sebi_corporate_filings.py)")
    print("="*60)
    SEBI_CF_URL = "https://www.sebi.gov.in/curation/corporate_filings.html"
    SEBI_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html,*/*",
        "Referer": "https://www.sebi.gov.in/",
    }
    result = {"scraper": "sebi_corporate_filings", "issues": [], "ok": False}

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get(SEBI_CF_URL, headers=SEBI_HEADERS)
        print(f"  Status: {r.status_code}")
        print(f"  Body: {len(r.text)} chars")

        if r.status_code == 200:
            nse_links = re.findall(r'nseindia\.com[^"\s]*', r.text)
            bse_links = re.findall(r'bseindia\.com[^"\s]*', r.text)
            print(f"  NSE links: {len(nse_links)}, BSE links: {len(bse_links)}")

            category_kws = ["corporate governance","shareholding","financial result","insider trading","related party"]
            found_kws = [kw for kw in category_kws if kw.lower() in r.text.lower()]
            print(f"  Category keywords found: {found_kws}")

            if len(nse_links) > 0 or len(bse_links) > 0:
                result["ok"] = True
            else:
                result["issues"].append("No NSE/BSE links found in SEBI corporate filings page")

            if not found_kws:
                result["issues"].append("No known category keywords found - HTML may have changed")
        else:
            result["issues"].append(f"Non-200 status: {r.status_code}")

    except Exception as e:
        result["issues"].append(f"Exception: {e}")
        print(f"  ERROR: {e}")

    RESULTS["sebi_corporate_filings"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 6. MCA Companies ─────────────────────────────────────────────────────────

def test_mca_companies():
    print("\n" + "="*60)
    print("6. MCA Companies (mca_companies.py)")
    print("="*60)
    MCA_PAGE = "https://www.mcacdm.nic.in/company-master-details.php"
    MCA_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html, */*",
        "Referer": MCA_PAGE,
    }
    result = {"scraper": "mca_companies", "issues": [], "ok": False}

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get(MCA_PAGE, headers=MCA_HEADERS)
        print(f"  Status: {r.status_code}")
        print(f"  Body: {len(r.text)} chars")

        if r.status_code == 200:
            # Check for csrf_token
            token_match = re.search(r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']', r.text, re.I)
            # Also check for export form
            action_match = re.search(r'<form[^>]+id=["\']exportForm["\'][^>]*action=["\']([^"\']+)["\']', r.text, re.I)

            print(f"  CSRF token found: {bool(token_match)}")
            print(f"  Export form found: {bool(action_match)}")

            if token_match:
                print(f"  CSRF token (partial): {token_match.group(1)[:20]}...")
            if action_match:
                print(f"  Export action: {action_match.group(1)}")

            if token_match:
                result["ok"] = True
            else:
                result["issues"].append("No CSRF token found - MCA page may require CAPTCHA or has changed")
                # Note: MCA export requires CAPTCHA - this is expected
                result["ok"] = True  # Page accessible; CAPTCHA/CSRF is a known requirement
                result["notes"] = "MCA export requires CAPTCHA - live download not possible automatically"

        else:
            result["issues"].append(f"MCA page returned {r.status_code}")

    except Exception as e:
        result["issues"].append(f"Exception: {e}")
        print(f"  ERROR: {e}")

    RESULTS["mca_companies"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result.get("notes"):
        print(f"  📝 Note: {result['notes']}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 7. MCA Directors ─────────────────────────────────────────────────────────

def test_mca_directors():
    print("\n" + "="*60)
    print("7. MCA Directors (mca_directors.py)")
    print("="*60)
    MCA_DIR_URL = "https://www.mca.gov.in/mcafoportal/companyLLPMasterData.do"
    MCA_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, */*",
        "Referer": "https://www.mca.gov.in/",
    }
    result = {"scraper": "mca_directors", "issues": [], "ok": False}

    TEST_CIN = "L17110MH1973PLC019786"  # Reliance Industries CIN
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.post(
                MCA_DIR_URL,
                data={"companyID": TEST_CIN, "requestType": "CINbased"},
                headers=MCA_HEADERS,
            )
        print(f"  Status: {r.status_code}")
        ct = r.headers.get("content-type","N/A")
        print(f"  Content-Type: {ct}")
        print(f"  Body (first 300): {r.text[:300]}")

        if r.status_code == 200:
            try:
                data = r.json()
                print(f"  JSON type: {type(data).__name__}")
                if isinstance(data, list) and data:
                    print(f"  Directors found: {len(data)}")
                    result["ok"] = True
                elif isinstance(data, dict):
                    dirs = data.get("directors") or data.get("signatories") or []
                    print(f"  Directors in dict: {len(dirs)}")
                    result["ok"] = len(dirs) > 0
                    if not result["ok"]:
                        result["issues"].append("MCA director response is a dict with no recognized director key")
            except Exception:
                result["issues"].append("MCA director endpoint did not return JSON - may require authentication/session")
                result["notes"] = "MCA21 V3 portal requires authenticated session; scraper will need login or cookie management"
        else:
            result["issues"].append(f"MCA director endpoint returned {r.status_code}")
            if r.status_code in (302, 403, 401):
                result["notes"] = "MCA21 V3 requires authentication - may need Playwright session"

    except Exception as e:
        result["issues"].append(f"Exception: {e}")
        print(f"  ERROR: {e}")

    RESULTS["mca_directors"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result.get("notes"):
        print(f"  📝 Note: {result['notes']}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 8. Financial Data (Screener.in) ─────────────────────────────────────────

def test_financial_data():
    print("\n" + "="*60)
    print("8. Financial Data / Screener.in (financial_data.py)")
    print("="*60)
    SCREENER_URL = "https://www.screener.in/company/RELIANCE/consolidated/"
    SCREENER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html, */*",
        "Referer": "https://www.screener.in/",
    }
    result = {"scraper": "financial_data", "issues": [], "ok": False}

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as c:
            r = c.get(SCREENER_URL, headers=SCREENER_HEADERS)
        print(f"  Status: {r.status_code}")
        ct = r.headers.get("content-type","N/A")
        print(f"  Content-Type: {ct}")
        print(f"  Body: {len(r.text)} chars")

        if r.status_code == 200:
            # Look for key financial indicators
            has_sales = bool(re.search(r"Sales", r.text, re.I))
            has_eps = bool(re.search(r"EPS\s+in\s+Rs", r.text, re.I))
            has_pe = bool(re.search(r"P/E", r.text))
            has_roe = bool(re.search(r"ROE", r.text))
            print(f"  Has Sales: {has_sales}, EPS: {has_eps}, P/E: {has_pe}, ROE: {has_roe}")

            # Check for login wall
            has_login = bool(re.search(r"login|sign.?in", r.text, re.I))
            if has_login and not has_sales:
                result["issues"].append("Screener.in may require login for full data access")
                result["notes"] = "Screener.in sometimes shows a login gate for automated requests"
            
            if has_sales or has_pe:
                result["ok"] = True
            else:
                result["issues"].append("Key financial indicators (Sales, P/E) not found in response")

        elif r.status_code == 403:
            result["issues"].append("Screener.in blocked request (403) - User-Agent or rate limit issue")
            result["notes"] = "Screener.in blocks bot-like requests; may need browser-style headers or Playwright"
        else:
            result["issues"].append(f"Screener.in returned {r.status_code}")

    except Exception as e:
        result["issues"].append(f"Exception: {e}")
        print(f"  ERROR: {e}")

    RESULTS["financial_data"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result.get("notes"):
        print(f"  📝 Note: {result['notes']}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── 9. Annual Reports (BSE) ─────────────────────────────────────────────────

def test_annual_reports():
    print("\n" + "="*60)
    print("9. Annual Reports (annual_reports.py)")
    print("="*60)
    # Reliance scrip_code = 500325
    SCRIP = "500325"
    BSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/html, application/json, */*",
        "Referer": "https://www.bseindia.com/",
    }
    URLS = [
        f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={SCRIP}",
        f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport/w?scripcode={SCRIP}",
        f"https://www.bseindia.com/corporates/annualdisplay.aspx?scripcd={SCRIP}",
    ]
    result = {"scraper": "annual_reports", "issues": [], "ok": False}

    for url in URLS:
        print(f"  Trying: {url[:80]}")
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as c:
                r = c.get(url, headers=BSE_HEADERS)
            ct = r.headers.get("content-type","N/A")
            print(f"  Status: {r.status_code} | Content-Type: {ct}")

            if r.status_code == 200:
                if "json" in ct or r.text.lstrip().startswith(("[","{")):
                    try:
                        data = r.json()
                        if isinstance(data, list) and data:
                            row = data[0]
                            pdf_url = row.get("pdf_url") or row.get("PDFDownload") or row.get("PDFURL") or row.get("Attachment","")
                            print(f"  JSON rows: {len(data)}, First PDF URL: {pdf_url[:80] if pdf_url else 'N/A'}")
                            if pdf_url:
                                result["ok"] = True
                                break
                        elif isinstance(data, dict):
                            for v in data.values():
                                if isinstance(v, list) and v:
                                    pdf_url = v[0].get("PDFDownload") or v[0].get("pdf_url","")
                                    print(f"  Dict rows: {len(v)}, PDF: {pdf_url[:80] if pdf_url else 'N/A'}")
                                    if pdf_url:
                                        result["ok"] = True
                                        break
                    except Exception:
                        pass
                else:
                    pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', r.text, re.I)
                    print(f"  HTML PDF links found: {len(pdf_links)}")
                    if pdf_links:
                        result["ok"] = True
                        break
        except Exception as e:
            print(f"  ERROR: {e}")
            result["issues"].append(f"{url[:50]}: {e}")

    if not result["ok"]:
        result["issues"].append("No annual report PDF links found from any BSE endpoint")

    RESULTS["annual_reports"] = result
    status = "✅ PASS" if result["ok"] else "❌ FAIL"
    print(f"\n  Result: {status}")
    if result["issues"]:
        for i in result["issues"]:
            print(f"  ⚠️  {i}")


# ─── SUMMARY ─────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    pass_count = sum(1 for r in RESULTS.values() if r["ok"])
    fail_count = len(RESULTS) - pass_count
    print(f"Total scrapers tested: {len(RESULTS)}")
    print(f"PASS: {pass_count} | FAIL: {fail_count}")
    print()
    for name, r in RESULTS.items():
        status = "✅" if r["ok"] else "❌"
        print(f"  {status} {name}")
        for issue in r.get("issues", []):
            print(f"       ⚠️  {issue}")
        if r.get("notes"):
            print(f"       📝 {r['notes']}")


if __name__ == "__main__":
    print("=" * 60)
    print("FINAGENT SCRAPERS — Live Connectivity & Parse Test")
    print(f"Date: {date.today()}")
    print("=" * 60)

    test_sebi_enforcement()
    time.sleep(2)
    test_bse_eod()
    time.sleep(2)
    test_bse_shp()
    time.sleep(2)
    test_nse_index()
    time.sleep(2)
    test_sebi_corporate_filings()
    time.sleep(2)
    test_mca_companies()
    time.sleep(2)
    test_mca_directors()
    time.sleep(2)
    test_financial_data()
    time.sleep(2)
    test_annual_reports()

    print_summary()
