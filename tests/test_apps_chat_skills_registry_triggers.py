"""Unit tests for v0.41 SkillRegistry.all_triggers() tool-name fix.

Regression: ``all_triggers`` returned ``tool: "skill_action"`` which
does not exist in the LLM-facing tool list (built by
``SkillToolAdapter._build_tools``). This misled the LLM to improvise
and call ``dynamic_workflow_run`` instead of
``autoresearch_compound_run`` for ``/study``, triggering an unwanted
"Confirmation Required" dialog.

Fix: ``all_triggers`` now returns the real computed tool name (same
algorithm as ``SkillToolAdapter._tool_name``).
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.skills.base import Skill, SkillAction, SkillResult
from llmwikify.apps.chat.skills.registry import SkillRegistry


def _noop(args, ctx):
    return SkillResult.ok({})


class _StudySkill(Skill):
    """The /study skill under test."""
    name = "autoresearch_compound"
    description = "Run compound research"
    actions = {
        "run": SkillAction(
            name="run",
            description="Run a research workflow.",
            handler=_noop,
            input_schema={"type": "object", "properties": {}, "required": []},
            triggers=["/study", "研究："],
            trigger_param="question",
        ),
    }


class _DashedSkill(Skill):
    """Skill with dashes in name and action."""
    name = "my-skill"
    description = "Test"
    actions = {
        "do-it": SkillAction(
            name="do-it",
            description="Test",
            handler=_noop,
            input_schema={"type": "object"},
            triggers=["/doit"],
        ),
    }


class _DottedSkill(Skill):
    """Skill with dots in name."""
    name = "foo.bar"
    description = "Test"
    actions = {
        "baz": SkillAction(
            name="baz",
            description="Test",
            handler=_noop,
            input_schema={"type": "object"},
            triggers=["/baz"],
        ),
    }


class _DynamicWorkflowSkill(Skill):
    """The general workflow runner skill."""
    name = "dynamic_workflow"
    description = "Dynamic workflow runner"
    actions = {
        "run": SkillAction(
            name="run",
            description="Run any workflow",
            handler=_noop,
            input_schema={"type": "object"},
            triggers=["/run"],
        ),
    }


class _NoTriggersSkill(Skill):
    """Skill with action that has no triggers."""
    name = "no_triggers_skill"
    description = "Test"
    actions = {
        "run": SkillAction(
            name="run",
            description="x",
            handler=_noop,
            input_schema={"type": "object"},
            triggers=[],
        ),
    }


def test_all_triggers_returns_real_tool_name_with_underscore() -> None:
    """Standard case: 'autoresearch_compound' + 'run' → 'autoresearch_compound_run'."""
    reg = SkillRegistry()
    reg.register(_StudySkill())
    triggers = reg.all_triggers()
    assert len(triggers) == 2
    tools = {t["tool"] for t in triggers}
    assert tools == {"autoresearch_compound_run"}
    # Each trigger entry has the right fields
    for t in triggers:
        assert t["skill"] == "autoresearch_compound"
        assert t["action"] == "run"
        assert t["param"] == "question"


def test_all_triggers_dashes_become_underscores() -> None:
    """Dashes in skill names get replaced (matches SkillToolAdapter._tool_name)."""
    reg = SkillRegistry()
    reg.register(_DashedSkill())
    triggers = reg.all_triggers()
    assert triggers[0]["tool"] == "my_skill_do_it"


def test_all_triggers_dots_become_underscores() -> None:
    """Dots in skill names get replaced."""
    reg = SkillRegistry()
    reg.register(_DottedSkill())
    triggers = reg.all_triggers()
    assert triggers[0]["tool"] == "foo_bar_baz"


def test_all_triggers_does_not_return_skill_action() -> None:
    """The misleading 'skill_action' string is no longer returned."""
    reg = SkillRegistry()
    reg.register(_StudySkill())
    triggers = reg.all_triggers()
    tools = {t["tool"] for t in triggers}
    assert "skill_action" not in tools


def test_all_triggers_includes_workflow_name() -> None:
    """v0.41: new 'workflow_name' field for skills backed by YAML workflows."""
    reg = SkillRegistry()
    reg.register(_StudySkill())
    triggers = reg.all_triggers()
    assert all(t["workflow_name"] == "autoresearch_compound" for t in triggers)


def test_all_triggers_no_skills_returns_empty() -> None:
    """Empty registry → empty list."""
    reg = SkillRegistry()
    assert reg.all_triggers() == []


def test_all_triggers_across_multiple_skills() -> None:
    """Multiple skills → each one's triggers with its own tool name."""
    reg = SkillRegistry()
    reg.register(_StudySkill())
    reg.register(_DynamicWorkflowSkill())
    triggers = reg.all_triggers()
    tools = {t["tool"] for t in triggers}
    assert "autoresearch_compound_run" in tools
    assert "dynamic_workflow_run" in tools
    assert "skill_action" not in tools


def test_all_triggers_actions_without_triggers_excluded() -> None:
    """Actions with empty triggers list don't produce trigger entries."""
    reg = SkillRegistry()
    reg.register(_NoTriggersSkill())
    assert reg.all_triggers() == []


def test_all_triggers_tool_name_matches_skill_tool_adapter() -> None:
    """The tool name from all_triggers must match the name in
    SkillToolAdapter's tool list (LLM consistency contract)."""
    from unittest.mock import MagicMock

    from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter

    # Build via registry
    reg = SkillRegistry()
    reg.register(_StudySkill())
    trigger_tools = {t["tool"] for t in reg.all_triggers()}

    # Build via the SkillToolAdapter
    skill_service = MagicMock()
    skill_service.registry = reg
    skill_service.register_all = lambda: None
    adapter = SkillToolAdapter(
        skill_service=skill_service,
        exposed_skills={"autoresearch_compound", "dynamic_workflow"},
    )
    adapter_tools = {t["name"] for t in adapter.list_tools()}

    # Every trigger tool must be in the adapter's tool list
    assert trigger_tools.issubset(adapter_tools), (
        f"trigger tools {trigger_tools} not in adapter tools {adapter_tools}"
    )
