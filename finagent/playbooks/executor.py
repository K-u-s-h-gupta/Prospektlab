from __future__ import annotations

from finagent.playbooks.schema import FinancialPlaybook


def apply_playbook_to_queries(queries: list[str], playbook: FinancialPlaybook | None) -> list[str]:
    if playbook is None:
        return queries
    out = list(queries)
    for q in playbook.query_templates:
        if q not in out:
            out.append(q)
    return out
