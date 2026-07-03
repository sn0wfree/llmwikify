"""One-time migration: events_json blob → autoresearch_events table.

Issue#5 — moves the per-session events log out of a single denormalized
JSON blob (which had O(n²) write cost and a 100MB+ per-row limit) into
a proper normalized table with an index on (session_id, ts).

Run from the project root:

    python scripts/migrate_events_to_table.py [--dry-run] [--drop-legacy]

Options:
    --dry-run       Show what would be migrated without writing.
    --drop-legacy   After migration, drop the events_json column
                    (Issue#5 Phase 3). Use with caution — only after
                    verifying all sessions have been migrated.

The script is idempotent: re-running it is a no-op for already-migrated
sessions (the autoresearch_events table is the source of truth, and the
blob is only read if the table is empty for that session).

Typical workflow:

    # 1. Audit
    python scripts/migrate_events_to_table.py --dry-run

    # 2. Migrate (writes new rows)
    python scripts/migrate_events_to_table.py

    # 3. Verify get_events() still returns the same data
    #    (the app continues to dual-write for new events)

    # 4. Later, after confidence: drop the legacy column
    python scripts/migrate_events_to_table.py --drop-legacy
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_agent_dir() -> Path:
    """Return the agent dir, honoring LLMWIKIFY_AGENT_DIR env var (for tests)."""
    import os
    override = os.environ.get("LLMWIKIFY_AGENT_DIR")
    if override:
        return Path(override)
    return Path.home() / ".llmwikify" / "agent"


def _open_research_db(agent_dir: Path | None = None):  # noqa: ANN001
    """Open a ResearchDatabase pointing at the given agent dir."""
    from llmwikify.apps.research.db import ResearchDatabase
    if agent_dir is None:
        agent_dir = _get_agent_dir()
    return ResearchDatabase(agent_dir)


def _backup_db(agent_dir: Path, *, suffix: str | None = None) -> Path:
    """Make a timestamped backup of the shared DB file (if it exists)."""
    db_path = agent_dir / ".llmwiki_agent.db"
    if not db_path.exists():
        # Newer installations may have the schema in a different file.
        candidates = list(agent_dir.glob("*.db"))
        if not candidates:
            logger.warning("No DB file found under %s, skipping backup", agent_dir)
            return None
        db_path = candidates[0]
    ts = suffix or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_suffix(f".db.pre_issue5_{ts}.bak")
    shutil.copy2(db_path, backup)
    logger.info("Backed up %s -> %s", db_path, backup)
    return backup


def report(
    agent_dir: Path | None = None,
    *,
    dry_run: bool = False,
    drop_legacy: bool = False,
) -> dict:
    """Run the migration. Returns a structured report.

    Args:
        agent_dir: Optional override for the agent directory (used in tests).
        dry_run: If True, do not write to the DB.
        drop_legacy: If True, drop the events_json column after migration.
    """
    if agent_dir is None:
        agent_dir = _get_agent_dir()
    db = _open_research_db(agent_dir)

    pending = db.list_sessions_with_unmigrated_events()
    out: dict = {
        "agent_dir": str(agent_dir),
        "pending_sessions": len(pending),
        "pending_session_ids": pending,
        "migrated": 0,
        "events_migrated": 0,
        "dropped_legacy": False,
        "dry_run": dry_run,
    }

    if pending and not dry_run:
        _backup_db(agent_dir)

    for sid in pending:
        if dry_run:
            count = db.count_event_rows(sid)  # 0
            blob_size = 0
            with db._connect() as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT events_json FROM autoresearch_sessions WHERE id = ?",
                    (sid,),
                ).fetchone()
            if row and row["events_json"]:
                blob_size = len(row["events_json"])
            logger.info(
                "[dry-run] would migrate session=%s events_json_len=%d events_in_table=%d",
                sid, blob_size, count,
            )
            continue
        n = db.migrate_session_events_to_table(sid)
        if n > 0:
            out["migrated"] += 1
            out["events_migrated"] += n
            logger.info("Migrated %d events for session %s", n, sid)

    if drop_legacy and not dry_run and out["migrated"] > 0:
        try:
            db.drop_legacy_events_json()
            out["dropped_legacy"] = True
        except Exception as e:
            logger.warning("Failed to drop legacy column: %s", e)
            out["drop_legacy_error"] = str(e)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate events_json blob → autoresearch_events table (Issue#5)",
    )
    parser.add_argument(
        "--agent-dir", type=Path, default=None,
        help="Override agent directory (default: ~/.llmwikify/agent)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be migrated without writing",
    )
    parser.add_argument(
        "--drop-legacy", action="store_true",
        help="Drop the events_json column after migration (Issue#5 Phase 3)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        result = report(
            agent_dir=args.agent_dir,
            dry_run=args.dry_run,
            drop_legacy=args.drop_legacy,
        )
    except sqlite3.Error as e:  # type: ignore[name-defined]
        print(f"SQLite error during migration: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Migration failed: {e}", file=sys.stderr)
        logger.exception("Migration failed")
        return 1

    print()
    print("=" * 60)
    print("events_json → autoresearch_events migration (Issue#5)")
    print("=" * 60)
    print(f"  Agent dir:          {result['agent_dir']}")
    print(f"  Pending sessions:   {result['pending_sessions']}")
    if result["dry_run"]:
        print("  Mode:               DRY RUN (no changes)")
    else:
        print(f"  Sessions migrated:  {result['migrated']}")
        print(f"  Events migrated:    {result['events_migrated']}")
        if result.get("dropped_legacy"):
            print("  Dropped legacy:     events_json column")
    print("=" * 60)

    return 0


# Late import for the sqlite3 type hint used in except clauses.
import sqlite3  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
