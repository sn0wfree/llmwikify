"""Tests for AgentService composition root (apps/chat/agent/agent_service.py)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.agent.agent_service import AgentService
from llmwikify.apps.chat.agent.context_manager import ContextManager
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

    def test_delete_session_delegates(self, agent_service):
        agent_service.chat_service.delete_session = MagicMock(return_value=True)
        result = agent_service.delete_session("session-1")
        agent_service.chat_service.delete_session.assert_called_once_with("session-1")
        assert result is True

    def test_session_control_delegates(self, agent_service):
        agent_service.chat_service.revert_session = MagicMock(return_value=2)
        agent_service.chat_service.edit_message = MagicMock(return_value=True)
        agent_service.chat_service.abort_session = MagicMock(return_value=False)
        agent_service.chat_service.get_session_status = MagicMock(return_value="idle")
        agent_service.chat_service.get_all_session_status = MagicMock(return_value={"s": "idle"})

        assert agent_service.revert_session("session-1", "message-1") == 2
        assert agent_service.edit_message("message-1", "updated") is True
        assert agent_service.abort_session("session-1") is False
        assert agent_service.get_session_status("session-1") == "idle"
        assert agent_service.get_all_session_status() == {"s": "idle"}


class TestContextManager:
    @pytest.mark.asyncio
    async def test_context_tracks_session_id(self):
        manager = ContextManager(config={"compaction_enabled": False})

        async def load_history(session_id):
            return []

        ctx = await manager.get_or_create(
            "session-1", "wiki-1", history_loader=load_history,
        )

        assert ctx.session_id == "session-1"


class TestAgentServiceConfirmations:
    def test_list_confirmations_merges_chat_and_wiki(self, agent_service):
        agent_service.wiki_service.list_confirmations = MagicMock(
            return_value={"wiki": [{"id": "w1"}]},
        )
        agent_service.chat_service.list_confirmations = MagicMock(
            return_value={"skill_actions": [{"id": "s1"}]},
        )

        result = agent_service.list_confirmations("wiki-1")

        assert result == {
            "wiki": [{"id": "w1"}],
            "skill_actions": [{"id": "s1"}],
        }

    @pytest.mark.asyncio
    async def test_approve_confirmation_prefers_chat_service(self, agent_service):
        agent_service.chat_service.approve_confirmation = AsyncMock(
            return_value={"status": "executed"},
        )
        agent_service.wiki_service.approve_confirmation = AsyncMock()

        result = await agent_service.approve_confirmation("s1", "wiki-1")

        assert result == {"status": "executed"}
        agent_service.wiki_service.approve_confirmation.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_confirmation_falls_back_to_wiki_service(self, agent_service):
        agent_service.chat_service.approve_confirmation = AsyncMock(
            return_value={"status": "error", "error": "Invalid confirmation ID: w1"},
        )
        agent_service.wiki_service.approve_confirmation = AsyncMock(
            return_value={"status": "executed"},
        )

        result = await agent_service.approve_confirmation("w1", "wiki-1")

        assert result == {"status": "executed"}
        agent_service.wiki_service.approve_confirmation.assert_awaited_once()


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
