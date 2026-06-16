from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row

from finagent.env import load_finagent_env
from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.pipeline.target_company_smoke import run_target_company_smoke


@dataclass(frozen=True)
class TableSpec:
    name: str
    cin_col: str | None = None
    symbol_col: str | None = None
    scrip_col: str | None = None
    name_col: str | None = None
    uid_col: str = "id"


_TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec("company_financials", cin_col="cin", symbol_col="nse_symbol", uid_col="nse_symbol"),
    TableSpec("shp_raw", cin_col="cin", scrip_col="scrip_code"),
    TableSpec("corporate_filings_raw", cin_col="cin", symbol_col="symbol", scrip_col="scrip_code", name_col="company_name", uid_col="source_uid"),
    TableSpec("xbrl_filings_raw", cin_col="cin", symbol_col="symbol", scrip_col="scrip_code", name_col="company_name", uid_col="source_uid"),
    TableSpec("corporate_xbrl_facts", cin_col="cin", symbol_col="symbol", scrip_col="scrip_code"),
    TableSpec("financial_results_xbrl", cin_col="cin", symbol_col="symbol", scrip_col="scrip_code", name_col="company_name", uid_col="source_uid"),
    TableSpec("corporate_event_xbrl", cin_col="cin", symbol_col="symbol", scrip_col="scrip_code", name_col="company_name", uid_col="source_uid"),
    TableSpec("corporate_actions_raw", cin_col="cin", symbol_col="symbol", scrip_col="scrip_code", name_col="company_name", uid_col="source_uid"),
    TableSpec("annual_reports_raw", cin_col="cin", symbol_col="nse_symbol", scrip_col="scrip_code", name_col="company_name", uid_col="report_uid"),
    TableSpec("concall_transcripts_raw", cin_col="cin", symbol_col="symbol", name_col="company_name", uid_col="attachment_url"),
    TableSpec("directors_raw", cin_col="cin", symbol_col="nse_symbol", scrip_col="bse_scrip_code", uid_col="din"),
    TableSpec("director_source_records", cin_col="cin", symbol_col="nse_symbol", scrip_col="bse_scrip_code", uid_col="filing_url"),
)


def _match_sql(spec: TableSpec) -> str:
    clauses: list[str] = []
    if spec.cin_col:
        clauses.append(f"{spec.cin_col} = %(cin)s")
    if spec.symbol_col:
        clauses.append(f"upper(coalesce({spec.symbol_col}, '')) = upper(%(symbol)s)")
    if spec.scrip_col:
        clauses.append(f"coalesce({spec.scrip_col}, '') = %(scrip)s")
    return " or ".join(clauses) or "false"


def _consistent_sql(spec: TableSpec) -> str:
    clauses: list[str] = []
    if spec.cin_col:
        clauses.append(f"(coalesce({spec.cin_col}, '') = '' or {spec.cin_col} = %(cin)s)")
    if spec.symbol_col:
        clauses.append(f"(coalesce({spec.symbol_col}, '') = '' or upper({spec.symbol_col}) = upper(%(symbol)s))")
    if spec.scrip_col:
        clauses.append(f"(coalesce({spec.scrip_col}, '') = '' or {spec.scrip_col} = %(scrip)s)")
    return " and ".join(clauses) or "true"


def _table_columns(spec: TableSpec) -> list[str]:
    cols = [spec.uid_col]
    if spec.cin_col:
        cols.append(spec.cin_col)
    if spec.symbol_col:
        cols.append(spec.symbol_col)
    if spec.scrip_col:
        cols.append(spec.scrip_col)
    if spec.name_col:
        cols.append(spec.name_col)
    return cols


def _safe_update_assignments(spec: TableSpec) -> list[str]:
    updates: list[str] = []
    if spec.cin_col:
        updates.append(f"{spec.cin_col} = case when coalesce({spec.cin_col}, '') = '' then %(cin)s else {spec.cin_col} end")
    if spec.symbol_col:
        updates.append(
            f"{spec.symbol_col} = case when coalesce({spec.symbol_col}, '') = '' then upper(%(symbol)s) else upper({spec.symbol_col}) end"
        )
    if spec.scrip_col:
        updates.append(f"{spec.scrip_col} = case when coalesce({spec.scrip_col}, '') = '' then %(scrip)s else {spec.scrip_col} end")
    if spec.name_col:
        updates.append(f"{spec.name_col} = case when coalesce({spec.name_col}, '') = '' then %(company_name)s else {spec.name_col} end")
    return updates


def _identity_summary(cur: Any, spec: TableSpec, params: dict[str, str]) -> dict[str, Any]:
    select_cols = [
        f"coalesce({spec.cin_col}, '') as cin" if spec.cin_col else "'' as cin",
        f"coalesce({spec.symbol_col}, '') as symbol" if spec.symbol_col else "'' as symbol",
        f"coalesce({spec.scrip_col}, '') as scrip_code" if spec.scrip_col else "'' as scrip_code",
        f"coalesce({spec.name_col}, '') as company_name" if spec.name_col else "'' as company_name",
    ]
    cur.execute(
        f"""
        select {", ".join(select_cols)}, count(*) as row_count
        from {spec.name}
        where {_match_sql(spec)}
        group by 1, 2, 3, 4
        order by row_count desc, cin, symbol, scrip_code
        limit 20
        """,
        params,
    )
    groups = cur.fetchall()

    cur.execute(
        f"""
        select count(*) as suspicious_rows
        from {spec.name}
        where ({_match_sql(spec)}) and not ({_consistent_sql(spec)})
        """,
        params,
    )
    suspicious = cur.fetchone()

    sample_columns = ", ".join(_table_columns(spec))
    cur.execute(
        f"""
        select {sample_columns}
        from {spec.name}
        where ({_match_sql(spec)}) and not ({_consistent_sql(spec)})
        order by {spec.uid_col}
        limit 10
        """,
        params,
    )
    samples = cur.fetchall()

    return {
        "groups": groups,
        "suspicious_rows": int((suspicious or {}).get("suspicious_rows") or 0),
        "suspicious_samples": samples,
    }


def reconcile_company_records(
    *,
    database_url: str | None,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
    company_name: str,
) -> dict[str, Any]:
    db_url = get_database_url(database_url)
    if not db_url:
        raise RuntimeError("Database URL is not configured")
    params = {
        "symbol": symbol.upper(),
        "cin": cin,
        "scrip": bse_scrip_code,
        "company_name": company_name,
    }
    updates: dict[str, int] = {}

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for spec in _TABLE_SPECS:
                assignments = _safe_update_assignments(spec)
                if not assignments:
                    continue
                cur.execute(
                    f"""
                    update {spec.name}
                    set {", ".join(assignments)}
                    where ({_match_sql(spec)}) and ({_consistent_sql(spec)})
                    """,
                    params,
                )
                updates[spec.name] = cur.rowcount or 0

            cur.execute(
                """
                update document_sections ds
                set metadata = coalesce(ds.metadata, '{}'::jsonb)
                    || jsonb_build_object(
                        'cin', ar.cin,
                        'company_cin', ar.cin,
                        'nse_symbol', ar.nse_symbol,
                        'bse_scrip_code', ar.scrip_code,
                        'company_name', ar.company_name,
                        'company_identifier', coalesce(ar.cin, ar.nse_symbol, ar.scrip_code),
                        'report_uid', ar.report_uid,
                        'report_year', ar.report_year
                    ),
                    updated_at = now()
                from annual_reports_raw ar
                where ds.source_table = 'annual_reports_raw'
                  and ds.source_uid = ar.report_uid
                  and (
                    ar.cin = %(cin)s
                    or upper(coalesce(ar.nse_symbol, '')) = upper(%(symbol)s)
                    or coalesce(ar.scrip_code, '') = %(scrip)s
                  )
                """,
                params,
            )
            updates["document_sections"] = cur.rowcount or 0
        conn.commit()
    return updates


def audit_company_records(
    *,
    database_url: str | None,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
) -> dict[str, Any]:
    db_url = get_database_url(database_url)
    if not db_url:
        raise RuntimeError("Database URL is not configured")
    params = {"symbol": symbol.upper(), "cin": cin, "scrip": bse_scrip_code}
    report: dict[str, Any] = {"tables": {}, "graph": {}, "document_sections": {}}

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for spec in _TABLE_SPECS:
                report["tables"][spec.name] = _identity_summary(cur, spec, params)

            cur.execute(
                """
                select vertex_id, label, properties
                from ikg_vertices
                where vertex_id in (%s, %s, %s)
                order by vertex_id
                """,
                (f"company:{cin}", f"company:{symbol.upper()}", f"company:{bse_scrip_code}"),
            )
            report["graph"]["company_vertices"] = cur.fetchall()

            cur.execute(
                """
                select
                  count(*) filter (
                    where source_table = 'annual_reports_raw'
                      and (
                        coalesce(metadata->>'cin', '') = %s
                        or coalesce(metadata->>'company_cin', '') = %s
                        or coalesce(metadata->>'company_identifier', '') in (%s, %s, %s)
                      )
                  ) as annual_sections_visible,
                  count(*) filter (
                    where source_table = 'annual_reports_raw'
                  ) as annual_sections_total
                from document_sections
                where source_table = 'annual_reports_raw'
                  and source_uid in (
                    select report_uid
                    from annual_reports_raw
                    where cin = %s
                       or upper(coalesce(nse_symbol, '')) = upper(%s)
                       or coalesce(scrip_code, '') = %s
                  )
                """,
                (cin, cin, cin, symbol.upper(), bse_scrip_code, cin, symbol.upper(), bse_scrip_code),
            )
            report["document_sections"] = cur.fetchone() or {}

            cur.execute(
                """
                select count(*) as canonical_edges
                from ikg_edges
                where from_vertex_id = %s or to_vertex_id = %s
                """,
                (f"company:{cin}", f"company:{cin}"),
            )
            report["graph"]["canonical_edge_count"] = int((cur.fetchone() or {}).get("canonical_edges") or 0)

    return report


def cleanup_legacy_company_graph(
    *,
    database_url: str | None,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
) -> dict[str, Any]:
    db_url = get_database_url(database_url)
    if not db_url:
        raise RuntimeError("Database URL is not configured")

    canonical_vertex = f"company:{cin}"
    legacy_vertices = [
        vertex
        for vertex in {f"company:{symbol.upper()}", f"company:{bse_scrip_code}"}
        if vertex != canonical_vertex and vertex.split(":", 1)[1]
    ]
    result: dict[str, Any] = {}

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for legacy_vertex in legacy_vertices:
                cur.execute(
                    """
                    select from_vertex_id, to_vertex_id, label
                    from ikg_edges
                    where from_vertex_id = %s or to_vertex_id = %s
                    """,
                    (legacy_vertex, legacy_vertex),
                )
                legacy_edges = cur.fetchall()

                cur.execute(
                    """
                    select count(*) as fact_count
                    from ikg_facts
                    where subject_entity_id = %s or object_entity_id = %s
                    """,
                    (legacy_vertex, legacy_vertex),
                )
                fact_count = int((cur.fetchone() or {}).get("fact_count") or 0)

                missing_equivalents: list[dict[str, str]] = []
                for edge in legacy_edges:
                    candidate_from = canonical_vertex if edge["from_vertex_id"] == legacy_vertex else edge["from_vertex_id"]
                    candidate_to = canonical_vertex if edge["to_vertex_id"] == legacy_vertex else edge["to_vertex_id"]
                    cur.execute(
                        """
                        select 1
                        from ikg_edges
                        where from_vertex_id = %s and to_vertex_id = %s and label = %s
                        limit 1
                        """,
                        (candidate_from, candidate_to, edge["label"]),
                    )
                    if cur.fetchone() is None:
                        missing_equivalents.append({
                            "from_vertex_id": edge["from_vertex_id"],
                            "to_vertex_id": edge["to_vertex_id"],
                            "label": edge["label"],
                        })

                cleaned = False
                deleted_edges = 0
                deleted_vertices = 0
                if legacy_edges and fact_count == 0 and not missing_equivalents:
                    cur.execute(
                        "delete from ikg_edges where from_vertex_id = %s or to_vertex_id = %s",
                        (legacy_vertex, legacy_vertex),
                    )
                    deleted_edges = cur.rowcount or 0
                    cur.execute("delete from ikg_vertices where vertex_id = %s", (legacy_vertex,))
                    deleted_vertices = cur.rowcount or 0
                    cleaned = deleted_vertices > 0

                result[legacy_vertex] = {
                    "edge_count": len(legacy_edges),
                    "fact_count": fact_count,
                    "missing_equivalents": missing_equivalents,
                    "cleaned": cleaned,
                    "deleted_edges": deleted_edges,
                    "deleted_vertices": deleted_vertices,
                }
        conn.commit()
    return result


def run_company_integrity_audit(
    *,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
    company_name: str,
    years_back: int | None = None,
    reports_per_company: int | None = None,
    annual_extract_mode: str | None = None,
    corp_filings_extract_limit: int | None = None,
    qdrant_limit: int = 20,
    skip_qdrant: bool = True,
    database_url: str | None = None,
) -> dict[str, Any]:
    load_finagent_env()
    before = audit_company_records(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
    )
    reconciliation = reconcile_company_records(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
        company_name=company_name,
    )
    after_reconciliation = audit_company_records(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
    )
    smoke = run_target_company_smoke(
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
        company_name=company_name,
        years_back=years_back,
        reports_per_company=reports_per_company,
        annual_extract_mode=annual_extract_mode,
        corp_filings_extract_limit=corp_filings_extract_limit,
        qdrant_limit=qdrant_limit,
        skip_qdrant=skip_qdrant,
        database_url=database_url,
    )
    graph_cleanup = cleanup_legacy_company_graph(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
    )
    after_smoke = audit_company_records(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
    )
    return {
        "company": {
            "symbol": symbol.upper(),
            "cin": cin,
            "bse_scrip_code": bse_scrip_code,
            "company_name": company_name,
        },
        "before": before,
        "reconciliation": reconciliation,
        "after_reconciliation": after_reconciliation,
        "smoke": smoke,
        "graph_cleanup": graph_cleanup,
        "after_smoke": after_smoke,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit one-company IKG data integrity and rebuild coverage")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--cin", required=True)
    parser.add_argument("--bse-scrip", required=True)
    parser.add_argument("--company-name", required=True)
    parser.add_argument("--years-back", type=int, default=None)
    parser.add_argument("--reports-per-company", type=int, default=None)
    parser.add_argument("--annual-extract-mode", default=None)
    parser.add_argument("--corp-filings-extract-limit", type=int, default=None)
    parser.add_argument("--qdrant-limit", type=int, default=20)
    parser.add_argument("--skip-qdrant", action="store_true")
    args = parser.parse_args()

    result = run_company_integrity_audit(
        symbol=args.symbol,
        cin=args.cin,
        bse_scrip_code=args.bse_scrip,
        company_name=args.company_name,
        years_back=args.years_back,
        reports_per_company=args.reports_per_company,
        annual_extract_mode=args.annual_extract_mode,
        corp_filings_extract_limit=args.corp_filings_extract_limit,
        qdrant_limit=args.qdrant_limit,
        skip_qdrant=args.skip_qdrant,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
