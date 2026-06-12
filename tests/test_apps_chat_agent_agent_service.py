"""Tests for AgentService composition root (apps/chat/agent/agent_service.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.agent_service import AgentService
from llmwikify.apps.chat.agent.orchestrator import ChatOrchestrator
from llmwikify.apps.chat.harness.service import HarnessService
from llmwikify.apps.chat.memory import MemoryManager
from llmwikify.apps.chat.skills.service import SkillService
from llmwikify.apps.db import AppDatabase
from llmwikify.apps.wiki.service import WikiService


@pytest.fixture
def wiki_registry():
    """Mock WikiRegistry with at least one wiki."""
    reg = MagicMock()
    reg.get_default_wiki_id.return_value = "wiki-1"
    wiki = MagicMock()
    wiki.is_initialized.return_value = True
    wiki.root = None
    reg.get_wiki.return_value = wiki
    reg.get_default_wiki.return_value = wiki
    reg.get_wiki_instance.return_value = wiki
    return reg


@pytest.fixture(autouse=True)
def _mock_wiki_get_llm(monkeypatch):
    """Patch WikiService.get_llm to return a mock (avoid real LLM init)."""
    from llmwikify.apps.wiki import service as wiki_service_mod

    def fake_get_llm(self):
        return MagicMock(name="mock_llm")

    monkeypatch.setattr(
        wiki_service_mod.WikiService, "get_llm", fake_get_llm,
    )


@pytest.fixture
def agent_service(wiki_registry):
    with tempfile.TemporaryDirectory() as tmp:
        yield AgentService(wiki_registry, Path(tmp))


class TestAgentServiceInit:
    def test_creates_all_components(self, agent_service):
        assert isinstance(agent_service.app_db, AppDatabase)
        assert isinstance(agent_service.wiki_service, WikiService)
        assert isinstance(agent_service.chat_service, ChatOrchestrator)
        assert isinstance(agent_service.skill_service, SkillService)
        assert isinstance(agent_service.harness_service, HarnessService)
        assert isinstance(agent_service.memory_manager, MemoryManager)

    def test_data_dir_created(self, agent_service):
        assert agent_service.data_dir.exists()

    def test_db_shortcut(self, agent_service):
        assert agent_service.db is agent_service.app_db.chat


class TestAgentServiceCustomComponents:
    def test_custom_app_db(self, wiki_registry):
        with tempfile.TemporaryDirectory() as tmp:
            custom_db = AppDatabase(tmp)
            svc = AgentService(wiki_registry, Path(tmp), app_db=custom_db)
            assert svc.app_db is custom_db

    def test_custom_skill_service(self, wiki_registry):
        with tempfile.TemporaryDirectory() as tmp:
            custom_skill = SkillService()
            svc = AgentService(
                wiki_registry, Path(tmp), skill_service=custom_skill,
            )
            assert svc.skill_service is custom_skill

    def test_custom_memory_manager(self, wiki_registry):
        with tempfile.TemporaryDirectory() as tmp:
            custom_mm = MemoryManager(AppDatabase(tmp))
            svc = AgentService(
                wiki_registry, Path(tmp), memory_manager=custom_mm,
            )
            assert svc.memory_manager is custom_mm


class TestAgentServiceDelegation:
    def test_reload_llm_delegates(self, agent_service):
        agent_service.wiki_service.reload_llm = MagicMock()
        agent_service.reload_llm()
        agent_service.wiki_service.reload_llm.assert_called_once()

    def test_get_agent_status_delegates(self, agent_service):
        agent_service.wiki_service.get_agent_status = MagicMock(
            return_value={"status": "ok"},
        )
        result = agent_service.get_agent_status("wiki-1")
        agent_service.wiki_service.get_agent_status.assert_called_with("wiki-1")
        assert result == {"status": "ok"}


class TestAgentServiceBackwardCompat:
    def test_get_tool_registry_delegates(self, agent_service):
        agent_service.wiki_service.get_tool_registry = MagicMock(
            return_value="mock_registry",
        )
        result = agent_service._get_tool_registry("wiki-1")
        assert result == "mock_registry"

    def test_get_llm_delegates(self, agent_service):
        agent_service.wiki_service.get_llm = MagicMock(return_value="mock_llm")
        result = agent_service._get_llm()
        assert result == "mock_llm"
