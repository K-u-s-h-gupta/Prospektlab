"""Dreaming Worker — nightly offline curation background task.

Orchestrates the complete dreaming pipeline:
  1. Pattern detection (pledge spikes, director exodus, price anomalies)
  2. Memory consolidation (extract verified claims from recent sessions)
  3. Stale memory eviction (remove memories older than TTL)
  4. Per-ticker summary pre-computation (warm the cache)

Designed to run as a background thread during low-traffic hours (2-4 AM IST).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("finagent.dreaming.worker")

_DATABASE_URL = os.getenv("IKG_DATABASE_URL") or os.getenv("DATABASE_URL", "")


async def run_dreaming_cycle(
    database_url: str | None = None,
    memory_store: Any | None = None,
) -> dict[str, Any]:
    """Run the full nightly dreaming cycle.

    Args:
        database_url: PostgreSQL connection string.
        memory_store: ProspektTieredMemoryStore instance (optional).

    Returns:
        dict with run statistics and detected patterns.
    """
    db_url = database_url or _DATABASE_URL
    start_t = time.time()
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results: dict[str, Any] = {
        "started_at": started_at,
        "patterns_detected": {},
        "refresh_hints_created": 0,
        "stale_memories_evicted": 0,
        "errors": [],
    }

    logger.info("[DREAMING] Starting nightly dreaming cycle at %s", started_at)

    # Step 1: Pattern detection
    try:
        from finagent.dreaming.pattern_detector import run_all_pattern_detectors
        from finagent.ikg.service import get_ikg_service

        patterns = await run_all_pattern_detectors(db_url)
        results["patterns_detected"] = {k: len(v) for k, v in patterns.items()}
        ikg_service = get_ikg_service()
        created_hints = 0
        for pattern_name, rows in patterns.items():
            for row in rows[:25]:
                entity_id = None
                if row.get("cin"):
                    entity_id = f"company:{row['cin']}"
                elif row.get("scrip_code"):
                    entity_id = str(row["scrip_code"])
                response = await ikg_service.create_refresh_hint(
                    entity_id=entity_id,
                    reason=f"Dreaming pattern detected: {pattern_name}",
                    priority="high" if pattern_name in {"pledge_spikes", "director_exodus"} else "normal",
                    source_type="dreaming_pattern_detector",
                    metadata=row,
                )
                if response.get("status") == "ok":
                    created_hints += 1
        results["refresh_hints_created"] = created_hints
        logger.info("[DREAMING] Patterns: %s", results["patterns_detected"])
    except Exception as exc:
        logger.error("[DREAMING] Pattern detection failed: %s", exc)
        results["errors"].append(f"pattern_detection: {exc}")

    # Step 2: Stale memory eviction (if memory store available)
    if memory_store:
        try:
            evicted = await _evict_stale_memories(memory_store)
            results["stale_memories_evicted"] = evicted
            logger.info("[DREAMING] Evicted %d stale memories", evicted)
        except Exception as exc:
            logger.error("[DREAMING] Memory eviction failed: %s", exc)
            results["errors"].append(f"memory_eviction: {exc}")

    # Step 3: Health check on pipeline data freshness
    try:
        from finagent.ikg.pipeline.orchestrator import get_pipeline_health
        health = get_pipeline_health(db_url)
        results["pipeline_health"] = health.get("status", "unknown")
        if health.get("alerts"):
            logger.warning("[DREAMING] Pipeline health alerts: %s", health["alerts"])
            results["pipeline_alerts"] = health["alerts"]
    except Exception as exc:
        logger.debug("[DREAMING] Health check unavailable: %s", exc)

    duration = round(time.time() - start_t, 2)
    results["duration_s"] = duration
    results["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info("[DREAMING] Nightly cycle complete in %.1fs. Results: %s", duration, results)
    return results


async def _evict_stale_memories(memory_store: Any) -> int:
    """Evict expired memories from the tiered store.

    Calls memory_store.evict_expired() which should remove memories
    whose expires_at timestamp has passed.

    Returns:
        Number of memories evicted.
    """
    try:
        # Check if the memory store has an evict method
        if hasattr(memory_store, "evict_expired"):
            evicted = await memory_store.evict_expired()
            return evicted or 0
        elif hasattr(memory_store, "archive_expired"):
            evicted = await memory_store.archive_expired()
            return evicted or 0
    except Exception as exc:
        logger.warning("[DREAMING] Memory eviction error: %s", exc)
    return 0


def run_dreaming_in_thread(
    database_url: str | None = None,
    memory_store: Any | None = None,
) -> dict[str, Any]:
    """Run the dreaming cycle synchronously in a background thread.

    Use this when calling from a non-async context (e.g., APScheduler job).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        run_dreaming_cycle(database_url=database_url, memory_store=memory_store)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_dreaming_in_thread()
    print(result)
