from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from finagent.paths import finagent_data_path
from finagent.playbooks.schema import FinancialPlaybook
from finagent.storage.sqlite import connect_wal


_SCHEMA = """
CREATE TABLE IF NOT EXISTS playbooks (
    name TEXT PRIMARY KEY,
    geography TEXT NOT NULL,
    intent_key TEXT NOT NULL,
    selected_agents_json TEXT NOT NULL,
    preferred_domains_json TEXT NOT NULL,
    query_templates_json TEXT NOT NULL,
    success_count INTEGER NOT NULL,
    example_target TEXT,
    example_objective TEXT
);
"""


class PlaybookStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else finagent_data_path("playbooks.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect_wal(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    def upsert(self, playbook: FinancialPlaybook) -> None:
        with connect_wal(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO playbooks
                (name, geography, intent_key, selected_agents_json, preferred_domains_json, query_templates_json,
                 success_count, example_target, example_objective)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    playbook.name,
                    playbook.geography,
                    playbook.intent_key,
                    json.dumps(playbook.selected_agents),
                    json.dumps(playbook.preferred_domains),
                    json.dumps(playbook.query_templates),
                    playbook.success_count,
                    playbook.example_target,
                    playbook.example_objective,
                ),
            )

    def retrieve(self, *, geography: str, objective: str) -> FinancialPlaybook | None:
        lower = (objective or "").lower()
        candidates: list[FinancialPlaybook] = []
        with connect_wal(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM playbooks WHERE geography IN (?, 'GLOBAL') ORDER BY success_count DESC LIMIT 20",
                (geography,),
            ).fetchall()
        for row in rows:
            intent_key = row["intent_key"]
            if intent_key and intent_key not in lower:
                continue
            candidates.append(
                FinancialPlaybook(
                    name=row["name"],
                    geography=row["geography"],
                    intent_key=row["intent_key"],
                    selected_agents=json.loads(row["selected_agents_json"] or "[]"),
                    preferred_domains=json.loads(row["preferred_domains_json"] or "[]"),
                    query_templates=json.loads(row["query_templates_json"] or "[]"),
                    success_count=int(row["success_count"] or 1),
                    example_target=row["example_target"] or "",
                    example_objective=row["example_objective"] or "",
                )
            )
        return candidates[0] if candidates else None
