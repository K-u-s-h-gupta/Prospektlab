"""Supabase PostgreSQL-backed storage layer replacing SQLite for production.

Uses the existing Supabase PostgREST client pattern (httpx) so no new
dependencies are required. All tables must be created in Supabase with
Row-Level Security (RLS) policies applied.

Required Supabase tables (run these in Supabase SQL Editor):

  -- portfolio_mirrors
  CREATE TABLE IF NOT EXISTS portfolio_mirrors (
      id SERIAL PRIMARY KEY,
      tenant_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
      symbol TEXT NOT NULL,
      exchange TEXT NOT NULL DEFAULT 'NSE',
      quantity REAL NOT NULL DEFAULT 0,
      market_value REAL NOT NULL DEFAULT 0,
      cost_basis REAL NOT NULL DEFAULT 0,
      active INTEGER NOT NULL DEFAULT 1,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      name TEXT,
      isin TEXT,
      amfi TEXT,
      kind TEXT NOT NULL DEFAULT 'equity',
      sector TEXT,
      industry TEXT,
      avg_cost REAL NOT NULL DEFAULT 0,
      last_price REAL NOT NULL DEFAULT 0,
      as_of TEXT
  );
  CREATE INDEX idx_portfolio_mirrors_tenant_active ON portfolio_mirrors(tenant_id, active, symbol);

  -- facts
  CREATE TABLE IF NOT EXISTS facts (
      id SERIAL PRIMARY KEY,
      target_key TEXT NOT NULL,
      kind TEXT NOT NULL,
      body TEXT NOT NULL,
      confidence TEXT NOT NULL,
      source_url TEXT,
      session_id TEXT,
      user_email TEXT NOT NULL,
      created_at REAL NOT NULL
  );
  CREATE INDEX idx_facts_target ON facts(target_key, created_at DESC);
  CREATE INDEX idx_facts_kind ON facts(target_key, kind);
  CREATE INDEX idx_facts_user ON facts(user_email, target_key, created_at DESC);

  -- session_summaries
  CREATE TABLE IF NOT EXISTS session_summaries (
      session_id TEXT PRIMARY KEY,
      target_key TEXT NOT NULL,
      target_display TEXT,
      summary TEXT NOT NULL,
      metrics_json TEXT,
      citation_count INTEGER,
      quality_score REAL,
      user_email TEXT NOT NULL,
      created_at REAL NOT NULL
  );
  CREATE INDEX idx_summaries_target ON session_summaries(target_key, created_at DESC);
  CREATE INDEX idx_summaries_user ON session_summaries(user_email, target_key, created_at DESC);

  -- rate_limits
  CREATE TABLE IF NOT EXISTS rate_limits (
      key TEXT PRIMARY KEY,
      count INTEGER NOT NULL DEFAULT 0,
      window_start REAL NOT NULL
  );

  -- verification_codes
  CREATE TABLE IF NOT EXISTS verification_codes (
      email TEXT NOT NULL,
      code TEXT NOT NULL,
      type TEXT NOT NULL DEFAULT 'signup',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (email, type)
  );

  -- pending_extractions
  CREATE TABLE IF NOT EXISTS pending_extractions (
      review_id TEXT PRIMARY KEY,
      tenant_id UUID NOT NULL,
      payload_json TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX idx_pending_tenant ON pending_extractions(tenant_id);

  -- revoked_tokens
  CREATE TABLE IF NOT EXISTS revoked_tokens (
      jti TEXT PRIMARY KEY,
      revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      expires_at TIMESTAMPTZ NOT NULL
  );

  -- token_usage
  CREATE TABLE IF NOT EXISTS token_usage (
      id SERIAL PRIMARY KEY,
      user_email TEXT NOT NULL,
      session_id TEXT DEFAULT '',
      prompt_tokens INTEGER DEFAULT 0,
      completion_tokens INTEGER DEFAULT 0,
      total_tokens INTEGER DEFAULT 0,
      model TEXT DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX idx_token_usage_email ON token_usage(user_email, created_at);

  -- RLS policies (use Supabase service key for admin ops; these policies
  -- protect when using the anon key with user JWT):
  ALTER TABLE portfolio_mirrors ENABLE ROW LEVEL SECURITY;
  CREATE POLICY portfolio_mirrors_tenant_isolation ON portfolio_mirrors
    FOR ALL USING (tenant_id = auth.uid());

  ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
  CREATE POLICY facts_user_isolation ON facts
    FOR ALL USING (user_email = auth.email());

  ALTER TABLE session_summaries ENABLE ROW LEVEL SECURITY;
  CREATE POLICY session_summaries_user_isolation ON session_summaries
    FOR ALL USING (user_email = auth.email());

  ALTER TABLE pending_extractions ENABLE ROW LEVEL SECURITY;
  CREATE POLICY pending_extractions_tenant_isolation ON pending_extractions
    FOR ALL USING (tenant_id = auth.uid());

  ALTER TABLE token_usage ENABLE ROW LEVEL SECURITY;
  CREATE POLICY token_usage_user_isolation ON token_usage
    FOR ALL USING (user_email = auth.email());
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from finagent.gateway.supabase_client import get_headers, _get_supabase_url, _get_supabase_key
from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.storage.supabase")

def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _nonnegative_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


_SUPABASE_TIMEOUT = httpx.Timeout(
    _float_env("SUPABASE_TIMEOUT_S", 8.0),
    connect=_float_env("SUPABASE_CONNECT_TIMEOUT_S", 4.0),
)

_PORTFOLIO_MIRROR_CACHE_TTL_S = _float_env(
    "SUPABASE_PORTFOLIO_CACHE_TTL_S",
    7 * 24 * 60 * 60,
)
_PORTFOLIO_MIRROR_FAST_CACHE_TTL_S = _nonnegative_float_env(
    "SUPABASE_PORTFOLIO_FAST_CACHE_TTL_S",
    30.0,
)


def _httpx_trust_env() -> bool:
    raw = os.environ.get("FINAGENT_HTTP_TRUST_ENV", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


_HTTPX_TRUST_ENV = _httpx_trust_env()


def _supabase_async_client(**kwargs):
    return httpx.AsyncClient(
        timeout=_SUPABASE_TIMEOUT,
        trust_env=_HTTPX_TRUST_ENV,
        **kwargs,
    )


def _get_headers() -> dict[str, str]:
    h = get_headers()
    h["Prefer"] = "return=representation"
    return h


def _clean_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove None values so PostgREST doesn't try to insert them."""
    return {k: v for k, v in d.items() if v is not None}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _week_start_utc() -> datetime:
    """Return the current week's UTC Monday 00:00 boundary."""
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _to_epoch_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
    return 0.0


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Portfolio Mirrors
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SupabasePortfolioStore:
    def __init__(self) -> None:
        self.base = f"{_get_supabase_url()}/rest/v1/portfolio_mirrors"
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _cache_path(self, tenant_id: str):
        safe_tenant = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tenant_id or "unknown"))
        return finagent_data_path("portfolio_mirror_cache", f"{safe_tenant}.json")

    def _write_cache(self, tenant_id: str, rows: list[dict[str, Any]]) -> None:
        if not tenant_id or not rows:
            return
        payload = {
            "cached_at": time.time(),
            "rows": rows,
        }
        self._cache[tenant_id] = (payload["cached_at"], rows)
        try:
            self._cache_path(tenant_id).write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            logger.debug("Portfolio mirror cache write failed for tenant %s: %s", tenant_id, exc)

    def _read_cache(self, tenant_id: str) -> list[dict[str, Any]]:
        if not tenant_id or _PORTFOLIO_MIRROR_CACHE_TTL_S <= 0:
            return []
        now = time.time()
        memory_entry = self._cache.get(tenant_id)
        if memory_entry:
            cached_at, rows = memory_entry
            if now - cached_at <= _PORTFOLIO_MIRROR_CACHE_TTL_S:
                return [dict(row) for row in rows]
        try:
            path = self._cache_path(tenant_id)
            if not path.exists():
                return []
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached_at = float(payload.get("cached_at") or 0)
            rows = payload.get("rows") or []
            if now - cached_at > _PORTFOLIO_MIRROR_CACHE_TTL_S or not isinstance(rows, list):
                return []
            clean_rows = [row for row in rows if isinstance(row, dict)]
            if clean_rows:
                self._cache[tenant_id] = (cached_at, clean_rows)
            return [dict(row) for row in clean_rows]
        except Exception as exc:
            logger.debug("Portfolio mirror cache read failed for tenant %s: %s", tenant_id, exc)
            return []

    def _read_fresh_memory_cache(self, tenant_id: str) -> list[dict[str, Any]]:
        if not tenant_id or _PORTFOLIO_MIRROR_FAST_CACHE_TTL_S <= 0:
            return []
        memory_entry = self._cache.get(tenant_id)
        if not memory_entry:
            return []
        cached_at, rows = memory_entry
        if time.time() - cached_at > _PORTFOLIO_MIRROR_FAST_CACHE_TTL_S:
            return []
        return [dict(row) for row in rows]

    def _clear_cache(self, tenant_id: str) -> None:
        self._cache.pop(tenant_id, None)
        try:
            self._cache_path(tenant_id).unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Portfolio mirror cache clear failed for tenant %s: %s", tenant_id, exc)

    async def replace_active_positions(
        self,
        tenant_id: str,
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ValueError("tenant_id is required for portfolio operations")
        if not positions:
            logger.warning("Refusing to replace portfolio mirror for tenant %s with zero prepared positions", tenant_id)
            return []

        try:
            async with _supabase_async_client() as client:
                # 1. Delete existing positions for tenant
                delete_res = await client.delete(
                    self.base,
                    headers=_get_headers(),
                    params={"tenant_id": f"eq.{tenant_id}"},
                )
                if not delete_res.is_success:
                    logger.error("Supabase portfolio delete failed: %s", delete_res.text)
                    return []

                # 2. Insert new positions (batch up to 100 at a time)
                inserted: list[dict[str, Any]] = []
                batch_size = 100
                for i in range(0, len(positions), batch_size):
                    batch = positions[i : i + batch_size]
                    rows = []
                    for p in batch:
                        row = {
                            "tenant_id": tenant_id,
                            "symbol": p.get("symbol", ""),
                            "exchange": p.get("exchange", "NSE"),
                            "quantity": float(p.get("quantity", 0) or 0),
                            "market_value": float(p.get("market_value", 0) or 0),
                            "cost_basis": float(p.get("cost_basis", 0) or 0),
                            "active": 1 if p.get("active", True) else 0,
                            "name": p.get("name", ""),
                            "isin": p.get("isin", ""),
                            "amfi": p.get("amfi", ""),
                            "kind": p.get("kind", "equity"),
                            "sector": p.get("sector", ""),
                            "industry": p.get("industry", ""),
                            "avg_cost": float(p.get("avg_cost", 0) or 0),
                            "last_price": float(p.get("last_price", 0) or 0),
                            "as_of": p.get("as_of", ""),
                        }
                        rows.append(_clean_none(row))
                    if rows:
                        res = await client.post(
                            self.base,
                            headers=_get_headers(),
                            json=rows,
                        )
                        if res.is_success:
                            data = res.json()
                            if isinstance(data, list):
                                inserted.extend(data)
                        else:
                            logger.error("Supabase portfolio insert failed: %s", res.text)
                if inserted:
                    self._write_cache(tenant_id, inserted)
                return inserted
        except httpx.TimeoutException:
            logger.debug("Supabase portfolio replace timed out for tenant %s; returning empty write result", tenant_id)
            return []
        except httpx.HTTPError as exc:
            logger.debug("Supabase portfolio replace failed for tenant %s; returning empty write result: %s", tenant_id, exc)
            return []

    async def load_active_positions(self, tenant_id: str) -> list[dict[str, Any]]:
        if not tenant_id:
            raise ValueError("tenant_id is required for portfolio operations")
        fresh_cached = self._read_fresh_memory_cache(tenant_id)
        if fresh_cached:
            return fresh_cached
        try:
            async with _supabase_async_client() as client:
                res = await client.get(
                    self.base,
                    headers=_get_headers(),
                    params={
                        "tenant_id": f"eq.{tenant_id}",
                        "active": "eq.1",
                        "select": "*",
                        "order": "market_value.desc,symbol.asc",
                    },
                )
                if not res.is_success:
                    logger.error("Supabase portfolio load failed: %s", res.text)
                    res.raise_for_status()
                rows = res.json()
                if isinstance(rows, list) and rows:
                    self._write_cache(tenant_id, rows)
                return rows
        except httpx.TimeoutException:
            cached = self._read_cache(tenant_id)
            if cached:
                logger.debug("Supabase portfolio load timed out for tenant %s; serving cached mirror", tenant_id)
                return cached
            logger.warning("Supabase portfolio load timed out for tenant %s and no cached mirror is available", tenant_id)
            raise
        except httpx.HTTPError as exc:
            cached = self._read_cache(tenant_id)
            if cached:
                logger.debug("Supabase portfolio load failed for tenant %s; serving cached mirror: %s", tenant_id, exc)
                return cached
            logger.warning("Supabase portfolio load failed for tenant %s and no cached mirror is available: %s", tenant_id, exc)
            raise

    async def delete_positions(self, tenant_id: str) -> int:
        if not tenant_id:
            raise ValueError("tenant_id is required for portfolio operations")
        try:
            async with _supabase_async_client() as client:
                res = await client.delete(
                    self.base,
                    headers=_get_headers(),
                    params={"tenant_id": f"eq.{tenant_id}"},
                )
                if not res.is_success:
                    logger.error("Supabase portfolio delete failed: %s", res.text)
                    return 0
                # PostgREST returns empty body for delete; we can't get row count easily
                self._clear_cache(tenant_id)
                return 1
        except httpx.TimeoutException:
            logger.debug("Supabase portfolio delete timed out for tenant %s; continuing", tenant_id)
            return 0
        except httpx.HTTPError as exc:
            logger.debug("Supabase portfolio delete failed for tenant %s; continuing: %s", tenant_id, exc)
            return 0


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Memory Store (facts + session_summaries)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SupabaseMemoryStore:
    def __init__(self) -> None:
        self.facts_base = f"{_get_supabase_url()}/rest/v1/facts"
        self.summaries_base = f"{_get_supabase_url()}/rest/v1/session_summaries"

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
    ) -> int:
        if not user_email:
            raise ValueError("user_email is required to persist memory facts")
        row = _clean_none({
            "target_key": target_key,
            "kind": kind,
            "body": body.strip(),
            "confidence": confidence,
            "source_url": source_url,
            "session_id": session_id,
            "user_email": user_email,
            "created_at": float(created_at) if created_at is not None else time.time(),
        })
        async with _supabase_async_client() as client:
            res = await client.post(
                self.facts_base,
                headers=_get_headers(),
                json=row,
            )
            if not res.is_success:
                logger.error("Supabase remember failed: %s", res.text)
                return 0
            return 1

    async def remember_many(
        self,
        facts: list[dict[str, Any]],
    ) -> int:
        count = 0
        for f in facts:
            if not f.get("user_email"):
                raise ValueError("user_email is required for every memory fact")
            try:
                ok = await self.remember(**f)
                count += ok
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
        created_at: float | None = None,
    ) -> None:
        if not user_email:
            raise ValueError("user_email is required to save session summaries")
        row = {
            "session_id": session_id,
            "target_key": target_key,
            "target_display": target_display,
            "summary": summary,
            "metrics_json": json.dumps(metrics or {}),
            "citation_count": citation_count,
            "quality_score": quality_score,
            "user_email": user_email,
            "created_at": float(created_at) if created_at is not None else time.time(),
        }
        async with _supabase_async_client() as client:
            res = await client.post(
                self.summaries_base,
                headers=_get_headers(),
                json=row,
            )
            if not res.is_success:
                logger.error("Supabase save_session_summary failed: %s", res.text)

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
        params: dict[str, Any] = {
            "target_key": f"eq.{target_key}",
            "user_email": f"eq.{user_email}",
            "select": "*",
            "order": "created_at.desc",
            "limit": limit,
        }
        if kind:
            params["kind"] = f"eq.{kind}"
        async with _supabase_async_client() as client:
            res = await client.get(
                self.facts_base,
                headers=_get_headers(),
                params=params,
            )
            if not res.is_success:
                logger.error("Supabase recall failed: %s", res.text)
                return []
            return res.json()

    async def get_facts(
        self,
        target_key: str | None = None,
        *,
        user_email: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to retrieve facts")
        params: dict[str, Any] = {
            "user_email": f"eq.{user_email}",
            "select": "*",
            "order": "created_at.desc",
            "limit": max(1, min(int(limit or 50), 500)),
        }
        if target_key:
            params["target_key"] = f"eq.{target_key}"
        async with _supabase_async_client() as client:
            res = await client.get(
                self.facts_base,
                headers=_get_headers(),
                params=params,
            )
            if not res.is_success:
                logger.error("Supabase get_facts failed: %s", res.text)
                return []
            data = res.json()
            return data if isinstance(data, list) else []

    async def last_summary(
        self,
        target_key: str,
        *,
        user_email: str | None = None,
    ) -> dict | None:
        if not user_email:
            raise ValueError("user_email is required to retrieve session summaries")
        async with _supabase_async_client() as client:
            res = await client.get(
                self.summaries_base,
                headers=_get_headers(),
                params={
                    "target_key": f"eq.{target_key}",
                    "user_email": f"eq.{user_email}",
                    "select": "*",
                    "order": "created_at.desc",
                    "limit": 1,
                },
            )
            if not res.is_success:
                logger.error("Supabase last_summary failed: %s", res.text)
                return None
            data = res.json()
            if data and isinstance(data, list) and len(data) > 0:
                return data[0]
            return None

    async def clear_target(self, target_key: str, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to clear memory facts")
        async with _supabase_async_client() as client:
            res = await client.delete(
                self.facts_base,
                headers=_get_headers(),
                params={
                    "target_key": f"eq.{target_key}",
                    "user_email": f"eq.{user_email}",
                },
            )
            if not res.is_success:
                logger.error("Supabase clear_target failed: %s", res.text)
                return 0
            return 1

    async def delete_session(self, session_id: str, user_email: str | None = None) -> dict[str, int]:
        if not user_email:
            raise ValueError("user_email is required to delete session memory")
        async with _supabase_async_client() as client:
            f_res = await client.delete(
                self.facts_base,
                headers=_get_headers(),
                params={
                    "session_id": f"eq.{session_id}",
                    "user_email": f"eq.{user_email}",
                },
            )
            s_res = await client.delete(
                self.summaries_base,
                headers=_get_headers(),
                params={
                    "session_id": f"eq.{session_id}",
                    "user_email": f"eq.{user_email}",
                },
            )
            return {
                "facts": 1 if f_res.is_success else 0,
                "summaries": 1 if s_res.is_success else 0,
            }

    async def count(self, target_key: str | None = None, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to count memory facts")
        params: dict[str, Any] = {"user_email": f"eq.{user_email}", "select": "*"}
        if target_key:
            params["target_key"] = f"eq.{target_key}"
        async with _supabase_async_client() as client:
            res = await client.get(
                self.facts_base,
                headers=_get_headers(),
                params=params,
            )
            if not res.is_success:
                return 0
            data = res.json()
            return len(data) if isinstance(data, list) else 0

    async def get_targets(self, user_email: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to get targets")
        async with _supabase_async_client() as client:
            res = await client.get(
                self.facts_base,
                headers=_get_headers(),
                params={
                    "user_email": f"eq.{user_email}",
                    "select": "target_key",
                    "order": "created_at.desc",
                    "limit": limit,
                },
            )
            if not res.is_success:
                return []
            data = res.json()
            if not isinstance(data, list):
                return []
            from collections import Counter
            counter = Counter(r["target_key"] for r in data if r.get("target_key"))
            return [{"target": t, "facts": c} for t, c in counter.most_common()]

    async def get_session_count(self, user_email: str | None = None) -> int:
        if not user_email:
            raise ValueError("user_email is required to count sessions")
        async with _supabase_async_client() as client:
            res = await client.get(
                self.summaries_base,
                headers=_get_headers(),
                params={"user_email": f"eq.{user_email}", "select": "*"},
            )
            if not res.is_success:
                return 0
            data = res.json()
            return len(data) if isinstance(data, list) else 0

    async def list_sessions(
        self,
        user_email: str | None = None,
        target_key: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not user_email:
            raise ValueError("user_email is required to list sessions")
        params: dict[str, Any] = {
            "user_email": f"eq.{user_email}",
            "select": "*",
            "order": "created_at.desc",
            "limit": limit,
        }
        if target_key:
            params["target_key"] = f"eq.{target_key}"
        async with _supabase_async_client() as client:
            res = await client.get(
                self.summaries_base,
                headers=_get_headers(),
                params=params,
            )
            if not res.is_success:
                return []
            data = res.json()
            return data if isinstance(data, list) else []


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# State Store (rate limits, verification codes, pending extractions, revoked tokens)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SupabaseStateStore:
    def __init__(self) -> None:
        self.base = f"{_get_supabase_url()}/rest/v1"

    async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        try:
            async with _supabase_async_client() as client:
                # Delete expired windows
                await client.delete(
                    f"{self.base}/rate_limits",
                    headers=_get_headers(),
                    params={"window_start": f"lt.{now - window_seconds}"},
                )
                # Get current row
                res = await client.get(
                    f"{self.base}/rate_limits",
                    headers=_get_headers(),
                    params={"key": f"eq.{key}", "select": "count,window_start"},
                )
                if not res.is_success:
                    logger.error("Supabase rate_limit read failed: %s", res.text)
                    return True
                data = res.json()
                if data and isinstance(data, list) and len(data) > 0:
                    count = data[0].get("count", 0)
                    window_start = data[0].get("window_start", 0)
                    if now - window_start < window_seconds:
                        if count >= limit:
                            return False
                        # Update count
                        u_res = await client.patch(
                            f"{self.base}/rate_limits",
                            headers=_get_headers(),
                            params={"key": f"eq.{key}"},
                            json={"count": count + 1},
                        )
                        if not u_res.is_success:
                            logger.error("Supabase rate_limit update failed: %s", u_res.text)
                        return True
                # Insert new window
                i_res = await client.post(
                    f"{self.base}/rate_limits",
                    headers=_get_headers(),
                    json={"key": key, "count": 1, "window_start": now},
                )
                if not i_res.is_success:
                    logger.error("Supabase rate_limit insert failed: %s", i_res.text)
                return True
        except httpx.TimeoutException as exc:
            logger.warning("Supabase rate_limit timeout; allowing request: %s", exc)
            return True
        except httpx.HTTPError as exc:
            logger.warning("Supabase rate_limit HTTP error; allowing request: %s", exc)
            return True

    async def store_verification_code(self, email: str, code: str, type_: str = "signup") -> None:
        async with _supabase_async_client() as client:
            res = await client.post(
                f"{self.base}/verification_codes",
                headers=_get_headers(),
                json={
                    "email": email.lower().strip(),
                    "code": code,
                    "type": type_,
                    "created_at": _utc_now_iso(),
                },
            )
            if not res.is_success:
                logger.error("Supabase store_verification_code failed: %s", res.text)

    async def verify_and_consume_code(
        self, email: str, code: str, type_: str = "signup", ttl_seconds: int = 600
    ) -> bool:
        now = time.time()
        async with _supabase_async_client() as client:
            res = await client.get(
                f"{self.base}/verification_codes",
                headers=_get_headers(),
                params={
                    "email": f"eq.{email.lower().strip()}",
                    "type": f"eq.{type_}",
                    "select": "code,created_at",
                },
            )
            if not res.is_success:
                return False
            data = res.json()
            if not data or not isinstance(data, list) or len(data) == 0:
                return False
            stored = data[0]
            if now - _to_epoch_seconds(stored.get("created_at")) > ttl_seconds:
                await client.delete(
                    f"{self.base}/verification_codes",
                    headers=_get_headers(),
                    params={
                        "email": f"eq.{email.lower().strip()}",
                        "type": f"eq.{type_}",
                    },
                )
                return False
            if stored["code"] != code.strip():
                return False
            await client.delete(
                f"{self.base}/verification_codes",
                headers=_get_headers(),
                params={
                    "email": f"eq.{email.lower().strip()}",
                    "type": f"eq.{type_}",
                },
            )
            return True

    async def store_pending_extraction(
        self, review_id: str, tenant_id: str, payload: dict[str, Any]
    ) -> None:
        async with _supabase_async_client() as client:
            res = await client.post(
                f"{self.base}/pending_extractions",
                headers=_get_headers(),
                json={
                    "review_id": review_id,
                    "tenant_id": tenant_id,
                    "payload_json": json.dumps(payload),
                    "created_at": _utc_now_iso(),
                },
            )
            if not res.is_success:
                logger.error("Supabase store_pending_extraction failed: %s", res.text)

    async def get_pending_extraction(self, review_id: str) -> dict[str, Any] | None:
        async with _supabase_async_client() as client:
            res = await client.get(
                f"{self.base}/pending_extractions",
                headers=_get_headers(),
                params={
                    "review_id": f"eq.{review_id}",
                    "select": "tenant_id,payload_json",
                },
            )
            if not res.is_success:
                return None
            data = res.json()
            if data and isinstance(data, list) and len(data) > 0:
                return {
                    "tenant_id": data[0]["tenant_id"],
                    "extraction": json.loads(data[0]["payload_json"]),
                }
            return None

    async def get_pending_extractions_by_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        async with _supabase_async_client() as client:
            res = await client.get(
                f"{self.base}/pending_extractions",
                headers=_get_headers(),
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "select": "review_id,payload_json",
                },
            )
            if not res.is_success:
                return []
            data = res.json()
            if data and isinstance(data, list):
                return [
                    {"review_id": d["review_id"], **json.loads(d["payload_json"])}
                    for d in data
                ]
            return []

    async def delete_pending_extraction(self, review_id: str) -> None:
        async with _supabase_async_client() as client:
            await client.delete(
                f"{self.base}/pending_extractions",
                headers=_get_headers(),
                params={"review_id": f"eq.{review_id}"},
            )

    async def is_token_revoked(self, jti: str) -> bool:
        now_iso = _utc_now_iso()
        async with _supabase_async_client() as client:
            # Clean expired
            await client.delete(
                f"{self.base}/revoked_tokens",
                headers=_get_headers(),
                params={"expires_at": f"lt.{now_iso}"},
            )
            res = await client.get(
                f"{self.base}/revoked_tokens",
                headers=_get_headers(),
                params={"jti": f"eq.{jti}", "select": "jti"},
            )
            if not res.is_success:
                return False
            data = res.json()
            return bool(data and isinstance(data, list) and len(data) > 0)

    async def revoke_token(self, jti: str, expires_at: float) -> None:
        async with _supabase_async_client() as client:
            res = await client.post(
                f"{self.base}/revoked_tokens",
                headers=_get_headers(),
                json={
                    "jti": jti,
                    "revoked_at": _utc_now_iso(),
                    "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
                },
            )
            if not res.is_success:
                logger.error("Supabase revoke_token failed: %s", res.text)

    async def cleanup_old_state(self, ttl_seconds: int = 3600) -> None:
        now = time.time()
        async with _supabase_async_client() as client:
            # Verification codes
            await client.delete(
                f"{self.base}/verification_codes",
                headers=_get_headers(),
                params={
                    "created_at": (
                        f"lt.{datetime.fromtimestamp(now - ttl_seconds, tz=timezone.utc).isoformat()}"
                    )
                },
            )
            # Pending extractions > 24h
            await client.delete(
                f"{self.base}/pending_extractions",
                headers=_get_headers(),
                params={
                    "created_at": (
                        f"lt.{datetime.fromtimestamp(now - 86400, tz=timezone.utc).isoformat()}"
                    )
                },
            )
            # Rate limit windows > 1h
            await client.delete(
                f"{self.base}/rate_limits",
                headers=_get_headers(),
                params={"window_start": f"lt.{now - 3600}"},
            )
            # Expired revoked tokens
            await client.delete(
                f"{self.base}/revoked_tokens",
                headers=_get_headers(),
                params={"expires_at": f"lt.{datetime.fromtimestamp(now, tz=timezone.utc).isoformat()}"},
            )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Token Usage
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SupabaseTokenUsageStore:
    def __init__(self) -> None:
        self.base = f"{_get_supabase_url()}/rest/v1/token_usage"

    async def get_weekly_usage(self, user_email: str) -> int:
        week_start = _week_start_utc()
        try:
            async with _supabase_async_client() as client:
                res = await client.get(
                    self.base,
                    headers=_get_headers(),
                    params={
                        "user_email": f"eq.{user_email}",
                        "created_at": f"gte.{week_start.isoformat()}",
                        "select": "total_tokens",
                    },
                )
                if not res.is_success:
                    logger.warning(
                        "Supabase get_weekly_usage non-success: status=%s body=%s",
                        res.status_code,
                        res.text[:300],
                    )
                    return 0
                data = res.json()
                if data and isinstance(data, list):
                    return sum(int(d.get("total_tokens", 0) or 0) for d in data)
                return 0
        except httpx.TimeoutException:
            logger.debug("Supabase token usage lookup timed out for %s; using 0 for this request", user_email)
            return 0
        except httpx.HTTPError as exc:
            logger.debug("Supabase token usage lookup failed for %s; using 0 for this request: %s", user_email, exc)
            return 0

    async def record_usage(
        self,
        user_email: str,
        session_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "",
    ) -> None:
        total = prompt_tokens + completion_tokens
        try:
            async with _supabase_async_client() as client:
                res = await client.post(
                    self.base,
                    headers=_get_headers(),
                    json={
                        "user_email": user_email,
                        "session_id": session_id,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total,
                        "model": model,
                    },
                )
                if not res.is_success:
                    logger.error("Supabase record_usage failed: %s", res.text)
        except httpx.TimeoutException:
            logger.debug("Supabase token usage write timed out for %s; continuing", user_email)
        except httpx.HTTPError as exc:
            logger.debug("Supabase token usage write failed for %s; continuing: %s", user_email, exc)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# In-memory fallback stores (used when SUPABASE_URL is not configured)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _MemoryPortfolioStore:
    def __init__(self) -> None:
        self._data: dict[str, list[dict[str, Any]]] = {}

    async def replace_active_positions(
        self, tenant_id: str, positions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        self._data[tenant_id] = positions
        return positions

    async def load_active_positions(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._data.get(tenant_id, [])

    async def delete_positions(self, tenant_id: str) -> int:
        if tenant_id in self._data:
            del self._data[tenant_id]
            return 1
        return 0


class _MemoryMemoryStore:
    def __init__(self) -> None:
        self._facts: list[dict[str, Any]] = []
        self._summaries: list[dict[str, Any]] = []

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
    ) -> int:
        self._facts.append(
            {
                "target_key": target_key,
                "kind": kind,
                "body": body.strip(),
                "confidence": confidence,
                "source_url": source_url,
                "session_id": session_id,
                "user_email": user_email,
                "created_at": float(created_at) if created_at is not None else time.time(),
            }
        )
        return 1

    async def remember_many(self, facts: list[dict[str, Any]]) -> int:
        for f in facts:
            self._facts.append({**f, "created_at": time.time()})
        return len(facts)

    async def save_session_summary(
        self,
        *,
        session_id: str,
        target_key: str,
        target_display: str,
        summary: str,
        metrics: dict | None = None,
        citation_count: int = 0,
        quality_score: float = 0,
        user_email: str | None = None,
        created_at: float | None = None,
    ) -> None:
        self._summaries.append(
            {
                "session_id": session_id,
                "target_key": target_key,
                "target_display": target_display,
                "summary": summary,
                "metrics_json": json.dumps(metrics or {}),
                "citation_count": citation_count,
                "quality_score": quality_score,
                "user_email": user_email,
                "created_at": float(created_at) if created_at is not None else time.time(),
            }
        )

    async def recall(
        self,
        target_key: str,
        *,
        kind: str | None = None,
        limit: int = 20,
        user_email: str | None = None,
    ) -> list[dict[str, Any]]:
        matches = [
            f
            for f in self._facts
            if f.get("target_key") == target_key and f.get("user_email") == user_email
        ]
        if kind:
            matches = [f for f in matches if f.get("kind") == kind]
        return matches[:limit]

    async def get_facts(
        self,
        target_key: str | None = None,
        *,
        user_email: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        matches = [f for f in self._facts if f.get("user_email") == user_email]
        if target_key:
            matches = [f for f in matches if f.get("target_key") == target_key]
        matches.sort(key=lambda row: float(row.get("created_at", 0) or 0), reverse=True)
        return matches[: max(1, min(int(limit or 50), 500))]

    async def last_summary(
        self, target_key: str, *, user_email: str | None = None
    ) -> dict | None:
        matches = [
            s
            for s in self._summaries
            if s.get("target_key") == target_key and s.get("user_email") == user_email
        ]
        return matches[-1] if matches else None

    async def clear_target(self, target_key: str, user_email: str | None = None) -> int:
        before = len(self._facts)
        self._facts = [
            f
            for f in self._facts
            if not (
                f.get("target_key") == target_key and f.get("user_email") == user_email
            )
        ]
        return before - len(self._facts)

    async def count(self, target_key: str | None = None, user_email: str | None = None) -> int:
        return len(
            [
                f
                for f in self._facts
                if f.get("user_email") == user_email
                and (not target_key or f.get("target_key") == target_key)
            ]
        )

    async def get_targets(self, user_email: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        from collections import Counter

        targets = [
            f["target_key"]
            for f in self._facts
            if f.get("user_email") == user_email and f.get("target_key")
        ]
        counter = Counter(targets)
        return [{"target": t, "facts": c} for t, c in counter.most_common()[:limit]]

    async def get_session_count(self, user_email: str | None = None) -> int:
        return len([s for s in self._summaries if s.get("user_email") == user_email])

    async def list_sessions(
        self, user_email: str | None = None, target_key: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        matches = [
            s
            for s in self._summaries
            if s.get("user_email") == user_email
            and (not target_key or s.get("target_key") == target_key)
        ]
        return matches[:limit]

    async def delete_session(self, session_id: str, user_email: str | None = None) -> dict[str, int]:
        before_f = len(self._facts)
        before_s = len(self._summaries)
        self._facts = [
            f
            for f in self._facts
            if not (
                f.get("session_id") == session_id and f.get("user_email") == user_email
            )
        ]
        self._summaries = [
            s
            for s in self._summaries
            if not (
                s.get("session_id") == session_id and s.get("user_email") == user_email
            )
        ]
        return {"facts": before_f - len(self._facts), "summaries": before_s - len(self._summaries)}

    async def get_active_portfolio_keys(self) -> list[str]:
        return [f["target_key"] for f in self._facts if f.get("target_key")]

    async def update_recent_keys(self, user_email: str, key: str) -> None:
        pass

    async def get_recent_targets(self, user_email: str, limit: int = 12) -> list[str]:
        return []


class _MemoryStateStore:
    def __init__(self) -> None:
        self._rate_limits: dict[str, list[float]] = {}
        self._verification_codes: dict[str, dict] = {}
        self._pending_extractions: dict[str, dict] = {}
        self._revoked_tokens: dict[str, float] = {}

    async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        self._rate_limits[key] = [
            t for t in self._rate_limits.get(key, []) if t > now - window_seconds
        ]
        if len(self._rate_limits[key]) >= limit:
            return False
        self._rate_limits[key].append(now)
        return True

    async def store_verification_code(self, email: str, code: str, type_: str = "signup") -> bool:
        self._verification_codes[f"{email}:{type_}"] = {
            "code": code,
            "created_at": time.time(),
        }
        return True

    async def verify_and_consume_code(
        self, email: str, code: str, type_: str = "signup", ttl_seconds: int = 600
    ) -> bool:
        key = f"{email}:{type_}"
        entry = self._verification_codes.get(key)
        if not entry:
            return False
        if time.time() - entry["created_at"] > ttl_seconds:
            del self._verification_codes[key]
            return False
        if entry["code"] == code.strip():
            del self._verification_codes[key]
            return True
        return False

    async def store_pending_extraction(self, review_id: str, tenant_id: str, payload: dict) -> bool:
        self._pending_extractions[review_id] = {
            "tenant_id": tenant_id,
            "extraction": payload,
        }
        return True

    async def get_pending_extraction(self, review_id: str) -> dict | None:
        entry = self._pending_extractions.get(review_id)
        if entry:
            return {"tenant_id": entry["tenant_id"], "extraction": entry["extraction"]}
        return None

    async def get_pending_extractions_by_tenant(self, tenant_id: str) -> list[dict]:
        return [
            {"review_id": k, **v["extraction"]}
            for k, v in self._pending_extractions.items()
            if v["tenant_id"] == tenant_id
        ]

    async def delete_pending_extraction(self, review_id: str) -> bool:
        self._pending_extractions.pop(review_id, None)
        return True

    async def revoke_token(self, jti: str, expires_at: float) -> bool:
        self._revoked_tokens[jti] = time.time()
        return True

    async def is_token_revoked(self, jti: str) -> bool:
        return jti in self._revoked_tokens


class _MemoryTokenUsageStore:
    def __init__(self) -> None:
        self._usage: list[dict] = []

    async def record_usage(
        self,
        user_email: str,
        session_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "",
    ) -> None:
        self._usage.append(
            {
                "user_email": user_email,
                "session_id": session_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "model": model,
                "created_at": time.time(),
            }
        )

    async def get_weekly_usage(self, user_email: str) -> int:
        week_start = time.time() - 7 * 24 * 3600
        return sum(
            u["total_tokens"]
            for u in self._usage
            if u["user_email"] == user_email and u["created_at"] >= week_start
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Singleton accessors (async-safe)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _is_supabase_configured() -> bool:
    return bool(_get_supabase_url() and _get_supabase_key())


_portfolio_store: SupabasePortfolioStore | _MemoryPortfolioStore | None = None
_memory_store: SupabaseMemoryStore | _MemoryMemoryStore | None = None
_state_store: SupabaseStateStore | _MemoryStateStore | None = None
_token_usage_store: SupabaseTokenUsageStore | _MemoryTokenUsageStore | None = None


def get_portfolio_store() -> SupabasePortfolioStore | _MemoryPortfolioStore:
    global _portfolio_store
    if _portfolio_store is None:
        _portfolio_store = SupabasePortfolioStore() if _is_supabase_configured() else _MemoryPortfolioStore()
    return _portfolio_store


def get_memory_store() -> SupabaseMemoryStore | _MemoryMemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = SupabaseMemoryStore() if _is_supabase_configured() else _MemoryMemoryStore()
    return _memory_store


def get_state_store() -> SupabaseStateStore | _MemoryStateStore:
    global _state_store
    if _state_store is None:
        _state_store = SupabaseStateStore() if _is_supabase_configured() else _MemoryStateStore()
    return _state_store


def get_token_usage_store() -> SupabaseTokenUsageStore | _MemoryTokenUsageStore:
    global _token_usage_store
    if _token_usage_store is None:
        _token_usage_store = SupabaseTokenUsageStore() if _is_supabase_configured() else _MemoryTokenUsageStore()
    return _token_usage_store

