"""GraphRAG MCP Server — FastAPI server exposing GraphRAG query endpoints at :8009.

Provides:
  POST /graphrag/search       — hybrid search (local if CIN, global otherwise)
  POST /graphrag/local        — entity-centric local search by CIN
  POST /graphrag/global       — community-level global search
  GET  /graphrag/index-status — indexing status and stats
  POST /graphrag/index        — trigger document indexing
  GET  /graphrag/health       — server health check
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("finagent.graphrag.mcp_server")


def create_graphrag_app() -> Any:
    """Create and return the FastAPI app for the GraphRAG MCP server."""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("fastapi and pydantic required. Install: pip install fastapi pydantic") from exc

    app = FastAPI(
        title="GraphRAG MCP Server",
        description="Graph-based Retrieval Augmented Generation for Indian Corporate Research",
        version="1.0.0",
    )

    class SearchRequest(BaseModel):
        query: str = Field(..., description="Research query")
        cin: str | None = Field(None, description="Company CIN for local search")
        top_k: int = Field(5, ge=1, le=20, description="Number of chunks to retrieve")
        use_hyde: bool = Field(True, description="Use HyDE query expansion")

    class IndexRequest(BaseModel):
        text: str = Field(..., description="Document text to index")
        source_file: str = Field("", description="Source filename or URL")
        source_type: str = Field("annual_report", description="Document type")
        company_cin: str | None = Field(None, description="Company CIN")
        company_ticker: str | None = Field(None, description="Company ticker")

    @app.get("/graphrag/health")
    async def health() -> dict[str, Any]:
        """Health check."""
        return {
            "status": "healthy",
            "service": "graphrag-mcp",
            "version": "1.0.0",
        }

    @app.post("/graphrag/search")
    async def hybrid_search(request: SearchRequest) -> dict[str, Any]:
        """Hybrid search: local if CIN provided, global otherwise."""
        from finagent.graphrag.query import hybrid_search as _hybrid_search

        result = await _hybrid_search(
            query=request.query,
            cin=request.cin,
            top_k_chunks=request.top_k,
            use_hyde=request.use_hyde,
        )
        return {
            "query": result.query,
            "mode": result.mode,
            "chunk_count": result.chunk_count,
            "sources_used": result.sources_used,
            "latency_ms": result.latency_ms,
            "context": result.to_context_block(),
            "pledge_risk": result.pledge_risk,
        }

    @app.post("/graphrag/local")
    async def local_search(request: SearchRequest) -> dict[str, Any]:
        """Entity-centric local search by CIN."""
        if not request.cin:
            raise HTTPException(status_code=400, detail="CIN is required for local search")

        from finagent.graphrag.query import local_search as _local_search

        result = await _local_search(
            query=request.query,
            cin=request.cin,
            top_k_chunks=request.top_k,
        )
        return {
            "query": result.query,
            "mode": "local",
            "company_subgraph": result.company_subgraph,
            "pledge_risk": result.pledge_risk,
            "chunk_count": result.chunk_count,
            "relevant_chunks": result.relevant_chunks[:request.top_k],
            "community_summary": result.community_summary,
            "latency_ms": result.latency_ms,
        }

    @app.post("/graphrag/global")
    async def global_search(request: SearchRequest) -> dict[str, Any]:
        """Community-level global search."""
        from finagent.graphrag.query import global_search as _global_search

        result = await _global_search(
            query=request.query,
            top_k_communities=request.top_k,
        )
        return {
            "query": result.query,
            "mode": "global",
            "community_summary": result.community_summary,
            "latency_ms": result.latency_ms,
        }

    @app.post("/graphrag/index")
    async def index_document(request: IndexRequest) -> dict[str, Any]:
        """Index a document for GraphRAG retrieval."""
        from finagent.graphrag.indexer import (
            embed_chunks,
            index_document as _index_document,
            store_chunks_to_cache,
        )

        chunks = _index_document(
            text=request.text,
            source_file=request.source_file,
            source_type=request.source_type,
            company_cin=request.company_cin,
            company_ticker=request.company_ticker,
        )

        if chunks and request.company_ticker:
            # Embed and store
            chunks = await embed_chunks(chunks)
            store_chunks_to_cache(chunks, request.company_ticker)

        return {
            "chunks_created": len(chunks),
            "company_ticker": request.company_ticker,
            "company_cin": request.company_cin,
            "source_type": request.source_type,
        }

    @app.get("/graphrag/index-status")
    async def index_status() -> dict[str, Any]:
        """Return indexing status and chunk counts."""
        from pathlib import Path

        cache_dir = Path(os.getenv("FINAGENT_GRAPHRAG_CACHE", "cache/graphrag")) / "chunks"
        if not cache_dir.exists():
            return {"total_tickers": 0, "total_chunks": 0}

        ticker_dirs = [d for d in cache_dir.iterdir() if d.is_dir()]
        total_chunks = 0
        tickers = []

        for ticker_dir in ticker_dirs:
            chunks_file = ticker_dir / "chunks.jsonl"
            if chunks_file.exists():
                with open(chunks_file, encoding="utf-8") as fh:
                    count = sum(1 for _ in fh)
                total_chunks += count
                tickers.append({"ticker": ticker_dir.name, "chunks": count})

        return {
            "total_tickers": len(tickers),
            "total_chunks": total_chunks,
            "tickers": tickers[:50],  # Cap at 50 for response size
        }

    # MCP tool definitions
    @app.get("/mcp/tools")
    async def list_mcp_tools() -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": "graphrag_search",
                    "description": "Search annual reports and SEBI filings using graph-augmented retrieval",
                    "parameters": {
                        "query": {"type": "string", "description": "Research query"},
                        "cin": {"type": "string", "description": "Optional CIN for entity-centric search"},
                    },
                },
                {
                    "name": "graphrag_index",
                    "description": "Index a new document for GraphRAG retrieval",
                    "parameters": {
                        "text": {"type": "string"},
                        "company_ticker": {"type": "string"},
                    },
                },
            ]
        }

    return app


def start_graphrag_server(host: str = "0.0.0.0", port: int = 8009) -> None:
    """Start the GraphRAG MCP server."""
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("uvicorn required. Install: pip install uvicorn") from exc

    app = create_graphrag_app()
    logger.info("Starting GraphRAG MCP server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_graphrag_server()
