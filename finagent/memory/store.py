"""Cross-session memory facade backed by ProspektLab tiered memory.

Agents keep calling this module's stable API. The implementation delegates to
ProspektLab's internal Core/Recall/Archival memory store, not Supabase, so
Supabase remains limited to auth and user-operational data.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Iterable

from finagent.memory.tiered_store import ProspektTieredMemoryStore

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
    kind: str
    body: str
    confidence: str
    source_url: str | None = None
    session_id: str | None = None
    user_email: str | None = None
    created_at: float = 0.0
    score: float = 0.0

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
    def __init__(self, store: ProspektTieredMemoryStore | None = None) -> None:
        self._store = store or ProspektTieredMemoryStore()

    @property
    def backend_name(self) -> str:
        return getattr(self._store, "backend_name", "prospekt_tiered")

    @property
    def location(self) -> str:
        return getattr(self._store, "location", "<memory>")

    async def remember(self, fact: MemoryFact) -> int:
        if not fact.body or not fact.body.strip():
            return 0
        if not fact.user_email:
            raise ValueError("user_email is required to persist memory facts")
        if not fact.created_at:
            fact.created_at = time.time()
        try:
            return await self._store.remember(
                target_key=normalize_target(fact.target_key),
                kind=fact.kind,
                body=fact.body.strip(),
                confidence=fact.confidence,
                source_url=fact.source_url,
                session_id=fact.session_id,
                user_email=fact.user_email,
                created_at=fact.created_at,
            )
        except Exception as exc:
            logger.warning("tiered memory remember failed: %s", exc)
            return 0

    async def remember_many(self, facts: Iterable[MemoryFact]) -> int:
        count = 0
        for fact in facts:
            if not fact.user_email:
                raise ValueError("user_email is required for every memory fact")
            try:
                count += await self.remember(fact)
            except Exception as exc:
                logger.warning("remember_many single fact failed: %s", exc)
        return count

    async def append(self, fact: MemoryFact) -> int:
        """Compatibility alias for older agent-facing memory.append() calls."""
        return await self.remember(fact)

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
            logger.warning("tiered memory save_session_summary failed: %s", exc)

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
        except Exception as exc:
            logger.warning("tiered memory recall failed: %s", exc)
            return []
        return [
            MemoryFact(
                target_key=row.get("target_key", ""),
                kind=row.get("kind", ""),
                body=row.get("body", ""),
                confidence=row.get("confidence", ""),
                source_url=row.get("source_url"),
                session_id=row.get("session_id"),
                user_email=row.get("user_email"),
                created_at=float(row.get("created_at") or 0.0),
                score=float(row.get("score") or 0.0),
            )
            for row in rows
        ]

    async def search(
        self,
        target_key: str,
        *,
        kind: str | None = None,
        limit: int = 20,
        user_email: str | None = None,
    ) -> list[MemoryFact]:
        """Compatibility alias for older agent-facing memory.search() calls."""
        return await self.recall(target_key, kind=kind, limit=limit, user_email=user_email)

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
            return await self._store.get_facts(
                target_key=normalize_target(target_key) if target_key else None,
                user_email=user_email,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("tiered memory get_facts failed: %s", exc)
            return []

    async def last_summary(self, target_key: str, *, user_email: str | None = None) -> dict | None:
        if not user_email:
            raise ValueError("user_email is required to retrieve session summaries")
        try:
            row = await self._store.last_summary(
                normalize_target(target_key),
                user_email=user_email,
            )
        except Exception as exc:
            logger.warning("tiered memory last_summary failed: %s", exc)
            return None
        if not row:
            return None
        metrics = row.get("metrics", {})
        if not metrics and row.get("metrics_json"):
            try:
                metrics = json.loads(row.get("metrics_json") or "{}")
            except Exception:
                metrics = {}
        return {
            "session_id": row.get("session_id"),
            "target_key": row.get("target_key"),
            "target_display": row.get("target_display"),
            "summary": row.get("summary", ""),
            "metrics": metrics,
            "citation_count": row.get("citation_count"),
            "quality_score": row.get("quality_score"),
            "user_email": row.get("user_email"),
            "created_at": row.get("created_at"),
        }

    async def count(self, target_key: str | None = None, *, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to count memory facts")
        try:
            return await self._store.count(
                target_key=normalize_target(target_key) if target_key else None,
                user_email=user_email,
            )
        except Exception as exc:
            logger.warning("tiered memory count failed: %s", exc)
            return 0

    async def clear_target(self, target_key: str, *, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to clear memory facts")
        try:
            return await self._store.clear_target(
                normalize_target(target_key),
                user_email=user_email,
            )
        except Exception as exc:
            logger.warning("tiered memory clear_target failed: %s", exc)
            return 0

    async def get_targets(self, *, user_email: str | None = None, limit: int = 20) -> list[dict]:
        if not user_email:
            raise ValueError("user_email is required to list targets")
        try:
            return await self._store.get_targets(user_email=user_email, limit=limit)
        except Exception as exc:
            logger.warning("tiered memory get_targets failed: %s", exc)
            return []

    async def get_session_count(self, *, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to count sessions")
        try:
            return await self._store.get_session_count(user_email=user_email)
        except Exception as exc:
            logger.warning("tiered memory get_session_count failed: %s", exc)
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
            return await self._store.list_sessions(
                user_email=user_email,
                target_key=normalize_target(target_key) if target_key else None,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("tiered memory list_sessions failed: %s", exc)
            return []

    async def delete_session(self, session_id: str, *, user_email: str | None = None) -> dict[str, int]:
        if not user_email:
            raise ValueError("user_email is required to delete session memory")
        try:
            return await self._store.delete_session(session_id, user_email=user_email)
        except Exception as exc:
            logger.warning("tiered memory delete_session failed: %s", exc)
            return {"facts": 0, "summaries": 0}


_singleton: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _singleton
    if _singleton is None:
        _singleton = MemoryStore()
    return _singleton
