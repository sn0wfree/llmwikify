"""MemoryConsolidationStore — SQLite CRUD for memory_consolidations.

Phase 6 (2026-06-19): Borrowed from nanobot Consolidator architecture
(see nanobot/agent/memory.py:444).

Stores per-session summary records produced by Consolidator when
``AgentContext.messages`` exceed the token threshold. Each row records:
  - which session + which message range was summarized
  - the LLM-generated summary
  - the markdown file path (if double-written)
  - token counts before/after

Idempotent init via tables.py CREATE TABLE IF NOT EXISTS.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.memory.tables import ALL_PHASE6_DDL

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationRecord:
    """One consolidation event (mirrors memory_consolidations row)."""

    id: str
    session_id: str
    start_msg_idx: int
    end_msg_idx: int
    summary: str
    md_file_path: str | None = None
    tokens_before: int | None = None
    tokens_after: int | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "start_msg_idx": self.start_msg_idx,
            "end_msg_idx": self.end_msg_idx,
            "summary": self.summary,
            "md_file_path": self.md_file_path,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "created_at": self.created_at,
        }


class MemoryConsolidationStore:
    """SQLite CRUD wrapper for memory_consolidations table.

    Backed by ``ChatDatabase.db_path``. Used by Consolidator (Phase 6
    Step 2) to persist summaries.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def init_schema(self) -> None:
        """Create table + indexes (idempotent)."""
        with sqlite3.connect(self.db_path) as conn:
            for ddl in ALL_PHASE6_DDL:
                conn.execute(ddl)
            conn.commit()

    def add(
        self,
        session_id: str,
        start_msg_idx: int,
        end_msg_idx: int,
        summary: str,
        md_file_path: str | None = None,
        tokens_before: int | None = None,
        tokens_after: int | None = None,
        consolidation_id: str | None = None,
    ) -> str:
        """Insert a consolidation record. Returns the new id."""
        cid = consolidation_id or str(uuid.uuid4())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO memory_consolidations
                   (id, session_id, start_msg_idx, end_msg_idx,
                    summary, md_file_path, tokens_before, tokens_after, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cid,
                    session_id,
                    start_msg_idx,
                    end_msg_idx,
                    summary,
                    md_file_path,
                    tokens_before,
                    tokens_after,
                    time.time(),
                ),
            )
            conn.commit()
        return cid

    def get(self, consolidation_id: str) -> ConsolidationRecord | None:
        """Fetch one record by id. Returns None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM memory_consolidations WHERE id = ?",
                (consolidation_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def list_by_session(
        self, session_id: str, limit: int | None = None
    ) -> list[ConsolidationRecord]:
        """List consolidations for one session, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            sql = (
                "SELECT * FROM memory_consolidations "
                "WHERE session_id = ? "
                "ORDER BY created_at DESC"
            )
            params: tuple = (session_id,)
            if limit is not None:
                sql += " LIMIT ?"
                params = (session_id, limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def list_since(
        self,
        since_timestamp: float,
        limit: int | None = None,
    ) -> list[ConsolidationRecord]:
        """List consolidations created after ``since_timestamp``.

        Used by Dream to scan for new unconsolidated history
        (since-last-run cursor pattern, borrowed from nanobot).
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            sql = (
                "SELECT * FROM memory_consolidations "
                "WHERE created_at > ? "
                "ORDER BY created_at ASC"
            )
            params: tuple = (since_timestamp,)
            if limit is not None:
                sql += " LIMIT ?"
                params = (since_timestamp, limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def latest_for_session(self, session_id: str) -> ConsolidationRecord | None:
        """Return the most recent consolidation for a session (or None)."""
        records = self.list_by_session(session_id, limit=1)
        return records[0] if records else None

    def delete(self, consolidation_id: str) -> bool:
        """Delete a consolidation record by id. Returns True if deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM memory_consolidations WHERE id = ?",
                (consolidation_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def count_by_session(self, session_id: str) -> int:
        """Count consolidation records for one session."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_consolidations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return int(row[0]) if row else 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ConsolidationRecord:
        return ConsolidationRecord(
            id=row["id"],
            session_id=row["session_id"],
            start_msg_idx=row["start_msg_idx"],
            end_msg_idx=row["end_msg_idx"],
            summary=row["summary"],
            md_file_path=row["md_file_path"],
            tokens_before=row["tokens_before"],
            tokens_after=row["tokens_after"],
            created_at=row["created_at"],
        )


__all__ = ["ConsolidationRecord", "MemoryConsolidationStore"]
