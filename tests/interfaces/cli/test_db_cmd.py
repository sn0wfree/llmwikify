"""Unit tests for ``interfaces/cli/commands/db.py``.

The helpers take an ``app_db`` and drive real sqlite queries, so the
tests build a real temp database rather than mocking — that exercises
the SQL and the rowcount/aggregation paths together.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.db import (
    _db_clean,
    _db_export,
    _db_list,
    _db_stats,
    _delete_wiki_data,
    _export_wiki_data,
    _get_db_stats,
    _get_wiki_stats,
    _list_all_wikis,
    _resolve_data_dir,
    run_db,
)

# ── Fixtures ────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, wiki_id TEXT);
CREATE TABLE chat_messages (id TEXT PRIMARY KEY, session_id TEXT);
CREATE TABLE tool_calls (id TEXT PRIMARY KEY, session_id TEXT);
CREATE TABLE autoresearch_sessions (id TEXT PRIMARY KEY, wiki_id TEXT);
CREATE TABLE autoresearch_sub_queries (id TEXT PRIMARY KEY, session_id TEXT);
CREATE TABLE autoresearch_sources (id TEXT PRIMARY KEY, session_id TEXT);
CREATE TABLE dream_proposals (id TEXT PRIMARY KEY, wiki_id TEXT);
CREATE TABLE notifications (id TEXT PRIMARY KEY, wiki_id TEXT);
CREATE TABLE confirmations (id TEXT PRIMARY KEY, wiki_id TEXT);
CREATE TABLE ingest_log (id TEXT PRIMARY KEY, wiki_id TEXT);
"""

SEED = """
INSERT INTO chat_sessions VALUES ('s1', 'w1'), ('s2', 'w1'), ('s3', 'w2');
INSERT INTO chat_messages VALUES ('m1', 's1'), ('m2', 's1'), ('m3', 's2');
INSERT INTO tool_calls VALUES ('t1', 's1'), ('t2', 's3');
INSERT INTO autoresearch_sessions VALUES ('a1', 'w1'), ('a2', 'w2');
INSERT INTO autoresearch_sub_queries VALUES ('q1', 'a1');
INSERT INTO autoresearch_sources VALUES ('src1', 'a1'), ('src2', 'a2');
INSERT INTO dream_proposals VALUES ('d1', 'w1');
INSERT INTO notifications VALUES ('n1', 'w1'), ('n2', 'w2');
INSERT INTO confirmations VALUES ('c1', 'w1');
INSERT INTO ingest_log VALUES ('i1', 'w1'), ('i2', 'w2');
"""


def _make_app_db(tmp_path: Path) -> SimpleNamespace:
    """A real sqlite file with the tables db.py queries, plus a stub app_db.

    Placed at the nested path ``_resolve_data_dir`` returns so the
    command wrappers' on-disk existence check passes.
    """
    db_path = tmp_path / ".llmwikify" / "agent" / ".llmwiki_agent.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.executescript(SEED)
        conn.commit()
    return SimpleNamespace(db_path=db_path)


@pytest.fixture
def app_db(tmp_path: Path) -> SimpleNamespace:
    return _make_app_db(tmp_path)


@pytest.fixture
def wiki_stub(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(root=tmp_path)


@pytest.fixture
def open_app_db(monkeypatch, app_db: SimpleNamespace):
    """Point the command wrappers at our seeded sqlite file.

    The real ``_open_app_db`` builds an ``AppDatabase`` (full schema
    init), which is unrelated to what ``db.py``'s own helpers query.
    """
    from llmwikify.interfaces.cli.commands import db as db_mod

    monkeypatch.setattr(db_mod, "_open_app_db", lambda wiki: app_db)
    return app_db


class TestResolveDataDir:
    def test_path_layout(self, wiki_stub: SimpleNamespace) -> None:
        p = _resolve_data_dir(wiki_stub)
        assert p == wiki_stub.root / ".llmwikify" / "agent"


class TestGetDbStats:
    def test_missing_db_returns_none(self, tmp_path: Path) -> None:
        assert _get_db_stats(SimpleNamespace(db_path=tmp_path / "nope.db")) is None

    def test_counts_every_table_and_size(self, app_db: SimpleNamespace) -> None:
        stats = _get_db_stats(app_db)
        assert stats is not None
        assert stats["tables"]["chat_sessions"] == 3
        assert stats["tables"]["chat_messages"] == 3
        assert stats["tables"]["autoresearch_sessions"] == 2
        assert stats["tables"]["dream_proposals"] == 1
        assert stats["size_mb"] >= 0.0

    def test_all_tables_listed(self, app_db: SimpleNamespace) -> None:
        stats = _get_db_stats(app_db)
        expected = {
            "chat_sessions",
            "chat_messages",
            "tool_calls",
            "autoresearch_sessions",
            "autoresearch_sub_queries",
            "autoresearch_sources",
            "dream_proposals",
            "notifications",
            "confirmations",
            "ingest_log",
        }
        assert expected.issubset(set(stats["tables"]))


class TestGetWikiStats:
    def test_aggregates_both_wikis(self, app_db: SimpleNamespace) -> None:
        s = _get_wiki_stats(app_db, "w1")
        assert s["wiki_id"] == "w1"
        assert s["chat_sessions"] == 2
        assert s["research_sessions"] == 1
        assert s["research_sources"] == 1
        assert s["tool_calls"] == 1  # only t1 (session s1) belongs to w1
        assert s["dream_proposals"] == 1
        assert s["notifications"] == 1
        assert s["confirmations"] == 1
        assert s["ingest_log"] == 1

    def test_unknown_wiki_is_all_zero(self, app_db: SimpleNamespace) -> None:
        s = _get_wiki_stats(app_db, "nope")
        for k, v in s.items():
            if k != "wiki_id":
                assert v == 0, k

    def test_missing_tables_degrade_to_zero(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE chat_sessions (id TEXT, wiki_id TEXT)")
            conn.execute("INSERT INTO chat_sessions VALUES ('s','w1')")
            conn.commit()
        s = _get_wiki_stats(SimpleNamespace(db_path=db_path), "w1")
        assert s["chat_sessions"] == 1
        # every other table is missing → caught → 0
        assert s["research_sessions"] == 0
        assert s["dream_proposals"] == 0


class TestListAllWikis:
    def test_dedupes_and_sorts(self, app_db: SimpleNamespace) -> None:
        wikis = _list_all_wikis(app_db)
        ids = [w["wiki_id"] for w in wikis]
        assert ids == ["w1", "w2"]

    def test_empty_db_returns_empty(self, tmp_path: Path) -> None:
        db_path = tmp_path / "none.db"
        with sqlite3.connect(db_path) as conn:
            conn.commit()
        assert _list_all_wikis(SimpleNamespace(db_path=db_path)) == []


class TestDeleteWikiData:
    def test_cascades_across_facades(self, app_db: SimpleNamespace) -> None:
        result = _delete_wiki_data(app_db, "w1")
        assert result["chat_sessions"] == 2
        assert result["chat_messages"] == 3  # m1,m2 from s1,s2
        assert result["autoresearch_sessions"] == 1
        assert result["dream_proposals"] == 1
        # w2 untouched
        assert _get_wiki_stats(app_db, "w2")["chat_sessions"] == 1

    def test_missing_tables_skip_not_raise(self, tmp_path: Path) -> None:
        db_path = tmp_path / "bare.db"
        with sqlite3.connect(db_path) as conn:
            conn.commit()
        # every table missing — should not raise
        result = _delete_wiki_data(SimpleNamespace(db_path=db_path), "w1")
        assert isinstance(result, dict)


class TestExportWikiData:
    def test_returns_json_serialisable_shape(self, app_db: SimpleNamespace) -> None:
        data = _export_wiki_data(app_db, "w1")
        for key in (
            "chat_sessions",
            "chat_messages",
            "research_sessions",
            "tool_calls",
            "dream_proposals",
            "notifications",
            "confirmations",
            "ingest_log",
        ):
            assert key in data, key
            assert isinstance(data[key], list)
        # must survive json round-trip (dict(row) of sqlite3.Row is plain)
        json.dumps(data, default=str)

    def test_unknown_wiki_yields_empty_lists(self, app_db: SimpleNamespace) -> None:
        data = _export_wiki_data(app_db, "nope")
        assert all(v == [] for v in data.values())


# ── command wrappers ────────────────────────────────────────────────


class TestDbStatsCommand:
    def test_missing_db_exits_1(self, wiki_stub: SimpleNamespace, capsys) -> None:
        rc = _db_stats(wiki_stub, SimpleNamespace(wiki_id=None))
        assert rc == 1
        assert "No agent database found" in capsys.readouterr().out

    def test_all_tables_printed(
        self, wiki_stub: SimpleNamespace, open_app_db, capsys
    ) -> None:
        # place the db where _db_stats expects it
        target = _resolve_data_dir(wiki_stub) / ".llmwiki_agent.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(open_app_db.db_path.read_bytes())
        rc = _db_stats(wiki_stub, SimpleNamespace(wiki_id=None))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Database Statistics" in out
        assert "chat_sessions" in out

    def test_wiki_id_branch(
        self, wiki_stub: SimpleNamespace, open_app_db, capsys
    ) -> None:
        target = _resolve_data_dir(wiki_stub) / ".llmwiki_agent.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(open_app_db.db_path.read_bytes())
        rc = _db_stats(wiki_stub, SimpleNamespace(wiki_id="w1"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Wiki: w1" in out
        assert "Chat sessions" in out


class TestDbListCommand:
    def test_missing_db_exits_1(self, wiki_stub: SimpleNamespace, capsys) -> None:
        assert _db_list(wiki_stub, SimpleNamespace()) == 1

    def test_no_wikis_message(self, wiki_stub: SimpleNamespace, open_app_db, capsys, monkeypatch) -> None:
        from llmwikify.interfaces.cli.commands import db as db_mod

        target = _resolve_data_dir(wiki_stub) / ".llmwiki_agent.db"
        # keep the on-disk check happy, but return no wikis
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as conn:
            conn.commit()
        monkeypatch.setattr(db_mod, "_list_all_wikis", lambda _db: [])
        rc = _db_list(wiki_stub, SimpleNamespace())
        assert rc == 0
        assert "No wikis found" in capsys.readouterr().out

    def test_lists_both_wikis(
        self, wiki_stub: SimpleNamespace, open_app_db, capsys
    ) -> None:
        target = _resolve_data_dir(wiki_stub) / ".llmwiki_agent.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(open_app_db.db_path.read_bytes())
        rc = _db_list(wiki_stub, SimpleNamespace())
        assert rc == 0
        out = capsys.readouterr().out
        assert "w1" in out and "w2" in out


class TestDbCleanCommand:
    def test_missing_db_exits_1(
        self, wiki_stub: SimpleNamespace, capsys
    ) -> None:
        rc = _db_clean(wiki_stub, SimpleNamespace(wiki_id="w1", force=True))
        assert rc == 1

    def test_cancel_without_force(self, wiki_stub: SimpleNamespace, capsys) -> None:
        import builtins

        target = _resolve_data_dir(wiki_stub) / ".llmwiki_agent.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as conn:
            conn.commit()
        orig = builtins.input
        builtins.input = lambda *_a, **_k: "no"
        try:
            rc = _db_clean(wiki_stub, SimpleNamespace(wiki_id="w1", force=False))
        finally:
            builtins.input = orig
        assert rc == 0
        assert "Cancelled" in capsys.readouterr().out

    def test_force_deletes(self, wiki_stub: SimpleNamespace, open_app_db) -> None:
        # `_open_app_db` is patched to return open_app_db, so the command
        # mutates that db — assert on it directly.
        rc = _db_clean(wiki_stub, SimpleNamespace(wiki_id="w1", force=True))
        assert rc == 0
        with sqlite3.connect(open_app_db.db_path) as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM chat_sessions WHERE wiki_id='w1'"
            ).fetchone()[0]
        assert n == 0


class TestDbExportCommand:
    def test_missing_db_exits_1(self, wiki_stub: SimpleNamespace) -> None:
        assert _db_export(wiki_stub, SimpleNamespace(wiki_id="w1", output="x.json")) == 1

    def test_writes_json(
        self, wiki_stub: SimpleNamespace, open_app_db, tmp_path: Path
    ) -> None:
        target = _resolve_data_dir(wiki_stub) / ".llmwiki_agent.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(open_app_db.db_path.read_bytes())
        out = tmp_path / "out.json"
        rc = _db_export(wiki_stub, SimpleNamespace(wiki_id="w1", output=str(out)))
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["chat_sessions"]


class TestRunDbDispatcher:
    def test_unknown_subcommand(self, wiki_stub: SimpleNamespace, capsys) -> None:
        rc = run_db(wiki_stub, SimpleNamespace(db_subcommand="bogus"))
        assert rc == 1
        assert "Unknown db subcommand" in capsys.readouterr().out

    def test_defaults_to_stats(self, wiki_stub: SimpleNamespace, open_app_db, capsys) -> None:
        # missing db_subcommand → dispatches to _db_stats
        rc = run_db(wiki_stub, SimpleNamespace())
        assert rc == 0
        assert "Database Statistics" in capsys.readouterr().out

    def test_list_dispatch(self, wiki_stub: SimpleNamespace) -> None:
        assert run_db(wiki_stub, SimpleNamespace(db_subcommand="list")) == 1
