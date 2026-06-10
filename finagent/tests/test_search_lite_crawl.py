from __future__ import annotations

import pytest

import finagent.tools.web.scraper as scraper
from finagent.tools.web.scraper import ScrapedDoc, search_layered


@pytest.mark.anyio
async def test_search_layered_forwards_lite_crawl_flag(monkeypatch):
    calls: list[dict[str, object]] = []

    async def fake_search_web(
        query: str,
        *,
        max_results: int = 5,
        preferred_domains=None,
        entity=None,
        query_cache=None,
        bypass_crawl4ai: bool = False,
        lite_crawl: bool = False,
    ):
        calls.append({"query": query, "bypass": bypass_crawl4ai, "lite": lite_crawl, "max_results": max_results})
        n = len(calls)
        return [
            ScrapedDoc(
                url=f"https://example.com/{n}",
                final_url=f"https://example.com/{n}",
                domain="example.com",
                tier=2,
                title=f"Doc {n}",
                excerpt="snippet",
                text_len=42,
                status=200,
            )
        ]

    monkeypatch.setattr(scraper, "search_web", fake_search_web)

    docs = await search_layered(
        "TCS",
        queries=["query-one", "query-two"],
        per_query=1,
        bypass_crawl4ai=False,
        lite_crawl=True,
    )

    assert len(calls) == 2
    assert all(call["lite"] is True for call in calls)
    assert all(call["bypass"] is False for call in calls)
    assert len(docs) == 2
