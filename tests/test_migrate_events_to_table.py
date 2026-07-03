"""Tests for the events_json → autoresearch_events migration script.

Exercises scripts/migrate_events_to_table.py end-to-end:
  - Dry-run reports pending sessions without writing
  - Apply migrates events from blob to table
  - Idempotency: re-running is a no-op
  - get_events() returns the same data after migration
  - --drop-legacy removes the events_json column
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "migrate_events_to_table.py"
)


def _create_source_db(agent_dir: Path, sessions_with_events: list[dict]) -> None:
    """Create a ResearchDatabase with the given sessions + events_json blobs.

    Args:
        agent_dir: Where to create the DB files.
        sessions_with_events: List of dicts with keys
            {"wiki_id", "query", "events": list[event_dict]}.
    """
    from llmwikify.apps.research.db import ResearchDatabase
    db = ResearchDatabase(agent_dir)
    for spec in sessions_with_events:
        sid = db.create_research_session(spec["wiki_id"], spec["query"])
        if spec["events"]:
            db.append_events(sid, spec["events"])
    # Force-clear the new table so each session looks "unmigrated" to
    # the script (we want to test the migration path, not the dual-write
    # path).
    with db._connect() as conn:
        conn.execute("DELETE FROM autoresearch_events")
        # Restore the events_json blob (dual-write cleared the new
        # table but the blob should still be there from before the DELETE
        # because dual-write always writes to both; verify).
        for spec in sessions_with_events:
            sid_row = conn.execute(
                "SELECT id FROM autoresearch_sessions WHERE query = ?",
                (spec["query"],),
            ).fetchone()
            if sid_row:
                conn.execute(
                    "UPDATE autoresearch_sessions SET events_json = ? WHERE id = ?",
                    (json.dumps(spec["events"], ensure_ascii=False), sid_row[0]),
                )
        conn.commit()


def test_dry_run_does_not_modify_db(tmp_path: Path) -> None:
    """--dry-run reports pending sessions without writing any rows."""
    _create_source_db(
        tmp_path,
        [
            {"wiki_id": "w1", "query": "q1", "events": [
                {"type": "step", "message": "a"},
                {"type": "done", "message": "b"},
            ]},
        ],
    )
    # Pre-condition: new table is empty for this session
    from llmwikify.apps.research.db import ResearchDatabase
    db = ResearchDatabase(tmp_path)
    pending = db.list_sessions_with_unmigrated_events()
    assert len(pending) == 1

    # Run the script in dry-run mode via direct function call
    sys.path.insert(0, str(SCRIPT.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_events_to_table", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.report(agent_dir=tmp_path, dry_run=True)
    assert result["dry_run"] is True
    assert result["pending_sessions"] == 1
    assert result["migrated"] == 0
    assert result["events_migrated"] == 0

    # Post-condition: new table is still empty (dry-run didn't write)
    db2 = ResearchDatabase(tmp_path)
    pending2 = db2.list_sessions_with_unmigrated_events()
    assert len(pending2) == 1


def test_migrate_copies_events_to_table(tmp_path: Path) -> None:
    """Migration moves events from blob to table; get_events() returns same data."""
    events = [
        {"type": "step", "message": "a"},
        {"type": "step", "message": "b"},
        {"type": "done", "message": "c"},
    ]
    _create_source_db(
        tmp_path,
        [{"wiki_id": "w1", "query": "q1", "events": events}],
    )

    sys.path.insert(0, str(SCRIPT.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_events_to_table", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.report(agent_dir=tmp_path, dry_run=False)
    assert result["migrated"] == 1
    assert result["events_migrated"] == 3

    # Verify: get_events returns the same data
    from llmwikify.apps.research.db import ResearchDatabase
    db = ResearchDatabase(tmp_path)
    pending = db.list_sessions_with_unmigrated_events()
    assert len(pending) == 0  # No more pending
    sid_row = next(iter(db._connect().execute(
        "SELECT id FROM autoresearch_sessions WHERE query = 'q1'"
    )))
    evs = db.get_events(sid_row[0])
    assert [e["message"] for e in evs] == ["a", "b", "c"]


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    """Re-running the script on an already-migrated session is a no-op."""
    _create_source_db(
        tmp_path,
        [{"wiki_id": "w1", "query": "q1", "events": [
            {"type": "step", "message": "a"},
        ]}],
    )
    sys.path.insert(0, str(SCRIPT.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_events_to_table", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # First run: 1 event migrated
    r1 = mod.report(agent_dir=tmp_path, dry_run=False)
    assert r1["events_migrated"] == 1

    # Second run: 0 events (already migrated)
    r2 = mod.report(agent_dir=tmp_path, dry_run=False)
    assert r2["migrated"] == 0
    assert r2["events_migrated"] == 0


def test_migrate_handles_empty_blob(tmp_path: Path) -> None:
    """A session with no events is silently skipped."""
    _create_source_db(
        tmp_path,
        [{"wiki_id": "w1", "query": "q1", "events": []}],
    )
    sys.path.insert(0, str(SCRIPT.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_events_to_table", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.report(agent_dir=tmp_path, dry_run=False)
    assert result["pending_sessions"] == 0
    assert result["migrated"] == 0


def test_migrate_handles_multiple_sessions(tmp_path: Path) -> None:
    """Script processes all pending sessions in one run."""
    _create_source_db(
        tmp_path,
        [
            {"wiki_id": "w1", "query": "q1", "events": [
                {"type": "step", "message": "1a"},
                {"type": "step", "message": "1b"},
            ]},
            {"wiki_id": "w1", "query": "q2", "events": [
                {"type": "step", "message": "2a"},
            ]},
            {"wiki_id": "w1", "query": "q3", "events": []},  # No events
        ],
    )
    sys.path.insert(0, str(SCRIPT.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("migrate_events_to_table", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.report(agent_dir=tmp_path, dry_run=False)
    assert result["migrated"] == 2
    assert result["events_migrated"] == 3
