from __future__ import annotations

import pytest

from llmwikify.apps.agent.tools.skill_adapter import (
    CompositeToolRegistry,
    SkillToolAdapter,
)
from llmwikify.apps.chat.agent.tool_executor import ToolExecutor
from llmwikify.apps.chat.skills.service import SkillService


@pytest.mark.asyncio
async def test_skill_tool_adapter_exposes_dynamic_workflow_list():
    adapter = SkillToolAdapter(SkillService())

    tools = adapter.list_tools()
    names = {tool["name"] for tool in tools}

    assert "dynamic_workflow_list" in names
    assert "dynamic_workflow_run" in names
    assert "autoresearch_compound_run" in names

    result = await adapter.execute("dynamic_workflow_list", {})

    assert result["status"] == "ok"
    assert "workflows" in result["data"]


@pytest.mark.asyncio
async def test_skill_tool_adapter_requires_confirmation_for_write_skill():
    adapter = SkillToolAdapter(SkillService())

    result = await adapter.execute(
        "dynamic_workflow_run",
        {"name": "llmwikify-research", "inputs": {"question": "test"}},
    )

    assert result["status"] == "confirmation_required"
    assert result["group"] == "skill_actions"
    assert adapter.get_pending_confirmations()[0]["tool"] == "dynamic_workflow_run"

    rejected = adapter.reject_execution(result["confirmation_id"])

    assert rejected["status"] == "rejected"
    assert adapter.get_pending_confirmations() == []


class _FakeRegistry:
    def __init__(self, name: str, result: dict):
        self._tools = {
            name: {
                "description": f"{name} description",
                "action_type": "read",
                "requires_confirmation": False,
                "parameters": {"type": "object", "properties": {}, "required": []},
            }
        }
        self.result = result

    def list_tools(self):
        return [
            {
                "name": name,
                "description": info["description"],
                "action_type": info["action_type"],
                "requires_confirmation": info["requires_confirmation"],
                "parameters": info["parameters"],
            }
            for name, info in self._tools.items()
        ]

    def get_tool(self, name):
        return self._tools.get(name)

    async def execute(self, name, arguments):
        return {"tool": name, "arguments": arguments, **self.result}

    def confirm_execution(self, confirmation_id, arguments=None):
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}

    def reject_execution(self, confirmation_id):
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}

    def get_pending_confirmations(self):
        return []

    def get_pending_by_group(self):
        return {}


@pytest.mark.asyncio
async def test_composite_tool_registry_routes_wiki_and_skill_tools():
    wiki_registry = _FakeRegistry("wiki_search", {"source": "wiki"})
    skill_adapter = SkillToolAdapter(SkillService())
    registry = CompositeToolRegistry(wiki_registry, skill_adapter)

    names = {tool["name"] for tool in registry.list_tools()}

    assert "wiki_search" in names
    assert "dynamic_workflow_list" in names
    assert (await registry.execute("wiki_search", {"query": "x"}))["source"] == "wiki"
    assert (await registry.execute("dynamic_workflow_list", {}))["status"] == "ok"


def test_composite_tool_registry_rejects_duplicate_tool_names():
    with pytest.raises(ValueError, match="Duplicate tool name"):
        CompositeToolRegistry(
            _FakeRegistry("wiki_search", {"source": "a"}),
            _FakeRegistry("wiki_search", {"source": "b"}),
        )


def test_tool_executor_toolspec_includes_skill_tools():
    registry = CompositeToolRegistry(
        _FakeRegistry("wiki_search", {"source": "wiki"}),
        SkillToolAdapter(SkillService()),
    )
    executor = ToolExecutor(chat_db=None)

    specs = executor.get_toolspec(registry)
    names = {spec["function"]["name"] for spec in specs}

    assert "wiki_search" in names
    assert "dynamic_workflow_list" in names
    assert "dynamic_workflow_run" in names
    assert "autoresearch_compound_run" in names
