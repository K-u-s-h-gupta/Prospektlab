"""ProspektLab internal tiered memory store.

This module replicates the useful parts of Letta's memory architecture without
depending on a Letta server. Supabase is intentionally not used for memory
reads or writes; production memory belongs in a dedicated Postgres database
with the schema in deployment/prospekt_memory_bootstrap.sql.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger("finagent.memory.tiered")

_MEMORY_BOOTSTRAP_PATH = Path(__file__).resolve().parents[2] / "deployment" / "prospekt_memory_bootstrap.sql"
_MEMORY_RUNTIME_PATCH_SQL = """
alter table if exists public.recall_memories
  add column if not exists expires_at timestamptz;
alter table if exists public.recall_memories
  add column if not exists expires_at_epoch double precision;
update public.recall_memories
set expires_at_epoch = extract(epoch from expires_at)
where expires_at is not null and expires_at_epoch is null;
"""
_MEMORY_BOOTSTRAP_LOCK = Lock()
_MEMORY_BOOTSTRAPPED_URLS: set[str] = set()
_MEMORY_RECALL_SCHEMA_CACHE: dict[str, "RecallMemorySchemaCapabilities"] = {}
_MEMORY_RECALL_SCHEMA_WARNED: set[str] = set()

RECALL_MEMORY_REQUIRED_COLUMNS = frozenset(
    {
        "user_email",
        "tenant_id",
        "target_key",
        "cin",
        "isin",
        "symbol",
        "kind",
        "body",
        "body_hash",
        "confidence",
        "source_url",
        "session_id",
        "session_key",
        "metadata_json",
        "legacy_source",
        "legacy_id",
        "created_at",
        "created_at_epoch",
        "expires_at",
        "expires_at_epoch",
    }
)
_RECALL_TIME_COLUMNS = frozenset({"created_at", "created_at_epoch", "expires_at", "expires_at_epoch"})


@dataclass(frozen=True)
class RecallMemorySchemaCapabilities:
    columns: frozenset[str]

    @property
    def has_created_at(self) -> bool:
        return "created_at" in self.columns

    @property
    def has_created_at_epoch(self) -> bool:
        return "created_at_epoch" in self.columns

    @property
    def has_expires_at(self) -> bool:
        return "expires_at" in self.columns

    @property
    def has_expires_at_epoch(self) -> bool:
        return "expires_at_epoch" in self.columns

    @property
    def uses_compatibility_mode(self) -> bool:
        return not _RECALL_TIME_COLUMNS.issubset(self.columns)


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _clean_email(email: str | None) -> str:
    return (email or "").strip().lower()


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


def _epoch_to_dt(value: Any) -> datetime:
    epoch = _coerce_epoch(value) or time.time()
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _limit(value: int | None, default: int = 20) -> int:
    try:
        n = int(value or default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, 1000))


def _body_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except Exception:
            return json.dumps({"value": value})
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return "{}"


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _connect_postgres(database_url: str, *, timeout_s: float, row_factory: Any | None = None):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for MEMORY_DATABASE_URL-backed tiered memory"
        ) from exc
    kwargs: dict[str, Any] = {
        "connect_timeout": max(1, int(timeout_s)),
        "prepare_threshold": None,
    }
    if row_factory is not None:
        kwargs["row_factory"] = row_factory
    return psycopg.connect(database_url, **kwargs)


def _memory_bootstrap_sql() -> str:
    bootstrap_sql = ""
    try:
        if _MEMORY_BOOTSTRAP_PATH.exists():
            bootstrap_sql = _MEMORY_BOOTSTRAP_PATH.read_text(encoding="utf-8")
    except OSError:
        bootstrap_sql = ""
    return f"{bootstrap_sql}\n{_MEMORY_RUNTIME_PATCH_SQL}".strip()


def ensure_memory_runtime_tables(database_url: str | None, *, timeout_s: float = 8.0) -> bool:
    """Best-effort bootstrap for the dedicated memory database."""

    db_url = (database_url or "").strip()
    if not db_url:
        return False

    with _MEMORY_BOOTSTRAP_LOCK:
        if db_url in _MEMORY_BOOTSTRAPPED_URLS:
            return True
        sql = _memory_bootstrap_sql()
        if not sql:
            return False
        try:
            with _connect_postgres(db_url, timeout_s=timeout_s) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            _MEMORY_BOOTSTRAPPED_URLS.add(db_url)
            _MEMORY_RECALL_SCHEMA_CACHE.pop(db_url, None)
            return True
        except Exception:
            return False


@dataclass(frozen=True)
class MemoryConfig:
    backend: str
    database_url: str
    vector_dim: int
    embeddings_enabled: bool
    timeout_s: float
    use_in_memory: bool

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        backend = (os.getenv("MEMORY_BACKEND") or "prospekt_tiered").strip().lower()
        return cls(
            backend=backend,
            database_url=(os.getenv("MEMORY_DATABASE_URL") or "").strip(),
            vector_dim=min(_int_env("MEMORY_VECTOR_DIM", 1536), 4096),
            embeddings_enabled=_truthy(os.getenv("MEMORY_EMBEDDINGS_ENABLED"), default=False),
            timeout_s=_float_env("MEMORY_TIMEOUT_S", 8.0),
            use_in_memory=_truthy(os.getenv("MEMORY_IN_MEMORY"), default=False)
            or backend in {"in_memory", "memory", "test"},
        )

    @property
    def disabled(self) -> bool:
        return self.backend in {"", "disabled", "none", "off", "false"}


class InMemoryTieredBackend:
    """Explicit test/dev backend. Production should use Postgres."""

    def __init__(self) -> None:
        self.core_blocks: list[dict[str, Any]] = []
        self.recall_memories: list[dict[str, Any]] = []
        self.archival_memories: list[dict[str, Any]] = []

    def upsert_core_block(self, record: dict[str, Any]) -> int:
        unique = (
            _clean_email(record.get("user_email")),
            record.get("tenant_id") or "",
            record.get("block_type"),
            record.get("label"),
        )
        for row in self.core_blocks:
            existing = (
                _clean_email(row.get("user_email")),
                row.get("tenant_id") or "",
                row.get("block_type"),
                row.get("label"),
            )
            if unique == existing:
                row.update(record)
                row["updated_at"] = time.time()
                return 1
        row = dict(record)
        row["id"] = str(len(self.core_blocks) + 1)
        row.setdefault("created_at", time.time())
        row.setdefault("updated_at", row["created_at"])
        self.core_blocks.append(row)
        return 1

    def query_core_blocks(self, *, user_email: str, limit: int = 20) -> list[dict[str, Any]]:
        user = _clean_email(user_email)
        rows = [
            dict(row)
            for row in self.core_blocks
            if _clean_email(row.get("user_email")) == user and bool(row.get("active", True))
        ]
        rows.sort(key=lambda row: (int(row.get("priority") or 0), _coerce_epoch(row.get("updated_at"))), reverse=True)
        return rows[: _limit(limit)]

    def insert_fact(self, record: dict[str, Any]) -> int:
        legacy = (record.get("legacy_source"), record.get("legacy_id"))
        unique = (
            _clean_email(record.get("user_email")),
            record.get("target_key"),
            record.get("kind"),
            record.get("session_key") or "",
            record.get("body_hash"),
        )
        for existing in self.recall_memories:
            existing_legacy = (existing.get("legacy_source"), existing.get("legacy_id"))
            if all(legacy) and legacy == existing_legacy:
                return 0
            existing_unique = (
                _clean_email(existing.get("user_email")),
                existing.get("target_key"),
                existing.get("kind"),
                existing.get("session_key") or "",
                existing.get("body_hash"),
            )
            if unique == existing_unique:
                return 0
        row = dict(record)
        row["id"] = str(len(self.recall_memories) + 1)
        self.recall_memories.append(row)
        return 1

    def query_facts(
        self,
        *,
        user_email: str,
        target_key: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        user = _clean_email(user_email)
        now = time.time()
        rows = [
            _fact_result(row)
            for row in self.recall_memories
            if _clean_email(row.get("user_email")) == user
            and (not target_key or row.get("target_key") == target_key)
            and (not kind or row.get("kind") == kind)
            and (not row.get("expires_at_epoch") or row.get("expires_at_epoch") > now)
        ]
        rows.sort(key=lambda row: (_coerce_epoch(row.get("created_at")), str(row.get("id") or "")), reverse=True)
        return rows[: _limit(limit)]

    def count_facts(self, *, user_email: str, target_key: str | None = None) -> int:
        user = _clean_email(user_email)
        return len(
            [
                row
                for row in self.recall_memories
                if _clean_email(row.get("user_email")) == user
                and (not target_key or row.get("target_key") == target_key)
            ]
        )

    def target_counts(self, *, user_email: str, limit: int = 20) -> list[dict[str, Any]]:
        counter = Counter(
            row.get("target_key")
            for row in self.recall_memories
            if _clean_email(row.get("user_email")) == _clean_email(user_email) and row.get("target_key")
        )
        return [{"target": target, "facts": count} for target, count in counter.most_common(_limit(limit))]

    def delete_facts(
        self,
        *,
        user_email: str,
        target_key: str | None = None,
        session_id: str | None = None,
    ) -> int:
        user = _clean_email(user_email)
        before = len(self.recall_memories)
        self.recall_memories = [
            row
            for row in self.recall_memories
            if not (
                _clean_email(row.get("user_email")) == user
                and (not target_key or row.get("target_key") == target_key)
                and (not session_id or row.get("session_key") == session_id)
            )
        ]
        return before - len(self.recall_memories)

    def insert_archive(self, record: dict[str, Any]) -> int:
        legacy = (record.get("legacy_source"), record.get("legacy_id"))
        unique = (
            _clean_email(record.get("user_email")),
            record.get("archive_type"),
            record.get("session_key") or "",
            record.get("target_key"),
            record.get("body_hash"),
        )
        for existing in self.archival_memories:
            existing_legacy = (existing.get("legacy_source"), existing.get("legacy_id"))
            if all(legacy) and legacy == existing_legacy:
                return 0
            existing_unique = (
                _clean_email(existing.get("user_email")),
                existing.get("archive_type"),
                existing.get("session_key") or "",
                existing.get("target_key"),
                existing.get("body_hash"),
            )
            if unique == existing_unique:
                return 0
        row = dict(record)
        row["id"] = str(len(self.archival_memories) + 1)
        self.archival_memories.append(row)
        return 1

    def query_archives(
        self,
        *,
        user_email: str,
        target_key: str | None = None,
        archive_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        user = _clean_email(user_email)
        rows = [
            _archive_result(row)
            for row in self.archival_memories
            if _clean_email(row.get("user_email")) == user
            and (not target_key or row.get("target_key") == target_key)
            and (not archive_type or row.get("archive_type") == archive_type)
        ]
        rows.sort(key=lambda row: (_coerce_epoch(row.get("created_at")), str(row.get("id") or "")), reverse=True)
        return rows[: _limit(limit)]

    def delete_archives(
        self,
        *,
        user_email: str,
        archive_type: str | None = None,
        session_id: str | None = None,
    ) -> int:
        user = _clean_email(user_email)
        before = len(self.archival_memories)
        self.archival_memories = [
            row
            for row in self.archival_memories
            if not (
                _clean_email(row.get("user_email")) == user
                and (not archive_type or row.get("archive_type") == archive_type)
                and (not session_id or row.get("session_key") == session_id)
            )
        ]
        return before - len(self.archival_memories)


class PostgresTieredBackend:
    def __init__(self, config: MemoryConfig) -> None:
        self.config = config

    def _connect(self):
        try:
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for MEMORY_DATABASE_URL-backed tiered memory"
            ) from exc
        return _connect_postgres(
            self.config.database_url,
            timeout_s=self.config.timeout_s,
            row_factory=dict_row,
        )

    def _ensure_runtime_ready(self) -> None:
        ensure_memory_runtime_tables(self.config.database_url, timeout_s=self.config.timeout_s)

    def _inspect_recall_schema(self, conn) -> RecallMemorySchemaCapabilities:
        cached = _MEMORY_RECALL_SCHEMA_CACHE.get(self.config.database_url)
        if cached is not None:
            return cached
        with conn.cursor() as cur:
            cur.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public' and table_name = 'recall_memories'
                """
            )
            rows = cur.fetchall()
        columns = frozenset(str(row.get("column_name") or "") for row in rows if row.get("column_name"))
        caps = RecallMemorySchemaCapabilities(columns=columns)
        _MEMORY_RECALL_SCHEMA_CACHE[self.config.database_url] = caps
        return caps

    def _warn_recall_schema_compatibility(self, caps: RecallMemorySchemaCapabilities) -> None:
        if not caps.uses_compatibility_mode:
            return
        db_key = self.config.database_url
        if db_key in _MEMORY_RECALL_SCHEMA_WARNED:
            return
        _MEMORY_RECALL_SCHEMA_WARNED.add(db_key)
        missing = sorted(_RECALL_TIME_COLUMNS - caps.columns)
        logger.warning(
            "Prospekt tiered memory recall_memories is missing %s; using compatibility SQL until bootstrap is applied.",
            ", ".join(missing),
        )

    def _build_recall_insert_statement(
        self,
        record: dict[str, Any],
        caps: RecallMemorySchemaCapabilities,
    ) -> tuple[str, tuple[Any, ...]]:
        columns = [
            "user_email",
            "tenant_id",
            "target_key",
            "cin",
            "isin",
            "symbol",
            "kind",
            "body",
            "body_hash",
            "confidence",
            "source_url",
            "session_id",
            "session_key",
            "metadata_json",
            "legacy_source",
            "legacy_id",
        ]
        placeholders = [
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s",
            "%s::jsonb",
            "%s",
            "%s",
        ]
        params: list[Any] = [
            record["user_email"],
            record.get("tenant_id") or "",
            record["target_key"],
            record.get("cin"),
            record.get("isin"),
            record.get("symbol"),
            record["kind"],
            record["body"],
            record["body_hash"],
            record["confidence"],
            record.get("source_url"),
            record.get("session_id"),
            record.get("session_key") or "",
            _json_dumps(record.get("metadata_json")),
            record.get("legacy_source"),
            record.get("legacy_id"),
        ]
        created_epoch = float(record.get("created_at") or time.time())
        expires_epoch = float(record.get("expires_at")) if record.get("expires_at") else None
        if caps.has_created_at:
            columns.append("created_at")
            placeholders.append("%s")
            params.append(_epoch_to_dt(created_epoch))
        if caps.has_created_at_epoch:
            columns.append("created_at_epoch")
            placeholders.append("%s")
            params.append(created_epoch)
        if caps.has_expires_at:
            columns.append("expires_at")
            placeholders.append("%s")
            params.append(_epoch_to_dt(expires_epoch) if expires_epoch else None)
        if caps.has_expires_at_epoch:
            columns.append("expires_at_epoch")
            placeholders.append("%s")
            params.append(expires_epoch)
        sql = f"""
            insert into recall_memories (
              {", ".join(columns)}
            )
            values (
              {", ".join(placeholders)}
            )
            on conflict do nothing
            returning id
        """
        return sql, tuple(params)

    def _build_recall_query_statement(
        self,
        *,
        user_email: str,
        target_key: str | None,
        kind: str | None,
        limit: int,
        caps: RecallMemorySchemaCapabilities,
    ) -> tuple[str, tuple[Any, ...]]:
        created_expr = "created_at_epoch" if caps.has_created_at_epoch else "extract(epoch from created_at)"
        expires_expr = (
            "expires_at_epoch"
            if caps.has_expires_at_epoch
            else ("extract(epoch from expires_at)" if caps.has_expires_at else "null::double precision")
        )
        expiry_where = (
            "(expires_at_epoch is null or expires_at_epoch > extract(epoch from now()))"
            if caps.has_expires_at_epoch
            else ("(expires_at is null or expires_at > now())" if caps.has_expires_at else "true")
        )
        where = ["lower(user_email) = lower(%s)", expiry_where]
        params: list[Any] = [user_email]
        if target_key:
            where.append("target_key = %s")
            params.append(target_key)
        if kind:
            where.append("kind = %s")
            params.append(kind)
        params.append(_limit(limit))
        sql = f"""
            select
              id::text as id, target_key, kind, body, confidence, source_url,
              nullif(session_key, '') as session_id, user_email, {created_expr} as created_at,
              {expires_expr} as expires_at,
              cin, isin, symbol, metadata_json, 0.0::double precision as score
            from recall_memories
            where {' and '.join(where)}
            order by {created_expr} desc, id desc
            limit %s
        """
        return sql, tuple(params)

    def upsert_core_block(self, record: dict[str, Any]) -> int:
        self._ensure_runtime_ready()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into core_memory_blocks (
                      user_email, tenant_id, block_type, label, text,
                      value_json, priority, active
                    )
                    values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    on conflict (user_email, tenant_id, block_type, label)
                    do update set
                      text = excluded.text,
                      value_json = excluded.value_json,
                      priority = excluded.priority,
                      active = excluded.active,
                      updated_at = now()
                    returning id
                    """,
                    (
                        record["user_email"],
                        record.get("tenant_id") or "",
                        record["block_type"],
                        record["label"],
                        record.get("text") or "",
                        _json_dumps(record.get("value_json")),
                        int(record.get("priority") or 0),
                        bool(record.get("active", True)),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return 1 if row else 0

    def query_core_blocks(self, *, user_email: str, limit: int = 20) -> list[dict[str, Any]]:
        self._ensure_runtime_ready()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select
                      id::text as id, user_email, tenant_id, block_type, label,
                      text, value_json, priority, active,
                      extract(epoch from created_at) as created_at,
                      extract(epoch from updated_at) as updated_at
                    from core_memory_blocks
                    where lower(user_email) = lower(%s) and active is true
                    order by priority desc, updated_at desc, id desc
                    limit %s
                    """,
                    (user_email, _limit(limit)),
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def insert_fact(self, record: dict[str, Any]) -> int:
        self._ensure_runtime_ready()
        with self._connect() as conn:
            caps = self._inspect_recall_schema(conn)
            self._warn_recall_schema_compatibility(caps)
            sql, params = self._build_recall_insert_statement(record, caps)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                inserted = cur.fetchone()
            conn.commit()
        return 1 if inserted else 0

    def query_facts(
        self,
        *,
        user_email: str,
        target_key: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self._ensure_runtime_ready()
        with self._connect() as conn:
            caps = self._inspect_recall_schema(conn)
            self._warn_recall_schema_compatibility(caps)
            sql, params = self._build_recall_query_statement(
                user_email=user_email,
                target_key=target_key,
                kind=kind,
                limit=limit,
                caps=caps,
            )
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [_fact_result(row) for row in cur.fetchall()]

    def count_facts(self, *, user_email: str, target_key: str | None = None) -> int:
        self._ensure_runtime_ready()
        where = ["lower(user_email) = lower(%s)"]
        params: list[Any] = [user_email]
        if target_key:
            where.append("target_key = %s")
            params.append(target_key)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"select count(*) as n from recall_memories where {' and '.join(where)}", tuple(params))
                row = cur.fetchone() or {}
        return int(row.get("n") or 0)

    def target_counts(self, *, user_email: str, limit: int = 20) -> list[dict[str, Any]]:
        self._ensure_runtime_ready()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select target_key as target, count(*)::integer as facts
                    from recall_memories
                    where lower(user_email) = lower(%s) and target_key <> ''
                    group by target_key
                    order by facts desc, target_key asc
                    limit %s
                    """,
                    (user_email, _limit(limit)),
                )
                return [{"target": row["target"], "facts": int(row["facts"] or 0)} for row in cur.fetchall()]

    def delete_facts(
        self,
        *,
        user_email: str,
        target_key: str | None = None,
        session_id: str | None = None,
    ) -> int:
        self._ensure_runtime_ready()
        where = ["lower(user_email) = lower(%s)"]
        params: list[Any] = [user_email]
        if target_key:
            where.append("target_key = %s")
            params.append(target_key)
        if session_id:
            where.append("session_key = %s")
            params.append(session_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"delete from recall_memories where {' and '.join(where)}", tuple(params))
                deleted = cur.rowcount or 0
            conn.commit()
        return int(deleted)

    def insert_archive(self, record: dict[str, Any]) -> int:
        self._ensure_runtime_ready()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into archival_memories (
                      user_email, tenant_id, target_key, archive_type, target_display,
                      body, body_hash, metrics_json, citation_count, quality_score,
                      confidence, evidence_refs, session_id, session_key, created_by,
                      status, legacy_source, legacy_id, created_at, created_at_epoch
                    )
                    values (
                      %s, %s, %s, %s, %s,
                      %s, %s, %s::jsonb, %s, %s,
                      %s, %s::jsonb, %s, %s, %s,
                      %s, %s, %s, %s, %s
                    )
                    on conflict do nothing
                    returning id
                    """,
                    (
                        record["user_email"],
                        record.get("tenant_id") or "",
                        record["target_key"],
                        record["archive_type"],
                        record.get("target_display") or "",
                        record["body"],
                        record["body_hash"],
                        _json_dumps(record.get("metrics_json")),
                        int(record.get("citation_count") or 0),
                        float(record.get("quality_score") or 0.0),
                        record.get("confidence") or "MEDIUM",
                        _json_dumps(record.get("evidence_refs") or []),
                        record.get("session_id"),
                        record.get("session_key") or "",
                        record.get("created_by") or "runtime",
                        record.get("status") or "active",
                        record.get("legacy_source"),
                        record.get("legacy_id"),
                        _epoch_to_dt(record.get("created_at")),
                        float(record.get("created_at") or time.time()),
                    ),
                )
                inserted = cur.fetchone()
            conn.commit()
        return 1 if inserted else 0

    def query_archives(
        self,
        *,
        user_email: str,
        target_key: str | None = None,
        archive_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self._ensure_runtime_ready()
        where = ["lower(user_email) = lower(%s)"]
        params: list[Any] = [user_email]
        if target_key:
            where.append("target_key = %s")
            params.append(target_key)
        if archive_type:
            where.append("archive_type = %s")
            params.append(archive_type)
        params.append(_limit(limit))
        sql = f"""
            select
              id::text as id, target_key, archive_type, target_display,
              body as summary, metrics_json, citation_count, quality_score,
              confidence, evidence_refs, nullif(session_key, '') as session_id,
              created_by, status, user_email, created_at_epoch as created_at
            from archival_memories
            where {' and '.join(where)}
            order by created_at_epoch desc, id desc
            limit %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return [_archive_result(row) for row in cur.fetchall()]

    def delete_archives(
        self,
        *,
        user_email: str,
        archive_type: str | None = None,
        session_id: str | None = None,
    ) -> int:
        self._ensure_runtime_ready()
        where = ["lower(user_email) = lower(%s)"]
        params: list[Any] = [user_email]
        if archive_type:
            where.append("archive_type = %s")
            params.append(archive_type)
        if session_id:
            where.append("session_key = %s")
            params.append(session_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"delete from archival_memories where {' and '.join(where)}", tuple(params))
                deleted = cur.rowcount or 0
            conn.commit()
        return int(deleted)


def _fact_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "target_key": row.get("target_key", ""),
        "kind": row.get("kind", ""),
        "body": row.get("body", ""),
        "confidence": row.get("confidence", ""),
        "source_url": row.get("source_url"),
        "session_id": row.get("session_id") or row.get("session_key") or None,
        "user_email": row.get("user_email"),
        "created_at": _coerce_epoch(row.get("created_at")),
        "score": float(row.get("score") or 0.0),
        "cin": row.get("cin"),
        "isin": row.get("isin"),
        "symbol": row.get("symbol"),
        "metadata": _json_loads(row.get("metadata_json")),
    }


def _archive_result(row: dict[str, Any]) -> dict[str, Any]:
    metrics = _json_loads(row.get("metrics_json"))
    return {
        "id": row.get("id"),
        "session_id": row.get("session_id") or row.get("session_key") or None,
        "target_key": row.get("target_key", ""),
        "target_display": row.get("target_display", ""),
        "summary": row.get("summary") or row.get("body") or "",
        "metrics_json": _json_dumps(metrics),
        "metrics": metrics,
        "citation_count": int(row.get("citation_count") or 0),
        "quality_score": float(row.get("quality_score") or 0.0),
        "archive_type": row.get("archive_type", "session_summary"),
        "confidence": row.get("confidence"),
        "evidence_refs": row.get("evidence_refs"),
        "created_by": row.get("created_by"),
        "status": row.get("status"),
        "user_email": row.get("user_email"),
        "created_at": _coerce_epoch(row.get("created_at")),
    }


class ProspektTieredMemoryStore:
    def __init__(self, backend: Any | None = None, config: MemoryConfig | None = None) -> None:
        self.config = config or MemoryConfig.from_env()
        if backend is not None:
            self.backend = backend
        elif self.config.disabled:
            self.backend = None
        elif self.config.use_in_memory:
            self.backend = InMemoryTieredBackend()
        elif self.config.database_url:
            self.backend = PostgresTieredBackend(self.config)
        else:
            self.backend = None

    @property
    def backend_name(self) -> str:
        if isinstance(self.backend, InMemoryTieredBackend):
            return "prospekt_tiered_in_memory"
        if isinstance(self.backend, PostgresTieredBackend):
            return "prospekt_tiered"
        return "prospekt_tiered_unconfigured"

    @property
    def location(self) -> str:
        if isinstance(self.backend, PostgresTieredBackend):
            return "<memory-postgres>"
        if isinstance(self.backend, InMemoryTieredBackend):
            return "<memory-in-memory>"
        return "<memory-unconfigured>"

    def _configured(self) -> bool:
        return self.backend is not None

    def _warn_unconfigured(self, operation: str) -> None:
        logger.warning(
            "Prospekt tiered memory %s skipped because MEMORY_DATABASE_URL is not configured",
            operation,
        )

    async def upsert_core_memory_block(
        self,
        *,
        user_email: str,
        block_type: str,
        label: str,
        text: str = "",
        value: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        priority: int = 0,
        active: bool = True,
    ) -> int:
        if not user_email:
            raise ValueError("user_email is required to persist core memory")
        if not block_type or not label:
            raise ValueError("block_type and label are required for core memory")
        if not self._configured():
            self._warn_unconfigured("core memory write")
            return 0
        record = {
            "user_email": _clean_email(user_email),
            "tenant_id": tenant_id or "",
            "block_type": block_type.strip(),
            "label": label.strip(),
            "text": (text or "").strip(),
            "value_json": value or {},
            "priority": int(priority or 0),
            "active": bool(active),
        }
        try:
            return await asyncio.to_thread(self.backend.upsert_core_block, record)
        except Exception as exc:
            logger.warning("Prospekt tiered memory upsert_core_memory_block failed: %s", exc)
            return 0

    async def get_core_memory_blocks(self, *, user_email: str, limit: int = 20) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to read core memory")
        if not self._configured():
            self._warn_unconfigured("core memory read")
            return []
        try:
            return await asyncio.to_thread(
                self.backend.query_core_blocks,
                user_email=_clean_email(user_email),
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory get_core_memory_blocks failed: %s", exc)
            return []

    async def remember(
        self,
        target_key: str,
        kind: str,
        body: str,
        confidence: str,
        source_url: str | None = None,
        session_id: str | None = None,
        user_email: str | None = None,
        created_at: float | None = None,
        expires_at: float | None = None,
        *,
        cin: str | None = None,
        isin: str | None = None,
        symbol: str | None = None,
        tenant_id: str | None = None,
        legacy_source: str | None = None,
        legacy_id: str | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if not user_email:
            raise ValueError("user_email is required to persist memory facts")
        text = (body or "").strip()
        if not text:
            return 0
        if not self._configured():
            self._warn_unconfigured("write")
            return 0
        created = float(created_at) if created_at is not None else time.time()
        session_key = (session_id or "").strip()
        metadata_json = {
            "record_type": "fact",
            "tier": "recall",
            "legacy_source": legacy_source,
            "legacy_id": str(legacy_id) if legacy_id is not None else None,
            **(metadata or {}),
        }
        record = {
            "user_email": _clean_email(user_email),
            "tenant_id": tenant_id or "",
            "target_key": target_key,
            "cin": cin,
            "isin": isin,
            "symbol": symbol,
            "kind": kind or "other",
            "body": text,
            "body_hash": _body_hash(text),
            "confidence": confidence or "MEDIUM",
            "source_url": source_url,
            "session_id": session_id,
            "session_key": session_key,
            "metadata_json": {k: v for k, v in metadata_json.items() if v is not None},
            "legacy_source": legacy_source,
            "legacy_id": str(legacy_id) if legacy_id is not None else None,
            "created_at": created,
            "expires_at": expires_at,
        }
        try:
            return await asyncio.to_thread(self.backend.insert_fact, record)
        except Exception as exc:
            logger.warning("Prospekt tiered memory remember failed: %s", exc)
            return 0

    async def recall(
        self,
        target_key: str,
        *,
        kind: str | None = None,
        limit: int = 20,
        user_email: str | None = None,
    ) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to recall memory facts")
        if not self._configured():
            self._warn_unconfigured("recall")
            return []
        try:
            return await asyncio.to_thread(
                self.backend.query_facts,
                user_email=_clean_email(user_email),
                target_key=target_key,
                kind=kind,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory recall failed: %s", exc)
            return []

    async def get_facts(
        self,
        target_key: str | None = None,
        *,
        user_email: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to retrieve facts")
        if not self._configured():
            self._warn_unconfigured("get_facts")
            return []
        try:
            return await asyncio.to_thread(
                self.backend.query_facts,
                user_email=_clean_email(user_email),
                target_key=target_key,
                kind=None,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory get_facts failed: %s", exc)
            return []

    async def save_session_summary(
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
        created_at: float | None = None,
        tenant_id: str | None = None,
        legacy_source: str | None = None,
        legacy_id: str | int | None = None,
    ) -> int:
        if not user_email:
            raise ValueError("user_email is required to save session summaries")
        text = (summary or "").strip()
        if not text:
            return 0
        if not self._configured():
            self._warn_unconfigured("summary write")
            return 0
        created = float(created_at) if created_at is not None else time.time()
        record = {
            "user_email": _clean_email(user_email),
            "tenant_id": tenant_id or "",
            "target_key": target_key,
            "archive_type": "session_summary",
            "target_display": target_display,
            "body": text,
            "body_hash": _body_hash(text),
            "metrics_json": metrics or {},
            "citation_count": int(citation_count or 0),
            "quality_score": float(quality_score or 0.0),
            "confidence": "HIGH" if quality_score >= 80 else "MEDIUM",
            "evidence_refs": [],
            "session_id": session_id,
            "session_key": (session_id or "").strip(),
            "created_by": "runtime",
            "status": "active",
            "legacy_source": legacy_source,
            "legacy_id": str(legacy_id) if legacy_id is not None else None,
            "created_at": created,
        }
        try:
            return await asyncio.to_thread(self.backend.insert_archive, record)
        except Exception as exc:
            logger.warning("Prospekt tiered memory save_session_summary failed: %s", exc)
            return 0

    async def write_archival_memory(
        self,
        *,
        user_email: str,
        target_key: str,
        archive_type: str,
        body: str,
        target_display: str = "",
        metrics: dict | None = None,
        confidence: str = "MEDIUM",
        evidence_refs: list | None = None,
        session_id: str | None = None,
        created_by: str = "dreaming_layer",
        status: str = "active",
        tenant_id: str | None = None,
        created_at: float | None = None,
        legacy_source: str | None = None,
        legacy_id: str | int | None = None,
    ) -> int:
        if not user_email:
            raise ValueError("user_email is required to write archival memory")
        text = (body or "").strip()
        if not text:
            return 0
        if not self._configured():
            self._warn_unconfigured("archival write")
            return 0
        created = float(created_at) if created_at is not None else time.time()
        record = {
            "user_email": _clean_email(user_email),
            "tenant_id": tenant_id or "",
            "target_key": target_key,
            "archive_type": archive_type or "pattern",
            "target_display": target_display,
            "body": text,
            "body_hash": _body_hash(text),
            "metrics_json": metrics or {},
            "citation_count": 0,
            "quality_score": 0.0,
            "confidence": confidence or "MEDIUM",
            "evidence_refs": evidence_refs or [],
            "session_id": session_id,
            "session_key": (session_id or "").strip(),
            "created_by": created_by or "dreaming_layer",
            "status": status or "active",
            "legacy_source": legacy_source,
            "legacy_id": str(legacy_id) if legacy_id is not None else None,
            "created_at": created,
        }
        try:
            return await asyncio.to_thread(self.backend.insert_archive, record)
        except Exception as exc:
            logger.warning("Prospekt tiered memory write_archival_memory failed: %s", exc)
            return 0

    async def list_archival_memories(
        self,
        *,
        user_email: str,
        target_key: str | None = None,
        archive_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to list archival memory")
        if not self._configured():
            self._warn_unconfigured("archival listing")
            return []
        try:
            return await asyncio.to_thread(
                self.backend.query_archives,
                user_email=_clean_email(user_email),
                target_key=target_key,
                archive_type=archive_type,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory list_archival_memories failed: %s", exc)
            return []

    async def last_summary(self, target_key: str, *, user_email: str | None = None) -> dict | None:
        rows = await self.list_sessions(user_email=user_email, target_key=target_key, limit=20)
        return rows[0] if rows else None

    async def count(self, target_key: str | None = None, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to count memory facts")
        if not self._configured():
            self._warn_unconfigured("count")
            return 0
        try:
            return await asyncio.to_thread(
                self.backend.count_facts,
                user_email=_clean_email(user_email),
                target_key=target_key,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory count failed: %s", exc)
            return 0

    async def get_targets(self, user_email: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to list targets")
        if not self._configured():
            self._warn_unconfigured("target listing")
            return []
        try:
            return await asyncio.to_thread(
                self.backend.target_counts,
                user_email=_clean_email(user_email),
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory get_targets failed: %s", exc)
            return []

    async def get_session_count(self, user_email: str | None = None) -> int:
        rows = await self.list_sessions(user_email=user_email, limit=1000)
        return len({row.get("session_id") for row in rows if row.get("session_id")})

    async def list_sessions(
        self,
        user_email: str | None = None,
        target_key: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to list sessions")
        if not self._configured():
            self._warn_unconfigured("session listing")
            return []
        try:
            rows = await asyncio.to_thread(
                self.backend.query_archives,
                user_email=_clean_email(user_email),
                target_key=target_key,
                archive_type="session_summary",
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory list_sessions failed: %s", exc)
            return []
        return rows

    async def clear_target(self, target_key: str, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to clear memory facts")
        if not self._configured():
            self._warn_unconfigured("clear_target")
            return 0
        try:
            return await asyncio.to_thread(
                self.backend.delete_facts,
                user_email=_clean_email(user_email),
                target_key=target_key,
                session_id=None,
            )
        except Exception as exc:
            logger.warning("Prospekt tiered memory clear_target failed: %s", exc)
            return 0

    async def delete_session(self, session_id: str, user_email: str | None = None) -> dict[str, int]:
        if not user_email:
            raise ValueError("user_email is required to delete session memory")
        if not self._configured():
            self._warn_unconfigured("delete_session")
            return {"facts": 0, "summaries": 0}
        try:
            facts = await asyncio.to_thread(
                self.backend.delete_facts,
                user_email=_clean_email(user_email),
                session_id=session_id,
            )
            summaries = await asyncio.to_thread(
                self.backend.delete_archives,
                user_email=_clean_email(user_email),
                archive_type="session_summary",
                session_id=session_id,
            )
            return {"facts": int(facts or 0), "summaries": int(summaries or 0)}
        except Exception as exc:
            logger.warning("Prospekt tiered memory delete_session failed: %s", exc)
            return {"facts": 0, "summaries": 0}
