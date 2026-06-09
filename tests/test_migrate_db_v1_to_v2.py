"""Tests for the v0.32 Phase 3 migration script.

Exercises scripts/migrate_db_v1_to_v2.py end-to-end:
  - Dry-run reports counts without modifying the DB
  - Apply copies rows + backs up source
  - Idempotency: re-running skips already-migrated rows
  - Skips rows with malformed/missing columns gracefully
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "migrate_db_v1_to_v2.py"
)


def _create_source_db(path: Path, sessions: list[dict]) -> None:
    """Create a ``.llmwiki_agent.db`` with N autoresearch_sessions rows.

    Re-runnable: deletes existing rows first.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
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
                quality_score INTEGER,
                synthesis_json TEXT,
                review_json TEXT,
                clarification_json TEXT,
                reasoning_json TEXT,
                structure_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM autoresearch_sessions")
        for s in sessions:
            cols = ", ".join(s.keys())
            placeholders = ", ".join("?" for _ in s)
            conn.execute(
                f"INSERT INTO autoresearch_sessions ({cols}) VALUES ({placeholders})",
                list(s.values()),
            )
        conn.commit()


def _read_target_session_ids(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "autoresearch_sessions" not in tables:
            return set()
        return {r[0] for r in conn.execute("SELECT id FROM autoresearch_sessions")}


class TestMigrationScript:
    def test_dry_run_on_empty_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "autoresearch.db").touch()
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", tmp],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0
            assert "Nothing to migrate" in result.stdout

    def test_dry_run_no_apply_no_modifications(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            source = data_dir / ".llmwiki_agent.db"
            target = data_dir / "autoresearch.db"
            _create_source_db(source, [
                {"id": "abc-123", "wiki_id": "w1", "query": "q1",
                 "status": "done", "current_step": "reporting",
                 "progress": 1.0, "result": "the report",
                 "iteration_round": 3, "created_at": "2025-01-01",
                 "updated_at": "2025-01-01"},
            ])

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", str(data_dir)],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0
            assert "Would copy:         1" in result.stdout
            # Target DB is created (by the script's import) but is
            # empty — no row was copied in dry-run mode.
            assert _read_target_session_ids(target) == set()

    def test_apply_copies_rows_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            source = data_dir / ".llmwiki_agent.db"
            target = data_dir / "autoresearch.db"
            sessions = [
                {"id": "s-1", "wiki_id": "w1", "query": "q1",
                 "status": "done", "current_step": "done",
                 "result": "report 1", "iteration_round": 2,
                 "created_at": "2025-01-01", "updated_at": "2025-01-01"},
                {"id": "s-2", "wiki_id": "w1", "query": "q2",
                 "status": "planning", "current_step": "planning",
                 "result": None, "iteration_round": 0,
                 "created_at": "2025-01-02", "updated_at": "2025-01-02"},
            ]
            _create_source_db(source, sessions)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", str(data_dir),
                 "--apply"],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            assert "Migration complete" in result.stdout
            assert "copied 2 rows" in result.stdout

            # Verify target has the 2 rows
            target_ids = _read_target_session_ids(target)
            assert target_ids == {"s-1", "s-2"}

            # Verify backup was created
            backups = list(data_dir.glob(".llmwiki_agent.db.bak-*"))
            assert len(backups) == 1

    def test_idempotent_apply(self) -> None:
        """Re-running --apply on a target with the same data should
        not duplicate rows."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            source = data_dir / ".llmwiki_agent.db"
            target = data_dir / "autoresearch.db"
            _create_source_db(source, [
                {"id": "s-1", "wiki_id": "w1", "query": "q",
                 "status": "done", "created_at": "2025-01-01",
                 "updated_at": "2025-01-01"},
            ])

            # First run
            subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", str(data_dir),
                 "--apply"],
                capture_output=True, text=True, timeout=30,
            )
            # Second run
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", str(data_dir),
                 "--apply"],
                capture_output=True, text=True, timeout=30,
            )
            assert "Would skip:         1" in result.stdout
            # Still just 1 row
            target_ids = _read_target_session_ids(target)
            assert target_ids == {"s-1"}

    def test_handles_missing_source_db(self) -> None:
        """If the source DB doesn't exist, the script should report
        nothing-to-migrate without raising."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "autoresearch.db").touch()
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", tmp],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0
            assert "Nothing to migrate" in result.stdout

    def test_handles_source_without_research_sessions(self) -> None:
        """If the source DB exists but has no research_sessions
        table, the script should report nothing-to-migrate."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / ".llmwiki_agent.db").touch()
            # create a dummy table
            with sqlite3.connect(data_dir / ".llmwiki_agent.db") as conn:
                conn.execute("CREATE TABLE foo (id INTEGER)")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", str(data_dir)],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0
            assert "Nothing to migrate" in result.stdout

    def test_partial_overlap_skips_existing_copies_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            source = data_dir / ".llmwiki_agent.db"
            target = data_dir / "autoresearch.db"
            _create_source_db(source, [
                {"id": "s-1", "wiki_id": "w1", "query": "q1",
                 "status": "done", "created_at": "2025-01-01",
                 "updated_at": "2025-01-01"},
                {"id": "s-2", "wiki_id": "w1", "query": "q2",
                 "status": "planning", "created_at": "2025-01-02",
                 "updated_at": "2025-01-02"},
            ])

            # First apply: both copied
            subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", str(data_dir),
                 "--apply"],
                capture_output=True, text=True, timeout=30,
            )
            # Now add a new row to the source
            _create_source_db(source, [
                {"id": "s-3", "wiki_id": "w1", "query": "q3",
                 "status": "planning", "created_at": "2025-01-03",
                 "updated_at": "2025-01-03"},
            ] + [
                {"id": "s-1", "wiki_id": "w1", "query": "q1",
                 "status": "done", "created_at": "2025-01-01",
                 "updated_at": "2025-01-01"},  # already in target
            ])
            # Re-apply: should skip s-1, copy s-3
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--data-dir", str(data_dir),
                 "--apply"],
                capture_output=True, text=True, timeout=30,
            )
            target_ids = _read_target_session_ids(target)
            assert target_ids == {"s-1", "s-2", "s-3"}
            assert "copied 1 rows" in result.stdout


# ─── Direct test of the underlying functions ────────────────────


class TestMigrationFunctions:
    def test_migrate_research_sessions_dry_run(self) -> None:
        """Direct test of the migrate_research_sessions() function."""
        import sys
        sys.path.insert(0, str(SCRIPT.parent.parent))
        from scripts.migrate_db_v1_to_v2 import migrate_research_sessions

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            source = data_dir / ".llmwiki_agent.db"
            target = data_dir / "autoresearch.db"
            _create_source_db(source, [
                {"id": "s-1", "wiki_id": "w1", "query": "q1",
                 "status": "done", "created_at": "2025-01-01",
                 "updated_at": "2025-01-01"},
                {"id": "s-2", "wiki_id": "w1", "query": "q2",
                 "status": "planning", "created_at": "2025-01-02",
                 "updated_at": "2025-01-02"},
            ])
            summary = migrate_research_sessions(source, target, apply=False)
            assert summary["copied"] == 2
            assert summary["skipped"] == 0
            assert summary["errors"] == 0
            # Dry-run: target not touched
            assert _read_target_session_ids(target) == set()

    def test_backup_file_creates_timestamped_copy(self) -> None:
        import sys
        sys.path.insert(0, str(SCRIPT.parent.parent))
        from scripts.migrate_db_v1_to_v2 import backup_file

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.db"
            p.write_bytes(b"hello")
            backup = backup_file(p)
            assert backup.exists()
            assert backup.read_bytes() == b"hello"
            assert backup.name.startswith("test.db.bak-")
