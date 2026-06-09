"""Memgraph projection client.

Postgres remains the durable source of truth. Memgraph is a query-serving
projection that can be rebuilt from ``ikg_vertices`` and ``ikg_edges``.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def _safe_cypher_name(value: str, *, fallback: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", str(value or "").strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}"
    return cleaned[:80]


def _json_props(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str):
        try:
            data = json.loads(value)
        except Exception:
            data = {"raw": value}
    else:
        data = {"value": value}

    def _coerce(obj: Any) -> Any:
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (list, tuple)):
            return [_coerce(item) for item in obj]
        if isinstance(obj, dict):
            return {str(key): _coerce(val) for key, val in obj.items()}
        return str(obj)

    return _coerce(data)


class MemgraphClient:
    """Small Bolt/Cypher client compatible with Memgraph."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self.uri = uri or os.getenv("MEMGRAPH_URI", "bolt://localhost:7687")
        self.user = user if user is not None else os.getenv("MEMGRAPH_USER", "")
        self.password = password if password is not None else os.getenv("MEMGRAPH_PASSWORD", "")

    @contextmanager
    def driver(self) -> Iterator[Any]:
        from neo4j import GraphDatabase

        auth = None
        if self.user or self.password:
            auth = (self.user, self.password)
        driver = GraphDatabase.driver(self.uri, auth=auth)
        try:
            yield driver
        finally:
            driver.close()

    def health(self) -> dict[str, Any]:
        with self.driver() as driver:
            with driver.session() as session:
                result = session.run("RETURN 1 AS ok").single()
                node_count = session.run("MATCH (n) RETURN count(n) AS count").single()["count"]
                rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
        return {
            "ok": bool(result and result["ok"] == 1),
            "uri": self.uri,
            "nodes": int(node_count or 0),
            "relationships": int(rel_count or 0),
        }

    def init_schema(self) -> None:
        labels = (
            "Company",
            "Person",
            "PromoterGroup",
            "PromoterEntity",
            "Auditor",
            "Regulator",
            "RegulatorAction",
            "CorporateFiling",
            "CorporateAction",
            "Document",
            "DocumentSection",
            "XBRLFinancialResult",
            "XBRLDisclosure",
            "FinancialData",
            "TextChunk",
            "Entity",
        )
        with self.driver() as driver:
            with driver.session() as session:
                for label in labels:
                    safe = _safe_cypher_name(label, fallback="Entity")
                    try:
                        session.run(f"CREATE INDEX ON :{safe}(vertex_id)")
                    except Exception:
                        pass
                try:
                    session.run("CREATE INDEX ON :Entity(vertex_id)")
                except Exception:
                    pass

    def clear(self) -> None:
        with self.driver() as driver:
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")

    def upsert_nodes(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            label = _safe_cypher_name(str(row.get("label") or "Entity"), fallback="Entity")
            props = _json_props(row.get("properties"))
            props["vertex_id"] = str(row["vertex_id"])
            props["ikg_label"] = str(row.get("label") or label)
            grouped.setdefault(label, []).append(
                {
                    "vertex_id": str(row["vertex_id"]),
                    "props": props,
                }
            )

        written = 0
        with self.driver() as driver:
            with driver.session() as session:
                for label, batch in grouped.items():
                    session.run(
                        f"""
                        UNWIND $rows AS row
                        MERGE (n:{label} {{vertex_id: row.vertex_id}})
                        SET n += row.props
                        WITH n
                        SET n:Entity
                        """,
                        rows=batch,
                    )
                    written += len(batch)
        return written

    def upsert_relationships(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            rel_type = _safe_cypher_name(str(row.get("label") or "RELATED_TO"), fallback="RELATED_TO").upper()
            props = _json_props(row.get("properties"))
            edge_key = str(row.get("id") or f"{row.get('from_vertex_id')}|{row.get('label')}|{row.get('to_vertex_id')}")
            props["edge_key"] = edge_key
            props["ikg_label"] = str(row.get("label") or rel_type)
            grouped.setdefault(rel_type, []).append(
                {
                    "from_vertex_id": str(row["from_vertex_id"]),
                    "to_vertex_id": str(row["to_vertex_id"]),
                    "edge_key": edge_key,
                    "props": props,
                }
            )

        written = 0
        with self.driver() as driver:
            with driver.session() as session:
                for rel_type, batch in grouped.items():
                    session.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (a:Entity {{vertex_id: row.from_vertex_id}})
                        MATCH (b:Entity {{vertex_id: row.to_vertex_id}})
                        MERGE (a)-[r:{rel_type} {{edge_key: row.edge_key}}]->(b)
                        SET r += row.props
                        """,
                        rows=batch,
                    )
                    written += len(batch)
        return written
