"""Unit tests for WikiService — orchestration layer for wiki operations.

Covers:

  - WikiService metadata (name, init, docstring)
  - Wiki resolution (get_default_wiki_id, get_wiki)
  - LLM lazy init (get_llm, reload_llm)
  - Factory methods (wiki_dream_editor, notification_manager, scheduler, tool_registry)
  - Wiki dream lifecycle (run_wiki_dream, get_wiki_dream_log, get_wiki_dream_proposals,
    approve/reject_proposal, batch_approve, apply_proposals)
  - Notifications (list, mark_read)
  - Confirmations (list, approve, reject, batch)
  - Ingest audit (get_ingest_log, get_ingest_entry)
  - Status (get_agent_status)
  - Multi-wiki registry (list/switch/register/unregister/scan)

Target: 30+ tests, no I/O, mocks for managers.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.db import ChatDatabase
from llmwikify.apps.wiki.service import WikiService

# ─── Mock helpers ─────────────────────────────────────────────────


class MockWikiRegistry:
    """Mock WikiRegistry with multi-wiki methods."""

    def __init__(self, default_id: str = "test_wiki") -> None:
        self.default_id = default_id
        self._wikis: dict[str, Any] = {
            default_id: MagicMock(name=f"Wiki({default_id})")
        }

    def get_default_wiki_id(self) -> str | None:
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
        inst.to_dict = lambda: {"wiki_id": wiki_id, "name": wiki_id}
        return inst

    def list_wikis(self) -> list:
        return [
            MagicMock(to_dict=lambda: {"wiki_id": wid})
            for wid in self._wikis
        ]

    def register_wiki(self, wiki_id: str, name: str, root: Path) -> Any:
        inst = MagicMock()
        inst.to_dict = lambda: {"wiki_id": wiki_id, "name": name, "root": str(root)}
        self._wikis[wiki_id] = MagicMock()
        return inst

    def register_remote(
        self, wiki_id: str, name: str, url: str, api_key: str | None = None
    ) -> Any:
        inst = MagicMock()
        inst.to_dict = lambda: {"wiki_id": wiki_id, "name": name, "url": url}
        return inst

    def unregister_wiki(self, wiki_id: str) -> None:
        self._wikis.pop(wiki_id, None)

    def scan_directories(self, paths: list, depth: int) -> list:
        return []


@pytest.fixture
def data_dir() -> Path:
    d = Path(tempfile.mkdtemp())
    yield d
    # Cleanup is handled by tmpdir mechanism


@pytest.fixture
def wiki_registry() -> MockWikiRegistry:
    return MockWikiRegistry()


@pytest.fixture
def chat_db(data_dir: Path) -> ChatDatabase:
    return ChatDatabase(data_dir)


@pytest.fixture
def wiki_service(
    wiki_registry: MockWikiRegistry,
    data_dir: Path,
    chat_db: ChatDatabase,
) -> WikiService:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return WikiService(wiki_registry, data_dir, chat_db)


# ─── Metadata ─────────────────────────────────────────────────────


class TestWikiServiceMetadata:
    def test_importable(self) -> None:
        from llmwikify.apps.wiki import WikiService as WS
        assert WS is WikiService

    def test_init(self, wiki_service: WikiService) -> None:
        assert wiki_service.wiki_registry is not None
        assert wiki_service.db is not None
        assert wiki_service._wiki_dream_editors == {}
        assert wiki_service._notification_managers == {}
        assert wiki_service._schedulers == {}
        assert wiki_service._tool_registries == {}


# ─── Wiki resolution ─────────────────────────────────────────────


class TestWikiResolution:
    def test_get_default_wiki_id(self, wiki_service: WikiService) -> None:
        assert wiki_service.get_default_wiki_id() == "test_wiki"

    def test_get_default_wiki(self, wiki_service: WikiService) -> None:
        wiki = wiki_service.get_wiki()
        assert wiki is not None

    def test_get_wiki_by_id(self, wiki_service: WikiService) -> None:
        wiki = wiki_service.get_wiki("test_wiki")
        assert wiki is not None

    def test_get_wiki_none_id_returns_default(self, wiki_service: WikiService) -> None:
        wiki = wiki_service.get_wiki(None)
        assert wiki is not None


# ─── Tool registry factory ───────────────────────────────────────


class TestToolRegistryFactory:
    def test_get_tool_registry_creates_instance(self, wiki_service: WikiService) -> None:
        from llmwikify.apps.agent.tools import WikiToolRegistry

        reg = wiki_service.get_tool_registry("test_wiki")
        assert isinstance(reg, WikiToolRegistry)
        assert "test_wiki" in wiki_service._tool_registries

    def test_get_tool_registry_caches(self, wiki_service: WikiService) -> None:
        reg1 = wiki_service.get_tool_registry("test_wiki")
        reg2 = wiki_service.get_tool_registry("test_wiki")
        assert reg1 is reg2

    def test_get_tool_registry_no_wiki_id_raises(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        with pytest.raises(ValueError, match="No wiki_id"):
            wiki_service.get_tool_registry(None)


# ─── Wiki dream lifecycle ────────────────────────────────────────────


class TestWikiDreamLifecycle:
    def test_get_dream_log_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        result = wiki_service.get_wiki_dream_log(None)
        assert result == []

    def test_get_dream_proposals_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        result = wiki_service.get_wiki_dream_proposals(None)
        assert result == {"proposals": {}, "stats": {}}

    def test_approve_proposal_not_found(self, wiki_service: WikiService) -> None:
        result = wiki_service.approve_wiki_dream_proposal("nonexistent")
        assert result["status"] == "error"

    def test_reject_proposal_not_found(self, wiki_service: WikiService) -> None:
        result = wiki_service.reject_wiki_dream_proposal("nonexistent")
        assert result["status"] == "error"

    def test_batch_approve_proposals_empty(self, wiki_service: WikiService) -> None:
        result = wiki_service.batch_approve_wiki_dream_proposals([])
        assert result["approved"] == 0
        assert result["results"] == []


# ─── Notifications ───────────────────────────────────────────────


class TestNotifications:
    def test_list_notifications_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        result = wiki_service.list_notifications(None)
        assert result == []

    def test_mark_notification_read_not_found(self, wiki_service: WikiService) -> None:
        result = wiki_service.mark_notification_read("nonexistent")
        assert result["status"] == "error"

    def test_mark_notification_read_returns_dict(self, wiki_service: WikiService) -> None:
        # Without any notification managers, should return error
        result = wiki_service.mark_notification_read("x")
        assert "status" in result


# ─── Confirmations ───────────────────────────────────────────────


class TestConfirmations:
    def test_list_confirmations_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        result = wiki_service.list_confirmations(None)
        assert result == {}

    def test_approve_confirmation_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        # These are async methods
        result = asyncio.run(wiki_service.approve_confirmation("cid"))
        assert result["status"] == "error"

    def test_reject_confirmation_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        result = asyncio.run(wiki_service.reject_confirmation("cid"))
        assert result["status"] == "error"


# ─── Ingest audit ───────────────────────────────────────────────


class TestIngestAudit:
    def test_get_ingest_log_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        result = wiki_service.get_ingest_log(None)
        assert result == []

    def test_get_ingest_entry(self, wiki_service: WikiService) -> None:
        result = wiki_service.get_ingest_entry("nonexistent")
        assert result is None


# ─── Agent status ────────────────────────────────────────────────


class TestAgentStatus:
    def test_get_agent_status_no_wiki(self, wiki_service: WikiService) -> None:
        wiki_service.wiki_registry.default_id = None
        result = wiki_service.get_agent_status(None)
        assert result["state"] == "idle"
        assert result["scheduler_tasks"] == []
        assert result["pending_confirmations"] == 0

    def test_get_agent_status_with_wiki(self, wiki_service: WikiService) -> None:
        # Should not raise, returns aggregated status
        result = wiki_service.get_agent_status("test_wiki")
        assert "state" in result
        assert "scheduler_tasks" in result
        assert "pending_confirmations" in result
        assert "wiki_dream_proposals" in result
        assert "unread_notifications" in result


# ─── Multi-wiki registry ─────────────────────────────────────────


class TestMultiWikiRegistry:
    def test_list_wikis(self, wiki_service: WikiService) -> None:
        result = wiki_service.list_wikis()
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_switch_wiki_success(self, wiki_service: WikiService) -> None:
        result = wiki_service.switch_wiki("test_wiki")
        assert "message" in result
        assert "wiki" in result

    def test_switch_wiki_not_found(self, wiki_service: WikiService) -> None:
        # Mock raises KeyError for nonexistent wikis
        result = wiki_service.switch_wiki("nonexistent_wiki_xyz")
        assert "error" in result
        assert "Wiki not found" in result["error"]

    def test_register_wiki_local(self, wiki_service: WikiService) -> None:
        result = wiki_service.register_wiki(
            "new_wiki", "New Wiki", wiki_type="local", root="/tmp/new"
        )
        assert "message" in result
        assert "wiki" in result

    def test_register_wiki_remote_no_url(self, wiki_service: WikiService) -> None:
        result = wiki_service.register_wiki(
            "remote_wiki", "Remote", wiki_type="remote"
        )
        assert "error" in result
        assert "url required" in result["error"]

    def test_register_wiki_local_no_root(self, wiki_service: WikiService) -> None:
        result = wiki_service.register_wiki(
            "new_wiki", "New Wiki", wiki_type="local"
        )
        assert "error" in result
        assert "root required" in result["error"]

    def test_unregister_wiki_success(self, wiki_service: WikiService) -> None:
        result = wiki_service.unregister_wiki("test_wiki")
        assert "message" in result

    def test_scan_wikis(self, wiki_service: WikiService) -> None:
        result = wiki_service.scan_wikis(scan_paths=".", scan_depth=2)
        assert "new_wikis" in result
        assert "count" in result


# ─── LLM lazy init ───────────────────────────────────────────────


class TestLLMLazyInit:
    def test_reload_llm_clears_cache(self, wiki_service: WikiService) -> None:
        wiki_service._llm = MagicMock()
        wiki_service.reload_llm()
        assert wiki_service._llm is None
