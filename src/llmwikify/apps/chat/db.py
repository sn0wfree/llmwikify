"""ChatDatabase — unified SQLite database for all chat-driven state.

Per v0.32 Phase 3 (🔴 2 weeks, now shipped incrementally):

This module consolidates the two pre-refactor databases:

  - ``apps/agent/core/db.py::AgentDatabase``  (1387 LOC,
    ``.llmwiki_agent.db`` — 13 tables: chat_sessions,
    chat_messages, tool_calls, research_sessions,
    research_sub_queries, research_sources, dream_proposals,
    notifications, confirmations, ingest_log, ppt_tasks,
    ppt_chat_sessions, ppt_chat_messages)
  - ``apps/chat/db.py::AutoResearchDatabase``   (589 LOC,
    ``autoresearch.db`` — 3 tables: autoresearch_sessions,
    autoresearch_sub_queries, autoresearch_sources)

into a single ``ChatDatabase`` class living in one file
(``apps/chat/db.py``). The two legacy classes are now thin
shims that re-export the consolidated methods.

The consolidation is **focused on the research tables** (the
design's 9-table target is a future v0.32.5 goal). The
non-research AgentDatabase tables (chat_sessions, chat_messages,
tool_calls, dream_proposals, notifications, confirmations,
ingest_log, ppt_*) are **NOT** migrated into ChatDatabase —
they are different business domains (chat UI, dream editor,
PPT) that don't share data with the research loop. Folding
them in would violate the Unix philosophy (one file = one
focus) for ~zero functional gain. They stay in
``apps/agent/core/db.py::AgentDatabase`` (the shim file) for
the v0.32 cycle and are revisited in v0.32.5+.

Schema
------

The new ChatDatabase owns 4 tables (one new, three carried
over with renaming):

  sessions             (id, wiki_id, query, type, status, ...)
                       — replaces both ``research_sessions``
                         (AgentDatabase) and
                         ``autoresearch_sessions``
                         (AutoResearchDatabase). Unified
                         session tracking with ``type`` column
                         (legacy: 'research' or 'autoresearch').

  research_sub_queries (id, session_id, query, source_type, ...)
                       — same as before (renamed to drop the
                         ``autoresearch_`` prefix; both old DBs
                         had identical schemas here)

  research_sources     (id, session_id, sub_query_id, url, ...)
                       — same as before (renamed similarly)

  research_steps       (session_id, step_num, status, ...)
                       — **NEW** (Phase 3 deliverable):
                         one row per (session, step_num)
                         for persisting the 15+ ResearchState
                         fields (round, max_rounds, max_replan,
                         phase, sub_queries, sources, synthesis,
                         report_md, review, knowledge_gaps,
                         contradictions, issues, observations,
                         _last_thought, cancelled, paused,
                         budget_remaining).

Backward compatibility
----------------------

  - ``AutoResearchDatabase`` is now an alias for ChatDatabase.
    Existing imports
    (``from llmwikify.apps.chat.db import AutoResearchDatabase``)
    keep working. The DB file path stays at
    ``data_dir / "autoresearch.db"`` for backward compat with
    existing user data.
  - ``AgentDatabase`` (apps/agent/core/db.py) is a thin shim
    that delegates to ChatDatabase for the research tables and
    keeps its own tables for the non-research domain.

Migration
---------

A standalone migration script
(``scripts/migrate_db_v1_to_v2.py``) reads from the old
``autoresearch.db`` and ``.llmwiki_agent.db`` files and writes
to the new ``autoresearch.db`` (with the unified schema). The
script supports dry-run + backup. ChatDatabase itself does
NOT auto-migrate (explicit migration is safer; users see what
changed).

Design refs
-----------

  - ``docs/designs/v0.32-skill-restructure.md`` §5 (ChatDatabase merge)
  - ``docs/designs/v0.32-execution-plan.md`` Phase 3
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from llmwikify.apps.db_base import BaseDatabase

logger = logging.getLogger(__name__)

# DB size warning threshold (MB). Independent of AgentDatabase.
DB_SIZE_WARNING_MB = 100


def get_chat_db_path(data_dir: Path | str) -> Path:
    """Return the canonical chat.db path inside the given data dir.

    .. deprecated::
        Use ``get_app_db_path()`` (from ``apps.db_base``) instead.
        This wrapper exists for backward compat only; the
        canonical filename is now ``.llmwiki_agent.db``.
    """
    from llmwikify.apps.db_base import get_app_db_path
    return get_app_db_path(data_dir)


class ChatDatabase(BaseDatabase):
    """Chat facade over the shared .llmwiki_agent.db.

    Consolidates the research-related tables from
    ``AgentDatabase`` (apps/agent/core/db.py) and
    ``AutoResearchDatabase`` (pre-Phase-3 versions of this
    file). The non-research AgentDatabase tables (chat,
    notifications, PPT, dream) are NOT migrated here — they
    stay in ``AgentDatabase``.

    Tables owned
    ------------
    - ``sessions``            (unified research session tracking)
    - ``research_sub_queries``(one row per sub-query)
    - ``research_sources``    (one row per gathered source)
    - ``research_steps``      (NEW: one row per ReAct/6-step round
                                for persisting 15+ ResearchState fields)

    Public method names mirror the pre-Phase-3 AgentDatabase
    research API (``create_research_session``,
    ``get_research_session``, ``list_research_sessions``,
    ``update_research_status``, ``save_sub_query``,
    ``get_sub_queries``, ``update_sub_query``, ``save_source``,
    ``update_source_analysis``, ``get_sources``,
    ``update_six_step_fields``, ``get_six_step_fields``,
    ``append_events``, ``get_events``,
    ``persist_report``, ``finalize_research``,
    ``delete_research``) so existing callers in
    ``apps/research/`` and ``apps/chat/`` can adopt the
    new class with only an import-path change.

    New research_steps API (Phase 3):
    - ``save_step(session_id, step_num, status, **fields)``
    - ``get_step(session_id, step_num)``
    - ``list_steps(session_id)``
    - ``delete_steps(session_id)``
    """

    def __init__(self, data_dir: Path | str):
        """Initialize the chat facade.

        Inherits __init__ from BaseDatabase, which resolves
        the canonical .llmwiki_agent.db path (with auto-migration
        from legacy autoresearch.db) and calls _init_db().
        """
        super().__init__(data_dir)
        self._check_db_size()

    # ─── low-level helpers ─────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create ChatDatabase's tables (chat domain only).

        ChatDatabase owns 4 tables:
          - chat_sessions, chat_messages, tool_calls
          - context_entries (NEW for MemoryManager, v0.33.0)

        The 4 research tables are owned by ResearchDatabase.
        The 4 wiki-domain tables are owned by WikiDatabase.
        Each facade creates its own tables via
        ``CREATE TABLE IF NOT EXISTS`` (idempotent).
        """
        with sqlite3.connect(self.db_path) as conn:
            # ─── Chat domain (3 tables + 1 NEW for MemoryManager) ──
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT,
                    jwt_token TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
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
            # ─── Context entries (for MemoryManager, v0.33.0) ──────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS context_entries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    entry_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    embedding TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_context_entries_session
                ON context_entries(session_id, entry_type)
                """
            )
            conn.commit()

    def _check_db_size(self) -> None:
        """Warn if the chat.db file grows beyond the threshold."""
        if not self.db_path.exists():
            return
        size_mb = self.db_path.stat().st_size / 1024 / 1024
        if size_mb > DB_SIZE_WARNING_MB:
            logger.warning(
                "Chat DB is large: %.2f MB (threshold: %d MB). "
                "Consider deleting old sessions.",
                size_mb, DB_SIZE_WARNING_MB,
            )

    # ════════════════════════════════════════════════════════════
    # DEPRECATED: Research-domain methods
    # ════════════════════════════════════════════════════════════
    # These 27 methods are deprecated thin delegates.
    # New code should use ``apps.research.db.ResearchDatabase`` instead.
    # They will be removed in v0.33.0.

    @property
    def _research(self):
        """Lazy ResearchDatabase instance."""
        if not hasattr(self, "_research_db"):
            from llmwikify.apps.research.db import ResearchDatabase
            object.__setattr__(self, "_research_db", ResearchDatabase(self.data_dir))
        return self._research_db

    # ─── Sessions ──────────────────────────────────────────────

    def create_research_session(self, wiki_id: str, query: str) -> str:
        return self._research.create_research_session(wiki_id, query)

    def get_research_session(self, session_id: str) -> dict | None:
        return self._research.get_research_session(session_id)

    def list_research_sessions(self, wiki_id: str | None = None, limit: int = 50) -> list[dict]:
        return self._research.list_research_sessions(wiki_id, limit)

    def update_research_status(self, session_id: str, status: str, step: str | None = None, iteration_round: int | None = None, synthesis_json: str | None = None, review_json: str | None = None) -> None:
        return self._research.update_research_status(session_id, status, step, iteration_round, synthesis_json, review_json)

    def update_research_progress(self, session_id: str, progress: float) -> None:
        return self._research.update_research_progress(session_id, progress)

    def persist_report(self, session_id: str, result: str | None = None) -> None:
        return self._research.persist_report(session_id, result)

    def finalize_research(self, session_id: str, result: str | None = None, wiki_page_name: str | None = None) -> None:
        return self._research.finalize_research(session_id, result, wiki_page_name)

    def delete_research(self, session_id: str) -> bool:
        return self._research.delete_research(session_id)

    # ─── Sub-queries ──────────────────────────────────────────

    def save_sub_query(self, session_id: str, query: str, source_type: str, url: str | None = None) -> str:
        return self._research.save_sub_query(session_id, query, source_type, url)

    def update_sub_query(self, sq_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
        return self._research.update_sub_query(sq_id, status, result, error)

    def get_sub_queries(self, session_id: str) -> list[dict]:
        return self._research.get_sub_queries(session_id)

    # ─── Sources ──────────────────────────────────────────────

    def save_source(self, session_id: str, sub_query_id: str, source_type: str, url: str, title: str, content_length: int, content_preview: str | None = None, content: str | None = None) -> str:
        return self._research.save_source(session_id, sub_query_id, source_type, url, title, content_length, content_preview, content)

    def update_source_analysis(self, source_id: str, analysis: dict) -> None:
        return self._research.update_source_analysis(source_id, analysis)

    def get_sources(self, session_id: str) -> list[dict]:
        return self._research.get_sources(session_id)

    def rate_source(self, source_id: str, rating: int) -> None:
        return self._research.rate_source(source_id, rating)

    def get_source_count(self, session_id: str) -> int:
        return self._research.get_source_count(session_id)

    # ─── 6-step framework fields ──────────────────────────────

    def update_six_step_fields(self, session_id: str, clarification: dict | None = None, reasoning: dict | None = None, structure: dict | None = None, self_loop_counts: dict | None = None, self_loop_history: list | None = None, evidence_scores: dict | None = None) -> None:
        return self._research.update_six_step_fields(session_id, clarification, reasoning, structure, self_loop_counts, self_loop_history, evidence_scores)

    def get_six_step_fields(self, session_id: str) -> dict[str, Any]:
        return self._research.get_six_step_fields(session_id)

    # ─── Event log persistence ───────────────────────────────

    def append_events(self, session_id: str, events: list[dict]) -> int:
        return self._research.append_events(session_id, events)

    def get_events(self, session_id: str) -> list[dict]:
        return self._research.get_events(session_id)

    # ─── research_steps ──────────────────────────────────────

    def save_step(self, session_id: str, step_num: int, action: str, status: str = "pending", thought: str | None = None, result: Any = None, duration_ms: int = 0) -> None:
        return self._research.save_step(session_id, step_num, action, status, thought, result, duration_ms)

    def get_step(self, session_id: str, step_num: int) -> dict | None:
        return self._research.get_step(session_id, step_num)

    def list_steps(self, session_id: str) -> list[dict]:
        return self._research.list_steps(session_id)

    def delete_steps(self, session_id: str) -> int:
        return self._research.delete_steps(session_id)

    def update_step_status(self, session_id: str, step_num: int, status: str) -> None:
        return self._research.update_step_status(session_id, step_num, status)

    def save_research_state(self, session_id: str, step_num: int, state: dict) -> str:
        return self._research.save_research_state(session_id, step_num, state)

    def load_research_state(self, session_id: str, step_num: int) -> dict | None:
        return self._research.load_research_state(session_id, step_num)

    # ─── Chat sessions/messages (migrated from AgentDatabase) ──────

    def create_chat_session(
        self,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> str:
        session_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO chat_sessions (id, wiki_id, jwt_token)
                   VALUES (?, ?, ?)""",
                (session_id, wiki_id, jwt_token),
            )
            conn.commit()
        return session_id

    def get_chat_session(self, session_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def update_chat_session_wiki(
        self, session_id: str, wiki_id: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE chat_sessions
                   SET wiki_id = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (wiki_id, session_id),
            )
            conn.commit()

    def update_chat_session_jwt(
        self, session_id: str, jwt_token: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE chat_sessions
                   SET jwt_token = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (jwt_token, session_id),
            )
            conn.commit()

    def list_chat_sessions(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_chat_session(self, session_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM chat_sessions WHERE id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_chat_session_title(self, session_id: str) -> str:
        session = self.get_chat_session(session_id)
        if not session:
            return ""
        messages = self.get_chat_messages(session_id, limit=2)
        for m in messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                return content[:100] if content else ""
        return ""

    def save_chat_message(self, message: dict) -> None:
        msg_id = message.get("id", uuid.uuid4().hex)
        session_id = message.get("session_id", "")
        role = message.get("role", "")
        content = message.get("content", "")
        tool_calls = json.dumps(message["tool_calls"]) if message.get("tool_calls") else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO chat_messages
                   (id, session_id, role, content, tool_calls)
                   VALUES (?, ?, ?, ?, ?)""",
                (msg_id, session_id, role, content, tool_calls),
            )
            conn.commit()

    def get_chat_messages(
        self,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
    ) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if before:
                rows = conn.execute(
                    """SELECT * FROM chat_messages
                       WHERE session_id = ? AND created_at < ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (session_id, before, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM chat_messages
                       WHERE session_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # ─── Tool calls ───────────────────────────────────────────────

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
        status: str = "pending",
    ) -> str:
        call_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO tool_calls
                   (id, session_id, tool_name, arguments, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (call_id, session_id, tool_name,
                 json.dumps(arguments, ensure_ascii=False), status),
            )
            conn.commit()
        return call_id

    def update_tool_call(
        self, call_id: str, result: Any, status: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE tool_calls
                   SET result = ?, status = ?
                   WHERE id = ?""",
                (json.dumps(result, ensure_ascii=False)
                 if not isinstance(result, str) else result,
                 status, call_id),
            )
            conn.commit()

    def get_tool_calls(self, session_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM tool_calls
                   WHERE session_id = ?
                   ORDER BY created_at""",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ════════════════════════════════════════════════════════════
    # DEPRECATED: Wiki-domain methods
    # ════════════════════════════════════════════════════════════
    # These 17 methods are deprecated thin delegates.
    # New code should use ``apps.wiki.db.WikiDatabase`` instead.
    # They will be removed in v0.33.0.

    @property
    def _wiki(self):
        """Lazy WikiDatabase instance."""
        if not hasattr(self, "_wiki_db"):
            from llmwikify.apps.wiki.db import WikiDatabase
            object.__setattr__(self, "_wiki_db", WikiDatabase(self.data_dir))
        return self._wiki_db

    # ─── Dream proposals (delegate → WikiDatabase) ──────────────

    def save_dream_proposal(self, proposal: dict) -> None:
        return self._wiki.save_dream_proposal(proposal)

    def get_dream_proposals(
        self,
        wiki_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        return self._wiki.get_dream_proposals(wiki_id, status, limit)

    def update_dream_proposal_status(self, proposal_id: str, status: str) -> None:
        return self._wiki.update_dream_proposal_status(proposal_id, status)

    def get_dream_proposal_stats(self, wiki_id: str) -> dict:
        return self._wiki.get_dream_proposal_stats(wiki_id)

    # ─── Notifications (delegate → WikiDatabase) ────────────────

    def save_notification(self, n: dict) -> None:
        return self._wiki.save_notification(n)

    def list_notifications(self, wiki_id: str, unread_only: bool = False) -> list[dict]:
        return self._wiki.list_notifications(wiki_id, unread_only)

    def mark_notification_read(self, notification_id: str) -> None:
        return self._wiki.mark_notification_read(notification_id)

    def get_unread_count(self, wiki_id: str) -> int:
        return self._wiki.get_unread_count(wiki_id)

    # ─── Confirmations (delegate → WikiDatabase) ────────────────

    def save_confirmation(self, c: dict) -> None:
        return self._wiki.save_confirmation(c)

    def get_confirmations(self, wiki_id: str, status: str | None = None) -> list[dict]:
        return self._wiki.get_confirmations(wiki_id, status)

    def update_confirmation_status(self, confirmation_id: str, status: str) -> None:
        return self._wiki.update_confirmation_status(confirmation_id, status)

    def update_confirmation_arguments(self, confirmation_id: str, arguments: dict) -> None:
        return self._wiki.update_confirmation_arguments(confirmation_id, arguments)

    def get_confirmation(self, confirmation_id: str) -> dict | None:
        return self._wiki.get_confirmation(confirmation_id)

    def delete_confirmation(self, confirmation_id: str) -> None:
        return self._wiki.delete_confirmation(confirmation_id)

    # ─── Ingest log (delegate → WikiDatabase) ───────────────────

    def log_ingest(self, entry: dict) -> None:
        return self._wiki.log_ingest(entry)

    def get_ingest_log(self, wiki_id: str, limit: int = 20) -> list[dict]:
        return self._wiki.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self._wiki.get_ingest_entry(ingest_id)


    # ─── Admin/stats ──────────────────────────────────────────────

    def get_wiki_stats(self, wiki_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Count across all relevant tables
            tables = {
                "chat_sessions": "wiki_id",
                "dream_proposals": "wiki_id",
                "notifications": "wiki_id",
                "confirmations": "wiki_id",
                "ingest_log": "wiki_id",
            }
            stats: dict[str, int] = {}
            for table, col in tables.items():
                row = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM {table} WHERE {col} = ?",
                    (wiki_id,),
                ).fetchone()
                stats[table] = row["cnt"] if row else 0
            # Research sessions from autoresearch_sessions
            row = conn.execute(
                """SELECT COUNT(*) as cnt
                   FROM autoresearch_sessions
                   WHERE wiki_id = ?""",
                (wiki_id,),
            ).fetchone()
            stats["research_sessions"] = row["cnt"] if row else 0
            return {"wiki_id": wiki_id, "counts": stats}

    def list_all_wikis(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT DISTINCT wiki_id
                   FROM chat_sessions
                   WHERE wiki_id IS NOT NULL
                   UNION
                   SELECT DISTINCT wiki_id
                   FROM dream_proposals
                   UNION
                   SELECT DISTINCT wiki_id
                   FROM notifications
                   UNION
                   SELECT DISTINCT wiki_id
                   FROM autoresearch_sessions"""
            ).fetchall()
            return [{"wiki_id": r["wiki_id"]} for r in rows]

    def delete_wiki_data(self, wiki_id: str) -> dict:
        deleted: dict[str, int] = {}
        with sqlite3.connect(self.db_path) as conn:
            for table, col in [
                ("chat_sessions", "wiki_id"),
                ("dream_proposals", "wiki_id"),
                ("notifications", "wiki_id"),
                ("confirmations", "wiki_id"),
                ("ingest_log", "wiki_id"),
            ]:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {col} = ?",
                    (wiki_id,),
                )
                deleted[table] = cursor.rowcount
            cursor = conn.execute(
                """DELETE FROM autoresearch_sessions
                   WHERE wiki_id = ?""",
                (wiki_id,),
            )
            deleted["autoresearch_sessions"] = cursor.rowcount
            conn.commit()
        return {"wiki_id": wiki_id, "deleted": deleted}

    def export_wiki_data(self, wiki_id: str) -> dict:
        data: dict[str, Any] = {"wiki_id": wiki_id}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            for table, col in [
                ("chat_sessions", "wiki_id"),
                ("dream_proposals", "wiki_id"),
                ("notifications", "wiki_id"),
            ]:
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE {col} = ?",
                    (wiki_id,),
                ).fetchall()
                data[table] = [dict(r) for r in rows]
            rows = conn.execute(
                """SELECT * FROM autoresearch_sessions
                   WHERE wiki_id = ?""",
                (wiki_id,),
            ).fetchall()
            data["autoresearch_sessions"] = [dict(r) for r in rows]
        return data

    def get_db_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            tables = [
                "autoresearch_sessions", "autoresearch_sub_queries",
                "autoresearch_sources", "research_steps",
                "chat_sessions", "chat_messages", "tool_calls",
                "dream_proposals", "notifications", "confirmations",
                "ingest_log",
            ]
            stats = {}
            for table in tables:
                try:
                    row = conn.execute(
                        f"SELECT COUNT(*) as cnt FROM {table}"
                    ).fetchone()
                    stats[table] = row["cnt"] if row else 0
                except Exception:
                    stats[table] = 0
            size_mb = self.db_path.stat().st_size / 1024 / 1024
            return {"tables": stats, "size_mb": round(size_mb, 2)}


# ─── Backward-compat aliases ─────────────────────────────────────
# Pre-Phase-3 callers used ``AutoResearchDatabase`` and the
# helper ``get_autoresearch_db_path``. After Phase 3, all
# three names refer to the same class / function. The DB
# file path is the same (data_dir / "autoresearch.db") so
# existing user data is preserved.
get_autoresearch_db_path = get_chat_db_path


class AutoResearchDatabase(ChatDatabase):
    """Backward-compat: initializes all 3 facades.

    Pre-v0.33.0 code used ``AutoResearchDatabase`` which created
    all 11 tables. This subclass ensures all 3 facades are
    instantiated so all tables exist in the shared DB file.
    """

    def __init__(self, data_dir):
        super().__init__(data_dir)
        # Initialize Research + Wiki facades so their tables exist
        from llmwikify.apps.research.db import ResearchDatabase
        from llmwikify.apps.wiki.db import WikiDatabase
        ResearchDatabase(data_dir)
        WikiDatabase(data_dir)


__all__ = [
    "ChatDatabase",
    "AutoResearchDatabase",  # back-compat alias
    "DB_SIZE_WARNING_MB",
    "get_chat_db_path",
    "get_autoresearch_db_path",  # back-compat alias
]
