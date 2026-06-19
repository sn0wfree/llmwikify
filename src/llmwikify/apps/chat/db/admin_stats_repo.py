"""AdminStatsRepository — owns cross-table admin/stats queries.

These methods read across multiple tables to produce counts,
per-wiki breakdowns, and DB size metrics.

Methods (5):
    get_wiki_stats    — per-table counts for a wiki_id
    list_all_wikis    — DISTINCT wiki_ids across all relevant tables
    delete_wiki_data  — DELETE all rows belonging to a wiki_id
    export_wiki_data  — SELECT all rows for export
    get_db_stats      — per-table counts + db size

Tables touched:
    chat_sessions, dream_proposals, notifications, confirmations,
    ingest_log, autoresearch_sessions
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from .base import ChatDBBase

logger = logging.getLogger(__name__)


class AdminStatsRepository(ChatDBBase):
    """Cross-table admin/stats queries.

    Does NOT own any tables (no ``_init_schema``). Reads from tables
    owned by other facades.
    """

    def _init_schema(self) -> None:
        """No tables owned by this repository."""
        return

    def get_wiki_stats(self, wiki_id: str) -> dict[str, Any]:
        """Per-table row counts for a wiki_id."""
        with self._connect() as conn:
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
            row = conn.execute(
                """SELECT COUNT(*) as cnt
                   FROM autoresearch_sessions
                   WHERE wiki_id = ?""",
                (wiki_id,),
            ).fetchone()
            stats["research_sessions"] = row["cnt"] if row else 0
            return {"wiki_id": wiki_id, "counts": stats}

    def list_all_wikis(self) -> list[dict[str, str]]:
        """Distinct wiki_ids across all relevant tables."""
        with self._connect() as conn:
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

    def delete_wiki_data(self, wiki_id: str) -> dict[str, Any]:
        """Delete all rows belonging to a wiki_id. Returns deletion counts."""
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

    def export_wiki_data(self, wiki_id: str) -> dict[str, Any]:
        """Export all rows belonging to a wiki_id."""
        data: dict[str, Any] = {"wiki_id": wiki_id}
        with self._connect() as conn:
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

    def get_db_stats(self) -> dict[str, Any]:
        """Per-table counts across the whole DB + file size in MB."""
        with self._connect() as conn:
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
            size_mb = Path(self.db_path).stat().st_size / 1024 / 1024
            return {"tables": stats, "size_mb": round(size_mb, 2)}


__all__ = ["AdminStatsRepository"]
