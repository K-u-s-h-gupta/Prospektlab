"""Shared IKG service for chat, deep research, and MCP access.

This module wraps the graph client plus Postgres-backed staging tables into a
single provenance-first interface. The goal is to keep IKG reusable without
forcing the chat agent to trust graph data blindly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from finagent.analysis.conflicts import MetricObservation
from finagent.ikg.db import connect_postgres, ensure_ikg_runtime_tables, get_database_url
from finagent.ikg.entity_resolver import IKGEntityResolver, ResolvedCorporateEntity, get_entity_resolver
from finagent.ikg.graph_client import get_graph_client

logger = logging.getLogger("finagent.ikg.service")

_CACHE_TTL_S = 300.0
_bundle_cache: dict[str, tuple[float, "IKGCompanyBundle"]] = {}


@dataclass
class IKGCompanyBundle:
    status: str = "unavailable"  # ok | partial | unavailable
    depth: str = "standard"  # standard | extended | forensic
    entity: dict[str, Any] = field(default_factory=dict)
    company: dict[str, Any] | None = None
    governance: dict[str, Any] = field(default_factory=dict)
    ownership: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    financials: dict[str, Any] = field(default_factory=dict)
    documents: dict[str, Any] = field(default_factory=dict)
    facts: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    as_of_date: str | None = None
    source_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_public_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "depth": self.depth,
            "entity": self.entity,
            "company": self.company,
            "governance": self.governance,
            "ownership": self.ownership,
            "risk": self.risk,
            "financials": self.financials,
            "documents": self.documents,
            "facts": self.facts,
            "coverage": self.coverage,
            "confidence": round(self.confidence, 3),
            "as_of_date": self.as_of_date,
            "source_refs": self.source_refs,
            "warnings": self.warnings,
        }

    def trusted_facts(self, *, limit: int = 8) -> list[dict[str, Any]]:
        out = [f for f in self.facts if (f.get("trust") or "") == "trusted"]
        if out:
            return out[:limit]
        return self.facts[:limit]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_dateish(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if not text:
        return None
    return text[:10] if len(text) >= 10 else text


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        clean = (url or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _collect_source_refs(*payloads: Any) -> list[str]:
    urls: list[str] = []
    for payload in payloads:
        if payload is None:
            continue
        if isinstance(payload, dict):
            value = payload.get("source_url")
            if isinstance(value, str):
                urls.append(value)
            nested = payload.values()
        elif isinstance(payload, list):
            nested = payload
        else:
            continue
        for item in nested:
            if isinstance(item, (dict, list)):
                urls.extend(_collect_source_refs(item))
    return _dedupe_urls(urls)


def _ownership_rows_to_edges(rows: list[dict[str, Any]], cin: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        owner_vertex_id = str(row.get("owner_vertex_id") or "")
        source_url = row.get("source_url")
        out.append(
            {
                "from": owner_vertex_id,
                "to": f"company:{cin}",
                "label": "OWNS_STAKE_IN",
                "percentage": _safe_float(row.get("holding_pct")) or 0.0,
                "pledge_pct": _safe_float(row.get("pledge_pct")) or 0.0,
                "quarter": row.get("quarter"),
                "owner_name": row.get("owner_name"),
                "source_table": row.get("source_table"),
                "source_uid": row.get("source_uid"),
                "source_url": source_url,
                "updated_at": row.get("updated_at"),
            }
        )
    return out


def _summarize_ownership_rows(rows: list[dict[str, Any]], cin: str) -> dict[str, Any]:
    total_holding = 0.0
    total_pledged = 0.0
    pledged_promoters: list[dict[str, Any]] = []
    for row in rows:
        holding = _safe_float(row.get("holding_pct")) or 0.0
        pledge_pct = _safe_float(row.get("pledge_pct")) or 0.0
        total_holding += holding
        if pledge_pct > 0:
            pledged_value = holding * (pledge_pct / 100.0)
            total_pledged += pledged_value
            pledged_promoters.append(
                {
                    "promoter": row.get("owner_name") or str(row.get("owner_vertex_id") or "").replace("promoter:", ""),
                    "holding_pct": holding,
                    "pledge_pct_of_holding": pledge_pct,
                    "quarter": row.get("quarter"),
                    "source_table": row.get("source_table"),
                    "source_uid": row.get("source_uid"),
                    "source_url": row.get("source_url"),
                }
            )
    return {
        "cin": cin,
        "total_promoter_holding_pct": round(total_holding, 2),
        "total_pledge_pct": round(total_pledged, 2),
        "pledged_promoters": pledged_promoters,
        "pledge_flag": "HIGH" if total_pledged > 50 else ("MODERATE" if total_pledged > 25 else "LOW"),
        "as_of_date": _latest_as_of(rows),
    }


def _latest_as_of(*payloads: Any) -> str | None:
    keys = (
        "updated_at",
        "as_of_date",
        "announced_at",
        "fetched_at",
        "filed_date",
        "created_at",
        "report_date",
        "period_end",
    )
    candidates: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in keys:
                    normalized = _normalize_dateish(value)
                    if normalized:
                        candidates.append(normalized)
                if isinstance(value, (dict, list)):
                    _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    for payload in payloads:
        _walk(payload)

    if not candidates:
        return None
    return max(candidates)


def _coverage_state(*values: Any) -> str:
    present = 0
    total = 0
    for value in values:
        total += 1
        if value is None:
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        present += 1
    if total == 0 or present == 0:
        return "missing"
    if present == total:
        return "complete"
    return "partial"


def _trust_for_fact(source_url: str | None, *, confidence: float | None = None) -> str:
    url = (source_url or "").lower()
    official_markers = (
        "nseindia.com",
        "bseindia.com",
        "mca.gov.in",
        "sebi.gov.in",
        "rbi.org.in",
    )
    if any(marker in url for marker in official_markers):
        return "trusted"
    if (confidence or 0.0) >= 0.85:
        return "trusted"
    if (confidence or 0.0) >= 0.65:
        return "supporting"
    return "candidate"


def _push_fact(
    facts: list[dict[str, Any]],
    *,
    category: str,
    headline: str,
    detail: str,
    source_url: str | None = None,
    as_of_date: str | None = None,
    confidence: float | None = None,
) -> None:
    facts.append(
        {
            "category": category,
            "headline": headline,
            "detail": detail,
            "source_url": source_url,
            "as_of_date": as_of_date,
            "confidence": round(confidence or 0.0, 3),
            "trust": _trust_for_fact(source_url, confidence=confidence),
        }
    )


class IKGService:
    """Read-only IKG accessor with lightweight caching."""

    def __init__(
        self,
        *,
        graph_client=None,
        entity_resolver: IKGEntityResolver | None = None,
        database_url: str | None = None,
    ) -> None:
        self.graph_client = graph_client or get_graph_client()
        self.entity_resolver = entity_resolver or get_entity_resolver()
        self.database_url = get_database_url(database_url)

    def _record_usage(self) -> None:
        try:
            from finagent.state.session_context import record_mcp

            record_mcp("ikg")
        except Exception:
            pass

    def _resolve(
        self,
        *,
        identifier: str | None = None,
        cin: str | None = None,
        ticker: str | None = None,
        isin: str | None = None,
        name: str | None = None,
        aliases: list[str] | None = None,
    ) -> ResolvedCorporateEntity | None:
        candidates: list[str] = []
        if cin:
            match = self.entity_resolver.resolve_by_cin(cin)
            if match:
                return match
        if ticker:
            normalized = ticker.replace(".NS", "").replace(".BO", "").strip().upper()
            match = self.entity_resolver.resolve_by_ticker(normalized)
            if match:
                return match
            candidates.append(normalized)
        if isin:
            match = self.entity_resolver.resolve_by_isin(isin)
            if match:
                return match
            candidates.append(isin)
        for raw in (identifier, name):
            if raw:
                candidates.append(raw)
        for alias in aliases or []:
            if alias:
                candidates.append(alias)
        seen: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            match = self.entity_resolver.resolve(normalized)
            if match:
                return match
        return None

    def _fetch_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        if not self.database_url:
            return []
        try:
            from psycopg.rows import dict_row
        except ImportError:
            return []

        try:
            ensure_ikg_runtime_tables(self.database_url)
            with connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.debug("IKG SQL fetch failed: %s", exc)
            return []

    async def get_company_master(self, cin: str) -> dict[str, Any] | None:
        rows = await asyncio.to_thread(
            self._fetch_rows,
            """
            select cin, company_name, nse_symbol, bse_scrip_code, isin, sector, industry
            from ikg_company_master
            where cin = %s
            limit 1
            """,
            (cin,),
        )
        if rows:
            return rows[0]
        rows = await asyncio.to_thread(
            self._fetch_rows,
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
            (f"company:{cin}", cin, cin),
        )
        if not rows:
            return None
        row = rows[0]
        props = row.get("properties") or {}
        entity_id = str(row.get("entity_id") or "")
        return {
            "cin": props.get("cin") or row.get("primary_identifier") or (entity_id.split(":", 1)[1] if entity_id.startswith("company:") else cin),
            "company_name": row.get("display_name"),
            "nse_symbol": props.get("nse_symbol"),
            "bse_scrip_code": props.get("bse_scrip_code"),
            "isin": props.get("isin"),
            "sector": props.get("sector"),
            "industry": props.get("industry"),
            "source_table": "ikg_canonical_entities",
        }

    async def get_ownership_summary(self, cin: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._fetch_rows,
            """
            with latest as (
                select quarter
                from ikg_ownership_summary
                where company_vertex_id = %s
                order by updated_at desc nulls last, quarter desc nulls last
                limit 1
            )
            select company_vertex_id, owner_vertex_id, owner_name, quarter, holding_pct, pledge_pct,
                   source_table, source_uid, null::text as source_url, updated_at
            from ikg_ownership_summary
            where company_vertex_id = %s
              and (
                not exists (select 1 from latest)
                or quarter = (select quarter from latest)
              )
            order by holding_pct desc nulls last, updated_at desc nulls last
            limit %s
            """,
            (f"company:{cin}", f"company:{cin}", limit),
        )

    async def get_auditor_history(self, cin: str, *, limit: int = 8) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._fetch_rows,
            """
            select cin, auditor_name, role, fiscal_year, source_uid, source_url, parser_version, fetched_at
            from auditor_history_raw
            where cin = %s
            order by fiscal_year desc nulls last, fetched_at desc
            limit %s
            """,
            (cin, limit),
        )

    async def get_related_party_transactions(self, cin: str, *, limit: int = 12) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._fetch_rows,
            """
            select cin, category, fact_name, fact_key, value_text, value_numeric,
                   period_start, period_end, instant, source_url, fetched_at
            from corporate_xbrl_facts
            where cin = %s
              and category = 'related_party_transactions'
            order by coalesce(period_end, instant) desc nulls last, fetched_at desc
            limit %s
            """,
            (cin, limit),
        )

    async def get_xbrl_facts(
        self,
        cin: str,
        *,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if category:
            sql = """
                select cin, category, fact_name, fact_key, value_text, value_numeric,
                       period_start, period_end, instant, source_url, fetched_at
                from corporate_xbrl_facts
                where cin = %s and category = %s
                order by coalesce(period_end, instant) desc nulls last, fetched_at desc
                limit %s
            """
            params = (cin, category, limit)
        else:
            sql = """
                select cin, category, fact_name, fact_key, value_text, value_numeric,
                       period_start, period_end, instant, source_url, fetched_at
                from corporate_xbrl_facts
                where cin = %s
                order by coalesce(period_end, instant) desc nulls last, fetched_at desc
                limit %s
            """
            params = (cin, limit)
        return await asyncio.to_thread(self._fetch_rows, sql, params)

    async def get_corporate_filings(self, cin: str, *, limit: int = 12) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._fetch_rows,
            """
            with filings as (
                select exchange, source_uid, category, symbol, scrip_code, cin, company_name,
                       announced_at, attachment_url, source_url,
                       null::date as period_start,
                       null::date as period_end,
                       announced_at::date as as_of_date,
                       jsonb_build_object(
                           'title', title,
                           'description', description,
                           'attachment_text_length', attachment_text_length,
                           'attachment_extraction_status', attachment_extraction_status,
                           'source_table', 'corporate_filings_raw'
                       ) as summary_json,
                       fetched_at,
                       coalesce(announced_at, fetched_at) as sort_at
                from corporate_filings_raw
                where cin = %s

                union all

                select exchange, source_uid, category, symbol, scrip_code, cin, company_name,
                       announced_at, attachment_url, source_url, period_start, period_end,
                       as_of_date, summary_json, fetched_at,
                       coalesce(announced_at, as_of_date::timestamptz, period_end::timestamptz, fetched_at) as sort_at
                from xbrl_filings_raw
                where cin = %s
            )
            select exchange, source_uid, category, symbol, scrip_code, cin, company_name,
                   announced_at, attachment_url, source_url, period_start, period_end,
                   as_of_date, summary_json, fetched_at
            from filings
            order by sort_at desc nulls last, fetched_at desc
            limit %s
            """,
            (cin, cin, limit),
        )

    async def get_corporate_actions(self, cin: str, *, limit: int = 12) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._fetch_rows,
            """
            select exchange, source_uid, cin, symbol, scrip_code, company_name, action_type,
                   announced_at, null::date as as_of_date, raw_json as summary_json,
                   attachment_url, source_url, fetched_at
            from corporate_actions_raw
            where cin = %s
            order by announced_at desc nulls last, fetched_at desc
            limit %s
            """,
            (cin, limit),
        )

    async def get_concall_transcripts(self, cin: str, *, limit: int = 8) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._fetch_rows,
            """
            select cin, symbol, company_name, quarter_label, fiscal_year, announced_at,
                   attachment_url, source_url, fetched_at
            from concall_transcripts_raw
            where cin = %s
            order by announced_at desc nulls last, fetched_at desc
            limit %s
            """,
            (cin, limit),
        )

    async def search_document_sections(
        self,
        cin: str,
        *,
        query: str | None = None,
        document_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        clauses = [
            """(
                metadata->>'cin' = %s
                or metadata->>'company_cin' = %s
                or metadata->>'company_identifier' = %s
            )"""
        ]
        params: list[Any] = [cin, cin, cin]
        if document_type:
            clauses.append("document_type = %s")
            params.append(document_type)
        if query:
            clauses.append(
                """to_tsvector(
                       'english',
                       coalesce(title, '') || ' ' || coalesce(text, '') || ' ' || coalesce(metadata::text, '')
                   ) @@ plainto_tsquery('english', %s)"""
            )
            params.append(query)
        params.append(limit)
        sql = f"""
            select document_uid, document_type, section_type, title, page_start, page_end,
                   left(text, 1200) as text, source_url, metadata, updated_at
            from document_sections
            where {' and '.join(clauses)}
            order by updated_at desc
            limit %s
        """
        return await asyncio.to_thread(self._fetch_rows, sql, tuple(params))

    async def get_fact_provenance(
        self,
        *,
        subject_entity_id: str,
        predicate: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if predicate:
            sql = """
                select fact_id, subject_entity_id, predicate, object_entity_id, object_value,
                       value_numeric, as_of_date, source_table, source_uid, source_url,
                       evidence_text, confidence, properties, updated_at
                from ikg_facts
                where subject_entity_id = %s and predicate = %s
                order by coalesce(as_of_date, updated_at::date) desc nulls last, updated_at desc
                limit %s
            """
            params = (subject_entity_id, predicate, limit)
        else:
            sql = """
                select fact_id, subject_entity_id, predicate, object_entity_id, object_value,
                       value_numeric, as_of_date, source_table, source_uid, source_url,
                       evidence_text, confidence, properties, updated_at
                from ikg_facts
                where subject_entity_id = %s
                order by coalesce(as_of_date, updated_at::date) desc nulls last, updated_at desc
                limit %s
            """
            params = (subject_entity_id, limit)
        return await asyncio.to_thread(self._fetch_rows, sql, params)

    async def list_candidate_facts(
        self,
        *,
        status: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        sql = """
            select id, subject_entity_id, predicate, object_entity_id, object_value, value_numeric,
                   confidence, candidate_status, validation_state, source_type, source_url,
                   evidence_text, metadata, extracted_at, promoted_at
            from ikg_candidate_facts
        """
        params: list[Any] = []
        if status:
            sql += " where candidate_status = %s"
            params.append(status)
        sql += " order by extracted_at desc limit %s"
        params.append(limit)
        return await asyncio.to_thread(self._fetch_rows, sql, tuple(params))

    async def submit_candidate_fact(
        self,
        *,
        subject_entity_id: str,
        predicate: str,
        object_entity_id: str | None = None,
        object_value: str | None = None,
        value_numeric: float | None = None,
        confidence: float = 0.5,
        source_type: str = "dreaming",
        source_url: str | None = None,
        evidence_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.database_url:
            return {"status": "unavailable", "warning": "database not configured"}
        ensure_ikg_runtime_tables(self.database_url)
        try:
            import psycopg

            with connect_postgres(self.database_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into ikg_candidate_facts (
                            subject_entity_id, predicate, object_entity_id, object_value, value_numeric,
                            confidence, candidate_status, validation_state, source_type, source_url,
                            evidence_text, metadata
                        )
                        values (%s, %s, %s, %s, %s, %s, 'candidate', 'pending', %s, %s, %s, %s::jsonb)
                        returning id, extracted_at
                        """,
                        (
                            subject_entity_id,
                            predicate,
                            object_entity_id,
                            object_value,
                            value_numeric,
                            confidence,
                            source_type,
                            source_url,
                            evidence_text,
                            json.dumps(metadata or {}),
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return {
                "status": "ok",
                "id": row[0] if row else None,
                "extracted_at": _normalize_dateish(row[1] if row else None),
            }
        except Exception as exc:
            logger.warning("submit_candidate_fact failed: %s", exc)
            return {"status": "failed", "error": str(exc)}

    async def create_refresh_hint(
        self,
        *,
        entity_id: str | None,
        reason: str,
        priority: str = "normal",
        source_type: str = "dreaming",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.database_url:
            return {"status": "unavailable", "warning": "database not configured"}
        ensure_ikg_runtime_tables(self.database_url)
        try:
            with connect_postgres(self.database_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into ikg_refresh_hints (entity_id, reason, priority, source_type, metadata)
                        values (%s, %s, %s, %s, %s::jsonb)
                        returning id, created_at
                        """,
                        (entity_id, reason, priority, source_type, json.dumps(metadata or {})),
                    )
                    row = cur.fetchone()
                conn.commit()
            return {
                "status": "ok",
                "id": row[0] if row else None,
                "created_at": _normalize_dateish(row[1] if row else None),
            }
        except Exception as exc:
            logger.warning("create_refresh_hint failed: %s", exc)
            return {"status": "failed", "error": str(exc)}

    async def list_refresh_hints(self, *, status: str | None = "open", limit: int = 25) -> list[dict[str, Any]]:
        sql = """
            select id, entity_id, reason, priority, source_type, metadata, status, created_at, updated_at
            from ikg_refresh_hints
        """
        params: list[Any] = []
        if status:
            sql += " where status = %s"
            params.append(status)
        sql += " order by created_at desc limit %s"
        params.append(limit)
        return await asyncio.to_thread(self._fetch_rows, sql, tuple(params))

    async def build_company_bundle(
        self,
        *,
        identifier: str | None = None,
        cin: str | None = None,
        ticker: str | None = None,
        isin: str | None = None,
        name: str | None = None,
        aliases: list[str] | None = None,
        depth: str = "standard",
    ) -> IKGCompanyBundle:
        self._record_usage()
        depth = (depth or "standard").strip().lower()
        resolved = self._resolve(
            identifier=identifier,
            cin=cin,
            ticker=ticker,
            isin=isin,
            name=name,
            aliases=aliases,
        )
        cache_key = "|".join(
            [
                depth,
                resolved.cin if resolved and resolved.cin else cin or "",
                resolved.nse_symbol if resolved and resolved.nse_symbol else ticker or "",
                identifier or name or "",
            ]
        )
        cached = _bundle_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_S:
            return cached[1]

        if not resolved and not cin and not ticker:
            bundle = IKGCompanyBundle(
                status="unavailable",
                depth=depth,
                entity={"identifier": identifier or name or "", "resolved": False},
                warnings=["IKG entity could not be resolved."],
            )
            _bundle_cache[cache_key] = (time.time(), bundle)
            return bundle

        cin = (resolved.cin if resolved else cin) or ""
        ticker = (resolved.nse_symbol if resolved else ticker) or ticker or ""
        aliases = aliases or []
        entity_payload = {
            "resolved": bool(resolved or cin or ticker),
            "cin": cin or None,
            "name": (resolved.name if resolved else name) or identifier or name,
            "nse_symbol": (resolved.nse_symbol if resolved else None) or ticker or None,
            "bse_scrip_code": resolved.bse_scrip_code if resolved else None,
            "isin": (resolved.isin if resolved else None) or isin,
            "sector": resolved.sector if resolved else None,
            "aliases": [a for a in aliases if a],
            "resolved_at": _utc_now_iso(),
        }

        tasks: dict[str, Any] = {}
        if cin:
            tasks["subgraph"] = self.graph_client.get_company_subgraph(cin)
            tasks["pledge"] = self.graph_client.get_pledge_risk(cin)
            tasks["director_history"] = self.graph_client.get_director_history(cin)
            tasks["enforcement"] = self.graph_client.get_enforcement_actions(cin)
            tasks["promoter_chain"] = self.graph_client.get_promoter_chain(cin)
            tasks["ownership_summary"] = self.get_ownership_summary(cin, limit=20 if depth == "standard" else 40)
            tasks["company_master"] = self.get_company_master(cin)
            tasks["auditors"] = self.get_auditor_history(cin, limit=8 if depth == "standard" else 16)
            tasks["rpt"] = self.get_related_party_transactions(cin, limit=8 if depth == "standard" else 16)
            tasks["filings"] = self.get_corporate_filings(cin, limit=8 if depth == "standard" else 16)
            tasks["actions"] = self.get_corporate_actions(cin, limit=8 if depth == "standard" else 16)
            tasks["transcripts"] = self.get_concall_transcripts(cin, limit=4 if depth == "standard" else 10)
            tasks["provenance"] = self.get_fact_provenance(subject_entity_id=f"company:{cin}", limit=12)
            if depth in {"extended", "forensic"}:
                tasks["xbrl"] = self.get_xbrl_facts(cin, limit=20 if depth == "extended" else 40)
                tasks["documents"] = self.search_document_sections(cin, limit=6 if depth == "extended" else 12)
        if ticker:
            tasks["financials"] = self.graph_client.get_company_financials(ticker)

        results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results: dict[str, Any] = {}
        for key, value in zip(tasks.keys(), results_list):
            if isinstance(value, Exception):
                logger.debug("IKG bundle task '%s' failed: %s", key, value)
                results[key] = None
            else:
                results[key] = value

        subgraph = results.get("subgraph") or {}
        company = subgraph.get("company") if isinstance(subgraph, dict) else None
        company_master = results.get("company_master")
        ownership_rows = results.get("ownership_summary") or []
        ownership_edges = _ownership_rows_to_edges(ownership_rows, cin) if ownership_rows else []
        pledge_fallback = _summarize_ownership_rows(ownership_rows, cin) if ownership_rows else {}
        graph_pledge = results.get("pledge") or {}
        graph_pledge_total = _safe_float(graph_pledge.get("total_promoter_holding_pct")) or 0.0
        graph_promoters = list(subgraph.get("promoters") or [])
        promoter_chain = (results.get("promoter_chain") or {}).get("promoter_chain", [])
        summary_promoter_chain = [
            {
                "promoter_id": str(row.get("owner_vertex_id") or "").replace("promoter:", ""),
                "holding_pct": _safe_float(row.get("holding_pct")),
                "pledge_pct_of_holding": _safe_float(row.get("pledge_pct")),
                "quarter": row.get("quarter"),
                "owner_name": row.get("owner_name"),
                "source_table": row.get("source_table"),
                "source_uid": row.get("source_uid"),
                "source_url": row.get("source_url"),
                "updated_at": row.get("updated_at"),
            }
            for row in ownership_rows
        ]
        governance = {
            "directors": list(subgraph.get("directors") or []),
            "director_history": results.get("director_history") or [],
            "auditors": results.get("auditors") or [],
            "audit_firm": subgraph.get("audit_firm") or [],
        }
        # IGS predictive governance composite (rules + model). Read the precomputed
        # score-history row first; fall back to a live blend. Additive + fully
        # guarded so the bundle never breaks when the IGS layer is unavailable.
        if cin:
            try:
                from finagent.ikg.igs.scoring import get_latest_score

                igs_score = get_latest_score(cin)
                if igs_score:
                    governance["igs_score"] = igs_score
            except Exception:
                logger.debug("IGS score lookup failed for %s", cin, exc_info=True)
        ownership = {
            "promoters": ownership_edges or graph_promoters,
            "promoter_chain": summary_promoter_chain or promoter_chain,
            "pledge_summary": pledge_fallback if ownership_rows else graph_pledge,
            "graph_pledge_summary": graph_pledge if graph_pledge_total > 0 or graph_promoters else {},
        }
        risk = {
            "enforcement_actions": results.get("enforcement") or [],
            "related_party_transactions": results.get("rpt") or [],
            "provenance": results.get("provenance") or [],
        }
        financials = {
            "company_financials": results.get("financials"),
            "xbrl_facts": results.get("xbrl") or [],
        }
        documents = {
            "corporate_filings": results.get("filings") or [],
            "corporate_actions": results.get("actions") or [],
            "concall_transcripts": results.get("transcripts") or [],
            "document_sections": results.get("documents") or [],
        }

        facts: list[dict[str, Any]] = []
        if entity_payload.get("name") and cin:
            _push_fact(
                facts,
                category="identity",
                headline=f"Resolved {entity_payload['name']} to CIN {cin}",
                detail="IKG entity resolution linked the working target to a canonical Indian corporate identity.",
                confidence=0.95,
            )

        pledge = ownership.get("pledge_summary") or {}
        pledge_pct = _safe_float(pledge.get("total_pledge_pct"))
        if pledge_pct is not None:
            _push_fact(
                facts,
                category="ownership",
                headline=f"Promoter pledge at {pledge_pct:.2f}%",
                detail=(
                    f"Promoter holding {(_safe_float(pledge.get('total_promoter_holding_pct')) or 0.0):.2f}% "
                    f"with pledge flag {pledge.get('pledge_flag') or 'unknown'}."
                ),
                source_url=(ownership.get("promoter_chain") or [{}])[0].get("source_url"),
                as_of_date=_latest_as_of(pledge, ownership.get("promoter_chain")),
                confidence=0.9,
            )

        directors = governance.get("director_history") or governance.get("directors") or []
        if directors:
            _push_fact(
                facts,
                category="governance",
                headline=f"{len(directors)} director relationship(s) present in IKG",
                detail="Board continuity and recent exits should be cross-checked against exchange governance filings.",
                source_url=directors[0].get("source_url"),
                as_of_date=_latest_as_of(directors),
                confidence=0.82,
            )

        enforcement = risk.get("enforcement_actions") or []
        if enforcement:
            _push_fact(
                facts,
                category="risk",
                headline=f"{len(enforcement)} enforcement action(s) linked to the company",
                detail="Regulatory orders or enforcement edges exist in the graph and should be treated as material risk signals.",
                source_url=enforcement[0].get("source_url"),
                as_of_date=_latest_as_of(enforcement),
                confidence=0.9,
            )

        auditors = governance.get("auditors") or []
        if auditors:
            latest_auditor = auditors[0]
            _push_fact(
                facts,
                category="accounting",
                headline=f"Auditor history available for {len(auditors)} period(s)",
                detail=f"Latest auditor record: {latest_auditor.get('auditor_name') or 'unknown auditor'}.",
                source_url=latest_auditor.get("source_url"),
                as_of_date=_latest_as_of(auditors),
                confidence=0.84,
            )

        rpt = risk.get("related_party_transactions") or []
        if rpt:
            latest_rpt = rpt[0]
            value_numeric = _safe_float(latest_rpt.get("value_numeric"))
            rpt_detail = latest_rpt.get("fact_name") or latest_rpt.get("fact_key") or "related-party fact"
            if value_numeric is not None:
                rpt_detail += f" with reported numeric value {value_numeric:,.2f}"
            _push_fact(
                facts,
                category="accounting",
                headline=f"{len(rpt)} related-party XBRL fact(s) available",
                detail=rpt_detail,
                source_url=latest_rpt.get("source_url"),
                as_of_date=_latest_as_of(rpt),
                confidence=0.78,
            )

        company_financials = financials.get("company_financials") or {}
        if company_financials:
            revenue = _safe_float(company_financials.get("total_revenue"))
            net_income = _safe_float(company_financials.get("net_income"))
            if revenue is not None or net_income is not None:
                detail_bits: list[str] = []
                if revenue is not None:
                    detail_bits.append(f"revenue {revenue:,.2f}")
                if net_income is not None:
                    detail_bits.append(f"net income {net_income:,.2f}")
                _push_fact(
                    facts,
                    category="financials",
                    headline="IKG financial snapshot available",
                    detail="Latest company financials include " + ", ".join(detail_bits) + ".",
                    source_url=company_financials.get("source_url"),
                    as_of_date=_latest_as_of(company_financials),
                    confidence=0.75,
                )

        filings = documents.get("corporate_filings") or []
        if filings:
            latest_filing = filings[0]
            _push_fact(
                facts,
                category="documents",
                headline=f"{len(filings)} corporate filing(s) available in IKG",
                detail=(
                    f"Latest category: {latest_filing.get('category') or 'unknown'} "
                    f"announced {(_normalize_dateish(latest_filing.get('announced_at')) or 'n/a')}."
                ),
                source_url=latest_filing.get("attachment_url") or latest_filing.get("source_url"),
                as_of_date=_latest_as_of(filings),
                confidence=0.8,
            )

        company_payload = company or company_master
        coverage = {
            "identity": _coverage_state(entity_payload.get("cin"), entity_payload.get("name"), company_payload),
            "governance": _coverage_state(governance.get("directors"), governance.get("auditors")),
            "ownership": _coverage_state(ownership.get("promoters"), ownership.get("pledge_summary")),
            "risk": _coverage_state(risk.get("enforcement_actions"), risk.get("related_party_transactions")),
            "financials": _coverage_state(financials.get("company_financials"), financials.get("xbrl_facts")),
            "documents": _coverage_state(documents.get("corporate_filings"), documents.get("document_sections")),
        }

        complete_count = sum(1 for value in coverage.values() if value == "complete")
        partial_count = sum(1 for value in coverage.values() if value == "partial")
        confidence = min(0.98, 0.35 + (0.1 * complete_count) + (0.04 * partial_count))
        status = "ok" if complete_count >= 3 else "partial"
        warnings: list[str] = []
        if not company_payload:
            warnings.append("Canonical company vertex missing; using staging/master data where possible.")
        if coverage["documents"] == "missing":
            warnings.append("Document-backed IKG evidence is limited for this entity.")
        if coverage["financials"] == "missing":
            warnings.append("Financial coverage is incomplete; rely on enrichment/web corroboration.")

        bundle = IKGCompanyBundle(
            status=status,
            depth=depth,
            entity=entity_payload,
            company=company_payload,
            governance=governance,
            ownership=ownership,
            risk=risk,
            financials=financials,
            documents=documents,
            facts=facts,
            coverage=coverage,
            confidence=confidence,
            as_of_date=_latest_as_of(
                company_payload,
                governance,
                ownership,
                risk,
                financials,
                documents,
            ),
            source_refs=_collect_source_refs(
                company_payload,
                governance,
                ownership,
                risk,
                financials,
                documents,
            ),
            warnings=warnings,
        )
        _bundle_cache[cache_key] = (time.time(), bundle)
        return bundle


_service: IKGService | None = None


def get_ikg_service() -> IKGService:
    global _service
    if _service is None:
        _service = IKGService()
    return _service


def metric_observations_from_bundle(bundle: IKGCompanyBundle | None) -> list[MetricObservation]:
    if bundle is None:
        return []
    company_financials = (bundle.financials.get("company_financials") if bundle.financials else {}) or {}
    observations: list[MetricObservation] = []
    metric_map = {
        "total_revenue": "revenue",
        "net_income": "net_income",
        "eps": "eps",
        "market_cap": "market_cap",
        "employee_count": "employees",
        "employees": "employees",
    }
    domain = "ikg"
    source_url = bundle.source_refs[0] if bundle.source_refs else "ikg://bundle"
    for key, metric in metric_map.items():
        value = _safe_float(company_financials.get(key))
        if value is None:
            continue
        observations.append(
            MetricObservation(
                metric=metric,
                value=value,
                raw=str(company_financials.get(key)),
                context=f"IKG company financials field '{key}' from canonical graph/staging bundle.",
                url=source_url,
                domain=domain,
                tier=1,
            )
        )
    return observations
