"""Tests for scripts/migrate_autoresearch_v3_to_v4.py.

Verifies the migration audit script:
- reports production DB state correctly
- exits 0 when no migration is needed
- would drop legacy columns when present (--apply path)
- creates a backup before applying
- --json output is well-formed

The script supports LLMWIKIFY_AGENT_DIR env var to redirect the
agent directory (used here to avoid touching the real ~/.llmwikify/agent).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "migrate_autoresearch_v3_to_v4.py"


def _make_legacy_db(path: Path) -> None:
    """Create a fake .llmwiki_agent.db with 3 legacy autoresearch columns."""
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE research_sessions (
                id TEXT PRIMARY KEY,
                wiki_id TEXT, query TEXT, status TEXT,
                clarification_json TEXT, reasoning_json TEXT, structure_json TEXT
            )"""
        )
        conn.execute("CREATE TABLE chat_sessions (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE ppt_tasks (id TEXT PRIMARY KEY)")
        conn.execute(
            """CREATE TABLE research_sub_queries (
                id TEXT PRIMARY KEY, session_id TEXT, query TEXT, source_type TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE research_sources (
                id TEXT PRIMARY KEY, session_id TEXT, source_type TEXT
            )"""
        )
        conn.commit()


@pytest.fixture
def fake_agent(tmp_path, monkeypatch):
    """Create a fake agent dir and set LLMWIKIFY_AGENT_DIR to point to it."""
    agent = tmp_path / "agent"
    agent.mkdir(parents=True)
    monkeypatch.setenv("LLMWIKIFY_AGENT_DIR", str(agent))
    return agent


def _run_script(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
        env=env,
    )


def test_script_exists():
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    src = SCRIPT.read_text()
    assert "report(" in src
    assert "migrate_research_six_step_columns" in src


def test_clean_db_exits_0(fake_agent, monkeypatch):
    """No migration needed → exit 0."""
    import os
    with sqlite3.connect(fake_agent / ".llmwiki_agent.db") as conn:
        conn.execute(
            "CREATE TABLE research_sessions (id TEXT PRIMARY KEY, query TEXT)"
        )
        conn.commit()
    env = os.environ.copy()
    env["LLMWIKIFY_AGENT_DIR"] = str(fake_agent)
    result = _run_script(env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "No migration needed" in combined


def test_json_output_is_well_formed(fake_agent):
    import os
    _make_legacy_db(fake_agent / ".llmwiki_agent.db")
    env = os.environ.copy()
    env["LLMWIKIFY_AGENT_DIR"] = str(fake_agent)
    result = _run_script("--json", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert "needs_migration" in data
    assert data["needs_migration"] is True
    assert "clarification_json" in data["legacy_columns_present"]
    assert data["research_sessions_columns"]


def test_apply_drops_columns_and_creates_backup(fake_agent):
    import os
    _make_legacy_db(fake_agent / ".llmwiki_agent.db")
    env = os.environ.copy()
    env["LLMWIKIFY_AGENT_DIR"] = str(fake_agent)
    result = _run_script("--apply", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    # Columns dropped
    with sqlite3.connect(fake_agent / ".llmwiki_agent.db") as conn:
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(research_sessions)").fetchall()
        }
    assert "clarification_json" not in cols
    assert "reasoning_json" not in cols
    assert "structure_json" not in cols
    # Backup file created
    backups = list(fake_agent.glob(".llmwiki_agent.db.bak.pre-v4-migration-*"))
    assert len(backups) == 1, f"expected 1 backup, got {backups}"
    # Backup has the legacy columns (proves it was a real backup, not a copy
    # done after the drop)
    with sqlite3.connect(backups[0]) as conn:
        bcols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(research_sessions)").fetchall()
        }
    assert "clarification_json" in bcols


def test_dry_run_does_not_modify_db(fake_agent):
    import os
    _make_legacy_db(fake_agent / ".llmwiki_agent.db")
    env = os.environ.copy()
    env["LLMWIKIFY_AGENT_DIR"] = str(fake_agent)
    result = _run_script(env=env)
    # Default is dry-run, no --apply
    assert result.returncode == 0, result.stdout + result.stderr
    # Columns should still be present
    with sqlite3.connect(fake_agent / ".llmwiki_agent.db") as conn:
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(research_sessions)").fetchall()
        }
    assert "clarification_json" in cols
    # No backup
    backups = list(fake_agent.glob(".llmwiki_agent.db.bak.pre-v4-migration-*"))
    assert backups == []


def test_detects_clarifying_status_sessions(fake_agent):
    """A session with status=clarifying should trigger migration need."""
    import os
    with sqlite3.connect(fake_agent / ".llmwiki_agent.db") as conn:
        conn.execute(
            """CREATE TABLE research_sessions (
                id TEXT PRIMARY KEY, status TEXT DEFAULT 'clarifying'
            )"""
        )
        conn.execute(
            "INSERT INTO research_sessions (id, status) VALUES ('s1', 'clarifying')"
        )
        conn.commit()
    env = os.environ.copy()
    env["LLMWIKIFY_AGENT_DIR"] = str(fake_agent)
    result = _run_script("--json", env=env)
    data = json.loads(result.stdout)
    assert data["needs_migration"] is True
    assert data["sessions_with_clarifying_status"] == 1


def test_report_function_directly(fake_agent):
    """Direct call to report() returns the expected dict shape."""
    _make_legacy_db(fake_agent / ".llmwiki_agent.db")
    spec = importlib.util.spec_from_file_location(
        "migrate_script", str(SCRIPT)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = mod.report(agent_dir=fake_agent)
    assert data["legacy_columns_present"] == [
        "clarification_json", "reasoning_json", "structure_json",
    ]
    assert data["needs_migration"] is True
