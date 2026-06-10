"""HyDE (Hypothetical Document Embeddings) retrieval wrapper.

Instead of embedding the user's question directly, HyDE:
1. Uses the LLM to generate a hypothetical "ideal answer document"
2. Embeds THAT hypothetical document
3. Uses the better embedding to retrieve real documents

This significantly improves retrieval quality for domain-specific
corpora like Indian annual reports and SEBI filings, where the
question vocabulary differs from document vocabulary.

Reference: "Precise Zero-Shot Dense Retrieval without Relevance Labels"
           (Gao et al., 2022) — https://arxiv.org/abs/2212.10496
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("finagent.retrieval.hyde")


@runtime_checkable
class AsyncRetriever(Protocol):
    """Protocol for retrieval backends that HyDE wraps."""
    async def retrieve(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]: ...


_HYDE_SYSTEM_PROMPT = """\
You are a financial document analyst specializing in Indian capital markets.
Generate a hypothetical document excerpt (2-4 paragraphs) that would PERFECTLY
answer the following research question. Write as if you are an author of an
Indian annual report, SEBI filing, or BSE corporate disclosure.

Rules:
- Use precise financial terminology and Indian regulatory language
- Include specific numeric references (percentages, ratios, INR amounts)
- Write in the style of official corporate disclosures
- Do NOT state it is hypothetical — write as if real
- Do NOT include investment recommendations

The hypothetical document should contain the kind of text that would appear
in a search-result hit if this question had a perfect answer.
"""


async def generate_hypothetical_document(
    query: str,
    *,
    timeout_s: float = 8.0,
) -> str:
    """Generate a hypothetical document using the configured LLM.

    Falls back to the original query if LLM generation fails, ensuring
    HyDE never degrades retrieval to worse than baseline.

    Args:
        query: The research question to expand.
        timeout_s: Max seconds to wait for LLM response.

    Returns:
        Hypothetical document string (or original query on failure).
    """
    from finagent.runtime_provider import resolve_openai_config

    cfg = resolve_openai_config(complexity="simple")  # cheap model for HyDE
    if not cfg:
        logger.debug("[HyDE] No LLM config available, using original query")
        return query

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=timeout_s,
        )
        resp = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": _HYDE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Research question: {query}"},
            ],
            temperature=0.4,
            max_tokens=600,
            seed=42,  # deterministic for caching
        )
        hypothetical = resp.choices[0].message.content or ""
        if hypothetical.strip():
            logger.debug(
                "[HyDE] Generated hypothetical doc (%d chars) for query: %s...",
                len(hypothetical), query[:60],
            )
            return hypothetical.strip()
    except asyncio.TimeoutError:
        logger.warning("[HyDE] LLM timeout generating hypothetical document")
    except Exception as exc:
        logger.warning("[HyDE] Failed to generate hypothetical doc: %s", exc)

    return query  # graceful fallback


async def hyde_retrieve(
    query: str,
    retriever: AsyncRetriever,
    *,
    top_k: int = 5,
    use_hyde: bool = True,
    blend: bool = True,
) -> list[dict[str, Any]]:
    """Retrieve documents using HyDE-expanded query.

    Args:
        query: Original user query.
        retriever: Any retrieval backend implementing AsyncRetriever protocol.
        top_k: Number of results to return.
        use_hyde: Whether to use HyDE expansion (disable to revert to baseline).
        blend: If True, retrieve with BOTH original and hypothetical query
               and deduplicate (best of both worlds).

    Returns:
        List of retrieved document dicts with 'text', 'score', 'source' keys.
    """
    if not use_hyde:
        return await retriever.retrieve(query, top_k=top_k)

    # Generate hypothetical document
    hyp_doc = await generate_hypothetical_document(query)

    if blend and hyp_doc != query:
        # Retrieve from both queries and merge
        original_results, hyp_results = await asyncio.gather(
            retriever.retrieve(query, top_k=top_k),
            retriever.retrieve(hyp_doc, top_k=top_k),
        )
        # Deduplicate by source/id, preferring higher score
        merged: dict[str, dict[str, Any]] = {}
        for doc in original_results + hyp_results:
            key = doc.get("id") or doc.get("source") or doc.get("text", "")[:100]
            if key not in merged or doc.get("score", 0) > merged[key].get("score", 0):
                merged[key] = doc
        # Sort by score descending, return top_k
        final = sorted(merged.values(), key=lambda d: d.get("score", 0), reverse=True)
        logger.info(
            "[HyDE] Blend mode: original=%d hyp=%d merged=%d final=%d",
            len(original_results), len(hyp_results), len(merged), len(final[:top_k]),
        )
        return final[:top_k]
    else:
        # Hypothetical-only mode
        return await retriever.retrieve(hyp_doc, top_k=top_k)


async def hyde_retrieve_annual_report(
    query: str,
    retriever: AsyncRetriever,
    *,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Specialized HyDE retrieval for annual reports and SEBI filings.

    Uses blend mode by default for maximum coverage of complex financial queries.
    """
    return await hyde_retrieve(query, retriever, top_k=top_k, use_hyde=True, blend=True)
