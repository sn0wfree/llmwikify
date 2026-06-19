"""Tests for AgentService AutoCompact lifecycle (Phase 9).

Covers:
  - auto_compact attr initially None
  - start_auto_compact returns None when no consolidator (no provider)
  - start_auto_compact returns None when enabled=False
  - start_auto_compact wires AutoCompact + creates background task
  - start_auto_compact is idempotent (returns same instance)
  - stop_auto_compact cancels the task and clears state
  - stop_auto_compact idempotent when never started
  - _active_session_keys returns running ids only
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.apps.chat.agent.agent_service import AgentService


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.achat = AsyncMock(return_value={"content": "summary"})
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


def test_auto_compact_attr_initially_none(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        provider=_make_provider(),
    )
    assert svc.auto_compact is None
    assert svc._auto_compact_task is None


@pytest.mark.asyncio
async def test_start_auto_compact_no_provider_returns_none(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        # No provider -> no consolidator
    )
    out = await svc.start_auto_compact(ttl_minutes=15)
    assert out is None
    assert svc.auto_compact is None
    assert svc._auto_compact_task is None


@pytest.mark.asyncio
async def test_start_auto_compact_disabled(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        provider=_make_provider(),
    )
    out = await svc.start_auto_compact(ttl_minutes=15, enabled=False)
    assert out is None
    assert svc.auto_compact is None


@pytest.mark.asyncio
async def test_start_auto_compact_wires_instance(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        provider=_make_provider(),
    )
    out = await svc.start_auto_compact(
        ttl_minutes=15, interval_seconds=3600.0,
    )
    try:
        assert out is svc.auto_compact
        assert svc.auto_compact is not None
        assert svc.auto_compact.ttl_minutes == 15
        assert svc._auto_compact_task is not None
        assert not svc._auto_compact_task.done()
    finally:
        await svc.stop_auto_compact()


@pytest.mark.asyncio
async def test_start_auto_compact_idempotent(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        provider=_make_provider(),
    )
    a = await svc.start_auto_compact(
        ttl_minutes=10, interval_seconds=3600.0,
    )
    b = await svc.start_auto_compact(
        ttl_minutes=99, interval_seconds=3600.0,
    )
    try:
        assert a is b
        # ttl_minutes unchanged on the second call (idempotent)
        assert svc.auto_compact.ttl_minutes == 10
    finally:
        await svc.stop_auto_compact()


@pytest.mark.asyncio
async def test_stop_auto_compact_cancels_task(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        provider=_make_provider(),
    )
    await svc.start_auto_compact(ttl_minutes=10, interval_seconds=3600.0)
    task = svc._auto_compact_task
    await svc.stop_auto_compact()
    assert svc.auto_compact is None
    assert svc._auto_compact_task is None
    assert task.done() or task.cancelled()


@pytest.mark.asyncio
async def test_stop_auto_compact_idempotent(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        provider=_make_provider(),
    )
    await svc.stop_auto_compact()  # never started
    await svc.stop_auto_compact()  # second call still ok
    assert svc.auto_compact is None


def test_active_session_keys_filters_running_only(tmp_path: Path) -> None:
    svc = AgentService(
        wiki_registry=_make_wiki_registry(),
        data_dir=tmp_path,
        provider=_make_provider(),
    )
    # Patch chat_service.get_all_session_status to a known map
    svc.chat_service.get_all_session_status = lambda: {
        "a": "running",
        "b": "completed",
        "c": "confirmation_required",
    }
    out = sorted(svc._active_session_keys())
    assert out == ["a", "c"]
