import asyncio
import logging
from finagent.tools.web.http_fetcher import fetch
from scratch_test_bing_regex import test as test_regex

logging.basicConfig(level=logging.INFO)

async def run_live_check():
    url = "https://www.bing.com/search?q=TCS+quarterly+results+2026&count=15&form=QBLH"
    print("Fetching Bing live via standard HTTP...")
    res = await fetch(url, respect_robots=False, timeout_s=20.0)
    print(f"Status code: {res.status}")
    print(f"Response length: {len(res.text or '')}")
    with open("bing_live_response.html", "w", encoding="utf-8") as f:
        f.write(res.text or "")
        
    print("\nRunning parser on standard HTTP response:")
    with open("bing_response.html", "w", encoding="utf-8") as f:
        f.write(res.text or "")
    test_regex()
    
    print("\nFetching Bing live via Playwright browser...")
    res_browser = await fetch(url, respect_robots=False, timeout_s=25.0, use_browser=True)
    print(f"Browser status: {res_browser.status}")
    print(f"Browser response length: {len(res_browser.text or '')}")
    with open("bing_browser_live_response.html", "w", encoding="utf-8") as f:
        f.write(res_browser.text or "")
        
    print("\nRunning parser on browser response:")
    with open("bing_response.html", "w", encoding="utf-8") as f:
        f.write(res_browser.text or "")
    test_regex()

if __name__ == "__main__":
    asyncio.run(run_live_check())
