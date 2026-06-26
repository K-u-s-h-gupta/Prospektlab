"""Director Network Explorer — graph traversal over the IKG to surface companies
connected to a seed company through shared board members.

Answers: "Which companies share directors with company X, and who are the
connecting directors?" — the institutional due-diligence / AML query.

Design:
  - `assemble_director_network(...)` is a PURE function (no DB) → unit-testable.
  - `DirectorNetworkExplorer.network(cin)` runs a single SQL join over
    ikg_edges (DIRECTOR_OF) and feeds the rows to the pure assembler.

Output is a node/link graph ready for force-directed rendering, with every
link carrying the connecting director (provenance preserved).
"""

from __future__ import annotations

import logging
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.director_network")


class NetworkLookupError(Exception):
    """Raised when network traversal fails due to a DB/infrastructure error."""


def assemble_director_network(
    seed_id: str,
    seed_name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a node/link graph from shared-director rows.

    rows item shape:
      {"person_id","director_name","company_id","company_name","designation"}
    where each row = "director (person_id) of the seed ALSO sits on company_id".
    """
    nodes: dict[str, dict[str, Any]] = {
        seed_id: {"id": seed_id, "label": "Company", "name": seed_name, "is_seed": True, "degree": 0}
    }
    links: list[dict[str, Any]] = []
    # de-dupe links by (person, company)
    seen_links: set[tuple[str, str]] = set()
    company_shared_count: dict[str, int] = {}

    for r in rows:
        person_id = str(r.get("person_id") or "")
        if not person_id:
            continue
        director_name = r.get("director_name") or person_id

        # director node
        if person_id not in nodes:
            nodes[person_id] = {"id": person_id, "label": "Person", "name": director_name, "degree": 0}

        # seed → director link (once)
        seed_key = (seed_id, person_id)
        if seed_key not in seen_links:
            seen_links.add(seed_key)
            links.append({
                "source": person_id,
                "target": seed_id,
                "label": "DIRECTOR_OF",
                "designation": r.get("seed_designation") or "",
            })
            nodes[seed_id]["degree"] += 1
            nodes[person_id]["degree"] += 1

        # connected company (may be absent for board-only rows)
        company_id = str(r.get("company_id") or "")
        if not company_id or company_id == seed_id:
            continue
        company_name = r.get("company_name") or company_id
        if company_id not in nodes:
            nodes[company_id] = {"id": company_id, "label": "Company", "name": company_name, "degree": 0}

        key = (person_id, company_id)
        if key not in seen_links:
            seen_links.add(key)
            links.append({
                "source": person_id,
                "target": company_id,
                "label": "DIRECTOR_OF",
                "designation": r.get("designation") or "",
            })
            nodes[person_id]["degree"] += 1
            nodes[company_id]["degree"] += 1
            company_shared_count[company_id] = company_shared_count.get(company_id, 0) + 1

    connected_companies = sorted(
        (
            {"id": cid, "name": nodes[cid]["name"], "shared_directors": cnt}
            for cid, cnt in company_shared_count.items()
        ),
        key=lambda c: c["shared_directors"],
        reverse=True,
    )

    return {
        "seed": {"id": seed_id, "name": seed_name},
        "nodes": list(nodes.values()),
        "links": links,
        "connected_companies": connected_companies,
        "summary": {
            "directors": sum(1 for n in nodes.values() if n["label"] == "Person"),
            "connected_companies": len(connected_companies),
        },
    }


class DirectorNetworkExplorer:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = get_database_url(database_url)

    def _connect(self) -> Any:
        from psycopg.rows import dict_row
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=5)

    def network(self, cin: str, *, limit: int = 200) -> dict[str, Any] | None:
        """Return the shared-director network for a company CIN.
        None if the company has no director edges. Raises NetworkLookupError on DB failure."""
        cin = (cin or "").upper().strip()
        if not cin or not self.database_url:
            return None
        seed_id = f"company:{cin}"
        try:
            with self._connect() as conn:
                # Use single transaction for consistent snapshot
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            "select properties->>'name' as name from ikg_vertices where vertex_id = %s",
                            (seed_id,),
                        )
                        srow = cur.fetchone()
                        seed_name = (srow or {}).get("name") or cin

                        cur.execute(
                            """
                            select
                              d.from_vertex_id            as person_id,
                              pv.properties->>'name'      as director_name,
                              d.properties->>'designation' as seed_designation,
                              o.to_vertex_id              as company_id,
                              cv.properties->>'name'      as company_name,
                              o.properties->>'designation' as designation
                            from ikg_edges d
                            join ikg_edges o
                              on o.from_vertex_id = d.from_vertex_id
                             and o.label = 'DIRECTOR_OF'
                             and o.to_vertex_id <> d.to_vertex_id
                            left join ikg_vertices pv on pv.vertex_id = d.from_vertex_id
                            left join ikg_vertices cv on cv.vertex_id = o.to_vertex_id
                            where d.to_vertex_id = %s
                              and d.label = 'DIRECTOR_OF'
                            limit %s
                            """,
                            (seed_id, limit),
                        )
                        rows = [dict(r) for r in cur.fetchall()]
                        
                        # Fetch board-only fallback in same transaction
                        if not rows:
                            cur.execute(
                                """
                                select d.from_vertex_id as person_id,
                                       pv.properties->>'name' as director_name,
                                       d.properties->>'designation' as seed_designation
                                from ikg_edges d
                                left join ikg_vertices pv on pv.vertex_id = d.from_vertex_id
                                where d.to_vertex_id = %s and d.label = 'DIRECTOR_OF'
                                limit %s
                                """,
                                (seed_id, limit),
                            )
                            board = [dict(r) for r in cur.fetchall()]
                            if not board:
                                return None
                            # board-only rows
                            board_rows = [
                                {"person_id": b["person_id"], "director_name": b.get("director_name"),
                                 "seed_designation": b.get("seed_designation"), "company_id": "", "company_name": ""}
                                for b in board
                            ]
                            return assemble_director_network(seed_id, seed_name, board_rows)
        except Exception as exc:
            raise NetworkLookupError(f"Director network traversal failed for {cin}: {exc}") from exc

        return assemble_director_network(seed_id, seed_name, rows)


_explorer: DirectorNetworkExplorer | None = None


def get_director_network_explorer() -> DirectorNetworkExplorer:
    global _explorer
    if _explorer is None:
        _explorer = DirectorNetworkExplorer()
    return _explorer
