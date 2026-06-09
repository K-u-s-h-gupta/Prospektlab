"""Migrate legacy Supabase memory tables into Prospekt tiered memory.

This reads public.facts and public.session_summaries through Supabase
PostgREST, then writes them into the dedicated Core/Recall/Archival memory
database through the same adapter used at runtime. Supabase remains the source
only for user-operational data after this migration.

Required env:
  SUPABASE_URL
  SUPABASE_KEY
  MEMORY_DATABASE_URL

Optional env:
  MEMORY_BACKEND=prospekt_tiered
  MEMORY_VECTOR_DIM=1536
  MEMORY_IN_MEMORY=1  # tests only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finagent.gateway.supabase_client import _get_supabase_url, get_headers
from finagent.memory.store import normalize_target
from finagent.memory.tiered_store import ProspektTieredMemoryStore


def _coerce_epoch(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0


async def _fetch_batch(
    client: httpx.AsyncClient,
    table: str,
    *,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    url = f"{_get_supabase_url()}/rest/v1/{table}"
    params = {
        "select": "*",
        "order": "id.asc" if table == "facts" else "created_at.asc",
        "limit": limit,
        "offset": offset,
    }
    res = await client.get(url, headers=get_headers(), params=params)
    res.raise_for_status()
    data = res.json()
    return data if isinstance(data, list) else []


async def _migrate_facts(
    *,
    client: httpx.AsyncClient,
    memory: ProspektTieredMemoryStore,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    processed = 0
    inserted = 0
    skipped = 0
    offset = 0
    while True:
        rows = await _fetch_batch(client, "facts", offset=offset, limit=batch_size)
        if not rows:
            break
        for row in rows:
            processed += 1
            row_id = str(row.get("id") or "")
            user_email = str(row.get("user_email") or "").strip().lower()
            body = str(row.get("body") or "").strip()
            if not user_email or not body:
                skipped += 1
                continue
            if dry_run:
                inserted += 1
                continue
            ok = await memory.remember(
                target_key=normalize_target(str(row.get("target_key") or "")),
                kind=str(row.get("kind") or "other"),
                body=body,
                confidence=str(row.get("confidence") or "MEDIUM"),
                source_url=row.get("source_url"),
                session_id=row.get("session_id"),
                user_email=user_email,
                created_at=_coerce_epoch(row.get("created_at")) or None,
                legacy_source="supabase_facts",
                legacy_id=row_id or None,
                metadata={
                    "supabase_id": row_id or None,
                    "migration_source_table": "facts",
                },
            )
            inserted += int(ok or 0)
        offset += batch_size
    return {"processed": processed, "inserted": inserted, "skipped": skipped}


async def _migrate_summaries(
    *,
    client: httpx.AsyncClient,
    memory: ProspektTieredMemoryStore,
    batch_size: int,
    dry_run: bool,
) -> dict[str, int]:
    processed = 0
    inserted = 0
    skipped = 0
    offset = 0
    while True:
        rows = await _fetch_batch(client, "session_summaries", offset=offset, limit=batch_size)
        if not rows:
            break
        for row in rows:
            processed += 1
            session_id = str(row.get("session_id") or "")
            legacy_id = str(row.get("id") or session_id or "")
            user_email = str(row.get("user_email") or "").strip().lower()
            summary = str(row.get("summary") or "").strip()
            if not user_email or not session_id or not summary:
                skipped += 1
                continue
            metrics: dict[str, Any] = {}
            try:
                parsed = json.loads(row.get("metrics_json") or "{}")
                metrics = parsed if isinstance(parsed, dict) else {}
            except Exception:
                metrics = {}
            if dry_run:
                inserted += 1
                continue
            ok = await memory.save_session_summary(
                session_id=session_id,
                target_key=normalize_target(str(row.get("target_key") or "")),
                target_display=str(row.get("target_display") or ""),
                summary=summary,
                metrics=metrics,
                citation_count=int(row.get("citation_count") or 0),
                quality_score=float(row.get("quality_score") or 0.0),
                user_email=user_email,
                created_at=_coerce_epoch(row.get("created_at")) or None,
                legacy_source="supabase_session_summaries",
                legacy_id=legacy_id or None,
            )
            inserted += int(ok or 0)
        offset += batch_size
    return {"processed": processed, "inserted": inserted, "skipped": skipped}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Supabase memory tables to Prospekt tiered memory.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not _get_supabase_url():
        raise SystemExit("SUPABASE_URL is required")
    if not args.dry_run and not os.getenv("MEMORY_DATABASE_URL") and not os.getenv("MEMORY_IN_MEMORY"):
        raise SystemExit("MEMORY_DATABASE_URL is required unless MEMORY_IN_MEMORY=1")

    memory = ProspektTieredMemoryStore()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), trust_env=False) as client:
        facts = await _migrate_facts(
            client=client,
            memory=memory,
            batch_size=max(1, args.batch_size),
            dry_run=args.dry_run,
        )
        summaries = await _migrate_summaries(
            client=client,
            memory=memory,
            batch_size=max(1, args.batch_size),
            dry_run=args.dry_run,
        )

    print(json.dumps({"facts": facts, "session_summaries": summaries, "dry_run": args.dry_run}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
