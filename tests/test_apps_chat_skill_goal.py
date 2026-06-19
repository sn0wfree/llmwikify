"""Tests for goal_skill — Phase 8 long_task / complete_goal SkillActions.

Covers:
  - start_long_task writes goal_state to chat_sessions.metadata
  - duplicate start_long_task fails (must complete_goal first)
  - complete_goal flips status + stores recap
  - complete_goal no-op when no active goal
  - get_goal returns active=True/False correctly
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from llmwikify.apps.chat.agent.goal_state import (
    GOAL_STATE_KEY,
    parse_goal_state,
)
from llmwikify.apps.chat.skills.base import SkillContext
from llmwikify.apps.chat.skills.crud.goal_skill import goal_skill


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def chat_db(tmp_path: Path):
    """Build a real ChatDatabase with a temp SQLite file."""
    from llmwikify.apps.chat.db._facade import ChatDatabase

    db = ChatDatabase(tmp_path)
    return db


@pytest.fixture
def session_id(chat_db) -> str:
    return chat_db.create_chat_session(wiki_id="default")


def _ctx(chat_db, session_id: str) -> SkillContext:
    return SkillContext(db=chat_db, session_id=session_id, config={})


def test_start_long_task_persists_goal_state(chat_db, session_id) -> None:
    handler = goal_skill.actions["start_long_task"].handler
    result = _run(handler(
        {"goal": "Research X over 3 turns", "ui_summary": "Research X"},
        _ctx(chat_db, session_id),
    ))
    assert result.status == "ok"
    assert result.data["registered"] is True
    metadata = chat_db.get_session_metadata(session_id)
    blob = parse_goal_state(metadata.get(GOAL_STATE_KEY))
    assert blob is not None
    assert blob["status"] == "active"
    assert blob["objective"] == "Research X over 3 turns"
    assert blob["ui_summary"] == "Research X"
    assert blob["started_at"]


def test_start_long_task_rejects_when_active(chat_db, session_id) -> None:
    handler = goal_skill.actions["start_long_task"].handler
    _run(handler({"goal": "first"}, _ctx(chat_db, session_id)))
    result = _run(handler({"goal": "second"}, _ctx(chat_db, session_id)))
    assert result.status == "error"
    assert "active" in (result.error or "").lower()
    # Still has the original goal
    blob = parse_goal_state(chat_db.get_session_metadata(session_id).get(GOAL_STATE_KEY))
    assert blob["objective"] == "first"


def test_start_long_task_requires_goal(chat_db, session_id) -> None:
    handler = goal_skill.actions["start_long_task"].handler
    result = _run(handler({"goal": "   "}, _ctx(chat_db, session_id)))
    assert result.status == "error"
    assert "goal is required" in (result.error or "").lower()


def test_complete_goal_flips_status_and_records_recap(chat_db, session_id) -> None:
    start = goal_skill.actions["start_long_task"].handler
    complete = goal_skill.actions["complete_goal"].handler
    _run(start({"goal": "do the thing"}, _ctx(chat_db, session_id)))
    result = _run(complete({"recap": "done with caveat"}, _ctx(chat_db, session_id)))
    assert result.status == "ok"
    assert result.data["completed"] is True
    assert result.data["recap"] == "done with caveat"
    blob = parse_goal_state(chat_db.get_session_metadata(session_id).get(GOAL_STATE_KEY))
    assert blob["status"] == "completed"
    assert blob["completed_at"]
    assert blob["recap"] == "done with caveat"


def test_complete_goal_noop_when_no_active(chat_db, session_id) -> None:
    handler = goal_skill.actions["complete_goal"].handler
    result = _run(handler({}, _ctx(chat_db, session_id)))
    assert result.status == "ok"
    assert result.data["completed"] is False


def test_get_goal_reflects_state(chat_db, session_id) -> None:
    start = goal_skill.actions["start_long_task"].handler
    get_goal = goal_skill.actions["get_goal"].handler
    out_inactive = _run(get_goal({}, _ctx(chat_db, session_id)))
    assert out_inactive.data["active"] is False
    _run(start({"goal": "g1"}, _ctx(chat_db, session_id)))
    out_active = _run(get_goal({}, _ctx(chat_db, session_id)))
    assert out_active.data["active"] is True
    assert out_active.data["goal"]["objective"] == "g1"


def test_after_complete_a_new_long_task_can_be_started(chat_db, session_id) -> None:
    start = goal_skill.actions["start_long_task"].handler
    complete = goal_skill.actions["complete_goal"].handler
    _run(start({"goal": "first"}, _ctx(chat_db, session_id)))
    _run(complete({"recap": "done"}, _ctx(chat_db, session_id)))
    result = _run(start({"goal": "second"}, _ctx(chat_db, session_id)))
    assert result.status == "ok"
    blob = parse_goal_state(chat_db.get_session_metadata(session_id).get(GOAL_STATE_KEY))
    assert blob["status"] == "active"
    assert blob["objective"] == "second"


def test_start_requires_session_id_when_ctx_empty(chat_db) -> None:
    handler = goal_skill.actions["start_long_task"].handler
    ctx = SkillContext(db=chat_db, session_id="", config={})
    result = _run(handler({"goal": "x"}, ctx))
    assert result.status == "error"
    assert "session_id" in (result.error or "").lower()


def test_skill_registered_in_default_service() -> None:
    from llmwikify.apps.chat.skills.service import SkillService

    svc = SkillService()
    svc.register_all()
    skill = svc.get_skill("goal")
    assert skill is not None
    assert "start_long_task" in skill.actions
    assert "complete_goal" in skill.actions
    assert "get_goal" in skill.actions
