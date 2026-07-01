"""Tests for reproduction.sessions."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.persist.sessions import (
    VALID_STATUSES,
    Artifact,
    ReproductionDatabase,
    Session,
)


@pytest.fixture
def db(tmp_path: Path) -> ReproductionDatabase:
    return ReproductionDatabase(db_path=tmp_path / "test.db")


def test_db_file_created(tmp_path: Path):
    path = tmp_path / "sub" / "x.db"
    ReproductionDatabase(db_path=path)
    assert path.exists()


def test_create_and_get_session(db: ReproductionDatabase):
    sid = db.create_session(
        wiki_id="w1",
        paper_id="paper-abc",
        source_type="pdf",
        source_ref="/tmp/x.pdf",
        symbol="600660.SH",
        start_date="2024-01-01",
        end_date="2024-02-28",
    )
    s = db.get_session(sid)
    assert s is not None
    assert s.id == sid
    assert s.paper_id == "paper-abc"
    assert s.symbol == "600660.SH"
    assert s.status == "pending"
    assert s.error is None


def test_get_session_missing_returns_none(db: ReproductionDatabase):
    assert db.get_session("does-not-exist") is None


def test_update_status_validates(db: ReproductionDatabase):
    sid = db.create_session("w", "p", "pdf", "r", "S", "2024-01-01", "2024-02-28")
    with pytest.raises(ValueError):
        db.update_status(sid, "bogus")


def test_update_status_persists(db: ReproductionDatabase):
    sid = db.create_session("w", "p", "pdf", "r", "S", "2024-01-01", "2024-02-28")
    db.update_status(sid, "extracting")
    assert db.get_session(sid).status == "extracting"
    db.update_status(sid, "backtesting")
    assert db.get_session(sid).status == "backtesting"


def test_update_status_records_error(db: ReproductionDatabase):
    sid = db.create_session("w", "p", "pdf", "r", "S", "2024-01-01", "2024-02-28")
    db.update_status(sid, "error", error="boom")
    s = db.get_session(sid)
    assert s.status == "error"
    assert s.error == "boom"


def test_update_status_records_signal_type_and_params(db: ReproductionDatabase):
    sid = db.create_session("w", "p", "pdf", "r", "S", "2024-01-01", "2024-02-28")
    db.update_status(
        sid,
        "backtesting",
        signal_type="ma_cross",
        signal_params={"fast": 5, "slow": 20},
    )
    s = db.get_session(sid)
    assert s.strategy_signal_type == "ma_cross"
    assert json.loads(s.strategy_params_json) == {"fast": 5, "slow": 20}


def test_record_event_and_get_events(db: ReproductionDatabase):
    sid = db.create_session("w", "p", "pdf", "r", "S", "2024-01-01", "2024-02-28")
    db.record_event(sid, "phase.start", phase="extracting")
    db.record_event(sid, "data.fetched", source="clickhouse", rows=22)
    events = db.get_events(sid)
    assert len(events) == 2
    assert events[0]["event_type"] == "phase.start"
    assert json.loads(events[0]["payload_json"])["phase"] == "extracting"
    assert json.loads(events[1]["payload_json"])["rows"] == 22


def test_create_artifact_and_get_artifacts(db: ReproductionDatabase):
    sid = db.create_session("w", "p", "pdf", "r", "S", "2024-01-01", "2024-02-28")
    aid = db.create_artifact(sid, "TradingStrategy", "trading/ma-cross", ref="abc")
    assert aid
    artifacts = db.get_artifacts(sid)
    assert len(artifacts) == 1
    a = artifacts[0]
    assert a.kind == "TradingStrategy"
    assert a.wiki_page == "trading/ma-cross"
    assert json.loads(a.meta_json)["ref"] == "abc"


def test_list_sessions_by_status(db: ReproductionDatabase):
    for i in range(3):
        sid = db.create_session("w", f"p{i}", "pdf", "r", "S", "2024-01-01", "2024-02-28")
        if i == 0:
            db.update_status(sid, "done")
    done = db.list_sessions(status="done")
    pending = db.list_sessions(status="pending")
    assert len(done) == 1
    assert len(pending) == 2


def test_independent_db_does_not_touch_main_app_db(tmp_path: Path, monkeypatch):
    """reproduction.db must not live in the same file as .llmwiki_agent.db."""
    target = tmp_path / "reproduction.db"
    db = ReproductionDatabase(db_path=target)
    sid = db.create_session("w", "p", "pdf", "r", "S", "2024-01-01", "2024-02-28")
    db.update_status(sid, "done")
    assert (tmp_path / "reproduction.db").exists()
    siblings = list(tmp_path.iterdir())
    assert all(".llmwiki_agent" not in p.name for p in siblings)


def test_valid_statuses_complete():
    assert {"pending", "extracting", "backtesting", "analyzing", "done", "error"} == VALID_STATUSES
