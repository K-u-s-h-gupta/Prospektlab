"""Run full Qdrant document index — run as: PYTHONPATH=/app python3 run_qdrant_index.py"""
import asyncio
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from finagent.graphrag.qdrant_indexer import index_document_sections_to_qdrant

result = asyncio.run(
    index_document_sections_to_qdrant(
        materialize=True,
        # No limit — index all 42k rows
    )
)
out = {k: v for k, v in result.items() if k != "materialized"}
print(json.dumps(out, indent=2))
