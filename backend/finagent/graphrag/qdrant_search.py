"""CLI helpers for Qdrant + Postgres IKG retrieval."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from finagent.graphrag.qdrant_store import check_qdrant, hybrid_search_sections


async def _search(args: argparse.Namespace) -> dict:
    hits = await hybrid_search_sections(
        args.query,
        top_k=args.top_k,
        company_cin=args.company_cin,
        nse_symbol=args.symbol,
        document_type=args.document_type,
    )
    return {"ok": True, "query": args.query, "hits": hits}


def main() -> None:
    parser = argparse.ArgumentParser(description="Search IKG sections using Qdrant + Postgres FTS")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--query", default="")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--company-cin", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--document-type", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.health:
        print(json.dumps(check_qdrant(), indent=2, default=str))
        return
    if not args.query.strip():
        parser.error("--query is required unless --health is used")
    print(json.dumps(asyncio.run(_search(args)), indent=2, default=str))


if __name__ == "__main__":
    main()
