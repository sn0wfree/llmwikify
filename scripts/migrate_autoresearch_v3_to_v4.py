"""One-time migration audit for the v3 → v4 autoresearch DB transition.

Run this script to verify the production database state after the v4
switch to an independent autoresearch.db. The script:

1. Backs up the production `.llmwiki_agent.db` (timestamped)
2. Reports any legacy `clarification_json / reasoning_json / structure_json`
   columns still in `research_sessions` (none expected)
3. Reports any sessions with `status='clarifying'` (none expected — that's
   the autoresearch v3+ marker, not used by base research)
4. Reports the size and row counts of both DBs
5. If any autoresearch data is found in `.llmwiki_agent.db`, the user is
   prompted to run the actual cleanup

Idempotent. Safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LEGACY_AUTORESEARCH_COLUMNS = (
    "clarification_json",
    "reasoning_json",
    "structure_json",
)


def _get_agent_dir() -> Path:
    """Return the agent dir, honoring LLMWIKIFY_AGENT_DIR env var (for tests)."""
    override = __import__("os").environ.get("LLMWIKIFY_AGENT_DIR")
    if override:
        return Path(override)
    return Path.home() / ".llmwikify" / "agent"


def report(agent_dir: Path | None = None) -> dict:
    """Run a read-only audit and return a structured report.

    Args:
        agent_dir: Optional override for the agent directory (used in tests).
                   If None, reads from LLMWIKIFY_AGENT_DIR env var or
                   ~/.llmwikify/agent.
    """
    if agent_dir is None:
        agent_dir = _get_agent_dir()
    shared_db = agent_dir / ".llmwiki_agent.db"
    autoresearch_db = agent_dir / "autoresearch.db"
    out: dict = {
        "agent_dir": str(agent_dir),
        "shared_db_exists": shared_db.exists(),
        "autoresearch_db_exists": autoresearch_db.exists(),
        "shared_db_size_bytes": shared_db.stat().st_size if shared_db.exists() else 0,
        "autoresearch_db_size_bytes": (
            autoresearch_db.stat().st_size if autoresearch_db.exists() else 0
        ),
        "research_sessions_columns": [],
        "legacy_columns_present": [],
        "research_sessions_count": 0,
        "autoresearch_sessions_count": 0,
        "sessions_with_clarifying_status": 0,
        "research_sub_queries_count": 0,
        "research_sources_count": 0,
        "needs_migration": False,
    }
    if shared_db.exists():
        with sqlite3.connect(shared_db) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "research_sessions" in tables:
                cols = [
                    r[1]
                    for r in conn.execute(
                        "PRAGMA table_info(research_sessions)"
                    ).fetchall()
                ]
                out["research_sessions_columns"] = cols
                out["legacy_columns_present"] = [
                    c for c in LEGACY_AUTORESEARCH_COLUMNS if c in cols
                ]
                out["research_sessions_count"] = conn.execute(
                    "SELECT COUNT(*) FROM research_sessions"
                ).fetchone()[0]
                # Build dynamic WHERE: only check columns that actually exist
                # (older schemas may lack current_step or status)
                conds = []
                if "status" in cols:
                    conds.append("status = 'clarifying'")
                if "current_step" in cols:
                    conds.append("current_step = 'clarifying'")
                if conds:
                    where = " WHERE " + " OR ".join(conds)
                else:
                    where = ""
                out["sessions_with_clarifying_status"] = conn.execute(
                    f"SELECT COUNT(*) FROM research_sessions{where}"
                ).fetchone()[0]
            if "research_sub_queries" in tables:
                out["research_sub_queries_count"] = conn.execute(
                    "SELECT COUNT(*) FROM research_sub_queries"
                ).fetchone()[0]
            if "research_sources" in tables:
                out["research_sources_count"] = conn.execute(
                    "SELECT COUNT(*) FROM research_sources"
                ).fetchone()[0]
    if autoresearch_db.exists():
        with sqlite3.connect(autoresearch_db) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "autoresearch_sessions" in tables:
                out["autoresearch_sessions_count"] = conn.execute(
                    "SELECT COUNT(*) FROM autoresearch_sessions"
                ).fetchone()[0]
    out["needs_migration"] = bool(
        out["legacy_columns_present"] or out["sessions_with_clarifying_status"]
    )
    return out


def backup_shared_db(agent_dir: Path | None = None) -> Path:
    """Back up the shared DB with a timestamp suffix. Returns backup path."""
    if agent_dir is None:
        agent_dir = _get_agent_dir()
    shared_db = agent_dir / ".llmwiki_agent.db"
    if not shared_db.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = shared_db.parent / f".llmwiki_agent.db.bak.pre-v4-migration-{ts}"
    shutil.copy2(shared_db, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually drop legacy columns if found (default: dry-run).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print report as JSON (for scripting).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.ERROR if args.json else logging.INFO,
        format="%(message)s",
    )
    if not args.json:
        logger.info("=== autoresearch v4 migration audit ===")

    report_data = report()

    if args.json:
        print(json.dumps(report_data, indent=2, ensure_ascii=False))
        return 0

    logger.info("Agent dir: %s", report_data["agent_dir"])
    logger.info("  .llmwiki_agent.db exists: %s (%d bytes)",
                report_data["shared_db_exists"],
                report_data["shared_db_size_bytes"])
    logger.info("  autoresearch.db exists:  %s (%d bytes)",
                report_data["autoresearch_db_exists"],
                report_data["autoresearch_db_size_bytes"])
    logger.info("")
    logger.info("research_sessions columns: %d", len(report_data["research_sessions_columns"]))
    for c in report_data["research_sessions_columns"]:
        marker = "  ← LEGACY" if c in LEGACY_AUTORESEARCH_COLUMNS else ""
        logger.info("  %s%s", c, marker)
    logger.info("")
    logger.info("Legacy autoresearch columns present: %d (%s)",
                len(report_data["legacy_columns_present"]),
                report_data["legacy_columns_present"] or "none")
    logger.info("Sessions with clarifying status:     %d",
                report_data["sessions_with_clarifying_status"])
    logger.info("")
    logger.info("Row counts:")
    logger.info("  research_sessions:         %d", report_data["research_sessions_count"])
    logger.info("  research_sub_queries:      %d", report_data["research_sub_queries_count"])
    logger.info("  research_sources:          %d", report_data["research_sources_count"])
    logger.info("  autoresearch_sessions:     %d", report_data["autoresearch_sessions_count"])
    logger.info("")

    if not report_data["needs_migration"]:
        if not args.json:
            logger.info("✓ No migration needed. Production DB is clean.")
        return 0

    if not args.json:
        logger.warning("Migration needed:")
        if report_data["legacy_columns_present"]:
            logger.warning("  - Drop %d legacy columns from research_sessions",
                          len(report_data["legacy_columns_present"]))
        if report_data["sessions_with_clarifying_status"]:
            logger.warning("  - %d sessions with clarifying status need review",
                          report_data["sessions_with_clarifying_status"])

    if not args.apply:
        if not args.json:
            logger.info("Dry-run only. Re-run with --apply to actually drop columns.")
        return 0

    backup = backup_shared_db()
    if backup and not args.json:
        logger.info("Backed up shared DB to: %s", backup)

    from llmwikify.apps.chat.db_migrations import migrate_research_six_step_columns
    n = migrate_research_six_step_columns(_get_agent_dir() / ".llmwiki_agent.db", drop_columns=True)
    if not args.json:
        logger.info("Dropped %d column(s)", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
