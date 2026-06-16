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
_BUNDLED_BY_SYMBOL: dict[str, dict[str, str]] | None = None

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


def _normalize_symbol_key(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    value = value.removesuffix(".NS").removesuffix(".BO")
    value = value.removesuffix(".NSE").removesuffix(".BSE")
    return value.split(".")[0]


def _load_bundled_by_symbol() -> dict[str, dict[str, str]]:
    """Build a symbol keyed view of the bundled NSE/Nifty sector map."""
    global _BUNDLED_BY_SYMBOL
    if _BUNDLED_BY_SYMBOL is not None:
        return _BUNDLED_BY_SYMBOL

    by_symbol: dict[str, dict[str, str]] = {}
    for isin, row in _load_bundled().items():
        symbol = _normalize_symbol_key(row.get("symbol", ""))
        if not symbol:
            continue
        enriched = dict(row)
        enriched.setdefault("isin", isin)
        enriched.setdefault("exchange", "NSE")
        by_symbol[symbol] = enriched
    _BUNDLED_BY_SYMBOL = by_symbol
    return by_symbol


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


def _is_generic_sector(value: Any) -> bool:
    return str(value or "").strip().lower() in {"", "general", "other", "unknown", "n/a", "na"}


def lookup_by_isin(isin: str) -> dict[str, str] | None:
    """Resolve ISIN to {symbol, exchange, name, sector, industry}.
    
    Priority:
    1. Bundled nifty500_sectors.json (legacy)
    2. Cache
    3. New isin_resolver (hybrid bundle + live NSE/AMFI lookup)
    """
    isin = isin.strip().upper().split(".")[0]
    if not isin:
        return None

    # 1) Try legacy bundled (nifty500_sectors.json)
    bundled = _load_bundled()
    if isin in bundled:
        return bundled[isin]

    # 2) Try cache
    cached = _cache_get(f"isin:{isin}")
    if cached:
        return cached

    # 3) Try new isin_resolver (hybrid approach: bundle + live lookup)
    try:
        from finagent.ingestion.isin_resolver import resolve_isin
        resolution = resolve_isin(isin)
        if resolution and resolution.get("symbol"):
            # Convert resolver output to sectors.py format
            data = {
                "symbol": resolution["symbol"],
                "exchange": resolution.get("exchange", "NSE"),
                "name": resolution.get("name", ""),
                "sector": resolution.get("sector", ""),
                "industry": resolution.get("industry", ""),  # may be empty; symbol lookup will fill it
            }
            _cache_set(f"isin:{isin}", data)
            return data
    except Exception as exc:
        logger.debug("isin_resolver failed for %s: %s", isin, exc)

    return None


def lookup_by_symbol(symbol: str, exchange: str = "NSE") -> dict[str, str] | None:
    """Resolve symbol to {name, sector, industry}."""
    symbol = _normalize_symbol_key(symbol)
    if not symbol:
        return None
    cache_key = f"sym:{symbol}.{exchange.upper()}"
    # 1) Bundled lookup. This avoids slow/stale Yahoo calls for normal NSE symbols
    # and keeps sector allocation deterministic for uploaded holdings.
    bundled = _load_bundled_by_symbol().get(symbol)
    if bundled:
        return bundled

    # 2) cache
    cached = _cache_get(cache_key)
    if cached:
        return cached
    # 3) Yahoo fallback
    suffix = ".NS" if exchange.upper() != "BSE" else ".BO"
    yahoo_data = _yahoo_lookup(f"{symbol}{suffix}")
    if yahoo_data:
        _cache_set(cache_key, yahoo_data)
        return yahoo_data
    return None


def enrich_position(position: dict[str, Any]) -> dict[str, Any]:
    """Add name/sector/industry to a position dict if missing."""
    pos = dict(position)
    isin = pos.get("isin", "").strip().upper().split(".")[0]
    symbol = pos.get("symbol", "").strip().upper()
    exchange = pos.get("exchange", "NSE")

    # Try ISIN first
    if isin:
        data = lookup_by_isin(isin)
        if data:
            if data.get("name"):
                pos["name"] = data["name"]
            if data.get("sector") and _is_generic_sector(pos.get("sector")):
                pos["sector"] = data["sector"]
            if data.get("industry") and not pos.get("industry"):
                pos["industry"] = data["industry"]
            clean_sym = symbol.split(".")[0]
            # Only overwrite symbol if it looks like an ISIN or is missing
            is_isin_like = len(clean_sym) >= 10 and clean_sym[:2] == "IN" and clean_sym[2:].isalnum()
            if not symbol or clean_sym == isin or is_isin_like or len(clean_sym) >= 12:
                pos["symbol"] = data.get("symbol", symbol)
                symbol = str(pos.get("symbol") or "").strip().upper()
            if not exchange or exchange == "NSE":
                pos["exchange"] = data.get("exchange", exchange)
                exchange = pos.get("exchange", exchange)

    # Then try symbol (for sector or industry if either is still missing)
    if exchange.upper() != "AMFI" and symbol and (_is_generic_sector(pos.get("sector")) or not pos.get("industry")):
        data = lookup_by_symbol(symbol, exchange)
        if data:
            if data.get("name") and (not pos.get("name") or len(pos.get("name", "")) < 3):
                pos["name"] = data["name"]
            if data.get("sector") and _is_generic_sector(pos.get("sector")):
                pos["sector"] = data["sector"]
            if data.get("industry") and not pos.get("industry"):
                pos["industry"] = data["industry"]

    return pos
