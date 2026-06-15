from __future__ import annotations

import pytest

from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter
from llmwikify.apps.chat.skills.service import SkillService
from llmwikify.apps.chat.skills.workflows.builtins import (
    get_builtin,
    list_builtin_names,
)


@pytest.mark.asyncio
async def test_autoresearch_compound_skill_is_registered_and_exposed():
    service = SkillService()
    adapter = SkillToolAdapter(service)

    assert service.get_skill("autoresearch_compound") is not None

    names = {tool["name"] for tool in adapter.list_tools()}
    assert "autoresearch_compound_run" in names
    assert "autoresearch_compound_status" in names


@pytest.mark.asyncio
async def test_autoresearch_compound_run_starts_without_write_confirmation(monkeypatch):
    from llmwikify.apps.chat.skills.workflows.executor import WorkflowExecutor

    monkeypatch.setattr(WorkflowExecutor, "run", lambda self: None)
    adapter = SkillToolAdapter(SkillService())

    result = await adapter.execute(
        "autoresearch_compound_run",
        {"question": "How should AutoResearch compound wiki knowledge?"},
    )

    assert result["status"] == "ok"
    assert result["data"]["status"] == "running"
    assert result["data"]["writes_wiki"] is False
    assert adapter.get_pending_confirmations() == []


@pytest.mark.asyncio
async def test_autoresearch_compound_status_handles_unknown_run():
    adapter = SkillToolAdapter(SkillService())

    result = await adapter.execute("autoresearch_compound_status", {"run_id": "missing"})

    assert result["status"] == "error"
    assert "no run with id" in result["error"]


def test_autoresearch_compound_workflow_is_builtin():
    builtin = get_builtin("autoresearch-compound")

    assert "autoresearch-compound" in list_builtin_names()
    assert builtin is not None
    assert builtin.phase_count == 6
    assert set(builtin.actor_names) == {
        "clarifier",
        "planner",
        "evidence_extractor",
        "finding_extractor",
        "wiki_proposer",
        "synthesizer",
    }
