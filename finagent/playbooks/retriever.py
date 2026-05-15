from __future__ import annotations

from finagent.playbooks.schema import FinancialPlaybook
from finagent.playbooks.store import PlaybookStore


def retrieve_playbook(*, geography: str, objective: str) -> FinancialPlaybook | None:
    store = PlaybookStore()
    return store.retrieve(geography=geography, objective=objective)
