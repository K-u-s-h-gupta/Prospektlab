"""SQLite session state (FTS5-ready schema)."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from finagent.paths import finagent_data_path
from finagent.storage.sqlite import connect_wal


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS findings USING fts5(
    session_id UNINDEXED,
    body,
    tokenize='porter'
);
"""


class ResearchStateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = connect_wal(self.db_path)
        conn.executescript(SCHEMA)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def save_checkpoint(self, session_id: str, step: int, payload_json: str) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO checkpoints(session_id, step, payload_json, created_at) VALUES (?,?,?,?)",
                (session_id, step, payload_json, now),
            )
            conn.commit()


def _cli_init() -> None:
    p = argparse.ArgumentParser(description="FinAgent research state DB")
    p.add_argument("--init", action="store_true", help="Create SQLite schema")
    p.add_argument(
        "--db",
        default=str(finagent_data_path("research_state.sqlite3")),
        help="Database file path",
    )
    args = p.parse_args()
    if args.init:
        ResearchStateStore(Path(args.db)).init_db()
        print(f"Initialized {args.db}")
    else:
        p.print_help()


if __name__ == "__main__":
    _cli_init()
