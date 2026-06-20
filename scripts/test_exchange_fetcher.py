"""Live test for the resilient NSE/BSE fetcher.

Tests:
1. NSE marketStatus (lightweight, proves session warm-up works)
2. NSE corporate announcements for BRITANNIA (real-world test)
3. BSE corporate announcements for BRITANNIA scrip 500825
4. Tier-by-tier breakdown — which tier succeeded?
"""
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

sys.stdout.reconfigure(encoding="utf-8")

from finagent.tools.web.exchange_fetcher import (
    fetch_nse_json,
    fetch_bse_json,
    session_status,
    reset_sessions,
    _tier1_nse,
    _tier1_bse,
    NSE_HOME,
    BSE_HOME,
)


def banner(title: str) -> None:
    print(f"\n{'=' * 64}\n  {title}\n{'=' * 64}")


def test_nse_market_status() -> None:
    banner("NSE marketStatus (smoke test — proves session warming works)")
    reset_sessions()
    t0 = time.time()
    data = fetch_nse_json("/api/marketStatus", referer_path="/")
    elapsed = time.time() - t0
    if data:
        if isinstance(data, dict) and data.get("marketState"):
            print(f"  T1 success in {elapsed:.2f}s — {len(data.get('marketState', []))} market segments returned")
        else:
            print(f"  Recovered in {elapsed:.2f}s — keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
    else:
        print(f"  FAILED in {elapsed:.2f}s")
    print(f"  Session status: {session_status()}")


def test_nse_announcements() -> None:
    banner("NSE corporate announcements for BRITANNIA")
    t0 = time.time()
    data = fetch_nse_json(
        "/api/corporate-announcements",
        params={"index": "equities", "symbol": "BRITANNIA"},
        referer_path="/get-quotes/equity?symbol=BRITANNIA",
    )
    elapsed = time.time() - t0
    if data:
        items = data if isinstance(data, list) else (data.get("data") or data.get("rows") or [])
        print(f"  Success in {elapsed:.2f}s — {len(items)} announcement(s)")
        for i, item in enumerate(items[:3]):
            if isinstance(item, dict):
                desc = (item.get("desc") or item.get("subject") or "")[:80]
                dt = item.get("an_dt") or item.get("sortDate") or ""
                print(f"    {i+1}. [{dt}] {desc}")
    else:
        print(f"  FAILED in {elapsed:.2f}s")


def test_bse_announcements() -> None:
    banner("BSE corporate announcements for BRITANNIA (scrip 500825)")
    t0 = time.time()
    data = fetch_bse_json(
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
    elapsed = time.time() - t0
    if data:
        items = data if isinstance(data, list) else (data.get("Table") or [])
        print(f"  Success in {elapsed:.2f}s — {len(items)} announcement(s)")
        for i, item in enumerate(items[:3]):
            if isinstance(item, dict):
                headline = (item.get("NEWSSUB") or item.get("HEADLINE") or "")[:80]
                dt = item.get("NEWS_DT") or item.get("DT_TM") or ""
                print(f"    {i+1}. [{dt}] {headline}")
    else:
        print(f"  FAILED in {elapsed:.2f}s")


def test_tier_isolation() -> None:
    banner("Tier-1-only test (no browser fallback)")
    reset_sessions()
    t0 = time.time()
    data = fetch_nse_json("/api/marketStatus", referer_path="/", use_browser_fallback=False)
    elapsed = time.time() - t0
    print(f"  T1-only result: {'PASS' if data else 'FAIL'} in {elapsed:.2f}s")
    if data:
        print(f"    Got: {type(data).__name__} with {len(data) if hasattr(data, '__len__') else '?'} entries")


def test_cross_exchange_orchestrator() -> None:
    banner("Cross-exchange orchestrator (NSE + BSE merge)")
    from finagent.news.sources.exchange_announcements import fetch_exchange_announcements
    t0 = time.time()
    items = fetch_exchange_announcements(
        nse_symbol="BRITANNIA",
        bse_scrip_code="500825",
        max_results=5,
    )
    elapsed = time.time() - t0
    print(f"  {len(items)} merged announcement(s) in {elapsed:.2f}s")
    for i, item in enumerate(items[:5]):
        nse = "N" if item.get("nse_corroborated") else "-"
        bse = "B" if item.get("bse_corroborated") else "-"
        title = str(item.get("title") or "")[:70]
        dt = str(item.get("published") or "")
        print(f"    {i+1}. [{nse}{bse}] [{dt}] {title}")


if __name__ == "__main__":
    test_nse_market_status()
    test_tier_isolation()
    test_nse_announcements()
    test_bse_announcements()
    test_cross_exchange_orchestrator()
    print("\n" + "=" * 64)
    print("  Done. Final session status:", session_status())
    print("=" * 64)
