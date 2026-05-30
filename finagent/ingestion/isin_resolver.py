"""ISIN resolver with hybrid bundled + live lookup capability.

Resolves ISINs to {symbol, name, exchange, kind, sector} using:
1. Bundle: pre-built isin_master.json (~7,500 Indian equity/MF ISINs)
2. Live lookups: NSE API for unknown equity ISINs; AMFI API for unknown MF ISINs
3. Cache: SQLite per-instrument 30-day TTL to avoid repeated API calls
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from finagent.paths import finagent_data_path

logger = logging.getLogger("finagent.ingestion.isin_resolver")

# Singleton instance
_resolver: ISINResolver | None = None


class ISINResolution:
    """Resolution result for a single ISIN."""

    def __init__(
        self,
        isin: str,
        symbol: str = "",
        name: str = "",
        exchange: str = "NSE",
        kind: Literal["equity", "mf", "etf", "bond", "other"] = "equity",
        sector: str = "",
        source: str = "unknown",
    ):
        self.isin = isin.upper()
        self.symbol = symbol.upper()
        self.name = name
        self.exchange = exchange.upper()
        self.kind = kind
        self.sector = sector
        self.source = source  # "bundle", "nse_api", "amfi_api", "cache", "unknown"

    def to_dict(self) -> dict[str, str]:
        return {
            "isin": self.isin,
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "kind": self.kind,
            "sector": self.sector,
            "source": self.source,
        }


class ISINResolver:
    """Hybrid ISIN resolver: bundle + live + cache."""

    def __init__(self):
        self.bundle: dict[str, dict[str, str]] = {}  # ISIN -> {symbol, name, exchange, kind, sector}
        self.cache_db: str | None = None
        self._load_bundle()
        self._init_cache_db()

    def _load_bundle(self) -> None:
        """Load bundled isin_master.json into memory."""
        bundle_path = Path(__file__).resolve().parent.parent / "data" / "isin_master.json"
        if not bundle_path.exists():
            logger.warning("isin_master.json not found at %s; bundle empty", bundle_path)
            self.bundle = {}
            return

        try:
            with open(bundle_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.bundle = data if isinstance(data, dict) else {}
            logger.info("Loaded ISIN bundle: %d entries", len(self.bundle))
        except Exception as exc:
            logger.error("Failed to load isin_master.json: %s", exc)
            self.bundle = {}

    def _init_cache_db(self) -> None:
        """Initialize SQLite cache for live lookups (30-day TTL per ISIN)."""
        try:
            cache_dir = finagent_data_path("cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_db = str(cache_dir / "isin_cache.db")

            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS isin_cache (
                    isin TEXT PRIMARY KEY,
                    symbol TEXT,
                    name TEXT,
                    exchange TEXT,
                    kind TEXT,
                    sector TEXT,
                    source TEXT,
                    cached_at TIMESTAMP,
                    ttl_days INTEGER
                )
            """)
            conn.commit()
            conn.close()
            logger.info("ISIN cache DB initialized: %s", self.cache_db)
        except Exception as exc:
            logger.error("Failed to init ISIN cache DB: %s", exc)
            self.cache_db = None

    def _get_cached(self, isin: str) -> ISINResolution | None:
        """Retrieve cached resolution if within TTL."""
        if not self.cache_db:
            return None

        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT symbol, name, exchange, kind, sector, source, cached_at, ttl_days
                FROM isin_cache WHERE isin = ?
                """,
                (isin.upper(),),
            )
            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            symbol, name, exchange, kind, sector, source, cached_at_str, ttl_days = row
            cached_at = datetime.fromisoformat(cached_at_str) if cached_at_str else datetime.now()
            ttl_seconds = (ttl_days or 30) * 86400
            age_seconds = (datetime.now() - cached_at).total_seconds()

            if age_seconds < ttl_seconds:
                logger.debug("Cache hit for ISIN %s (age=%.1fs)", isin, age_seconds)
                return ISINResolution(
                    isin=isin,
                    symbol=symbol or "",
                    name=name or "",
                    exchange=exchange or "NSE",
                    kind=kind or "equity",
                    sector=sector or "",
                    source="cache",
                )

            logger.debug("Cache expired for ISIN %s (age=%.1fs > ttl=%d days)", isin, age_seconds, ttl_days or 30)
        except Exception as exc:
            logger.warning("Cache lookup failed for ISIN %s: %s", isin, exc)

        return None

    def _set_cached(
        self,
        resolution: ISINResolution,
        ttl_days: int = 30,
    ) -> None:
        """Store resolution in cache."""
        if not self.cache_db:
            return

        try:
            conn = sqlite3.connect(self.cache_db)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO isin_cache
                (isin, symbol, name, exchange, kind, sector, source, cached_at, ttl_days)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution.isin,
                    resolution.symbol,
                    resolution.name,
                    resolution.exchange,
                    resolution.kind,
                    resolution.sector,
                    resolution.source,
                    datetime.now().isoformat(),
                    ttl_days,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Cache write failed for ISIN %s: %s", resolution.isin, exc)

    def _fetch_nse_live(self, isin: str) -> ISINResolution | None:
        """Fetch equity ISIN from live NSE API (async-compatible wrapper)."""
        try:
            import httpx

            isin_upper = isin.upper()
            # NSE expects lowercase ISINs in some endpoints
            url = f"https://www.nseindia.com/api/equity-search?q={isin_upper}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            with httpx.Client(headers=headers, timeout=10.0) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()

                if data.get("values"):
                    # NSE returns array of matches; take first
                    match = data["values"][0]
                    symbol = match.get("1") or ""  # Symbol is in index 1
                    name = match.get("2") or ""  # Name is in index 2

                    logger.info("NSE live lookup: %s -> %s (%s)", isin, symbol, name)
                    return ISINResolution(
                        isin=isin,
                        symbol=symbol.upper(),
                        name=name,
                        exchange="NSE",
                        kind="equity",
                        source="nse_api",
                    )
        except Exception as exc:
            logger.debug("NSE live lookup failed for ISIN %s: %s", isin, exc)

        return None

    def _fetch_amfi_live(self, isin: str) -> ISINResolution | None:
        """Fetch MF ISIN from live AMFI API (async-compatible wrapper)."""
        try:
            import httpx

            isin_upper = isin.upper()
            # AMFI maintains a public CSV of MF scheme data
            # For now, return None; in Phase 2 we can cache AMFI's full CSV
            # and lookup ISINs from it.
            logger.debug("AMFI live lookup not yet implemented for ISIN %s", isin)
        except Exception as exc:
            logger.debug("AMFI live lookup failed for ISIN %s: %s", isin, exc)

        return None

    def resolve(self, isin: str, kind_hint: str = "") -> ISINResolution:
        """Resolve ISIN to symbol/name/sector.

        Priority:
        1. Check bundle
        2. Check cache
        3. Fetch live (NSE for equity, AMFI for MF)
        4. Return unknown result

        Args:
            isin: ISIN code (e.g., "INE017A01026")
            kind_hint: optional hint ("equity", "mf") to guide live lookup

        Returns:
            ISINResolution with best available data
        """
        isin = isin.upper()
        if not isin:
            return ISINResolution(isin=isin, source="unknown")

        # 1. Check bundle
        if isin in self.bundle:
            data = self.bundle[isin]
            logger.debug("Bundle hit for ISIN %s", isin)
            return ISINResolution(
                isin=isin,
                symbol=data.get("symbol", ""),
                name=data.get("name", ""),
                exchange=data.get("exchange", "NSE"),
                kind=data.get("kind", "equity"),
                sector=data.get("sector", ""),
                source="bundle",
            )

        # 2. Check cache
        cached = self._get_cached(isin)
        if cached:
            return cached

        # 3. Try live lookup (best-effort, no error propagation)
        live_result = None
        if kind_hint.lower() == "mf":
            live_result = self._fetch_amfi_live(isin)
        else:
            # Default to NSE for equity or unknown
            live_result = self._fetch_nse_live(isin)

        if live_result:
            self._set_cached(live_result, ttl_days=30)
            return live_result

        # 4. Return unknown
        logger.warning("ISIN resolution failed: %s (not in bundle, cache, or live APIs)", isin)
        return ISINResolution(isin=isin, source="unknown")


def get_resolver() -> ISINResolver:
    """Lazy-load singleton ISIN resolver."""
    global _resolver
    if _resolver is None:
        _resolver = ISINResolver()
    return _resolver


def resolve_isin(isin: str, kind_hint: str = "") -> dict[str, str]:
    """Module-level convenience function for ISIN resolution.

    Args:
        isin: ISIN code
        kind_hint: optional kind hint ("equity", "mf")

    Returns:
        dict with keys: isin, symbol, name, exchange, kind, sector, source
    """
    resolver = get_resolver()
    resolution = resolver.resolve(isin, kind_hint=kind_hint)
    return resolution.to_dict()


def resolve_isin_batch(isins: list[str]) -> dict[str, dict[str, str]]:
    """Resolve multiple ISINs in batch.

    Args:
        isins: list of ISIN codes

    Returns:
        dict mapping ISIN -> resolution dict
    """
    resolver = get_resolver()
    return {isin: resolver.resolve(isin).to_dict() for isin in isins}
