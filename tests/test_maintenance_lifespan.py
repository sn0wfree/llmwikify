"""Lifespan integration tests for MaintenanceManager (WikiServer wiring)."""

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


def _make_server(tmp_path: Path, **kwargs):
    from llmwikify.interfaces.server.core import WikiServer

    defaults = {
        "enable_dream_scheduler": False,
        "enable_auto_compact": False,
        "enable_confirmations_cleanup": False,
        "enable_rest": False,
        "enable_webui": False,
    }
    defaults.update(kwargs)
    server = WikiServer(_make_wiki(tmp_path), **defaults)
    server._agent_service = MagicMock()
    server._agent_service.data_dir = tmp_path
    server._agent_service.start_dream_scheduler = AsyncMock()
    server._agent_service.stop_dream_scheduler = AsyncMock()
    server._agent_service.start_auto_compact = AsyncMock()
    server._agent_service.stop_auto_compact = AsyncMock()
    server._agent_service.start_confirmations_cleanup = AsyncMock()
    server._agent_service.stop_confirmations_cleanup = AsyncMock()
    return server


def _write_global_config(tmp_path: Path, maintenance: dict | None) -> Path:
    import llmwikify.apps.agent.maintenance.config as mcfg

    cfg_path = tmp_path / "llmwikify.json"
    data = {"llm": {"provider": "none"}}
    if maintenance is not None:
        data["maintenance"] = maintenance
    cfg_path.write_text(json.dumps(data))
    return cfg_path


@pytest.fixture
def patched_config_path(monkeypatch, tmp_path):
    import llmwikify.apps.agent.maintenance.config as mcfg

    def _patch(maintenance: dict | None) -> Path:
        path = _write_global_config(tmp_path, maintenance)
        monkeypatch.setattr(mcfg, "CONFIG_PATH", path)
        return path

    return _patch


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_manager(tmp_path: Path, patched_config_path) -> None:
    patched_config_path({"enabled": True, "auto_ingest": {"enabled": False}})
    server = _make_server(tmp_path, enable_maintenance=True)

    async with server.app.router.lifespan_context(server.app):
        mgr = getattr(server.app.state, "maintenance_manager", None)
        assert mgr is not None
        assert mgr._running is True
    assert mgr._running is False


@pytest.mark.asyncio
async def test_lifespan_config_disable_wins(tmp_path: Path, patched_config_path) -> None:
    patched_config_path({"enabled": False})
    server = _make_server(tmp_path, enable_maintenance=True)

    async with server.app.router.lifespan_context(server.app):
        assert getattr(server.app.state, "maintenance_manager", None) is None


@pytest.mark.asyncio
async def test_lifespan_server_flag_disable(tmp_path: Path, patched_config_path) -> None:
    patched_config_path({"enabled": True})
    server = _make_server(tmp_path, enable_maintenance=False)

    async with server.app.router.lifespan_context(server.app):
        assert getattr(server.app.state, "maintenance_manager", None) is None


def _make_api_app(manager):
    """Bare FastAPI app with only maintenance routes + manager on state."""
    from fastapi import FastAPI

    from llmwikify.interfaces.server.http.maintenance_routes import (
        register_maintenance_routes,
    )

    app = FastAPI()
    app.state.maintenance_manager = manager
    register_maintenance_routes(app)
    return app


def _make_manager(tmp_path: Path, **cfg_overrides):
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager

    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    registry = MagicMock()
    registry.list_wikis.return_value = []
    mgr = MaintenanceManager(registry=registry, config=cfg)
    mgr._running = True
    return mgr


def test_api_maintenance_health_roundtrip(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_api_app(_make_manager(tmp_path))
    with TestClient(app) as client:
        resp = client.get("/api/maintenance/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["running"] is True
        assert "health_history" in body
        assert body["config"]["enabled"] is True

        status = client.get("/api/maintenance/status")
        assert status.status_code == 200

        bad = client.post("/api/maintenance/trigger?task=bogus")
        assert bad.status_code == 400


def test_api_maintenance_503_when_disabled(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = _make_api_app(None)
    with TestClient(app) as client:
        resp = client.get("/api/maintenance/health")
        assert resp.status_code == 503
