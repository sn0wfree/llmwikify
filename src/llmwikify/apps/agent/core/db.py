"""AgentBackend Database — DEPRECATED wrapper around ChatDatabase.

.. deprecated::
    Use ``llmwikify.apps.chat.db.ChatDatabase`` instead.
    This module is scheduled for removal in v0.33.0.

All methods delegate to ``ChatDatabase``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
import warnings
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Database size warning threshold (MB)
DB_SIZE_WARNING_MB = 100


def get_agent_db_path(data_dir: Path) -> Path:
    return data_dir / ".llmwiki_agent.db"


class AgentDatabase:
    """DEPRECATED: Use ``ChatDatabase`` instead.

    All methods delegate to ``ChatDatabase``.
    Will be removed in v0.33.0.
    """

    def __init__(self, db_path: Path):
        warnings.warn(
            "AgentDatabase is deprecated. Use ChatDatabase instead. "
            "This wrapper will be removed in v0.33.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Import here to avoid circular imports at module level
        from llmwikify.apps.chat.db import ChatDatabase

        self._chat_db = ChatDatabase(db_path.parent)
        # Expose the resolved path (may differ from input db_path
        # when ChatDatabase normalises to .llmwiki_agent.db).
        self.db_path = self._chat_db.db_path

        # PPT tables still live in the agent DB file
        self._init_ppt_tables()

    def _check_db_size(self) -> None:
        """Check database size and log warning if too large."""
        db_path = self._chat_db.db_path
        if not db_path.exists():
            return
        size_mb = db_path.stat().st_size / 1024 / 1024
        logger.debug("Agent DB size: %.2f MB", size_mb)
        if size_mb > DB_SIZE_WARNING_MB:
            logger.warning(
                "Agent DB is large: %.2f MB (threshold: %d MB).",
                size_mb, DB_SIZE_WARNING_MB,
            )

    def _connect(self) -> sqlite3.Connection:
        """Return a connection to the chat DB (autoresearch.db)."""
        conn = sqlite3.connect(self._chat_db.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_ppt_tables(self) -> None:
        """Create backward-compat views for old table names."""
        db_path = self._chat_db.db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """CREATE VIEW IF NOT EXISTS research_sessions AS
                   SELECT * FROM autoresearch_sessions"""
            )
            conn.execute(
                """CREATE VIEW IF NOT EXISTS research_sub_queries AS
                   SELECT * FROM autoresearch_sub_queries"""
            )
            conn.execute(
                """CREATE VIEW IF NOT EXISTS research_sources AS
                   SELECT * FROM autoresearch_sources"""
            )
            conn.commit()

    # ─── Delegated: Chat sessions ─────────────────────────────────

    def create_session(self, wiki_id: str | None = None, jwt_token: str | None = None) -> str:
        return self._chat_db.create_chat_session(wiki_id, jwt_token)

    def get_session(self, session_id: str) -> dict | None:
        return self._chat_db.get_chat_session(session_id)

    def update_session_wiki(self, session_id: str, wiki_id: str) -> None:
        self._chat_db.update_chat_session_wiki(session_id, wiki_id)

    def update_session_jwt(self, session_id: str, jwt_token: str) -> None:
        self._chat_db.update_chat_session_jwt(session_id, jwt_token)

    def list_sessions(self) -> list[dict]:
        return self._chat_db.list_chat_sessions()

    def delete_session(self, session_id: str) -> bool:
        db_path = self._chat_db.db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM tool_calls WHERE session_id = ?", (session_id,))
            cur = conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_session_title(self, session_id: str) -> str:
        return self._chat_db.get_chat_session_title(session_id)

    def save_message(self, message: dict) -> None:
        self._chat_db.save_chat_message(message)

    def get_messages(self, session_id: str, limit: int = 50, before: str | None = None) -> list[dict]:
        return self._chat_db.get_chat_messages(session_id, limit, before)

    # ─── Delegated: Tool calls ────────────────────────────────────

    def log_tool_call(self, session_id: str, tool_name: str, arguments: dict, status: str = "pending") -> str:
        return self._chat_db.log_tool_call(session_id, tool_name, arguments, status)

    def update_tool_call(self, call_id: str, result: Any, status: str) -> None:
        self._chat_db.update_tool_call(call_id, result, status)

    def get_tool_calls(self, session_id: str) -> list[dict]:
        return self._chat_db.get_tool_calls(session_id)

    # ─── Delegated: Dream proposals ───────────────────────────────

    def save_proposal(self, proposal: dict) -> None:
        self._chat_db.save_dream_proposal(proposal)

    def get_proposals(self, wiki_id: str, status: str | None = None, limit: int = 50) -> list[dict]:
        return self._chat_db.get_dream_proposals(wiki_id, status, limit)

    def update_proposal_status(self, proposal_id: str, status: str) -> None:
        self._chat_db.update_dream_proposal_status(proposal_id, status)

    def get_proposal_stats(self, wiki_id: str) -> dict:
        return self._chat_db.get_dream_proposal_stats(wiki_id)

    # ─── Delegated: Notifications ─────────────────────────────────

    def save_notification(self, n: dict) -> None:
        self._chat_db.save_notification(n)

    def list_notifications(self, wiki_id: str, unread_only: bool = False) -> list[dict]:
        return self._chat_db.list_notifications(wiki_id, unread_only)

    def mark_notification_read(self, notification_id: str) -> None:
        self._chat_db.mark_notification_read(notification_id)

    def get_unread_count(self, wiki_id: str) -> int:
        return self._chat_db.get_unread_count(wiki_id)

    # ─── Delegated: Confirmations ─────────────────────────────────

    def save_confirmation(self, c: dict) -> None:
        self._chat_db.save_confirmation(c)

    def get_confirmations(self, wiki_id: str, status: str | None = None) -> list[dict]:
        return self._chat_db.get_confirmations(wiki_id, status)

    def update_confirmation_status(self, confirmation_id: str, status: str) -> None:
        self._chat_db.update_confirmation_status(confirmation_id, status)

    def update_confirmation_arguments(self, confirmation_id: str, arguments: dict) -> None:
        self._chat_db.update_confirmation_arguments(confirmation_id, arguments)

    def get_confirmation(self, confirmation_id: str) -> dict | None:
        return self._chat_db.get_confirmation(confirmation_id)

    def delete_confirmation(self, confirmation_id: str) -> None:
        self._chat_db.delete_confirmation(confirmation_id)

    # ─── Delegated: Ingest log ────────────────────────────────────

    def log_ingest(self, entry: dict) -> None:
        self._chat_db.log_ingest(entry)

    def get_ingest_log(self, wiki_id: str, limit: int = 20) -> list[dict]:
        return self._chat_db.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self._chat_db.get_ingest_entry(ingest_id)

    # ─── Admin/stats (match old AgentDatabase API) ─────────────────

    def get_wiki_stats(self, wiki_id: str) -> dict:
        """Return stats as flat dict matching old AgentDatabase API."""
        db_path = self._chat_db.db_path
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            stats: dict[str, Any] = {"wiki_id": wiki_id}
            for table, col in [
                ("chat_sessions", "wiki_id"),
                ("dream_proposals", "wiki_id"),
                ("notifications", "wiki_id"),
                ("confirmations", "wiki_id"),
                ("ingest_log", "wiki_id"),
            ]:
                row = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {table} WHERE {col} = ?",
                    (wiki_id,),
                ).fetchone()
                stats[table] = row["cnt"] if row else 0
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM autoresearch_sessions WHERE wiki_id = ?",
                (wiki_id,),
            ).fetchone()
            stats["research_sessions"] = row["cnt"] if row else 0
            # Count sources for research sessions
            rsids = [r["id"] for r in conn.execute(
                "SELECT id FROM autoresearch_sessions WHERE wiki_id = ?",
                (wiki_id,),
            ).fetchall()]
            if rsids:
                placeholders = ",".join("?" * len(rsids))
                row = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM autoresearch_sources WHERE session_id IN ({placeholders})",
                    rsids,
                ).fetchone()
                stats["research_sources"] = row["cnt"] if row else 0
            else:
                stats["research_sources"] = 0
        return stats

    def list_all_wikis(self) -> list[dict]:
        """List all wikis with stats, matching old AgentDatabase API."""
        db_path = self._chat_db.db_path
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT DISTINCT wiki_id
                   FROM chat_sessions WHERE wiki_id IS NOT NULL
                   UNION
                   SELECT DISTINCT wiki_id
                   FROM autoresearch_sessions WHERE wiki_id IS NOT NULL"""
            ).fetchall()
            result = []
            for r in rows:
                wid = r["wiki_id"]
                stats = self.get_wiki_stats(wid)
                result.append(stats)
            return sorted(result, key=lambda x: x.get("wiki_id", ""))

    def delete_wiki_data(self, wiki_id: str) -> dict:
        """Delete all data for a wiki. Returns flat count dict."""
        db_path = self._chat_db.db_path
        result: dict[str, int] = {}
        with sqlite3.connect(db_path) as conn:
            # Delete research sources and sub-queries first (cascade)
            rsids = [r[0] for r in conn.execute(
                "SELECT id FROM autoresearch_sessions WHERE wiki_id = ?",
                (wiki_id,),
            ).fetchall()]
            if rsids:
                placeholders = ",".join("?" * len(rsids))
                conn.execute(
                    f"DELETE FROM autoresearch_sources WHERE session_id IN ({placeholders})",
                    rsids,
                )
                conn.execute(
                    f"DELETE FROM autoresearch_sub_queries WHERE session_id IN ({placeholders})",
                    rsids,
                )
                conn.execute(
                    f"DELETE FROM research_steps WHERE session_id IN ({placeholders})",
                    rsids,
                )
            # Delete sessions
            for table, col in [
                ("chat_sessions", "wiki_id"),
                ("dream_proposals", "wiki_id"),
                ("notifications", "wiki_id"),
                ("confirmations", "wiki_id"),
                ("ingest_log", "wiki_id"),
            ]:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {col} = ?", (wiki_id,),
                )
                result[table] = cursor.rowcount
            cursor = conn.execute(
                "DELETE FROM autoresearch_sessions WHERE wiki_id = ?",
                (wiki_id,),
            )
            result["research_sessions"] = cursor.rowcount
            # Cascade: delete messages and tool_calls for deleted sessions
            cursor = conn.execute(
                "DELETE FROM chat_messages WHERE session_id NOT IN "
                "(SELECT id FROM chat_sessions)",
            )
            result["chat_messages"] = cursor.rowcount
            cursor = conn.execute(
                "DELETE FROM tool_calls WHERE session_id NOT IN "
                "(SELECT id FROM chat_sessions)",
            )
            result["tool_calls"] = cursor.rowcount
            conn.commit()
        return result

    def export_wiki_data(self, wiki_id: str) -> dict:
        """Export data matching old AgentDatabase API key structure.

        Queries autoresearch.db (via ChatDatabase) for all tables.
        """
        data: dict[str, Any] = {}
        db_path = self._chat_db.db_path
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            # chat_sessions (exclude jwt_token)
            rows = conn.execute(
                "SELECT id, wiki_id, created_at, updated_at FROM chat_sessions WHERE wiki_id = ?",
                (wiki_id,),
            ).fetchall()
            data["chat_sessions"] = [dict(r) for r in rows]
            # chat_messages (joined via session)
            session_ids = [r["id"] for r in rows]
            if session_ids:
                placeholders = ",".join("?" * len(session_ids))
                rows = conn.execute(
                    f"SELECT * FROM chat_messages WHERE session_id IN ({placeholders})",
                    session_ids,
                ).fetchall()
            else:
                rows = []
            data["chat_messages"] = [dict(r) for r in rows]
            # tool_calls (joined via session)
            if session_ids:
                rows = conn.execute(
                    f"SELECT * FROM tool_calls WHERE session_id IN ({placeholders})",
                    session_ids,
                ).fetchall()
            else:
                rows = []
            data["tool_calls"] = [dict(r) for r in rows]
            # research_sessions
            rows = conn.execute(
                "SELECT * FROM autoresearch_sessions WHERE wiki_id = ?",
                (wiki_id,),
            ).fetchall()
            data["research_sessions"] = [dict(r) for r in rows]
            # research_sub_queries
            rsids = [r["id"] for r in rows]
            if rsids:
                placeholders = ",".join("?" * len(rsids))
                rows = conn.execute(
                    f"SELECT * FROM autoresearch_sub_queries WHERE session_id IN ({placeholders})",
                    rsids,
                ).fetchall()
            else:
                rows = []
            data["research_sub_queries"] = [dict(r) for r in rows]
            # research_sources
            if rsids:
                rows = conn.execute(
                    f"SELECT * FROM autoresearch_sources WHERE session_id IN ({placeholders})",
                    rsids,
                ).fetchall()
            else:
                rows = []
            data["research_sources"] = [dict(r) for r in rows]
        return data

    def get_db_stats(self) -> dict:
        """Return stats matching old AgentDatabase API."""
        db_path = self._chat_db.db_path
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            tables = {}
            for table in [
                "chat_sessions", "chat_messages", "tool_calls",
                "autoresearch_sessions", "autoresearch_sub_queries",
                "autoresearch_sources", "research_steps",
            ]:
                try:
                    row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                    tables[table] = row["cnt"] if row else 0
                except Exception:
                    tables[table] = 0
            # Map to old API key names
            tables["research_sessions"] = tables.pop("autoresearch_sessions", 0)
            tables["research_sources"] = tables.pop("autoresearch_sources", 0)
            tables["research_sub_queries"] = tables.pop("autoresearch_sub_queries", 0)
        size_bytes = db_path.stat().st_size if db_path.exists() else 0
        return {
            "size_bytes": size_bytes,
            "size_mb": size_bytes / 1024 / 1024,
            "tables": tables,
        }

    # ─── Delegated: Research methods ──────────────────────────────

    def create_research_session(self, wiki_id: str, query: str) -> str:
        return self._chat_db.create_research_session(wiki_id, query)

    def get_research_session(self, session_id: str) -> dict | None:
        return self._chat_db.get_research_session(session_id)

    def list_research_sessions(self, wiki_id: str | None = None) -> list[dict]:
        return self._chat_db.list_research_sessions(wiki_id)

    def update_research_status(self, session_id: str, status: str, step: str | None = None, iteration_round: int | None = None, synthesis_json: str | None = None, review_json: str | None = None) -> None:
        self._chat_db.update_research_status(session_id, status, step, iteration_round, synthesis_json, review_json)

    def update_research_progress(self, session_id: str, progress: float, wiki_page_name: str | None = None) -> None:
        self._chat_db.update_research_progress(session_id, progress, wiki_page_name)

    def persist_report(self, session_id: str, result: str | None = None) -> None:
        self._chat_db.persist_report(session_id, result)

    def finalize_research(self, session_id: str, result: str | None = None, wiki_page_name: str | None = None) -> None:
        self._chat_db.finalize_research(session_id, result, wiki_page_name)

    def delete_research(self, session_id: str) -> bool:
        return self._chat_db.delete_research(session_id)

    def save_sub_query(self, session_id: str, query: str, source_type: str, url: str | None = None) -> str:
        return self._chat_db.save_sub_query(session_id, query, source_type, url)

    def get_sub_queries(self, session_id: str) -> list[dict]:
        return self._chat_db.get_sub_queries(session_id)

    def update_sub_query(self, sq_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
        self._chat_db.update_sub_query(sq_id, status, result, error)

    def save_source(self, session_id: str, sub_query_id: str, source_type: str, url: str, title: str, content_length: int, content_preview: str | None = None, content: str | None = None) -> str:
        return self._chat_db.save_source(session_id, sub_query_id, source_type, url, title, content_length, content_preview, content)

    def get_sources(self, session_id: str) -> list[dict]:
        return self._chat_db.get_sources(session_id)

    def update_source_analysis(self, source_id: str, analysis: dict) -> None:
        self._chat_db.update_source_analysis(source_id, analysis)

    def rate_source(self, source_id: str, rating: int) -> None:
        self._chat_db.rate_source(source_id, rating)

    def get_source_count(self, session_id: str) -> int:
        return self._chat_db.get_source_count(session_id)


