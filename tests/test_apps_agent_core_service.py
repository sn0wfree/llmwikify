"""Unit tests for AgentService — deprecated wrapper.

Verifies that AgentService properly delegates all methods to
ChatService + WikiService. Also verifies that the
DeprecationWarning is emitted on instantiation.

Covers:

  - DeprecationWarning emission
  - Initialization creates both WikiService + ChatService
  - chat() delegates to chat_service.chat()
  - All wiki methods delegate to wiki_service
  - All chat methods delegate to chat_service
  - _get_tool_registry and _get_llm backward-compat accessors
  - db attribute still works for backward compat

Target: 20+ tests, no I/O, mocks for managers.
"""

from __future__ import annotations

import asyncio
import tempfile
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.agent.core.service import AgentService


# ─── Mock WikiRegistry ─────────────────────────────────────────────


class MockWikiRegistry:
    def __init__(self) -> None:
        self.default_id = "test_wiki"
        self._wikis: dict[str, Any] = {
            "test_wiki": MagicMock(name="Wiki(test_wiki)")
        }

    def get_default_wiki_id(self) -> str:
        return self.default_id

    def get_default_wiki(self) -> Any:
        return self._wikis.get(self.default_id)

    def get_wiki(self, wiki_id: str) -> Any:
        return self._wikis.get(wiki_id)

    def get_wiki_instance(self, wiki_id: str) -> Any:
        if wiki_id not in self._wikis:
            raise KeyError(wiki_id)
        inst = MagicMock()
        inst.name = wiki_id
        inst.root = Path(f"/tmp/{wiki_id}")
        inst.to_dict = lambda: {"wiki_id": wiki_id}
        return inst

    def list_wikis(self) -> list:
        return [MagicMock(to_dict=lambda: {"wiki_id": "test_wiki"})]

    def register_wiki(
        self, wiki_id: str, name: str, root: Path
    ) -> Any:
        inst = MagicMock()
        inst.to_dict = lambda: {"wiki_id": wiki_id, "name": name}
        return inst

    def register_remote(
        self, wiki_id: str, name: str, url: str, api_key: str | None = None
    ) -> Any:
        inst = MagicMock()
        inst.to_dict = lambda: {"wiki_id": wiki_id, "name": name}
        return inst

    def unregister_wiki(self, wiki_id: str) -> None:
        self._wikis.pop(wiki_id, None)

    def scan_directories(self, paths: list, depth: int) -> list:
        return []


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def data_dir() -> Path:
    return Path(tempfile.mkdtemp())


@pytest.fixture
def agent_service(data_dir: Path) -> AgentService:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return AgentService(MockWikiRegistry(), data_dir)


# ─── DeprecationWarning ──────────────────────────────────────────


class TestDeprecationWarning:
    def test_init_emits_deprecation(self, data_dir: Path) -> None:
        with pytest.warns(
            DeprecationWarning,
            match="AgentService is deprecated",
        ):
            AgentService(MockWikiRegistry(), data_dir)


# ─── Initialization ──────────────────────────────────────────────


class TestInit:
    def test_init_creates_subservices(
        self, agent_service: AgentService
    ) -> None:
        from llmwikify.apps.wiki.service import WikiService
        from llmwikify.apps.chat.agent.service import ChatService

        assert isinstance(agent_service.wiki_service, WikiService)
        assert isinstance(agent_service.chat_service, ChatService)

    def test_db_attribute_exists(
        self, agent_service: AgentService
    ) -> None:
        assert agent_service.db is not None

    def test_data_dir_attribute(
        self, agent_service: AgentService
    ) -> None:
        assert agent_service.data_dir is not None


# ─── Chat delegation ─────────────────────────────────────────────


class TestChatDelegation:
    def test_reload_llm_delegates(
        self, agent_service: AgentService
    ) -> None:
        agent_service.wiki_service._llm = MagicMock()
        agent_service.reload_llm()
        assert agent_service.wiki_service._llm is None

    @pytest.mark.asyncio
    async def test_chat_delegates_to_chat_service(
        self, agent_service: AgentService
    ) -> None:
        # Mock the chat_service.chat to return known events
        async def fake_chat(*args, **kwargs):
            yield {"type": "message_delta", "content": "hi"}
            yield {"type": "done", "final_response": "ok"}

        agent_service.chat_service.chat = fake_chat
        events = []
        async for event in agent_service.chat(message="test"):
            events.append(event)
        assert any(e["type"] == "done" for e in events)

    @pytest.mark.asyncio
    async def test_approve_confirmation_and_continue_delegates(
        self, agent_service: AgentService
    ) -> None:
        async def fake_continue(*args, **kwargs):
            yield {"type": "done", "final_response": "ok"}

        agent_service.chat_service.approve_confirmation_continue = (
            fake_continue
        )
        events = []
        async for event in agent_service.approve_confirmation_and_continue(
            confirmation_id="c1", session_id="s1"
        ):
            events.append(event)
        assert any(e["type"] == "done" for e in events)


# ─── Wiki delegation ─────────────────────────────────────────────


class TestWikiDelegation:
    def test_run_dream_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"status": "ok", "pending_review": 0}
        agent_service.wiki_service.run_dream = AsyncMock(
            return_value=expected
        )
        result = asyncio.run(agent_service.run_dream("test_wiki"))
        assert result == expected

    def test_get_dream_log_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = [{"id": "1", "action": "edit"}]
        agent_service.wiki_service.get_dream_log = MagicMock(
            return_value=expected
        )
        result = agent_service.get_dream_log("test_wiki", limit=10)
        assert result == expected

    def test_get_dream_proposals_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"proposals": {}, "stats": {}}
        agent_service.wiki_service.get_dream_proposals = MagicMock(
            return_value=expected
        )
        result = agent_service.get_dream_proposals("test_wiki")
        assert result == expected

    def test_approve_proposal_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"status": "ok", "id": "p1"}
        agent_service.wiki_service.approve_proposal = MagicMock(
            return_value=expected
        )
        result = agent_service.approve_proposal("p1")
        assert result == expected

    def test_reject_proposal_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"status": "ok", "id": "p1"}
        agent_service.wiki_service.reject_proposal = MagicMock(
            return_value=expected
        )
        result = agent_service.reject_proposal("p1")
        assert result == expected

    def test_batch_approve_proposals_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"approved": 2, "results": []}
        agent_service.wiki_service.batch_approve_proposals = MagicMock(
            return_value=expected
        )
        result = agent_service.batch_approve_proposals(["p1", "p2"])
        assert result == expected

    def test_apply_proposals_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"applied": 1}
        agent_service.wiki_service.apply_proposals = AsyncMock(
            return_value=expected
        )
        result = asyncio.run(agent_service.apply_proposals("test_wiki"))
        assert result == expected

    def test_list_notifications_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = [{"id": "n1", "message": "test"}]
        agent_service.wiki_service.list_notifications = MagicMock(
            return_value=expected
        )
        result = agent_service.list_notifications("test_wiki")
        assert result == expected

    def test_mark_notification_read_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"status": "ok", "notification_id": "n1"}
        agent_service.wiki_service.mark_notification_read = MagicMock(
            return_value=expected
        )
        result = agent_service.mark_notification_read("n1")
        assert result == expected

    def test_list_confirmations_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"group1": [{"id": "c1"}]}
        agent_service.wiki_service.list_confirmations = MagicMock(
            return_value=expected
        )
        result = agent_service.list_confirmations("test_wiki")
        assert result == expected

    def test_approve_confirmation_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"status": "ok"}
        agent_service.wiki_service.approve_confirmation = AsyncMock(
            return_value=expected
        )
        result = asyncio.run(
            agent_service.approve_confirmation("c1", "test_wiki")
        )
        assert result == expected

    def test_reject_confirmation_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"status": "rejected"}
        agent_service.wiki_service.reject_confirmation = AsyncMock(
            return_value=expected
        )
        result = asyncio.run(
            agent_service.reject_confirmation("c1", "test_wiki")
        )
        assert result == expected

    def test_batch_approve_confirmations_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"approved": 1, "results": []}
        agent_service.wiki_service.batch_approve_confirmations = (
            AsyncMock(return_value=expected)
        )
        result = asyncio.run(
            agent_service.batch_approve_confirmations(
                ["c1"], "test_wiki"
            )
        )
        assert result == expected

    def test_get_ingest_log_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = [{"id": "i1"}]
        agent_service.wiki_service.get_ingest_log = MagicMock(
            return_value=expected
        )
        result = agent_service.get_ingest_log("test_wiki")
        assert result == expected

    def test_get_ingest_entry_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"id": "i1", "tool": "wiki_ingest"}
        agent_service.wiki_service.get_ingest_entry = MagicMock(
            return_value=expected
        )
        result = agent_service.get_ingest_entry("i1")
        assert result == expected

    def test_get_agent_status_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = {"state": "idle", "scheduler_tasks": []}
        agent_service.wiki_service.get_agent_status = MagicMock(
            return_value=expected
        )
        result = agent_service.get_agent_status("test_wiki")
        assert result == expected


# ─── Internal accessors ───────────────────────────────────────────


class TestInternalAccessors:
    def test_get_tool_registry_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = MagicMock()
        agent_service.wiki_service.get_tool_registry = MagicMock(
            return_value=expected
        )
        result = agent_service._get_tool_registry("test_wiki")
        assert result is expected

    def test_get_llm_delegates(
        self, agent_service: AgentService
    ) -> None:
        expected = MagicMock()
        agent_service.wiki_service.get_llm = MagicMock(
            return_value=expected
        )
        result = agent_service._get_llm()
        assert result is expected


# ─── Backward-compat: db attribute ───────────────────────────────


class TestBackwardCompatDB:
    def test_db_is_chatdatabase(
        self, agent_service: AgentService
    ) -> None:
        from llmwikify.apps.chat.db import ChatDatabase

        assert isinstance(agent_service.db, ChatDatabase)

    def test_db_sessions_table_exists(
        self, agent_service: AgentService
    ) -> None:
        stats = agent_service.db.get_db_stats()
        assert "autoresearch_sessions" in stats["tables"]
        assert "chat_sessions" in stats["tables"]
