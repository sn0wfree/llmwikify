"""Schema bootstrap and migration helpers for the autoresearch database.

AutoResearchDatabase.__init__ already runs the idempotent
`CREATE TABLE IF NOT EXISTS` for the 3 tables. This module exposes an
explicit entry point (`init_autoresearch_db`) and an optional cleanup
helper (`migrate_research_six_step_columns`) for users who previously
ran autoresearch against the old shared `AgentDatabase` layout and
want to drop the 3 leftover JSON columns from `research_sessions`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


# Columns that autoresearch v1-v3 added to the shared `research_sessions`
# table via ALTER TABLE. They have been replaced by native columns in the
# independent `autoresearch_sessions` table.
LEGACY_SHARED_COLUMNS: list[tuple[str, str]] = [
    ("clarification_json", "TEXT"),
    ("reasoning_json", "TEXT"),
    ("structure_json", "TEXT"),
]


def init_autoresearch_db(db_path) -> None:
    """Idempotently create the autoresearch schema.

    Args:
        db_path: Path to the autoresearch.db file (typically
                 ~/.llmwikify/agent/autoresearch.db).

    .. note::
        The canonical filename is now ``.llmwiki_agent.db``.
        Calling this with a path pointing to the old
        ``autoresearch.db`` filename works: the underlying
        ChatDatabase init will auto-migrate the legacy file to
        the new name. To read the resulting DB, query the
        canonical path returned by ``get_app_db_path()``.
    """
    from llmwikify.apps.chat.db import AutoResearchDatabase
    from llmwikify.apps.db_base import get_app_db_path
    db_path = Path(db_path)
    AutoResearchDatabase(db_path.parent)
    # The init above will create the file at the canonical
    # .llmwiki_agent.db path. If the caller passed the legacy
    # path, they should use get_app_db_path() to find it.
    _ = get_app_db_path(db_path.parent)


def migrate_research_six_step_columns(
    old_db_path,
    drop_columns: bool = True,
) -> int:
    """Optional: clean up the legacy autoresearch columns from research_sessions.

    The v1-v3 design added 3 columns to the shared `research_sessions`
    table in `.llmwiki_agent.db` via `ALTER TABLE`. The v4 design moved
    autoresearch to its own database. If you have old data, you can
    call this helper to drop the leftover columns.

    Args:
        old_db_path: Path to the shared `AgentDatabase` file.
        drop_columns: If True, actually drop the columns. If False, only
                      report which columns exist (dry-run).

    Returns:
        Number of columns dropped (or that would be dropped in dry-run).
    """
    old_db_path = Path(old_db_path)
    if not old_db_path.exists():
        logger.info("Old DB not found at %s, nothing to migrate", old_db_path)
        return 0

    with sqlite3.connect(old_db_path) as conn:
        # Check which legacy columns currently exist
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(research_sessions)").fetchall()
        }
        to_drop = [col for col, _ in LEGACY_SHARED_COLUMNS if col in existing]

        if not to_drop:
            logger.info("No legacy autoresearch columns to clean up")
            return 0

        if not drop_columns:
            logger.info("Dry-run: would drop %s", to_drop)
            return len(to_drop)

        dropped = 0
        for col in to_drop:
            try:
                # SQLite ≥ 3.35 supports DROP COLUMN; older versions raise.
                conn.execute(f"ALTER TABLE research_sessions DROP COLUMN {col}")
                dropped += 1
                logger.info("Dropped legacy column: %s", col)
            except sqlite3.OperationalError as e:
                logger.warning(
                    "Could not drop %s (SQLite version may be < 3.35): %s. "
                    "The column will remain but is no longer read by autoresearch.",
                    col, e,
                )
        conn.commit()
        return dropped


def migrate_v3_add_events_column(ar_db_path) -> bool:
    """Idempotently add the `events_json` column to autoresearch_sessions.

    New sessions get the column via the CREATE TABLE schema. This helper
    upgrades existing DBs (created before the events_json column was
    introduced) by running an ALTER TABLE that is safe to re-run.

    Args:
        ar_db_path: Path to the autoresearch.db file.

    Returns:
        True if a column was added; False if it was already present or
        the DB doesn't exist yet (will be created with the column).
    """
    ar_db_path = Path(ar_db_path)
    if not ar_db_path.exists():
        return False
    with sqlite3.connect(ar_db_path) as conn:
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(autoresearch_sessions)").fetchall()
        }
        if "events_json" in existing:
            return False
        conn.execute(
            "ALTER TABLE autoresearch_sessions ADD COLUMN events_json TEXT"
        )
        conn.commit()
        logger.info("Added events_json column to autoresearch_sessions")
        return True


# 6-step framework fields. A session is "incomplete" if any of these
# are NULL on a session marked 'done' or with progress=1.0.
FRAMEWORK_FIELDS = (
    "clarification_json",
    "evidence_scores_json",
    "synthesis_json",
    "reasoning_json",
    "structure_json",
    "review_json",
)


def migrate_v3_mark_partial_sessions(ar_db_path) -> list[str]:
    """Backfill: mark 'done' sessions as 'incomplete' if 6-step fields are missing.

    Fixes the bug pattern observed in session 7fe6f04f-9cab-...: engine
    marked session as 'done' but 4/6 framework steps never ran
    (result.markdown=null, quality_score=0). After the framework
    compliance gate is added (commit a45d3a7 followup), this can no
    longer happen — but old sessions in the DB still have status='done'.

    This migration:
    1. Finds sessions with status='done' (or progress=1.0) where ANY
       of FRAMEWORK_FIELDS is NULL or empty
    2. Sets their status to 'incomplete'
    3. Updates their result JSON with incomplete_reason + framework_completed

    Idempotent: re-running on a clean DB returns an empty list.

    Args:
        ar_db_path: Path to the autoresearch.db file.

    Returns:
        List of session IDs that were updated.
    """
    ar_db_path = Path(ar_db_path)
    if not ar_db_path.exists():
        return []
    updated: list[str] = []
    with sqlite3.connect(ar_db_path) as conn:
        conn.row_factory = sqlite3.Row
        # Find 'done' sessions with missing framework fields
        rows = conn.execute(
            """SELECT id, query, result,
                      clarification_json, evidence_scores_json,
                      synthesis_json, reasoning_json, structure_json,
                      review_json
               FROM autoresearch_sessions
               WHERE status = 'done'"""
        ).fetchall()
        for row in rows:
            present = sum(
                1 for f in FRAMEWORK_FIELDS
                if row[f] is not None and str(row[f]).strip()
            )
            total = len(FRAMEWORK_FIELDS)
            if present == total:
                continue  # fully complete, skip
            # Partial: backfill
            sid = row["id"]
            existing_result = {}
            if row["result"]:
                try:
                    existing_result = json.loads(row["result"])
                except (json.JSONDecodeError, TypeError):
                    pass
            existing_result["incomplete_reason"] = (
                f"backfill: only {present}/{total} framework steps completed"
            )
            existing_result["framework_completed"] = present
            existing_result["framework_total"] = total
            new_result = json.dumps(existing_result, ensure_ascii=False)
            conn.execute(
                """UPDATE autoresearch_sessions
                   SET status = 'incomplete',
                       current_step = 'incomplete',
                       result = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (new_result, sid),
            )
            updated.append(sid)
            logger.info(
                "Backfilled session %s: %d/%d framework steps → status=incomplete",
                sid, present, total,
            )
        conn.commit()
    return updated
