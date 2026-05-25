"""Chat memory layer for Finagent.

Stores guest chats in RAM (wiped on restart or refresh due to new session_id).
Stores authenticated user chats in a persistent SQLite database.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from finagent.paths import finagent_data_path
from finagent.storage.sqlite import connect_wal

_RAM_STORE: dict[str, list[dict[str, str]]] = {}
_RAM_LOCK = threading.Lock()

class ChatMemoryManager:
    def __init__(self):
        self.db_path = finagent_data_path("chat_memory.db")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return connect_wal(self.db_path, timeout=10.0)

    def _init_db(self) -> None:
        """Initialize the SQLite database for logged-in users."""
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
            # Index for faster retrieval by session_id and user_email
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_user_session 
                ON messages(user_email, session_id)
            ''')
            conn.commit()

    def append_message(self, user_email: str | None, session_id: str, role: str, content: str) -> None:
        """Append a message to the chat history.
        
        Args:
            user_email: The email of the logged-in user, or None if guest.
            session_id: The active chat session ID.
            role: "user" or "assistant".
            content: The text content of the message.
        """
        if user_email:
            with self._conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO messages (user_email, session_id, role, content)
                    VALUES (?, ?, ?, ?)
                ''', (user_email, session_id, role, content))
                conn.commit()
        else:
            with _RAM_LOCK:
                if session_id not in _RAM_STORE:
                    _RAM_STORE[session_id] = []
                _RAM_STORE[session_id].append({"role": role, "content": content})

    def get_history(self, user_email: str | None, session_id: str) -> list[dict[str, str]]:
        """Retrieve the chat history for a given session.
        
        Returns:
            A list of dicts like [{"role": "user", "content": "..."}]
        """
        if user_email:
            with self._conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT role, content FROM messages
                    WHERE user_email = ? AND session_id = ?
                    ORDER BY timestamp ASC, id ASC
                ''', (user_email, session_id))
                rows = cursor.fetchall()
                return [{"role": row[0], "content": row[1]} for row in rows]
        else:
            with _RAM_LOCK:
                return list(_RAM_STORE.get(session_id, []))

    def delete_session(self, user_email: str | None, session_id: str) -> int:
        """Delete chat history for a session."""
        if user_email:
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
        with _RAM_LOCK:
            prior = len(_RAM_STORE.get(session_id, []))
            _RAM_STORE.pop(session_id, None)
            return prior
