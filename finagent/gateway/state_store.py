"""Local SQLite state store for rate limiting, verification codes, pending extractions, and token revocation.

Uses the existing WAL-mode SQLite pattern so it survives restarts and provides
durable, non-Redis shared state within a single host. Supabase-backed
functions in supabase_client.py fall back to this store when Supabase is
unavailable or the tables are not yet created.

Thread safety: each public function opens a fresh connection. SQLite
WAL mode handles concurrent readers; writers serialize on the WAL lock.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from finagent.paths import finagent_data_path
from finagent.storage.sqlite import connect_wal

logger = logging.getLogger("finagent.gateway.state")


def _state_db_path() -> Path:
    return finagent_data_path("state.sqlite3")


def _init_state_db() -> None:
    path = _state_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_wal(path, timeout=5.0) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rate_limits (
                key TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0,
                window_start REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verification_codes (
                email TEXT NOT NULL,
                code TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'signup',
                created_at REAL NOT NULL,
                PRIMARY KEY (email, type)
            );

            CREATE TABLE IF NOT EXISTS pending_extractions (
                review_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS revoked_tokens (
                jti TEXT PRIMARY KEY,
                revoked_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pending_tenant
            ON pending_extractions(tenant_id);
            """
        )


# ── Rate limiting ──────────────────────────────────────────────────────────

def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Atomically check and increment a rate limit counter.
    Returns True if the request is allowed, False if the limit is exceeded.
    """
    _init_state_db()
    now = time.time()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        # Purge expired windows
        conn.execute("DELETE FROM rate_limits WHERE window_start < ?", (now - window_seconds,))
        row = conn.execute(
            "SELECT count, window_start FROM rate_limits WHERE key = ?", (key,)
        ).fetchone()
        if row:
            count, window_start = row
            if now - window_start < window_seconds:
                if count >= limit:
                    return False
                conn.execute(
                    "UPDATE rate_limits SET count = count + 1 WHERE key = ?", (key,)
                )
                return True
        # New window
        conn.execute(
            "INSERT OR REPLACE INTO rate_limits (key, count, window_start) VALUES (?, 1, ?)",
            (key, now),
        )
        return True


# ── Verification codes ───────────────────────────────────────────────────

def store_verification_code(email: str, code: str, type_: str = "signup") -> None:
    _init_state_db()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO verification_codes (email, code, type, created_at) VALUES (?, ?, ?, ?)",
            (email.lower().strip(), code, type_, time.time()),
        )


def verify_and_consume_code(email: str, code: str, type_: str = "signup", ttl_seconds: int = 600) -> bool:
    _init_state_db()
    now = time.time()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        row = conn.execute(
            "SELECT code, created_at FROM verification_codes WHERE email = ? AND type = ?",
            (email.lower().strip(), type_),
        ).fetchone()
        if not row:
            return False
        stored_code, created_at = row
        if now - created_at > ttl_seconds:
            conn.execute(
                "DELETE FROM verification_codes WHERE email = ? AND type = ?",
                (email.lower().strip(), type_),
            )
            return False
        if stored_code != code.strip():
            return False
        conn.execute(
            "DELETE FROM verification_codes WHERE email = ? AND type = ?",
            (email.lower().strip(), type_),
        )
        return True


# ── Pending extractions ──────────────────────────────────────────────────

def store_pending_extraction(review_id: str, tenant_id: str, payload: dict[str, Any]) -> None:
    _init_state_db()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_extractions (review_id, tenant_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (review_id, tenant_id, json.dumps(payload), time.time()),
        )


def get_pending_extraction(review_id: str) -> dict[str, Any] | None:
    _init_state_db()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        row = conn.execute(
            "SELECT tenant_id, payload_json FROM pending_extractions WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        if not row:
            return None
        return {"tenant_id": row[0], "extraction": json.loads(row[1])}


def get_pending_extractions_by_tenant(tenant_id: str) -> list[dict[str, Any]]:
    _init_state_db()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        rows = conn.execute(
            "SELECT review_id, payload_json FROM pending_extractions WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        return [{"review_id": r[0], **json.loads(r[1])} for r in rows]


def delete_pending_extraction(review_id: str) -> None:
    _init_state_db()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        conn.execute("DELETE FROM pending_extractions WHERE review_id = ?", (review_id,))


# ── Token revocation ─────────────────────────────────────────────────────

def is_token_revoked(jti: str) -> bool:
    _init_state_db()
    now = time.time()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now,))
        row = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()
        return row is not None


def revoke_token(jti: str, expires_at: float) -> None:
    _init_state_db()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO revoked_tokens (jti, revoked_at, expires_at) VALUES (?, ?, ?)",
            (jti, time.time(), expires_at),
        )


# ── Periodic cleanup ─────────────────────────────────────────────────────

def cleanup_old_state(ttl_seconds: int = 3600) -> None:
    """Call periodically to purge old verification codes and pending extractions.
    Also cleans expired rate-limit windows and revoked tokens.
    """
    _init_state_db()
    now = time.time()
    with connect_wal(_state_db_path(), timeout=5.0) as conn:
        # Verification codes older than TTL
        cur = conn.execute("DELETE FROM verification_codes WHERE created_at < ?", (now - ttl_seconds,))
        if cur.rowcount:
            logger.info("Cleaned %d expired verification codes", cur.rowcount)
        # Pending extractions older than 24 hours
        cur = conn.execute("DELETE FROM pending_extractions WHERE created_at < ?", (now - 86400,))
        if cur.rowcount:
            logger.info("Cleaned %d expired pending extractions", cur.rowcount)
        # Rate limit windows (sweep is also done per-key, but this catches stragglers)
        cur = conn.execute("DELETE FROM rate_limits WHERE window_start < ?", (now - 3600,))
        if cur.rowcount:
            logger.info("Cleaned %d stale rate-limit windows", cur.rowcount)
        # Expired revoked tokens
        cur = conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now,))
        if cur.rowcount:
            logger.info("Cleaned %d expired revoked tokens", cur.rowcount)
