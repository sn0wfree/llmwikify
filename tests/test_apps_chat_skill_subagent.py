"""Phase 10-E (2026-06-20) tests for spawn_subagent SkillAction.

Cases:
  1. Skill is registered in default registry (via SkillService)
  2. spawn_subagent fails when subagent_manager is missing from ctx
  3. spawn_subagent fails on empty goal
  4. spawn_subagent fails on too-long goal (>4000 chars)
  5. successful invocation returns SkillResult.ok with payload
  6. Hard cap on max_iterations (>10 → 10)
  7. Hard cap on timeout_seconds (>300 → 300)
  8. Missing parent_session_id → fail
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.agent.subagent_manager import SubagentResult
from llmwikify.apps.chat.skills.base import SkillContext
from llmwikify.apps.chat.skills.crud.subagent_skill import (
    _spawn_subagent,
    subagent_skill,
)


def _make_ctx(
    *,
    manager=None,
    session_id: str = "s1",
    extra_config: dict | None = None,
) -> SkillContext:
    config: dict = {}
    if manager is not None:
        config["subagent_manager"] = manager
    if extra_config:
        config.update(extra_config)
    return SkillContext(session_id=session_id, config=config)


def test_subagent_skill_registered_in_service() -> None:
    """SkillService.register_all should register subagent_skill."""
    from llmwikify.apps.chat.skills.service import SkillService

    svc = SkillService()
    svc.register_all()
    assert svc.registry.has("subagent")
    skill = svc.registry.get("subagent")
    assert skill is not None
    assert "spawn_subagent" in skill.actions


@pytest.mark.asyncio
async def test_spawn_fails_when_manager_missing() -> None:
    ctx = _make_ctx(manager=None)
    result = await _spawn_subagent({"goal": "x"}, ctx)
    assert result.status == "error"
    assert "subagent_manager" in (result.error or "")


@pytest.mark.asyncio
async def test_spawn_fails_on_empty_goal() -> None:
    mgr = MagicMock()
    mgr.run = AsyncMock()
    ctx = _make_ctx(manager=mgr)
    result = await _spawn_subagent({"goal": ""}, ctx)
    assert result.status == "error"
    assert "goal is required" in (result.error or "")
    mgr.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_spawn_fails_on_overlong_goal() -> None:
    mgr = MagicMock()
    mgr.run = AsyncMock()
    ctx = _make_ctx(manager=mgr)
    result = await _spawn_subagent({"goal": "x" * 4001}, ctx)
    assert result.status == "error"
    assert "too long" in (result.error or "")
    mgr.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_spawn_success_returns_ok() -> None:
    mgr = MagicMock()
    mgr.run = AsyncMock(return_value=SubagentResult(
        status="ok",
        final_content="child answer",
        tools_used=["search"],
        usage={"prompt_tokens": 5},
    ))
    ctx = _make_ctx(manager=mgr)
    result = await _spawn_subagent({"goal": "investigate X"}, ctx)
    assert result.status == "ok"
    assert result.data["final_content"] == "child answer"
    assert result.data["tools_used"] == ["search"]
    assert result.data["status"] == "ok"


@pytest.mark.asyncio
async def test_spawn_caps_max_iterations_at_10() -> None:
    mgr = MagicMock()
    mgr.run = AsyncMock(return_value=SubagentResult(status="ok"))
    ctx = _make_ctx(manager=mgr)
    await _spawn_subagent(
        {"goal": "x", "max_iterations": 50},
        ctx,
    )
    spec_passed = mgr.run.call_args[0][0]
    assert spec_passed.max_iterations == 10


@pytest.mark.asyncio
async def test_spawn_caps_timeout_at_300() -> None:
    mgr = MagicMock()
    mgr.run = AsyncMock(return_value=SubagentResult(status="ok"))
    ctx = _make_ctx(manager=mgr)
    await _spawn_subagent(
        {"goal": "x", "timeout_seconds": 9999},
        ctx,
    )
    spec_passed = mgr.run.call_args[0][0]
    assert spec_passed.timeout_seconds == 300.0


@pytest.mark.asyncio
async def test_spawn_fails_when_session_id_missing() -> None:
    mgr = MagicMock()
    mgr.run = AsyncMock()
    ctx = _make_ctx(manager=mgr, session_id="")
    result = await _spawn_subagent({"goal": "x"}, ctx)
    assert result.status == "error"
    assert "parent_session_id" in (result.error or "")
    mgr.run.assert_not_awaited()


def test_skill_declares_correct_input_schema() -> None:
    schema = subagent_skill.actions["spawn_subagent"].input_schema
    assert schema["type"] == "object"
    assert "goal" in schema["properties"]
    assert "max_iterations" in schema["properties"]
    assert "timeout_seconds" in schema["properties"]
    assert schema["required"] == ["goal"]
    assert schema["properties"]["max_iterations"]["maximum"] == 10
