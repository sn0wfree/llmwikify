"""Unit tests for v0.41 SkillToolAdapter 'Always' permission short-circuit.

Regression: ``chat_permissions`` rows written by clicking "Always" in
the ConfirmationModal were dead code — ``db.has_always_permission()``
was defined but never called. After clicking "Always", the next call
to the same tool would still raise the confirmation dialog.

Fix: ``SkillToolAdapter.execute`` and ``WikiToolRegistry.execute`` now
query ``has_always_permission`` and skip the confirmation branch if
the user has previously granted "Always" for that tool.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter
from llmwikify.apps.chat.skills.base import Skill, SkillAction, SkillResult


def _noop(args, ctx):
    return SkillResult.ok({"ok": True})


class _WriteSkill(Skill):
    """A skill that requires pre-confirmation (mimics dynamic_workflow.run)."""
    name = "dangerous_skill"
    description = "Requires approval"
    actions = {
        "run": SkillAction(
            name="run",
            description="Run it",
            handler=_noop,
            input_schema={"type": "object"},
            triggers=[],
            requires_confirmation=True,  # ← the key flag
        ),
    }


def _make_adapter(*, has_always: bool) -> SkillToolAdapter:
    """Build a SkillToolAdapter with mocked deps for execute() testing."""
    skill_service = MagicMock()
    registry = MagicMock()
    # Instantiate the skill once so its class-attr `actions` are valid
    _WriteSkill()
    skill_service.registry = registry
    skill_service.register_all = lambda: None
    skill_service.execute = AsyncMock(
        return_value=SkillResult.ok({"ran": True}),
    )
    db = MagicMock()
    db.has_always_permission = MagicMock(return_value=has_always)

    # Build via __new__ to skip _build_tools() / _register_get_skill_commands()
    # (we'll manually populate the tool dict)
    adapter = SkillToolAdapter.__new__(SkillToolAdapter)
    adapter.skill_service = skill_service
    adapter.wiki = None
    adapter.wiki_service = None
    adapter.db = db
    adapter.wiki_id = "wiki-1"
    adapter.session_id = "sess-1"
    adapter.exposed_skills = {"dangerous_skill"}
    adapter._name_map = {"dangerous_skill_run": ("dangerous_skill", "run")}
    adapter._tools = {
        "dangerous_skill_run": {
            "description": "Run it",
            "action_type": "write",
            "requires_confirmation": "pre",
            "parameters": {"type": "object"},
        },
    }
    adapter._pending_confirmations = {}
    adapter._get_skill_commands_handler = AsyncMock()
    # Phase 10-E (2026-06-20): wire-up adds these attrs; tests that
    # use ``__new__`` to bypass __init__ need to set defaults here.
    adapter.subagent_manager = None
    adapter.child_tool_registry = None
    return adapter


class TestAlwaysPermissionShortCircuit:
    @pytest.mark.asyncio
    async def test_no_permission_raises_confirmation(self) -> None:
        """No 'Always' on record → confirmation_required is returned."""
        adapter = _make_adapter(has_always=False)
        result = await adapter.execute("dangerous_skill_run", {})
        assert result["status"] == "confirmation_required"
        assert "confirmation_id" in result
        # No DB call to has_always_permission means we hit the wrong branch
        # (or has_always_permission was called and returned False)
        adapter.db.has_always_permission.assert_called_with(
            "dangerous_skill_run", session_id="sess-1",
        )

    @pytest.mark.asyncio
    async def test_with_permission_skips_confirmation(self) -> None:
        """'Always' on record → tool runs directly, no confirmation dialog."""
        adapter = _make_adapter(has_always=True)
        result = await adapter.execute("dangerous_skill_run", {})
        # No confirmation_required envelope
        assert "confirmation_id" not in result
        # The actual execution went through (SkillResult.ok → {"data": {...}, "status": "ok"})
        assert result == {"data": {"ran": True}, "status": "ok"}
        # No pending confirmations stored
        assert adapter._pending_confirmations == {}
        # The skill service was called directly
        adapter.skill_service.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_db_falls_back_to_confirmation(self) -> None:
        """If db is None, the old behavior (always confirm) is preserved."""
        adapter = _make_adapter(has_always=False)
        adapter.db = None
        result = await adapter.execute("dangerous_skill_run", {})
        assert result["status"] == "confirmation_required"

    @pytest.mark.asyncio
    async def test_non_confirming_tool_unaffected(self) -> None:
        """Tools with requires_confirmation=False never enter the branch."""
        adapter = _make_adapter(has_always=False)
        # Manually add a non-confirming tool
        adapter._name_map["safe_tool_run"] = ("safe_skill", "run")
        adapter._tools["safe_tool_run"] = {
            "description": "Safe",
            "action_type": "read",
            "requires_confirmation": False,
            "parameters": {"type": "object"},
        }
        # No safe_skill in exposed_skills, so add it
        adapter.exposed_skills = {"dangerous_skill", "safe_skill"}
        result = await adapter.execute("safe_tool_run", {})
        # Direct execution; no confirmation_required
        assert "status" not in result or result.get("status") != "confirmation_required"

    @pytest.mark.asyncio
    async def test_has_always_permission_called_only_for_confirming_tools(self) -> None:
        """Performance: has_always_permission must NOT be called for non-confirming tools."""
        adapter = _make_adapter(has_always=True)
        adapter._name_map["safe_tool_run"] = ("safe_skill", "run")
        adapter._tools["safe_tool_run"] = {
            "description": "Safe",
            "action_type": "read",
            "requires_confirmation": False,
            "parameters": {"type": "object"},
        }
        adapter.exposed_skills = {"dangerous_skill", "safe_skill"}
        # Reset the mock to track calls
        adapter.db.has_always_permission = MagicMock(return_value=True)
        await adapter.execute("safe_tool_run", {})
        # Critical: no DB call for the safe tool
        adapter.db.has_always_permission.assert_not_called()
