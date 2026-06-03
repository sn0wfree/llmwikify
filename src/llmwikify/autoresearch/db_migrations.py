"""SQLite schema migrations for the 6-step framework.

Adds three columns to research_sessions without touching the base research
schema. Idempotent: safe to call repeatedly (catches OperationalError when
the column already exists).
"""

from __future__ import annotations

import sqlite3

SIX_STEP_COLUMNS: list[tuple[str, str]] = [
    ("clarification_json", "TEXT"),
    ("reasoning_json", "TEXT"),
    ("structure_json", "TEXT"),
]


def ensure_six_step_columns(db_path) -> None:
    """Add 6-step framework columns to research_sessions if missing.

    Args:
        db_path: Path to the SQLite database file (AgentDatabase.db_path).
    """
    with sqlite3.connect(db_path) as conn:
        for col, col_type in SIX_STEP_COLUMNS:
            try:
                conn.execute(
                    f"ALTER TABLE research_sessions ADD COLUMN {col} {col_type}"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
