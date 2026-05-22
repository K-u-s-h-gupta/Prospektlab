import asyncio
import logging
import sys
from finagent.tools.web.scraper import search_web

# Enable logging to see what's happening
logging.basicConfig(level=logging.DEBUG)

async def test():
    import os
    os.environ["TAVILY_API_KEY"] = ""
    print("Starting direct scraper test...")
    try:
        res = await search_web('Reliance Industries "annual report" site:nseindia.com', max_results=3)
        print("Scraper call 1 completed successfully!")
        print("Result count:", len(res))
        for i, r in enumerate(res):
            print(f"[{i}] {r.url} (via {r.via}) - title: {r.title} - text length: {r.text_len}")
            print(f"    Excerpt: {r.excerpt[:200]}...")
            
        print("\nTesting simple query to verify Bing extraction...")
        res2 = await search_web('Reliance Industries', max_results=3)
        print("Scraper call 2 completed successfully!")
        print("Result count:", len(res2))
        for i, r in enumerate(res2):
            print(f"[{i}] {r.url} (via {r.via}) - title: {r.title} - text length: {r.text_len}")
            print(f"    Excerpt: {r.excerpt[:200]}...")
    except Exception as e:
        print("SCRAPER CRASHED!", file=sys.stderr)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
