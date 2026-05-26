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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
        self._init_tables()

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
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            cur = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_session_title(self, session_id: str) -> str:
        messages = self.get_messages(session_id, limit=1)
        for msg in messages:
            if msg["role"] == "user":
                content = msg["content"][:50]
                return content + ("..." if len(msg["content"]) > 50 else "")
        return "New Chat"

    def save_message(self, message: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO chat_messages (id, session_id, role, content, tool_calls, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                message["id"],
                message["session_id"],
                message["role"],
                message["content"],
                json.dumps(message.get("tool_calls")) if message.get("tool_calls") else None,
                message.get("created_at"),
            ))
            conn.commit()

    def get_messages(self, session_id: str, limit: int = 50, before: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if before:
                rows = conn.execute(
                    "SELECT * FROM chat_messages WHERE session_id = ? AND created_at < ? ORDER BY created_at DESC LIMIT ?",
                    (session_id, before, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("tool_calls"):
                    d["tool_calls"] = json.loads(d["tool_calls"])
                results.append(d)
            return list(reversed(results))

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

    def _init_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                ON chat_messages(session_id, created_at DESC)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dream_proposals (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    page_name TEXT NOT NULL,
                    edit_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reason TEXT,
                    content_length INTEGER,
                    source_entries TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now')),
                    reviewed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dream_proposals_wiki_status
                ON dream_proposals(wiki_id, status)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT,
                    read INTEGER DEFAULT 0,
                    timestamp TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_wiki_read
                ON notifications(wiki_id, read)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS confirmations (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    action_type TEXT,
                    impact TEXT,
                    group_name TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_confirmations_wiki_status
                ON confirmations(wiki_id, status)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ingest_log (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    result_summary TEXT,
                    status TEXT NOT NULL,
                    timestamp TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ingest_log_wiki
                ON ingest_log(wiki_id, timestamp DESC)
            """)
            conn.commit()

    def save_proposal(self, proposal: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO dream_proposals
                (id, wiki_id, page_name, edit_type, content, reason, content_length,
                 source_entries, status, created_at, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                proposal["id"],
                proposal.get("wiki_id"),
                proposal["page_name"],
                proposal["edit_type"],
                proposal["content"],
                proposal.get("reason"),
                proposal.get("content_length"),
                json.dumps(proposal.get("source_entries")),
                proposal["status"],
                proposal.get("created_at"),
                proposal.get("reviewed_at"),
            ))
            conn.commit()

    def get_proposals(self, wiki_id: str, status: str | None = None, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM dream_proposals WHERE wiki_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?",
                    (wiki_id, status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM dream_proposals WHERE wiki_id = ? ORDER BY created_at DESC LIMIT ?",
                    (wiki_id, limit),
                ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("source_entries"):
                    d["source_entries"] = json.loads(d["source_entries"])
                results.append(d)
            return results

    def update_proposal_status(self, proposal_id: str, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE dream_proposals SET status = ?, reviewed_at = datetime('now') WHERE id = ?",
                (status, proposal_id),
            )
            conn.commit()

    def get_proposal_stats(self, wiki_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM dream_proposals WHERE wiki_id = ? GROUP BY status",
                (wiki_id,),
            ).fetchall()
            stats = {"pending": 0, "approved": 0, "rejected": 0, "auto_approved": 0, "applied": 0}
            for row in rows:
                s = row["status"]
                if s in stats:
                    stats[s] = row["count"]
            return stats

    def save_notification(self, n: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO notifications (id, wiki_id, type, message, data, read, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                n["id"],
                n.get("wiki_id"),
                n["type"],
                n["message"],
                json.dumps(n.get("data")) if n.get("data") else None,
                1 if n.get("read") else 0,
                n.get("timestamp"),
            ))
            conn.commit()

    def list_notifications(self, wiki_id: str, unread_only: bool = False) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if unread_only:
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE wiki_id = ? AND read = 0 ORDER BY timestamp DESC",
                    (wiki_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE wiki_id = ? ORDER BY timestamp DESC",
                    (wiki_id,),
                ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["read"] = bool(d["read"])
                if d.get("data"):
                    d["data"] = json.loads(d["data"])
                results.append(d)
            return results

    def mark_notification_read(self, notification_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE notifications SET read = 1 WHERE id = ?",
                (notification_id,),
            )
            conn.commit()

    def get_unread_count(self, wiki_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM notifications WHERE wiki_id = ? AND read = 0",
                (wiki_id,),
            ).fetchone()
            return row["count"] if row else 0

    def save_confirmation(self, c: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO confirmations (id, wiki_id, tool, arguments, action_type, impact, group_name, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                c["id"],
                c.get("wiki_id"),
                c["tool"],
                json.dumps(c["arguments"]),
                c.get("action_type"),
                json.dumps(c["impact"]) if c.get("impact") else None,
                c.get("group"),
                c["status"],
                c.get("created_at"),
            ))
            conn.commit()

    def get_confirmations(self, wiki_id: str, status: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM confirmations WHERE wiki_id = ? AND status = ? ORDER BY created_at DESC",
                    (wiki_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM confirmations WHERE wiki_id = ? ORDER BY created_at DESC",
                    (wiki_id,),
                ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["arguments"] = json.loads(d["arguments"])
                if d.get("impact"):
                    d["impact"] = json.loads(d["impact"])
                results.append(d)
            return results

    def update_confirmation_status(self, confirmation_id: str, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE confirmations SET status = ? WHERE id = ?",
                (status, confirmation_id),
            )
            conn.commit()

    def get_confirmation(self, confirmation_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM confirmations WHERE id = ?",
                (confirmation_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["arguments"] = json.loads(d["arguments"])
            if d.get("impact"):
                d["impact"] = json.loads(d["impact"])
            return d

    def delete_confirmation(self, confirmation_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM confirmations WHERE id = ?", (confirmation_id,))
            conn.commit()

    def log_ingest(self, entry: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO ingest_log (id, wiki_id, tool, arguments, result_summary, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entry["id"],
                entry.get("wiki_id"),
                entry["tool"],
                json.dumps(entry["arguments"]),
                entry.get("result_summary"),
                entry["status"],
                entry.get("timestamp"),
            ))
            conn.commit()

    def get_ingest_log(self, wiki_id: str, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM ingest_log WHERE wiki_id = ? ORDER BY timestamp DESC LIMIT ?",
                (wiki_id, limit),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["arguments"] = json.loads(d["arguments"])
                results.append(d)
            return results

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM ingest_log WHERE id = ?",
                (ingest_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["arguments"] = json.loads(d["arguments"])
            return d