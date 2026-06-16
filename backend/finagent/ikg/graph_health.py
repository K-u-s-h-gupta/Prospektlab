"""IKG Graph Health & Reconciliation — completeness and coverage metrics.

Supports moat Phase 1 ("make the graph trustworthy"): per-company completeness
scoring and corpus-level coverage, so the team can publish "N companies tracked
at evidence-grade depth" and catch silent gaps.

Design:
  - `score_completeness(presence)` is PURE (no DB) → unit-testable.
  - `GraphHealth.report()` runs aggregate counts; `GraphHealth.company(cin)`
    scores one company's edge/fact completeness.
"""

from __future__ import annotations

import logging
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.graph_health")


class GraphHealthError(Exception):
    """Raised when graph-health queries fail due to a DB/infrastructure error."""


# Edge/fact dimensions that define an "evidence-grade" company profile.
_DIMENSIONS = (
    "directors",       # DIRECTOR_OF edges
    "shareholding",    # ownership summary / pledge
    "auditors",        # AUDITED_BY / auditor history
    "financials",      # HAS_FINANCIALS
    "filings",         # corporate filings / documents
    "enforcement",     # enforcement actions (presence is informational, not required)
)

# Dimensions that count toward the completeness denominator (enforcement is
# informational — most clean companies have none).
_REQUIRED = ("directors", "shareholding", "auditors", "financials", "filings")


def score_completeness(presence: dict[str, bool]) -> dict[str, Any]:
    """Score a company's profile completeness from per-dimension presence flags."""
    present = [d for d in _REQUIRED if presence.get(d)]
    score = round(100.0 * len(present) / len(_REQUIRED), 1)
    if score >= 80:
        grade = "evidence_grade"
    elif score >= 50:
        grade = "partial"
    else:
        grade = "thin"
    missing = [d for d in _REQUIRED if not presence.get(d)]
    return {
        "completeness_score": score,
        "grade": grade,
        "present": present,
        "missing": missing,
        "has_enforcement": bool(presence.get("enforcement")),
    }


class GraphHealth:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = get_database_url(database_url)

    def _connect(self) -> Any:
        from psycopg.rows import dict_row
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=5)

    def report(self) -> dict[str, Any]:
        """Corpus-level reconciliation snapshot. Raises GraphHealthError on DB failure."""
        if not self.database_url:
            return {}
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("select count(*) as n from ikg_vertices where label = 'Company'")
                    companies = (cur.fetchone() or {}).get("n", 0)

                    cur.execute(
                        """
                        select count(distinct from_vertex_id) as n
                        from ikg_edges
                        where from_vertex_id like 'company:%' or to_vertex_id like 'company:%'
                        """
                    )
                    companies_with_edges = (cur.fetchone() or {}).get("n", 0)

                    cur.execute("select label, count(*) as n from ikg_edges group by label order by n desc")
                    edges_by_label = {r["label"]: r["n"] for r in cur.fetchall()}

                    cur.execute("select count(*) as n from ikg_facts")
                    facts = (cur.fetchone() or {}).get("n", 0)

                    cur.execute(
                        "select count(*) as n from ikg_facts where source_url is not null and source_url <> ''"
                    )
                    cited_facts = (cur.fetchone() or {}).get("n", 0)
        except Exception as exc:
            raise GraphHealthError(f"Graph health report failed: {exc}") from exc

        return {
            "companies": companies,
            "companies_with_edges": companies_with_edges,
            "edge_coverage_ratio": round(companies_with_edges / companies, 3) if companies else 0.0,
            "edges_by_label": edges_by_label,
            "facts_total": facts,
            "facts_cited": cited_facts,
            "fact_citation_ratio": round(cited_facts / facts, 3) if facts else 0.0,
        }

    def company(self, cin: str) -> dict[str, Any] | None:
        """Per-company completeness. None if the company vertex is absent.
        Raises GraphHealthError on DB failure."""
        cin = (cin or "").upper().strip()
        if not cin or not self.database_url:
            return None
        entity_id = f"company:{cin}"
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("select 1 from ikg_vertices where vertex_id = %s", (entity_id,))
                    if cur.fetchone() is None:
                        return None
                    cur.execute(
                        "select label, count(*) as n from ikg_edges "
                        "where from_vertex_id = %s or to_vertex_id = %s group by label",
                        (entity_id, entity_id),
                    )
                    edge_labels = {r["label"]: r["n"] for r in cur.fetchall()}
                    cur.execute(
                        "select predicate, count(*) as n from ikg_facts "
                        "where subject_entity_id = %s group by predicate",
                        (entity_id,),
                    )
                    fact_preds = {r["predicate"]: r["n"] for r in cur.fetchall()}
        except Exception as exc:
            raise GraphHealthError(f"Company health failed for {cin}: {exc}") from exc

        presence = {
            "directors": edge_labels.get("DIRECTOR_OF", 0) > 0,
            "shareholding": edge_labels.get("OWNS_STAKE_IN", 0) > 0
                or "has_promoter_holding" in fact_preds or "has_pledge" in fact_preds,
            "auditors": edge_labels.get("AUDITED_BY", 0) > 0 or "audited_by" in fact_preds,
            "financials": edge_labels.get("HAS_FINANCIALS", 0) > 0 or "has_financials" in fact_preds,
            "filings": edge_labels.get("HAS_ANNUAL_REPORT", 0) > 0
                or edge_labels.get("HAS_CONCALL_TRANSCRIPT", 0) > 0
                or edge_labels.get("HAS_CORPORATE_ACTION", 0) > 0,
            "enforcement": edge_labels.get("ENFORCEMENT_ACTION_AGAINST", 0) > 0,
        }
        result = score_completeness(presence)
        result["cin"] = cin
        result["edge_labels"] = edge_labels
        return result


_health: GraphHealth | None = None


def get_graph_health() -> GraphHealth:
    global _health
    if _health is None:
        _health = GraphHealth()
    return _health
