"""Chat memory layer for Finagent.

Stores authenticated user chats in a persistent SQLite database.
Retrieval truncated to stay within a configurable token budget.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from finagent.paths import finagent_data_path
from finagent.storage.sqlite import connect_wal

_DEFAULT_MAX_MESSAGES = 100


class ChatMemoryManager:
    def __init__(self):
        self.db_path = finagent_data_path("chat_memory.db")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return connect_wal(self.db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_user_session
                ON messages(user_email, session_id)
            ''')
            conn.commit()

    def append_message(self, user_email: str | None, session_id: str, role: str, content: str) -> None:
        if not user_email:
            raise ValueError("User email is required. Guest sessions are not supported.")

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (user_email, session_id, role, content)
                VALUES (?, ?, ?, ?)
            ''', (user_email, session_id, role, content))
            conn.commit()

    def get_history(
        self,
        user_email: str | None,
        session_id: str,
        *,
        max_messages: int = _DEFAULT_MAX_MESSAGES,
        max_chars: int = 120_000,
    ) -> list[dict[str, str]]:
        """Retrieve recent chat history for a session, truncated to budget.

        Returns at most ``max_messages`` messages whose combined content
        length stays under ``max_chars`` (~30k tokens at 4 chars/token).
        Keeps the most recent messages when the budget is exceeded.
        """
        if not user_email:
            raise ValueError("User email is required. Guest sessions are not supported.")

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content FROM messages
                WHERE user_email = ? AND session_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            ''', (user_email, session_id, max_messages))
            rows = cursor.fetchall()

        rows.reverse()
        result: list[dict[str, str]] = []
        total_chars = 0
        for role, content in reversed(rows):
            if total_chars + len(content) > max_chars and result:
                break
            total_chars += len(content)
            result.append({"role": role, "content": content})
        result.reverse()
        return result

    def delete_session(self, user_email: str | None, session_id: str) -> int:
        if not user_email:
            raise ValueError("User email is required. Guest sessions are not supported.")

        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                DELETE FROM messages
                WHERE user_email = ? AND session_id = ?
                ''',
                (user_email, session_id),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
