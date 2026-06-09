"""Migrate data from pre-Phase-3 databases to the consolidated ChatDatabase.

Per v0.32 Phase 3: the two pre-refactor research databases
(``apps/agent/core/db.py::AgentDatabase`` and
``apps/chat/db.py::AutoResearchDatabase``) are now consolidated
into ``apps/chat/db.py::ChatDatabase``. The schema is mostly
additive (the new ``research_steps`` table is added; the
existing 3 autoresearch_* tables are unchanged), so users
without prior data need no migration.

For users with EXISTING data in
``~/.llmwikify/agent/.llmwiki_agent.db`` (AgentDatabase's
research_sessions table), this script copies that data
into the new autoresearch_sessions table. The script:

  1. Backs up the source files to ``.bak-<timestamp>``
  2. Opens the source DB read-only
  3. Inserts each row into the new DB, mapping columns
  4. Reports counts: copied / skipped (already present) /
     errors

Usage:

  # Dry-run (default): show what would be copied
  python scripts/migrate_db_v1_to_v2.py

  # Actually copy the data
  python scripts/migrate_db_v1_to_v2.py --apply

  # Custom data directory
  python scripts/migrate_db_v1_to_v2.py --data-dir ~/.llmwikify/agent

The script is IDEMPOTENT: re-running it will not duplicate
data (it skips rows whose ID already exists in the target).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Source: pre-Phase-3 AgentDatabase (apps/agent/core/db.py)
SOURCE_AGENT_DB = ".llmwiki_agent.db"

# Target: post-Phase-3 ChatDatabase (apps/chat/db.py)
TARGET_AUTORESEARCH_DB = "autoresearch.db"

# Map from AgentDatabase.research_sessions columns →
# ChatDatabase.autoresearch_sessions columns. Most names are
# identical; the differences are listed explicitly.
COLUMN_MAP = {
    # Both sides:
    "id": "id",
    "wiki_id": "wiki_id",
    "query": "query",
    "status": "status",
    "current_step": "current_step",
    "progress": "progress",
    "result": "result",
    "wiki_page_name": "wiki_page_name",
    "iteration_round": "iteration_round",
    # AgentDatabase uses 'planning' as default; ChatDatabase
    # uses 'clarifying'. We preserve the source value (no
    # remap) so existing data semantics are maintained.
    "max_rounds": "max_rounds",
    "quality_score": "quality_score",
    "synthesis_json": "synthesis_json",
    "review_json": "review_json",
    "created_at": "created_at",
    "updated_at": "updated_at",
    # 3 framework JSON columns were present on AgentDatabase's
    # research_sessions as separate columns; on
    # ChatDatabase.autoresearch_sessions they're the same
    # columns. We map them through.
    "clarification_json": "clarification_json",
    "reasoning_json": "reasoning_json",
    "structure_json": "structure_json",
}


def backup_file(path: Path) -> Path:
    """Copy ``path`` to ``path.bak-<timestamp>``. Returns the new path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak-{ts}")
    backup.write_bytes(path.read_bytes())
    logger.info("Backed up %s → %s", path, backup.name)
    return backup


def fetch_source_research_sessions(source_path: Path) -> list[dict]:
    """Read all rows from the source research sessions table.

    Checks for both ``research_sessions`` (pre-v0.33.0) and
    ``autoresearch_sessions`` (v0.33.0+) table names.
    """
    if not source_path.exists():
        logger.info("Source DB %s does not exist, nothing to migrate", source_path)
        return []
    rows: list[dict] = []
    with sqlite3.connect(source_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        # Support both old and new table names
        source_table = None
        if "research_sessions" in tables:
            source_table = "research_sessions"
        elif "autoresearch_sessions" in tables:
            source_table = "autoresearch_sessions"
        if source_table is None:
            logger.info("Source DB has no research sessions table")
            return []
        for row in conn.execute(f"SELECT * FROM {source_table}").fetchall():
            rows.append(dict(row))
    return rows


def fetch_target_session_ids(target_path: Path) -> set[str]:
    """Return the set of session IDs already present in the target DB."""
    if not target_path.exists():
        return set()
    with sqlite3.connect(target_path) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "autoresearch_sessions" not in tables:
            return set()
        return {
            r[0]
            for r in conn.execute("SELECT id FROM autoresearch_sessions").fetchall()
        }


def migrate_research_sessions(
    source_path: Path,
    target_path: Path,
    *,
    apply: bool = False,
) -> dict[str, int]:
    """Copy research_sessions rows from source → target.

    Returns a summary dict with keys: copied, skipped, errors.
    """
    source_rows = fetch_source_research_sessions(source_path)
    target_ids = fetch_target_session_ids(target_path)
    summary = {"copied": 0, "skipped": 0, "errors": 0, "total_source_rows": len(source_rows)}

    if not source_rows:
        return summary

    if not apply:
        for row in source_rows:
            if row.get("id") in target_ids:
                summary["skipped"] += 1
            else:
                summary["copied"] += 1
        return summary

    # Apply: back up source first
    backup_file(source_path)

    # Open target in RW; ensure autoresearch_sessions table exists.
    # We create it directly rather than using ChatDatabase because
    # ChatDatabase normalises to .llmwiki_agent.db, but the
    # migration target may be a different filename (autoresearch.db).
    with sqlite3.connect(target_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS autoresearch_sessions (
                id TEXT PRIMARY KEY,
                wiki_id TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planning',
                current_step TEXT,
                progress REAL,
                result TEXT,
                wiki_page_name TEXT,
                iteration_round INTEGER,
                max_rounds INTEGER,
                max_replan INTEGER,
                quality_score INTEGER,
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
        conn.commit()

    with sqlite3.connect(target_path) as conn:
        for row in source_rows:
            sid = row.get("id")
            if sid in target_ids:
                summary["skipped"] += 1
                continue
            # Build the INSERT with mapped columns
            cols: list[str] = []
            placeholders: list[str] = []
            values: list = []
            for src_col, tgt_col in COLUMN_MAP.items():
                if src_col not in row:
                    continue
                cols.append(tgt_col)
                placeholders.append("?")
                values.append(row[src_col])
            try:
                conn.execute(
                    f"INSERT INTO autoresearch_sessions ({', '.join(cols)}) "
                    f"VALUES ({', '.join(placeholders)})",
                    values,
                )
                summary["copied"] += 1
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to copy session %s: %s", sid, e,
                )
                summary["errors"] += 1
        conn.commit()

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate pre-Phase-3 research data to the new "
                    "consolidated ChatDatabase.",
    )
    parser.add_argument(
        "--data-dir",
        default="~/.llmwikify/agent",
        help="Directory containing the source and target DBs "
             "(default: ~/.llmwikify/agent)",
    )
    parser.add_argument(
        "--source",
        default=SOURCE_AGENT_DB,
        help=f"Source DB filename (default: {SOURCE_AGENT_DB})",
    )
    parser.add_argument(
        "--target",
        default=TARGET_AUTORESEARCH_DB,
        help=f"Target DB filename (default: {TARGET_AUTORESEARCH_DB})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the migration (default: dry-run)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    data_dir = Path(args.data_dir).expanduser()
    source_path = data_dir / args.source
    target_path = data_dir / args.target

    if not data_dir.exists():
        print(f"ERROR: data directory does not exist: {data_dir}", file=sys.stderr)
        return 2

    print(f"Source: {source_path}")
    print(f"Target: {target_path}")
    print(f"Mode:   {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    summary = migrate_research_sessions(
        source_path, target_path, apply=args.apply,
    )

    print("Summary:")
    print(f"  Source rows found: {summary['total_source_rows']}")
    print(f"  Would copy:         {summary['copied']}")
    print(f"  Would skip:         {summary['skipped']} (already in target)")
    print(f"  Errors:             {summary['errors']}")
    print()

    if not args.apply and summary["copied"] > 0:
        print(f"Re-run with --apply to actually copy {summary['copied']} rows.")
        return 0
    if not args.apply and summary["copied"] == 0:
        print("Nothing to migrate.")
        return 0
    if args.apply:
        print(f"Migration complete: copied {summary['copied']} rows.")
        if summary["errors"]:
            return 1
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
