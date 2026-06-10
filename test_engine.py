"""Quick validation test for SmartScraper engine + all scrapers."""
import asyncio
import sys
import os
import warnings

# Suppress benign Windows asyncio/Patchright subprocess cleanup warnings
warnings.filterwarnings("ignore", category=ResourceWarning)

sys.path.insert(0, 'd:/PROSPEKTLAB')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


async def test_engine():
    print("=== 1. Engine Self-Test ===")
    from finagent.ikg.scrapers._engine import SmartHTTPClient, SmartBrowser, bootstrap_proxy_pool

    pool = await bootstrap_proxy_pool()
    print(f"  Proxy pool size: {pool.pool_size()}")
    nxt = pool.next()
    print(f"  Next proxy: {nxt or 'direct (no validated proxies yet)'}")

    client = SmartHTTPClient()
    try:
        resp = await client.get("https://httpbin.org/headers", timeout=15.0)
        ua = resp.json().get("headers", {}).get("User-Agent", "N/A")
        print(f"  SmartHTTPClient status: {resp.status_code}")
        print(f"  UA seen by server: {ua[:80]}")
    except Exception as e:
        print(f"  SmartHTTPClient ERROR: {e}")


async def test_browser():
    print()
    print("=== 2. Patchright Browser Test ===")
    from finagent.ikg.scrapers._engine import SmartBrowser
    import re

    browser = SmartBrowser(headless=True)
    await browser.start()
    try:
        content = await browser.get_page_content(
            "https://bot.sannysoft.com", wait_ms=3000
        )
        webdriver_match = re.search(r"webdriver[^<]{0,200}", content, re.I)
        print(f"  Browser started: OK")
        print(f"  Page length: {len(content)}")
        print(f"  webdriver context: {webdriver_match.group(0)[:120] if webdriver_match else 'NOT FOUND (good)'}")
    except Exception as e:
        print(f"  Browser ERROR: {e}")
    finally:
        await browser.close()


async def test_scrapers():
    print()
    print("=== 3. Scraper Import Test ===")
    scrapers = [
        "finagent.ikg.scrapers.sebi_enforcement",
        "finagent.ikg.scrapers.bse_eod",
        "finagent.ikg.scrapers.bse_shp",
        "finagent.ikg.scrapers.nse_index",
        "finagent.ikg.scrapers.sebi_corporate_filings",
        "finagent.ikg.scrapers.mca_companies",
        "finagent.ikg.scrapers.mca_directors",
        "finagent.ikg.scrapers.financial_data",
        "finagent.ikg.scrapers.annual_reports",
    ]
    for mod in scrapers:
        try:
            __import__(mod)
            print(f"  OK  {mod}")
        except Exception as e:
            print(f"  ERR {mod}: {e}")


async def test_live_endpoints():
    print()
    print("=== 4. Live Endpoint Tests (via SmartHTTPClient) ===")
    from finagent.ikg.scrapers._engine import SmartHTTPClient

    client = SmartHTTPClient()

    tests = [
        ("SEBI enforcement", "https://www.sebi.gov.in/enforcement/orders.html",
         {"Referer": "https://www.sebi.gov.in/"}),
        ("BSE EOD metadata", "https://api.bseindia.com/BseIndiaAPI/api/GetBhavcopydata/w?flag=1&segment=equity&date=20250601",
         {"Referer": "https://www.bseindia.com/"}),
        ("BSE SHP", "https://api.bseindia.com/BseIndiaAPI/api/shpDecleraction/w?scripcode=500325",
         {"Referer": "https://www.bseindia.com/"}),
        ("NSE Nifty500", "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
         {"Referer": "https://www.niftyindices.com/"}),
        ("Screener.in", "https://www.screener.in/company/RELIANCE/consolidated/",
         {"Referer": "https://www.screener.in/"}),
        ("BSE Annual Reports", "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode=500325",
         {"Referer": "https://www.bseindia.com/"}),
    ]

    import time
    for name, url, extra_h in tests:
        try:
            t0 = time.time()
            resp = await client.get(url, headers=extra_h, timeout=20.0, retries=2)
            elapsed = time.time() - t0
            print(f"  OK  [{resp.status_code}] {name:30s} {elapsed:.1f}s | {len(resp.text)} chars")
        except Exception as e:
            print(f"  ERR {name:30s}: {e}")
        await asyncio.sleep(1.0)


async def main():
    await test_engine()
    await test_browser()
    await test_scrapers()
    await test_live_endpoints()
    print()
    print("=== Validation Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
