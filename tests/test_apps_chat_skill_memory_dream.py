"""Tests for MemoryDreamSkill (Phase 6).

Covers:
  - run() forwards to MemoryManager.dream.run()
  - run_for_session() forwards correctly
  - fail-soft: no memory_manager → SkillResult.fail
  - fail-soft: no dream attr → SkillResult.fail
  - run() with empty args (no session_id) falls back to ctx.session_id
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.memory import MemoryManager
from llmwikify.apps.chat.memory.consolidation_store import (
    MemoryConsolidationStore,
)
from llmwikify.apps.chat.skills.base import SkillContext, SkillResult
from llmwikify.apps.chat.skills.crud.memory_dream_skill import (
    MemoryDreamSkill,
    _get_dream,
    _run,
    _run_for_session,
)


def _make_app_db_mock(tmp_path: Path) -> MagicMock:
    db_path = str(tmp_path / "agent.db")
    Path(db_path).touch()
    chat_db = MagicMock()
    chat_db.db_path = db_path
    app_db = MagicMock()
    app_db.chat = chat_db
    app_db.data_dir = tmp_path
    return app_db


def _make_skill_context(
    memory_manager: MagicMock | None = None,
    session_id: str = "test-session",
) -> SkillContext:
    """Build a SkillContext with optional memory_manager in config."""
    ctx = MagicMock(spec=SkillContext)
    ctx.session_id = session_id
    ctx.config = {"memory_manager": memory_manager} if memory_manager else {}
    return ctx


class TestGetDream:
    def test_returns_dream_when_configured(self, tmp_path: Path) -> None:
        provider = MagicMock()
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        ctx = _make_skill_context(memory_manager=mm)
        dream = _get_dream(ctx)
        assert dream is mm.dream

    def test_fails_when_no_memory_manager(self) -> None:
        ctx = _make_skill_context(memory_manager=None)
        result = _get_dream(ctx)
        assert isinstance(result, SkillResult)
        assert result.status == "error"
        assert "memory_manager not configured" in result.error

    def test_fails_when_no_dream_attr(self) -> None:
        # MemoryManager without provider → dream is None
        mm = MemoryManager(
            app_db=_make_app_db_mock(Path("/tmp")),
            wiki=None,
            data_dir=Path("/tmp"),
            provider=None,
        )
        ctx = _make_skill_context(memory_manager=mm)
        result = _get_dream(ctx)
        assert isinstance(result, SkillResult)
        assert result.status == "error"
        assert "dream not configured" in result.error


class TestRunAction:
    @pytest.mark.asyncio
    async def test_run_with_consolidations(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.achat = AsyncMock(return_value={"content": "- Fact A\n- Fact B"})
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        mm.dream.config.enable_md_write = False

        # Seed consolidations
        store = MemoryConsolidationStore(mm.app_db.chat.db_path)
        store.init_schema()
        for sid in ["s1", "s2"]:
            store.add(sid, 0, 10, "summary")

        ctx = _make_skill_context(memory_manager=mm)
        result = await _run({}, ctx)
        assert isinstance(result, SkillResult)
        assert result.status == "ok"
        assert result.data["facts_extracted"] == 2

    @pytest.mark.asyncio
    async def test_run_no_consolidations(self, tmp_path: Path) -> None:
        provider = MagicMock()
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        ctx = _make_skill_context(memory_manager=mm)
        result = await _run({}, ctx)
        assert isinstance(result, SkillResult)
        assert result.status == "ok"
        assert result.data["consolidations_scanned"] == 0

    @pytest.mark.asyncio
    async def test_run_llm_failure_returns_fail(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.achat = AsyncMock(side_effect=RuntimeError("boom"))
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        # Seed
        store = MemoryConsolidationStore(mm.app_db.chat.db_path)
        store.init_schema()
        store.add("s1", 0, 10, "x")

        ctx = _make_skill_context(memory_manager=mm)
        result = await _run({}, ctx)
        # LLM failure → caught internally → 0 facts, status=ok
        # (Dream.run() is designed fail-soft; the skill passes through)
        assert result.status == "ok"
        assert result.data["facts_written"] == 0


class TestRunForSessionAction:
    @pytest.mark.asyncio
    async def test_run_for_specific_session(self, tmp_path: Path) -> None:
        provider = MagicMock()
        provider.achat = AsyncMock(return_value={"content": "- Fact"})
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        mm.dream.config.enable_md_write = False
        store = MemoryConsolidationStore(mm.app_db.chat.db_path)
        store.init_schema()
        store.add("s1", 0, 10, "summary")
        store.add("s2", 0, 10, "other")

        ctx = _make_skill_context(memory_manager=mm)
        result = await _run_for_session({"session_id": "s1"}, ctx)
        assert isinstance(result, SkillResult)
        assert result.status == "ok"
        assert result.data["consolidations_scanned"] == 1

    @pytest.mark.asyncio
    async def test_run_for_session_falls_back_to_ctx(
        self, tmp_path: Path
    ) -> None:
        provider = MagicMock()
        provider.achat = AsyncMock(return_value={"content": "- Fact"})
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        mm.dream.config.enable_md_write = False
        store = MemoryConsolidationStore(mm.app_db.chat.db_path)
        store.init_schema()
        store.add("ctx-session", 0, 10, "summary")

        ctx = _make_skill_context(memory_manager=mm, session_id="ctx-session")
        # Pass empty session_id → fallback to ctx.session_id
        result = await _run_for_session({"session_id": ""}, ctx)
        assert result.status == "ok"
        assert result.data["consolidations_scanned"] == 1

    @pytest.mark.asyncio
    async def test_run_for_session_empty_id_fails(
        self, tmp_path: Path
    ) -> None:
        provider = MagicMock()
        mm = MemoryManager(
            app_db=_make_app_db_mock(tmp_path),
            wiki=None,
            data_dir=tmp_path,
            provider=provider,
        )
        ctx = MagicMock(spec=SkillContext)
        ctx.session_id = ""  # no fallback possible
        ctx.config = {"memory_manager": mm}
        result = await _run_for_session({}, ctx)
        assert result.status == "error"
        assert "session_id is required" in result.error


class TestMemoryDreamSkill:
    def test_skill_metadata(self) -> None:
        skill = MemoryDreamSkill()
        assert skill.name == "memory_dream"
        assert "run" in skill.actions
        assert "run_for_session" in skill.actions

    def test_skill_instance_exported(self) -> None:
        from llmwikify.apps.chat.skills.crud.memory_dream_skill import (
            memory_dream_skill,
        )
        assert memory_dream_skill.name == "memory_dream"
