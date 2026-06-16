"""Lightweight TTL cache with optional Redis backend.

Usage:
    from finagent.cache import app_cache
    await app_cache.set("quotes:RELIANCE", data, ttl=60)
    hit = await app_cache.get("quotes:RELIANCE")
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("finagent.cache")

_REDIS_URL = os.getenv("REDIS_URL", "").strip()


class _InMemoryCache:
    """Thread-safe in-memory cache with per-key TTL."""

    def __init__(self, max_keys: int = 4096) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._max_keys = max_keys
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, *, ttl: int = 300) -> None:
        async with self._lock:
            if len(self._store) >= self._max_keys:
                self._evict()
            self._store[key] = (time.monotonic() + ttl, value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        if len(self._store) >= self._max_keys:
            oldest = sorted(self._store, key=lambda k: self._store[k][0])
            for k in oldest[: len(oldest) // 4]:
                del self._store[k]


class _RedisCache:
    """Async Redis cache. Falls back to in-memory on connection errors."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._fallback = _InMemoryCache()
        self._redis: Any = None

    async def _conn(self) -> Any:
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._url, decode_responses=True)
            await self._redis.ping()
            return self._redis
        except Exception:
            logger.warning("Redis unavailable at %s, using in-memory cache", self._url)
            self._redis = None
            return None

    async def get(self, key: str) -> Any | None:
        r = await self._conn()
        if r is None:
            return await self._fallback.get(key)
        try:
            raw = await r.get(f"fc:{key}")
            return json.loads(raw) if raw else None
        except Exception:
            return await self._fallback.get(key)

    async def set(self, key: str, value: Any, *, ttl: int = 300) -> None:
        r = await self._conn()
        if r is None:
            return await self._fallback.set(key, value, ttl=ttl)
        try:
            await r.setex(f"fc:{key}", ttl, json.dumps(value, default=str))
        except Exception:
            await self._fallback.set(key, value, ttl=ttl)

    async def delete(self, key: str) -> None:
        r = await self._conn()
        if r is None:
            return await self._fallback.delete(key)
        try:
            await r.delete(f"fc:{key}")
        except Exception:
            await self._fallback.delete(key)


def _build_cache() -> _InMemoryCache | _RedisCache:
    if _REDIS_URL:
        return _RedisCache(_REDIS_URL)
    return _InMemoryCache()


app_cache = _build_cache()
