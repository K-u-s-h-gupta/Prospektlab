from __future__ import annotations

import asyncio
import sys

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8020/finagent/gateway/widget.html"
    async with AsyncWebCrawler(
        config=BrowserConfig(headless=True, browser_type="chromium", verbose=False)
    ) as crawler:
        result = await crawler.arun(
            url,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=30000),
        )
    html = result.html or ""
    print(f"success={result.success}")
    print(f"url={result.url}")
    print(f"html_len={len(html)}")
    print(f"has_workspace={'Portfolio mirror' in html}")
    return 0 if result.success and html else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
