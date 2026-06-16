"""
ORACLE FIOS - Document Pipeline MCP Server
=============================================
Implements the smart document retrieval pipeline:

  Step 1: Check Qdrant (already indexed?)
    YES -> Return cached chunks
    NO  -> Step 2

  Step 2: Auto-fetch from BSE / NseIndiaApi
    -> Download PDF (annual reports, filings)
    -> Extract text (PyMuPDF)
    -> Chunk & store in Qdrant
    -> Return relevant chunks

  Step 3 (fallback): Tavily Extract
    -> Extract URL content directly
    -> Return extracted text to LLM

Exposes MCP tools:
  - doc_search           : search indexed documents in Qdrant
  - doc_ingest_pdf       : ingest a PDF file into Qdrant
  - doc_ingest_url       : extract URL content, chunk, and index in Qdrant
  - doc_fetch_annual_report : auto-fetch annual report from NSE and index
  - doc_compare_offer_documents : retrieve and compare DRHP / RHP / prospectus docs
  - doc_list_collections : list available document collections
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "oracle_documents")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Embedding model config
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 dimension

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("oracle.docs_mcp")

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "ORACLE Document Pipeline",
    instructions=(
        "Document ingestion, indexing, and retrieval pipeline. "
        "Searches Qdrant vector DB for indexed documents (annual reports, "
        "con-call transcripts, research notes). If not found, auto-fetches "
        "from BSE/NSE and indexes for future queries. "
        "Part of the ORACLE Financial Intelligence OS."
    ),
)

# ---------------------------------------------------------------------------
# Lazy-loaded clients
# ---------------------------------------------------------------------------
_qdrant_client = None
_embedder = None
_download_dir = os.path.join(tempfile.gettempdir(), "oracle_docs")
SECTION_ALIASES = {
    "risk_factors": ["risk factors", "risk factor"],
    "business_overview": ["our business", "business overview", "company overview", "industry overview"],
    "objects_of_issue": ["objects of the issue", "objects of this issue", "use of proceeds", "issue proceeds"],
    "financial_information": [
        "financial information",
        "restated financial information",
        "summary financial information",
        "selected financial information",
    ],
    "capital_structure": ["capital structure"],
    "management": ["our management", "management", "board of directors"],
}
DOC_SEARCH_CONFIG = {
    "drhp": {"query": "draft red herring prospectus pdf", "keywords": ["drhp", "draft red herring prospectus"]},
    "rhp": {"query": "red herring prospectus pdf", "keywords": ["rhp", "red herring prospectus"]},
    "prospectus": {"query": "prospectus pdf", "keywords": ["prospectus"]},
}


def _get_qdrant():
    """Get or create Qdrant client and ensure collection exists."""
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        if QDRANT_API_KEY:
            _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        else:
            _qdrant_client = QdrantClient(url=QDRANT_URL)

        # Ensure collection exists
        collections = [c.name for c in _qdrant_client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            _qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection: %s", COLLECTION_NAME)

    return _qdrant_client


def _get_embedder():
    """Get or create the sentence-transformers embedding model."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("Loaded embedding model: %s", EMBEDDING_MODEL)
    return _embedder


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using sentence-transformers."""
    model = _get_embedder()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------
def _chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks, respecting paragraph boundaries."""
    if not text or not text.strip():
        return []

    # Split by paragraphs first, then recombine into chunks
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk += ("\n\n" + para) if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # If single paragraph is too long, split by sentences
            if len(para) > chunk_size:
                sentences = para.replace(". ", ".\n").split("\n")
                current_chunk = ""
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 <= chunk_size:
                        current_chunk += (" " + sent) if current_chunk else sent
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = sent
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk.strip())

    # Add overlap: prepend last N chars of previous chunk
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            overlapped.append(prev_tail + " ... " + chunks[i])
        chunks = overlapped

    return chunks


def _extract_pdf_text(pdf_path: str) -> str:
    """Extract text from a PDF file using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    text_parts = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text_parts.append(f"--- Page {page_num + 1} ---\n{page.get_text()}")
    doc.close()
    return "\n\n".join(text_parts)


def _doc_id(source: str, symbol: str | None = None) -> str:
    """Generate a deterministic document ID."""
    return hashlib.md5(f"{source}:{symbol or 'UNKNOWN'}".encode()).hexdigest()


def _get_tavily_client():
    """Return a Tavily client for document search/extraction flows."""
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY not configured.")
    from tavily import TavilyClient

    return TavilyClient(api_key=TAVILY_API_KEY)


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _score_document_candidate(company_name: str, doc_type: str, title: str, url: str, snippet: str, score: float | None) -> float:
    config = DOC_SEARCH_CONFIG[doc_type]
    haystack = f"{title} {url} {snippet}".lower()
    company_tokens = [token for token in re.split(r"[^a-z0-9]+", company_name.lower()) if len(token) > 2]
    boosted_score = float(score or 0.0)
    if any(keyword in haystack for keyword in config["keywords"]):
        boosted_score += 3.0
    boosted_score += min(2.0, 0.25 * sum(1 for token in company_tokens if token in haystack))
    host = _hostname(url)
    if any(domain in host for domain in ("sebi.gov.in", "nseindia.com", "bseindia.com")):
        boosted_score += 2.0
    return boosted_score


def _find_section_positions(text: str) -> list[tuple[int, str]]:
    lower_text = text.lower()
    positions: list[tuple[int, str]] = []
    for section_name, aliases in SECTION_ALIASES.items():
        best_pos = None
        for alias in aliases:
            pos = lower_text.find(alias)
            if pos != -1 and (best_pos is None or pos < best_pos):
                best_pos = pos
        if best_pos is not None:
            positions.append((best_pos, section_name))
    positions.sort(key=lambda item: item[0])
    return positions


def _extract_named_sections(text: str) -> dict[str, dict[str, Any]]:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return {}

    positions = _find_section_positions(normalized_text)
    sections: dict[str, dict[str, Any]] = {}
    for idx, (start, section_name) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else min(len(normalized_text), start + 6000)
        section_text = normalized_text[start:end].strip()
        sections[section_name] = {
            "present": True,
            "section_length": len(section_text),
            "excerpt": section_text[:1200],
        }

    for section_name in SECTION_ALIASES:
        sections.setdefault(section_name, {"present": False, "section_length": 0, "excerpt": ""})
    return sections


def _build_transition_notes(documents: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for left, right in zip(documents, documents[1:]):
        left_type = left["doc_type"].upper()
        right_type = right["doc_type"].upper()
        for section_name in SECTION_ALIASES:
            left_section = left["sections"][section_name]
            right_section = right["sections"][section_name]
            if left_section["present"] and not right_section["present"]:
                notes.append(f"{section_name} appears in {left_type} but not in {right_type}.")
            elif not left_section["present"] and right_section["present"]:
                notes.append(f"{section_name} appears in {right_type} but not in {left_type}.")
            elif left_section["present"] and right_section["present"] and left_section["section_length"] > 0:
                left_len = left_section["section_length"]
                right_len = right_section["section_length"]
                change_ratio = abs(right_len - left_len) / left_len
                if change_ratio >= 0.2:
                    direction = "expanded" if right_len > left_len else "condensed"
                    notes.append(f"{section_name} was {direction} from {left_type} to {right_type}.")

    deduped: list[str] = []
    seen = set()
    for note in notes:
        if note not in seen:
            seen.add(note)
            deduped.append(note)
    return deduped


# ---------------------------------------------------------------------------
# Tool: doc_search
# ---------------------------------------------------------------------------
@mcp.tool
def doc_search(
    query: str,
    symbol: str | None = None,
    doc_type: str | None = None,
    top_k: int = 5,
) -> dict:
    """
    Search indexed documents in the Qdrant vector database.
    Use this when the user asks about specific management commentary,
    guidance, or document-specific information.

    This is Step 1 of the document pipeline: check if we already have
    the answer indexed.

    Args:
        query:    Search query (e.g. "Infosys margin guidance Q4 2026").
        symbol:   Optional stock symbol to filter by (e.g. "INFY").
        doc_type: Optional doc type filter: "annual_report", "con_call",
                  "research_note", "filing", "webpage".
        top_k:    Number of results (default 5).

    Returns:
        List of relevant document chunks with content, metadata, and scores.
    """
    logger.info("doc_search: query='%s', symbol=%s, doc_type=%s", query, symbol, doc_type)

    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = _get_qdrant()

        # Embed the query
        query_vector = _embed_texts([query])[0]

        # Build filter
        must_conditions = []
        if symbol:
            must_conditions.append(
                FieldCondition(key="symbol", match=MatchValue(value=symbol.strip().upper()))
            )
        if doc_type:
            must_conditions.append(
                FieldCondition(key="doc_type", match=MatchValue(value=doc_type))
            )

        search_filter = Filter(must=must_conditions) if must_conditions else None

        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            query_filter=search_filter,
        )

        if not results:
            return {
                "error": False,
                "data": {
                    "query": query,
                    "total_results": 0,
                    "results": [],
                    "note": "No indexed documents found. Use doc_ingest_pdf or doc_fetch_annual_report to index documents first.",
                },
            }

        chunks = []
        for r in results:
            chunks.append({
                "content": r.payload.get("text", ""),
                "symbol": r.payload.get("symbol"),
                "doc_type": r.payload.get("doc_type"),
                "source": r.payload.get("source"),
                "chunk_index": r.payload.get("chunk_index"),
                "date": r.payload.get("date"),
                "score": round(r.score, 4),
            })

        logger.info("doc_search OK: %d results", len(chunks))
        return {
            "error": False,
            "data": {
                "query": query,
                "total_results": len(chunks),
                "results": chunks,
            },
        }

    except Exception as exc:
        logger.error("doc_search failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: doc_ingest_pdf
# ---------------------------------------------------------------------------
@mcp.tool
def doc_ingest_pdf(
    pdf_path: str,
    symbol: str | None = None,
    doc_type: str = "annual_report",
    date_str: str | None = None,
) -> dict:
    """
    Ingest a PDF file into the Qdrant vector database.
    Extracts text, chunks it, embeds, and stores for future searches.

    Args:
        pdf_path: Absolute path to the PDF file.
        symbol:   Optional stock symbol this document relates to (e.g. "RELIANCE").
        doc_type: Document type: "annual_report", "con_call", "research_note", "filing".
        date_str: Optional date string (YYYY-MM-DD) of the document.

    Returns:
        dict with: total chunks indexed, document ID.
    """
    normalized_symbol = symbol.strip().upper() if symbol else None
    logger.info("doc_ingest_pdf: %s, symbol=%s, type=%s", pdf_path, normalized_symbol, doc_type)

    try:
        from qdrant_client.models import PointStruct
        import uuid

        # Extract text
        text = _extract_pdf_text(pdf_path)
        if not text.strip():
            return {"error": True, "message": "PDF is empty or could not be read."}

        # Chunk
        chunks = _chunk_text(text)
        if not chunks:
            return {"error": True, "message": "No content chunks generated."}

        # Embed
        embeddings = _embed_texts(chunks)

        # Store in Qdrant
        client = _get_qdrant()
        points = []
        doc_id = _doc_id(pdf_path, normalized_symbol)

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "text": chunk,
                        "symbol": normalized_symbol,
                        "doc_type": doc_type,
                        "source": pdf_path,
                        "doc_id": doc_id,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "date": date_str or datetime.now().strftime("%Y-%m-%d"),
                        "indexed_at": datetime.now().isoformat(),
                    },
                )
            )

        # Upsert in batches of 100
        for i in range(0, len(points), 100):
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[i : i + 100],
            )

        logger.info("doc_ingest_pdf OK: %d chunks indexed for %s", len(chunks), normalized_symbol or "UNKNOWN")
        return {
            "error": False,
            "data": {
                "symbol": normalized_symbol,
                "doc_type": doc_type,
                "source": pdf_path,
                "doc_id": doc_id,
                "total_chunks": len(chunks),
                "total_characters": len(text),
            },
        }

    except Exception as exc:
        logger.error("doc_ingest_pdf failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: doc_ingest_url
# ---------------------------------------------------------------------------
@mcp.tool
def doc_ingest_url(
    url: str,
    symbol: str | None = None,
    doc_type: str = "webpage",
    date_str: str | None = None,
) -> dict:
    """
    Extract content from a URL using Tavily, chunk it, and index in Qdrant.
    This is Step 3 (fallback) of the pipeline — when no PDF is available,
    scrape the webpage directly.

    Args:
        url:      URL to extract and index.
        symbol:   Optional stock symbol this content relates to.
        doc_type: Document type: "webpage", "con_call", "research_note", "article".
        date_str: Optional date string.

    Returns:
        dict with: total chunks indexed, source URL.
    """
    normalized_symbol = symbol.strip().upper() if symbol else None
    logger.info("doc_ingest_url: %s, symbol=%s", url, normalized_symbol)

    try:
        from qdrant_client.models import PointStruct
        from tavily import TavilyClient
        import uuid

        # Step 1: Extract content using Tavily
        if not TAVILY_API_KEY:
            return {"error": True, "message": "TAVILY_API_KEY not configured."}

        client = TavilyClient(api_key=TAVILY_API_KEY)
        response = client.extract(urls=[url], extract_depth="advanced")

        results = response.get("results", [])
        if not results:
            return {"error": True, "message": f"Could not extract content from {url}"}

        text = results[0].get("raw_content", "")
        if not text.strip():
            return {"error": True, "message": "Extracted content is empty."}

        # Step 2: Chunk
        chunks = _chunk_text(text)

        # Step 3: Embed and store
        embeddings = _embed_texts(chunks)
        qdrant = _get_qdrant()
        points = []
        doc_id = _doc_id(url, normalized_symbol)

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "text": chunk,
                        "symbol": normalized_symbol,
                        "doc_type": doc_type,
                        "source": url,
                        "doc_id": doc_id,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "date": date_str or datetime.now().strftime("%Y-%m-%d"),
                        "indexed_at": datetime.now().isoformat(),
                    },
                )
            )

        for i in range(0, len(points), 100):
            qdrant.upsert(
                collection_name=COLLECTION_NAME,
                points=points[i : i + 100],
            )

        logger.info("doc_ingest_url OK: %d chunks from %s", len(chunks), url)
        return {
            "error": False,
            "data": {
                "symbol": normalized_symbol,
                "doc_type": doc_type,
                "source": url,
                "doc_id": doc_id,
                "total_chunks": len(chunks),
            },
        }

    except Exception as exc:
        logger.error("doc_ingest_url failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: doc_fetch_annual_report
# ---------------------------------------------------------------------------
@mcp.tool
def doc_fetch_annual_report(symbol: str) -> dict:
    """
    Auto-fetch the latest annual report from NSE for a company,
    download the PDF, extract text, chunk, and index in Qdrant.

    This implements Step 2 of the pipeline — auto-fetching from NSE.

    Args:
        symbol: NSE stock symbol (e.g. "HDFCBANK", "RELIANCE").

    Returns:
        dict with: annual report URLs found, indexing status.
    """
    symbol = symbol.strip().upper()
    logger.info("doc_fetch_annual_report: %s", symbol)

    try:
        from nse import NSE

        os.makedirs(_download_dir, exist_ok=True)
        nse = NSE(_download_dir)

        # Get annual report list from NSE
        reports = nse.annual_reports(symbol=symbol)
        report_data = reports.get("data", [])

        if not report_data:
            return {
                "error": True,
                "message": f"No annual reports found on NSE for '{symbol}'. "
                           "Try doc_ingest_url with a direct link instead.",
            }

        # Get the latest report
        latest = report_data[0]
        report_url = latest.get("fileName", "")

        if not report_url:
            return {"error": True, "message": "Report URL not found in NSE data."}

        # Download the PDF
        try:
            saved_path = nse.download_document(report_url, folder=_download_dir)
            saved_path = str(saved_path)
        except Exception as dl_err:
            return {
                "error": False,
                "data": {
                    "symbol": symbol,
                    "status": "url_found_but_download_failed",
                    "report_url": report_url,
                    "download_error": str(dl_err),
                    "suggestion": f"Use doc_ingest_url('{report_url}', '{symbol}', 'annual_report') to extract content via Tavily instead.",
                    "all_reports": [
                        {"year": r.get("year"), "url": r.get("fileName")}
                        for r in report_data[:5]
                    ],
                },
            }

        # Ingest the downloaded PDF
        result = doc_ingest_pdf(
            pdf_path=saved_path,
            symbol=symbol,
            doc_type="annual_report",
        )

        if result.get("error"):
            return result

        result["data"]["report_url"] = report_url
        result["data"]["all_reports_count"] = len(report_data)

        logger.info("doc_fetch_annual_report OK: %s - %d chunks", symbol, result["data"]["total_chunks"])
        return result

    except Exception as exc:
        logger.error("doc_fetch_annual_report failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: doc_compare_offer_documents
# ---------------------------------------------------------------------------
@mcp.tool
def doc_compare_offer_documents(
    company_name: str,
    include_doc_types: list[str] | None = None,
) -> dict:
    """
    Retrieve and compare a company's DRHP, RHP, and prospectus documents.

    This is designed for version-comparison questions such as:
    "What changed from DRHP to RHP to prospectus?"

    Args:
        company_name: Company name as mentioned by the user.
        include_doc_types: Optional subset of ["drhp", "rhp", "prospectus"].

    Returns:
        Structured comparison payload with discovered URLs, extracted text stats,
        section matrix, and transition notes.
    """
    logger.info("doc_compare_offer_documents: %s", company_name)

    try:
        requested_doc_types = include_doc_types or ["drhp", "rhp", "prospectus"]
        requested_doc_types = [doc_type.lower() for doc_type in requested_doc_types if doc_type.lower() in DOC_SEARCH_CONFIG]
        if not requested_doc_types:
            return {"error": True, "message": "Provide at least one valid document type: drhp, rhp, prospectus."}

        tavily = _get_tavily_client()
        documents: list[dict[str, Any]] = []
        not_found: list[str] = []

        for doc_type in requested_doc_types:
            search_config = DOC_SEARCH_CONFIG[doc_type]
            query = f"\"{company_name}\" {search_config['query']}"
            search_response = tavily.search(
                query=query,
                max_results=5,
                search_depth="advanced",
                include_answer=False,
                topic="finance",
                include_domains=[
                    "sebi.gov.in",
                    "nseindia.com",
                    "bseindia.com",
                    "chittorgarh.com",
                    "investorgain.com",
                    "topsharebrokers.com",
                ],
            )

            candidates = []
            for result in search_response.get("results", []):
                title = result.get("title") or ""
                url = result.get("url") or ""
                snippet = result.get("content") or ""
                if not url:
                    continue
                candidates.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet[:400],
                    "score": _score_document_candidate(company_name, doc_type, title, url, snippet, result.get("score")),
                })

            candidates.sort(key=lambda item: item["score"], reverse=True)
            if not candidates:
                not_found.append(doc_type)
                continue

            best = candidates[0]
            extract_response = tavily.extract(urls=[best["url"]], extract_depth="advanced")
            extracted_results = extract_response.get("results", [])
            if not extracted_results:
                not_found.append(doc_type)
                continue

            raw_text = extracted_results[0].get("raw_content", "") or ""
            sections = _extract_named_sections(raw_text)
            documents.append({
                "doc_type": doc_type,
                "title": best["title"],
                "url": best["url"],
                "domain": _hostname(best["url"]),
                "text_length": len(raw_text),
                "search_query": query,
                "top_candidates": candidates[:3],
                "sections": sections,
                "preview": " ".join(raw_text.split())[:1600],
            })

        section_matrix: dict[str, dict[str, Any]] = {}
        for section_name in SECTION_ALIASES:
            section_matrix[section_name] = {}
            for document in documents:
                section_matrix[section_name][document["doc_type"]] = {
                    "present": document["sections"].get(section_name, {}).get("present", False),
                    "section_length": document["sections"].get(section_name, {}).get("section_length", 0),
                    "excerpt": document["sections"].get(section_name, {}).get("excerpt", ""),
                }

        return {
            "error": False,
            "data": {
                "company_name": company_name,
                "requested_doc_types": requested_doc_types,
                "documents_found": [document["doc_type"] for document in documents],
                "documents_not_found": not_found,
                "documents": documents,
                "section_matrix": section_matrix,
                "transition_notes": _build_transition_notes(documents),
            },
        }

    except Exception as exc:
        logger.error("doc_compare_offer_documents failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: doc_list_collections
# ---------------------------------------------------------------------------
@mcp.tool
def doc_list_collections() -> dict:
    """
    List all document collections and their stats in Qdrant.

    Returns:
        dict with: collection names, point counts, vector dimensions.
    """
    logger.info("doc_list_collections")

    try:
        client = _get_qdrant()
        collections = client.get_collections().collections

        info = []
        for c in collections:
            detail = client.get_collection(c.name)
            info.append({
                "name": c.name,
                "points_count": detail.points_count,
                "vectors_count": detail.vectors_count,
                "status": str(detail.status),
            })

        return {"error": False, "data": {"collections": info}}

    except Exception as exc:
        logger.error("doc_list_collections failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting ORACLE Document Pipeline MCP Server ...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8004)
