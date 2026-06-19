"""Tests for Dream (Phase 6).

Borrowed from nanobot Dream architecture (memory.py:859).
Tests cover:
  - Cursor management (read/write/incremental)
  - list_since (incremental scan)
  - LLM fact extraction (parse "- fact" lines, "1. fact", etc.)
  - Double-write (SQLite + markdown + index)
  - run() vs run_for_session()
  - Markdown failure tolerance
  - Timeout handling
  - MemoryManager.dream_run() forwarding
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
from llmwikify.apps.chat.memory.dream import (
    CURSOR_FILENAME,
    Dream,
    DreamConfig,
    DreamResult,
)
from llmwikify.apps.chat.memory.facts_store import (
    MemoryFactsStore,
)

# ─── helpers ─────────────────────────────────────────────────────


def _make_provider(*responses: str) -> MagicMock:
    """Mock LLM provider returning successive responses."""
    provider = MagicMock()
    provider.achat = AsyncMock(side_effect=list(responses))
    return provider


def _make_app_db_mock(tmp_path: Path) -> MagicMock:
    db_path = str(tmp_path / "agent.db")
    Path(db_path).touch()
    chat_db = MagicMock()
    chat_db.db_path = db_path
    app_db = MagicMock()
    app_db.chat = chat_db
    app_db.data_dir = tmp_path
    return app_db


def _seed_consolidations(
    tmp_path: Path, session_ids: list[str], summary: str = "summary"
) -> list[str]:
    """Seed memory_consolidations with one row per session_id.

    Returns list of consolidation IDs.
    """
    store = MemoryConsolidationStore(str(tmp_path / "agent.db"))
    store.init_schema()
    ids = []
    for sid in session_ids:
        ids.append(store.add(session_id=sid, start_msg_idx=0, end_msg_idx=10, summary=summary))
        time.sleep(0.005)  # ensure distinct created_at
    return ids


# ─── Cursor management ──────────────────────────────────────────


class TestDreamCursor:
    def test_read_cursor_default_zero(self, tmp_path: Path) -> None:
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=_make_provider(),
            data_dir=tmp_path,
        )
        assert dream._read_cursor() == 0.0

    def test_write_cursor_creates_file(self, tmp_path: Path) -> None:
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=_make_provider(),
            data_dir=tmp_path,
        )
        dream._write_cursor(1234567890.5)
        assert dream._cursor_path.exists()
        assert float(dream._cursor_path.read_text()) == 1234567890.5

    def test_read_after_write(self, tmp_path: Path) -> None:
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=_make_provider(),
            data_dir=tmp_path,
        )
        dream._write_cursor(999.9)
        assert dream._read_cursor() == 999.9

    def test_corrupted_cursor_returns_zero(self, tmp_path: Path) -> None:
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=_make_provider(),
            data_dir=tmp_path,
        )
        # Manually write garbage
        dream._memory_dir.mkdir(parents=True, exist_ok=True)
        dream._cursor_path.write_text("not-a-number")
        assert dream._read_cursor() == 0.0


# ─── Fact extraction (LLM parsing) ───────────────────────────────


class TestDreamFactExtraction:
    @pytest.mark.asyncio
    async def test_extract_dash_prefixed_facts(self, tmp_path: Path) -> None:
        provider = _make_provider(
            "- User prefers dark mode\n- Stocks: AAPL\n- Risk tolerance: moderate"
        )
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        # Seed a consolidation so _extract_facts has data
        _seed_consolidations(tmp_path, ["s1"])
        records = dream.consolidation_store.list_since(0)
        facts = await dream._extract_facts(records)
        assert len(facts) == 3
        assert facts[0]["content"] == "User prefers dark mode"
        assert facts[1]["content"] == "Stocks: AAPL"
        assert facts[0]["source_session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_extract_numbered_facts(self, tmp_path: Path) -> None:
        provider = _make_provider(
            "1. First fact\n2. Second fact\n3. Third"
        )
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        _seed_consolidations(tmp_path, ["s1"])
        facts = await dream._extract_facts(dream.consolidation_store.list_since(0))
        assert len(facts) == 3
        assert facts[0]["content"] == "First fact"

    @pytest.mark.asyncio
    async def test_skip_too_short_facts(self, tmp_path: Path) -> None:
        provider = _make_provider("- hi\n- This is a valid fact\n- ok")
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        _seed_consolidations(tmp_path, ["s1"])
        facts = await dream._extract_facts(dream.consolidation_store.list_since(0))
        # Only the medium-length one passes
        assert len(facts) == 1
        assert facts[0]["content"] == "This is a valid fact"

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.achat = AsyncMock(side_effect=RuntimeError("LLM down"))
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        _seed_consolidations(tmp_path, ["s1"])
        facts = await dream._extract_facts(dream.consolidation_store.list_since(0))
        assert facts == []

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty(self, tmp_path: Path) -> None:
        provider = _make_provider("")
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        _seed_consolidations(tmp_path, ["s1"])
        facts = await dream._extract_facts(dream.consolidation_store.list_since(0))
        assert facts == []


# ─── Double-write ────────────────────────────────────────────────


class TestDreamWriteFacts:
    @pytest.mark.asyncio
    async def test_sqlite_write(self, tmp_path: Path) -> None:
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=_make_provider(),
            data_dir=tmp_path,
            config=DreamConfig(enable_md_write=False),
        )
        facts = [
            {"content": "Fact 1", "source_session_id": "s1",
             "source_type": "dream_extraction", "confidence": 1.0},
            {"content": "Fact 2", "source_session_id": "s2",
             "source_type": "dream_extraction", "confidence": 1.0},
        ]
        written = await dream._write_facts(facts)
        assert written == 2
        assert dream.facts_store.count() == 2

    @pytest.mark.asyncio
    async def test_markdown_write(self, tmp_path: Path) -> None:
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=_make_provider(),
            data_dir=tmp_path,
            config=DreamConfig(enable_md_write=True),
        )
        facts = [
            {"content": "Momentum works in A-share", "source_session_id": "s1",
             "source_type": "dream_extraction", "confidence": 1.0},
        ]
        await dream._write_facts(facts)
        # Per-fact md
        assert dream._facts_dir.exists()
        md_files = list(dream._facts_dir.glob("*.md"))
        # index.md + 1 fact.md
        assert any(f.name == "index.md" for f in md_files)
        # Find the fact md (not index)
        fact_mds = [f for f in md_files if f.name != "index.md"]
        assert len(fact_mds) == 1
        content = fact_mds[0].read_text()
        assert "Momentum works in A-share" in content

    @pytest.mark.asyncio
    async def test_markdown_disabled(self, tmp_path: Path) -> None:
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=_make_provider(),
            data_dir=tmp_path,
            config=DreamConfig(enable_md_write=False),
        )
        facts = [{"content": "x", "source_session_id": "s1",
                  "source_type": "dream_extraction", "confidence": 1.0}]
        await dream._write_facts(facts)
        assert not dream._facts_dir.exists()


# ─── run() main entry ────────────────────────────────────────────


class TestDreamRun:
    @pytest.mark.asyncio
    async def test_run_with_no_data(self, tmp_path: Path) -> None:
        provider = _make_provider()
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        result = await dream.run()
        assert isinstance(result, DreamResult)
        assert result.consolidations_scanned == 0
        assert result.facts_written == 0
        provider.achat.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_with_consolidations(self, tmp_path: Path) -> None:
        provider = _make_provider("- Fact A\n- Fact B")
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=DreamConfig(enable_md_write=False),
        )
        _seed_consolidations(tmp_path, ["s1", "s2", "s3"])
        result = await dream.run()
        assert result.consolidations_scanned == 3
        assert result.facts_extracted == 2
        assert result.facts_written == 2
        assert result.cursor > 0
        # Cursor updated
        assert dream._read_cursor() > 0

    @pytest.mark.asyncio
    async def test_run_incremental(self, tmp_path: Path) -> None:
        """Second run should see no new consolidations (cursor blocks)."""
        provider = _make_provider("- Fact A")
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=DreamConfig(enable_md_write=False),
        )
        _seed_consolidations(tmp_path, ["s1", "s2"])
        r1 = await dream.run()
        assert r1.consolidations_scanned == 2

        # Second run — cursor advanced, no new data
        r2 = await dream.run()
        assert r2.consolidations_scanned == 0
        assert r2.facts_written == 0

    @pytest.mark.asyncio
    async def test_run_min_consolidations_to_run(
        self, tmp_path: Path
    ) -> None:
        provider = _make_provider()
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=DreamConfig(
                enable_md_write=False,
                min_consolidations_to_run=5,
            ),
        )
        _seed_consolidations(tmp_path, ["s1", "s2"])
        result = await dream.run()
        # Only 2 < min 5, no extraction
        assert result.consolidations_scanned == 2
        assert result.facts_written == 0
        provider.achat.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_timeout(self, tmp_path: Path) -> None:
        provider = MagicMock()
        # Sleep is wrapped in async lambda so the coroutine is awaited
        async def _slow(**_kw):
            await asyncio.sleep(10)

        provider.achat = AsyncMock(side_effect=_slow)
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=DreamConfig(
                enable_md_write=False,
                timeout_seconds=0.1,
            ),
        )
        _seed_consolidations(tmp_path, ["s1"])
        result = await dream.run()
        # Scanned count reflects what was loaded BEFORE timeout; the key
        # assertion is that no facts were written (timeout interrupted LLM).
        assert result.facts_extracted == 0
        assert result.facts_written == 0
        assert result.elapsed_seconds < 1.0  # near-timeout

    @pytest.mark.asyncio
    async def test_run_exception(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.achat = AsyncMock(side_effect=RuntimeError("boom"))
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        _seed_consolidations(tmp_path, ["s1"])
        result = await dream.run()
        # LLM error → 0 facts written, no raise
        assert result.facts_written == 0


# ─── run_for_session ────────────────────────────────────────────


class TestDreamRunForSession:
    @pytest.mark.asyncio
    async def test_run_for_specific_session(self, tmp_path: Path) -> None:
        provider = _make_provider("- Fact for s1")
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
            config=DreamConfig(enable_md_write=False),
        )
        _seed_consolidations(tmp_path, ["s1", "s2", "s3"])
        result = await dream.run_for_session("s2")
        assert result.consolidations_scanned == 1
        assert result.facts_written == 1
        assert result.cursor > 0

    @pytest.mark.asyncio
    async def test_run_for_session_empty(self, tmp_path: Path) -> None:
        provider = _make_provider()
        dream = Dream(
            memory_manager=MagicMock(),
            db=_make_app_db_mock(tmp_path).chat,
            provider=provider,
            data_dir=tmp_path,
        )
        _seed_consolidations(tmp_path, ["s1"])
        result = await dream.run_for_session("nonexistent")
        assert result.consolidations_scanned == 0


# ─── MemoryManager.dream_run forwarding ──────────────────────────


class TestMemoryManagerDreamIntegration:
    @pytest.mark.asyncio
    async def test_dream_run_forwards(self, tmp_path: Path) -> None:
        provider = _make_provider("- Fact X")
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        _seed_consolidations(tmp_path, ["s1"])
        # Override config to skip md write for isolation
        mm.dream.config.enable_md_write = False
        result = await mm.dream_run()
        assert isinstance(result, DreamResult)
        assert result.facts_written >= 1

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
        result = await mm.dream_run()
        assert result is None

    def test_memory_manager_with_provider_includes_dream(
        self, tmp_path: Path
    ) -> None:
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=_make_provider(),
        )
        assert mm.dream is not None
        assert isinstance(mm.dream, Dream)
        assert mm.consolidator is not None  # also present
