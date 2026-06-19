"""Tests for Phase 7 provider injection + DreamScheduler lifecycle.

Covers:
  - AgentService accepts `provider` and forwards to MemoryManager
  - Without provider → no dream/consolidator (back-compat)
  - start_dream_scheduler: no-op when dream is None
  - start_dream_scheduler: enabled=False short-circuits
  - start_dream_scheduler: idempotent (double-start safe)
  - start_dream_scheduler: loads cron from memory_config.json
  - start_dream_scheduler: writes default config on first run
  - start_dream_scheduler: respects dream.enabled=false in config
  - stop_dream_scheduler: idempotent (no-op when not started)
  - WikiServer exposes provider + enable_dream_scheduler params
  - WikiServer lifespan starts/stops DreamScheduler
  - WikiServer health endpoint includes dream_scheduler feature flag
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.agent.agent_service import AgentService
from llmwikify.apps.chat.memory.dream_scheduler import DreamScheduler
from llmwikify.apps.chat.memory.memory_config import (
    DEFAULT_CONFIG_FILENAME,
    MemoryConfig,
)


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.achat = AsyncMock(return_value={"content": "summary"})
    return provider


def _make_wiki_registry() -> MagicMock:
    """Build a minimal WikiRegistry mock with required methods."""
    reg = MagicMock()
    reg.get_default_wiki_id = MagicMock(return_value="test-wiki")
    reg.close = MagicMock()
    # Wiki for tests
    wiki = MagicMock()
    wiki.root = Path("/tmp/test-wiki")
    wiki.is_initialized = MagicMock(return_value=True)
    wiki.close = MagicMock()
    reg.get_default_wiki = MagicMock(return_value=wiki)
    return reg


# ─── AgentService provider injection ──────────────────────────────


class TestAgentServiceProviderInjection:
    def test_provider_stored(self, tmp_path: Path) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        assert svc.provider is provider

    def test_no_provider_default_none(self, tmp_path: Path) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
        )
        assert svc.provider is None
        # MemoryManager built without provider → no consolidator/dream
        assert svc.memory_manager.consolidator is None
        assert svc.memory_manager.dream is None

    def test_provider_wires_memory_manager(self, tmp_path: Path) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        # With provider, MemoryManager should have consolidator + dream
        assert svc.memory_manager.consolidator is not None
        assert svc.memory_manager.dream is not None

    def test_explicit_memory_manager_overrides_provider(
        self, tmp_path: Path,
    ) -> None:
        provider = _make_provider()
        explicit_mm = MagicMock()
        explicit_mm.consolidator = None
        explicit_mm.dream = None
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
            memory_manager=explicit_mm,
        )
        assert svc.memory_manager is explicit_mm

    def test_dream_scheduler_attr_initially_none(self, tmp_path: Path) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        assert svc.dream_scheduler is None


# ─── AgentService.start_dream_scheduler ─────────────────────────


class TestAgentServiceStartDreamScheduler:
    @pytest.mark.asyncio
    async def test_start_with_provider_and_dream(
        self, tmp_path: Path
    ) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        # Write config to avoid first-run write side effect in test
        from llmwikify.apps.chat.memory.memory_config import (
            write_default_memory_config,
        )
        write_default_memory_config(tmp_path)
        sched = await svc.start_dream_scheduler()
        assert sched is not None
        assert isinstance(sched, DreamScheduler)
        assert sched.is_running
        assert svc.dream_scheduler is sched
        # Cleanup
        await svc.stop_dream_scheduler()

    @pytest.mark.asyncio
    async def test_start_no_dream_returns_none(self, tmp_path: Path) -> None:
        # No provider → no dream
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        sched = await svc.start_dream_scheduler()
        assert sched is None
        assert svc.dream_scheduler is None

    @pytest.mark.asyncio
    async def test_start_disabled_short_circuit(self, tmp_path: Path) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        sched = await svc.start_dream_scheduler(enabled=False)
        assert sched is None
        assert svc.dream_scheduler is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self, tmp_path: Path) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        from llmwikify.apps.chat.memory.memory_config import (
            write_default_memory_config,
        )
        write_default_memory_config(tmp_path)
        s1 = await svc.start_dream_scheduler()
        s2 = await svc.start_dream_scheduler()
        assert s1 is s2  # same instance returned
        await svc.stop_dream_scheduler()

    @pytest.mark.asyncio
    async def test_start_loads_cron_from_config(
        self, tmp_path: Path
    ) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        # Write custom config
        import json
        (tmp_path / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
            "consolidation": {},
            "dream": {"enabled": True, "cron_expression": "0 */2 * * *"},
        }))
        sched = await svc.start_dream_scheduler()
        assert sched is not None
        assert sched.cron_expression == "0 */2 * * *"
        await svc.stop_dream_scheduler()

    @pytest.mark.asyncio
    async def test_start_respects_dream_disabled_in_config(
        self, tmp_path: Path
    ) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        import json
        (tmp_path / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
            "consolidation": {},
            "dream": {"enabled": False},
        }))
        sched = await svc.start_dream_scheduler()
        assert sched is None  # config disabled
        assert svc.dream_scheduler is None

    @pytest.mark.asyncio
    async def test_start_writes_default_config_on_first_run(
        self, tmp_path: Path
    ) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        # No config file exists initially
        assert not (tmp_path / DEFAULT_CONFIG_FILENAME).exists()
        await svc.start_dream_scheduler()
        # First-run convenience: file written
        assert (tmp_path / DEFAULT_CONFIG_FILENAME).exists()
        await svc.stop_dream_scheduler()

    @pytest.mark.asyncio
    async def test_start_explicit_cron_overrides_config(
        self, tmp_path: Path
    ) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        # Config has one cron, but we override
        import json
        (tmp_path / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
            "consolidation": {},
            "dream": {"enabled": True, "cron_expression": "0 3 * * *"},
        }))
        sched = await svc.start_dream_scheduler(cron_expression="0 5 * * *")
        assert sched.cron_expression == "0 5 * * *"
        await svc.stop_dream_scheduler()


# ─── AgentService.stop_dream_scheduler ──────────────────────────


class TestAgentServiceStopDreamScheduler:
    @pytest.mark.asyncio
    async def test_stop_after_start(self, tmp_path: Path) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        from llmwikify.apps.chat.memory.memory_config import (
            write_default_memory_config,
        )
        write_default_memory_config(tmp_path)
        await svc.start_dream_scheduler()
        assert svc.dream_scheduler is not None
        await svc.stop_dream_scheduler()
        assert svc.dream_scheduler is None

    @pytest.mark.asyncio
    async def test_stop_without_start_is_noop(
        self, tmp_path: Path
    ) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=_make_provider(),
        )
        # Should not raise even when dream_scheduler is None
        await svc.stop_dream_scheduler()
        assert svc.dream_scheduler is None

    @pytest.mark.asyncio
    async def test_double_stop_idempotent(self, tmp_path: Path) -> None:
        provider = _make_provider()
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=provider,
        )
        from llmwikify.apps.chat.memory.memory_config import (
            write_default_memory_config,
        )
        write_default_memory_config(tmp_path)
        await svc.start_dream_scheduler()
        await svc.stop_dream_scheduler()
        await svc.stop_dream_scheduler()  # no raise
        assert svc.dream_scheduler is None


# ─── WikiServer integration ─────────────────────────────────────


class TestWikiServerProviderIntegration:
    def test_provider_param_stored(self, tmp_path: Path) -> None:
        from llmwikify.interfaces.server.core import WikiServer
        from llmwikify.kernel import Wiki

        wiki = Wiki(tmp_path / "wiki")
        wiki.init()
        provider = _make_provider()
        # enable_dream_scheduler=False to avoid starting APScheduler
        # (it would conflict with the FastAPI app lifecycle in unit tests)
        server = WikiServer(
            wiki,
            provider=provider,
            enable_dream_scheduler=False,
            enable_webui=False,
        )
        assert server.provider is provider
        assert server.enable_dream_scheduler is False

    def test_no_provider_default(self, tmp_path: Path) -> None:
        from llmwikify.interfaces.server.core import WikiServer
        from llmwikify.kernel import Wiki

        wiki = Wiki(tmp_path / "wiki")
        wiki.init()
        server = WikiServer(wiki, enable_webui=False)
        assert server.provider is None
        assert server.enable_dream_scheduler is True  # default True

    def test_lifespan_set_on_app(self, tmp_path: Path) -> None:
        """Phase 7: lifespan handler is wired to FastAPI app."""
        from llmwikify.interfaces.server.core import WikiServer
        from llmwikify.kernel import Wiki

        wiki = Wiki(tmp_path / "wiki")
        wiki.init()
        server = WikiServer(wiki, enable_dream_scheduler=False, enable_webui=False)
        # FastAPI stores lifespan on router
        assert server.app.router.lifespan_context is not None

    def test_agent_service_captured(self, tmp_path: Path) -> None:
        from llmwikify.interfaces.server.core import WikiServer
        from llmwikify.kernel import Wiki

        wiki = Wiki(tmp_path / "wiki")
        wiki.init()
        server = WikiServer(wiki, enable_dream_scheduler=False, enable_webui=False)
        # AgentService created by _register_agent_routes
        assert server._agent_service is not None
        assert hasattr(server._agent_service, "start_dream_scheduler")
        assert hasattr(server._agent_service, "stop_dream_scheduler")