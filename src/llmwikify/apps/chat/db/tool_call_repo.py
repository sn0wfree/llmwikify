"""ToolCallRepository — owns the ``tool_calls`` table.

Schema:
    tool_calls (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        tool_name TEXT NOT NULL,
        arguments TEXT NOT NULL,           -- JSON
        result TEXT,                       -- JSON
        status TEXT NOT NULL DEFAULT 'pending',
        started_at TEXT,                   -- v0.40
        finished_at TEXT,                  -- v0.40
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
    )

Methods (3):
    log_tool_call         — INSERT new call, return id
    update_tool_call      — UPDATE result/status/finished_at
    get_tool_calls        — SELECT all for session, ordered by created_at

Also exposes:
    delete_after_rowid    — DELETE tool_calls with rowid > given value
                            (used by ChatMessageRepository.revert_to_message
                            via the tool_call_delete_after_rowid hook)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any

from .base import ChatDBBase

logger = logging.getLogger(__name__)


class ToolCallRepository(ChatDBBase):
    """Repository for the ``tool_calls`` table."""

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
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
                """
            )
            # v0.40: timing columns
            for col in ("started_at", "finished_at"):
                try:
                    conn.execute(
                        f"ALTER TABLE tool_calls ADD COLUMN {col} TEXT"
                    )
                except sqlite3.OperationalError:
                    pass
            conn.commit()

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
        status: str = "pending",
        started_at: str | None = None,
    ) -> str:
        """Insert a new tool call and return its id."""
        call_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO tool_calls
                   (id, session_id, tool_name, arguments, status, started_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (call_id, session_id, tool_name,
                 json.dumps(arguments, ensure_ascii=False), status, started_at),
            )
            conn.commit()
        return call_id

    def update_tool_call(
        self,
        call_id: str,
        result: Any,
        status: str,
        finished_at: str | None = None,
    ) -> None:
        """Update a tool call's result, status, and finished_at."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE tool_calls
                   SET result = ?, status = ?, finished_at = ?
                   WHERE id = ?""",
                (json.dumps(result, ensure_ascii=False)
                 if not isinstance(result, str) else result,
                 status, finished_at, call_id),
            )
            conn.commit()

    def get_tool_calls(self, session_id: str) -> list[dict[str, Any]]:
        """Fetch all tool calls for a session, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM tool_calls
                   WHERE session_id = ?
                   ORDER BY created_at""",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_after_rowid(
        self, conn: sqlite3.Connection,
        session_id: str, target_rowid: int,
    ) -> int:
        """Delete tool_calls created after a given rowid.

        Used by ChatMessageRepository.revert_to_message via the
        tool_call_delete_after_rowid callback. Runs in the same
        transaction as the message revert.
        """
        cursor = conn.execute(
            """DELETE FROM tool_calls
               WHERE session_id = ? AND rowid > ?""",
            (session_id, target_rowid),
        )
        return cursor.rowcount


__all__ = ["ToolCallRepository"]
