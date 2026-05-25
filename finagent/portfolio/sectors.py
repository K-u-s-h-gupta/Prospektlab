"""ISIN / symbol → sector / industry resolver with bundled fallback + Yahoo cache."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("finagent.portfolio.sectors")

_BUNDLED_PATH = Path(__file__).resolve().parent.parent / "data" / "nifty500_sectors.json"
_BUNDLED: dict[str, dict[str, str]] | None = None

_CACHE_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sector_cache.sqlite3"
_CACHE_TTL_DAYS = 30


def _load_bundled() -> dict[str, dict[str, str]]:
    global _BUNDLED
    if _BUNDLED is not None:
        return _BUNDLED
    if _BUNDLED_PATH.exists():
        try:
            with _BUNDLED_PATH.open("r", encoding="utf-8") as f:
                _BUNDLED = json.load(f)
            logger.info("Loaded %d bundled sector mappings", len(_BUNDLED))
            return _BUNDLED or {}
        except Exception as exc:
            logger.warning("Failed to load bundled sector lookup: %s", exc)
    _BUNDLED = {}
    return _BUNDLED


def _ensure_cache_db() -> None:
    _CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sector_cache (
                key TEXT PRIMARY KEY,
                name TEXT,
                sector TEXT,
                industry TEXT,
                fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sector_cache_fetched ON sector_cache(fetched_at);
            """
        )


def _cache_get(key: str) -> dict[str, str] | None:
    _ensure_cache_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_CACHE_TTL_DAYS)).isoformat()
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        row = conn.execute(
            "SELECT name, sector, industry FROM sector_cache WHERE key = ? AND fetched_at > ?",
            (key, cutoff),
        ).fetchone()
    if row:
        return {"name": row[0], "sector": row[1], "industry": row[2]}
    return None


def _cache_set(key: str, data: dict[str, str]) -> None:
    _ensure_cache_db()
    with sqlite3.connect(str(_CACHE_DB_PATH), check_same_thread=False) as conn:
        conn.execute(
            """
            INSERT INTO sector_cache (key, name, sector, industry, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                name=excluded.name,
                sector=excluded.sector,
                industry=excluded.industry,
                fetched_at=excluded.fetched_at
            """,
            (key, data.get("name", ""), data.get("sector", ""), data.get("industry", ""), datetime.now(timezone.utc).isoformat()),
        )


def _yahoo_lookup(symbol: str) -> dict[str, str] | None:
    """Fetch ticker info from yfinance as fallback."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        sector = info.get("sector") or ""
        industry = info.get("industry") or ""
        name = info.get("longName") or info.get("shortName") or ""
        if sector or industry:
            return {"name": name, "sector": sector, "industry": industry}
    except Exception as exc:
        logger.debug("Yahoo lookup failed for %s: %s", symbol, exc)
    return None


def lookup_by_isin(isin: str) -> dict[str, str] | None:
    """Resolve ISIN to {symbol, exchange, name, sector, industry}."""
    isin = isin.strip().upper()
    if not isin:
        return None
    # 1) bundled
    bundled = _load_bundled()
    if isin in bundled:
        return bundled[isin]
    # 2) cache (by ISIN)
    cached = _cache_get(f"isin:{isin}")
    if cached:
        return cached
    return None


def lookup_by_symbol(symbol: str, exchange: str = "NSE") -> dict[str, str] | None:
    """Resolve symbol to {name, sector, industry}."""
    symbol = symbol.strip().upper()
    if not symbol:
        return None
    cache_key = f"sym:{symbol}.{exchange.upper()}"
    # 1) cache
    cached = _cache_get(cache_key)
    if cached:
        return cached
    # 2) Yahoo fallback
    suffix = ".NS" if exchange.upper() != "BSE" else ".BO"
    yahoo_data = _yahoo_lookup(f"{symbol}{suffix}")
    if yahoo_data:
        _cache_set(cache_key, yahoo_data)
        return yahoo_data
    return None


def enrich_position(position: dict[str, Any]) -> dict[str, Any]:
    """Add name/sector/industry to a position dict if missing."""
    pos = dict(position)
    isin = pos.get("isin", "").strip().upper()
    symbol = pos.get("symbol", "").strip().upper()
    exchange = pos.get("exchange", "NSE")

    # Try ISIN first
    if isin:
        data = lookup_by_isin(isin)
        if data:
            pos.setdefault("name", data.get("name", ""))
            pos.setdefault("sector", data.get("sector", ""))
            pos.setdefault("industry", data.get("industry", ""))
            if not symbol:
                pos["symbol"] = data.get("symbol", symbol)
            if not exchange or exchange == "NSE":
                pos["exchange"] = data.get("exchange", exchange)

    # Then try symbol
    if not pos.get("sector") and symbol:
        data = lookup_by_symbol(symbol, exchange)
        if data:
            pos.setdefault("name", data.get("name", ""))
            pos.setdefault("sector", data.get("sector", ""))
            pos.setdefault("industry", data.get("industry", ""))

    return pos
