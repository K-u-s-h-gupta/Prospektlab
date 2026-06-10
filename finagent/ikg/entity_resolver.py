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
import os
import re
from dataclasses import dataclass
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.entity_resolver")


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


class IKGEntityResolver:
    """Resolves company names/tickers to canonical CINs using PostgreSQL staging tables."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = get_database_url(database_url)
        self._in_memory_cache: dict[str, ResolvedCorporateEntity] = {}

    def _connect(self) -> Any:
        try:
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg required for IKG entity resolution") from exc
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=5)

    def _fetch_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not self.database_url:
            return []
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("IKG resolver SQL fetch failed: %s", exc)
            return []

    def _normalize_name(self, name: str) -> str:
        """Normalize company name for fuzzy matching."""
        name = name.upper().strip()
        # Remove common suffixes
        for suffix in (
            " LIMITED", " LTD", " LTD.", " PRIVATE", " PVT", " PVT.",
            " INC", " CORP", " CORPORATION", " CO.", " CO",
        ):
            if name.endswith(suffix):
                name = name[: -len(suffix)].strip()
        # Remove punctuation noise
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
        """Look up a company by its CIN."""
        if cin in self._in_memory_cache:
            return self._in_memory_cache[cin]
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
                self._in_memory_cache[lookup] = entity
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
            self._in_memory_cache[cin] = entity
            self._in_memory_cache[lookup] = entity
            return entity
        except Exception as exc:
            logger.debug("CIN resolution failed for %s: %s", cin, exc)
            return None

    def resolve_by_ticker(self, ticker: str) -> ResolvedCorporateEntity | None:
        """Look up a company by NSE/BSE ticker symbol."""
        ticker_upper = ticker.upper().strip()
        if ticker_upper in self._in_memory_cache:
            return self._in_memory_cache[ticker_upper]
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
                self._in_memory_cache[ticker_upper] = entity
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
            self._in_memory_cache[ticker_upper] = entity
            return entity
        except Exception as exc:
            logger.debug("Ticker resolution failed for %s: %s", ticker, exc)
            return None

    def resolve_by_isin(self, isin: str) -> ResolvedCorporateEntity | None:
        """Look up a company by ISIN."""
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
            logger.debug("ISIN resolution failed for %s: %s", isin, exc)
            return None

    def resolve_by_name(
        self, company_name: str, limit: int = 5
    ) -> list[ResolvedCorporateEntity]:
        """Fuzzy match company name to CIN using PostgreSQL trigram similarity."""
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
            logger.debug("Name resolution failed for '%s': %s", company_name, exc)
            return []

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

        # CIN pattern: L/U + 5 digits + state code (2 chars) + year (4) + type (3) + 6 digits
        if re.match(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$", clean.upper()):
            return self.resolve_by_cin(clean.upper())

        # ISIN pattern: IN + 10 alphanumeric
        if re.match(r"^IN[A-Z0-9]{10}$", clean.upper()):
            return self.resolve_by_isin(clean.upper())

        # Ticker: short, no spaces, often uppercase
        if len(clean.split()) == 1 and len(clean) <= 15 and clean.isupper():
            result = self.resolve_by_ticker(clean)
            if result:
                return result

        # Fallback: name-based resolution
        matches = self.resolve_by_name(clean, limit=1)
        return matches[0] if matches else None


# ── Module-level singleton ────────────────────────────────────────────────────

_resolver: IKGEntityResolver | None = None


def get_entity_resolver() -> IKGEntityResolver:
    global _resolver
    if _resolver is None:
        _resolver = IKGEntityResolver()
    return _resolver
