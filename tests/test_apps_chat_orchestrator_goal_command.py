"""Phase 8 (2026-06-20): /goal slash command tests.

Covers:
  - /goal registered as prefix command in default router
  - /goal (no args) → reports no active goal when DB returns empty metadata
  - /goal <objective> → registers active goal via GoalSkill (writes metadata)
  - /goal done <recap> → completes active goal
  - /goal returns ok=False when no session_id is supplied (skill error path)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_orchestrator(db: MagicMock | None = None):
    from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator

    orch = ChatOrchestrator.__new__(ChatOrchestrator)
    orch.db = db or MagicMock()
    orch.command_router = ChatOrchestrator._build_default_command_router(orch)
    return orch


def _make_chat_db_facade() -> MagicMock:
    """Return a fake ChatDatabase facade with metadata helpers."""
    db = MagicMock()
    # In-memory store keyed by session_id
    store: dict[str, dict] = {}

    def _get(sid: str) -> dict:
        return dict(store.get(sid, {}))

    def _update(sid: str, **kwargs):
        store.setdefault(sid, {}).update(kwargs)

    db.get_session_metadata = _get
    db.update_session_metadata = _update
    return db


def test_goal_registered_in_default_router() -> None:
    orch = _make_orchestrator()
    assert orch.command_router.is_command("/goal")
    assert orch.command_router.is_command("/goal foo bar")
    assert orch.command_router.is_command("/GOAL ack")


@pytest.mark.asyncio
async def test_goal_no_args_reports_inactive_when_metadata_empty() -> None:
    db = _make_chat_db_facade()
    orch = _make_orchestrator(db)
    events = []
    async for ev in orch._dispatch_command(
        text="/goal",
        session_id="s1",
        wiki_id=None,
        db=db,
        ctx=None,
        abort_event=None,
    ):
        events.append(ev)
    assert len(events) == 2
    assert events[0]["type"] == "command_done"
    assert events[0]["command"] == "/goal"
    assert events[0]["ok"] is True
    assert events[0]["data"]["active"] is False


@pytest.mark.asyncio
async def test_goal_with_objective_registers_active_goal() -> None:
    db = _make_chat_db_facade()
    orch = _make_orchestrator(db)
    events = []
    async for ev in orch._dispatch_command(
        text="/goal Build the new dashboard",
        session_id="s1",
        wiki_id=None,
        db=db,
        ctx=None,
        abort_event=None,
    ):
        events.append(ev)
    assert events[0]["ok"] is True
    assert events[0]["data"]["registered"] is True
    assert events[0]["data"]["objective"] == "Build the new dashboard"
    # Verify metadata was actually written via the facade
    md = db.get_session_metadata("s1")
    assert "goal_state" in md
    assert md["goal_state"]["status"] == "active"


@pytest.mark.asyncio
async def test_goal_done_completes_active_goal() -> None:
    db = _make_chat_db_facade()
    orch = _make_orchestrator(db)
    # First, register a goal
    async for _ in orch._dispatch_command(
        text="/goal Investigate flaky test",
        session_id="s1",
        wiki_id=None,
        db=db,
        ctx=None,
        abort_event=None,
    ):
        pass
    # Now complete it
    events = []
    async for ev in orch._dispatch_command(
        text="/goal done found root cause in fixture",
        session_id="s1",
        wiki_id=None,
        db=db,
        ctx=None,
        abort_event=None,
    ):
        events.append(ev)
    assert events[0]["ok"] is True
    assert events[0]["data"]["completed"] is True
    assert events[0]["data"]["recap"] == "found root cause in fixture"
    md = db.get_session_metadata("s1")
    assert md["goal_state"]["status"] == "completed"


@pytest.mark.asyncio
async def test_goal_done_without_active_goal_reports_no_active() -> None:
    db = _make_chat_db_facade()
    orch = _make_orchestrator(db)
    events = []
    async for ev in orch._dispatch_command(
        text="/goal done nothing was happening",
        session_id="s1",
        wiki_id=None,
        db=db,
        ctx=None,
        abort_event=None,
    ):
        events.append(ev)
    assert events[0]["ok"] is True
    assert events[0]["data"]["completed"] is False


@pytest.mark.asyncio
async def test_goal_without_session_id_fails_gracefully() -> None:
    db = _make_chat_db_facade()
    orch = _make_orchestrator(db)
    events = []
    async for ev in orch._dispatch_command(
        text="/goal Build something",
        session_id=None,
        wiki_id=None,
        db=db,
        ctx=None,
        abort_event=None,
    ):
        events.append(ev)
    assert events[0]["ok"] is False
    assert "session_id" in events[0]["message"].lower()
