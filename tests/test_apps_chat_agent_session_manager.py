"""Tests for SessionManager (Phase 5 extraction)."""
from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.chat.agent.session_manager import SessionManager

# ── Stubs ───────────────────────────────────────────────────────


class _FakeDB:
    """In-memory chat DB stub with the methods SessionManager uses."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.reverted: list[tuple[str, str]] = []
        self.edited: list[tuple[str, str]] = []
        self._sessions: set[str] = set()

    def delete_chat_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            self._sessions.remove(session_id)
        self.deleted.append(session_id)
        return True

    def revert_to_message(self, session_id: str, message_id: str) -> int:
        self.reverted.append((session_id, message_id))
        return 3  # pretend 3 rows reverted

    def update_chat_message(self, message_id: str, content: str) -> bool:
        self.edited.append((message_id, content))
        return True


class _FakeContextManager:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def remove(self, session_id: str) -> None:
        self.removed.append(session_id)


def _make_mgr() -> tuple[SessionManager, _FakeDB, _FakeContextManager]:
    db = _FakeDB()
    ctx = _FakeContextManager()
    status: dict[str, str] = {}
    aborts: dict[str, asyncio.Event] = {}
    mgr = SessionManager(
        db=db, context_manager=ctx,
        session_status=status, abort_events=aborts,
    )
    return mgr, db, ctx


# ── delete_session ───────────────────────────────────────────────


class TestDeleteSession:
    def test_evicts_context_and_deletes_db_row(self) -> None:
        mgr, db, ctx = _make_mgr()
        assert mgr.delete_session("s1") is True
        assert ctx.removed == ["s1"]
        assert db.deleted == ["s1"]

    def test_delete_is_idempotent(self) -> None:
        mgr, db, ctx = _make_mgr()
        mgr.delete_session("s1")
        mgr.delete_session("s1")
        assert db.deleted == ["s1", "s1"]
        assert ctx.removed == ["s1", "s1"]


# ── revert_session ───────────────────────────────────────────────


class TestRevertSession:
    def test_returns_row_count_and_evicts_context(self) -> None:
        mgr, db, ctx = _make_mgr()
        count = mgr.revert_session("s1", "m1")
        assert count == 3
        assert db.reverted == [("s1", "m1")]
        assert ctx.removed == ["s1"]


# ── edit_message ─────────────────────────────────────────────────


class TestEditMessage:
    def test_delegates_to_db(self) -> None:
        mgr, db, _ = _make_mgr()
        assert mgr.edit_message("m1", "new content") is True
        assert db.edited == [("m1", "new content")]


# ── abort_session ────────────────────────────────────────────────


class TestAbortSession:
    def test_returns_false_when_not_busy(self) -> None:
        mgr, _db, _ctx = _make_mgr()
        # status dict is empty
        assert mgr.abort_session("s1") is False

    def test_returns_false_when_busy_but_no_event(self) -> None:
        mgr, _db, _ctx = _make_mgr()
        mgr._session_status["s1"] = "busy"
        # abort_events dict is empty
        assert mgr.abort_session("s1") is False

    def test_sets_event_when_busy(self) -> None:
        mgr, _db, _ctx = _make_mgr()
        event = asyncio.Event()
        mgr._session_status["s1"] = "busy"
        mgr._abort_events["s1"] = event
        assert mgr.abort_session("s1") is True
        assert event.is_set()

    def test_set_event_can_be_awaited(self) -> None:
        """An async coroutine should observe the set event."""
        mgr, _db, _ctx = _make_mgr()
        event = asyncio.Event()
        mgr._session_status["s1"] = "busy"
        mgr._abort_events["s1"] = event

        async def wait_then_abort() -> bool:
            await asyncio.wait_for(event.wait(), timeout=0.1)
            return True

        async def runner() -> tuple[bool, bool]:
            waiter = asyncio.create_task(wait_then_abort())
            await asyncio.sleep(0.001)  # let waiter subscribe
            aborted = mgr.abort_session("s1")
            return aborted, await waiter

        result = asyncio.run(runner())
        assert result == (True, True)


# ── get_session_status / get_all_session_status ──────────────────


class TestSessionStatus:
    def test_get_returns_idle_default(self) -> None:
        mgr, _db, _ctx = _make_mgr()
        assert mgr.get_session_status("unknown") == "idle"

    def test_get_returns_tracked_status(self) -> None:
        mgr, _db, _ctx = _make_mgr()
        mgr._session_status["s1"] = "busy"
        mgr._session_status["s2"] = "idle"
        assert mgr.get_session_status("s1") == "busy"
        assert mgr.get_session_status("s2") == "idle"

    def test_get_all_returns_snapshot(self) -> None:
        mgr, _db, _ctx = _make_mgr()
        mgr._session_status["s1"] = "busy"
        mgr._session_status["s2"] = "idle"
        snapshot = mgr.get_all_session_status()
        assert snapshot == {"s1": "busy", "s2": "idle"}
        # The snapshot is a copy — mutating it must not affect the source.
        snapshot["s1"] = "MUTATED"
        assert mgr.get_session_status("s1") == "busy"

    def test_get_all_empty(self) -> None:
        mgr, _db, _ctx = _make_mgr()
        assert mgr.get_all_session_status() == {}


# ── Smoke / integration ──────────────────────────────────────────


def test_session_status_dict_is_shared_with_caller() -> None:
    """Mutating the dict from outside should be visible via the manager."""
    db = _FakeDB()
    ctx = _FakeContextManager()
    status: dict[str, str] = {}
    aborts: dict[str, asyncio.Event] = {}
    mgr = SessionManager(
        db=db, context_manager=ctx,
        session_status=status, abort_events=aborts,
    )
    status["s1"] = "busy"
    assert mgr.get_session_status("s1") == "busy"
