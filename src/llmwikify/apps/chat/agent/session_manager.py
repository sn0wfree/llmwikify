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
abort events are passed
by reference — both sides observe the same state.

Public API mirrors the previous ChatOrchestrator methods 1:1 so
external callers (``chat_sse.py`` HTTP routes) do not need to
status now lives in a store, so it can be bounded or externalised.

change. ChatOrchestrator delegates to the manager.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import MutableMapping
from typing import Any

from llmwikify.apps.chat.agent.state_store import (
    DictSessionStateStore,
    SessionStateStore,
    SessionStateView,
)

logger = logging.getLogger(__name__)


class SessionManager:
    """Lifecycle and bookkeeping for chat sessions."""

    def __init__(
        self,
        db: Any,
        context_manager: Any,
        session_status: Any,
        abort_events: dict[str, asyncio.Event],
        state_store: Any = None,
    ) -> None:
        self._db = db
        self._context_manager = context_manager
        self._abort_events = abort_events
        if state_store is not None:
            self._state_store = state_store
        elif isinstance(session_status, SessionStateStore):
            self._state_store = session_status
        else:
            # A plain dict - keep it as the source of truth.
            self._state_store = DictSessionStateStore(session_status)

    @property
    def _session_status(self) -> MutableMapping[str, str]:
        """A dict-like view over the state store (the legacy surface)."""
        return SessionStateView(self._state_store)

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
        if not self._state_store.get(session_id).busy:
            return False
        event = self._abort_events.get(session_id)
        if event:
            event.set()
            return True
        return False

    def get_session_status(self, session_id: str) -> str:
        """Return ``"busy"`` / ``"idle"`` for ``session_id`` (default idle)."""
        return self._state_store.get(session_id).status

    def get_all_session_status(self) -> dict[str, str]:
        """Snapshot of every tracked session's status."""
        return {
            sid: state.status for sid, state in self._state_store.list_all().items()
        }
