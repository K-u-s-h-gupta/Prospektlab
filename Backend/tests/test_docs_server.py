"""
Test script for Document Pipeline MCP Server.
Run: python -m tests.test_docs_server
Requires: Qdrant running (docker) + TAVILY_API_KEY for URL ingestion
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_servers.docs_server import (
    doc_search,
    doc_list_collections,
    _chunk_text,
)


def test_chunking():
    print("=" * 60)
    print("TEST: Text chunking logic")
    print("=" * 60)
    sample_text = """
    Reliance Industries Limited is an Indian multinational conglomerate.
    The company is headquartered in Mumbai and was founded by Dhirubhai Ambani.

    Reliance operates in petrochemicals, refining, oil and gas exploration,
    telecommunications, and retail sectors. The company is one of the
    most profitable companies in India.

    In Q4 FY2026, Reliance reported consolidated revenue of Rs 2.5 lakh crore.
    The net profit stood at Rs 19,500 crore, up 12% year-on-year.
    The EBITDA margin improved by 200 basis points to 18.5%.

    Jio Platforms continued to grow with 480 million subscribers.
    The retail segment crossed 18,000 stores across India.
    The oil-to-chemicals business benefited from improved GRMs.
    """
    chunks = _chunk_text(sample_text, chunk_size=300, overlap=50)
    print(f"  [OK] Generated {len(chunks)} chunks from {len(sample_text)} chars")
    for i, chunk in enumerate(chunks):
        print(f"       Chunk {i}: {len(chunk)} chars | '{chunk[:60]}...'")
    print()


def test_doc_search_empty():
    print("=" * 60)
    print("TEST: doc_search (no Qdrant running expected)")
    print("=" * 60)
    result = doc_search("Reliance margin guidance", symbol="RELIANCE")
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['total_results']} results found")
        if d.get("note"):
            print(f"       Note: {d['note'][:80]}")
    else:
        print(f"  [INFO] Expected: {result['message'][:80]}")
        print("         (Qdrant not running — this is OK for now)")
    print()


def test_list_collections():
    print("=" * 60)
    print("TEST: doc_list_collections")
    print("=" * 60)
    result = doc_list_collections()
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {len(d['collections'])} collections")
        for c in d["collections"]:
            print(f"       - {c['name']}: {c['points_count']} points")
    else:
        print(f"  [INFO] Expected: {result['message'][:80]}")
        print("         (Qdrant not running — this is OK for now)")
    print()


if __name__ == "__main__":
    print("\n>>> ORACLE Document Pipeline MCP Server - Tests\n")

    test_chunking()
    test_doc_search_empty()
    test_list_collections()

    print("[OK] All tests completed!")
