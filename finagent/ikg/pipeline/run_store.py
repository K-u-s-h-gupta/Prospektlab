"""Durable IKG pipeline run logging and scheduler locks."""

from __future__ import annotations

import json
import logging
import os
import re
import hashlib
import socket
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from finagent.ikg.db import connect_postgres, ensure_ikg_runtime_tables, get_database_url

logger = logging.getLogger("finagent.ikg.pipeline.run_store")

_RUNTIME_CONTROL_CACHE: dict[str, tuple[bool, datetime]] = {}
_RUNTIME_CONTROL_BACKOFF_UNTIL: datetime | None = None
_RUNTIME_CONTROL_LAST_ERROR: str = ""


def _runtime_control_connect_timeout() -> int:
    raw = str(os.getenv("IKG_RUNTIME_CONTROL_CONNECT_TIMEOUT_SECONDS", "2")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 2
    return max(1, min(value, 30))


def _runtime_control_cache_ttl_seconds() -> int:
    raw = str(os.getenv("IKG_RUNTIME_CONTROL_CACHE_TTL_SECONDS", "30")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 30
    return max(1, min(value, 600))


def _runtime_control_backoff_seconds() -> int:
    raw = str(os.getenv("IKG_RUNTIME_CONTROL_BACKOFF_SECONDS", "60")).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 60
    return max(5, min(value, 1800))


def _coerce_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def persist_pipeline_run(result: Any, database_url: str | None = None) -> bool:
    """Persist a pipeline run result to the Supabase/Postgres IKG database."""
    db_url = get_database_url(database_url)
    if not db_url:
        return False
    ensure_ikg_runtime_tables(db_url)

    data = asdict(result) if is_dataclass(result) else dict(result or {})
    metadata = dict(data.get("metadata") or {})
    run_id = str(metadata.pop("run_id", "") or uuid.uuid4())
    source_name = metadata.get("source_name") or metadata.get("source")
    official_source_url = metadata.get("official_source_url") or metadata.get("source_url")
    http_status = metadata.get("http_status")
    parser_version = metadata.get("parser_version")

    try:
        with connect_postgres(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ikg_pipeline_runs (
                      run_id, task_name, source_name, started_at, completed_at,
                      duration_s, records_fetched, records_stored, records_failed,
                      success, error, official_source_url, http_status,
                      parser_version, metadata
                    )
                    values (
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s::jsonb
                    )
                    on conflict (run_id) do update set
                      completed_at = excluded.completed_at,
                      duration_s = excluded.duration_s,
                      records_fetched = excluded.records_fetched,
                      records_stored = excluded.records_stored,
                      records_failed = excluded.records_failed,
                      success = excluded.success,
                      error = excluded.error,
                      metadata = excluded.metadata
                    """,
                    (
                        run_id,
                        data.get("task_name", "unknown"),
                        source_name,
                        _coerce_dt(data.get("started_at")),
                        _coerce_dt(data.get("completed_at")),
                        data.get("duration_s") or 0,
                        data.get("records_fetched") or 0,
                        data.get("records_stored") or 0,
                        data.get("records_failed") or 0,
                        bool(data.get("success")),
                        data.get("error"),
                        official_source_url,
                        int(http_status) if http_status not in (None, "") else None,
                        parser_version,
                        json.dumps(_json_safe(metadata), default=str),
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.warning("Failed to persist pipeline run %s: %s", data.get("task_name"), exc)
        return False


def _lock_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


@contextmanager
def scheduler_job_lock(
    job_id: str,
    database_url: str | None = None,
    ttl_minutes: int | None = None,
) -> Iterator[bool]:
    """Acquire a Supabase/Postgres-backed scheduler lock for one job.

    If the lock table is unavailable, the caller is allowed to run. That keeps
    local bootstrap flows usable before the schema has been applied.
    """
    db_url = get_database_url(database_url)
    if not db_url:
        yield True
        return
    ensure_ikg_runtime_tables(db_url)

    ttl = ttl_minutes or int(os.getenv("IKG_SCHEDULER_LOCK_TTL_MINUTES", "240"))
    owner = _lock_owner()
    locked_until = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    acquired = False

    try:
        with connect_postgres(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ikg_scheduler_locks (job_id, locked_by, locked_until, updated_at)
                    values (%s, %s, %s, now())
                    on conflict (job_id) do update set
                      locked_by = excluded.locked_by,
                      locked_until = excluded.locked_until,
                      updated_at = now()
                    where ikg_scheduler_locks.locked_until <= now()
                       or ikg_scheduler_locks.locked_by = excluded.locked_by
                    returning job_id
                    """,
                    (job_id, owner, locked_until),
                )
                acquired = cur.fetchone() is not None
            conn.commit()

        yield acquired

    except Exception as exc:
        logger.warning("Scheduler lock unavailable for %s; running unlocked: %s", job_id, exc)
        yield True

    finally:
        if not acquired:
            return
        try:
            with connect_postgres(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        update ikg_scheduler_locks
                        set locked_until = now(), updated_at = now()
                        where job_id = %s and locked_by = %s
                        """,
                        (job_id, owner),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to release scheduler lock for %s: %s", job_id, exc)


def is_runtime_control_enabled(
    control_key: str,
    *,
    default: bool = True,
    database_url: str | None = None,
) -> bool:
    """Return the current value for a runtime control flag.

    Controls live in Supabase/Postgres so the scheduler can be paused or
    resumed without redeploying the worker stack. Missing rows fall back to the
    provided default to keep fresh databases usable.
    """
    global _RUNTIME_CONTROL_BACKOFF_UNTIL
    global _RUNTIME_CONTROL_LAST_ERROR

    db_url = get_database_url(database_url)
    if not db_url:
        return default

    now = datetime.now(timezone.utc)
    cached = _RUNTIME_CONTROL_CACHE.get(control_key)
    if cached and cached[1] > now:
        return cached[0]

    if _RUNTIME_CONTROL_BACKOFF_UNTIL and _RUNTIME_CONTROL_BACKOFF_UNTIL > now:
        return default

    try:
        with connect_postgres(db_url, connect_timeout=_runtime_control_connect_timeout()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select enabled
                    from ikg_runtime_controls
                    where control_key = %s
                    """,
                    (control_key,),
                )
                row = cur.fetchone()
        value = default
        if row:
            if isinstance(row, dict):
                value = bool(row.get("enabled", default))
            else:
                value = bool(row[0])
        _RUNTIME_CONTROL_CACHE[control_key] = (
            value,
            now + timedelta(seconds=_runtime_control_cache_ttl_seconds()),
        )
        _RUNTIME_CONTROL_BACKOFF_UNTIL = None
        _RUNTIME_CONTROL_LAST_ERROR = ""
        return value
    except Exception as exc:
        error_message = str(exc)
        lowered = error_message.lower()
        timeout_like = "timeout" in lowered or "timed out" in lowered
        log_level = logging.INFO if timeout_like else logging.WARNING
        if _RUNTIME_CONTROL_LAST_ERROR == error_message and not timeout_like:
            log_level = logging.INFO
        logger.log(
            log_level,
            "Runtime control lookup failed for %s; defaulting to %s for %ss: %s",
            control_key,
            default,
            _runtime_control_backoff_seconds(),
            exc,
        )
        _RUNTIME_CONTROL_LAST_ERROR = error_message
        _RUNTIME_CONTROL_BACKOFF_UNTIL = now + timedelta(seconds=_runtime_control_backoff_seconds())
        return default


def build_ikg_from_staging(
    database_url: str | None = None,
    nifty10_cins: set[str] | None = None,
) -> dict[str, int]:
    """Build IKG graph vertices + edges from populated staging tables.

    Reads ikg_company_master, directors_raw, shp_raw, company_financials,
    annual_reports_raw, corporate_filings_raw, enforcement_raw and writes
    ikg_vertices + ikg_edges rows.

    Args:
        database_url: PostgreSQL connection string.
        nifty10_cins: Optional CIN filter — only build graph for these companies.

    Returns:
        dict with vertices_created, edges_created.
    """
    db_url = get_database_url(database_url)
    if not db_url:
        return {"vertices_created": 0, "edges_created": 0}

    ensure_ikg_runtime_tables(db_url)
    vertices_created = 0
    edges_created = 0

    def _upsert_vertex(cur: Any, vertex_id: str, label: str, props: dict) -> None:
        nonlocal vertices_created
        cur.execute(
            """
            insert into ikg_vertices (vertex_id, label, properties, updated_at)
            values (%s, %s, %s::jsonb, now())
            on conflict (vertex_id) do update set
              label = excluded.label,
              properties = ikg_vertices.properties || excluded.properties,
              updated_at = now()
            """,
            (vertex_id, label, json.dumps(props, default=str)),
        )
        vertices_created += 1

    def _upsert_edge(cur: Any, from_id: str, to_id: str, label: str, props: dict) -> None:
        nonlocal edges_created
        # Use a savepoint so that FK violations (e.g. to_vertex_id not yet present)
        # are silently skipped without aborting the surrounding transaction.
        # In psycopg v3 a failed statement leaves the connection in INERROR state
        # and every subsequent statement on that connection also fails until a
        # ROLLBACK or ROLLBACK TO SAVEPOINT is issued.
        try:
            cur.execute("SAVEPOINT _edge_insert")
            cur.execute(
                """
                insert into ikg_edges (from_vertex_id, to_vertex_id, label, properties, updated_at)
                values (%s, %s, %s, %s::jsonb, now())
                on conflict (from_vertex_id, to_vertex_id, label) do update set
                  properties = ikg_edges.properties || excluded.properties,
                  updated_at = now()
                """,
                (from_id, to_id, label, json.dumps(props, default=str)),
            )
            cur.execute("RELEASE SAVEPOINT _edge_insert")
            edges_created += 1
        except Exception as exc:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT _edge_insert")
            except Exception:
                pass
            logger.debug("Edge insert skipped %s->%s: %s", from_id, to_id, exc)

    def _upsert_canonical_entity(
        cur: Any,
        entity_id: str,
        entity_type: str,
        display_name: str,
        *,
        primary_identifier: str | None = None,
        properties: dict[str, Any] | None = None,
        aliases: list[tuple[str, str]] | None = None,
    ) -> None:
        cur.execute(
            """
            insert into ikg_canonical_entities (
              entity_id, entity_type, display_name, primary_identifier,
              properties, updated_at
            )
            values (%s, %s, %s, %s, %s::jsonb, now())
            on conflict (entity_id) do update set
              entity_type = excluded.entity_type,
              display_name = excluded.display_name,
              primary_identifier = coalesce(excluded.primary_identifier, ikg_canonical_entities.primary_identifier),
              properties = ikg_canonical_entities.properties || excluded.properties,
              updated_at = now()
            """,
            (
                entity_id,
                entity_type,
                display_name,
                primary_identifier,
                json.dumps(properties or {}, default=str),
            ),
        )
        for alias, alias_type in aliases or []:
            alias = (alias or "").strip()
            if not alias:
                continue
            cur.execute(
                """
                insert into ikg_entity_aliases (entity_id, alias, alias_type, source_citation)
                values (%s, %s, %s, %s)
                on conflict (entity_id, alias, alias_type) do update set
                  source_citation = excluded.source_citation
                """,
                (entity_id, alias, alias_type, "IKG_graph_build"),
            )

    def _upsert_fact(
        cur: Any,
        fact_id: str,
        subject_entity_id: str,
        predicate: str,
        *,
        object_entity_id: str | None = None,
        object_value: str | None = None,
        value_numeric: Any = None,
        valid_from: Any = None,
        valid_to: Any = None,
        as_of_date: Any = None,
        event_date: Any = None,
        source_table: str | None = None,
        source_uid: str | None = None,
        source_url: str | None = None,
        evidence_text: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        def _date_value(raw: Any) -> Any:
            if raw is None:
                return None
            text = str(raw).strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}", text):
                return text[:10]
            return None

        def _numeric_value(raw: Any) -> Any:
            if raw in (None, ""):
                return None
            try:
                return float(str(raw).replace("%", "").replace(",", "").strip())
            except Exception:
                return None

        cur.execute(
            """
            insert into ikg_facts (
              fact_id, subject_entity_id, predicate, object_entity_id, object_value,
              value_numeric, valid_from, valid_to, as_of_date, event_date,
              source_table, source_uid, source_url, evidence_text, properties,
              updated_at
            )
            values (
              %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s::jsonb,
              now()
            )
            on conflict (fact_id) do update set
              subject_entity_id = excluded.subject_entity_id,
              predicate = excluded.predicate,
              object_entity_id = excluded.object_entity_id,
              object_value = excluded.object_value,
              value_numeric = excluded.value_numeric,
              valid_from = excluded.valid_from,
              valid_to = excluded.valid_to,
              as_of_date = excluded.as_of_date,
              event_date = excluded.event_date,
              source_table = excluded.source_table,
              source_uid = excluded.source_uid,
              source_url = excluded.source_url,
              evidence_text = excluded.evidence_text,
              properties = ikg_facts.properties || excluded.properties,
              updated_at = now()
            """,
            (
                fact_id,
                subject_entity_id,
                predicate,
                object_entity_id,
                object_value,
                _numeric_value(value_numeric),
                _date_value(valid_from),
                _date_value(valid_to),
                _date_value(as_of_date),
                _date_value(event_date),
                source_table,
                source_uid,
                source_url,
                evidence_text,
                json.dumps(properties or {}, default=str),
            ),
        )

    def _stable_vertex_id(prefix: str, *parts: Any, max_len: int = 200) -> str:
        raw = ":".join(str(part or "") for part in parts)
        candidate = f"{prefix}:{raw}"
        if len(candidate) <= max_len and all(ch not in candidate for ch in "\r\n\t"):
            return candidate
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}:{digest}"

    def _write_pipeline(conn: Any) -> Any:
        if os.getenv("FINAGENT_IKG_GRAPH_PIPELINE_WRITES", "1").strip().lower() not in {
            "1", "true", "yes", "on",
        }:
            return nullcontext()
        try:
            return conn.pipeline()
        except Exception:
            return nullcontext()

    try:
        from psycopg.rows import dict_row

        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:

                # ── 1. Company vertices ───────────────────────────────────────
                cin_filter_sql = ""
                cin_params: list = []
                if nifty10_cins:
                    cin_filter_sql = "WHERE cin = ANY(%s)"
                    cin_params = [list(nifty10_cins)]

                cur.execute(
                    f"SELECT * FROM ikg_company_master {cin_filter_sql} ORDER BY company_name",
                    cin_params,
                )
                companies = cur.fetchall()

                with _write_pipeline(conn):
                    for co in companies:
                        cin = co.get("cin") or co.get("nse_symbol")
                        if not cin:
                            continue
                        vid = f"company:{cin}"
                        _upsert_vertex(cur, vid, "Company", {
                            "cin": co.get("cin"),
                            "nse_symbol": co.get("nse_symbol"),
                            "bse_scrip_code": co.get("bse_scrip_code"),
                            "isin": co.get("isin"),
                            "company_name": co.get("company_name"),
                            "sector": co.get("sector"),
                            "industry": co.get("industry"),
                            "listing_status": co.get("listing_status"),
                            "state": co.get("state"),
                            "status": co.get("status"),
                            "category": co.get("category"),
                            "company_class": co.get("company_class"),
                            "registration_date": str(co.get("registration_date") or ""),
                            "authorized_capital": co.get("authorized_capital"),
                            "paidup_capital": co.get("paidup_capital"),
                            "roc": co.get("roc"),
                        })
                        aliases = [
                            (str(co.get("company_name") or ""), "legal_name"),
                            (str(co.get("nse_symbol") or ""), "nse_symbol"),
                            (str(co.get("bse_scrip_code") or ""), "bse_scrip_code"),
                            (str(co.get("isin") or ""), "isin"),
                        ]
                        _upsert_canonical_entity(
                            cur,
                            vid,
                            "Company",
                            str(co.get("company_name") or co.get("nse_symbol") or cin),
                            primary_identifier=str(co.get("cin") or cin),
                            properties={
                                "cin": co.get("cin"),
                                "nse_symbol": co.get("nse_symbol"),
                                "bse_scrip_code": co.get("bse_scrip_code"),
                                "isin": co.get("isin"),
                            },
                            aliases=aliases,
                        )

                conn.commit()
                logger.info("Created %d Company vertices", len(companies))

                # ── 2. Director vertices + SERVES_AS edges ────────────────────
                director_where = "WHERE d.cin = ANY(%s)" if nifty10_cins else ""
                director_params = [list(nifty10_cins)] if nifty10_cins else []
                cur.execute(
                    f"""
                    SELECT d.*, c.nse_symbol FROM directors_raw d
                    LEFT JOIN ikg_company_master c USING (cin)
                    {director_where}
                    """,
                    director_params,
                )
                directors = cur.fetchall()
                with _write_pipeline(conn):
                    for d in directors:
                        din = d.get("din")
                        cin = d.get("cin")
                        if not din or not cin:
                            continue
                        dvid = f"person:{din}"
                        _upsert_vertex(cur, dvid, "Person", {
                            "din": din,
                            "name": d.get("name"),
                            "designation": d.get("designation"),
                        })
                        _upsert_canonical_entity(
                            cur,
                            dvid,
                            "Person",
                            str(d.get("name") or din),
                            primary_identifier=str(din),
                            properties={"din": din, "designation": d.get("designation")},
                            aliases=[(str(d.get("name") or ""), "name"), (str(din), "din")],
                        )
                        company_vid = f"company:{cin}"
                        _upsert_edge(cur, dvid, company_vid, "DIRECTOR_OF", {
                            "designation": d.get("designation"),
                            "appointment_date": str(d.get("appointment_date") or ""),
                            "cessation_date": str(d.get("cessation_date") or ""),
                            "source_citation": d.get("source") or "NSE_corporate_governance",
                        })
                        source_uid = f"{cin}:{din}:{d.get('appointment_date') or ''}:{d.get('cessation_date') or ''}"
                        _upsert_fact(
                            cur,
                            f"role:{source_uid}",
                            dvid,
                            "DIRECTOR_OF",
                            object_entity_id=company_vid,
                            valid_from=d.get("appointment_date"),
                            valid_to=d.get("cessation_date"),
                            source_table="directors_raw",
                            source_uid=source_uid,
                            evidence_text=d.get("designation"),
                            properties={
                                "designation": d.get("designation"),
                                "source_citation": d.get("source") or "NSE_corporate_governance",
                            },
                        )

                conn.commit()
                logger.info("Created %d Director vertices + edges", len(directors))

                # ── 3. Shareholding → OWNS_STAKE_IN edges ────────────────────
                shp_where = "WHERE coalesce(s.cin, c.cin) = ANY(%s)" if nifty10_cins else ""
                shp_params = [list(nifty10_cins)] if nifty10_cins else []
                cur.execute(
                    f"""
                    SELECT s.*, c.cin AS resolved_cin, c.nse_symbol FROM shp_raw s
                    LEFT JOIN ikg_company_master c ON c.bse_scrip_code = s.scrip_code
                      OR c.cin = s.cin
                    {shp_where}
                    """,
                    shp_params,
                )
                shp_rows = cur.fetchall()
                with _write_pipeline(conn):
                    for shp in shp_rows:
                        cin = shp.get("cin") or shp.get("resolved_cin")
                        scrip = shp.get("scrip_code")
                        if not cin and not scrip:
                            continue
                        company_ref = cin or scrip
                        company_vid = f"company:{company_ref}"
                        # Pre-create a placeholder vertex so FK constraints on ikg_edges
                        # are satisfied even for companies known only by BSE scrip code.
                        _upsert_vertex(cur, company_vid, "Company", {
                            "cin": cin or None,
                            "bse_scrip_code": scrip or None,
                            "nse_symbol": shp.get("nse_symbol") or None,
                        })
                        groups = shp.get("promoter_groups_json") or []
                        if isinstance(groups, str):
                            try:
                                groups = json.loads(groups)
                            except Exception:
                                groups = []
                        for grp in (groups if isinstance(groups, list) else []):
                            pname = grp.get("name", "").strip()
                            if not pname:
                                continue
                            promoter_slug = re.sub(r"[^A-Z0-9]+", "_", pname.upper()).strip("_")[:80] or "UNKNOWN"
                            pid = f"promoter:{promoter_slug}"
                            _upsert_vertex(cur, pid, "PromoterGroup", {
                                "name": pname,
                                "category": grp.get("category"),
                            })
                            _upsert_canonical_entity(
                                cur,
                                pid,
                                "PromoterEntity",
                                pname,
                                primary_identifier=promoter_slug,
                                properties={"category": grp.get("category")},
                                aliases=[(pname, "name"), (promoter_slug, "slug")],
                            )
                            _upsert_edge(cur, pid, company_vid, "OWNS_STAKE_IN", {
                                "percentage": grp.get("holding_pct", 0),
                                "pledge_pct": grp.get("pledge_pct_of_holding", 0),
                                "quarter": shp.get("quarter"),
                                "source_citation": "BSE_SHP",
                            })
                            quarter = str(shp.get("quarter") or "").strip()
                            fact_id = f"ownership:{promoter_slug}:{company_ref}:{quarter or 'latest'}"
                            _upsert_fact(
                                cur,
                                fact_id,
                                pid,
                                "OWNS_STAKE_IN",
                                object_entity_id=company_vid,
                                value_numeric=grp.get("holding_pct", 0),
                                as_of_date=shp.get("as_on_date"),
                                source_table="shp_raw",
                                source_uid=f"{scrip or cin}:{quarter}",
                                source_url=shp.get("source_url"),
                                properties={
                                    "holding_pct": grp.get("holding_pct", 0),
                                    "pledge_pct": grp.get("pledge_pct_of_holding", 0),
                                    "quarter": quarter,
                                    "holder_category": grp.get("category"),
                                    "source_citation": "BSE_SHP",
                                },
                            )
                            cur.execute(
                                """
                                insert into ikg_ownership_summary (
                                  company_vertex_id, owner_vertex_id, owner_name,
                                  quarter, holding_pct, pledge_pct, source_table,
                                  source_uid, updated_at
                                )
                                values (%s, %s, %s, %s, %s, %s, %s, %s, now())
                                on conflict (company_vertex_id, owner_vertex_id, quarter)
                                do update set
                                  owner_name = excluded.owner_name,
                                  holding_pct = excluded.holding_pct,
                                  pledge_pct = excluded.pledge_pct,
                                  source_uid = excluded.source_uid,
                                  updated_at = now()
                                """,
                                (
                                    company_vid,
                                    pid,
                                    pname,
                                    quarter,
                                    grp.get("holding_pct", 0),
                                    grp.get("pledge_pct_of_holding", 0),
                                    "shp_raw",
                                    f"{scrip or cin}:{quarter}",
                                ),
                            )

                conn.commit()
                logger.info("Created promoter SHP edges from %d SHP records", len(shp_rows))

                # ── 4. Financial metrics → HAS_FINANCIALS edges ──────────────
                fin_where = "WHERE cin = ANY(%s)" if nifty10_cins else ""
                fin_params = [list(nifty10_cins)] if nifty10_cins else []
                cur.execute(
                    f"""
                    SELECT * FROM company_financials
                    {fin_where}
                    """,
                    fin_params,
                )
                fin_rows = cur.fetchall()
                with _write_pipeline(conn):
                    for fin in fin_rows:
                        cin = fin.get("cin") or fin.get("nse_symbol")
                        if not cin:
                            continue
                        company_vid = f"company:{cin}"
                        fin_vid = f"financials:{fin.get('nse_symbol') or cin}"
                        vm = fin.get("validated_metrics_json") or {}
                        if isinstance(vm, str):
                            try:
                                vm = json.loads(vm)
                            except Exception:
                                vm = {}
                        _upsert_vertex(cur, fin_vid, "FinancialData", {
                            "nse_symbol": fin.get("nse_symbol"),
                            "cin": fin.get("cin"),
                            "sources_used": fin.get("sources_used") or [],
                            "validated_metrics": vm,
                            "fetched_at": str(fin.get("fetched_at") or ""),
                        })
                        _upsert_edge(cur, company_vid, fin_vid, "HAS_FINANCIALS", {
                            "source_citation": "screener.in+yfinance",
                        })

                conn.commit()
                logger.info("Created %d Financial vertices + edges", len(fin_rows))

                xbrl_where = "where cin = any(%s)" if nifty10_cins else ""
                xbrl_params = [list(nifty10_cins)] if nifty10_cins else []
                try:
                    cur.execute(
                        f"""
                        select *
                        from financial_results_xbrl
                        {xbrl_where}
                        order by period_end desc nulls last, announced_at desc nulls last
                        limit 10000
                        """,
                        xbrl_params,
                    )
                    xbrl_fin_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Financial XBRL graph step skipped: %s", exc)
                    xbrl_fin_rows = []

                metric_predicates = {
                    "revenue_from_operations": "REVENUE_FROM_OPERATIONS",
                    "total_income": "TOTAL_INCOME",
                    "profit_before_tax": "PROFIT_BEFORE_TAX",
                    "profit_after_tax": "PROFIT_AFTER_TAX",
                    "eps_basic": "EPS_BASIC",
                    "eps_diluted": "EPS_DILUTED",
                    "net_worth": "NET_WORTH",
                }
                with _write_pipeline(conn):
                    for row in xbrl_fin_rows:
                        cin = str(row.get("cin") or row.get("symbol") or row.get("scrip_code") or "").strip()
                        if not cin:
                            continue
                        company_vid = f"company:{cin}"
                        disclosure_vid = _stable_vertex_id(
                            "xbrl_financial_result",
                            row.get("exchange"),
                            row.get("source_uid"),
                        )
                        _upsert_vertex(cur, disclosure_vid, "XBRLFinancialResult", {
                            "exchange": row.get("exchange"),
                            "source_uid": row.get("source_uid"),
                            "cin": row.get("cin"),
                            "symbol": row.get("symbol"),
                            "scrip_code": row.get("scrip_code"),
                            "company_name": row.get("company_name"),
                            "announced_at": str(row.get("announced_at") or ""),
                            "period_start": str(row.get("period_start") or ""),
                            "period_end": str(row.get("period_end") or ""),
                            "as_of_date": str(row.get("as_of_date") or ""),
                            "attachment_url": row.get("attachment_url"),
                            "source_url": row.get("source_url"),
                            "summary": row.get("summary_json") or {},
                        })
                        _upsert_edge(cur, company_vid, disclosure_vid, "HAS_OFFICIAL_FINANCIAL_RESULT", {
                            "period_end": str(row.get("period_end") or ""),
                            "source_citation": "NSE_BSE_XBRL",
                        })
                        for column, predicate in metric_predicates.items():
                            value = row.get(column)
                            if value in (None, ""):
                                continue
                            fact_hash = hashlib.sha1(
                                str((row.get("exchange"), row.get("source_uid"), column)).encode("utf-8")
                            ).hexdigest()[:24]
                            _upsert_fact(
                                cur,
                                f"xbrl:{predicate}:{fact_hash}",
                                company_vid,
                                predicate,
                                value_numeric=value,
                                as_of_date=row.get("as_of_date") or row.get("period_end"),
                                source_table="financial_results_xbrl",
                                source_uid=row.get("source_uid"),
                                source_url=row.get("attachment_url") or row.get("source_url"),
                                properties={
                                    "exchange": row.get("exchange"),
                                    "source_uid": row.get("source_uid"),
                                    "xbrl_column": column,
                                },
                            )

                if xbrl_fin_rows:
                    conn.commit()
                    logger.info("Created %d official financial XBRL vertices/facts", len(xbrl_fin_rows))

                try:
                    cur.execute(
                        f"""
                        select *
                        from corporate_event_xbrl
                        {xbrl_where}
                        order by as_of_date desc nulls last, announced_at desc nulls last
                        limit 10000
                        """,
                        xbrl_params,
                    )
                    xbrl_event_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Corporate event XBRL graph step skipped: %s", exc)
                    xbrl_event_rows = []

                with _write_pipeline(conn):
                    for row in xbrl_event_rows:
                        cin = str(row.get("cin") or row.get("symbol") or row.get("scrip_code") or "").strip()
                        if not cin:
                            continue
                        company_vid = f"company:{cin}"
                        disclosure_vid = _stable_vertex_id(
                            "xbrl_disclosure",
                            row.get("exchange"),
                            row.get("source_uid"),
                            row.get("category"),
                        )
                        _upsert_vertex(cur, disclosure_vid, "XBRLDisclosure", {
                            "category": row.get("category"),
                            "exchange": row.get("exchange"),
                            "source_uid": row.get("source_uid"),
                            "cin": row.get("cin"),
                            "symbol": row.get("symbol"),
                            "scrip_code": row.get("scrip_code"),
                            "company_name": row.get("company_name"),
                            "announced_at": str(row.get("announced_at") or ""),
                            "period_start": str(row.get("period_start") or ""),
                            "period_end": str(row.get("period_end") or ""),
                            "as_of_date": str(row.get("as_of_date") or ""),
                            "attachment_url": row.get("attachment_url"),
                            "source_url": row.get("source_url"),
                            "summary": row.get("summary_json") or {},
                        })
                        _upsert_edge(cur, company_vid, disclosure_vid, "HAS_XBRL_DISCLOSURE", {
                            "category": row.get("category"),
                            "as_of_date": str(row.get("as_of_date") or ""),
                            "source_citation": "NSE_BSE_XBRL",
                        })
                        fact_hash = hashlib.sha1(
                            str((row.get("exchange"), row.get("source_uid"), row.get("category"))).encode("utf-8")
                        ).hexdigest()[:24]
                        _upsert_fact(
                            cur,
                            f"xbrl:DISCLOSURE:{fact_hash}",
                            company_vid,
                            "HAS_XBRL_DISCLOSURE",
                            object_entity_id=disclosure_vid,
                            as_of_date=row.get("as_of_date") or row.get("period_end"),
                            source_table="corporate_event_xbrl",
                            source_uid=row.get("source_uid"),
                            source_url=row.get("attachment_url") or row.get("source_url"),
                            properties={
                                "category": row.get("category"),
                                "exchange": row.get("exchange"),
                                "summary": row.get("summary_json") or {},
                            },
                        )

                if xbrl_event_rows:
                    conn.commit()
                    logger.info("Created %d official event XBRL vertices/facts", len(xbrl_event_rows))

                fact_limit = int(os.getenv("FINAGENT_IKG_XBRL_FACT_LIMIT", "100000") or "0")
                fact_limit_sql = "limit %s" if fact_limit else ""
                fact_params: list[Any] = []
                fact_where = ""
                if nifty10_cins:
                    fact_where = "where cin = any(%s)"
                    fact_params.append(list(nifty10_cins))
                if fact_limit:
                    fact_params.append(fact_limit)
                try:
                    cur.execute(
                        f"""
                        select exchange, source_uid, category, cin, symbol, scrip_code,
                               fact_name, fact_key, value_text, value_numeric,
                               period_start, period_end, instant, attachment_url, source_url
                        from corporate_xbrl_facts
                        {fact_where}
                        order by fetched_at desc
                        {fact_limit_sql}
                        """,
                        fact_params,
                    )
                    xbrl_fact_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Generic XBRL fact graph step skipped: %s", exc)
                    xbrl_fact_rows = []

                with _write_pipeline(conn):
                    for row in xbrl_fact_rows:
                        cin = str(row.get("cin") or row.get("symbol") or row.get("scrip_code") or "").strip()
                        if not cin:
                            continue
                        company_vid = f"company:{cin}"
                        fact_key = str(row.get("fact_key") or row.get("fact_name") or "xbrl_fact")
                        predicate = f"XBRL_{fact_key[:64].upper()}"[:80]
                        fact_hash = hashlib.sha1(
                            str((
                                row.get("exchange"),
                                row.get("source_uid"),
                                row.get("fact_name"),
                                row.get("value_text"),
                            )).encode("utf-8")
                        ).hexdigest()[:28]
                        _upsert_fact(
                            cur,
                            f"xbrl:FACT:{fact_hash}",
                            company_vid,
                            predicate,
                            object_value=str(row.get("value_text") or ""),
                            value_numeric=row.get("value_numeric"),
                            as_of_date=row.get("period_end") or row.get("instant"),
                            source_table="corporate_xbrl_facts",
                            source_uid=row.get("source_uid"),
                            source_url=row.get("attachment_url") or row.get("source_url"),
                            properties={
                                "exchange": row.get("exchange"),
                                "category": row.get("category"),
                                "fact_name": row.get("fact_name"),
                                "fact_key": row.get("fact_key"),
                                "period_start": str(row.get("period_start") or ""),
                                "period_end": str(row.get("period_end") or ""),
                                "instant": str(row.get("instant") or ""),
                            },
                        )

                if xbrl_fact_rows:
                    conn.commit()
                    logger.info("Created %d generic official XBRL facts", len(xbrl_fact_rows))

                # ── 5. Annual reports -> Document + TextChunk edges ──────────
                annual_statuses = ("ok", "metadata_only", "targeted")
                annual_where = "where extraction_status = any(%s) and cin = any(%s)" if nifty10_cins else "where extraction_status = any(%s)"
                annual_params = [list(annual_statuses), list(nifty10_cins)] if nifty10_cins else [list(annual_statuses)]
                try:
                    cur.execute(
                        f"""
                        select report_uid, cin, nse_symbol, scrip_code, company_name, report_year,
                               pdf_url, source_url, extracted_model, page_count, tables_count,
                               full_text_length, fetched_at
                        from annual_reports_raw
                        {annual_where}
                        order by fetched_at desc
                        """,
                        annual_params,
                    )
                    annual_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Annual reports graph step skipped: %s", exc)
                    annual_rows = []

                report_vertex_ids: dict[str, str] = {}
                for report in annual_rows:
                    report_uid = str(report.get("report_uid") or "").strip()
                    if not report_uid:
                        continue
                    company_ref = (
                        str(report.get("cin") or "").strip()
                        or str(report.get("nse_symbol") or "").strip()
                        or str(report.get("scrip_code") or "").strip()
                    )
                    if not company_ref:
                        continue
                    company_vid = f"company:{company_ref}"
                    doc_vid = f"document:annual:{report_uid}"
                    report_vertex_ids[report_uid] = doc_vid

                    _upsert_vertex(cur, doc_vid, "Document", {
                        "document_type": "annual_report",
                        "report_uid": report_uid,
                        "cin": report.get("cin"),
                        "nse_symbol": report.get("nse_symbol"),
                        "scrip_code": report.get("scrip_code"),
                        "company_name": report.get("company_name"),
                        "report_year": report.get("report_year"),
                        "pdf_url": report.get("pdf_url"),
                        "source_url": report.get("source_url"),
                        "extracted_model": report.get("extracted_model"),
                        "page_count": report.get("page_count"),
                        "tables_count": report.get("tables_count"),
                        "full_text_length": report.get("full_text_length"),
                        "fetched_at": str(report.get("fetched_at") or ""),
                    })
                    _upsert_edge(cur, company_vid, doc_vid, "HAS_ANNUAL_REPORT", {
                        "report_year": report.get("report_year"),
                        "pdf_url": report.get("pdf_url"),
                        "source_citation": "BSE_annual_reports",
                    })

                conn.commit()
                logger.info("Created %d AnnualReport document vertices + edges", len(annual_rows))

                include_annual_chunks = str(os.getenv("FINAGENT_IKG_INCLUDE_ANNUAL_CHUNKS", "1")).strip().lower() not in {
                    "0", "false", "no", "off",
                }
                annual_chunk_rows: list[dict[str, Any]] = []
                if include_annual_chunks and report_vertex_ids:
                    try:
                        cur.execute(
                            """
                            select report_uid, chunk_index, total_chunks, chunk_id, chunk_text, char_count, source_file
                            from annual_report_chunks
                            where report_uid = any(%s)
                            order by report_uid, chunk_index
                            """,
                            (list(report_vertex_ids.keys()),),
                        )
                        annual_chunk_rows = cur.fetchall()
                    except Exception as exc:
                        conn.rollback()
                        logger.warning("Annual report chunk graph step skipped: %s", exc)
                        annual_chunk_rows = []

                for chunk in annual_chunk_rows:
                    report_uid = str(chunk.get("report_uid") or "").strip()
                    doc_vid = report_vertex_ids.get(report_uid)
                    if not doc_vid:
                        continue
                    chunk_index = int(chunk.get("chunk_index") or 0)
                    chunk_text = str(chunk.get("chunk_text") or "")
                    chunk_vid = f"chunk:annual:{report_uid}:{chunk_index}"
                    _upsert_vertex(cur, chunk_vid, "TextChunk", {
                        "report_uid": report_uid,
                        "chunk_id": chunk.get("chunk_id"),
                        "chunk_index": chunk_index,
                        "total_chunks": chunk.get("total_chunks"),
                        "char_count": chunk.get("char_count") or len(chunk_text),
                        "source_file": chunk.get("source_file"),
                        "text_preview": chunk_text[:700],
                    })
                    _upsert_edge(cur, doc_vid, chunk_vid, "HAS_TEXT_CHUNK", {
                        "chunk_index": chunk_index,
                        "char_count": chunk.get("char_count") or len(chunk_text),
                        "source_citation": "BSE_annual_reports",
                    })

                if annual_chunk_rows:
                    conn.commit()
                    logger.info("Created %d AnnualReport chunk vertices + edges", len(annual_chunk_rows))

                annual_section_rows: list[dict[str, Any]] = []
                if report_vertex_ids:
                    try:
                        cur.execute(
                            """
                            select *
                            from document_sections
                            where source_table = 'annual_reports_raw'
                              and source_uid = any(%s)
                            order by source_uid, page_start nulls last, page_end nulls last
                            """,
                            (list(report_vertex_ids.keys()),),
                        )
                        annual_section_rows = cur.fetchall()
                    except Exception as exc:
                        conn.rollback()
                        logger.warning("Annual report section graph step skipped: %s", exc)
                        annual_section_rows = []

                for section in annual_section_rows:
                    report_uid = str(section.get("source_uid") or "").strip()
                    doc_vid = report_vertex_ids.get(report_uid)
                    if not doc_vid:
                        continue
                    section_key = f"{report_uid}:{section.get('section_type')}:{section.get('page_start')}:{section.get('page_end')}"
                    section_vid = f"section:{hashlib.sha1(section_key.encode('utf-8')).hexdigest()[:24]}"
                    text = str(section.get("text") or "")
                    _upsert_vertex(cur, section_vid, "DocumentSection", {
                        "document_uid": section.get("document_uid"),
                        "document_type": section.get("document_type"),
                        "section_type": section.get("section_type"),
                        "title": section.get("title"),
                        "page_start": section.get("page_start"),
                        "page_end": section.get("page_end"),
                        "text_length": section.get("text_length") or len(text),
                        "text_preview": text[:900],
                        "source_url": section.get("source_url"),
                    })
                    _upsert_edge(cur, doc_vid, section_vid, "HAS_DOCUMENT_SECTION", {
                        "section_type": section.get("section_type"),
                        "page_start": section.get("page_start"),
                        "page_end": section.get("page_end"),
                        "source_citation": "BSE_annual_reports_targeted",
                    })

                if annual_section_rows:
                    conn.commit()
                    logger.info("Created %d AnnualReport section vertices + edges", len(annual_section_rows))

                # ── 6. Corporate filings -> MADE_CORPORATE_FILING edges ──────
                filing_where = "WHERE cin = ANY(%s)" if nifty10_cins else ""
                filing_params = [list(nifty10_cins)] if nifty10_cins else []
                try:
                    cur.execute(
                        f"""
                        SELECT * FROM corporate_filings_raw
                        {filing_where}
                        ORDER BY announced_at DESC NULLS LAST
                        LIMIT 5000
                        """,
                        filing_params,
                    )
                    filing_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Corporate filings graph step skipped: %s", exc)
                    filing_rows = []
                with _write_pipeline(conn):
                    for filing in filing_rows:
                        cin = filing.get("cin")
                        source_uid = filing.get("source_uid")
                        exchange = filing.get("exchange")
                        if not cin or not source_uid or not exchange:
                            continue
                        company_vid = f"company:{cin}"
                        filing_vid = f"filing:{exchange}:{source_uid}"
                        _upsert_vertex(cur, filing_vid, "CorporateFiling", {
                            "category": filing.get("category"),
                            "exchange": exchange,
                            "symbol": filing.get("symbol"),
                            "scrip_code": filing.get("scrip_code"),
                            "title": filing.get("title"),
                            "announced_at": str(filing.get("announced_at") or ""),
                            "attachment_url": filing.get("attachment_url"),
                            "source_map_url": filing.get("source_map_url"),
                        })
                        _upsert_edge(cur, company_vid, filing_vid, "MADE_CORPORATE_FILING", {
                            "category": filing.get("category"),
                            "exchange": exchange,
                            "announced_at": str(filing.get("announced_at") or ""),
                            "source_citation": "NSE_BSE_corporate_filings",
                        })

                conn.commit()
                logger.info("Created %d CorporateFiling vertices + edges", len(filing_rows))

                # ── 7. Corporate Actions -> HAS_CORPORATE_ACTION edges ──
                action_where = "where cin = any(%s)" if nifty10_cins else ""
                action_params = [list(nifty10_cins)] if nifty10_cins else []
                try:
                    cur.execute(
                        f"""
                        select *
                        from corporate_actions_raw
                        {action_where}
                        order by announced_at desc nulls last
                        limit 10000
                        """,
                        action_params,
                    )
                    action_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Corporate actions graph step skipped: %s", exc)
                    action_rows = []

                with _write_pipeline(conn):
                    for action in action_rows:
                        cin = str(action.get("cin") or action.get("symbol") or action.get("scrip_code") or "").strip()
                        if not cin:
                            continue
                        company_vid = f"company:{cin}"
                        action_vid = _stable_vertex_id(
                            "corporate_action",
                            action.get("exchange"),
                            action.get("source_uid"),
                            action.get("action_type"),
                        )
                        _upsert_vertex(cur, action_vid, "CorporateAction", {
                            "action_type": action.get("action_type"),
                            "ratio": action.get("ratio"),
                            "record_date_raw": action.get("record_date_raw"),
                            "title": action.get("title"),
                            "announced_at": str(action.get("announced_at") or ""),
                            "attachment_url": action.get("attachment_url"),
                            "source_url": action.get("source_url"),
                        })
                        _upsert_edge(cur, company_vid, action_vid, "HAS_CORPORATE_ACTION", {
                            "action_type": action.get("action_type"),
                            "ratio": action.get("ratio"),
                            "announced_at": str(action.get("announced_at") or ""),
                            "source_citation": "NSE_BSE_corporate_filings",
                        })
                        fact_hash = hashlib.sha1(
                            str((action.get("exchange"), action.get("source_uid"), action.get("action_type"))).encode("utf-8")
                        ).hexdigest()[:24]
                        _upsert_fact(
                            cur,
                            f"corporate_action:{fact_hash}",
                            company_vid,
                            "HAS_CORPORATE_ACTION",
                            object_entity_id=action_vid,
                            event_date=action.get("announced_at"),
                            source_table="corporate_actions_raw",
                            source_uid=action.get("source_uid"),
                            source_url=action.get("attachment_url") or action.get("source_url"),
                            evidence_text=action.get("title"),
                            properties={
                                "action_type": action.get("action_type"),
                                "ratio": action.get("ratio"),
                                "record_date_raw": action.get("record_date_raw"),
                            },
                        )

                if action_rows:
                    conn.commit()
                    logger.info("Created %d CorporateAction vertices/facts", len(action_rows))

                auditor_section_params: list[Any] = ["%statutory auditor%", "%auditors%"]
                auditor_section_where = """
                where (
                  section_type in ('audit_and_risk', 'governance')
                  or text ilike %s
                  or text ilike %s
                )
                """
                if nifty10_cins:
                    auditor_section_where += """
                    and (
                      metadata->>'cin' = any(%s)
                      or metadata->>'company_cin' = any(%s)
                      or source_uid in (
                        select report_uid from annual_reports_raw where cin = any(%s)
                      )
                    )
                    """
                    auditor_section_params.extend([list(nifty10_cins), list(nifty10_cins), list(nifty10_cins)])
                try:
                    cur.execute(
                        f"""
                        select *
                        from document_sections
                        {auditor_section_where}
                        order by updated_at desc
                        limit 5000
                        """,
                        auditor_section_params,
                    )
                    auditor_sections = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Auditor section extraction skipped: %s", exc)
                    auditor_sections = []

                if auditor_sections:
                    from finagent.ikg.scrapers.xbrl_utils import extract_auditor_names_from_text

                    with _write_pipeline(conn):
                        for section in auditor_sections:
                            metadata = section.get("metadata") or {}
                            if isinstance(metadata, str):
                                try:
                                    metadata = json.loads(metadata)
                                except Exception:
                                    metadata = {}
                            cin = str(metadata.get("cin") or metadata.get("company_cin") or "").strip()
                            if not cin and section.get("source_table") == "annual_reports_raw":
                                cur.execute(
                                    "select cin from annual_reports_raw where report_uid = %s limit 1",
                                    (section.get("source_uid"),),
                                )
                                row = cur.fetchone()
                                cin = str((row or {}).get("cin") if isinstance(row, dict) else (row[0] if row else "") or "").strip()
                            if not cin:
                                continue
                            fiscal_year = str(metadata.get("fiscal_year") or metadata.get("report_year") or "").strip() or None
                            text = str(section.get("text") or "")
                            for auditor in extract_auditor_names_from_text(text):
                                auditor_name = auditor.get("auditor_name")
                                if not auditor_name:
                                    continue
                                cur.execute(
                                    """
                                    insert into auditor_history_raw (
                                      cin, auditor_name, role, fiscal_year, source_table,
                                      source_uid, source_url, evidence_text, confidence,
                                      parser_version, fetched_at
                                    )
                                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                                    on conflict do nothing
                                    """,
                                    (
                                        cin,
                                        auditor_name,
                                        "statutory_auditor",
                                        fiscal_year,
                                        section.get("source_table"),
                                        section.get("source_uid"),
                                        section.get("source_url"),
                                        text[:1000],
                                        0.72,
                                        "auditor_history_v1",
                                    ),
                                )
                    conn.commit()
                    logger.info("Scanned %d sections for auditor history", len(auditor_sections))

                auditor_where = "where cin = any(%s)" if nifty10_cins else ""
                auditor_params = [list(nifty10_cins)] if nifty10_cins else []
                try:
                    cur.execute(
                        f"""
                        select *
                        from auditor_history_raw
                        {auditor_where}
                        order by fiscal_year desc nulls last, fetched_at desc
                        limit 10000
                        """,
                        auditor_params,
                    )
                    auditor_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Auditor history graph step skipped: %s", exc)
                    auditor_rows = []

                with _write_pipeline(conn):
                    for auditor in auditor_rows:
                        cin = str(auditor.get("cin") or "").strip()
                        auditor_name = str(auditor.get("auditor_name") or "").strip()
                        if not cin or not auditor_name:
                            continue
                        company_vid = f"company:{cin}"
                        slug = re.sub(r"[^A-Z0-9]+", "_", auditor_name.upper()).strip("_")[:100] or "UNKNOWN_AUDITOR"
                        auditor_vid = f"auditor:{slug}"
                        _upsert_vertex(cur, auditor_vid, "Auditor", {
                            "name": auditor_name,
                            "role": auditor.get("role"),
                        })
                        _upsert_edge(cur, auditor_vid, company_vid, "AUDITOR_OF", {
                            "role": auditor.get("role"),
                            "fiscal_year": auditor.get("fiscal_year"),
                            "source_citation": auditor.get("source_table"),
                        })
                        fact_hash = hashlib.sha1(
                            str((cin, auditor_name, auditor.get("fiscal_year"), auditor.get("source_uid"))).encode("utf-8")
                        ).hexdigest()[:24]
                        _upsert_fact(
                            cur,
                            f"auditor:{fact_hash}",
                            auditor_vid,
                            "AUDITOR_OF",
                            object_entity_id=company_vid,
                            source_table="auditor_history_raw",
                            source_uid=auditor.get("source_uid"),
                            source_url=auditor.get("source_url"),
                            evidence_text=auditor.get("evidence_text"),
                            properties={
                                "role": auditor.get("role"),
                                "fiscal_year": auditor.get("fiscal_year"),
                                "confidence": auditor.get("confidence"),
                            },
                        )

                if auditor_rows:
                    conn.commit()
                    logger.info("Created %d Auditor vertices/facts", len(auditor_rows))

                try:
                    cur.execute("SELECT * FROM enforcement_raw ORDER BY order_date DESC NULLS LAST LIMIT 2000")
                    orders = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Enforcement orders graph step skipped: %s", exc)
                    orders = []

                # Build name-to-CIN lookup from entity aliases for name-based matching
                _name_to_cin: dict[str, str] = {}
                try:
                    cur.execute(
                        "SELECT entity_id, alias FROM ikg_entity_aliases "
                        "WHERE entity_id LIKE 'company:%%' AND alias_type IN ('legal_name', 'nse_symbol', 'name')"
                    )
                    for eid, alias in cur.fetchall():
                        cin_val = eid.replace("company:", "")
                        normalized = re.sub(r"\s+", " ", (alias or "").strip().upper())
                        if normalized and len(normalized) >= 4:
                            _name_to_cin[normalized] = cin_val
                except Exception:
                    conn.rollback()
                    logger.debug("Could not build name-to-CIN lookup for enforcement matching")

                regulator_vid = "regulator:SEBI"
                _upsert_vertex(cur, regulator_vid, "Regulator", {
                    "name": "Securities and Exchange Board of India",
                    "abbreviation": "SEBI",
                    "jurisdiction": "India",
                })
                enforcement_edges_created = 0
                with _write_pipeline(conn):
                    for order in orders:
                        oid = order.get("order_number")
                        if not oid:
                            continue
                        order_vid = f"regulator_action:{oid}"
                        _upsert_vertex(cur, order_vid, "RegulatorAction", {
                            "order_number": oid,
                            "violation_type": order.get("violation_type"),
                            "penalty_amount_inr": order.get("penalty_amount_inr"),
                            "order_date": str(order.get("order_date") or ""),
                            "pdf_url": order.get("pdf_url"),
                            "regulator": "SEBI",
                        })
                        _upsert_edge(cur, regulator_vid, order_vid, "ISSUED", {
                            "order_date": str(order.get("order_date") or ""),
                        })
                        entities = order.get("entities_json") or {}
                        if isinstance(entities, str):
                            try:
                                entities = json.loads(entities)
                            except Exception:
                                entities = {}
                        linked_cins: set[str] = set()
                        for cin in entities.get("cins", []):
                            linked_cins.add(cin)
                        # Match company names from NER against known entities
                        for company_name in entities.get("companies", []):
                            normalized = re.sub(r"\s+", " ", (company_name or "").strip().upper())
                            if len(normalized) < 6:
                                continue
                            matched_cin = _name_to_cin.get(normalized)
                            if not matched_cin:
                                # Try stripping common suffixes for partial match
                                for suffix in (" LIMITED", " LTD", " LTD.", " PRIVATE LIMITED", " PVT. LTD", " PVT LTD"):
                                    base = normalized.removesuffix(suffix)
                                    if base != normalized:
                                        for alias_name, alias_cin in _name_to_cin.items():
                                            if alias_name.startswith(base) and alias_cin not in linked_cins:
                                                matched_cin = alias_cin
                                                break
                                    if matched_cin:
                                        break
                            if matched_cin:
                                linked_cins.add(matched_cin)
                        for cin in linked_cins:
                            target_vid = f"company:{cin}"
                            _upsert_vertex(cur, target_vid, "Company", {
                                "cin": cin,
                                "source_citation": "SEBI_enforcement",
                            })
                            _upsert_edge(cur, order_vid, target_vid, "ENFORCEMENT_ACTION_AGAINST", {
                                "source_citation": "SEBI_enforcement",
                            })
                            enforcement_edges_created += 1

                conn.commit()
                logger.info(
                    "Created %d SEBI Enforcement vertices, %d company edges (from %d orders)",
                    len(orders), enforcement_edges_created, len(orders),
                )

                # ── 8. Canonical document_sections -> evidence graph edges ──
                section_where = ""
                section_params: list[Any] = []
                if nifty10_cins:
                    section_where = """
                    where (
                      metadata->>'cin' = any(%s)
                      or metadata->>'company_cin' = any(%s)
                      or source_uid in (
                        select report_uid from annual_reports_raw where cin = any(%s)
                      )
                    )
                    """
                    section_params = [list(nifty10_cins), list(nifty10_cins), list(nifty10_cins)]
                try:
                    cur.execute(
                        f"""
                        select *
                        from document_sections
                        {section_where}
                        order by updated_at desc
                        limit 20000
                        """,
                        section_params,
                    )
                    section_rows = cur.fetchall()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Generic document section graph step skipped: %s", exc)
                    section_rows = []

                with _write_pipeline(conn):
                    for section in section_rows:
                        source_table = str(section.get("source_table") or "")
                        if source_table == "annual_reports_raw":
                            continue
                        metadata = section.get("metadata") or {}
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except Exception:
                                metadata = {}
                        if not isinstance(metadata, dict):
                            metadata = {}

                        section_key = (
                            f"{section.get('document_uid')}:{section.get('source_table')}:"
                            f"{section.get('source_uid')}:{section.get('section_type')}:"
                            f"{section.get('page_start')}:{section.get('page_end')}"
                        )
                        section_vid = f"section:{hashlib.sha1(section_key.encode('utf-8')).hexdigest()[:24]}"
                        text = str(section.get("text") or "")
                        _upsert_vertex(cur, section_vid, "DocumentSection", {
                            "document_uid": section.get("document_uid"),
                            "source_table": source_table,
                            "source_uid": section.get("source_uid"),
                            "document_type": section.get("document_type"),
                            "section_type": section.get("section_type"),
                            "title": section.get("title"),
                            "page_start": section.get("page_start"),
                            "page_end": section.get("page_end"),
                            "text_length": section.get("text_length") or len(text),
                            "text_preview": text[:900],
                            "source_url": section.get("source_url"),
                        })

                        doc_vid = f"document:{section.get('document_uid')}"
                        company_ref = str(metadata.get("cin") or metadata.get("company_cin") or "").strip()
                        if source_table == "corporate_filings_raw":
                            original_uid = str(metadata.get("original_source_uid") or section.get("source_uid") or "")
                            exchange = str(metadata.get("exchange") or "").strip()
                            doc_vid = f"filing:{exchange}:{original_uid}" if exchange and original_uid else doc_vid
                        elif source_table == "enforcement_raw":
                            order_number = str(metadata.get("original_order_number") or "").strip()
                            doc_vid = f"regulator_action:{order_number}" if order_number else doc_vid
                        elif source_table == "concall_transcripts_raw":
                            doc_vid = f"document:concall:{section.get('source_uid')}"
                            _upsert_vertex(cur, doc_vid, "Document", {
                                "document_type": "concall_transcript",
                                "symbol": metadata.get("symbol") or metadata.get("nse_symbol"),
                                "company_name": metadata.get("company_name"),
                                "cin": company_ref or None,
                                "announced_at": metadata.get("announced_at"),
                                "quarter_label": metadata.get("quarter_label"),
                                "fiscal_year": metadata.get("fiscal_year"),
                                "source_url": section.get("source_url"),
                            })
                            if company_ref:
                                _upsert_edge(cur, f"company:{company_ref}", doc_vid, "HAS_CONCALL_TRANSCRIPT", {
                                    "announced_at": metadata.get("announced_at"),
                                    "quarter_label": metadata.get("quarter_label"),
                                    "source_citation": "NSE_concall_transcripts",
                                })
                        elif source_table == "director_source_records":
                            doc_vid = f"document:director_source:{section.get('source_uid')}"
                            _upsert_vertex(cur, doc_vid, "Document", {
                                "document_type": "director_governance_document",
                                "source": metadata.get("source"),
                                "symbol": metadata.get("symbol") or metadata.get("nse_symbol"),
                                "cin": company_ref or None,
                                "quarter": metadata.get("quarter"),
                                "source_url": section.get("source_url"),
                            })
                            if company_ref:
                                _upsert_edge(cur, f"company:{company_ref}", doc_vid, "HAS_DIRECTOR_SOURCE_DOCUMENT", {
                                    "quarter": metadata.get("quarter"),
                                    "source_citation": "NSE_BSE_corporate_governance",
                                })

                        if doc_vid.startswith("document:") and source_table not in {
                            "concall_transcripts_raw",
                            "director_source_records",
                        }:
                            _upsert_vertex(cur, doc_vid, "Document", {
                                "document_uid": section.get("document_uid"),
                                "document_type": section.get("document_type"),
                                "source_table": source_table,
                                "source_uid": section.get("source_uid"),
                                "source_url": section.get("source_url"),
                            })

                        _upsert_edge(cur, doc_vid, section_vid, "HAS_DOCUMENT_SECTION", {
                            "section_type": section.get("section_type"),
                            "page_start": section.get("page_start"),
                            "page_end": section.get("page_end"),
                            "source_citation": source_table,
                        })

                if section_rows:
                    conn.commit()
                    logger.info("Created %d generic DocumentSection vertices + evidence edges", len(section_rows))

        logger.info(
            "IKG graph build complete: %d vertices, %d edges",
            vertices_created, edges_created,
        )
        return {"vertices_created": vertices_created, "edges_created": edges_created}

    except Exception as exc:
        logger.error("build_ikg_from_staging failed: %s", exc)
        return {"vertices_created": vertices_created, "edges_created": edges_created, "error": str(exc)}
