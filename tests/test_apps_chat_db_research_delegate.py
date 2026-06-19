"""Tests for ResearchDelegate (27 thin delegates to ResearchDatabase).

These are 1-line forwarders — the test just verifies the facade
still works end-to-end (i.e. delegates correctly forward).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.db import ChatDatabase, ResearchDelegate


@pytest.fixture
def delegate(tmp_path: Path) -> ResearchDelegate:
    return ResearchDelegate(tmp_path)


# ─── facade integration (uses ChatDatabase to access delegate) ──


@pytest.fixture
def db(tmp_path: Path) -> ChatDatabase:
    return ChatDatabase(tmp_path)


# ─── Sessions (8) ───────────────────────────────────────────────


class TestSessions:
    def test_create_and_get(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w1", query="q")
        session = db.get_research_session(sid)
        assert session is not None
        assert session["wiki_id"] == "w1"
        assert session["query"] == "q"

    def test_list_research_sessions(self, db: ChatDatabase) -> None:
        db.create_research_session(wiki_id="w1", query="q1")
        db.create_research_session(wiki_id="w1", query="q2")
        sessions = db.list_research_sessions(wiki_id="w1")
        assert len(sessions) == 2

    def test_update_status(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.update_research_status(sid, "running", step="step1")
        session = db.get_research_session(sid)
        assert session["status"] == "running"

    def test_update_progress(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.update_research_progress(sid, 0.5)
        session = db.get_research_session(sid)
        assert session["progress"] == 0.5

    def test_persist_report(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.persist_report(sid, '{"result": "ok"}')
        session = db.get_research_session(sid)
        # persist_report stores into the 'result' column
        assert session["result"] == '{"result": "ok"}'

    def test_finalize_research(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.finalize_research(sid, "result", "page-name")
        session = db.get_research_session(sid)
        # Status becomes 'done' after finalize
        assert session["status"] == "done"
        # wiki_page_name is persisted
        assert session["wiki_page_name"] == "page-name"

    def test_delete_research(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        assert db.delete_research(sid) is True
        assert db.get_research_session(sid) is None


# ─── Six-step fields (2) ────────────────────────────────────────


class TestSixStep:
    def test_update_and_get(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.update_six_step_fields(
            sid, clarification={"q": "what"},
            reasoning={"step": "think"},
        )
        fields = db.get_six_step_fields(sid)
        assert fields["clarification"] == {"q": "what"}
        assert fields["reasoning"] == {"step": "think"}


# ─── Steps (5) ─────────────────────────────────────────────────


class TestSteps:
    def test_save_and_get_step(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.save_step(sid, 1, "action1", status="completed", thought="think")
        step = db.get_step(sid, 1)
        assert step is not None
        assert step["action"] == "action1"

    def test_list_steps(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.save_step(sid, 1, "a")
        db.save_step(sid, 2, "b")
        steps = db.list_steps(sid)
        assert len(steps) == 2

    def test_update_step_status(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.save_step(sid, 1, "a", status="pending")
        db.update_step_status(sid, 1, "running")
        step = db.get_step(sid, 1)
        assert step["status"] == "running"

    def test_delete_steps(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.save_step(sid, 1, "a")
        db.save_step(sid, 2, "b")
        n = db.delete_steps(sid)
        assert n == 2

    def test_save_and_load_research_state(self, db: ChatDatabase) -> None:
        sid = db.create_research_session(wiki_id="w", query="q")
        db.save_research_state(sid, 1, {"key": "value"})
        loaded = db.load_research_state(sid, 1)
        assert loaded is not None
        assert loaded["key"] == "value"
