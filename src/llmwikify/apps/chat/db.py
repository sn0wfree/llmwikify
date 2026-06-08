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


class ChatDatabase:
    """Unified SQLite database for research sessions, sub-queries, sources, and steps.

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
        """Initialize the unified chat/research database.

        Args:
            data_dir: Directory where the SQLite file lives
                      (typically ``~/.llmwikify/agent/``).
        """
        self.data_dir = Path(data_dir)
        self.db_path = get_chat_db_path(self.data_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._check_db_size()

    # ─── low-level helpers ─────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Idempotently create the 4-table schema.

        Uses ``CREATE TABLE IF NOT EXISTS`` so re-instantiation
        is a no-op. Column additions for newer schema versions
        are handled by the migration helpers in
        ``db_migrations.py``.

        Note: the table names below are the SAME as the
        pre-Phase-3 ``AutoResearchDatabase`` (``autoresearch_*``)
        — not renamed — to keep backward compatibility with
        existing user data and the migration helpers in
        ``db_migrations.py``. Phase 3 only **adds** a new
        ``research_steps`` table; it does not rename existing
        ones. (The "9 tables → 1 file" design is about
        consolidating across two files, not about renaming
        tables.)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS autoresearch_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'clarifying',
                    current_step TEXT DEFAULT 'clarifying',
                    progress REAL DEFAULT 0.0,
                    result TEXT,
                    wiki_page_name TEXT,
                    iteration_round INTEGER DEFAULT 0,
                    max_rounds INTEGER DEFAULT 5,
                    max_replan INTEGER DEFAULT 2,
                    quality_score INTEGER DEFAULT 0,
                    synthesis_json TEXT,
                    review_json TEXT,
                    clarification_json TEXT,
                    reasoning_json TEXT,
                    structure_json TEXT,
                    self_loop_counts_json TEXT,
                    self_loop_history_json TEXT,
                    evidence_scores_json TEXT,
                    events_json TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS autoresearch_sub_queries (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    url TEXT,
                    status TEXT DEFAULT 'pending',
                    result TEXT,
                    error TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT,
                    FOREIGN KEY (session_id) REFERENCES autoresearch_sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ar_sub_queries_session
                ON autoresearch_sub_queries(session_id, status)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS autoresearch_sources (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sub_query_id TEXT,
                    source_type TEXT NOT NULL,
                    url TEXT,
                    title TEXT,
                    content_length INTEGER,
                    content_preview TEXT,
                    content TEXT,
                    analysis TEXT,
                    rating INTEGER,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES autoresearch_sessions(id),
                    FOREIGN KEY (sub_query_id) REFERENCES autoresearch_sub_queries(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ar_sources_session
                ON autoresearch_sources(session_id)
                """
            )
            # ── NEW: research_steps table (Phase 3) ──
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS research_steps (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    step_num INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    thought TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (session_id) REFERENCES autoresearch_sessions(id),
                    UNIQUE (session_id, step_num)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_research_steps_session
                ON research_steps(session_id, step_num)
                """
            )
            # ── Chat sessions/messages (migrated from AgentDatabase) ──
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
            # ── Tool calls ──
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
            # ── Dream proposals ──
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
            # ── Notifications ──
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
            # ── Confirmations ──
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
            # ── Ingest log ──
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

    # ─── Session CRUD ─────────────────────────────────────────

    def create_research_session(
        self, wiki_id: str, query: str, *, session_type: str = "research"
    ) -> str:
        """Create a new session row. Returns session id (UUID4 hex).

        ``session_type`` is reserved for future use; the
        table is unified across research/autoresearch in the
        pre-Phase-3 layout. Default status is 'clarifying'
        (the first 6-step stage).
        """
        session_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO autoresearch_sessions
                   (id, wiki_id, query, status, current_step)
                   VALUES (?, ?, ?, 'clarifying', 'clarifying')""",
                (session_id, wiki_id, query),
            )
            conn.commit()
        return session_id

    def get_research_session(self, session_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM autoresearch_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_research_sessions(
        self, wiki_id: str | None = None, session_type: str | None = None
    ) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            sql = """SELECT s.*,
                       (SELECT COUNT(*) FROM autoresearch_sub_queries
                        WHERE session_id = s.id) AS sub_query_count,
                       (SELECT COUNT(*) FROM autoresearch_sources
                        WHERE session_id = s.id) AS source_count
                    FROM autoresearch_sessions s"""
            clauses: list[str] = []
            params: list[Any] = []
            if wiki_id is not None:
                clauses.append("s.wiki_id = ?")
                params.append(wiki_id)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY s.created_at DESC"
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update_research_status(
        self,
        session_id: str,
        status: str,
        step: str | None = None,
        iteration_round: int | None = None,
        synthesis_json: str | None = None,
        review_json: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            sets = ["status = ?", "updated_at = datetime('now')"]
            params: list[Any] = [status]
            if step:
                sets.append("current_step = ?")
                params.append(step)
            if iteration_round is not None:
                sets.append("iteration_round = ?")
                params.append(iteration_round)
            if synthesis_json is not None:
                sets.append("synthesis_json = ?")
                params.append(synthesis_json)
            if review_json is not None:
                sets.append("review_json = ?")
                params.append(review_json)
            params.append(session_id)
            conn.execute(
                f"UPDATE autoresearch_sessions SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()

    def update_research_progress(
        self,
        session_id: str,
        progress: float,
        wiki_page_name: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            if wiki_page_name:
                conn.execute(
                    """UPDATE autoresearch_sessions
                       SET progress = ?, wiki_page_name = ?,
                           updated_at = datetime('now')
                       WHERE id = ?""",
                    (progress, wiki_page_name, session_id),
                )
            else:
                conn.execute(
                    """UPDATE autoresearch_sessions
                       SET progress = ?, updated_at = datetime('now')
                       WHERE id = ?""",
                    (progress, session_id),
                )
            conn.commit()

    def persist_report(
        self, session_id: str, result: str | None = None
    ) -> None:
        """Persist report data without changing status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE autoresearch_sessions
                   SET result = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (result, session_id),
            )
            conn.commit()

    def finalize_research(
        self,
        session_id: str,
        result: str | None = None,
        wiki_page_name: str | None = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE autoresearch_sessions
                   SET status = 'done', result = ?, wiki_page_name = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (result, wiki_page_name, session_id),
            )
            conn.commit()

    def delete_research(self, session_id: str) -> bool:
        """Delete a session and cascade-delete its sub_queries, sources, and steps."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM autoresearch_sources WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "DELETE FROM autoresearch_sub_queries WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "DELETE FROM research_steps WHERE session_id = ?",
                (session_id,),
            )
            cursor = conn.execute(
                "DELETE FROM autoresearch_sessions WHERE id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ─── Sub-queries ──────────────────────────────────────────

    def save_sub_query(
        self,
        session_id: str,
        query: str,
        source_type: str,
        url: str | None = None,
    ) -> str:
        sq_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO autoresearch_sub_queries
                   (id, session_id, query, source_type, url)
                   VALUES (?, ?, ?, ?, ?)""",
                (sq_id, session_id, query, source_type, url),
            )
            conn.commit()
        return sq_id

    def update_sub_query(
        self,
        sq_id: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        result_json = json.dumps(result) if result is not None else None
        with sqlite3.connect(self.db_path) as conn:
            if status == "done":
                conn.execute(
                    """UPDATE autoresearch_sub_queries
                       SET status = ?, result = ?, completed_at = datetime('now')
                       WHERE id = ?""",
                    (status, result_json, sq_id),
                )
            else:
                conn.execute(
                    """UPDATE autoresearch_sub_queries
                       SET status = ?, result = ?, error = ?
                       WHERE id = ?""",
                    (status, result_json, error, sq_id),
                )
            conn.commit()

    def get_sub_queries(self, session_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM autoresearch_sub_queries
                   WHERE session_id = ?
                   ORDER BY created_at ASC""",
                (session_id,),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            if d.get("result"):
                try:
                    d["result"] = json.loads(d["result"])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(d)
        return out

    # ─── Sources ──────────────────────────────────────────────

    def save_source(
        self,
        session_id: str,
        sub_query_id: str,
        source_type: str,
        url: str,
        title: str,
        content_length: int,
        content_preview: str | None = None,
        content: str | None = None,
    ) -> str:
        source_id = uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO autoresearch_sources
                   (id, session_id, sub_query_id, source_type, url, title,
                    content_length, content_preview, content)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_id, session_id, sub_query_id, source_type, url,
                    title, content_length, content_preview, content,
                ),
            )
            conn.commit()
        return source_id

    def update_source_analysis(self, source_id: str, analysis: dict) -> None:
        analysis_json = json.dumps(analysis, ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE autoresearch_sources SET analysis = ? WHERE id = ?",
                (analysis_json, source_id),
            )
            conn.commit()

    def get_sources(self, session_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM autoresearch_sources
                   WHERE session_id = ?
                   ORDER BY created_at ASC""",
                (session_id,),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            if d.get("analysis"):
                try:
                    d["analysis"] = json.loads(d["analysis"])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(d)
        return out

    def rate_source(self, source_id: str, rating: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE autoresearch_sources SET rating = ? WHERE id = ?",
                (rating, source_id),
            )
            conn.commit()

    def get_source_count(self, session_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM autoresearch_sources WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["c"] if row else 0

    # ─── 6-step framework fields ──────────────────────────────

    def update_six_step_fields(
        self,
        session_id: str,
        clarification: dict | None = None,
        reasoning: dict | None = None,
        structure: dict | None = None,
        self_loop_counts: dict | None = None,
        self_loop_history: list | None = None,
        evidence_scores: dict | None = None,
    ) -> None:
        """Update one or more 6-step framework JSON fields.

        Only fields that are not None are written. Existing
        values are overwritten (not merged).
        """
        sets: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if clarification is not None:
            sets.append("clarification_json = ?")
            params.append(json.dumps(clarification, ensure_ascii=False))
        if reasoning is not None:
            sets.append("reasoning_json = ?")
            params.append(json.dumps(reasoning, ensure_ascii=False))
        if structure is not None:
            sets.append("structure_json = ?")
            params.append(json.dumps(structure, ensure_ascii=False))
        if self_loop_counts is not None:
            sets.append("self_loop_counts_json = ?")
            params.append(json.dumps(self_loop_counts, ensure_ascii=False))
        if self_loop_history is not None:
            sets.append("self_loop_history_json = ?")
            params.append(json.dumps(self_loop_history, ensure_ascii=False))
        if evidence_scores is not None:
            sets.append("evidence_scores_json = ?")
            params.append(json.dumps(evidence_scores, ensure_ascii=False))
        params.append(session_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE autoresearch_sessions SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()

    def get_six_step_fields(self, session_id: str) -> dict[str, Any]:
        """Return all 6 JSON framework fields for a session, parsed.

        Missing fields are returned as None.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT clarification_json, reasoning_json, structure_json,
                          self_loop_counts_json, self_loop_history_json,
                          evidence_scores_json
                   FROM autoresearch_sessions WHERE id = ?""",
                (session_id,),
            ).fetchone()
        if not row:
            return {
                "clarification": None,
                "reasoning": None,
                "structure": None,
                "self_loop_counts": None,
                "self_loop_history": None,
                "evidence_scores": None,
            }

        def _maybe_load(raw: str | None) -> Any:
            if not raw:
                return None
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return None

        return {
            "clarification": _maybe_load(row["clarification_json"]),
            "reasoning": _maybe_load(row["reasoning_json"]),
            "structure": _maybe_load(row["structure_json"]),
            "self_loop_counts": _maybe_load(row["self_loop_counts_json"]),
            "self_loop_history": _maybe_load(row["self_loop_history_json"]),
            "evidence_scores": _maybe_load(row["evidence_scores_json"]),
        }

    # ─── Event log persistence ───────────────────────────────

    def append_events(self, session_id: str, events: list[dict]) -> int:
        """Append a batch of events to the session's persisted event log."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT events_json FROM autoresearch_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            existing: list[dict] = []
            if row and row["events_json"]:
                try:
                    parsed = json.loads(row["events_json"])
                    if isinstance(parsed, list):
                        existing = parsed
                except (json.JSONDecodeError, TypeError):
                    existing = []
            existing.extend(events)
            new_json = json.dumps(existing, ensure_ascii=False)
            conn.execute(
                """UPDATE autoresearch_sessions
                   SET events_json = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (new_json, session_id),
            )
            conn.commit()
            return len(existing)

    def get_events(self, session_id: str) -> list[dict]:
        """Return all persisted events for a session, in insertion order."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT events_json FROM autoresearch_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if not row or not row["events_json"]:
            return []
        try:
            parsed = json.loads(row["events_json"])
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    # ─── research_steps (Phase 3 NEW) ────────────────────────

    def save_step(
        self,
        session_id: str,
        step_num: int,
        action: str,
        status: str = "pending",
        thought: str | None = None,
        result: dict | None = None,
        duration_ms: int = 0,
    ) -> str:
        """Persist one research step (one row per ReAct round).

        This is the new home for the 15+ ResearchState fields
        (round, max_rounds, max_replan, phase, sub_queries,
        sources, synthesis, report_md, review, knowledge_gaps,
        contradictions, issues, observations, _last_thought,
        cancelled, paused, budget_remaining) that the
        pre-Phase-3 ReAct loop held in memory.

        One row per ``(session_id, step_num)``. The full
        ResearchState dict is serialized into ``result_json``;
        only the most-frequently-queried fields (action,
        status, thought, duration) get dedicated columns for
        fast filtering.

        Returns:
            The new step's id (UUID4 hex).
        """
        step_id = uuid.uuid4().hex
        result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO research_steps
                   (id, session_id, step_num, action, thought, status,
                    result_json, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    step_id, session_id, step_num, action, thought, status,
                    result_json, duration_ms,
                ),
            )
            conn.commit()
        return step_id

    def get_step(self, session_id: str, step_num: int) -> dict | None:
        """Return a single step by (session_id, step_num)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM research_steps
                   WHERE session_id = ? AND step_num = ?""",
                (session_id, step_num),
            ).fetchone()
        if not row:
            return None
        return _row_to_step_dict(row)

    def list_steps(self, session_id: str) -> list[dict]:
        """Return all steps for a session, ordered by step_num."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM research_steps
                   WHERE session_id = ?
                   ORDER BY step_num ASC""",
                (session_id,),
            ).fetchall()
        return [_row_to_step_dict(r) for r in rows]

    def delete_steps(self, session_id: str) -> int:
        """Delete all steps for a session. Returns count deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM research_steps WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cur.rowcount

    def update_step_status(
        self, session_id: str, step_num: int, status: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE research_steps
                   SET status = ?
                   WHERE session_id = ? AND step_num = ?""",
                (status, session_id, step_num),
            )
            conn.commit()

    def save_research_state(
        self,
        session_id: str,
        step_num: int,
        state: dict,
    ) -> str:
        """Persist a full ResearchState dict as a step's result.

        Convenience wrapper for the common case of "save my
        whole ReAct state after this round". The state dict is
        stored verbatim in ``result_json`` and the step's
        ``action`` is set to the value of ``state.phase`` (if
        present) so list_steps() can group by phase.
        """
        action = state.get("phase", "unknown")
        return self.save_step(
            session_id=session_id,
            step_num=step_num,
            action=action,
            status="done",
            result=state,
        )

    def load_research_state(
        self, session_id: str, step_num: int
    ) -> dict | None:
        """Load a previously saved ResearchState dict by step_num."""
        step = self.get_step(session_id, step_num)
        if not step:
            return None
        return step.get("result")

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

    # ─── Dream proposals ──────────────────────────────────────────

    def save_dream_proposal(self, proposal: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
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
            conn.commit()

    def get_dream_proposals(
        self,
        wiki_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    """SELECT * FROM dream_proposals
                       WHERE wiki_id = ? AND status = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (wiki_id, status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM dream_proposals
                       WHERE wiki_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (wiki_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def update_dream_proposal_status(
        self, proposal_id: str, status: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE dream_proposals
                   SET status = ?, reviewed_at = datetime('now')
                   WHERE id = ?""",
                (status, proposal_id),
            )
            conn.commit()

    def get_dream_proposal_stats(self, wiki_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT status, COUNT(*) as cnt
                   FROM dream_proposals
                   WHERE wiki_id = ?
                   GROUP BY status""",
                (wiki_id,),
            ).fetchall()
            return {r["status"]: r["cnt"] for r in rows}

    # ─── Notifications ────────────────────────────────────────────

    def save_notification(self, n: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
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
            conn.commit()

    def list_notifications(
        self, wiki_id: str, unread_only: bool = False
    ) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if unread_only:
                rows = conn.execute(
                    """SELECT * FROM notifications
                       WHERE wiki_id = ? AND read = 0
                       ORDER BY timestamp DESC""",
                    (wiki_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM notifications
                       WHERE wiki_id = ?
                       ORDER BY timestamp DESC""",
                    (wiki_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def mark_notification_read(self, notification_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE notifications
                   SET read = 1
                   WHERE id = ?""",
                (notification_id,),
            )
            conn.commit()

    def get_unread_count(self, wiki_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT COUNT(*) as cnt
                   FROM notifications
                   WHERE wiki_id = ? AND read = 0""",
                (wiki_id,),
            ).fetchone()
            return row[0] if row else 0

    # ─── Confirmations ────────────────────────────────────────────

    def save_confirmation(self, c: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
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
            conn.commit()

    def get_confirmations(
        self, wiki_id: str, status: str | None = None
    ) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    """SELECT * FROM confirmations
                       WHERE wiki_id = ? AND status = ?
                       ORDER BY created_at""",
                    (wiki_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM confirmations
                       WHERE wiki_id = ?
                       ORDER BY created_at""",
                    (wiki_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def update_confirmation_status(
        self, confirmation_id: str, status: str
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE confirmations
                   SET status = ?
                   WHERE id = ?""",
                (status, confirmation_id),
            )
            conn.commit()

    def update_confirmation_arguments(
        self, confirmation_id: str, arguments: dict
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE confirmations
                   SET arguments = ?
                   WHERE id = ?""",
                (json.dumps(arguments, ensure_ascii=False),
                 confirmation_id),
            )
            conn.commit()

    def get_confirmation(
        self, confirmation_id: str
    ) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM confirmations WHERE id = ?",
                (confirmation_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_confirmation(self, confirmation_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM confirmations WHERE id = ?",
                (confirmation_id,),
            )
            conn.commit()

    # ─── Ingest log ───────────────────────────────────────────────

    def log_ingest(self, entry: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
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
            conn.commit()

    def get_ingest_log(
        self, wiki_id: str, limit: int = 20
    ) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM ingest_log
                   WHERE wiki_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (wiki_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_ingest_entry(self, ingest_id: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM ingest_log WHERE id = ?",
                (ingest_id,),
            ).fetchone()
            return dict(row) if row else None

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


def _row_to_step_dict(row: sqlite3.Row) -> dict:
    """Convert a research_steps row to a dict, parsing result_json."""
    d = dict(row)
    if d.get("result_json"):
        try:
            d["result"] = json.loads(d["result_json"])
        except (json.JSONDecodeError, TypeError):
            d["result"] = None
    else:
        d["result"] = None
    return d


# ─── Backward-compat aliases ─────────────────────────────────────
# Pre-Phase-3 callers used ``AutoResearchDatabase`` and the
# helper ``get_autoresearch_db_path``. After Phase 3, all
# three names refer to the same class / function. The DB
# file path is the same (data_dir / "autoresearch.db") so
# existing user data is preserved.
AutoResearchDatabase = ChatDatabase
get_autoresearch_db_path = get_chat_db_path


__all__ = [
    "ChatDatabase",
    "AutoResearchDatabase",  # back-compat alias
    "DB_SIZE_WARNING_MB",
    "get_chat_db_path",
    "get_autoresearch_db_path",  # back-compat alias
]
