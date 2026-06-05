"""Schema bootstrap and migration helpers for the autoresearch database.

AutoResearchDatabase.__init__ already runs the idempotent
`CREATE TABLE IF NOT EXISTS` for the 3 tables. This module exposes an
explicit entry point (`init_autoresearch_db`) and an optional cleanup
helper (`migrate_research_six_step_columns`) for users who previously
ran autoresearch against the old shared `AgentDatabase` layout and
want to drop the 3 leftover JSON columns from `research_sessions`.
"""

from __future__ import annotations

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
    """
    from llmwikify.autoresearch.db import AutoResearchDatabase
    db_path = Path(db_path)
    AutoResearchDatabase(db_path.parent)


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
