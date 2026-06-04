"""AutoResearchDatabase: independent SQLite database for autoresearch.

This module is fully self-contained — it does not import from
llmwikify.agent.backend. The public method names intentionally mirror
AgentDatabase's research-related API so that engine.py / session.py /
gatherer.py / analyzer.py / routes.py work unchanged.

Differences from AgentDatabase:
- DB file: ~/.llmwikify/agent/autoresearch.db (independent)
- Tables: autoresearch_sessions / autoresearch_sub_queries / autoresearch_sources
- 6-step framework fields are native in the schema (no ALTER TABLE)
- Default status is 'clarifying' (not 'planning') because the first
  6-step stage is concept clarification
- Adds 6-step framework helpers: update_six_step_fields, get_six_step_fields
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


def get_autoresearch_db_path(data_dir: Path | str) -> Path:
    """Return the autoresearch.db path inside the given data dir."""
    return Path(data_dir) / "autoresearch.db"


class AutoResearchDatabase:
    """Independent SQLite database for autoresearch sessions, sub-queries, and sources.

    Tables:
    - autoresearch_sessions
    - autoresearch_sub_queries
    - autoresearch_sources

    Public method names mirror AgentDatabase so existing code can adopt
    this DB with only an import-path change.
    """

    def __init__(self, data_dir: Path | str):
        """Initialize the autoresearch database.

        Args:
            data_dir: Directory where autoresearch.db will be created
                      (typically ~/.llmwikify/agent/).
        """
        self.data_dir = Path(data_dir)
        self.db_path = get_autoresearch_db_path(self.data_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._check_db_size()

    # ─── low-level helpers ─────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Idempotently create the autoresearch schema (3 tables + 2 indexes)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
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
                    synthesis_json TEXT,
                    review_json TEXT,
                    clarification_json TEXT,
                    reasoning_json TEXT,
                    structure_json TEXT,
                    self_loop_counts_json TEXT,
                    self_loop_history_json TEXT,
                    evidence_scores_json TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
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
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ar_sub_queries_session
                ON autoresearch_sub_queries(session_id, status)
            """)
            conn.execute("""
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
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ar_sources_session
                ON autoresearch_sources(session_id)
            """)
            conn.commit()

    def _check_db_size(self) -> None:
        """Warn if the autoresearch.db file grows beyond the threshold."""
        if not self.db_path.exists():
            return
        size_mb = self.db_path.stat().st_size / 1024 / 1024
        if size_mb > DB_SIZE_WARNING_MB:
            logger.warning(
                "AutoResearch DB is large: %.2f MB (threshold: %d MB). "
                "Consider deleting old sessions.",
                size_mb, DB_SIZE_WARNING_MB,
            )

    # ─── Session CRUD ─────────────────────────────────────────────

    def create_research_session(self, wiki_id: str, query: str) -> str:
        """Create a new autoresearch session and return its id.

        Default status is 'clarifying' (the first 6-step stage).
        """
        session_id = str(uuid.uuid4())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO autoresearch_sessions (id, wiki_id, query, status, current_step)
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

    def list_research_sessions(self, wiki_id: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if wiki_id:
                rows = conn.execute(
                    """SELECT s.*,
                       (SELECT COUNT(*) FROM autoresearch_sub_queries
                        WHERE session_id = s.id) as sub_query_count,
                       (SELECT COUNT(*) FROM autoresearch_sources
                        WHERE session_id = s.id) as source_count
                    FROM autoresearch_sessions s
                    WHERE s.wiki_id = ?
                    ORDER BY s.created_at DESC""",
                    (wiki_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT s.*,
                       (SELECT COUNT(*) FROM autoresearch_sub_queries
                        WHERE session_id = s.id) as sub_query_count,
                       (SELECT COUNT(*) FROM autoresearch_sources
                        WHERE session_id = s.id) as source_count
                    FROM autoresearch_sessions s
                    ORDER BY s.created_at DESC"""
                ).fetchall()
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
                       SET progress = ?, wiki_page_name = ?, updated_at = datetime('now')
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

    def persist_report(self, session_id: str, result: str | None = None) -> None:
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
        """Delete a session and cascade-delete its sub_queries and sources."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM autoresearch_sources WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "DELETE FROM autoresearch_sub_queries WHERE session_id = ?",
                (session_id,),
            )
            cursor = conn.execute(
                "DELETE FROM autoresearch_sessions WHERE id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ─── Sub-queries ──────────────────────────────────────────────

    def save_sub_query(
        self,
        session_id: str,
        query: str,
        source_type: str,
        url: str | None = None,
    ) -> str:
        sq_id = str(uuid.uuid4())
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

    # ─── Sources ──────────────────────────────────────────────────

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
        source_id = str(uuid.uuid4())
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
                """UPDATE autoresearch_sources
                   SET analysis = ?
                   WHERE id = ?""",
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

    # ─── 6-step framework helpers ────────────────────────────────

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

        Only fields that are not None are written. Existing values are
        overwritten (not merged). This replaces the previous engine.py
        raw SQL block.
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
