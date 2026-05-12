"""
Test script for Research & News MCP Server (Tavily).
Run: python -m tests.test_research_server
Requires: TAVILY_API_KEY in .env
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_servers.research_server import (
    search_web,
    search_news,
    search_financial,
    extract_url,
)


def test_search_web():
    print("=" * 60)
    print("TEST: search_web('SEBI new regulations 2026')")
    print("=" * 60)
    result = search_web("SEBI new regulations 2026", max_results=3)
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['total_results']} results")
        if d.get("answer"):
            print(f"       Answer: {d['answer'][:150]}...")
        for r in d["results"][:2]:
            print(f"       - {r['title'][:60]}")
    else:
        print(f"  [WARN] {result['message'][:80]}")
    print()


def test_search_news():
    print("=" * 60)
    print("TEST: search_news('Indian stock market today')")
    print("=" * 60)
    result = search_news("Indian stock market today", max_results=5)
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['total_articles']} articles")
        for a in d["articles"][:3]:
            print(f"       - {a['title'][:60]}")
    else:
        print(f"  [WARN] {result['message'][:80]}")
    print()


def test_search_financial():
    print("=" * 60)
    print("TEST: search_financial('Reliance Industries Q4 results')")
    print("=" * 60)
    result = search_financial("Reliance Industries Q4 results 2026", max_results=3)
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] {d['total_results']} results")
        if d.get("answer"):
            print(f"       Answer: {d['answer'][:150]}...")
    else:
        print(f"  [WARN] {result['message'][:80]}")
    print()


def test_extract_url():
    print("=" * 60)
    print("TEST: extract_url(['https://screener.in/company/RELIANCE/'])")
    print("=" * 60)
    result = extract_url(["https://screener.in/company/RELIANCE/"])
    if not result.get("error"):
        d = result["data"]
        print(f"  [OK] Extracted {d['total_extracted']} URLs, {d['total_failed']} failed")
        if d["results"]:
            print(f"       Content length: {len(d['results'][0].get('content', ''))} chars")
    else:
        print(f"  [WARN] {result['message'][:80]}")
    print()


if __name__ == "__main__":
    print("\n>>> ORACLE Research & News MCP Server (Tavily) - Tests\n")

    test_search_web()
    test_search_news()
    test_search_financial()
    test_extract_url()

    print("[OK] All tests completed!")
