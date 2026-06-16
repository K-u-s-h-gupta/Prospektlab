from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_wal(db_path: str | Path, *, timeout: float = 10.0) -> sqlite3.Connection:
    """Open SQLite with the ProspektLab concurrency pragmas applied."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn
