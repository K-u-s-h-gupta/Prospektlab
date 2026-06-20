"""Test Tier 1b (curl_cffi browser-TLS impersonation) by disabling Tier 1."""
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8")

import finagent.tools.web.exchange_fetcher as ef

# Force Tier 1 (warmed httpx) to always fail
ef._tier1_nse = lambda *a, **k: None
ef._tier1_bse = lambda *a, **k: None
# Force Tier 2 (browser) to fail so we know it was T1b that succeeded
ef._tier2_browser_json_sync = lambda *a, **k: None


print("=" * 64)
print("Tier 1 disabled — testing T1b (curl_cffi with Chrome131 TLS fingerprint)")
print("=" * 64)

print()
print("--- NSE marketStatus via T1b ---")
t0 = time.time()
data = ef.fetch_nse_json("/api/marketStatus", referer_path="/")
print(f"  {'PASS' if data else 'FAIL'} in {time.time() - t0:.2f}s")
if data and isinstance(data, dict):
    print(f"  market segments: {len(data.get('marketState', []))}")

print()
print("--- NSE BRITANNIA announcements via T1b ---")
t0 = time.time()
data = ef.fetch_nse_json(
    "/api/corporate-announcements",
    params={"index": "equities", "symbol": "BRITANNIA"},
    referer_path="/get-quotes/equity?symbol=BRITANNIA",
)
print(f"  {'PASS' if data else 'FAIL'} in {time.time() - t0:.2f}s")
if data:
    items = data if isinstance(data, list) else (data.get("data") or [])
    print(f"  announcement count: {len(items)}")
    if items:
        print(f"  most recent: {items[0].get('desc', '')[:80]}")

print()
print("--- BSE BRITANNIA announcements via T1b ---")
t0 = time.time()
data = ef.fetch_bse_json(
    "/BseIndiaAPI/api/AnnSubCategoryGetData/w",
    params={
        "pageno": "1",
        "strCat": "-1",
        "strPrevDate": "",
        "strScrip": "500825",
        "strSearch": "P",
        "strToDate": "",
        "strType": "C",
    },
)
print(f"  {'PASS' if data else 'FAIL'} in {time.time() - t0:.2f}s")
if data:
    items = data if isinstance(data, list) else (data.get("Table") or [])
    print(f"  announcement count: {len(items)}")
    if items:
        print(f"  most recent: {items[0].get('NEWSSUB', '')[:80]}")
