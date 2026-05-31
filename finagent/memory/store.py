"""Supabase PostgreSQL-backed memory store (replaces SQLite).

Thread safety: each method is async and uses the Supabase PostgREST client.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Iterable

from finagent.storage.supabase_store import get_memory_store as _get_storage_memory_store

logger = logging.getLogger("finagent.memory")


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


class MemoryStore:
    def __init__(self) -> None:
        self._store = _get_storage_memory_store()

    async def remember(self, fact: MemoryFact) -> int:
        if not fact.body or not fact.body.strip():
            return 0
        if not fact.user_email:
            raise ValueError("user_email is required to persist memory facts")
        if not fact.created_at:
            fact.created_at = time.time()
        target = normalize_target(fact.target_key)
        try:
            await self._store.remember(
                target_key=target,
                kind=fact.kind,
                body=fact.body.strip(),
                confidence=fact.confidence,
                source_url=fact.source_url,
                session_id=fact.session_id,
                user_email=fact.user_email,
                created_at=fact.created_at,
            )
            return 1
        except Exception as exc:
            logger.warning("Supabase remember failed: %s", exc)
            return 0

    async def remember_many(self, facts: Iterable[MemoryFact]) -> int:
        count = 0
        for f in facts:
            if not f.user_email:
                raise ValueError("user_email is required for every memory fact")
            try:
                ok = await self.remember(f)
                if ok:
                    count += 1
            except Exception as exc:
                logger.warning("remember_many single fact failed: %s", exc)
        return count

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
    ) -> None:
        if not user_email:
            raise ValueError("user_email is required to save session summaries")
        try:
            await self._store.save_session_summary(
                session_id=session_id,
                target_key=normalize_target(target_key),
                target_display=target_display,
                summary=summary,
                metrics=metrics,
                citation_count=citation_count,
                quality_score=quality_score,
                user_email=user_email,
                created_at=time.time(),
            )
        except Exception as exc:
            logger.warning("Supabase save_session_summary failed: %s", exc)

    async def recall(
        self,
        target_key: str,
        *,
        kind: str | None = None,
        limit: int = 20,
        user_email: str | None = None,
    ) -> list[MemoryFact]:
        if not user_email:
            raise ValueError("user_email is required to recall memory facts")
        target = normalize_target(target_key)
        try:
            rows = await self._store.recall(
                target_key=target,
                kind=kind,
                limit=limit,
                user_email=user_email,
            )
            return [
                MemoryFact(
                    target_key=r.get("target_key", ""),
                    kind=r.get("kind", ""),
                    body=r.get("body", ""),
                    confidence=r.get("confidence", ""),
                    source_url=r.get("source_url"),
                    session_id=r.get("session_id"),
                    user_email=r.get("user_email"),
                    created_at=r.get("created_at", 0.0),
                    score=0.0,
                )
                for r in rows
            ]
        except Exception as exc:
            logger.warning("Supabase recall failed: %s", exc)
            return []

    async def get_facts(
        self,
        target_key: str | None = None,
        *,
        user_email: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if not user_email:
            raise ValueError("user_email is required to retrieve facts")
        try:
            if target_key:
                target_key = normalize_target(target_key)
            return await self._store.get_facts(
                target_key=target_key,
                user_email=user_email,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Supabase get_facts failed: %s", exc)
            return []

    async def last_summary(self, target_key: str, *, user_email: str | None = None) -> dict | None:
        if not user_email:
            raise ValueError("user_email is required to retrieve session summaries")
        target = normalize_target(target_key)
        try:
            row = await self._store.last_summary(target_key=target, user_email=user_email)
            if not row:
                return None
            return {
                "session_id": row.get("session_id"),
                "target_key": row.get("target_key"),
                "target_display": row.get("target_display"),
                "summary": row.get("summary", ""),
                "metrics": json.loads(row.get("metrics_json") or "{}"),
                "citation_count": row.get("citation_count"),
                "quality_score": row.get("quality_score"),
                "user_email": row.get("user_email"),
                "created_at": row.get("created_at"),
            }
        except Exception as exc:
            logger.warning("Supabase last_summary failed: %s", exc)
            return None

    async def count(self, target_key: str | None = None, *, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to count memory facts")
        try:
            normalized = normalize_target(target_key) if target_key else None
            return await self._store.count(target_key=normalized, user_email=user_email)
        except Exception as exc:
            logger.warning("Supabase count failed: %s", exc)
            return 0

    async def clear_target(self, target_key: str, *, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to clear memory facts")
        try:
            return await self._store.clear_target(normalize_target(target_key), user_email=user_email)
        except Exception as exc:
            logger.warning("Supabase clear_target failed: %s", exc)
            return 0

    async def get_targets(self, *, user_email: str | None = None, limit: int = 20) -> list[dict]:
        if not user_email:
            raise ValueError("user_email is required to list targets")
        try:
            return await self._store.get_targets(user_email=user_email, limit=limit)
        except Exception as exc:
            logger.warning("Supabase get_targets failed: %s", exc)
            return []

    async def get_session_count(self, *, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to count sessions")
        try:
            return await self._store.get_session_count(user_email=user_email)
        except Exception as exc:
            logger.warning("Supabase get_session_count failed: %s", exc)
            return 0

    async def list_sessions(
        self,
        *,
        user_email: str | None = None,
        target_key: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        if not user_email:
            raise ValueError("user_email is required to list sessions")
        try:
            normalized = normalize_target(target_key) if target_key else None
            return await self._store.list_sessions(
                user_email=user_email,
                target_key=normalized,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Supabase list_sessions failed: %s", exc)
            return []

    async def delete_session(self, session_id: str, *, user_email: str | None = None) -> dict[str, int]:
        if not user_email:
            raise ValueError("user_email is required to delete session memory")
        try:
            return await self._store.delete_session(session_id, user_email=user_email)
        except Exception as exc:
            logger.warning("Supabase delete_session failed: %s", exc)
            return {"facts": 0, "summaries": 0}


_singleton: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Return the per-process memory store singleton.

    Pass `db_path` to override for tests; subsequent calls without
    a path reuse the same store.
    """
    global _singleton
    if _singleton is None:
        _singleton = MemoryStore()
    return _singleton
