import asyncio
import logging
from finagent.tools.web.scraper import _search_ddg, _search_bing

logging.basicConfig(level=logging.INFO)

async def test():
    print("Testing DDG Search...")
    ddg_res = await _search_ddg("TCS quarterly results 2026", max_results=5)
    print(f"DDG Results count: {len(ddg_res)}")
    for href, title in ddg_res[:5]:
        print(f" - {title}: {href}")

    print("\nTesting Bing Search...")
    bing_res = await _search_bing("TCS quarterly results 2026", max_results=5)
    print(f"Bing Results count: {len(bing_res)}")
    for href, title in bing_res[:5]:
        print(f" - {title}: {href}")

if __name__ == "__main__":
    asyncio.run(test())
