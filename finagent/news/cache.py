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
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS news_cache (
                cache_key TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT '',
                results TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_news_cache_source ON news_cache(source, fetched_at);
            """
        )


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
    """Store results in cache."""
    _ensure_db()
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        conn.execute(
            """
            INSERT INTO news_cache (cache_key, source, results, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                source=excluded.source,
                results=excluded.results,
                fetched_at=excluded.fetched_at
            """,
            (cache_key, source, json.dumps(results), datetime.now(timezone.utc).isoformat()),
        )


def cache_clear_source(source: str) -> int:
    """Clear all cache entries for a source."""
    _ensure_db()
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        cur = conn.execute("DELETE FROM news_cache WHERE source = ?", (source,))
        return cur.rowcount
