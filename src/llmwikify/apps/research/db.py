"""ResearchDatabase — research-ops domain facade over the shared .llmwiki_agent.db.

Per v0.33-service-refactor.md, this is one of 3 logical
database facades over the same physical SQLite file
(``data_dir/.llmwiki_agent.db``).

Tables owned
------------

  - ``autoresearch_sessions``: research session state
  - ``autoresearch_sub_queries``: sub-queries per session
  - ``autoresearch_sources``: sources per sub-query
  - ``research_steps``: 6-step framework audit trail

All research methods that were previously in ChatDatabase
live here. ChatDatabase delegates to ResearchDatabase for
backward compat (see ``apps/chat/db.py``).
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


class ResearchDatabase(BaseDatabase):
    """Research facade: sessions, sub-queries, sources, research steps.

    The 4 tables are created in the shared physical
    .llmwiki_agent.db file (same as ChatDatabase and
    WikiDatabase). This class only exposes the research
    methods; the other 7 tables (chat + wiki-ops) are
    accessed via the other facades.
    """

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with the project's standard pragmas.

        - ``journal_mode=WAL`` lets readers proceed while a writer
          holds the lock, eliminating most ``database is locked``
          errors.
        - ``busy_timeout=5000`` makes SQLite block for up to 5s
          waiting for the lock instead of failing immediately.
        - ``row_factory=sqlite3.Row`` so callers can use ``row["col"]``
          syntax (the v0.34.0 CHANGELOG entry notes a tuple-index
          bug from missing row_factory in some methods).
        - ``synchronous=NORMAL`` is the safe-for-WAL mode that gives
          the durability of FULL with the throughput of OFF.

        Note: ``foreign_keys`` is intentionally NOT enabled. The
        pre-existing schema has 3 FK constraints and the test
        suite has fixtures that violate them (e.g. ``save_source``
        with a sub_query_id that hasn't been inserted yet). Turning
        FK enforcement on would surface latent data-integrity bugs
        that need to be fixed separately. Use raw ``sqlite3``
        connections and ``PRAGMA foreign_keys = ON`` explicitly
        in tests that need it.

        All call sites that open ``sqlite3.connect(self.db_path)``
        should go through this helper.
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            isolation_level=None,  # autocommit; we manage txns explicitly
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        """Idempotently create the 4 research tables.

        NOTE: this method only creates the 4 tables owned
        by ResearchDatabase. The other 8 tables (chat + wiki-ops)
        are created by their respective facades when they
        construct.
        """
        with self._connect() as conn:
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

            # ── Issue#5: autoresearch_events table (replaces events_json blob) ──
            # Each event is a row with the full payload as JSON + an index on
            # (session_id, ts) for O(log n) range queries and pagination.
            # The events_json column is kept for now (dual-write period)
            # as a fallback for sessions that haven't been migrated.
            conn.execute(
        """
        CREATE TABLE IF NOT EXISTS autoresearch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            ts REAL NOT NULL,
            event_type TEXT,
            payload_json TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES autoresearch_sessions(id)
        )
        """
            )
            conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_autoresearch_events_sid_ts
        ON autoresearch_events(session_id, ts)
        """
            )

            conn.commit()

    # ─── Research methods (moved from ChatDatabase) ─────────────
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
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO autoresearch_sessions
                   (id, wiki_id, query, status, current_step)
                   VALUES (?, ?, ?, 'clarifying', 'clarifying')""",
                (session_id, wiki_id, query),
            )
            conn.commit()
        return session_id

    def get_research_session(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM autoresearch_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_research_sessions(
        self,
        wiki_id: str | None = None,
        session_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            sql = """SELECT s.*,
                       COUNT(DISTINCT sq.id) AS sub_query_count,
                       COUNT(DISTINCT src.id) AS source_count
                    FROM autoresearch_sessions s
                    LEFT JOIN autoresearch_sub_queries sq ON sq.session_id = s.id
                    LEFT JOIN autoresearch_sources src ON src.session_id = s.id"""
            clauses: list[str] = []
            params: list[Any] = []
            if wiki_id is not None:
                clauses.append("s.wiki_id = ?")
                params.append(wiki_id)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " GROUP BY s.id ORDER BY s.created_at DESC LIMIT ?"
            params.append(int(limit))
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
            conn.execute(
                """UPDATE autoresearch_sessions
                   SET status = 'done', result = ?, wiki_page_name = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (result, wiki_page_name, session_id),
            )
            conn.commit()

    def delete_research(self, session_id: str) -> bool:
        """Delete a session and cascade-delete its sub_queries, sources,
        steps, and events (Issue#5)."""
        with self._connect() as conn:
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
            # Issue#5: clear the new event table too. Without this, a
            # future get_events(sid) would fall through to the events_json
            # blob (which IS cleared by the session DELETE above since
            # it's a column) — but new append_events would re-create
            # events under a non-existent session. Be explicit.
            conn.execute(
                "DELETE FROM autoresearch_events WHERE session_id = ?",
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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

    def get_sub_query_count(self, session_id: str) -> int:
        """Cheap count-only query (no row hydration).

        Issue#8: used by the observer's dirty-check to decide whether
        the full ``get_sub_queries`` is needed.
        """
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS c FROM autoresearch_sub_queries
                   WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
        return int(row[0]) if row else 0

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
        with self._connect() as conn:
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
        with self._connect() as conn:
            conn.execute(
                "UPDATE autoresearch_sources SET analysis = ? WHERE id = ?",
                (analysis_json, source_id),
            )
            conn.commit()

    def get_sources(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
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

    def count_sources(self, session_id: str) -> int:
        """Cheap count-only query (no row hydration).

        Issue#8: used by the observer's dirty-check to decide whether
        the full ``get_sources`` is needed. Alias of ``get_source_count``
        for naming consistency with ``get_sub_query_count``.
        """
        return self.get_source_count(session_id)

    def rate_source(self, source_id: str, rating: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE autoresearch_sources SET rating = ? WHERE id = ?",
                (rating, source_id),
            )
            conn.commit()

    def get_source_count(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM autoresearch_sources WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row[0] if row else 0

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
        with self._connect() as conn:
            conn.execute(
                f"UPDATE autoresearch_sessions SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()

    def get_six_step_fields(self, session_id: str) -> dict[str, Any]:
        """Return all 6 JSON framework fields for a session, parsed.

        Missing fields are returned as None.
        """
        with self._connect() as conn:
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
        """Append a batch of events to the session's persisted event log.

        Issue#5: dual-write to the new ``autoresearch_events`` table
        (O(1) per event) AND the legacy ``events_json`` column (kept
        as fallback for sessions not yet migrated to the new table).
        After the migration script runs against all existing sessions
        and the blob is confirmed stale, the events_json write can
        be removed.
        """
        if not events:
            return 0
        import time as _time
        now_ts = _time.time()
        with self._connect() as conn:
            # New table: O(1) bulk insert
            conn.execute("BEGIN")
            try:
                conn.executemany(
                    """INSERT INTO autoresearch_events
                       (session_id, ts, event_type, payload_json)
                       VALUES (?, ?, ?, ?)""",
                    (
                        (
                            session_id,
                            now_ts + i * 0.0001,  # preserve insertion order
                            e.get("type"),
                            json.dumps(e, ensure_ascii=False),
                        )
                        for i, e in enumerate(events)
                    ),
                )
                # Legacy blob: kept during dual-write period
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
            except Exception:
                conn.rollback()
                raise

    def get_events(self, session_id: str) -> list[dict]:
        """Return all persisted events for a session, in insertion order.

        Issue#5: reads from the new ``autoresearch_events`` table
        (O(n) where n = number of events for this session). If the
        new table is empty (session was created before this migration
        and has never been touched since), falls back to the legacy
        ``events_json`` blob to preserve backward compatibility.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT payload_json FROM autoresearch_events
                   WHERE session_id = ?
                   ORDER BY ts ASC, id ASC""",
                (session_id,),
            ).fetchall()
            if rows:
                out: list[dict] = []
                for r in rows:
                    try:
                        out.append(json.loads(r["payload_json"]))
                    except (json.JSONDecodeError, TypeError):
                        continue
                return out
            # Fallback: legacy blob (only when new table has nothing)
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

    def get_events_since(
        self, session_id: str, since_ts: float, *, limit: int = 500,
    ) -> list[dict]:
        """Return events for a session with ``ts > since_ts`` (Issue#15).

        Uses the indexed ``(session_id, ts)`` range scan for O(log n)
        cost. Used by clients that track the max ts they've seen and
        only need to fetch the delta on each poll.

        Args:
            since_ts: Unix epoch seconds. Events with ``ts > since_ts``
                are returned (strictly greater, so the cursor event is
                not duplicated).
            limit: Maximum number of events to return. Defaults to 500
                which is enough for a 5s polling cycle at ~100 events/s.

        Returns:
            List of event dicts, in insertion order. Empty if no
            new events since the cursor.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT payload_json, ts FROM autoresearch_events
                   WHERE session_id = ? AND ts > ?
                   ORDER BY ts ASC, id ASC
                   LIMIT ?""",
                (session_id, since_ts, int(limit)),
            ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                out.append(json.loads(r["payload_json"]))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    # ─── Issue#5: events_json → autoresearch_events migration ─────

    def count_event_rows(self, session_id: str) -> int:
        """Return how many event rows exist in the new table for a session.

        Used by the migration script to detect sessions that still need
        to be migrated (count == 0 + events_json blob is non-null).
        """
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS c FROM autoresearch_events
                   WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def migrate_session_events_to_table(
        self, session_id: str, *, base_ts: float | None = None,
    ) -> int:
        """One-shot migration: copy events_json blob → autoresearch_events.

        Idempotent: if the new table already has rows for this session,
        returns 0 (no-op). Otherwise, parses the blob and inserts one
        row per event with synthetic timestamps (base_ts + i * 0.0001)
        to preserve insertion order.

        Returns: number of rows inserted (0 if already migrated or
        no blob to migrate).
        """
        import time as _time
        if base_ts is None:
            base_ts = _time.time()

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            # Skip if already migrated
            existing = conn.execute(
                """SELECT COUNT(*) AS c FROM autoresearch_events
                   WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
            if existing and int(existing["c"]) > 0:
                return 0

            row = conn.execute(
                "SELECT events_json FROM autoresearch_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not row or not row["events_json"]:
                return 0

            try:
                events = json.loads(row["events_json"])
            except (json.JSONDecodeError, TypeError):
                return 0
            if not isinstance(events, list) or not events:
                return 0

            conn.executemany(
                """INSERT INTO autoresearch_events
                   (session_id, ts, event_type, payload_json)
                   VALUES (?, ?, ?, ?)""",
                (
                    (
                        session_id,
                        base_ts + i * 0.0001,
                        e.get("type") if isinstance(e, dict) else None,
                        json.dumps(e, ensure_ascii=False),
                    )
                    for i, e in enumerate(events)
                ),
            )
            conn.commit()
            return len(events)

    def list_sessions_with_unmigrated_events(self) -> list[str]:
        """Return session_ids where events_json blob is non-empty but
        the new autoresearch_events table has no rows.

        Used by the migration script to find pending work.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT s.id AS id
                   FROM autoresearch_sessions s
                   WHERE s.events_json IS NOT NULL
                     AND s.events_json != ''
                     AND s.events_json != '[]'
                     AND NOT EXISTS (
                       SELECT 1 FROM autoresearch_events e
                       WHERE e.session_id = s.id
                     )""",
            ).fetchall()
        return [r["id"] for r in rows]

    def drop_legacy_events_json(self) -> int:
        """Drop the events_json column from autoresearch_sessions.

        Phase 3 of Issue#5 — only call this after the migration script
        has been run on all production data and the new table is the
        sole source of truth. Returns 0 (SQLite ALTER DROP COLUMN was
        added in 3.35.0 and we always return successfully or raise).
        """
        # We use raw SQL via the connection; SQLite supports DROP COLUMN
        # since 3.35.0 (Jan 2021). The base_db pragmas ensure modern SQLite.
        with self._connect() as conn:
            conn.execute(
                "ALTER TABLE autoresearch_sessions DROP COLUMN events_json",
            )
            conn.commit()
        return 0

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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
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
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM research_steps WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cur.rowcount

    def update_step_status(
        self, session_id: str, step_num: int, status: str
    ) -> None:
        with self._connect() as conn:
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

