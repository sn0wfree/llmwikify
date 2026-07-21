"""Tests for v0.40 confirmations cleanup lifespan integration.

Covers:
  - WikiServer accepts enable_confirmations_cleanup (default True)
  - WikiServer accepts confirmations_cleanup_interval_seconds
  - lifespan startup calls start_confirmations_cleanup
  - lifespan startup skips when enable_confirmations_cleanup=False
  - lifespan shutdown calls stop_confirmations_cleanup
  - health endpoint exposes confirmations_cleanup feature flag
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_wiki(tmp_path: Path):
    from llmwikify.kernel import Wiki

    wiki = Wiki(tmp_path / "wiki")
    wiki.init()
    return wiki


def test_wikiserver_accepts_enable_confirmations_cleanup_param(
    tmp_path: Path,
) -> None:
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_confirmations_cleanup=False,
        enable_webui=False,
    )
    assert server.enable_confirmations_cleanup is False


def test_wikiserver_default_enable_confirmations_cleanup_is_true(
    tmp_path: Path,
) -> None:
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_webui=False,
    )
    assert server.enable_confirmations_cleanup is True
    assert server.confirmations_cleanup_interval_seconds == 300.0


@pytest.mark.asyncio
async def test_lifespan_startup_invokes_start_confirmations_cleanup(
    tmp_path: Path,
) -> None:
    """Smoke: when enable_confirmations_cleanup=True, start is called."""
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_confirmations_cleanup=True,
        enable_rest=False,
        enable_webui=False,
    )
    server._agent_service = MagicMock()
    server._agent_service.start_confirmations_cleanup = AsyncMock(
        return_value=MagicMock(),
    )
    server._agent_service.stop_confirmations_cleanup = AsyncMock()
    server._agent_service.start_auto_compact = AsyncMock()
    server._agent_service.stop_auto_compact = AsyncMock()
    server._agent_service.start_dream_scheduler = AsyncMock()
    server._agent_service.stop_dream_scheduler = AsyncMock()
    async with server.app.router.lifespan_context(server.app):
        pass
    assert server._agent_service.start_confirmations_cleanup.await_count == 1
    assert server._agent_service.stop_confirmations_cleanup.await_count == 1


@pytest.mark.asyncio
async def test_lifespan_skips_start_when_disabled(tmp_path: Path) -> None:
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_confirmations_cleanup=False,
        enable_rest=False,
        enable_webui=False,
    )
    server._agent_service = MagicMock()
    server._agent_service.start_confirmations_cleanup = AsyncMock()
    server._agent_service.stop_confirmations_cleanup = AsyncMock()
    server._agent_service.start_auto_compact = AsyncMock()
    server._agent_service.stop_auto_compact = AsyncMock()
    server._agent_service.start_dream_scheduler = AsyncMock()
    server._agent_service.stop_dream_scheduler = AsyncMock()
    async with server.app.router.lifespan_context(server.app):
        pass
    assert server._agent_service.start_confirmations_cleanup.await_count == 0
    # stop is still called for idempotent shutdown
    assert server._agent_service.stop_confirmations_cleanup.await_count == 1


def test_health_endpoint_exposes_confirmations_cleanup_flag(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_confirmations_cleanup=False,
        enable_webui=False,
    )
    with TestClient(server.app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "confirmations_cleanup" in body["features"]
    assert body["features"]["confirmations_cleanup"] is False
