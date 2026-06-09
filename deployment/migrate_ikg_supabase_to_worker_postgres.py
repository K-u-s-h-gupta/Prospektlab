"""Copy IKG tables from Supabase/Postgres into the worker Postgres database.

This script is intentionally non-destructive. It never drops or truncates the
source Supabase tables. Use it to move the worker load off Supabase, verify row
counts, then run a separate guarded prune SQL only after you are satisfied.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Iterable

import psycopg
from psycopg.rows import dict_row


IKG_TABLES: list[str] = [
    "runtime_controls",
    "ikg_scheduler_locks",
    "ikg_pipeline_runs",
    "ikg_company_master",
    "daily_prices",
    "shp_raw",
    "company_financials",
    "director_source_records",
    "directors_raw",
    "sebi_corporate_filing_map",
    "corporate_filings_raw",
    "xbrl_filings_raw",
    "corporate_xbrl_facts",
    "financial_results_xbrl",
    "corporate_event_xbrl",
    "corporate_actions_raw",
    "annual_reports_raw",
    "annual_report_chunks",
    "document_sections",
    "concall_transcripts_raw",
    "enforcement_raw",
    "ikg_vertices",
    "ikg_edges",
    "ikg_facts",
    "spl_strategies",
    "compliance_ledger",
]


APP_TABLES_STAY_IN_SUPABASE = [
    "profiles",
    "portfolio_mirrors",
    "pending_extractions",
    "token_usage",
    "referral_sources",
]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _worker_url_from_env() -> str:
    explicit = (
        os.getenv("IKG_WORKER_DATABASE_URL", "").strip()
        or os.getenv("TARGET_DATABASE_URL", "").strip()
        or os.getenv("WORKER_DATABASE_URL", "").strip()
    )
    if explicit:
        return explicit
    password = os.getenv("IKG_POSTGRES_PASSWORD", "ikg_password_change_me")
    return f"postgresql://ikg_user:{password}@127.0.0.1:15432/ikg"


def _source_url_from_env() -> str:
    return (
        os.getenv("SUPABASE_DB_URL", "").strip()
        or os.getenv("SUPABASE_DATABASE_URL", "").strip()
        or os.getenv("SOURCE_DATABASE_URL", "").strip()
    )


def _connect(url: str, **kwargs: object) -> psycopg.Connection:
    kwargs.setdefault("prepare_threshold", None)
    return psycopg.connect(url, **kwargs)


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_exists(conn: psycopg.Connection, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("select to_regclass(%s) is not null as exists", (f"public.{table}",))
        return bool(cur.fetchone()[0])


def _table_columns(conn: psycopg.Connection, table: str) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public'
              and table_name = %s
              and is_generated = 'NEVER'
            order by ordinal_position
            """,
            (table,),
        )
        return [str(row["column_name"]) for row in cur.fetchall()]


def _count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from public.{_qident(table)}")
        return int(cur.fetchone()[0])


def _execute_bootstrap(target_url: str, bootstrap_sql: Path) -> None:
    if not bootstrap_sql.exists():
        raise FileNotFoundError(f"bootstrap SQL not found: {bootstrap_sql}")
    sql = bootstrap_sql.read_text(encoding="utf-8")
    started = time.time()
    with _connect(target_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print(f"bootstrap_ok duration_s={time.time() - started:.1f}")


def _truncate_target(conn: psycopg.Connection, tables: Iterable[str]) -> None:
    existing = [t for t in tables if _table_exists(conn, t)]
    if not existing:
        return
    names = ", ".join(f"public.{_qident(t)}" for t in existing)
    with conn.cursor() as cur:
        cur.execute(f"truncate table {names} restart identity cascade")
    conn.commit()
    print(f"target_truncated tables={len(existing)}")


def _copy_sql(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    col_sql: str,
    select_sql: str,
    params: tuple[object, ...] = (),
) -> int:
    copied_bytes = 0
    with source.cursor().copy(
        f"copy ({select_sql}) to stdout with (format binary)",
        params,
    ) as src_copy:
        with target.cursor().copy(
            f"copy public.{_qident(table)} ({col_sql}) from stdin with (format binary)"
        ) as tgt_copy:
            for chunk in src_copy:
                copied_bytes += len(chunk)
                tgt_copy.write(chunk)
    target.commit()
    return copied_bytes


def _copy_table(
    source: psycopg.Connection,
    target: psycopg.Connection,
    table: str,
    *,
    chunk_rows: int = 50_000,
) -> tuple[int, int]:
    if not _table_exists(source, table):
        print(f"skip_missing_source table={table}")
        return (0, 0)
    if not _table_exists(target, table):
        print(f"skip_missing_target table={table}")
        return (_count(source, table), 0)

    source_cols = set(_table_columns(source, table))
    target_cols = _table_columns(target, table)
    cols = [c for c in target_cols if c in source_cols]
    if not cols:
        print(f"skip_no_common_columns table={table}")
        return (_count(source, table), _count(target, table))

    source_count = _count(source, table)
    if source_count == 0:
        print(f"copy_skip_empty table={table}")
        return (0, _count(target, table))

    col_sql = ", ".join(_qident(c) for c in cols)
    started = time.time()
    copied_bytes = 0

    if chunk_rows > 0 and "id" in source_cols and source_count > chunk_rows:
        last_id = 0
        chunk_no = 0
        while True:
            with source.cursor() as cur:
                cur.execute(
                    f"""
                    select {_qident("id")}
                    from public.{_qident(table)}
                    where {_qident("id")} > %s
                    order by {_qident("id")}
                    limit 1 offset %s
                    """,
                    (last_id, chunk_rows - 1),
                )
                boundary = cur.fetchone()
                if boundary:
                    end_id = int(boundary[0])
                else:
                    cur.execute(
                        f"select max({_qident('id')}) from public.{_qident(table)} where {_qident('id')} > %s",
                        (last_id,),
                    )
                    max_row = cur.fetchone()
                    end_id = int(max_row[0] or 0)
            if end_id <= last_id:
                break
            chunk_no += 1
            select_sql = (
                f"select {col_sql} from public.{_qident(table)} "
                f"where {_qident('id')} > %s and {_qident('id')} <= %s "
                f"order by {_qident('id')}"
            )
            chunk_bytes = _copy_sql(source, target, table, col_sql, select_sql, (last_id, end_id))
            copied_bytes += chunk_bytes
            print(
                f"copy_chunk_ok table={table} chunk={chunk_no} id_gt={last_id} id_lte={end_id} "
                f"bytes={chunk_bytes}"
            )
            last_id = end_id
    else:
        select_sql = f"select {col_sql} from public.{_qident(table)}"
        copied_bytes = _copy_sql(source, target, table, col_sql, select_sql)

    target.commit()
    target_count = _count(target, table)
    print(
        f"copy_ok table={table} source_rows={source_count} target_rows={target_count} "
        f"bytes={copied_bytes} duration_s={time.time() - started:.1f}"
    )
    return (source_count, target_count)


def _verify_counts(source: psycopg.Connection, target: psycopg.Connection, tables: Iterable[str]) -> bool:
    ok = True
    print("verify_counts")
    for table in tables:
        if not _table_exists(source, table):
            continue
        if not _table_exists(target, table):
            print(f"verify_fail table={table} reason=missing_target")
            ok = False
            continue
        source_count = _count(source, table)
        target_count = _count(target, table)
        status = "ok" if source_count == target_count else "mismatch"
        if status != "ok":
            ok = False
        print(f"verify_{status} table={table} source_rows={source_count} target_rows={target_count}")
    return ok


def _reset_target_sequences(conn: psycopg.Connection, tables: Iterable[str]) -> None:
    with conn.cursor() as cur:
        for table in tables:
            if not _table_exists(conn, table):
                continue
            cur.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = %s
                  and column_default like 'nextval%%'
                order by ordinal_position
                """,
                (table,),
            )
            for row in cur.fetchall():
                column = str(row[0])
                cur.execute("select pg_get_serial_sequence(%s, %s)", (f"public.{table}", column))
                seq = cur.fetchone()[0]
                if not seq:
                    continue
                cur.execute(f"select coalesce(max({_qident(column)}), 0) from public.{_qident(table)}")
                max_id = int(cur.fetchone()[0] or 0)
                if max_id > 0:
                    cur.execute("select setval(%s, %s, true)", (seq, max_id))
                    print(f"sequence_reset table={table} column={column} max={max_id}")
    conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate IKG tables from Supabase to worker Postgres")
    parser.add_argument("--env-file", default="finagent/.env", help="Local env file with source credentials")
    parser.add_argument("--source-url", default="", help="Supabase/Postgres source URL")
    parser.add_argument("--target-url", default="", help="Worker Postgres target URL")
    parser.add_argument("--bootstrap-sql", default="deployment/ikg_db_bootstrap.sql")
    parser.add_argument("--tables", nargs="*", default=IKG_TABLES, help="Tables to copy")
    parser.add_argument("--bootstrap", action="store_true", help="Run target bootstrap SQL first")
    parser.add_argument("--truncate-target", action="store_true", help="Truncate target IKG tables before copy")
    parser.add_argument("--verify-only", action="store_true", help="Only compare counts")
    parser.add_argument("--chunk-rows", type=int, default=50_000, help="Chunk size for large id-based tables")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _load_env_file(Path(args.env_file))
    source_url = args.source_url.strip() or _source_url_from_env()
    target_url = args.target_url.strip() or _worker_url_from_env()
    if not source_url:
        print("ERROR: source DB URL missing. Set SUPABASE_DB_URL or pass --source-url.", file=sys.stderr)
        return 2
    if not target_url:
        print("ERROR: target DB URL missing. Set IKG_WORKER_DATABASE_URL or pass --target-url.", file=sys.stderr)
        return 2

    if args.bootstrap:
        _execute_bootstrap(target_url, Path(args.bootstrap_sql))

    with _connect(source_url, connect_timeout=20) as source:
        with _connect(target_url, connect_timeout=20) as target:
            if args.verify_only:
                return 0 if _verify_counts(source, target, args.tables) else 1
            if args.truncate_target:
                _truncate_target(target, args.tables)
            for table in args.tables:
                _copy_table(source, target, table, chunk_rows=args.chunk_rows)
            _reset_target_sequences(target, args.tables)
            return 0 if _verify_counts(source, target, args.tables) else 1


if __name__ == "__main__":
    raise SystemExit(main())
