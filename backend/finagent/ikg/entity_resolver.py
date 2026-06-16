"""IKG Entity Resolver — CIN/DIN/ISIN-based entity resolution.

Provides canonical identifier resolution for:
  - Company name → CIN (via PostgreSQL staging tables loaded from MCA)
  - NSE/BSE ticker → CIN (via ISIN crossref)
  - Director name → DIN (fuzzy match from MCA director data)
  - ISIN → BSE scrip code / NSE symbol

This is used by the Governance and Accounting agents to look up IKG graph data
for a given company without requiring the user to supply the CIN manually.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.entity_resolver")

_CACHE_TTL = 600  # 10 minutes


class EntityLookupError(Exception):
    """Raised when entity resolution fails due to a DB/infrastructure error (not a miss)."""


@dataclass
class ResolvedCorporateEntity:
    """Result of CIN/DIN entity resolution."""
    cin: str | None = None
    name: str | None = None
    nse_symbol: str | None = None
    bse_scrip_code: str | None = None
    isin: str | None = None
    sector: str | None = None
    confidence: float = 1.0
    source: str = "mca_bulk"


class _TTLCache:
    """Thread-safe dict with per-entry TTL and max-size eviction."""

    def __init__(self, ttl: float = _CACHE_TTL, max_size: int = 10_000) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() - entry[0] > self._ttl:
                del self._store[key]
                return None
            return entry[1]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._store) >= self._max_size:
                cutoff = time.monotonic() - self._ttl
                expired = [k for k, (t, _) in self._store.items() if t < cutoff]
                for k in expired:
                    del self._store[k]
                if len(self._store) >= self._max_size:
                    oldest_key = min(self._store, key=lambda k: self._store[k][0])
                    del self._store[oldest_key]
            self._store[key] = (time.monotonic(), value)


class IKGEntityResolver:
    """Resolves company names/tickers to canonical CINs using PostgreSQL staging tables."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = get_database_url(database_url)
        self._cache = _TTLCache()

    def _connect(self) -> Any:
        try:
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg required for IKG entity resolution") from exc
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=5)

    def _fetch_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not self.database_url:
            return []
        # Let exceptions propagate — callers distinguish DB error from empty result
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]

    def _normalize_name(self, name: str) -> str:
        """Normalize company name for fuzzy matching."""
        name = name.upper().strip()
        for suffix in (
            " LIMITED", " LTD", " LTD.", " PRIVATE", " PVT", " PVT.",
            " INC", " CORP", " CORPORATION", " CO.", " CO",
        ):
            if name.endswith(suffix):
                name = name[: -len(suffix)].strip()
        name = re.sub(r"\bAND\b", " ", name)
        name = re.sub(r"[^A-Z0-9\s]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def _entity_from_company_row(
        self,
        row: dict[str, Any],
        *,
        confidence: float = 1.0,
        source: str = "mca_bulk",
    ) -> ResolvedCorporateEntity:
        return ResolvedCorporateEntity(
            cin=row.get("cin"),
            name=row.get("company_name"),
            nse_symbol=row.get("nse_symbol"),
            bse_scrip_code=row.get("bse_scrip_code"),
            isin=row.get("isin"),
            sector=row.get("sector"),
            confidence=confidence,
            source=source,
        )

    def _entity_from_canonical_row(
        self,
        row: dict[str, Any],
        *,
        confidence: float = 0.9,
        source: str = "ikg_canonical_entities",
    ) -> ResolvedCorporateEntity:
        props = row.get("properties") or {}
        entity_id = str(row.get("entity_id") or "")
        cin = (
            row.get("cin")
            or props.get("cin")
            or row.get("primary_identifier")
            or (entity_id.split(":", 1)[1] if entity_id.startswith("company:") else None)
        )
        return ResolvedCorporateEntity(
            cin=cin,
            name=row.get("company_name") or row.get("display_name"),
            nse_symbol=row.get("nse_symbol") or props.get("nse_symbol"),
            bse_scrip_code=row.get("bse_scrip_code") or props.get("bse_scrip_code"),
            isin=row.get("isin") or props.get("isin"),
            sector=row.get("sector") or props.get("sector") or props.get("industry"),
            confidence=confidence,
            source=source,
        )

    def resolve_by_cin(self, cin: str) -> ResolvedCorporateEntity | None:
        """Look up a company by its CIN. Raises EntityLookupError on DB failure."""
        cached = self._cache.get(f"cin:{cin}")
        if cached is not None:
            return cached
        if not self.database_url:
            return None
        try:
            lookup = cin.upper().strip()
            rows = self._fetch_rows(
                """
                select cin, company_name, nse_symbol, bse_scrip_code, isin, sector
                from ikg_company_master
                where cin = %s
                limit 1
                """,
                (lookup,),
            )
            if rows:
                entity = self._entity_from_company_row(rows[0])
                self._cache.put(f"cin:{lookup}", entity)
                return entity
            rows = self._fetch_rows(
                """
                select entity_id, display_name, primary_identifier, properties
                from ikg_canonical_entities
                where entity_type = 'Company'
                  and (
                    entity_id = %s
                    or primary_identifier = %s
                    or properties->>'cin' = %s
                  )
                limit 1
                """,
                (f"company:{lookup}", lookup, lookup),
            )
            if not rows:
                return None
            entity = self._entity_from_canonical_row(rows[0])
            self._cache.put(f"cin:{lookup}", entity)
            return entity
        except Exception as exc:
            raise EntityLookupError(f"CIN resolution failed for {cin}: {exc}") from exc

    def resolve_by_ticker(self, ticker: str) -> ResolvedCorporateEntity | None:
        """Look up a company by NSE/BSE ticker symbol. Raises EntityLookupError on DB failure."""
        ticker_upper = ticker.upper().strip()
        cached = self._cache.get(f"ticker:{ticker_upper}")
        if cached is not None:
            return cached
        if not self.database_url:
            return None
        try:
            rows = self._fetch_rows(
                """
                select cin, company_name, nse_symbol, bse_scrip_code, isin, sector
                from ikg_company_master
                where nse_symbol = %s or bse_scrip_code = %s
                limit 1
                """,
                (ticker_upper, ticker_upper),
            )
            if rows:
                entity = self._entity_from_company_row(rows[0])
                self._cache.put(f"ticker:{ticker_upper}", entity)
                return entity
            rows = self._fetch_rows(
                """
                select ce.entity_id, ce.display_name, ce.primary_identifier, ce.properties,
                       ea.alias, ea.alias_type, coalesce(ea.confidence, ce.confidence, 0.9) as confidence
                from ikg_canonical_entities ce
                left join ikg_entity_aliases ea
                  on ea.entity_id = ce.entity_id
                where ce.entity_type = 'Company'
                  and (
                    upper(coalesce(ce.properties->>'nse_symbol', '')) = %s
                    or upper(coalesce(ce.properties->>'bse_scrip_code', '')) = %s
                    or upper(coalesce(ea.alias, '')) = %s
                  )
                order by case
                    when upper(coalesce(ce.properties->>'nse_symbol', '')) = %s then 0
                    when upper(coalesce(ea.alias_type, '')) = 'NSE_SYMBOL' then 1
                    when upper(coalesce(ce.properties->>'bse_scrip_code', '')) = %s then 2
                    else 3
                end,
                coalesce(ea.confidence, ce.confidence, 0.9) desc
                limit 1
                """,
                (ticker_upper, ticker_upper, ticker_upper, ticker_upper, ticker_upper),
            )
            if not rows:
                return None
            entity = self._entity_from_canonical_row(
                rows[0],
                confidence=float(rows[0].get("confidence") or 0.9),
                source="ikg_aliases",
            )
            self._cache.put(f"ticker:{ticker_upper}", entity)
            return entity
        except Exception as exc:
            raise EntityLookupError(f"Ticker resolution failed for {ticker}: {exc}") from exc

    def resolve_by_isin(self, isin: str) -> ResolvedCorporateEntity | None:
        """Look up a company by ISIN. Raises EntityLookupError on DB failure."""
        if not isin or not self.database_url:
            return None
        try:
            lookup = isin.upper().strip()
            rows = self._fetch_rows(
                """
                select cin, company_name, nse_symbol, bse_scrip_code, isin, sector
                from ikg_company_master
                where isin = %s
                limit 1
                """,
                (lookup,),
            )
            if rows:
                return self._entity_from_company_row(rows[0])
            rows = self._fetch_rows(
                """
                select ce.entity_id, ce.display_name, ce.primary_identifier, ce.properties,
                       coalesce(ea.confidence, ce.confidence, 0.9) as confidence
                from ikg_canonical_entities ce
                left join ikg_entity_aliases ea
                  on ea.entity_id = ce.entity_id and upper(coalesce(ea.alias, '')) = %s
                where ce.entity_type = 'Company'
                  and (
                    upper(coalesce(ce.properties->>'isin', '')) = %s
                    or upper(coalesce(ea.alias, '')) = %s
                  )
                order by coalesce(ea.confidence, ce.confidence, 0.9) desc
                limit 1
                """,
                (lookup, lookup, lookup),
            )
            if not rows:
                return None
            return self._entity_from_canonical_row(
                rows[0],
                confidence=float(rows[0].get("confidence") or 0.9),
                source="ikg_aliases",
            )
        except Exception as exc:
            raise EntityLookupError(f"ISIN resolution failed for {isin}: {exc}") from exc

    def resolve_by_name(
        self, company_name: str, limit: int = 5
    ) -> list[ResolvedCorporateEntity]:
        """Fuzzy match company name to CIN using PostgreSQL trigram similarity.
        Raises EntityLookupError on DB failure."""
        if not self.database_url:
            return []
        normalized = self._normalize_name(company_name)
        try:
            rows = self._fetch_rows(
                """
                select cin, company_name, nse_symbol, bse_scrip_code, isin, sector,
                       similarity(upper(company_name), %s) as sim
                from ikg_company_master
                where upper(company_name) %% %s
                   or upper(company_name) ilike %s
                order by sim desc
                limit %s
                """,
                (normalized, normalized, f"%{normalized}%", limit),
            )
            if rows:
                return [
                    self._entity_from_company_row(
                        row,
                        confidence=float(row.get("sim") or 0.5),
                    )
                    for row in rows
                ]
            rows = self._fetch_rows(
                """
                select ce.entity_id, ce.display_name, ce.primary_identifier, ce.properties,
                       ea.alias, ea.alias_type,
                       greatest(
                           similarity(upper(ce.display_name), %s),
                           coalesce(similarity(upper(ea.alias), %s), 0)
                       ) as sim
                from ikg_canonical_entities ce
                left join ikg_entity_aliases ea
                  on ea.entity_id = ce.entity_id
                where ce.entity_type = 'Company'
                  and (
                    upper(ce.display_name) %% %s
                    or upper(ce.display_name) ilike %s
                    or upper(coalesce(ea.alias, '')) %% %s
                    or upper(coalesce(ea.alias, '')) ilike %s
                  )
                order by sim desc
                limit %s
                """,
                (
                    normalized,
                    normalized,
                    normalized,
                    f"%{normalized}%",
                    normalized,
                    f"%{normalized}%",
                    limit * 3,
                ),
            )
            matches: list[ResolvedCorporateEntity] = []
            seen: set[str] = set()
            for row in rows:
                entity = self._entity_from_canonical_row(
                    row,
                    confidence=float(row.get("sim") or 0.5),
                    source="ikg_aliases",
                )
                key = entity.cin or entity.name or ""
                if not key or key in seen:
                    continue
                seen.add(key)
                matches.append(entity)
                if len(matches) >= limit:
                    break
            return matches
        except Exception as exc:
            raise EntityLookupError(f"Name resolution failed for '{company_name}': {exc}") from exc

    def resolve(
        self, identifier: str
    ) -> ResolvedCorporateEntity | None:
        """Auto-detect identifier type and resolve.

        Supports:
          - CIN (starts with L/U, 21 chars)
          - ISIN (starts with IN, 12 chars)
          - Ticker (short, no spaces)
          - Company name (fallback, fuzzy match)
        """
        clean = identifier.strip()
        upper = clean.upper()

        if re.match(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$", upper):
            return self.resolve_by_cin(upper)

        if re.match(r"^IN[A-Z0-9]{10}$", upper):
            return self.resolve_by_isin(upper)

        # Ticker: single word, <=15 chars (case-insensitive — users type "infy" not "INFY")
        if len(clean.split()) == 1 and len(clean) <= 15:
            result = self.resolve_by_ticker(upper)
            if result:
                return result

        matches = self.resolve_by_name(clean, limit=1)
        return matches[0] if matches else None


# ── Module-level singleton (thread-safe) ─────────────────────────────────────

_resolver: IKGEntityResolver | None = None
_resolver_lock = threading.Lock()


def get_entity_resolver() -> IKGEntityResolver:
    global _resolver
    if _resolver is None:
        with _resolver_lock:
            if _resolver is None:
                _resolver = IKGEntityResolver()
    return _resolver
