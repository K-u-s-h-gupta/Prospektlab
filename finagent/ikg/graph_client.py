"""IKG Graph Client — PostgreSQL adjacency-list + Memgraph projection.

Provides a unified async interface to the Indian Corporate Knowledge Graph.
Primary backend: PostgreSQL (durable source of truth via ikg_vertices / ikg_edges).
Query projection: Memgraph (rebuilt from Postgres, see memgraph_client.py).

Configuration (environment variables):
  IKG_BACKEND         = "postgres" | "memory" (default: "memory")
  IKG_DATABASE_URL    = postgresql://... for postgres backend
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

from finagent.ikg.db import connect_postgres, ensure_ikg_runtime_tables, get_database_url

logger = logging.getLogger("finagent.ikg.graph_client")

def _backend_name() -> str:
    return (os.getenv("IKG_BACKEND") or "memory").strip().lower()


class InMemoryGraphBackend:
    """Lightweight in-memory graph for dev/testing. Not persistent."""

    def __init__(self) -> None:
        self.vertices: dict[str, dict[str, Any]] = {}  # vertex_id → properties
        self.edges: list[dict[str, Any]] = []

    def upsert_vertex(self, vertex_id: str, label: str, props: dict[str, Any]) -> None:
        self.vertices[vertex_id] = {"id": vertex_id, "label": label, **props}

    def upsert_edge(self, from_id: str, to_id: str, label: str, props: dict[str, Any]) -> None:
        for e in self.edges:
            if e["from"] == from_id and e["to"] == to_id and e["label"] == label:
                e.update(props)
                return
        self.edges.append({"from": from_id, "to": to_id, "label": label, **props})

    def query_vertex(self, vertex_id: str) -> dict[str, Any] | None:
        return self.vertices.get(vertex_id)

    def query_edges_from(self, vertex_id: str, label: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self.edges if e["from"] == vertex_id and (not label or e["label"] == label)]

    def query_edges_to(self, vertex_id: str, label: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self.edges if e["to"] == vertex_id and (not label or e["label"] == label)]

    def query_by_property(self, label: str, prop: str, value: Any) -> list[dict[str, Any]]:
        return [v for v in self.vertices.values() if v.get("label") == label and v.get(prop) == value]

    def stats(self) -> dict[str, int]:
        return {"vertices": len(self.vertices), "edges": len(self.edges)}


class PostgresGraphBackend:
    """PostgreSQL adjacency-list graph backend for self-hosted deployments.

    Schema is created by deployment/ikg_db_bootstrap.sql.
    """

    def __init__(self) -> None:
        self.database_url = get_database_url(os.getenv("IKG_POSTGRES_URL", ""))

    def _connect(self) -> Any:
        try:
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL IKG backend") from exc
        if not self.database_url:
            raise RuntimeError("IKG_DATABASE_URL must be set for PostgreSQL IKG backend")
        ensure_ikg_runtime_tables(self.database_url)
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=10)

    def upsert_vertex(self, vertex_id: str, label: str, props: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ikg_vertices (vertex_id, label, properties)
                    values (%s, %s, %s::jsonb)
                    on conflict (vertex_id) do update
                      set label = excluded.label,
                          properties = ikg_vertices.properties || excluded.properties,
                          updated_at = now()
                    """,
                    (vertex_id, label, json.dumps(props)),
                )
            conn.commit()

    def upsert_edge(self, from_id: str, to_id: str, label: str, props: dict[str, Any]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ikg_edges (from_vertex_id, to_vertex_id, label, properties)
                    values (%s, %s, %s, %s::jsonb)
                    on conflict (from_vertex_id, to_vertex_id, label) do update
                      set properties = ikg_edges.properties || excluded.properties,
                          updated_at = now()
                    """,
                    (from_id, to_id, label, json.dumps(props)),
                )
            conn.commit()

    def query_vertex(self, vertex_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select vertex_id, label, properties from ikg_vertices where vertex_id = %s",
                    (vertex_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {"id": row["vertex_id"], "label": row["label"], **row["properties"]}

    def _normalize_edge_row(self, row: dict[str, Any]) -> dict[str, Any]:
        props = row.get("properties") or {}
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except Exception:
                props = {}
        return {
            "id": row.get("id"),
            "from": row.get("from_vertex_id"),
            "to": row.get("to_vertex_id"),
            "from_vertex_id": row.get("from_vertex_id"),
            "to_vertex_id": row.get("to_vertex_id"),
            "label": row.get("label"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            **(props if isinstance(props, dict) else {}),
        }

    def query_edges_from(self, vertex_id: str, label: str | None = None) -> list[dict[str, Any]]:
        sql = "select * from ikg_edges where from_vertex_id = %s"
        params: list[Any] = [vertex_id]
        if label:
            sql += " and label = %s"
            params.append(label)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [self._normalize_edge_row(dict(r)) for r in cur.fetchall()]

    def query_edges_to(self, vertex_id: str, label: str | None = None) -> list[dict[str, Any]]:
        sql = "select * from ikg_edges where to_vertex_id = %s"
        params: list[Any] = [vertex_id]
        if label:
            sql += " and label = %s"
            params.append(label)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [self._normalize_edge_row(dict(r)) for r in cur.fetchall()]

    def query_by_property(self, label: str, prop: str, value: Any) -> list[dict[str, Any]]:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", prop):
            raise ValueError(f"Unsafe property name: {prop!r}")
        from psycopg import sql as psql
        with self._connect() as conn:
            with conn.cursor() as cur:
                query = psql.SQL(
                    "select vertex_id, label, properties from ikg_vertices "
                    "where label = {label} and properties->>({prop}) = {value}"
                ).format(
                    label=psql.Literal(label),
                    prop=psql.Literal(prop),
                    value=psql.Literal(str(value)),
                )
                cur.execute(query)
                rows = cur.fetchall()
        return [{"id": r["vertex_id"], "label": r["label"], **r["properties"]} for r in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) as n from ikg_vertices")
                v = (cur.fetchone() or {}).get("n", 0)
                cur.execute("select count(*) as n from ikg_edges")
                e = (cur.fetchone() or {}).get("n", 0)
        return {"vertices": int(v), "edges": int(e)}


# ── High-level async graph client ─────────────────────────────────────────────

class IKGClient:
    """Unified async interface to the IKG graph."""

    def __init__(self, backend: Any | None = None) -> None:
        backend_name = _backend_name()
        if backend is not None:
            self._backend = backend
        elif backend_name == "postgres":
            self._backend = PostgresGraphBackend()
        else:
            self._backend = InMemoryGraphBackend()
        logger.info("[IKG] Backend: %s", backend_name)

    async def upsert_vertex(self, vertex_id: str, label: str, props: dict[str, Any]) -> None:
        await asyncio.to_thread(self._backend.upsert_vertex, vertex_id, label, props)

    async def upsert_edge(self, from_id: str, to_id: str, label: str, props: dict[str, Any]) -> None:
        await asyncio.to_thread(self._backend.upsert_edge, from_id, to_id, label, props)

    async def _query_edges_to_any(self, vertex_id: str, labels: list[str]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str, str]] = set()
        merged: list[dict[str, Any]] = []
        for label in labels:
            edges = await asyncio.to_thread(self._backend.query_edges_to, vertex_id, label)
            for edge in edges:
                key = (str(edge.get("from")), str(edge.get("to")), str(edge.get("label")))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(edge)
        return merged

    async def get_company_subgraph(self, cin: str) -> dict[str, Any]:
        """Return full subgraph for a company: directors, promoters, enforcement."""
        vertex = await asyncio.to_thread(self._backend.query_vertex, f"company:{cin}")
        directors = await self._query_edges_to_any(f"company:{cin}", ["DIRECTOR_OF", "SERVES_AS_DIRECTOR"])
        promoters = await asyncio.to_thread(
            self._backend.query_edges_to, f"company:{cin}", "OWNS_STAKE_IN"
        )
        enforcement = await asyncio.to_thread(
            self._backend.query_edges_to, f"company:{cin}", "ENFORCEMENT_ACTION_AGAINST"
        )
        auditor = await asyncio.to_thread(
            self._backend.query_edges_from, f"company:{cin}", "AUDITED_BY"
        )
        return {
            "company": vertex,
            "directors": directors,
            "promoters": promoters,
            "enforcement_actions": enforcement,
            "audit_firm": auditor,
        }

    async def get_director_history(self, cin: str) -> list[dict[str, Any]]:
        """Return all directors (current + past) for a company."""
        return await self._query_edges_to_any(f"company:{cin}", ["DIRECTOR_OF", "SERVES_AS_DIRECTOR"])

    async def get_pledge_risk(self, cin: str) -> dict[str, Any]:
        """Return pledge exposure summary for a company."""
        promoter_edges = await asyncio.to_thread(
            self._backend.query_edges_to, f"company:{cin}", "OWNS_STAKE_IN"
        )
        total_holding = 0.0
        total_pledged = 0.0
        pledged_promoters: list[dict[str, Any]] = []
        for edge in promoter_edges:
            pct = float(edge.get("percentage") or 0)
            pledge_pct = float(edge.get("pledge_pct") or 0)
            total_holding += pct
            if pledge_pct > 0:
                total_pledged += pct * (pledge_pct / 100.0)
                pledged_promoters.append({
                    "promoter": edge.get("from", "").replace("promoter:", ""),
                    "holding_pct": pct,
                    "pledge_pct_of_holding": pledge_pct,
                })
        return {
            "cin": cin,
            "total_promoter_holding_pct": round(total_holding, 2),
            "total_pledge_pct": round(total_pledged, 2),
            "pledged_promoters": pledged_promoters,
            "pledge_flag": "HIGH" if total_pledged > 50 else ("MODERATE" if total_pledged > 25 else "LOW"),
        }

    async def get_enforcement_actions(self, cin: str) -> list[dict[str, Any]]:
        """Return SEBI/RBI enforcement actions against a company."""
        return await asyncio.to_thread(
            self._backend.query_edges_to, f"company:{cin}", "ENFORCEMENT_ACTION_AGAINST"
        )

    async def get_company_financials(self, ticker: str) -> dict[str, Any] | None:
        """Return normalized financial data stored in IKG for a ticker."""
        # Financials are stored as vertex properties on the Company node
        results = await asyncio.to_thread(
            self._backend.query_by_property, "Company", "nse_symbol", ticker
        )
        if not results:
            results = await asyncio.to_thread(
                self._backend.query_by_property, "Company", "bse_scrip_code", ticker
            )
        return results[0] if results else None

    async def get_shared_directors(self, cin1: str, cin2: str) -> list[dict[str, Any]]:
        """Return directors common to two companies (interlocking boards)."""
        dirs1 = {
            e.get("from") for e in await self._query_edges_to_any(
                f"company:{cin1}", ["DIRECTOR_OF", "SERVES_AS_DIRECTOR"]
            )
        }
        dirs2 = {
            e.get("from") for e in await self._query_edges_to_any(
                f"company:{cin2}", ["DIRECTOR_OF", "SERVES_AS_DIRECTOR"]
            )
        }
        common_dins = dirs1 & dirs2
        shared: list[dict[str, Any]] = []
        for din_vertex_id in common_dins:
            vertex = await asyncio.to_thread(self._backend.query_vertex, din_vertex_id)
            if vertex:
                shared.append(vertex)
        return shared

    async def get_promoter_chain(self, cin: str) -> dict[str, Any]:
        """Return the full promoter ownership chain for a company."""
        edges = await asyncio.to_thread(
            self._backend.query_edges_to, f"company:{cin}", "OWNS_STAKE_IN"
        )
        promoters = []
        for edge in edges:
            promoter_id = edge.get("from", "").replace("promoter:", "")
            pledges = await asyncio.to_thread(
                self._backend.query_edges_from, edge.get("from", ""), "PLEDGED_TO"
            )
            promoters.append({
                "promoter_id": promoter_id,
                "holding_pct": edge.get("percentage"),
                "pledge_pct_of_holding": edge.get("pledge_pct"),
                "quarter": edge.get("quarter"),
                "pledges": pledges,
            })
        return {"cin": cin, "promoter_chain": promoters}

    async def stats(self) -> dict[str, int]:
        return await asyncio.to_thread(self._backend.stats)


# ── Module-level singleton ────────────────────────────────────────────────────

_ikg_client: IKGClient | None = None


def get_graph_client() -> IKGClient:
    """Return the module-level IKG client singleton."""
    global _ikg_client
    if _ikg_client is None:
        _ikg_client = IKGClient()
    return _ikg_client


def reset_graph_client() -> None:
    """Reset the singleton (useful for testing)."""
    global _ikg_client
    _ikg_client = None
