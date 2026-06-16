"""News cache module.

SQLite-backed cache with per-source TTL.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("finagent.news.cache")

_CACHE_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "news_cache.sqlite3"


def _ensure_db() -> None:
    _CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        # Create minimal table if it doesn't exist (old DBs may have different schema)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS news_cache (
                cache_key TEXT PRIMARY KEY,
                results TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Run migration (adds source, cache_key, etc. and safe indexes)
        _migrate_news_cache_schema(conn)


def _migrate_news_cache_schema(conn: sqlite3.Connection) -> None:
    """Add missing columns for older versions of the news cache."""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(news_cache)").fetchall()}

        # Old schema used 'query_hash' instead of 'cache_key'
        if "query_hash" in cols and "cache_key" not in cols:
            try:
                conn.execute("ALTER TABLE news_cache ADD COLUMN cache_key TEXT")
                conn.execute("UPDATE news_cache SET cache_key = query_hash WHERE cache_key IS NULL")
            except Exception:
                pass

        if "source" not in cols:
            conn.execute("ALTER TABLE news_cache ADD COLUMN source TEXT NOT NULL DEFAULT ''")
            cols.add("source")

        if "fetched_at" not in cols:
            conn.execute("ALTER TABLE news_cache ADD COLUMN fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")

        # Safe index creation (only after source column exists)
        if "source" in cols:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_news_cache_source ON news_cache(source, fetched_at)")

        # Best-effort cleanup of very old rows that have neither key
        conn.execute("DELETE FROM news_cache WHERE cache_key IS NULL AND query_hash IS NULL")

    except Exception as e:
        logger.warning("News cache migration encountered issue (non-fatal): %s", e)


def cache_get(cache_key: str, ttl_minutes: int = 30, source: str = "") -> list[dict[str, Any]] | None:
    """Get cached results if within TTL."""
    _ensure_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)).isoformat()
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        row = conn.execute(
            "SELECT results FROM news_cache WHERE cache_key = ? AND source = ? AND fetched_at > ?",
            (cache_key, source, cutoff),
        ).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return None
    return None


def cache_set(cache_key: str, results: list[dict[str, Any]], source: str = "") -> None:
    """Store results in cache. Uses INSERT OR REPLACE for maximum compatibility across schema versions."""
    _ensure_db()
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO news_cache (cache_key, source, results, fetched_at)
            VALUES (?, ?, ?, ?)
            """,
            (cache_key, source, json.dumps(results), datetime.now(timezone.utc).isoformat()),
        )


def cache_clear_source(source: str) -> int:
    """Clear all cache entries for a source."""
    _ensure_db()
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        cur = conn.execute("DELETE FROM news_cache WHERE source = ?", (source,))
        return cur.rowcount
