"""ChatSessionRepository — owns the ``chat_sessions`` table.

Schema:
    chat_sessions (
        id TEXT PRIMARY KEY,
        wiki_id TEXT,
        title TEXT,                 -- v0.40: auto-naming
        metadata TEXT,              -- Phase 8: JSON blob (goal_state, ...)
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )

Methods (9):
    create_chat_session        — INSERT new session, return id
    get_chat_session           — SELECT one by id
    update_chat_session_wiki   — UPDATE wiki_id + updated_at
    update_chat_session_title  — UPDATE title + updated_at (v0.40)
    list_chat_sessions         — SELECT all, ORDER BY created_at DESC
    delete_chat_session        — DELETE one session (cascade via app code)
    get_chat_session_title     — get stored title OR derive from first user msg
    get_session_metadata       — Phase 8: parsed JSON metadata or {}
    set_session_metadata       — Phase 8: write JSON metadata
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any

from .base import ChatDBBase

logger = logging.getLogger(__name__)


class ChatSessionRepository(ChatDBBase):
    """Repository for the ``chat_sessions`` table."""

    def _init_schema(self) -> None:
        with self._mgr.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            # v0.40: title column for session auto-naming
            try:
                conn.execute(
                    "ALTER TABLE chat_sessions ADD COLUMN title TEXT"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            # Phase 8: metadata JSON blob (goal_state, etc.)
            try:
                conn.execute(
                    "ALTER TABLE chat_sessions ADD COLUMN metadata TEXT"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            # Remove jwt_token column if it exists (security fix)
            try:
                conn.execute("ALTER TABLE chat_sessions DROP COLUMN jwt_token")
            except sqlite3.OperationalError:
                pass  # column doesn't exist or can't be dropped
            # Index for ORDER BY created_at DESC (list_chat_sessions)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_created_at
                ON chat_sessions(created_at)
                """
            )
            # Index for wiki_id filtering (admin/CLI queries)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_wiki_id
                ON chat_sessions(wiki_id)
                """
            )

    def create_chat_session(
        self,
        wiki_id: str | None = None,
    ) -> str:
        """Insert a new chat session and return its id."""
        session_id = uuid.uuid4().hex
        self._mgr.execute_write(
            """INSERT INTO chat_sessions (id, wiki_id)
               VALUES (?, ?)""",
            (session_id, wiki_id),
        )
        return session_id

    def get_chat_session(self, session_id: str) -> dict[str, Any] | None:
        """Fetch one session by id, or None if not found."""
        return self._mgr.select_one(
            "SELECT * FROM chat_sessions WHERE id = ?",
            (session_id,),
        )

    def update_chat_session_wiki(
        self, session_id: str, wiki_id: str
    ) -> None:
        """Update a session's wiki binding."""
        self._mgr.execute_write(
            """UPDATE chat_sessions
               SET wiki_id = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (wiki_id, session_id),
        )

    def update_chat_session_title(
        self, session_id: str, title: str
    ) -> None:
        """Update a session's auto-derived title (v0.40)."""
        self._mgr.execute_write(
            """UPDATE chat_sessions
               SET title = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (title, session_id),
        )

    def list_chat_sessions(self) -> list[dict[str, Any]]:
        """List all sessions, newest first."""
        return self._mgr.select_all(
            "SELECT * FROM chat_sessions ORDER BY created_at DESC"
        )

    def delete_chat_session(self, session_id: str) -> bool:
        """Delete one session row. Returns True if a row was removed.

        NOTE: this only deletes the chat_sessions row. The caller
        (ChatDatabase.delete_chat_session) is responsible for
        deleting related rows in event_log, chat_permissions,
        chat_messages, tool_calls, context_entries.
        """
        cursor = self._mgr.execute_write(
            "DELETE FROM chat_sessions WHERE id = ?",
            (session_id,),
        )
        return cursor.rowcount > 0

    def get_chat_session_title(self, session_id: str) -> str:
        """Return the stored title, or fall back to first user message.

        Used by the session list UI to show a human-readable name.
        Falls back to ``get_chat_messages(session_id, limit=2)`` and
        returns the first 100 chars of the first user message.
        """
        session = self.get_chat_session(session_id)
        if not session:
            return ""
        stored = session.get("title")
        if stored:
            return stored
        # Fallback: derive from first user message via the message repo
        # (deferred to ChatDatabase facade to avoid circular import).
        return ""  # facade will derive if needed

    # ─── Phase 8: session metadata (goal_state, ...) ──────────────

    def get_session_metadata(self, session_id: str) -> dict[str, Any]:
        """Return the parsed ``metadata`` JSON blob, or ``{}``.

        Returns an empty dict for missing sessions, ``NULL`` blobs, or
        malformed JSON so callers can ``meta.get(...)`` without
        defensive ``isinstance`` checks.
        """
        session = self.get_chat_session(session_id)
        if not session:
            return {}
        raw = session.get("metadata")
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "chat_sessions.metadata corrupted for %s, treating as empty",
                session_id,
            )
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def set_session_metadata(
        self, session_id: str, metadata: dict[str, Any],
    ) -> None:
        """Replace the ``metadata`` JSON blob for one session.

        Pass an empty dict to clear it (stored as ``NULL`` for cheaper
        reads on the common "no metadata" case).

        Implementation note (Phase 17 real-test fix, 2026-06-21):
        callers like ``GoalSkill`` invoke ``update_session_metadata``
        before any explicit session has been created (e.g. the LLM
        starts a long-task on a session_id it just minted, or a
        future caller writes metadata before the user's first chat
        message). The previous UPDATE-only implementation silently
        dropped those writes. We now use INSERT-OR-IGNORE-then-UPDATE
        so metadata writes never fail on a missing row.
        """
        blob = json.dumps(metadata) if metadata else None
        with self._mgr.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO chat_sessions
                   (id, wiki_id, jwt_token, title, metadata, created_at, updated_at)
                   VALUES (?, '', '', NULL, ?, datetime('now'), datetime('now'))""",
                (session_id, blob),
            )
            conn.execute(
                """UPDATE chat_sessions
                   SET metadata = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (blob, session_id),
            )

    def update_session_metadata(
        self, session_id: str, **patch: Any,
    ) -> dict[str, Any]:
        """Merge ``patch`` into the existing metadata, persist, return new dict.

        Convenience wrapper: callers wanting "set goal_state to this"
        do ``repo.update_session_metadata(sid, goal_state=blob)``
        without an explicit read-merge-write dance.
        """
        meta = self.get_session_metadata(session_id)
        meta.update(patch)
        self.set_session_metadata(session_id, meta)
        return meta


__all__ = ["ChatSessionRepository"]
