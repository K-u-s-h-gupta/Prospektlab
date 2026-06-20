"""Force Tier 2 (stealth browser) to verify the fallback path works.

We bypass Tier 1 by monkey-patching _tier1_nse to always return None,
so the call has to go through patchright stealth browser.
"""
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8")

import finagent.tools.web.exchange_fetcher as ef

# Force Tier 1 to fail
ef._tier1_nse = lambda *a, **k: None
ef._tier1_bse = lambda *a, **k: None

print("Tier 1 disabled — testing Tier 2 (stealth browser) fallback...")
print()

t0 = time.time()
data = ef.fetch_nse_json("/api/marketStatus", referer_path="/")
elapsed = time.time() - t0
if data:
    print(f"T2 marketStatus: PASS in {elapsed:.2f}s")
    if isinstance(data, dict):
        ms = data.get("marketState") or []
        print(f"  Got {len(ms)} market segment(s)")
else:
    print(f"T2 marketStatus: FAIL in {elapsed:.2f}s")

print()
t0 = time.time()
data = ef.fetch_nse_json(
    "/api/corporate-announcements",
    params={"index": "equities", "symbol": "BRITANNIA"},
    referer_path="/get-quotes/equity?symbol=BRITANNIA",
)
elapsed = time.time() - t0
if data:
    items = data if isinstance(data, list) else (data.get("data") or [])
    print(f"T2 NSE announcements: PASS in {elapsed:.2f}s — {len(items)} item(s)")
    for i, item in enumerate(items[:2]):
        if isinstance(item, dict):
            print(f"  {i+1}. {item.get('desc', '')[:80]}")
else:
    print(f"T2 NSE announcements: FAIL in {elapsed:.2f}s")
