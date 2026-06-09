"""GraphRAG Query Engine — combines graph traversal with dense retrieval.

Two query modes:

1. **Local Search** (entity-centric):
   - Start from a specific Company node in IKG
   - Traverse 1-2 hops to find related directors, promoters, enforcement
   - Retrieve document chunks linked to the company
   - Combine graph context + chunk context for the LLM

2. **Global Search** (community-level):
   - Load pre-computed community summaries
   - Map query to relevant communities
   - Return high-level thematic context across related entities

Both modes integrate with HyDE for improved retrieval quality.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("finagent.graphrag.query")


@dataclass
class GraphRAGResult:
    """Result of a GraphRAG query."""
    query: str
    mode: str = "local"  # "local" | "global"

    # Graph context
    company_subgraph: dict[str, Any] = field(default_factory=dict)
    community_summary: str = ""
    pledge_risk: dict[str, Any] = field(default_factory=dict)

    # Document chunks
    relevant_chunks: list[dict[str, Any]] = field(default_factory=list)
    chunk_count: int = 0

    # Combined context (ready for LLM injection)
    combined_context: str = ""

    # Metadata
    sources_used: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def to_context_block(self) -> str:
        """Format as a context block for agent injection."""
        if self.combined_context:
            return self.combined_context
        return self._build_context()

    def _build_context(self) -> str:
        parts = []

        if self.company_subgraph:
            company = self.company_subgraph.get("company") or {}
            parts.append(f"## IKG Company Profile: {company.get('name', 'unknown')}")
            parts.append(f"CIN: {company.get('cin', 'N/A')}")
            parts.append(f"Sector: {company.get('sector', 'N/A')}")

            directors = self.company_subgraph.get("directors", [])
            if directors:
                parts.append(f"\nBoard: {len(directors)} directors on record")

        if self.pledge_risk:
            flag = self.pledge_risk.get("pledge_flag", "")
            pct = self.pledge_risk.get("total_pledge_pct", 0)
            parts.append(f"\nPledge risk: {flag} ({pct:.1f}% of promoter holding pledged)")

        if self.community_summary:
            parts.append(f"\n## Community Summary\n{self.community_summary}")

        if self.relevant_chunks:
            parts.append(f"\n## Relevant Document Excerpts ({len(self.relevant_chunks)} chunks)")
            for i, chunk in enumerate(self.relevant_chunks[:5], 1):
                text = chunk.get("text", "")[:400]
                source = chunk.get("source_file", "unknown")
                parts.append(f"\n### Excerpt {i} (from {source})")
                parts.append(text)

        return "\n".join(parts)


async def local_search(
    query: str,
    cin: str,
    *,
    top_k_chunks: int = 5,
    include_pledge: bool = True,
    include_enforcement: bool = True,
) -> GraphRAGResult:
    """Entity-centric local search: start from a company node.

    Args:
        query: User's research query.
        cin: Company CIN as the starting node.
        top_k_chunks: Number of document chunks to retrieve.
        include_pledge: Include pledge risk data.
        include_enforcement: Include enforcement actions.

    Returns:
        GraphRAGResult with graph context + document chunks.
    """
    import time

    start_t = time.time()
    result = GraphRAGResult(query=query, mode="local")

    # Step 1: Get company subgraph from IKG
    try:
        from finagent.ikg.graph_client import get_graph_client
        client = get_graph_client()

        subgraph = await client.get_company_subgraph(cin)
        result.company_subgraph = subgraph
        result.sources_used.append("ikg_graph")

        if include_pledge:
            pledge_data = await client.get_pledge_risk(cin)
            result.pledge_risk = pledge_data

        if include_enforcement:
            enforcement = await client.get_enforcement_actions(cin)
            if enforcement:
                result.company_subgraph["enforcement_actions"] = enforcement

    except Exception as exc:
        logger.debug("[GRAPHRAG-QUERY] IKG traversal failed for CIN %s: %s", cin, exc)

    # Step 2: Retrieve document chunks from the configured retrieval backend.
    try:
        backend = os.getenv("FINAGENT_RETRIEVAL_BACKEND", "qdrant_postgres").strip().lower()
        if backend in {"qdrant", "qdrant_postgres", "postgres_qdrant"}:
            company = result.company_subgraph.get("company") or {}
            qdrant_hits = await _qdrant_postgres_retrieval(
                query,
                top_k=top_k_chunks,
                company_cin=cin,
                nse_symbol=company.get("nse_symbol"),
            )
            if qdrant_hits:
                result.relevant_chunks = qdrant_hits[:top_k_chunks]
                result.chunk_count = len(result.relevant_chunks)
                result.sources_used.append("qdrant_postgres")

        if not result.relevant_chunks and os.getenv("FINAGENT_DISABLE_AZURE_SEARCH", "1").strip().lower() not in {
            "1", "true", "yes", "on",
        }:
            from finagent.graphrag.azure_search import hybrid_search_sections, is_azure_search_configured

            if is_azure_search_configured():
                azure_result = hybrid_search_sections(
                    query,
                    top_k=top_k_chunks,
                    filters=f"company_cin eq '{cin}'" if cin else None,
                )
                if azure_result.ok and azure_result.results:
                    result.relevant_chunks = azure_result.results[:top_k_chunks]
                    result.chunk_count = len(result.relevant_chunks)
                    result.sources_used.append("azure_ai_search")

    except Exception as exc:
        logger.debug("[GRAPHRAG-QUERY] Azure AI Search retrieval failed: %s", exc)

    # Step 3: Retrieve document chunks (from cache) if Azure Search did not return sections.
    try:
        if result.relevant_chunks:
            raise StopIteration
        # Resolve ticker from CIN
        company = result.company_subgraph.get("company") or {}
        ticker = (
            company.get("nse_symbol")
            or company.get("bse_scrip_code")
            or ""
        )

        if ticker:
            from finagent.graphrag.indexer import load_chunks_from_cache
            all_chunks = load_chunks_from_cache(ticker)

            if all_chunks:
                # Simple keyword relevance scoring (replace with embedding similarity later)
                query_tokens = set(query.lower().split())
                scored_chunks = []
                for chunk in all_chunks:
                    chunk_tokens = set(chunk.text.lower().split())
                    overlap = len(query_tokens & chunk_tokens)
                    scored_chunks.append((overlap, chunk))

                scored_chunks.sort(key=lambda x: x[0], reverse=True)
                top_chunks = scored_chunks[:top_k_chunks]
                result.relevant_chunks = [c.to_dict() for _, c in top_chunks]
                result.chunk_count = len(top_chunks)
                result.sources_used.append("document_chunks")

    except StopIteration:
        pass
    except Exception as exc:
        logger.debug("[GRAPHRAG-QUERY] Chunk retrieval failed: %s", exc)

    # Step 4: Generate community summary if available
    try:
        from finagent.graphrag.indexer import generate_community_summary
        community = await generate_community_summary(cin)
        if community:
            result.community_summary = community.summary
            result.sources_used.append("community_summary")
    except Exception as exc:
        logger.debug("[GRAPHRAG-QUERY] Community summary failed: %s", exc)

    # Build combined context
    result.combined_context = result._build_context()
    result.latency_ms = round((time.time() - start_t) * 1000, 1)

    logger.info(
        "[GRAPHRAG-QUERY] Local search for CIN=%s: %d chunks, %d sources, %.0fms",
        cin, result.chunk_count, len(result.sources_used), result.latency_ms,
    )
    return result


async def global_search(
    query: str,
    *,
    top_k_communities: int = 3,
) -> GraphRAGResult:
    """Community-level global search across the entire IKG.

    Maps the query to relevant communities using keyword matching
    (will be upgraded to embedding-based matching).

    Args:
        query: User's research query.
        top_k_communities: Number of communities to return.

    Returns:
        GraphRAGResult with community summaries.
    """
    import time

    start_t = time.time()
    result = GraphRAGResult(query=query, mode="global")

    try:
        backend = os.getenv("FINAGENT_RETRIEVAL_BACKEND", "qdrant_postgres").strip().lower()
        if backend in {"qdrant", "qdrant_postgres", "postgres_qdrant"}:
            hits = await _qdrant_postgres_retrieval(query, top_k=8)
            result.relevant_chunks = hits
            result.chunk_count = len(hits)
            if hits:
                result.sources_used.append("qdrant_postgres")
    except Exception as exc:
        logger.debug("[GRAPHRAG-QUERY] Global Qdrant/Postgres retrieval failed: %s", exc)

    logger.info("[GRAPHRAG-QUERY] Global search (placeholder): query=%s...", query[:60])
    result.combined_context = result._build_context()
    result.latency_ms = round((time.time() - start_t) * 1000, 1)
    return result


async def hybrid_search(
    query: str,
    cin: str | None = None,
    *,
    top_k_chunks: int = 5,
    use_hyde: bool = True,
) -> GraphRAGResult:
    """Hybrid search combining graph traversal, dense retrieval, and HyDE.

    If CIN is provided, uses local search (entity-centric).
    Otherwise, uses global search (community-level).

    Args:
        query: User's research query.
        cin: Company CIN (optional, triggers local search if provided).
        top_k_chunks: Number of document chunks to retrieve.
        use_hyde: Whether to use HyDE query expansion.

    Returns:
        GraphRAGResult with combined context.
    """
    if cin:
        return await local_search(query, cin, top_k_chunks=top_k_chunks)
    else:
        return await global_search(query)


async def _qdrant_postgres_retrieval(
    query: str,
    *,
    top_k: int,
    company_cin: str | None = None,
    nse_symbol: str | None = None,
) -> list[dict[str, Any]]:
    from finagent.graphrag.qdrant_store import hybrid_search_sections

    return await hybrid_search_sections(
        query,
        top_k=top_k,
        company_cin=company_cin,
        nse_symbol=nse_symbol,
    )
