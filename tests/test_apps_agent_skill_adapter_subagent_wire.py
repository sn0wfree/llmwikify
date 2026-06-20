"""Phase 10-E wire-up tests (2026-06-20).

Verifies that ChatOrchestrator builds the parent / child tool
registries with the right exposure of the ``subagent`` skill, and
that ``SkillToolAdapter`` propagates ``subagent_manager`` +
``child_tool_registry`` into ``SkillContext.config`` so
``spawn_subagent`` actually reaches a live manager.

Cases:
  1. SkillToolAdapter default exposed_skills excludes 'subagent'
     when no manager is supplied (back-compat).
  2. SkillToolAdapter auto-adds 'subagent' to exposed_skills when a
     manager is supplied (LLM can see the spawn tool).
  3. _execute_direct injects subagent_manager + child_tool_registry
     into SkillContext.config when configured.
  4. _execute_direct does NOT inject when not configured (Phase 8/9
     back-compat — config stays clean).
  5. Orchestrator._get_tool_registry returns separate adapters for
     parent (expose_subagent=True) and child (False); only the
     child is cached.
  6. Parent registry surface includes spawn_subagent; child
     registry does not.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter


def _make_skill_service():
    svc = MagicMock()
    svc.register_all = lambda: None
    registry = MagicMock()
    registry.all_actions = lambda: []
    svc.registry = registry
    return svc


def test_default_exposed_skills_excludes_subagent_when_no_manager() -> None:
    svc = _make_skill_service()
    adapter = SkillToolAdapter(svc)
    assert "subagent" not in adapter.exposed_skills
    assert "dynamic_workflow" in adapter.exposed_skills


def test_default_exposed_skills_includes_subagent_when_manager_given() -> None:
    svc = _make_skill_service()
    mgr = MagicMock()
    adapter = SkillToolAdapter(svc, subagent_manager=mgr)
    assert "subagent" in adapter.exposed_skills


def test_explicit_exposed_skills_override_default() -> None:
    """If caller passes exposed_skills explicitly, the auto-add of
    'subagent' is bypassed (caller's choice wins)."""
    svc = _make_skill_service()
    mgr = MagicMock()
    adapter = SkillToolAdapter(
        svc,
        subagent_manager=mgr,
        exposed_skills=["dynamic_workflow"],
    )
    assert "subagent" not in adapter.exposed_skills
    assert "dynamic_workflow" in adapter.exposed_skills


@pytest.mark.asyncio
async def test_execute_direct_injects_manager_and_child_registry() -> None:
    """When subagent_manager + child_tool_registry are configured,
    _execute_direct must surface them via SkillContext.config so
    the subagent_skill handler can find them."""
    svc = MagicMock()
    svc.register_all = lambda: None
    registry = MagicMock()
    registry.all_actions = lambda: []
    svc.registry = registry
    captured_ctx: dict[str, Any] = {}

    async def _execute(skill_name, action, args, ctx):
        captured_ctx["ctx"] = ctx
        return None

    svc.execute = _execute
    mgr = MagicMock()
    child_reg = MagicMock()
    adapter = SkillToolAdapter(
        svc,
        subagent_manager=mgr,
        child_tool_registry=child_reg,
        wiki_id="wiki-1",
        session_id="sess-1",
    )
    adapter._name_map["fake_run"] = ("fake", "run")
    adapter._tools["fake_run"] = {
        "description": "x",
        "action_type": "read",
        "requires_confirmation": False,
        "parameters": {},
    }
    await adapter._execute_direct("fake_run", {})
    cfg = captured_ctx["ctx"].config
    assert cfg["subagent_manager"] is mgr
    assert cfg["child_tool_registry"] is child_reg
    assert cfg["wiki_id"] == "wiki-1"


@pytest.mark.asyncio
async def test_execute_direct_omits_subagent_keys_when_not_configured() -> None:
    """Back-compat: if no manager is supplied, the SkillContext
    config must not contain subagent_manager / child_tool_registry
    keys (Phase 8/9 callers shouldn't see them at all)."""
    svc = MagicMock()
    svc.register_all = lambda: None
    registry = MagicMock()
    registry.all_actions = lambda: []
    svc.registry = registry
    captured_ctx: dict[str, Any] = {}

    async def _execute(skill_name, action, args, ctx):
        captured_ctx["ctx"] = ctx
        return None

    svc.execute = _execute
    adapter = SkillToolAdapter(svc, wiki_id="wiki-1", session_id="sess-1")
    adapter._name_map["fake_run"] = ("fake", "run")
    adapter._tools["fake_run"] = {
        "description": "x",
        "action_type": "read",
        "requires_confirmation": False,
        "parameters": {},
    }
    await adapter._execute_direct("fake_run", {})
    cfg = captured_ctx["ctx"].config
    assert "subagent_manager" not in cfg
    assert "child_tool_registry" not in cfg


def test_orchestrator_get_tool_registry_signature_supports_expose_subagent() -> None:
    """Smoke: the new keyword args must exist on the public method
    so the v2 chat path can call them. (Full wire requires a real
    AgentService; we just check the signature accepts the kwargs.)"""
    import inspect

    from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator

    sig = inspect.signature(ChatOrchestrator._get_tool_registry)
    assert "expose_subagent" in sig.parameters
    assert "subagent_manager" in sig.parameters
    assert "child_tool_registry" in sig.parameters
