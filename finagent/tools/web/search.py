"""Multi-engine search rotation (stubs)."""

from finagent.tools.web.scraper import search_web as _search_web

async def search_google(query: str) -> list[dict]:
    docs = await _search_web(query, max_results=10)
    return [{"title": d.title, "url": d.final_url or d.url, "snippet": d.text[:200]} for d in docs]


async def search_bing(query: str) -> list[dict]:
    docs = await _search_web(query, max_results=10)
    return [{"title": d.title, "url": d.final_url or d.url, "snippet": d.text[:200]} for d in docs]


async def search_duckduckgo(query: str) -> list[dict]:
    docs = await _search_web(query, max_results=10)
    return [{"title": d.title, "url": d.final_url or d.url, "snippet": d.text[:200]} for d in docs]
