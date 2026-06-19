"""MemoryFactsStore — SQLite CRUD for memory_facts.

Phase 6 (2026-06-19): Borrowed from nanobot Dream architecture
(see nanobot/agent/memory.py:859).

Stores long-term extracted facts produced by Dream when it scans
memory_consolidations and uses an LLM to extract durable knowledge.
Each row records:
  - a single fact (free-text content)
  - its source (consolidation / dream_extraction / manual)
  - confidence (0.0-1.0)
  - last_referenced_at (for eviction)

Idempotent init via tables.py CREATE TABLE IF NOT EXISTS.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from llmwikify.apps.chat.memory.tables import ALL_PHASE6_DDL

logger = logging.getLogger(__name__)


FactSource = Literal["consolidation", "dream_extraction", "manual"]


@dataclass
class Fact:
    """One extracted fact (mirrors memory_facts row)."""

    id: str
    content: str
    source_session_id: str | None = None
    source_type: str = "dream_extraction"
    confidence: float = 1.0
    last_referenced_at: float | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "source_session_id": self.source_session_id,
            "source_type": self.source_type,
            "confidence": self.confidence,
            "last_referenced_at": self.last_referenced_at,
            "created_at": self.created_at,
        }


class MemoryFactsStore:
    """SQLite CRUD wrapper for memory_facts table.

    Backed by ``ChatDatabase.db_path``. Used by Dream (Phase 6
    Step 3) to persist extracted facts.
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
        content: str,
        source_type: FactSource = "dream_extraction",
        source_session_id: str | None = None,
        confidence: float = 1.0,
        fact_id: str | None = None,
    ) -> str:
        """Insert a fact. Returns the new id."""
        fid = fact_id or str(uuid.uuid4())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO memory_facts
                   (id, content, source_session_id, source_type,
                    confidence, last_referenced_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    fid,
                    content,
                    source_session_id,
                    source_type,
                    confidence,
                    None,
                    time.time(),
                ),
            )
            conn.commit()
        return fid

    def get(self, fact_id: str) -> Fact | None:
        """Fetch one fact by id. Returns None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM memory_facts WHERE id = ?",
                (fact_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_fact(row)

    def list_by_source(
        self,
        source_type: FactSource,
        limit: int | None = None,
    ) -> list[Fact]:
        """List facts of a specific source type, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            sql = (
                "SELECT * FROM memory_facts "
                "WHERE source_type = ? "
                "ORDER BY created_at DESC"
            )
            params: tuple = (source_type,)
            if limit is not None:
                sql += " LIMIT ?"
                params = (source_type, limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_fact(r) for r in rows]

    def list_all(
        self,
        limit: int | None = None,
    ) -> list[Fact]:
        """List all facts, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM memory_facts ORDER BY created_at DESC"
            params: tuple = ()
            if limit is not None:
                sql += " LIMIT ?"
                params = (limit,)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_fact(r) for r in rows]

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Fact]:
        """Keyword substring search (case-insensitive).

        Used by MemoryIndex integration (optional, future Phase 8).
        """
        if not query:
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memory_facts "
                "WHERE LOWER(content) LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{query.lower()}%", limit),
            ).fetchall()
            return [self._row_to_fact(r) for r in rows]

    def touch(self, fact_id: str) -> bool:
        """Update last_referenced_at to now (for LRU eviction)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE memory_facts SET last_referenced_at = ? WHERE id = ?",
                (time.time(), fact_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete(self, fact_id: str) -> bool:
        """Delete a fact by id. Returns True if deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM memory_facts WHERE id = ?",
                (fact_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def count(self) -> int:
        """Total fact count."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_facts"
            ).fetchone()
            return int(row[0]) if row else 0

    def list_stale(self, threshold_days: int = 14) -> list[Fact]:
        """List facts not referenced within threshold_days (for eviction)."""
        cutoff = time.time() - (threshold_days * 86400)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memory_facts "
                "WHERE last_referenced_at IS NULL OR last_referenced_at < ?",
                (cutoff,),
            ).fetchall()
            return [self._row_to_fact(r) for r in rows]

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> Fact:
        return Fact(
            id=row["id"],
            content=row["content"],
            source_session_id=row["source_session_id"],
            source_type=row["source_type"],
            confidence=row["confidence"],
            last_referenced_at=row["last_referenced_at"],
            created_at=row["created_at"],
        )


__all__ = ["Fact", "FactSource", "MemoryFactsStore"]
