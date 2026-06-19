"""Tests for Consolidator (Phase 6).

Borrowed from nanobot Consolidator architecture (memory.py:444).
Tests cover:
  - Threshold gating (tokens < trigger → no-op)
  - Eviction range (keep_recent_messages boundary)
  - Throttling (min_consolidation_interval_sec)
  - LLM call (mocked, fail-soft)
  - Double-write (SQLite + markdown file)
  - Markdown path under ~/.llmwikify/memory/sessions/
  - MemoryManager.consolidate_session forwarding
  - Provider=None → consolidator is None → forward returns None
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.memory import MemoryManager
from llmwikify.apps.chat.memory.consolidation_store import (
    MemoryConsolidationStore,
)
from llmwikify.apps.chat.memory.consolidator import (
    ConsolidationResult,
    Consolidator,
    ConsolidatorConfig,
)

# ─── helpers ─────────────────────────────────────────────────────


def _make_messages(n: int, content_factory=lambda i: f"msg-{i}") -> list[dict]:
    """Build n simple user messages."""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": content_factory(i)}
        for i in range(n)
    ]


def _make_provider(summary: str = "Topic: X. Decision: Y.") -> MagicMock:
    """Build a mock LLM provider returning a fixed summary."""
    provider = MagicMock()
    provider.achat = AsyncMock(return_value={"content": summary})
    return provider


def _make_app_db_mock(tmp_path: Path) -> MagicMock:
    """Build a minimal AppDatabase mock with .chat.db_path."""
    db_path = str(tmp_path / "agent.db")
    # Touch the file so sqlite3.connect works
    Path(db_path).touch()
    chat_db = MagicMock()
    chat_db.db_path = db_path
    app_db = MagicMock()
    app_db.chat = chat_db
    app_db.data_dir = tmp_path
    return app_db


# ─── Consolidator threshold gating ──────────────────────────────


class TestConsolidatorThreshold:
    @pytest.mark.asyncio
    async def test_below_threshold_no_op(self, tmp_path: Path) -> None:
        provider = _make_provider()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        result = await consol.maybe_consolidate(
            session_id="s1",
            messages=_make_messages(20),
            session_tokens=2000,  # < trigger 4000
        )
        assert result is None
        provider.achat.assert_not_called()

    @pytest.mark.asyncio
    async def test_few_messages_no_op(self, tmp_path: Path) -> None:
        provider = _make_provider()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        result = await consol.maybe_consolidate(
            session_id="s1",
            messages=_make_messages(5),  # < keep_recent=8
            session_tokens=5000,
        )
        assert result is None
        provider.achat.assert_not_called()

    @pytest.mark.asyncio
    async def test_above_threshold_consolidates(self, tmp_path: Path) -> None:
        provider = _make_provider("Summary: discussed momentum factor")
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(enable_md_write=False),
        )
        result = await consol.maybe_consolidate(
            session_id="s1",
            messages=_make_messages(20),
            session_tokens=5000,
        )
        assert result is not None
        assert isinstance(result, ConsolidationResult)
        assert result.messages_evicted == 12  # 20 - 8 keep_recent
        assert result.tokens_before > 0
        provider.achat.assert_called_once()


# ─── Eviction range ──────────────────────────────────────────────


class TestConsolidatorEviction:
    @pytest.mark.asyncio
    async def test_evict_first_n(self, tmp_path: Path) -> None:
        provider = _make_provider("ok")
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(
                keep_recent_messages=4,
                enable_md_write=False,
            ),
        )
        result = await consol.maybe_consolidate(
            session_id="s1",
            messages=_make_messages(10),
            session_tokens=10000,
        )
        assert result is not None
        assert result.messages_evicted == 6  # 10 - 4
        # Verify LLM got called with the first 6 messages
        call_args = provider.achat.call_args
        sent_messages = call_args.kwargs["messages"]
        # First is system prompt, then 6 user/assistant, total 7
        assert len(sent_messages) == 7

    @pytest.mark.asyncio
    async def test_evict_messages_passed_to_llm(
        self, tmp_path: Path
    ) -> None:
        provider = _make_provider()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(
                keep_recent_messages=2,
                enable_md_write=False,
            ),
        )
        await consol.maybe_consolidate(
            session_id="s1",
            messages=_make_messages(5),
            session_tokens=5000,
        )
        # LLM should have received messages[0..3] (5 - 2 = 3 evicted)
        sent = provider.achat.call_args.kwargs["messages"]
        assert len(sent) == 1 + 3  # system + 3 evicted


# ─── Throttling ──────────────────────────────────────────────────


class TestConsolidatorThrottling:
    @pytest.mark.asyncio
    async def test_throttle_blocks_immediate_repeat(self, tmp_path: Path) -> None:
        provider = _make_provider()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(
                min_consolidation_interval_sec=60.0,
                enable_md_write=False,
            ),
        )
        # First call: should run
        r1 = await consol.maybe_consolidate(
            session_id="s1",
            messages=_make_messages(20),
            session_tokens=5000,
        )
        assert r1 is not None
        # Second call (immediately): throttled
        r2 = await consol.maybe_consolidate(
            session_id="s1",
            messages=_make_messages(20),
            session_tokens=5000,
        )
        assert r2 is None

    @pytest.mark.asyncio
    async def test_throttle_per_session(self, tmp_path: Path) -> None:
        provider = _make_provider()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(
                min_consolidation_interval_sec=60.0,
                enable_md_write=False,
            ),
        )
        # s1 and s2 are independent
        r1 = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        r2 = await consol.maybe_consolidate(
            "s2", _make_messages(20), 5000,
        )
        assert r1 is not None
        assert r2 is not None

    @pytest.mark.asyncio
    async def test_throttle_expires(self, tmp_path: Path) -> None:
        provider = _make_provider()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(
                min_consolidation_interval_sec=0.0,
                enable_md_write=False,
            ),
        )
        r1 = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        r2 = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        # interval=0 → both run
        assert r1 is not None
        assert r2 is not None


# ─── LLM failure handling ───────────────────────────────────────


class TestConsolidatorLLMFailure:
    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.achat = AsyncMock(side_effect=RuntimeError("LLM down"))
        app_db = _make_app_db_mock(tmp_path)
        # Pre-create schema so MemoryConsolidationStore can query later
        MemoryConsolidationStore(app_db.chat.db_path).init_schema()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=app_db.chat,
            provider=provider,
            data_dir=tmp_path,
        )
        result = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        assert result is None
        # No SQLite record written on failure
        store = MemoryConsolidationStore(consol.db_path)
        assert store.count_by_session("s1") == 0

    @pytest.mark.asyncio
    async def test_llm_empty_content_returns_none(self, tmp_path: Path) -> None:
        provider = _make_provider(summary="")  # empty
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        result = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        assert result is None


# ─── Markdown double-write ───────────────────────────────────────


class TestConsolidatorMarkdownWrite:
    @pytest.mark.asyncio
    async def test_markdown_file_created(self, tmp_path: Path) -> None:
        provider = _make_provider("User asked about X")
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(enable_md_write=True),
        )
        result = await consol.maybe_consolidate(
            "sess-abc", _make_messages(20), 5000,
        )
        assert result is not None
        assert result.md_path is not None
        assert result.md_path.exists()
        assert result.md_path.parent == tmp_path / "memory" / "sessions"
        content = result.md_path.read_text(encoding="utf-8")
        assert "sess-abc" in content
        assert "User asked about X" in content
        assert "tokens_saved" in content

    @pytest.mark.asyncio
    async def test_markdown_disabled(self, tmp_path: Path) -> None:
        provider = _make_provider()
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(enable_md_write=False),
        )
        result = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        assert result is not None
        assert result.md_path is None
        # File should not exist
        assert not (tmp_path / "memory" / "sessions").exists()

    @pytest.mark.asyncio
    async def test_markdown_failure_continues(self, tmp_path: Path) -> None:
        """Markdown write failure should not block SQLite persist."""
        provider = _make_provider("ok")
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(enable_md_write=True),
        )
        # Force mkdir to fail by setting a read-only parent
        # (Easier: make _memory_sessions_dir unwritable)
        consol._memory_sessions_dir = Path("/nonexistent_path/xyz/blocked")
        result = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        # Should still succeed via SQLite
        assert result is not None
        assert result.record is not None
        assert result.md_path is None  # markdown write logged + skipped


# ─── SQLite persistence ─────────────────────────────────────────


class TestConsolidatorSQLite:
    @pytest.mark.asyncio
    async def test_sqlite_record_persisted(self, tmp_path: Path) -> None:
        provider = _make_provider("A concise summary")
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=ConsolidatorConfig(enable_md_write=False),
        )
        result = await consol.maybe_consolidate(
            "s1", _make_messages(20), 5000,
        )
        assert result is not None
        # Verify SQLite has the record
        store = MemoryConsolidationStore(consol.db_path)
        recs = store.list_by_session("s1")
        assert len(recs) == 1
        assert recs[0].summary == "A concise summary"
        assert recs[0].tokens_before > 0

    @pytest.mark.asyncio
    async def test_store_init_lazy(self, tmp_path: Path) -> None:
        provider = _make_provider()
        db = _make_app_db_mock(tmp_path).chat
        consol = Consolidator(
            memory_manager=MagicMock(),
            db=db,
            provider=provider,
            data_dir=tmp_path,
        )
        assert consol._store is None
        _ = consol.store  # trigger init
        assert consol._store is not None


# ─── MemoryManager.consolidate_session forwarding ────────────────


class TestMemoryManagerConsolidatorIntegration:
    def test_memory_manager_without_provider(self, tmp_path: Path) -> None:
        """No provider → consolidator/dream are None (back-compat)."""
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=None,
        )
        assert mm.consolidator is None
        assert mm.dream is None

    def test_memory_manager_with_provider(self, tmp_path: Path) -> None:
        provider = _make_provider()
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        assert mm.consolidator is not None
        assert isinstance(mm.consolidator, Consolidator)
        # Dream is wired in Step 3 (Phase 6)
        assert mm.dream is not None
        from llmwikify.apps.chat.memory.dream import Dream
        assert isinstance(mm.dream, Dream)

    @pytest.mark.asyncio
    async def test_consolidate_session_forwards(self, tmp_path: Path) -> None:
        provider = _make_provider("forwarded summary")
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        # Override config to skip md write for test isolation
        mm.consolidator.config.enable_md_write = False
        result = await mm.consolidate_session(
            "s1", _make_messages(20), 5000,
        )
        assert result is not None
        assert result.messages_evicted == 12

    @pytest.mark.asyncio
    async def test_consolidate_session_no_provider(self, tmp_path: Path) -> None:
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=None,
        )
        result = await mm.consolidate_session(
            "s1", _make_messages(20), 5000,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_dream_run_no_provider_returns_none(
        self, tmp_path: Path
    ) -> None:
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=None,
        )
        assert await mm.dream_run() is None
