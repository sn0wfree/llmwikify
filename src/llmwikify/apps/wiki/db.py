"""WikiDatabase — wiki-ops domain facade over the shared .llmwiki_agent.db.

Per v0.33-service-refactor.md, this is one of 3 logical
database facades over the same physical SQLite file
(``data_dir/.llmwiki_agent.db``).

Tables owned
------------

  - ``dream_proposals``: Dream editor proposals (id,
    wiki_id, page_name, edit_type, content, status, ...)
  - ``notifications``: in-app notifications (id, wiki_id,
    type, message, read, ...)
  - ``confirmations``: tool-execution confirmations (id,
    wiki_id, tool, arguments, status, ...)
  - ``ingest_log``: posthoc ingest audit trail (id, wiki_id,
    tool, arguments, status, ...)

All methods that were previously in ChatDatabase
("dream_*", "notification_*", "confirmation_*", "ingest_*",
admin/wiki-stats methods) live here. ChatDatabase
delegates to WikiDatabase for backward compat (see
``apps/chat/db.py``).
"""

from __future__ import annotations

import json
import logging
import uuid

from llmwikify.apps.db_base import BaseDatabase

logger = logging.getLogger(__name__)


class WikiDatabase(BaseDatabase):
    """Wiki-ops facade: dream proposals, notifications,
    confirmations, ingest log.

    The 4 tables are created in the shared physical
    .llmwiki_agent.db file (same as ChatDatabase and
    ResearchDatabase). This class only exposes the wiki-ops
    methods; the other 7 tables (chat_sessions/messages/
    tool_calls + autoresearch_*) are accessed via the
    other facades.
    """

    def _init_db(self) -> None:
        """Idempotently create the 4 wiki-ops tables.

        NOTE: this method only creates the 4 tables owned
        by WikiDatabase. The other 8 tables (chat + research)
        are created by their respective facades when they
        construct.
        """
        with self._mgr.transaction() as conn:
            conn.execute(
                """
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
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_dream_proposals_wiki_status
                ON dream_proposals(wiki_id, status)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT,
                    read INTEGER DEFAULT 0,
                    timestamp TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notifications_wiki_read
                ON notifications(wiki_id, read)
                """
            )
            conn.execute(
                """
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
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_confirmations_wiki_status
                ON confirmations(wiki_id, status)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_log (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    result_summary TEXT,
                    status TEXT NOT NULL,
                    timestamp TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingest_log_wiki
                ON ingest_log(wiki_id, timestamp DESC)
                """
            )

    # ─── Dream proposals (4 methods) ───────────────────────────

    def save_dream_proposal(self, proposal: dict) -> None:
        self._mgr.execute_write(
            """INSERT OR REPLACE INTO dream_proposals
               (id, wiki_id, page_name, edit_type, content,
                reason, content_length, source_entries,
                status, reviewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proposal.get("id", uuid.uuid4().hex),
             proposal.get("wiki_id", ""),
             proposal.get("page_name", ""),
             proposal.get("edit_type", ""),
             proposal.get("content", ""),
             proposal.get("reason"),
             proposal.get("content_length"),
             json.dumps(proposal.get("source_entries", []))
             if proposal.get("source_entries") else None,
             proposal.get("status", "pending"),
             proposal.get("reviewed_at")),
        )

    def get_dream_proposals(
        self,
        wiki_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if status:
            return self._mgr.select_all(
                """SELECT * FROM dream_proposals
                   WHERE wiki_id = ? AND status = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (wiki_id, status, limit),
            )
        else:
            return self._mgr.select_all(
                """SELECT * FROM dream_proposals
                   WHERE wiki_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (wiki_id, limit),
            )

    def update_dream_proposal_status(
        self, proposal_id: str, status: str
    ) -> None:
        self._mgr.execute_write(
            """UPDATE dream_proposals
               SET status = ?, reviewed_at = datetime('now')
               WHERE id = ?""",
            (status, proposal_id),
        )

    def get_dream_proposal_stats(self, wiki_id: str) -> dict:
        rows = self._mgr.select_all(
            """SELECT status, COUNT(*) as cnt
               FROM dream_proposals
               WHERE wiki_id = ?
               GROUP BY status""",
            (wiki_id,),
        )
        return {r["status"]: r["cnt"] for r in rows}

    # ─── Notifications (4 methods) ────────────────────────────

    def save_notification(self, n: dict) -> None:
        self._mgr.execute_write(
            """INSERT OR REPLACE INTO notifications
               (id, wiki_id, type, message, data, read, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (n.get("id", uuid.uuid4().hex),
             n.get("wiki_id", ""),
             n.get("type", "info"),
             n.get("message", ""),
             json.dumps(n.get("data", {}), ensure_ascii=False)
             if n.get("data") else None,
             1 if n.get("read") else 0,
             n.get("timestamp")),
        )

    def list_notifications(
        self, wiki_id: str, unread_only: bool = False
    ) -> list[dict]:
        if unread_only:
            return self._mgr.select_all(
                """SELECT * FROM notifications
                   WHERE wiki_id = ? AND read = 0
                   ORDER BY timestamp DESC""",
                (wiki_id,),
            )
        else:
            return self._mgr.select_all(
                """SELECT * FROM notifications
                   WHERE wiki_id = ?
                   ORDER BY timestamp DESC""",
                (wiki_id,),
            )

    def mark_notification_read(self, notification_id: str) -> None:
        self._mgr.execute_write(
            """UPDATE notifications
               SET read = 1
               WHERE id = ?""",
            (notification_id,),
        )

    def get_unread_count(self, wiki_id: str) -> int:
        row = self._mgr.select_one(
            """SELECT COUNT(*) as cnt
               FROM notifications
               WHERE wiki_id = ? AND read = 0""",
            (wiki_id,),
        )
        return row["cnt"] if row else 0

    # ─── Confirmations (6 methods) ────────────────────────────

    def save_confirmation(self, c: dict) -> None:
        self._mgr.execute_write(
            """INSERT OR REPLACE INTO confirmations
               (id, wiki_id, tool, arguments, action_type,
                impact, group_name, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (c.get("id", uuid.uuid4().hex),
             c.get("wiki_id", ""),
             c.get("tool", ""),
             json.dumps(c.get("arguments", {}), ensure_ascii=False),
             c.get("action_type"),
             json.dumps(c.get("impact"), ensure_ascii=False)
             if c.get("impact") else None,
             c.get("group_name"),
             c.get("status", "pending")),
        )

    def get_confirmations(
        self, wiki_id: str, status: str | None = None
    ) -> list[dict]:
        if status:
            return self._mgr.select_all(
                """SELECT * FROM confirmations
                   WHERE wiki_id = ? AND status = ?
                   ORDER BY created_at""",
                (wiki_id, status),
            )
        else:
            return self._mgr.select_all(
                """SELECT * FROM confirmations
                   WHERE wiki_id = ?
                   ORDER BY created_at""",
                (wiki_id,),
            )

    def update_confirmation_status(
        self, confirmation_id: str, status: str
    ) -> None:
        self._mgr.execute_write(
            """UPDATE confirmations
               SET status = ?
               WHERE id = ?""",
            (status, confirmation_id),
        )

    def update_confirmation_arguments(
        self, confirmation_id: str, arguments: dict
    ) -> None:
        self._mgr.execute_write(
            """UPDATE confirmations
               SET arguments = ?
               WHERE id = ?""",
            (json.dumps(arguments, ensure_ascii=False),
             confirmation_id),
        )
    def get_confirmation(
        self,
        confirmation_id: str
    ) -> dict | None:
        return self._mgr.select_one(
            "SELECT * FROM confirmations WHERE id = ?",
            (confirmation_id,),
        )

    def get_confirmation_with_decoded_args(
        self, confirmation_id: str
    ) -> dict | None:
        """Get confirmation with arguments JSON-decoded.

        Returns a new dict with arguments parsed from JSON. Returns None if
        the confirmation doesn't exist. On JSON parse failure, returns the
        raw dict unchanged (arguments remains a string).
        """
        conf = self.get_confirmation(confirmation_id)
        if conf is None:
            return None
        args = conf.get("arguments")
        if isinstance(args, str):
            try:
                return {**conf, "arguments": json.loads(args)}
            except (json.JSONDecodeError, TypeError):
                return conf
        return conf

    def delete_confirmation(self, confirmation_id: str) -> None:
        self._mgr.execute_write(
            "DELETE FROM confirmations WHERE id = ?",
            (confirmation_id,),
        )

    # ─── Ingest log (3 methods) ─────────────────────────────────

    def log_ingest(self, entry: dict) -> None:
        self._mgr.execute_write(
            """INSERT INTO ingest_log
               (id, wiki_id, tool, arguments, result_summary, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entry.get("id", uuid.uuid4().hex),
             entry.get("wiki_id", ""),
             entry.get("tool", ""),
             json.dumps(entry.get("arguments", {}), ensure_ascii=False),
             entry.get("result_summary"),
             entry.get("status", "ok")),
        )

    def get_ingest_log(
        self, wiki_id: str, limit: int = 20
    ) -> list[dict]:
        return self._mgr.select_all(
            """SELECT * FROM ingest_log
               WHERE wiki_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (wiki_id, limit),
        )

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self._mgr.select_one(
            "SELECT * FROM ingest_log WHERE id = ?",
            (ingest_id,),
        )


__all__ = ["WikiDatabase"]
