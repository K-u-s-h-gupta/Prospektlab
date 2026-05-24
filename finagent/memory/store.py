"""SQLite-backed memory store with FTS5 search.

Design goals (modelled on Hermes' `hermes_state.py`):
- Single file under the FinAgent home directory (`FINAGENT_HOME` or the
  runtime default). Cheap, durable, no server.
- One row per *fact*. A fact is "thing the agent learned that's worth
  remembering next time". Examples: "NVDA fiscal year ends January",
  "AAPL has a $90B annual buyback program", "MSTR holds 214,400 BTC".
- FTS5 virtual table for fuzzy search across the full body.
- `target_key` is the canonical normalized identifier (ticker symbol or
  lowercased company name). All recall is keyed by this.
- `kind` lets us bucket facts (financial, risk, sentiment, news_event,
  competitive, governance, etc.) for filtered recall.
- `confidence` is HIGH / MEDIUM / LOW and biases recall ranking.
- `source_url` is mandatory for high-confidence facts.

Thread safety: each method opens a fresh connection. SQLite handles the
locking with WAL mode enabled at init.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.memory")

_DEFAULT_DB = finagent_data_path("memory.sqlite3")
_init_lock = threading.Lock()


@dataclass
class MemoryFact:
    target_key: str
    kind: str  # financial | risk | sentiment | news_event | competitive | governance | identity | other
    body: str
    confidence: str  # HIGH | MEDIUM | LOW
    source_url: str | None = None
    session_id: str | None = None
    user_email: str | None = None
    created_at: float = 0.0
    score: float = 0.0  # BM25 rank when returned by recall()

    def to_dict(self) -> dict:
        return {
            "target_key": self.target_key,
            "kind": self.kind,
            "body": self.body,
            "confidence": self.confidence,
            "source_url": self.source_url,
            "session_id": self.session_id,
            "user_email": self.user_email,
            "created_at": self.created_at,
            "score": self.score,
        }


def normalize_target(s: str) -> str:
    s = (s or "").strip().lower()
    # Strip common corporate suffixes so "NVIDIA Corporation" and "nvidia"
    # land in the same memory bucket.
    s = re.sub(
        r"\s+(corporation|corp\.?|incorporated|inc\.?|company|co\.?|plc|ltd\.?|limited|holdings)$",
        "",
        s,
    )
    return s.strip()


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    confidence TEXT NOT NULL,
    source_url TEXT,
    session_id TEXT,
    user_email TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_target ON facts(target_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(target_key, kind);
CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_email, target_key, created_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    body,
    content='facts',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, body) VALUES (new.id, new.body);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, body) VALUES('delete', old.id, old.body);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, body) VALUES('delete', old.id, old.body);
    INSERT INTO facts_fts(rowid, body) VALUES (new.id, new.body);
END;

CREATE TABLE IF NOT EXISTS session_summaries (
    session_id TEXT PRIMARY KEY,
    target_key TEXT NOT NULL,
    target_display TEXT,
    summary TEXT NOT NULL,
    metrics_json TEXT,
    citation_count INTEGER,
    quality_score REAL,
    user_email TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summaries_target ON session_summaries(target_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_user ON session_summaries(user_email, target_key, created_at DESC);
"""


class MemoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _init_lock:
            # On a legacy DB the tables exist but may lack user_email,
            # so the CREATE INDEX in _SCHEMA referencing that column will
            # fail.  We try init first (works for fresh DBs); if it blows
            # up we migrate and retry.
            try:
                self._init_schema()
            except sqlite3.OperationalError as exc:
                if "no such column" in str(exc).lower():
                    self._migrate_schema()
                    self._init_schema()
                else:
                    raise
            # One more migration pass for any future column additions.
            self._migrate_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), timeout=10.0)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _migrate_schema(self) -> None:
        """Add user_email columns to legacy databases that lack them."""
        with self._conn() as c:
            # facts table
            try:
                facts_cols = {r[1] for r in c.execute("PRAGMA table_info(facts)")}
            except sqlite3.OperationalError:
                facts_cols = set()
            if "user_email" not in facts_cols:
                try:
                    c.execute("ALTER TABLE facts ADD COLUMN user_email TEXT")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_email, target_key, created_at DESC)")
                    logger.info("[MEMORY-MIGRATE] Added user_email column to facts table")
                except sqlite3.OperationalError:
                    pass  # Table doesn't exist yet (fresh DB) or already migrated
            # session_summaries table
            try:
                sum_cols = {r[1] for r in c.execute("PRAGMA table_info(session_summaries)")}
            except sqlite3.OperationalError:
                sum_cols = set()
            if "user_email" not in sum_cols:
                try:
                    c.execute("ALTER TABLE session_summaries ADD COLUMN user_email TEXT")
                    c.execute("CREATE INDEX IF NOT EXISTS idx_summaries_user ON session_summaries(user_email, target_key, created_at DESC)")
                    logger.info("[MEMORY-MIGRATE] Added user_email column to session_summaries table")
                except sqlite3.OperationalError:
                    pass  # Table doesn't exist yet (fresh DB) or already migrated

    # ── Writers ────────────────────────────────────────────────────────────
    def remember(self, fact: MemoryFact) -> int:
        if not fact.body or not fact.body.strip():
            return 0
        if not fact.created_at:
            fact.created_at = time.time()
        target = normalize_target(fact.target_key)
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO facts(target_key, kind, body, confidence, source_url, session_id, user_email, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (target, fact.kind, fact.body.strip(), fact.confidence, fact.source_url, fact.session_id, fact.user_email, fact.created_at),
            )
            return int(cur.lastrowid or 0)

    def remember_many(self, facts: Iterable[MemoryFact]) -> int:
        count = 0
        for f in facts:
            if self.remember(f):
                count += 1
        return count

    def save_session_summary(
        self,
        *,
        session_id: str,
        target_key: str,
        target_display: str,
        summary: str,
        metrics: dict | None = None,
        citation_count: int = 0,
        quality_score: float = 0.0,
        user_email: str | None = None,
    ) -> None:
        target = normalize_target(target_key)
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO session_summaries(session_id, target_key, target_display, "
                "summary, metrics_json, citation_count, quality_score, user_email, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    target,
                    target_display,
                    summary,
                    json.dumps(metrics or {}),
                    citation_count,
                    quality_score,
                    user_email,
                    time.time(),
                ),
            )

    # ── Readers ────────────────────────────────────────────────────────────
    def recall(
        self,
        target_key: str,
        *,
        kind: str | None = None,
        limit: int = 20,
        query: str | None = None,
        user_email: str | None = None,
    ) -> list[MemoryFact]:
        """Return the most relevant prior facts for `target_key`.

        Recall ranking: HIGH confidence first, then newest. If `query`
        is provided, falls back to FTS5 BM25 ranking restricted to the
        target.
        """
        target = normalize_target(target_key)
        with self._conn() as c:
            user_clause = " AND f.user_email = ?" if user_email else ""
            params_base = [target]
            if user_email:
                params_base.append(user_email)

            if query:
                params = [query] + params_base + [limit]
                rows = c.execute(
                    f"""
                    SELECT f.*, bm25(facts_fts) AS bm
                    FROM facts_fts
                    JOIN facts f ON f.id = facts_fts.rowid
                    WHERE facts_fts MATCH ? AND f.target_key = ?{user_clause}
                    ORDER BY bm ASC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
            elif kind:
                params = params_base + [kind, limit]
                rows = c.execute(
                    f"SELECT *, 0 AS bm FROM facts WHERE target_key = ?{user_clause} AND kind = ? "
                    "ORDER BY (confidence = 'HIGH') DESC, created_at DESC LIMIT ?",
                    params,
                ).fetchall()
            else:
                params = params_base + [limit]
                rows = c.execute(
                    f"SELECT *, 0 AS bm FROM facts WHERE target_key = ?{user_clause} "
                    "ORDER BY (confidence = 'HIGH') DESC, created_at DESC LIMIT ?",
                    params,
                ).fetchall()
        return [
            MemoryFact(
                target_key=r["target_key"],
                kind=r["kind"],
                body=r["body"],
                confidence=r["confidence"],
                source_url=r["source_url"],
                session_id=r["session_id"],
                user_email=r.get("user_email") if "user_email" in r.keys() else None,
                created_at=r["created_at"],
                score=float(r["bm"]),
            )
            for r in rows
        ]

    def last_summary(self, target_key: str, *, user_email: str | None = None) -> dict | None:
        target = normalize_target(target_key)
        with self._conn() as c:
            user_clause = " AND user_email = ?" if user_email else ""
            params = [target]
            if user_email:
                params.append(user_email)
            row = c.execute(
                f"SELECT * FROM session_summaries WHERE target_key = ?{user_clause} ORDER BY created_at DESC LIMIT 1",
                params,
            ).fetchone()
        if not row:
            return None
        return {
            "session_id": row["session_id"],
            "target_key": row["target_key"],
            "target_display": row["target_display"],
            "summary": row["summary"],
            "metrics": json.loads(row["metrics_json"] or "{}"),
            "citation_count": row["citation_count"],
            "quality_score": row["quality_score"],
            "user_email": row["user_email"] if "user_email" in row.keys() else None,
            "created_at": row["created_at"],
        }

    def count(self, target_key: str | None = None, *, user_email: str | None = None) -> int:
        with self._conn() as c:
            if target_key and user_email:
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM facts WHERE target_key = ? AND user_email = ?",
                    (normalize_target(target_key), user_email),
                ).fetchone()
            elif target_key:
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM facts WHERE target_key = ?",
                    (normalize_target(target_key),),
                ).fetchone()
            elif user_email:
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM facts WHERE user_email = ?",
                    (user_email,),
                ).fetchone()
            else:
                row = c.execute("SELECT COUNT(*) AS n FROM facts").fetchone()
        return int(row["n"] if row else 0)

    def clear_target(self, target_key: str, *, user_email: str | None = None) -> int:
        target = normalize_target(target_key)
        with self._conn() as c:
            if user_email:
                cur = c.execute(
                    "DELETE FROM facts WHERE target_key = ? AND user_email = ?",
                    (target, user_email),
                )
            else:
                cur = c.execute("DELETE FROM facts WHERE target_key = ?", (target,))
            return int(cur.rowcount or 0)

    def delete_session(self, session_id: str, *, user_email: str | None = None) -> dict[str, int]:
        with self._conn() as c:
            if user_email:
                fact_cur = c.execute(
                    "DELETE FROM facts WHERE session_id = ? AND user_email = ?",
                    (session_id, user_email),
                )
                summary_cur = c.execute(
                    "DELETE FROM session_summaries WHERE session_id = ? AND user_email = ?",
                    (session_id, user_email),
                )
            else:
                fact_cur = c.execute("DELETE FROM facts WHERE session_id = ?", (session_id,))
                summary_cur = c.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
            return {
                "facts": int(fact_cur.rowcount or 0),
                "summaries": int(summary_cur.rowcount or 0),
            }


_singleton: MemoryStore | None = None


def get_memory_store(db_path: Path | None = None) -> MemoryStore:
    """Return the per-process memory store singleton.

    Pass `db_path` to override for tests; subsequent calls without
    a path reuse the same store.
    """
    global _singleton
    if _singleton is None or db_path is not None:
        _singleton = MemoryStore(db_path)
    return _singleton
