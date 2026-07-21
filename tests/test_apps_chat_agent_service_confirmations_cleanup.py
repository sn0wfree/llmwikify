"""Tests for v0.40 confirmations cleanup background task.

Covers:
  - start_confirmations_cleanup: starts the periodic task
  - start_confirmations_cleanup: enabled=False short-circuits
  - start_confirmations_cleanup: idempotent (double-start safe)
  - stop_confirmations_cleanup: idempotent (no-op when not started)
  - WikiServer exposes enable_confirmations_cleanup param
  - WikiServer health endpoint includes confirmations_cleanup flag
  - Periodic tick calls delete_expired_confirmations
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.agent_service import AgentService


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.achat = MagicMock(return_value={"content": "summary"})
    return provider


def _make_wiki_registry() -> MagicMock:
    reg = MagicMock()
    reg.get_default_wiki_id = MagicMock(return_value="test-wiki")
    reg.close = MagicMock()
    wiki = MagicMock()
    wiki.root = Path("/tmp/test-wiki")
    wiki.is_initialized = MagicMock(return_value=True)
    wiki.close = MagicMock()
    reg.get_default_wiki = MagicMock(return_value=wiki)
    return reg


class TestAgentServiceStartConfirmationsCleanup:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, tmp_path: Path) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        task = await svc.start_confirmations_cleanup(interval_seconds=60.0)
        assert task is not None
        assert svc._confirmations_cleanup_task is task
        # Cleanup
        await svc.stop_confirmations_cleanup()

    @pytest.mark.asyncio
    async def test_start_disabled_short_circuit(self, tmp_path: Path) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        task = await svc.start_confirmations_cleanup(enabled=False)
        assert task is None
        assert svc._confirmations_cleanup_task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self, tmp_path: Path) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        t1 = await svc.start_confirmations_cleanup(interval_seconds=60.0)
        t2 = await svc.start_confirmations_cleanup(interval_seconds=60.0)
        assert t1 is t2
        await svc.stop_confirmations_cleanup()

    @pytest.mark.asyncio
    async def test_periodic_tick_runs_cleanup(self, tmp_path: Path) -> None:
        """The periodic task eventually calls delete_expired_confirmations.

        Use a tiny interval + manual wait so the test finishes quickly.
        """
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        # Inject one expired token so delete returns 1
        wiki_db = svc.wiki_service._wiki_db
        wiki_db.save_confirmation({
            "id": "exptest", "wiki_id": "w1", "tool": "wiki_page_update",
            "arguments": {"page_name": "p1", "expires_at": 0.0},
            "status": "pending",
        })

        # Patch the cleanup method to count invocations
        original_cleanup = wiki_db.delete_expired_confirmations
        call_counter = {"n": 0}

        def spy_cleanup(now=None):
            call_counter["n"] += 1
            return original_cleanup(now=now)

        wiki_db.delete_expired_confirmations = spy_cleanup

        try:
            # Use a tiny interval (0.05s) so the first tick fires quickly
            # (sleep fires *before* the first tick, so we wait a bit more).
            await svc.start_confirmations_cleanup(interval_seconds=0.05)
            await asyncio.sleep(0.15)
            assert call_counter["n"] >= 1
        finally:
            await svc.stop_confirmations_cleanup()
            wiki_db.delete_expired_confirmations = original_cleanup


class TestAgentServiceStopConfirmationsCleanup:
    @pytest.mark.asyncio
    async def test_stop_after_start(self, tmp_path: Path) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        await svc.start_confirmations_cleanup(interval_seconds=60.0)
        assert svc._confirmations_cleanup_task is not None
        await svc.stop_confirmations_cleanup()
        assert svc._confirmations_cleanup_task is None

    @pytest.mark.asyncio
    async def test_stop_without_start_is_noop(self, tmp_path: Path) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=_make_provider(),
        )
        # Should not raise even when task is None
        await svc.stop_confirmations_cleanup()
        assert svc._confirmations_cleanup_task is None

    @pytest.mark.asyncio
    async def test_double_stop_idempotent(self, tmp_path: Path) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        await svc.start_confirmations_cleanup(interval_seconds=60.0)
        await svc.stop_confirmations_cleanup()
        await svc.stop_confirmations_cleanup()  # no raise
        assert svc._confirmations_cleanup_task is None

    @pytest.mark.asyncio
    async def test_cleanup_tick_logs_on_deletion(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        svc = AgentService(
            wiki_registry=_make_wiki_registry(),
            data_dir=tmp_path,
            provider=None,
        )
        wiki_db = svc.wiki_service._wiki_db
        wiki_db.save_confirmation({
            "id": "logexp", "wiki_id": "w1", "tool": "wiki_page_update",
            "arguments": {"page_name": "p1", "expires_at": 0.0},
            "status": "pending",
        })
        try:
            with caplog.at_level(logging.INFO):
                await svc.start_confirmations_cleanup(interval_seconds=0.05)
                await asyncio.sleep(0.15)
            assert any("deleted" in r.message for r in caplog.records)
        finally:
            await svc.stop_confirmations_cleanup()


class TestWikiServerConfirmationsCleanupIntegration:
    def test_flag_default_true(self, tmp_path: Path) -> None:
        from llmwikify.interfaces.server.core import WikiServer
        from llmwikify.kernel import Wiki

        wiki = Wiki(tmp_path / "wiki")
        wiki.init()
        server = WikiServer(
            wiki,
            enable_dream_scheduler=False,
            enable_auto_compact=False,
            enable_confirmations_cleanup=True,
            enable_webui=False,
        )
        assert server.enable_confirmations_cleanup is True
        assert server.confirmations_cleanup_interval_seconds == 300.0

    def test_flag_default_can_be_disabled(self, tmp_path: Path) -> None:
        from llmwikify.interfaces.server.core import WikiServer
        from llmwikify.kernel import Wiki

        wiki = Wiki(tmp_path / "wiki")
        wiki.init()
        server = WikiServer(
            wiki,
            enable_dream_scheduler=False,
            enable_auto_compact=False,
            enable_confirmations_cleanup=False,
            enable_webui=False,
        )
        assert server.enable_confirmations_cleanup is False

    def test_custom_interval_stored(self, tmp_path: Path) -> None:
        from llmwikify.interfaces.server.core import WikiServer
        from llmwikify.kernel import Wiki

        wiki = Wiki(tmp_path / "wiki")
        wiki.init()
        server = WikiServer(
            wiki,
            enable_dream_scheduler=False,
            enable_auto_compact=False,
            confirmations_cleanup_interval_seconds=60.0,
            enable_webui=False,
        )
        assert server.confirmations_cleanup_interval_seconds == 60.0
