from __future__ import annotations

from finagent.retrieval.reranker import rerank_docs
from finagent.tools.web.scraper import ScrapedDoc


def _doc(
    domain: str,
    title: str,
    excerpt: str,
    *,
    tier: int = 5,
    url_path: str = "",
) -> ScrapedDoc:
    url = f"https://{domain}/{url_path or title.lower().replace(' ', '-')}"
    return ScrapedDoc(
        url=url,
        final_url=url,
        domain=domain,
        tier=tier,
        title=title,
        excerpt=excerpt,
        text_len=len(excerpt),
        status=200,
    )


def test_regulatory_sources_beat_generic_keyword_stuffing() -> None:
    exchange_doc = _doc(
        "nseindia.com",
        "CG Power Regulation 33 financial results 2026-05-20",
        "SEBI LODR Regulation 33 quarterly financial results and board outcome.",
        tier=1,
    )
    blog_doc = _doc(
        "example-blog.test",
        "CG Power analysis analysis analysis",
        "CG Power analysis valuation analysis results analysis repeated many times.",
        tier=5,
    )

    ranked = rerank_docs("CG Power SEBI LODR Regulation 33 results", [blog_doc, exchange_doc])

    assert ranked[0] is exchange_doc


def test_latest_queries_prefer_recent_relevant_items() -> None:
    old_doc = _doc(
        "moneycontrol.com",
        "Tata Power latest news 2024-01-10",
        "Tata Power latest news and analyst update.",
        tier=4,
    )
    recent_doc = _doc(
        "livemint.com",
        "Tata Power latest news 2026-05-20",
        "Tata Power latest news and analyst update.",
        tier=4,
    )

    ranked = rerank_docs("Tata Power latest news", [old_doc, recent_doc])

    assert ranked[0] is recent_doc


def test_preferred_domain_boost_is_respected() -> None:
    preferred_doc = _doc(
        "bseindia.com",
        "Tata Motors shareholding pattern",
        "Tata Motors shareholding pattern under SEBI LODR.",
        tier=1,
    )
    other_doc = _doc(
        "finance-portal.test",
        "Tata Motors shareholding pattern",
        "Tata Motors shareholding pattern summary.",
        tier=3,
    )

    ranked = rerank_docs(
        "Tata Motors shareholding pattern",
        [other_doc, preferred_doc],
        preferred_domains=["bseindia.com"],
    )

    assert ranked[0] is preferred_doc
