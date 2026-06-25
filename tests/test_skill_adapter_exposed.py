"""Unit tests for SkillToolAdapter default exposure (v0.41).

v0.41 changes the default ``exposed_skills`` so that
``web_search`` and ``web_fetch`` Skills are visible to the top-
level chat LLM (previously filtered out by default).

Target: 6 tests covering:
  - default_exposed contains web_search + web_fetch
  - Adapter builds tool entries for all 3 actions of web_search
  - Adapter builds tool entry for fetch_url action
  - Explicit exposed_skills overrides default
  - subagent_manager auto-adds 'subagent'
  - list_tools returns the expected tool names
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from llmwikify.apps.agent.tools.skill_adapter import SkillToolAdapter
from llmwikify.apps.chat.skills.registry import SkillRegistry
from llmwikify.apps.chat.skills.service import SkillService


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def skill_service() -> SkillService:
    """Real SkillService populated with all base skills."""
    return SkillService()


# ─── Default exposure ───────────────────────────────────────────


class TestDefaultExposure:
    def test_default_exposed_includes_web_search(
        self, skill_service: SkillService,
    ) -> None:
        adapter = SkillToolAdapter(skill_service)
        assert "web_search" in adapter.exposed_skills

    def test_default_exposed_includes_web_fetch(
        self, skill_service: SkillService,
    ) -> None:
        adapter = SkillToolAdapter(skill_service)
        assert "web_fetch" in adapter.exposed_skills

    def test_default_exposed_includes_workflow_and_compound(
        self, skill_service: SkillService,
    ) -> None:
        adapter = SkillToolAdapter(skill_service)
        assert "dynamic_workflow" in adapter.exposed_skills
        assert "autoresearch_compound" in adapter.exposed_skills

    def test_subagent_added_when_subagent_manager_provided(
        self, skill_service: SkillService,
    ) -> None:
        adapter = SkillToolAdapter(skill_service, subagent_manager=MagicMock())
        assert "subagent" in adapter.exposed_skills
        assert "web_search" in adapter.exposed_skills
        assert "web_fetch" in adapter.exposed_skills


# ─── Tool building ───────────────────────────────────────────────


class TestToolBuilding:
    def test_web_search_actions_exposed_as_tools(
        self, skill_service: SkillService,
    ) -> None:
        adapter = SkillToolAdapter(skill_service)
        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}

        # The SkillToolAdapter renames skill_action to skill_action
        assert "web_search_search_web" in tool_names
        assert "web_search_search_youtube" in tool_names
        assert "web_search_search_news" in tool_names

    def test_web_fetch_action_exposed_as_tool(
        self, skill_service: SkillService,
    ) -> None:
        adapter = SkillToolAdapter(skill_service)
        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}

        assert "web_fetch_fetch_url" in tool_names

    def test_unknown_skills_not_exposed(
        self, skill_service: SkillService,
    ) -> None:
        """Skills outside the exposed list aren't built into tools."""
        adapter = SkillToolAdapter(skill_service)
        # 'search' is in ALL_ACTIONS but not in default_exposed
        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}
        assert "search_search" not in tool_names


# ─── Override ────────────────────────────────────────────────────


class TestExplicitOverride:
    def test_explicit_exposed_skills_overrides_default(
        self, skill_service: SkillService,
    ) -> None:
        """When exposed_skills is given, default is ignored."""
        adapter = SkillToolAdapter(
            skill_service,
            exposed_skills=["web_search"],
        )
        assert adapter.exposed_skills == {"web_search"}
        assert "web_fetch" not in adapter.exposed_skills
        assert "dynamic_workflow" not in adapter.exposed_skills

    def test_empty_exposed_skills_means_default(
        self, skill_service: SkillService,
    ) -> None:
        """When ``exposed_skills=[]`` is passed, the ``or default``
        in the constructor triggers — empty list is falsy."""
        adapter = SkillToolAdapter(
            skill_service,
            exposed_skills=[],
        )
        # Empty list is falsy, so default kicks in
        assert "web_search" in adapter.exposed_skills
        assert "web_fetch" in adapter.exposed_skills