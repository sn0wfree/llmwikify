"""Tests for WikiServer Phase 9 AutoCompact lifespan integration.

Covers:
  - WikiServer accepts enable_auto_compact (default True)
  - memory_config.json round-trip with auto_compact section
  - lifespan startup calls start_auto_compact when enabled + provider present
  - lifespan startup skips when enable_auto_compact=False
  - lifespan shutdown calls stop_auto_compact
  - health endpoint exposes auto_compact feature flag
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_provider() -> MagicMock:
    p = MagicMock()
    p.achat = AsyncMock(return_value={"content": "summary"})
    return p


def _make_wiki(tmp_path: Path):
    from llmwikify.kernel import Wiki

    wiki = Wiki(tmp_path / "wiki")
    wiki.init()
    return wiki


def test_wikiserver_accepts_enable_auto_compact_param(tmp_path: Path) -> None:
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_webui=False,
    )
    assert server.enable_auto_compact is False


def test_wikiserver_default_enable_auto_compact_is_true(tmp_path: Path) -> None:
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_webui=False,
    )
    assert server.enable_auto_compact is True


def test_memory_config_loads_auto_compact_section(tmp_path: Path) -> None:
    from llmwikify.apps.chat.memory.memory_config import (
        DEFAULT_CONFIG_FILENAME,
        load_memory_config,
    )

    cfg_path = tmp_path / DEFAULT_CONFIG_FILENAME
    cfg_path.write_text(json.dumps({
        "auto_compact": {
            "enabled": False,
            "ttl_minutes": 90,
            "interval_seconds": 600.0,
        },
    }))
    cfg = load_memory_config(tmp_path)
    assert cfg.auto_compact["enabled"] is False
    assert cfg.auto_compact["ttl_minutes"] == 90
    assert cfg.auto_compact["interval_seconds"] == 600.0


def test_memory_config_default_auto_compact_section(tmp_path: Path) -> None:
    from llmwikify.apps.chat.memory.memory_config import load_memory_config

    cfg = load_memory_config(tmp_path)
    assert cfg.auto_compact["enabled"] is True
    assert cfg.auto_compact["ttl_minutes"] == 30
    assert cfg.auto_compact["interval_seconds"] == 300.0


@pytest.mark.asyncio
async def test_lifespan_startup_invokes_start_auto_compact(tmp_path: Path) -> None:
    """Smoke: when enable_auto_compact=True + provider, start is called."""
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        provider=_make_provider(),
        enable_dream_scheduler=False,
        enable_auto_compact=True,
        enable_rest=False,
        enable_webui=False,
    )
    # Stub the AgentService methods so we don't actually spawn tasks.
    # enable_rest=False above prevents real AgentService creation; we
    # attach a MagicMock so the lifespan handler sees _agent_service != None.
    server._agent_service = MagicMock()
    server._agent_service.data_dir = tmp_path
    server._agent_service.start_auto_compact = AsyncMock(return_value=MagicMock())
    server._agent_service.stop_auto_compact = AsyncMock()
    server._agent_service.start_dream_scheduler = AsyncMock()
    server._agent_service.stop_dream_scheduler = AsyncMock()
    # Drive the lifespan context manager manually
    async with server.app.router.lifespan_context(server.app):
        pass
    assert server._agent_service.start_auto_compact.await_count == 1
    assert server._agent_service.stop_auto_compact.await_count == 1


@pytest.mark.asyncio
async def test_lifespan_skips_when_auto_compact_disabled(tmp_path: Path) -> None:
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        provider=_make_provider(),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_rest=False,
        enable_webui=False,
    )
    server._agent_service = MagicMock()
    server._agent_service.data_dir = tmp_path
    server._agent_service.start_auto_compact = AsyncMock()
    server._agent_service.stop_auto_compact = AsyncMock()
    server._agent_service.start_dream_scheduler = AsyncMock()
    server._agent_service.stop_dream_scheduler = AsyncMock()
    async with server.app.router.lifespan_context(server.app):
        pass
    assert server._agent_service.start_auto_compact.await_count == 0
    # stop is still called to keep idempotent shutdown semantics
    assert server._agent_service.stop_auto_compact.await_count == 1


@pytest.mark.asyncio
async def test_lifespan_respects_memory_config_disable(tmp_path: Path) -> None:
    """Even when WikiServer flag is True, config-level disable wins."""
    from llmwikify.apps.chat.memory.memory_config import DEFAULT_CONFIG_FILENAME
    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        provider=_make_provider(),
        enable_dream_scheduler=False,
        enable_auto_compact=True,
        enable_rest=False,
        enable_webui=False,
    )
    server._agent_service = MagicMock()
    data_dir = tmp_path
    server._agent_service.data_dir = data_dir
    (data_dir / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
        "auto_compact": {"enabled": False},
    }))
    server._agent_service.start_auto_compact = AsyncMock()
    server._agent_service.stop_auto_compact = AsyncMock()
    server._agent_service.start_dream_scheduler = AsyncMock()
    server._agent_service.stop_dream_scheduler = AsyncMock()
    async with server.app.router.lifespan_context(server.app):
        pass
    assert server._agent_service.start_auto_compact.await_count == 0


def test_health_endpoint_exposes_auto_compact_flag(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from llmwikify.interfaces.server.core import WikiServer

    server = WikiServer(
        _make_wiki(tmp_path),
        enable_dream_scheduler=False,
        enable_auto_compact=False,
        enable_webui=False,
    )
    with TestClient(server.app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "auto_compact" in body["features"]
    assert body["features"]["auto_compact"] is False
