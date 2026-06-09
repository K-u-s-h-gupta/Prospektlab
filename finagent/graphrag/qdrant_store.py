"""Qdrant + Postgres full-text retrieval for IKG document sections."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from psycopg.rows import dict_row

from finagent.env import load_finagent_env
from finagent.ikg.db import connect_postgres, ensure_ikg_runtime_tables, get_database_url

load_finagent_env()

logger = logging.getLogger("finagent.graphrag.qdrant_store")


@dataclass(frozen=True)
class QdrantConfig:
    url: str = "http://localhost:6333"
    api_key: str = ""
    collection: str = "ikg_document_sections"
    vector_size: int = 1536
    distance: str = "cosine"


@dataclass
class RetrievalHit:
    source: str
    score: float
    section_uid: str
    text: str
    document_uid: str = ""
    document_type: str = ""
    section_type: str = ""
    title: str = ""
    source_url: str = ""
    page_start: int | None = None
    page_end: int | None = None
    company_cin: str = ""
    nse_symbol: str = ""
    bse_scrip_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "score": self.score,
            "section_uid": self.section_uid,
            "chunk_id": self.section_uid,
            "text": self.text,
            "document_uid": self.document_uid,
            "source_file": self.source_url,
            "source_url": self.source_url,
            "source_type": self.document_type,
            "document_type": self.document_type,
            "section_type": self.section_type,
            "title": self.title,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "company_cin": self.company_cin,
            "company_ticker": self.nse_symbol or self.bse_scrip_code,
            "nse_symbol": self.nse_symbol,
            "bse_scrip_code": self.bse_scrip_code,
            "metadata": self.metadata,
        }


def get_qdrant_config() -> QdrantConfig:
    return QdrantConfig(
        url=os.getenv("QDRANT_URL", "http://localhost:6333").strip() or "http://localhost:6333",
        api_key=os.getenv("QDRANT_API_KEY", "").strip(),
        collection=os.getenv("QDRANT_COLLECTION", "ikg_document_sections").strip() or "ikg_document_sections",
        vector_size=int(os.getenv("QDRANT_VECTOR_SIZE", "1536") or "1536"),
        distance=os.getenv("QDRANT_DISTANCE", "cosine").strip().lower() or "cosine",
    )


def is_qdrant_configured() -> bool:
    return os.getenv("FINAGENT_RETRIEVAL_BACKEND", "qdrant_postgres").strip().lower() in {
        "qdrant",
        "qdrant_postgres",
        "postgres_qdrant",
    }


def _point_id(section_uid: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finagent:ikg:document_section:{section_uid}"))


def _distance_enum(value: str) -> Any:
    from qdrant_client.models import Distance

    normalized = (value or "cosine").strip().lower()
    if normalized in {"dot", "dotproduct"}:
        return Distance.DOT
    if normalized in {"euclid", "euclidean", "l2"}:
        return Distance.EUCLID
    return Distance.COSINE


def get_qdrant_client() -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise RuntimeError("qdrant-client is not installed. Run `uv sync` after updating pyproject.toml.") from exc

    cfg = get_qdrant_config()
    timeout = float(os.getenv("QDRANT_TIMEOUT_S", "10") or "10")
    if cfg.api_key:
        return QdrantClient(url=cfg.url, api_key=cfg.api_key, timeout=timeout)
    return QdrantClient(url=cfg.url, timeout=timeout)


def ensure_collection(*, recreate: bool = False) -> dict[str, Any]:
    """Create the Qdrant document-section collection and payload indexes."""
    from qdrant_client.models import VectorParams

    cfg = get_qdrant_config()
    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if recreate and cfg.collection in existing:
        client.delete_collection(cfg.collection)
        existing.remove(cfg.collection)

    if cfg.collection not in existing:
        client.create_collection(
            collection_name=cfg.collection,
            vectors_config=VectorParams(size=cfg.vector_size, distance=_distance_enum(cfg.distance)),
        )

    for field_name in (
        "company_cin",
        "nse_symbol",
        "bse_scrip_code",
        "document_type",
        "section_type",
        "report_year",
        "filing_date",
        "source_table",
    ):
        try:
            client.create_payload_index(
                collection_name=cfg.collection,
                field_name=field_name,
                field_schema="keyword",
            )
        except Exception as exc:
            logger.debug("Qdrant payload index skipped for %s: %s", field_name, exc)

    info = client.get_collection(cfg.collection)
    return {
        "ok": True,
        "collection": cfg.collection,
        "vectors_count": getattr(info, "vectors_count", None),
        "points_count": getattr(info, "points_count", None),
        "vector_size": cfg.vector_size,
        "distance": cfg.distance,
    }


async def embed_texts(texts: list[str], *, model: str | None = None, batch_size: int = 64) -> list[list[float]]:
    """Generate embeddings with the configured OpenAI-compatible provider.

    Includes automatic retry with exponential back-off on 429 rate-limit errors so
    transient TPM exhaustion does not abort the entire indexing job.
    """
    import asyncio as _asyncio

    from finagent.runtime_provider import resolve_openai_config

    cfg = resolve_openai_config()
    if not cfg:
        raise RuntimeError("OPENAI_API_KEY or compatible embedding provider config is required for Qdrant indexing")

    from openai import AsyncOpenAI, RateLimitError

    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=60.0)
    embedding_model = model or os.getenv("FINAGENT_EMBEDDING_MODEL", "text-embedding-3-small")
    batch_size = max(1, int(os.getenv("FINAGENT_EMBEDDING_BATCH_SIZE", str(batch_size)) or str(batch_size)))
    max_chars = max(256, int(os.getenv("FINAGENT_EMBEDDING_MAX_CHARS", "2500") or "2500"))
    # NOTE: inter-call delay is handled by the caller (qdrant_indexer.py) so that
    # the throttle fires even when embed_texts is called with a single sub-batch.
    max_retries = int(os.getenv("FINAGENT_EMBEDDING_MAX_RETRIES", "6") or "6")
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = [text[:max_chars] for text in texts[i : i + batch_size]]
        retry_delay = 2.0
        for attempt in range(max_retries):
            try:
                response = await client.embeddings.create(model=embedding_model, input=batch)
                embeddings.extend([item.embedding for item in response.data])
                break
            except RateLimitError as exc:
                if attempt >= max_retries - 1:
                    raise
                logger.warning(
                    "Embedding rate limit hit (attempt %d/%d); sleeping %.1fs before retry: %s",
                    attempt + 1, max_retries, retry_delay, exc,
                )
                await _asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60.0)
    return embeddings


def _metadata_value(metadata: Any, *keys: str) -> str:
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    if not isinstance(metadata, dict):
        return ""
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def section_payload(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    text = str(row.get("text") or "")
    tables = str(row.get("tables_markdown") or "")
    payload = {
        "section_uid": str(row.get("id")),
        "document_uid": str(row.get("document_uid") or ""),
        "source_table": str(row.get("source_table") or ""),
        "source_uid": str(row.get("source_uid") or ""),
        "document_type": str(row.get("document_type") or ""),
        "section_type": str(row.get("section_type") or ""),
        "title": str(row.get("title") or ""),
        "text": text[:12000],
        "tables_markdown": tables[:12000],
        "text_length": int(row.get("text_length") or len(text)),
        "page_start": int(row.get("page_start") or 0),
        "page_end": int(row.get("page_end") or row.get("page_start") or 0),
        "source_url": str(row.get("source_url") or ""),
        "fetched_at": str(row.get("fetched_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }
    payload["company_cin"] = (
        _metadata_value(metadata, "cin", "company_cin")
        or str(row.get("annual_cin") or row.get("filing_cin") or row.get("concall_cin") or "")
    )
    payload["company_name"] = (
        _metadata_value(metadata, "company_name")
        or str(row.get("annual_company_name") or row.get("filing_company_name") or row.get("concall_company_name") or "")
    )
    payload["nse_symbol"] = (
        _metadata_value(metadata, "nse_symbol", "symbol")
        or str(row.get("annual_nse_symbol") or row.get("filing_symbol") or row.get("concall_symbol") or "")
    ).upper()
    payload["bse_scrip_code"] = (
        _metadata_value(metadata, "bse_scrip_code", "scrip_code")
        or str(row.get("annual_scrip_code") or row.get("filing_scrip_code") or "")
    )
    payload["report_year"] = str(row.get("annual_report_year") or _metadata_value(metadata, "report_year", "fiscal_year") or "")
    payload["filing_date"] = str(
        row.get("filing_announced_at")
        or row.get("concall_announced_at")
        or row.get("enforcement_order_date")
        or _metadata_value(metadata, "announced_at", "order_date")
        or ""
    )
    return payload


def fetch_document_sections(
    *,
    database_url: str | None = None,
    limit: int | None = None,
    since: str | None = None,
    company_symbol: str | None = None,
    document_type: str | None = None,
) -> list[dict[str, Any]]:
    db_url = get_database_url(database_url)
    if not db_url:
        return []
    ensure_ikg_runtime_tables(db_url)

    where = ["coalesce(ds.text_length, 0) > 0"]
    params: list[Any] = []
    if since:
        where.append("ds.updated_at >= %s")
        params.append(since)
    if document_type:
        where.append("ds.document_type = %s")
        params.append(document_type)
    if company_symbol:
        where.append(
            """
            (
              upper(ds.metadata->>'symbol') = upper(%s)
              or upper(ds.metadata->>'nse_symbol') = upper(%s)
              or upper(ar.nse_symbol) = upper(%s)
              or upper(cf.symbol) = upper(%s)
              or upper(ct.symbol) = upper(%s)
            )
            """
        )
        params.extend([company_symbol] * 5)

    limit_sql = "limit %s" if limit else ""
    if limit:
        params.append(limit)

    sql = f"""
        select ds.*,
               ar.cin as annual_cin,
               ar.nse_symbol as annual_nse_symbol,
               ar.scrip_code as annual_scrip_code,
               ar.company_name as annual_company_name,
               ar.report_year as annual_report_year,
               cf.cin as filing_cin,
               cf.symbol as filing_symbol,
               cf.scrip_code as filing_scrip_code,
               cf.company_name as filing_company_name,
               cf.announced_at as filing_announced_at,
               ct.cin as concall_cin,
               ct.symbol as concall_symbol,
               ct.company_name as concall_company_name,
               ct.announced_at as concall_announced_at,
               er.order_date as enforcement_order_date
        from document_sections ds
        left join annual_reports_raw ar
          on ds.source_table = 'annual_reports_raw'
         and ds.source_uid = ar.report_uid
        left join corporate_filings_raw cf
          on ds.source_table = 'corporate_filings_raw'
         and ds.metadata->>'original_source_uid' = cf.source_uid
        left join concall_transcripts_raw ct
          on ds.source_table = 'concall_transcripts_raw'
         and ds.metadata->>'symbol' = ct.symbol
         and ds.metadata->>'announced_at' = ct.announced_at::text
        left join enforcement_raw er
          on ds.source_table = 'enforcement_raw'
         and ds.metadata->>'original_order_number' = er.order_number
        where {" and ".join(where)}
        order by ds.updated_at desc, ds.id desc
        {limit_sql}
    """
    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
            except Exception as exc:
                conn.rollback()
                logger.warning("Enriched document_sections fetch failed; using base sections only: %s", exc)
                base_where = ["coalesce(text_length, 0) > 0"]
                base_params: list[Any] = []
                if since:
                    base_where.append("updated_at >= %s")
                    base_params.append(since)
                if document_type:
                    base_where.append("document_type = %s")
                    base_params.append(document_type)
                base_limit = "limit %s" if limit else ""
                if limit:
                    base_params.append(limit)
                cur.execute(
                    f"""
                    select *
                    from document_sections
                    where {" and ".join(base_where)}
                    order by updated_at desc, id desc
                    {base_limit}
                    """,
                    base_params,
                )
                rows = [dict(row) for row in cur.fetchall()]
                if company_symbol:
                    symbol = company_symbol.upper()
                    filtered = []
                    for row in rows:
                        metadata = row.get("metadata") or {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except Exception:
                                metadata = {}
                        if str((metadata or {}).get("symbol") or (metadata or {}).get("nse_symbol") or "").upper() == symbol:
                            filtered.append(row)
                    rows = filtered
                return rows


def upsert_sections(rows: list[dict[str, Any]], embeddings: list[list[float]]) -> int:
    if not rows:
        return 0
    if len(rows) != len(embeddings):
        raise ValueError("rows and embeddings length mismatch")

    from qdrant_client.models import PointStruct

    cfg = get_qdrant_config()
    client = get_qdrant_client()
    points = []
    for row, vector in zip(rows, embeddings):
        payload = section_payload(row)
        section_uid = payload["section_uid"]
        points.append(PointStruct(id=_point_id(section_uid), vector=vector, payload=payload))
    client.upsert(collection_name=cfg.collection, points=points, wait=True)
    return len(points)


def _filter_from_params(
    *,
    company_cin: str | None = None,
    nse_symbol: str | None = None,
    document_type: str | None = None,
) -> Any | None:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    conditions = []
    if company_cin:
        conditions.append(FieldCondition(key="company_cin", match=MatchValue(value=company_cin)))
    if nse_symbol:
        conditions.append(FieldCondition(key="nse_symbol", match=MatchValue(value=nse_symbol.upper())))
    if document_type:
        conditions.append(FieldCondition(key="document_type", match=MatchValue(value=document_type)))
    return Filter(must=conditions) if conditions else None


def _hit_from_payload(source: str, score: float, payload: dict[str, Any]) -> RetrievalHit:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    text = str(payload.get("text") or "")
    if not text and payload.get("tables_markdown"):
        text = str(payload.get("tables_markdown") or "")
    return RetrievalHit(
        source=source,
        score=float(score or 0.0),
        section_uid=str(payload.get("section_uid") or ""),
        text=text,
        document_uid=str(payload.get("document_uid") or ""),
        document_type=str(payload.get("document_type") or ""),
        section_type=str(payload.get("section_type") or ""),
        title=str(payload.get("title") or ""),
        source_url=str(payload.get("source_url") or ""),
        page_start=int(payload.get("page_start") or 0) or None,
        page_end=int(payload.get("page_end") or 0) or None,
        company_cin=str(payload.get("company_cin") or ""),
        nse_symbol=str(payload.get("nse_symbol") or ""),
        bse_scrip_code=str(payload.get("bse_scrip_code") or ""),
        metadata=metadata,
    )


async def qdrant_vector_search(
    query: str,
    *,
    top_k: int = 8,
    company_cin: str | None = None,
    nse_symbol: str | None = None,
    document_type: str | None = None,
) -> list[RetrievalHit]:
    cfg = get_qdrant_config()
    client = get_qdrant_client()
    vector = (await embed_texts([query]))[0]
    query_filter = _filter_from_params(company_cin=company_cin, nse_symbol=nse_symbol, document_type=document_type)
    if hasattr(client, "search"):
        points = client.search(
            collection_name=cfg.collection,
            query_vector=vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
    else:
        response = client.query_points(
            collection_name=cfg.collection,
            query=vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        points = getattr(response, "points", response)
    hits = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        hits.append(_hit_from_payload("qdrant", float(getattr(point, "score", 0.0) or 0.0), payload))
    return hits


def postgres_full_text_search(
    query: str,
    *,
    database_url: str | None = None,
    top_k: int = 8,
    company_cin: str | None = None,
    nse_symbol: str | None = None,
    document_type: str | None = None,
) -> list[RetrievalHit]:
    db_url = get_database_url(database_url)
    if not db_url or not query.strip():
        return []
    ensure_ikg_runtime_tables(db_url)

    filters = []
    params: list[Any] = [query]
    if document_type:
        filters.append("ds.document_type = %s")
        params.append(document_type)
    if company_cin:
        filters.append(
            "(ds.metadata->>'cin' = %s or ds.metadata->>'company_cin' = %s or ar.cin = %s or cf.cin = %s or ct.cin = %s)"
        )
        params.extend([company_cin] * 5)
    if nse_symbol:
        filters.append(
            "(upper(ds.metadata->>'symbol') = upper(%s) or upper(ds.metadata->>'nse_symbol') = upper(%s) "
            "or upper(ar.nse_symbol) = upper(%s) or upper(cf.symbol) = upper(%s) or upper(ct.symbol) = upper(%s))"
        )
        params.extend([nse_symbol] * 5)
    where_extra = (" and " + " and ".join(filters)) if filters else ""
    params.append(top_k)

    sql = f"""
        with q as (select websearch_to_tsquery('english', %s) as query)
        select ds.*,
               ts_rank_cd(
                 to_tsvector(
                   'english',
                   coalesce(ds.document_uid, '') || ' ' ||
                   coalesce(ds.source_table, '') || ' ' ||
                   coalesce(ds.source_uid, '') || ' ' ||
                   coalesce(ds.document_type, '') || ' ' ||
                   coalesce(ds.section_type, '') || ' ' ||
                   coalesce(ds.title, '') || ' ' ||
                   coalesce(ds.text, '') || ' ' ||
                   coalesce(ds.tables_markdown, '') || ' ' ||
                   coalesce(ds.metadata::text, '')
                 ),
                 q.query
               ) as rank,
               ar.cin as annual_cin,
               ar.nse_symbol as annual_nse_symbol,
               ar.scrip_code as annual_scrip_code,
               ar.company_name as annual_company_name,
               ar.report_year as annual_report_year,
               cf.cin as filing_cin,
               cf.symbol as filing_symbol,
               cf.scrip_code as filing_scrip_code,
               cf.company_name as filing_company_name,
               cf.announced_at as filing_announced_at,
               ct.cin as concall_cin,
               ct.symbol as concall_symbol,
               ct.company_name as concall_company_name,
               ct.announced_at as concall_announced_at,
               er.order_date as enforcement_order_date
        from document_sections ds
        cross join q
        left join annual_reports_raw ar
          on ds.source_table = 'annual_reports_raw'
         and ds.source_uid = ar.report_uid
        left join corporate_filings_raw cf
          on ds.source_table = 'corporate_filings_raw'
         and ds.metadata->>'original_source_uid' = cf.source_uid
        left join concall_transcripts_raw ct
          on ds.source_table = 'concall_transcripts_raw'
         and ds.metadata->>'symbol' = ct.symbol
         and ds.metadata->>'announced_at' = ct.announced_at::text
        left join enforcement_raw er
          on ds.source_table = 'enforcement_raw'
         and ds.metadata->>'original_order_number' = er.order_number
        where q.query @@ to_tsvector(
          'english',
          coalesce(ds.document_uid, '') || ' ' ||
          coalesce(ds.source_table, '') || ' ' ||
          coalesce(ds.source_uid, '') || ' ' ||
          coalesce(ds.document_type, '') || ' ' ||
          coalesce(ds.section_type, '') || ' ' ||
          coalesce(ds.title, '') || ' ' ||
          coalesce(ds.text, '') || ' ' ||
          coalesce(ds.tables_markdown, '') || ' ' ||
          coalesce(ds.metadata::text, '')
        )
        {where_extra}
        order by rank desc, ds.updated_at desc
        limit %s
    """
    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=20) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(sql, params)
                rows = [dict(row) for row in cur.fetchall()]
            except Exception as exc:
                conn.rollback()
                logger.warning("Enriched Postgres FTS failed; using base document_sections only: %s", exc)
                base_params = [query]
                base_filters = []
                if document_type:
                    base_filters.append("document_type = %s")
                    base_params.append(document_type)
                where_extra = (" and " + " and ".join(base_filters)) if base_filters else ""
                base_params.append(top_k)
                cur.execute(
                    f"""
                    with q as (select websearch_to_tsquery('english', %s) as query)
                    select *,
                           ts_rank_cd(
                             to_tsvector(
                               'english',
                               coalesce(document_uid, '') || ' ' ||
                               coalesce(source_table, '') || ' ' ||
                               coalesce(source_uid, '') || ' ' ||
                               coalesce(document_type, '') || ' ' ||
                               coalesce(section_type, '') || ' ' ||
                               coalesce(title, '') || ' ' ||
                               coalesce(text, '') || ' ' ||
                               coalesce(tables_markdown, '') || ' ' ||
                               coalesce(metadata::text, '')
                             ),
                             q.query
                           ) as rank
                    from document_sections
                    cross join q
                    where q.query @@ to_tsvector(
                      'english',
                      coalesce(document_uid, '') || ' ' ||
                      coalesce(source_table, '') || ' ' ||
                      coalesce(source_uid, '') || ' ' ||
                      coalesce(document_type, '') || ' ' ||
                      coalesce(section_type, '') || ' ' ||
                      coalesce(title, '') || ' ' ||
                      coalesce(text, '') || ' ' ||
                      coalesce(tables_markdown, '') || ' ' ||
                      coalesce(metadata::text, '')
                    )
                    {where_extra}
                    order by rank desc, updated_at desc
                    limit %s
                    """,
                    base_params,
                )
                rows = [dict(row) for row in cur.fetchall()]

    hits = []
    for row in rows:
        payload = section_payload(row)
        hits.append(_hit_from_payload("postgres_fts", float(row.get("rank") or 0.0), payload))
    return hits


async def hybrid_search_sections(
    query: str,
    *,
    database_url: str | None = None,
    top_k: int = 8,
    company_cin: str | None = None,
    nse_symbol: str | None = None,
    document_type: str | None = None,
) -> list[dict[str, Any]]:
    """Merge Qdrant semantic hits with Postgres full-text hits."""
    vector_hits: list[RetrievalHit] = []
    try:
        vector_hits = await qdrant_vector_search(
            query,
            top_k=top_k,
            company_cin=company_cin,
            nse_symbol=nse_symbol,
            document_type=document_type,
        )
    except Exception as exc:
        logger.debug("Qdrant vector search failed: %s", exc)

    fts_hits = postgres_full_text_search(
        query,
        database_url=database_url,
        top_k=top_k,
        company_cin=company_cin,
        nse_symbol=nse_symbol,
        document_type=document_type,
    )

    merged: dict[str, RetrievalHit] = {}
    for hit in vector_hits + fts_hits:
        key = hit.section_uid or hashlib.sha1(f"{hit.document_uid}:{hit.text[:80]}".encode("utf-8")).hexdigest()
        existing = merged.get(key)
        if existing is None:
            merged[key] = hit
            continue
        existing.score = max(existing.score, hit.score) + 0.15
        existing.source = "qdrant+postgres_fts" if existing.source != hit.source else existing.source

    ranked = sorted(merged.values(), key=lambda item: item.score, reverse=True)
    return [hit.to_dict() for hit in ranked[:top_k]]


def check_qdrant() -> dict[str, Any]:
    try:
        info = ensure_collection(recreate=False)
        info["configured"] = is_qdrant_configured()
        return info
    except Exception as exc:
        return {"ok": False, "configured": is_qdrant_configured(), "error": str(exc)}
