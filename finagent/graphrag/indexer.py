"""GraphRAG Indexer — builds community summaries from IKG + document chunks.

Takes extracted annual report text (from azure_doc_intel.py) and
creates graph-linked document chunks that are:
  1. Chunked into 512-token segments with 64-token overlap
  2. Each chunk linked to a Company node via CIN
  3. Community summaries generated for clusters of related entities
  4. Chunk embeddings stored for dense retrieval

This is a simplified GraphRAG implementation optimized for the Indian
corporate domain. For the full Microsoft GraphRAG implementation,
see https://github.com/microsoft/graphrag.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("finagent.graphrag.indexer")

_CHUNK_SIZE_TOKENS = 512
_CHUNK_OVERLAP_TOKENS = 64
_CACHE_DIR = Path(os.getenv("FINAGENT_GRAPHRAG_CACHE", "cache/graphrag"))


@dataclass
class DocumentChunk:
    """A text chunk from an annual report or filing, linked to a company node."""
    chunk_id: str           # hash of content + source
    text: str
    source_file: str = ""
    source_type: str = ""   # "annual_report" | "sebi_filing" | "bse_filing"
    company_cin: str | None = None
    company_ticker: str | None = None
    page_number: int = 0
    chunk_index: int = 0
    total_chunks: int = 0
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source_file": self.source_file,
            "source_type": self.source_type,
            "company_cin": self.company_cin,
            "company_ticker": self.company_ticker,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "metadata": self.metadata,
        }


@dataclass
class CommunitySummary:
    """A community-level summary for a cluster of related entities."""
    community_id: str
    summary: str
    entity_ids: list[str] = field(default_factory=list)
    entity_count: int = 0
    relationship_count: int = 0
    key_themes: list[str] = field(default_factory=list)


def _simple_tokenize(text: str) -> list[str]:
    """Simple whitespace+punctuation tokenizer (no external deps)."""
    return re.findall(r"\w+|[^\w\s]", text)


def _chunk_text(
    text: str,
    chunk_size: int = _CHUNK_SIZE_TOKENS,
    overlap: int = _CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """Split text into overlapping chunks by token count.

    Args:
        text: Input text.
        chunk_size: Tokens per chunk.
        overlap: Overlapping tokens between consecutive chunks.

    Returns:
        List of text chunks.
    """
    tokens = _simple_tokenize(text)
    if not tokens:
        return []

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = " ".join(chunk_tokens)
        chunks.append(chunk_text)
        if end >= len(tokens):
            break
        start += chunk_size - overlap

    return chunks


def _generate_chunk_id(text: str, source: str) -> str:
    """Generate a deterministic chunk ID from content + source."""
    content = f"{source}:{text[:200]}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def index_document(
    text: str,
    *,
    source_file: str = "",
    source_type: str = "annual_report",
    company_cin: str | None = None,
    company_ticker: str | None = None,
) -> list[DocumentChunk]:
    """Chunk a document and create DocumentChunk objects.

    Args:
        text: Full document text (from Azure DI or PyMuPDF).
        source_file: Source filename or URL.
        source_type: Document type.
        company_cin: Company CIN for graph linking.
        company_ticker: Company ticker for metadata.

    Returns:
        List of DocumentChunk objects ready for embedding and storage.
    """
    if not text or not text.strip():
        return []

    raw_chunks = _chunk_text(text)
    chunks: list[DocumentChunk] = []

    for i, chunk_text in enumerate(raw_chunks):
        if len(chunk_text.strip()) < 20:
            continue  # Skip trivially small chunks

        chunk = DocumentChunk(
            chunk_id=_generate_chunk_id(chunk_text, source_file),
            text=chunk_text,
            source_file=source_file,
            source_type=source_type,
            company_cin=company_cin,
            company_ticker=company_ticker,
            chunk_index=i,
            total_chunks=len(raw_chunks),
            metadata={
                "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        chunks.append(chunk)

    logger.info(
        "[GRAPHRAG-INDEX] Indexed document: %s → %d chunks (ticker=%s)",
        source_file[:60], len(chunks), company_ticker,
    )
    return chunks


async def embed_chunks(
    chunks: list[DocumentChunk],
    *,
    model: str = "text-embedding-3-small",
    batch_size: int = 50,
) -> list[DocumentChunk]:
    """Generate embeddings for document chunks using OpenAI embedding API.

    Args:
        chunks: List of DocumentChunk objects.
        model: OpenAI embedding model.
        batch_size: Number of chunks to embed per API call.

    Returns:
        Same chunks with embedding field populated.
    """
    from finagent.runtime_provider import resolve_openai_config

    cfg = resolve_openai_config()
    if not cfg:
        logger.warning("[GRAPHRAG-INDEX] No OpenAI config, skipping embeddings")
        return chunks

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=30.0)
        embedded = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.text[:8000] for c in batch]  # Truncate to model limit

            resp = await client.embeddings.create(model=model, input=texts)
            for j, emb_data in enumerate(resp.data):
                batch[j].embedding = emb_data.embedding
                embedded += 1

        logger.info("[GRAPHRAG-INDEX] Embedded %d chunks", embedded)
    except Exception as exc:
        logger.warning("[GRAPHRAG-INDEX] Embedding failed: %s", exc)

    return chunks


def store_chunks_to_cache(
    chunks: list[DocumentChunk],
    ticker: str,
) -> None:
    """Store indexed chunks to local file cache (JSON)."""
    cache_dir = _CACHE_DIR / "chunks" / ticker.upper()
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / "chunks.jsonl"
    with open(cache_file, "a", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    logger.info(
        "[GRAPHRAG-INDEX] Stored %d chunks to %s",
        len(chunks), cache_file,
    )


def load_chunks_from_cache(ticker: str) -> list[DocumentChunk]:
    """Load indexed chunks from local file cache."""
    cache_file = _CACHE_DIR / "chunks" / ticker.upper() / "chunks.jsonl"
    if not cache_file.exists():
        return []

    chunks = []
    with open(cache_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            chunks.append(DocumentChunk(
                chunk_id=data["chunk_id"],
                text=data["text"],
                source_file=data.get("source_file", ""),
                source_type=data.get("source_type", ""),
                company_cin=data.get("company_cin"),
                company_ticker=data.get("company_ticker"),
                chunk_index=data.get("chunk_index", 0),
                total_chunks=data.get("total_chunks", 0),
                metadata=data.get("metadata", {}),
            ))

    return chunks


async def generate_community_summary(
    cin: str,
    *,
    include_directors: bool = True,
    include_enforcement: bool = True,
) -> CommunitySummary | None:
    """Generate a community summary for a company's IKG subgraph.

    Uses the IKG graph client to traverse the company's neighborhood
    and generate a concise summary of the entity cluster.

    Args:
        cin: Company CIN.
        include_directors: Include director relationships.
        include_enforcement: Include enforcement actions.

    Returns:
        CommunitySummary or None if no data.
    """
    from finagent.ikg.graph_client import get_graph_client

    client = get_graph_client()
    subgraph = await client.get_company_subgraph(cin)

    if not subgraph.get("company"):
        return None

    company = subgraph["company"]
    directors = subgraph.get("directors", [])
    promoters = subgraph.get("promoters", [])
    enforcement = subgraph.get("enforcement_actions", [])

    # Build summary text
    parts = [
        f"Company: {company.get('name', 'unknown')} (CIN: {cin})",
    ]

    if directors:
        parts.append(f"Board: {len(directors)} directors on record")

    if promoters:
        total_holding = sum(float(p.get("percentage", 0)) for p in promoters)
        parts.append(f"Promoter holding: {total_holding:.1f}%")

    if enforcement:
        parts.append(f"SEBI enforcement actions: {len(enforcement)}")

    entity_ids = [f"company:{cin}"]
    entity_ids.extend(d.get("from", "") for d in directors)
    entity_ids.extend(p.get("from", "") for p in promoters)

    return CommunitySummary(
        community_id=f"community:{cin}",
        summary=" | ".join(parts),
        entity_ids=entity_ids,
        entity_count=1 + len(directors) + len(promoters),
        relationship_count=len(directors) + len(promoters) + len(enforcement),
        key_themes=[
            "corporate_governance" if directors else None,
            "pledge_risk" if any(float(p.get("pledge_pct", 0)) > 0 for p in promoters) else None,
            "enforcement_risk" if enforcement else None,
        ],
    )
