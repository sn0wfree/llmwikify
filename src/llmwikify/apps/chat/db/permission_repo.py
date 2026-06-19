"""PermissionRepository — owns the ``chat_permissions`` table.

Schema:
    chat_permissions (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        tool_name TEXT NOT NULL,
        pattern TEXT,
        response TEXT NOT NULL DEFAULT 'once',
        created_at TEXT DEFAULT (datetime('now'))
    )

Methods (2):
    save_permission       — INSERT a permission grant
    has_always_permission — COUNT(*) for tool with response='always'
"""
from __future__ import annotations

import logging
import sqlite3
import uuid

from .base import ChatDBBase

logger = logging.getLogger(__name__)


class PermissionRepository(ChatDBBase):
    """Repository for the ``chat_permissions`` table."""

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_permissions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    tool_name TEXT NOT NULL,
                    pattern TEXT,
                    response TEXT NOT NULL DEFAULT 'once',
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_permissions_tool
                ON chat_permissions(tool_name, response)
                """
            )
            conn.commit()

    def save_permission(
        self,
        tool_name: str,
        response: str,
        session_id: str | None = None,
        pattern: str | None = None,
    ) -> str:
        """Save a permission grant. Returns the permission id."""
        perm_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO chat_permissions
                   (id, session_id, tool_name, pattern, response)
                   VALUES (?, ?, ?, ?, ?)""",
                (perm_id, session_id, tool_name, pattern, response),
            )
            conn.commit()
        return perm_id

    def has_always_permission(
        self, tool_name: str, session_id: str | None = None
    ) -> bool:
        """Check if there's an "always" permission for this tool.

        Matches if the permission is global (session_id IS NULL or
        empty) or bound to the given session.
        """
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM chat_permissions
                   WHERE tool_name = ? AND response = 'always'
                   AND (session_id IS NULL OR session_id = ? OR session_id = '')""",
                (tool_name, session_id),
            ).fetchone()
            return row["cnt"] > 0


__all__ = ["PermissionRepository"]
