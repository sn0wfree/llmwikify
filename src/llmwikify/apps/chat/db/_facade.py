"""ChatDatabase — thin facade over 7 repositories.

After Phase 5 god-class split (2026-06-19), this class delegates every
method to one of 7 repositories. Public API is unchanged.

The 7 repositories live in ``apps.chat.db``:

  1. ChatSessionRepository    — chat_sessions (8 methods)
  2. ChatMessageRepository    — chat_messages (4 methods)
  3. ToolCallRepository       — tool_calls (3 methods)
  4. PermissionRepository     — chat_permissions (2 methods)
  5. ResearchDelegate         — 27 research-domain delegates
  6. WikiDelegate             — 17 wiki-domain delegates
  7. AdminStatsRepository     — cross-table admin/stats (5 methods)

Schema
------

  - ``chat_sessions`` (id, wiki_id, jwt_token, title, created_at, updated_at)
  - ``chat_messages`` (id, session_id, role, content, tool_calls, token/cost
    columns, research_run_id, reverted, created_at)
  - ``tool_calls`` (id, session_id, tool_name, arguments, result, status,
    started_at, finished_at, created_at)
  - ``context_entries`` (id, session_id, entry_type, content, metadata,
    embedding, created_at, updated_at) — owned by MemoryManager, created here
  - ``chat_permissions`` (id, session_id, tool_name, pattern, response, created_at)
  - ``event_log`` (id, session_id, event_type, payload, created_at)

Backward compatibility
----------------------

  - ``AutoResearchDatabase`` is a subclass of ChatDatabase that
    initializes all 3 facades (Chat + Research + Wiki) for tests that
    expect all 11 tables to exist in the shared DB file.
  - ``get_chat_db_path()`` delegates to ``apps.db_base.get_app_db_path()``.

Cross-repo transactions
-----------------------

A few methods touch multiple tables in one transaction. These are
coordinated here (in the facade) rather than inside a single repo:

  - ``delete_chat_session()`` — cascade-delete rows from event_log,
    chat_permissions, chat_messages, tool_calls, context_entries,
    then the session itself.
  - ``revert_to_message()`` — UPDATE chat_messages + DELETE tool_calls
    (wired via ChatMessageRepository's tool_call_delete_after_rowid
    callback into ToolCallRepository.delete_after_rowid).

Design refs
-----------

  - ``docs/designs/v0.33-service-refactor.md`` — 3-facade DB architecture
  - ``docs/designs/v0.32-skill-restructure.md`` — original consolidation
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.db.admin_stats_repo import AdminStatsRepository
from llmwikify.apps.chat.db.base import DB_SIZE_WARNING_MB, get_chat_db_path
from llmwikify.apps.chat.db.chat_message_repo import ChatMessageRepository
from llmwikify.apps.chat.db.chat_session_repo import ChatSessionRepository
from llmwikify.apps.chat.db.permission_repo import PermissionRepository
from llmwikify.apps.chat.db.research_delegate import ResearchDelegate
from llmwikify.apps.chat.db.tool_call_repo import ToolCallRepository
from llmwikify.apps.chat.db.wiki_delegate import WikiDelegate
from llmwikify.apps.db_base import BaseDatabase

logger = logging.getLogger(__name__)


__all__ = [
    "ChatDatabase",
    "AutoResearchDatabase",  # back-compat alias
    "DB_SIZE_WARNING_MB",
    "get_chat_db_path",
    "get_autoresearch_db_path",  # back-compat alias
]


# Backward-compat alias for the path helper
get_autoresearch_db_path = get_chat_db_path


class ChatDatabase(BaseDatabase):
    """Thin facade over the 7 repositories.

    Holds references to each repo and delegates every method.
    Public API matches the pre-split class exactly.
    """

    def __init__(self, data_dir: Path | str):
        """Initialize the chat facade.

        Sets up ``data_dir`` + ``db_path`` manually (rather than
        calling ``super().__init__``) so the 7 repositories can be
        instantiated BEFORE ``_init_db`` runs (which needs the
        repos to create their tables).
        """
        from llmwikify.apps.db_base import get_app_db_path
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = get_app_db_path(self.data_dir)
        self._init_repos()
        self._init_db()
        self._check_db_size()

    # ─── repo lifecycle ─────────────────────────────────────────

    def _init_repos(self) -> None:
        """Instantiate the 7 repositories.

        Each repo holds its own reference to ``self.db_path`` (the
        shared SQLite file). Repos are stateless wrappers around
        that file, so re-creating them on each ChatDatabase init
        is cheap.
        """
        self._sessions = ChatSessionRepository(self.db_path)
        self._messages = ChatMessageRepository(self.db_path)
        self._tools = ToolCallRepository(self.db_path)
        self._perms = PermissionRepository(self.db_path)
        self._research = ResearchDelegate(self.data_dir)
        self._wiki = WikiDelegate(self.data_dir)
        self._admin = AdminStatsRepository(self.db_path)

    def _init_db(self) -> None:
        """Create ChatDatabase's tables (chat domain only).

        Runs each owned repo's ``_init_schema``. Context_entries
        and event_log stay here (created in BaseDatabase's shared
        ``_init_db`` was removed; we keep them in ChatDatabase
        because they were historically created here).

        Phase 6 (2026-06-19): also creates ``memory_consolidations``
        and ``memory_facts`` for the Consolidator + Dream pipeline
        (borrowed from nanobot agent/memory.py architecture).
        """
        # Owned-table repos create their own schemas.
        self._sessions._init_schema()
        self._messages._init_schema()
        self._tools._init_schema()
        self._perms._init_schema()
        # AdminStatsRepository owns no tables; skip.
        # ResearchDelegate + WikiDelegate forward to ResearchDatabase /
        # WikiDatabase which create their own tables lazily on first use.
        # The remaining tables (context_entries, event_log) are
        # still ChatDatabase's responsibility for historical reasons.
        with sqlite3.connect(self.db_path) as conn:
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
            # event_log (v0.41) — created here because no repo owns it
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_log_session
                ON event_log(session_id, created_at)
                """
            )
            # Phase 6 (2026-06-19): memory_consolidations + memory_facts
            # (borrowed from nanobot Consolidator + Dream architecture).
            # See docs/poc/apply-plan.md §6 for full rationale.
            from llmwikify.apps.chat.memory.tables import ALL_PHASE6_DDL
            for ddl in ALL_PHASE6_DDL:
                conn.execute(ddl)
            conn.commit()

    # ─── Chat sessions (8 → ChatSessionRepository) ──────────────

    def create_chat_session(
        self,
        wiki_id: str | None = None,
        jwt_token: str | None = None,
    ) -> str:
        return self._sessions.create_chat_session(wiki_id, jwt_token)

    def get_chat_session(self, session_id: str) -> dict | None:
        return self._sessions.get_chat_session(session_id)

    def update_chat_session_wiki(
        self, session_id: str, wiki_id: str
    ) -> None:
        return self._sessions.update_chat_session_wiki(session_id, wiki_id)

    def update_chat_session_title(
        self, session_id: str, title: str
    ) -> None:
        return self._sessions.update_chat_session_title(session_id, title)

    def update_chat_session_jwt(
        self, session_id: str, jwt_token: str
    ) -> None:
        return self._sessions.update_chat_session_jwt(session_id, jwt_token)

    def list_chat_sessions(self) -> list[dict]:
        return self._sessions.list_chat_sessions()

    def delete_chat_session(self, session_id: str) -> bool:
        """Cascade-delete a session and all related rows.

        Coordinated transaction across event_log, chat_permissions,
        chat_messages, tool_calls, context_entries, then chat_sessions.
        All deletes succeed or all roll back.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "DELETE FROM event_log WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM chat_permissions WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM chat_messages WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM tool_calls WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM context_entries WHERE session_id = ?",
                    (session_id,),
                )
                cursor = conn.execute(
                    "DELETE FROM chat_sessions WHERE id = ?",
                    (session_id,),
                )
                conn.execute("COMMIT")
                return cursor.rowcount > 0
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def get_chat_session_title(self, session_id: str) -> str:
        """Stored title OR fallback to first user message (max 100 chars)."""
        session = self._sessions.get_chat_session(session_id)
        if not session:
            return ""
        stored = session.get("title")
        if stored:
            return stored
        # Fallback: derive from first user message
        messages = self._messages.get_chat_messages(session_id, limit=2)
        for m in messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                return content[:100] if content else ""
        return ""

    # ─── Phase 8: session metadata (goal_state) ─────────────────

    def get_session_metadata(self, session_id: str) -> dict:
        return self._sessions.get_session_metadata(session_id)

    def set_session_metadata(self, session_id: str, metadata: dict) -> None:
        return self._sessions.set_session_metadata(session_id, metadata)

    def update_session_metadata(self, session_id: str, **patch) -> dict:
        return self._sessions.update_session_metadata(session_id, **patch)

    # ─── Chat messages (4 → ChatMessageRepository) ──────────────

    def save_chat_message(self, message: dict) -> None:
        return self._messages.save_chat_message(message)

    def update_chat_message(self, message_id: str, content: str) -> bool:
        return self._messages.update_chat_message(message_id, content)

    def get_chat_messages(
        self,
        session_id: str,
        limit: int = 50,
        before: str | None = None,
        include_reverted: bool = False,
    ) -> list[dict]:
        return self._messages.get_chat_messages(
            session_id, limit, before, include_reverted,
        )

    def revert_to_message(self, session_id: str, message_id: str) -> int:
        """Mark messages after message_id as reverted; delete tool_calls.

        Cross-repo coordination: ChatMessageRepository runs the
        UPDATE, then via the ``tool_call_delete_after_rowid`` callback
        invokes ToolCallRepository.delete_after_rowid — all in one
        transaction.
        """
        return self._messages.revert_to_message(
            session_id, message_id,
            tool_call_delete_after_rowid=self._tools.delete_after_rowid,
        )

    # ─── Tool calls (3 → ToolCallRepository) ────────────────────

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
        status: str = "pending",
        started_at: str | None = None,
    ) -> str:
        return self._tools.log_tool_call(
            session_id, tool_name, arguments, status, started_at,
        )

    def update_tool_call(
        self,
        call_id: str,
        result: Any,
        status: str,
        finished_at: str | None = None,
    ) -> None:
        return self._tools.update_tool_call(
            call_id, result, status, finished_at,
        )

    def get_tool_calls(self, session_id: str) -> list[dict]:
        return self._tools.get_tool_calls(session_id)

    # ─── Permissions (2 → PermissionRepository) ─────────────────

    def save_permission(
        self,
        tool_name: str,
        response: str,
        session_id: str | None = None,
        pattern: str | None = None,
    ) -> str:
        return self._perms.save_permission(
            tool_name, response, session_id, pattern,
        )

    def has_always_permission(
        self, tool_name: str, session_id: str | None = None
    ) -> bool:
        return self._perms.has_always_permission(tool_name, session_id)

    # ─── Research delegates (27 → ResearchDelegate) ─────────────

    def create_research_session(self, wiki_id: str, query: str) -> str:
        return self._research.create_research_session(wiki_id, query)

    def get_research_session(self, session_id: str) -> dict | None:
        return self._research.get_research_session(session_id)

    def list_research_sessions(
        self, wiki_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        return self._research.list_research_sessions(wiki_id, limit)

    def update_research_status(
        self, session_id: str, status: str,
        step: str | None = None, iteration_round: int | None = None,
        synthesis_json: str | None = None,
        review_json: str | None = None,
    ) -> None:
        return self._research.update_research_status(
            session_id, status, step, iteration_round,
            synthesis_json, review_json,
        )

    def update_research_progress(
        self, session_id: str, progress: float,
    ) -> None:
        return self._research.update_research_progress(session_id, progress)

    def persist_report(
        self, session_id: str, result: str | None = None,
    ) -> None:
        return self._research.persist_report(session_id, result)

    def finalize_research(
        self, session_id: str, result: str | None = None,
        wiki_page_name: str | None = None,
    ) -> None:
        return self._research.finalize_research(
            session_id, result, wiki_page_name,
        )

    def delete_research(self, session_id: str) -> bool:
        return self._research.delete_research(session_id)

    def save_sub_query(
        self, session_id: str, query: str, source_type: str,
        url: str | None = None,
    ) -> str:
        return self._research.save_sub_query(
            session_id, query, source_type, url,
        )

    def update_sub_query(
        self, sq_id: str, status: str,
        result: dict | None = None, error: str | None = None,
    ) -> None:
        return self._research.update_sub_query(
            sq_id, status, result, error,
        )

    def get_sub_queries(self, session_id: str) -> list[dict]:
        return self._research.get_sub_queries(session_id)

    def save_source(
        self, session_id: str, sub_query_id: str, source_type: str,
        url: str, title: str, content_length: int,
        content_preview: str | None = None, content: str | None = None,
    ) -> str:
        return self._research.save_source(
            session_id, sub_query_id, source_type, url, title,
            content_length, content_preview, content,
        )

    def update_source_analysis(self, source_id: str, analysis: dict) -> None:
        return self._research.update_source_analysis(source_id, analysis)

    def get_sources(self, session_id: str) -> list[dict]:
        return self._research.get_sources(session_id)

    def rate_source(self, source_id: str, rating: int) -> None:
        return self._research.rate_source(source_id, rating)

    def get_source_count(self, session_id: str) -> int:
        return self._research.get_source_count(session_id)

    def update_six_step_fields(
        self, session_id: str,
        clarification: dict | None = None,
        reasoning: dict | None = None,
        structure: dict | None = None,
        self_loop_counts: dict | None = None,
        self_loop_history: list | None = None,
        evidence_scores: dict | None = None,
    ) -> None:
        return self._research.update_six_step_fields(
            session_id, clarification, reasoning, structure,
            self_loop_counts, self_loop_history, evidence_scores,
        )

    def get_six_step_fields(self, session_id: str) -> dict[str, Any]:
        return self._research.get_six_step_fields(session_id)

    def append_events(self, session_id: str, events: list[dict]) -> int:
        return self._research.append_events(session_id, events)

    def get_events(self, session_id: str) -> list[dict]:
        return self._research.get_events(session_id)

    def save_step(
        self, session_id: str, step_num: int, action: str,
        status: str = "pending", thought: str | None = None,
        result: Any = None, duration_ms: int = 0,
    ) -> None:
        return self._research.save_step(
            session_id, step_num, action, status,
            thought, result, duration_ms,
        )

    def get_step(self, session_id: str, step_num: int) -> dict | None:
        return self._research.get_step(session_id, step_num)

    def list_steps(self, session_id: str) -> list[dict]:
        return self._research.list_steps(session_id)

    def delete_steps(self, session_id: str) -> int:
        return self._research.delete_steps(session_id)

    def update_step_status(
        self, session_id: str, step_num: int, status: str,
    ) -> None:
        return self._research.update_step_status(
            session_id, step_num, status,
        )

    def save_research_state(
        self, session_id: str, step_num: int, state: dict,
    ) -> str:
        return self._research.save_research_state(
            session_id, step_num, state,
        )

    def load_research_state(
        self, session_id: str, step_num: int,
    ) -> dict | None:
        return self._research.load_research_state(session_id, step_num)

    # ─── Wiki delegates (17 → WikiDelegate) ─────────────────────

    def save_dream_proposal(self, proposal: dict) -> None:
        return self._wiki.save_dream_proposal(proposal)

    def get_dream_proposals(
        self,
        wiki_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        return self._wiki.get_dream_proposals(wiki_id, status, limit)

    def update_dream_proposal_status(
        self, proposal_id: str, status: str,
    ) -> None:
        return self._wiki.update_dream_proposal_status(proposal_id, status)

    def get_dream_proposal_stats(self, wiki_id: str) -> dict:
        return self._wiki.get_dream_proposal_stats(wiki_id)

    def save_notification(self, n: dict) -> None:
        return self._wiki.save_notification(n)

    def list_notifications(
        self, wiki_id: str, unread_only: bool = False,
    ) -> list[dict]:
        return self._wiki.list_notifications(wiki_id, unread_only)

    def mark_notification_read(self, notification_id: str) -> None:
        return self._wiki.mark_notification_read(notification_id)

    def get_unread_count(self, wiki_id: str) -> dict:
        return self._wiki.get_unread_count(wiki_id)

    def save_confirmation(self, c: dict) -> None:
        return self._wiki.save_confirmation(c)

    def get_confirmations(
        self, wiki_id: str, status: str | None = None,
    ) -> list[dict]:
        return self._wiki.get_confirmations(wiki_id, status)

    def update_confirmation_status(
        self, confirmation_id: str, status: str,
    ) -> None:
        return self._wiki.update_confirmation_status(
            confirmation_id, status,
        )

    def update_confirmation_arguments(
        self, confirmation_id: str, arguments: dict,
    ) -> None:
        return self._wiki.update_confirmation_arguments(
            confirmation_id, arguments,
        )

    def get_confirmation(self, confirmation_id: str) -> dict | None:
        return self._wiki.get_confirmation(confirmation_id)

    def delete_confirmation(self, confirmation_id: str) -> None:
        return self._wiki.delete_confirmation(confirmation_id)

    def log_ingest(self, entry: dict) -> None:
        return self._wiki.log_ingest(entry)

    def get_ingest_log(
        self, wiki_id: str, limit: int = 20,
    ) -> list[dict]:
        return self._wiki.get_ingest_log(wiki_id, limit)

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        return self._wiki.get_ingest_entry(ingest_id)

    # ─── Admin/stats (5 → AdminStatsRepository) ────────────────

    def get_wiki_stats(self, wiki_id: str) -> dict[str, Any]:
        return self._admin.get_wiki_stats(wiki_id)

    def list_all_wikis(self) -> list[dict[str, str]]:
        return self._admin.list_all_wikis()

    def delete_wiki_data(self, wiki_id: str) -> dict[str, Any]:
        return self._admin.delete_wiki_data(wiki_id)

    def export_wiki_data(self, wiki_id: str) -> dict[str, Any]:
        return self._admin.export_wiki_data(wiki_id)

    def get_db_stats(self) -> dict[str, Any]:
        return self._admin.get_db_stats()


class AutoResearchDatabase(ChatDatabase):
    """Backward-compat: initializes all 3 facades.

    Pre-v0.33.0 code used ``AutoResearchDatabase`` which created
    all 11 tables. This subclass ensures all 3 facades are
    instantiated so all tables exist in the shared DB file.
    """

    def __init__(self, data_dir):
        super().__init__(data_dir)
        from llmwikify.apps.research.db import ResearchDatabase
        from llmwikify.apps.wiki.db import WikiDatabase
        ResearchDatabase(data_dir)
        WikiDatabase(data_dir)
