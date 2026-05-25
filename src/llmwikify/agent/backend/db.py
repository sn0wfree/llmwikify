"""Agent Backend - Database management for chat sessions and tool calls."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_agent_db_path(data_dir: Path) -> Path:
    return data_dir / ".llmwiki_agent.db"


class AgentDatabase:
    """SQLite database for chat sessions, tool calls, and research sessions."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT,
                    jwt_token TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    tool_name TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    result TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    progress REAL DEFAULT 0.0,
                    wiki_page_name TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

    def create_session(self, wiki_id: str | None = None, jwt_token: str | None = None) -> str:
        session_id = str(uuid.uuid4())[:8]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO chat_sessions (id, wiki_id, jwt_token) VALUES (?, ?, ?)",
                (session_id, wiki_id, jwt_token),
            )
            conn.commit()
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def update_session_wiki(self, session_id: str, wiki_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE chat_sessions SET wiki_id = ?, updated_at = datetime('now') WHERE id = ?",
                (wiki_id, session_id),
            )
            conn.commit()

    def update_session_jwt(self, session_id: str, jwt_token: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE chat_sessions SET jwt_token = ?, updated_at = datetime('now') WHERE id = ?",
                (jwt_token, session_id),
            )
            conn.commit()

    def list_sessions(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cur.rowcount > 0

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
        status: str = "pending",
    ) -> str:
        call_id = str(uuid.uuid4())[:8]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tool_calls (id, session_id, tool_name, arguments, status) VALUES (?, ?, ?, ?, ?)",
                (call_id, session_id, tool_name, json.dumps(arguments), status),
            )
            conn.commit()
        return call_id

    def update_tool_call(self, call_id: str, result: Any, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE tool_calls SET result = ?, status = ? WHERE id = ?",
                (json.dumps(result), status, call_id),
            )
            conn.commit()

    def get_tool_calls(self, session_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_research_session(self, wiki_id: str, query: str) -> str:
        session_id = str(uuid.uuid4())[:8]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO research_sessions (id, wiki_id, query) VALUES (?, ?, ?)",
                (session_id, wiki_id, query),
            )
            conn.commit()
        return session_id

    def update_research_progress(self, session_id: str, progress: float, wiki_page_name: str | None = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            if wiki_page_name:
                conn.execute(
                    "UPDATE research_sessions SET progress = ?, wiki_page_name = ?, status = 'completed' WHERE id = ?",
                    (progress, wiki_page_name, session_id),
                )
            else:
                conn.execute(
                    "UPDATE research_sessions SET progress = ? WHERE id = ?",
                    (progress, session_id),
                )
            conn.commit()

    def get_research_session(self, session_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM research_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_research_sessions(self, wiki_id: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if wiki_id:
                rows = conn.execute(
                    "SELECT * FROM research_sessions WHERE wiki_id = ? ORDER BY created_at DESC",
                    (wiki_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_sessions ORDER BY created_at DESC"
                ).fetchall()
            return [dict(row) for row in rows]