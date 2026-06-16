"""Index Supabase IKG document sections into Qdrant."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from typing import Any

from finagent.graphrag.qdrant_store import (
    embed_texts,
    ensure_collection,
    fetch_document_sections,
    get_qdrant_config,
    upsert_sections,
)
from finagent.graphrag.section_materializer import materialize_document_sections
from finagent.ikg.db import get_database_url

logger = logging.getLogger("finagent.graphrag.qdrant_indexer")


async def index_document_sections_to_qdrant(
    *,
    database_url: str | None = None,
    limit: int | None = None,
    batch_size: int | None = None,
    recreate: bool = False,
    since: str | None = None,
    company_symbol: str | None = None,
    document_type: str | None = None,
    materialize: bool = True,
) -> dict[str, Any]:
    """Materialize source docs and index canonical document_sections into Qdrant."""
    started = time.time()
    if batch_size is None:
        batch_size = int(os.getenv("FINAGENT_QDRANT_INDEX_BATCH_SIZE", "8") or "8")
    batch_size = max(1, batch_size)
    dynamic_batch_size = batch_size
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "No Supabase/Postgres database URL configured"}

    materialized: dict[str, Any] = {}
    if materialize:
        materialized = materialize_document_sections(database_url=db_url, limit=limit)

    collection = ensure_collection(recreate=recreate)
    rows = fetch_document_sections(
        database_url=db_url,
        limit=limit,
        since=since,
        company_symbol=company_symbol,
        document_type=document_type,
    )
    indexed = 0
    skipped = 0
    # Inter-batch delay to avoid OpenAI embedding TPM rate limits (40k TPM for
    # text-embedding-3-small). The inner-loop delay inside embed_texts() only fires
    # when a single embed_texts() call contains >batch_size texts; since we slice
    # exactly batch_size rows per call the inner loop runs once and the delay never
    # triggers. We apply it here at the outer loop level instead.
    inter_batch_delay_s = max(0.0, float(os.getenv("FINAGENT_EMBEDDING_BATCH_DELAY_S", "8.0") or "8.0"))

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts: list[str] = []
        effective_rows: list[dict[str, Any]] = []
        for row in batch:
            text = str(row.get("text") or "").strip()
            tables = str(row.get("tables_markdown") or "").strip()
            combined = text if text else tables
            if len(combined) < int(os.getenv("FINAGENT_QDRANT_MIN_TEXT_CHARS", "80")):
                skipped += 1
                continue
            texts.append(combined)
            effective_rows.append(row)
        if not effective_rows:
            continue
        # Throttle after the first batch to stay within TPM limits
        if start > 0 and inter_batch_delay_s > 0:
            await asyncio.sleep(inter_batch_delay_s)
        while True:
            try:
                embeddings = await embed_texts(texts, batch_size=max(1, min(dynamic_batch_size, len(texts))))
                if dynamic_batch_size < batch_size and os.getenv("FINAGENT_EMBEDDING_GROW_AFTER_SUCCESS", "1").strip().lower() in {"1", "true", "yes", "on"}:
                    dynamic_batch_size = min(batch_size, dynamic_batch_size + 1)
                break
            except Exception as exc:
                error_text = str(exc).lower()
                rate_limited = "rate limit" in error_text or "429" in error_text or "tpm" in error_text
                shrink_on_429 = os.getenv("FINAGENT_EMBEDDING_SHRINK_ON_429", "1").strip().lower() in {"1", "true", "yes", "on"}
                if rate_limited and shrink_on_429 and dynamic_batch_size > 1 and len(texts) > 1:
                    dynamic_batch_size = max(1, dynamic_batch_size // 2)
                    logger.warning(
                        "Qdrant embedding batch rate-limited; shrinking batch_size to %d and retrying",
                        dynamic_batch_size,
                    )
                    await asyncio.sleep(inter_batch_delay_s or 1.0)
                    continue
                raise
        indexed += upsert_sections(effective_rows, embeddings)
        logger.info(
            "Qdrant indexing progress: indexed=%d/%d skipped=%d collection=%s batch_size=%d",
            indexed,
            len(rows),
            skipped,
            get_qdrant_config().collection,
            dynamic_batch_size,
        )

    return {
        "success": True,
        "collection": collection.get("collection"),
        "rows_seen": len(rows),
        "indexed": indexed,
        "skipped": skipped,
        "materialized": materialized,
        "duration_s": round(time.time() - started, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Index IKG document_sections into Qdrant")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--reindex", action="store_true", help="Recreate Qdrant collection before indexing")
    parser.add_argument("--since", default=None, help="Only index document_sections updated after this timestamp")
    parser.add_argument("--company-symbol", default=None)
    parser.add_argument("--document-type", default=None)
    parser.add_argument("--skip-materialize", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = asyncio.run(
        index_document_sections_to_qdrant(
            limit=args.limit,
            batch_size=args.batch_size,
            recreate=args.reindex,
            since=args.since,
            company_symbol=args.company_symbol,
            document_type=args.document_type,
            materialize=not args.skip_materialize,
        )
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
