"""Tests for AutoCompact — Phase 9 idle-session TTL consolidator.

Covers:
  - is_expired reads chat_sessions.updated_at and respects TTL
  - list_expired_sessions skips active + already-archiving keys
  - check_expired forwards to MemoryManager.consolidate_session
  - check_expired no-op when no consolidator wired
  - active_keys_from_status_map filters in-flight statuses
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from llmwikify.apps.chat.agent.autocompact import (
    AutoCompact,
    active_keys_from_status_map,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def chat_db(tmp_path: Path):
    from llmwikify.apps.chat.db._facade import ChatDatabase

    return ChatDatabase(tmp_path)


def _set_updated(db, sid: str, when: datetime) -> None:
    """Backdate a session's updated_at so we can drive expiry tests."""
    import sqlite3
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (when.strftime("%Y-%m-%d %H:%M:%S"), sid),
        )
        conn.commit()


class _StubConsolidator:
    """Minimal stand-in for Consolidator (records calls)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    async def maybe_consolidate(
        self, session_id: str, messages: list[dict], session_tokens: int,
    ):
        self.calls.append((session_id, len(messages), session_tokens))
        return {"summary": "ok"}


class _StubMemoryManager:
    def __init__(self, consolidator) -> None:
        self.consolidator = consolidator

    async def consolidate_session(self, session_id, messages, session_tokens):
        if self.consolidator is None:
            return None
        return await self.consolidator.maybe_consolidate(
            session_id, messages, session_tokens,
        )


def test_is_expired_returns_true_past_ttl(chat_db) -> None:
    auto = AutoCompact(chat_db=chat_db, memory_manager=None, ttl_minutes=30)
    now = datetime(2026, 6, 20, 12, 0, 0)
    old = now - timedelta(minutes=45)
    assert auto.is_expired(old.strftime("%Y-%m-%d %H:%M:%S"), now=now) is True


def test_is_expired_returns_false_within_ttl(chat_db) -> None:
    auto = AutoCompact(chat_db=chat_db, memory_manager=None, ttl_minutes=30)
    now = datetime(2026, 6, 20, 12, 0, 0)
    fresh = now - timedelta(minutes=10)
    assert auto.is_expired(fresh.strftime("%Y-%m-%d %H:%M:%S"), now=now) is False


def test_is_expired_zero_ttl_disables(chat_db) -> None:
    auto = AutoCompact(chat_db=chat_db, memory_manager=None, ttl_minutes=0)
    very_old = datetime(2020, 1, 1)
    assert auto.is_expired(very_old.isoformat()) is False


def test_is_expired_handles_unparseable_ts(chat_db) -> None:
    auto = AutoCompact(chat_db=chat_db, memory_manager=None, ttl_minutes=30)
    assert auto.is_expired("not a date") is False
    assert auto.is_expired(None) is False


def test_list_expired_returns_only_idle_sessions(chat_db) -> None:
    sid_old = chat_db.create_chat_session()
    sid_fresh = chat_db.create_chat_session()
    now = datetime.now()
    _set_updated(chat_db, sid_old, now - timedelta(hours=2))
    _set_updated(chat_db, sid_fresh, now - timedelta(minutes=1))

    auto = AutoCompact(chat_db=chat_db, memory_manager=None, ttl_minutes=30)
    expired = auto.list_expired_sessions(now=now)
    assert [r["id"] for r in expired] == [sid_old]


def test_list_expired_skips_active_sessions(chat_db) -> None:
    sid_old = chat_db.create_chat_session()
    now = datetime.now()
    _set_updated(chat_db, sid_old, now - timedelta(hours=2))
    auto = AutoCompact(chat_db=chat_db, memory_manager=None, ttl_minutes=30)
    expired = auto.list_expired_sessions(active_session_keys={sid_old}, now=now)
    assert expired == []


def test_check_expired_forwards_to_consolidator(chat_db) -> None:
    sid = chat_db.create_chat_session()
    chat_db.save_chat_message({
        "id": "m1",
        "session_id": sid,
        "role": "user",
        "content": "hello world",
    })
    chat_db.save_chat_message({
        "id": "m2",
        "session_id": sid,
        "role": "assistant",
        "content": "hi back",
    })
    now = datetime.now()
    _set_updated(chat_db, sid, now - timedelta(hours=2))
    cons = _StubConsolidator()
    mm = _StubMemoryManager(cons)
    auto = AutoCompact(chat_db=chat_db, memory_manager=mm, ttl_minutes=30)
    touched = _run(auto.check_expired(now=now))
    assert touched == [sid]
    assert len(cons.calls) == 1
    call_sid, msg_count, _ = cons.calls[0]
    assert call_sid == sid
    assert msg_count == 2


def test_check_expired_noop_when_no_consolidator(chat_db) -> None:
    sid = chat_db.create_chat_session()
    now = datetime.now()
    _set_updated(chat_db, sid, now - timedelta(hours=2))
    mm = _StubMemoryManager(consolidator=None)
    auto = AutoCompact(chat_db=chat_db, memory_manager=mm, ttl_minutes=30)
    touched = _run(auto.check_expired(now=now))
    assert touched == []


def test_check_expired_skips_active_session(chat_db) -> None:
    sid_active = chat_db.create_chat_session()
    sid_idle = chat_db.create_chat_session()
    chat_db.save_chat_message({
        "id": "m1", "session_id": sid_idle,
        "role": "user", "content": "x",
    })
    now = datetime.now()
    _set_updated(chat_db, sid_active, now - timedelta(hours=2))
    _set_updated(chat_db, sid_idle, now - timedelta(hours=2))
    cons = _StubConsolidator()
    mm = _StubMemoryManager(cons)
    auto = AutoCompact(chat_db=chat_db, memory_manager=mm, ttl_minutes=30)
    touched = _run(auto.check_expired(
        active_session_keys={sid_active}, now=now,
    ))
    assert touched == [sid_idle]
    assert [c[0] for c in cons.calls] == [sid_idle]


def test_check_expired_uses_scheduler_callback(chat_db) -> None:
    sid = chat_db.create_chat_session()
    chat_db.save_chat_message({
        "id": "m1", "session_id": sid, "role": "user", "content": "x",
    })
    now = datetime.now()
    _set_updated(chat_db, sid, now - timedelta(hours=2))
    cons = _StubConsolidator()
    mm = _StubMemoryManager(cons)
    auto = AutoCompact(chat_db=chat_db, memory_manager=mm, ttl_minutes=30)
    scheduled: list = []

    def _scheduler(coro):
        scheduled.append(coro)

    touched = _run(auto.check_expired(now=now, scheduler=_scheduler))
    assert touched == [sid]
    # scheduler got called instead of awaiting; consolidator NOT invoked yet
    assert cons.calls == []
    assert len(scheduled) == 1
    # Drain the scheduled coroutine so it doesn't dangle
    _run(scheduled[0])
    assert len(cons.calls) == 1


def test_active_keys_from_status_map_filters_in_flight() -> None:
    status = {
        "a": "running",
        "b": "idle",
        "c": "confirmation_required",
        "d": "completed",
        "e": "in_progress",
    }
    out = sorted(active_keys_from_status_map(status))
    assert out == ["a", "c", "e"]


def test_archiving_set_prevents_double_fire(chat_db) -> None:
    sid = chat_db.create_chat_session()
    now = datetime.now()
    _set_updated(chat_db, sid, now - timedelta(hours=2))
    auto = AutoCompact(chat_db=chat_db, memory_manager=None, ttl_minutes=30)
    auto._archiving.add(sid)
    expired = auto.list_expired_sessions(now=now)
    assert expired == []
