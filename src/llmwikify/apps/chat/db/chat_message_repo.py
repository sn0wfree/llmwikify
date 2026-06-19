"""ChatMessageRepository — owns the ``chat_messages`` table.

Schema:
    chat_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tool_calls TEXT,                  -- JSON
        tokens_input INTEGER DEFAULT 0,   -- v0.40
        tokens_output INTEGER DEFAULT 0,
        tokens_reasoning INTEGER DEFAULT 0,
        tokens_cache_read INTEGER DEFAULT 0,
        tokens_cache_write INTEGER DEFAULT 0,
        cost REAL DEFAULT 0.0,
        research_run_id TEXT,             -- v0.41
        reverted INTEGER DEFAULT 0,       -- v0.40
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
    )

Methods (4):
    save_chat_message          — INSERT OR IGNORE a message
    update_chat_message        — UPDATE content by id
    get_chat_messages          — SELECT with optional before/reverted filter
    revert_to_message          — UPDATE reverted=1 for msgs after target

The revert_to_message method also touches tool_calls (deletes calls
created after the target message's rowid). The tool_calls portion
is exposed via the ``tool_call_delete_after_rowid`` hook which the
ChatDatabase facade calls before invoking the messages update.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any

from .base import ChatDBBase

logger = logging.getLogger(__name__)


class ChatMessageRepository(ChatDBBase):
    """Repository for the ``chat_messages`` table."""

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                ON chat_messages(session_id, created_at DESC)
                """
            )
            # v0.40: reverted column for session revert
            try:
                conn.execute(
                    "ALTER TABLE chat_messages ADD COLUMN reverted INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            # v0.40: token/cost columns
            for col in (
                "tokens_input", "tokens_output", "tokens_reasoning",
                "tokens_cache_read", "tokens_cache_write", "cost",
            ):
                try:
                    default = "0" if col != "cost" else "0.0"
                    conn.execute(
                        f"ALTER TABLE chat_messages ADD COLUMN {col} INTEGER DEFAULT {default}"
                    )
                except sqlite3.OperationalError:
                    pass
            # v0.41: research_run_id column for /study card reload
            try:
                conn.execute(
                    "ALTER TABLE chat_messages ADD COLUMN research_run_id TEXT"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            conn.commit()

    def save_chat_message(self, message: dict[str, Any]) -> None:
        """Insert a message (or ignore if id already exists)."""
        msg_id = message.get("id", uuid.uuid4().hex)
        session_id = message.get("session_id", "")
        role = message.get("role", "")
        content = message.get("content", "")
        tool_calls = (
            json.dumps(message["tool_calls"])
            if message.get("tool_calls")
            else None
        )
        tokens_input = message.get("tokens_input", 0)
        tokens_output = message.get("tokens_output", 0)
        tokens_reasoning = message.get("tokens_reasoning", 0)
        tokens_cache_read = message.get("tokens_cache_read", 0)
        tokens_cache_write = message.get("tokens_cache_write", 0)
        cost = message.get("cost", 0.0)
        research_run_id = message.get("research_run_id")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO chat_messages
                   (id, session_id, role, content, tool_calls,
                    tokens_input, tokens_output, tokens_reasoning,
                    tokens_cache_read, tokens_cache_write, cost,
                    research_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, session_id, role, content, tool_calls,
                 tokens_input, tokens_output, tokens_reasoning,
                 tokens_cache_read, tokens_cache_write, cost,
                 research_run_id),
            )
            conn.commit()

    def update_chat_message(self, message_id: str, content: str) -> bool:
        """Update a message's content in-place. Returns True if updated."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE chat_messages SET content = ? WHERE id = ?",
                (content, message_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_chat_messages(
        self,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        include_reverted: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch messages for a session.

        Args:
            session_id: session to fetch.
            limit: max messages to return.
            before: only return messages with created_at < this value.
            include_reverted: if False, filter out reverted messages.

        Returns messages in chronological (oldest-first) order.
        """
        with self._connect() as conn:
            reverted_clause = "" if include_reverted else " AND reverted = 0"
            if before:
                rows = conn.execute(
                    f"""SELECT * FROM chat_messages
                       WHERE session_id = ? AND created_at < ?{reverted_clause}
                       ORDER BY created_at DESC LIMIT ?""",
                    (session_id, before, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""SELECT * FROM chat_messages
                       WHERE session_id = ?{reverted_clause}
                       ORDER BY created_at DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def revert_to_message(
        self,
        session_id: str,
        message_id: str,
        tool_call_delete_after_rowid: callable = None,
    ) -> int:
        """Mark all messages after ``message_id`` as reverted.

        Uses rowid ordering for reliable comparison even when
        messages share the same created_at timestamp.

        Args:
            session_id: session to revert within.
            message_id: target message id (inclusive).
            tool_call_delete_after_rowid: optional callable that
                takes (conn, session_id, target_rowid) and deletes
                tool_calls created after the target rowid. Wired
                by ChatDatabase facade to coordinate cross-table
                revert in a single transaction.

        Returns the number of messages reverted (0 if target not found).
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT rowid FROM chat_messages WHERE id = ? AND session_id = ?",
                    (message_id, session_id),
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK")
                    return 0
                target_rowid = row[0]
                cursor = conn.execute(
                    """UPDATE chat_messages
                       SET reverted = 1
                       WHERE session_id = ? AND rowid > ? AND reverted = 0""",
                    (session_id, target_rowid),
                )
                if tool_call_delete_after_rowid is not None:
                    tool_call_delete_after_rowid(
                        conn, session_id, target_rowid,
                    )
                conn.execute("COMMIT")
                return cursor.rowcount
            except Exception:
                conn.execute("ROLLBACK")
                raise


__all__ = ["ChatMessageRepository"]
