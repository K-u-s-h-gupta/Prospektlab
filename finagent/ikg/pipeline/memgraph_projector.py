"""Project Postgres IKG graph tables into Memgraph."""

from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any

from finagent.ikg.db import connect_postgres, ensure_ikg_runtime_tables, get_database_url
from finagent.ikg.memgraph_client import MemgraphClient

logger = logging.getLogger("finagent.ikg.pipeline.memgraph_projector")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _fetch_vertex_batch(
    cur: Any,
    *,
    limit: int,
    offset: int,
    max_companies: int | None = None,
) -> list[dict[str, Any]]:
    company_filter = ""
    params: list[Any] = []
    if max_companies:
        company_filter = "where vertex_id in (select vertex_id from _memgraph_project_vertices)"
    params.extend([limit, offset])
    cur.execute(
        f"""
        select vertex_id, label, properties
        from ikg_vertices
        {company_filter}
        order by vertex_id
        limit %s offset %s
        """,
        params,
    )
    return [dict(row) for row in cur.fetchall()]


def _fetch_edge_batch(
    cur: Any,
    *,
    limit: int,
    offset: int,
    max_companies: int | None = None,
) -> list[dict[str, Any]]:
    edge_filter = ""
    params: list[Any] = []
    if max_companies:
        edge_filter = """
        where from_vertex_id in (select vertex_id from _memgraph_project_vertices)
          and to_vertex_id in (select vertex_id from _memgraph_project_vertices)
        """
    params.extend([limit, offset])
    cur.execute(
        f"""
        select id, from_vertex_id, to_vertex_id, label, properties
        from ikg_edges
        {edge_filter}
        order by id
        limit %s offset %s
        """,
        params,
    )
    return [dict(row) for row in cur.fetchall()]


def _prepare_company_scope(cur: Any, *, max_companies: int | None) -> None:
    cur.execute("drop table if exists _memgraph_project_vertices")
    cur.execute(
        """
        create temporary table _memgraph_project_vertices (
          vertex_id varchar(200) primary key
        ) on commit drop
        """
    )
    if not max_companies:
        cur.execute("insert into _memgraph_project_vertices select vertex_id from ikg_vertices")
        return
    cur.execute(
        """
        with target_companies as (
          select v.vertex_id
          from ikg_company_master c
          join ikg_vertices v
            on v.label = 'Company'
           and v.vertex_id = 'company:' || coalesce(c.cin, c.nse_symbol, c.bse_scrip_code)
          where coalesce(c.cin, c.nse_symbol, c.bse_scrip_code) is not null
          order by coalesce(nse_symbol, company_name, cin)
          limit %s
        ),
        neighbor_vertices as (
          select vertex_id from target_companies
          union
          select e.from_vertex_id
          from ikg_edges e join target_companies t on e.to_vertex_id = t.vertex_id
          union
          select e.to_vertex_id
          from ikg_edges e join target_companies t on e.from_vertex_id = t.vertex_id
        )
        insert into _memgraph_project_vertices(vertex_id)
        select distinct vertex_id from neighbor_vertices
        on conflict do nothing
        """,
        (max_companies,),
    )


def project_memgraph(
    *,
    database_url: str | None = None,
    batch_size: int = 1000,
    max_companies: int | None = None,
    rebuild: bool = False,
    init_schema: bool = True,
) -> dict[str, Any]:
    start = time.time()
    db_url = get_database_url(database_url)
    if not db_url:
        raise RuntimeError("IKG_DATABASE_URL/DATABASE_URL is required")
    ensure_ikg_runtime_tables(db_url)

    client = MemgraphClient()
    if init_schema:
        client.init_schema()
    if rebuild:
        client.clear()

    nodes_written = 0
    edges_written = 0
    from psycopg.rows import dict_row

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            _prepare_company_scope(cur, max_companies=max_companies)
            offset = 0
            while True:
                rows = _fetch_vertex_batch(cur, limit=batch_size, offset=offset, max_companies=max_companies)
                if not rows:
                    break
                nodes_written += client.upsert_nodes(rows)
                offset += batch_size
                logger.info("Memgraph node projection: nodes=%d", nodes_written)

            offset = 0
            while True:
                rows = _fetch_edge_batch(cur, limit=batch_size, offset=offset, max_companies=max_companies)
                if not rows:
                    break
                edges_written += client.upsert_relationships(rows)
                offset += batch_size
                logger.info("Memgraph relationship projection: relationships=%d", edges_written)

    health = client.health()
    return {
        "success": True,
        "nodes_projected": nodes_written,
        "relationships_projected": edges_written,
        "duration_s": round(time.time() - start, 2),
        "memgraph": health,
    }


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(description="Project Postgres IKG graph into Memgraph")
    parser.add_argument("--init", action="store_true", help="Create Memgraph indexes and exit")
    parser.add_argument("--health", action="store_true", help="Check Memgraph connectivity and counts")
    parser.add_argument("--rebuild", action="store_true", help="Clear Memgraph before projection")
    parser.add_argument("--incremental", action="store_true", help="Project without clearing Memgraph")
    parser.add_argument("--max-companies", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args(argv)

    client = MemgraphClient()
    if args.init:
        client.init_schema()
        print(json.dumps({"success": True, "initialized": True, "health": client.health()}, indent=2))
        return 0
    if args.health:
        print(json.dumps(client.health(), indent=2))
        return 0
    result = project_memgraph(
        batch_size=max(1, args.batch_size),
        max_companies=args.max_companies,
        rebuild=args.rebuild,
        init_schema=True,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
