"""EventLog — lightweight event log for debugging and replay.

Records SSE events to SQLite so they can be retrieved for
debugging, session replay, or audit. Not full event sourcing —
just a log of what happened during a chat session.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from llmwikify.foundation.db import get_connection

logger = logging.getLogger(__name__)


class EventLog:
    """Lightweight event log for chat sessions.

    Writes events to the event_log table. Read via get_events()
    for debugging or replay.
    """

    def __init__(self, db_path: str | Any, *, _mgr=None) -> None:
        """Initialize with a DB path or ChatDatabase instance."""
        if hasattr(db_path, "db_path"):
            self._db_path = str(db_path.db_path)
        else:
            self._db_path = str(db_path)
        self._mgr = _mgr or get_connection(self._db_path)

    def log(self, session_id: str, event: dict) -> None:
        """Write an event to the log. Best-effort — never raises."""
        if not session_id:
            return
        try:
            self._mgr.execute_write(
                """INSERT INTO event_log (session_id, event_type, payload)
                   VALUES (?, ?, ?)""",
                (
                    session_id,
                    event.get("type", "unknown"),
                    json.dumps(event, ensure_ascii=False, default=str),
                ),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("EventLog.log failed: %s", e)

    def get_events(self, session_id: str) -> list[dict]:
        """Retrieve all events for a session, ordered by time."""
        try:
            rows = self._mgr.conn.execute(
                """SELECT event_type, payload, created_at
                   FROM event_log
                   WHERE session_id = ?
                   ORDER BY created_at ASC""",
                (session_id,),
            ).fetchall()
            result = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except (json.JSONDecodeError, TypeError):
                    payload = {"type": row["event_type"], "raw": row["payload"]}
                payload["_created_at"] = row["created_at"]
                result.append(payload)
            return result
        except Exception as e:  # noqa: BLE001
            logger.debug("EventLog.get_events failed: %s", e)
            return []

    def clear(self, session_id: str) -> int:
        """Delete all events for a session. Returns count deleted."""
        try:
            cursor = self._mgr.execute_write(
                "DELETE FROM event_log WHERE session_id = ?",
                (session_id,),
            )
            return cursor.rowcount
        except Exception as e:  # noqa: BLE001
            logger.debug("EventLog.clear failed: %s", e)
            return 0
