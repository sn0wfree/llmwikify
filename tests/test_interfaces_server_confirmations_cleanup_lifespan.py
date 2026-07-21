"""Tests for v0.40 confirmations cleanup lifespan integration.

Covers:
  - WikiServer accepts enable_confirmations_cleanup (default True)
  - lifespan startup calls start_confirmations_cleanup (with config interval)
  - lifespan startup skips when enable_confirmations_cleanup=False
  - lifespan startup honors config-level enabled=false (even when flag True)
  - lifespan shutdown calls stop_confirmations_cleanup
  - health endpoint exposes confirmations_cleanup feature flag
"""

from __future__ import annotations

import json
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


def test_memory_config_loads_confirmations_cleanup_section(
    tmp_path: Path,
) -> None:
    from llmwikify.apps.chat.memory.memory_config import (
        DEFAULT_CONFIG_FILENAME,
        load_memory_config,
    )

    cfg_path = tmp_path / DEFAULT_CONFIG_FILENAME
    cfg_path.write_text(json.dumps({
        "confirmations_cleanup": {
            "enabled": False,
            "interval_seconds": 60.0,
        },
    }))
    cfg = load_memory_config(tmp_path)
    assert cfg.confirmations_cleanup["enabled"] is False
    assert cfg.confirmations_cleanup["interval_seconds"] == 60.0


def test_memory_config_default_confirmations_cleanup_section(
    tmp_path: Path,
) -> None:
    from llmwikify.apps.chat.memory.memory_config import load_memory_config

    cfg = load_memory_config(tmp_path)
    assert cfg.confirmations_cleanup["enabled"] is True
    assert cfg.confirmations_cleanup["interval_seconds"] == 300.0


@pytest.mark.asyncio
async def test_lifespan_startup_invokes_start_confirmations_cleanup(
    tmp_path: Path,
) -> None:
    """Smoke: when enable_confirmations_cleanup=True + config enabled, start called."""
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
    server._agent_service.data_dir = tmp_path
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
    # Default interval=300.0 must be passed through
    call_kwargs = (
        server._agent_service.start_confirmations_cleanup.await_args.kwargs
    )
    assert call_kwargs["interval_seconds"] == 300.0
    assert call_kwargs["enabled"] is True
    assert server._agent_service.stop_confirmations_cleanup.await_count == 1


@pytest.mark.asyncio
async def test_lifespan_reads_interval_from_memory_config(
    tmp_path: Path,
) -> None:
    """Custom interval in memory_config.json flows through to start_confirmations_cleanup."""
    from llmwikify.apps.chat.memory.memory_config import DEFAULT_CONFIG_FILENAME
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
    server._agent_service.data_dir = tmp_path
    (tmp_path / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
        "confirmations_cleanup": {"enabled": True, "interval_seconds": 42.0},
    }))
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
    call_kwargs = (
        server._agent_service.start_confirmations_cleanup.await_args.kwargs
    )
    assert call_kwargs["interval_seconds"] == 42.0


@pytest.mark.asyncio
async def test_lifespan_skips_start_when_wikiserver_flag_false(
    tmp_path: Path,
) -> None:
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


@pytest.mark.asyncio
async def test_lifespan_respects_config_disable(tmp_path: Path) -> None:
    """Even when WikiServer flag True, config-level disable wins (match auto_compact)."""
    from llmwikify.apps.chat.memory.memory_config import DEFAULT_CONFIG_FILENAME
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
    server._agent_service.data_dir = tmp_path
    (tmp_path / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
        "confirmations_cleanup": {"enabled": False},
    }))
    server._agent_service.start_confirmations_cleanup = AsyncMock()
    server._agent_service.stop_confirmations_cleanup = AsyncMock()
    server._agent_service.start_auto_compact = AsyncMock()
    server._agent_service.stop_auto_compact = AsyncMock()
    server._agent_service.start_dream_scheduler = AsyncMock()
    server._agent_service.stop_dream_scheduler = AsyncMock()
    async with server.app.router.lifespan_context(server.app):
        pass
    assert server._agent_service.start_confirmations_cleanup.await_count == 0


def test_health_endpoint_exposes_confirmations_cleanup_flag(
    tmp_path: Path,
) -> None:
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
