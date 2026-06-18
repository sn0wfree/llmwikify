"""SessionManager — extracted from ChatOrchestrator (Phase 5).

Owns session-level operations that touch the database and the
in-memory state tracking dictionary:

  - ``delete_session`` — drop from DB + evict from context cache
  - ``revert_session`` — rewind to a historical message
  - ``edit_message`` — update a stored message in place
  - ``abort_session`` — signal a running session to stop
  - ``get_session_status`` / ``get_all_session_status`` — read state

Dependencies are injected at construction time so the manager is
unit-testable without spinning up a full ChatOrchestrator. The
state dicts (``_session_status``, ``_abort_events``) are passed
by reference — both sides observe the same state.

Public API mirrors the previous ChatOrchestrator methods 1:1 so
external callers (``chat_sse.py`` HTTP routes) do not need to
change. ChatOrchestrator delegates to the manager.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """Lifecycle and bookkeeping for chat sessions."""

    def __init__(
        self,
        db: Any,
        context_manager: Any,
        session_status: dict[str, str],
        abort_events: dict[str, asyncio.Event],
    ) -> None:
        self._db = db
        self._context_manager = context_manager
        self._session_status = session_status
        self._abort_events = abort_events

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from DB and evict its in-memory context."""
        self._context_manager.remove(session_id)
        return self._db.delete_chat_session(session_id)

    def revert_session(self, session_id: str, message_id: str) -> int:
        """Rewind a session to a historical message; returns rows affected."""
        count = self._db.revert_to_message(session_id, message_id)
        self._context_manager.remove(session_id)
        return count

    def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit a stored chat message in place."""
        return self._db.update_chat_message(message_id, new_content)

    def abort_session(self, session_id: str) -> bool:
        """Signal abort for an active session via its asyncio.Event.

        Returns False if the session is not currently busy or has
        no abort event registered.
        """
        if self._session_status.get(session_id) != "busy":
            return False
        event = self._abort_events.get(session_id)
        if event:
            event.set()
            return True
        return False

    def get_session_status(self, session_id: str) -> str:
        """Return ``"busy"`` / ``"idle"`` for ``session_id`` (default idle)."""
        return self._session_status.get(session_id, "idle")

    def get_all_session_status(self) -> dict[str, str]:
        """Snapshot of every tracked session's status."""
        return dict(self._session_status)
