"""Boundary tests for AutoIngestService (track A)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
from llmwikify.apps.agent.maintenance.config import AutoIngestConfig


def _make_service(tmp_path: Path, wiki=None, **cfg_overrides) -> AutoIngestService:
    cfg = AutoIngestConfig(debounce_seconds=0.05, **cfg_overrides)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(exist_ok=True)
    wiki = wiki or SimpleNamespace(
        raw_dir=raw_dir,
        ingest_source=lambda p: {
            "title": "t", "source_name": "s", "content": "hello", "error": None,
        },
        _llm_process_source=lambda r: {"operations": [{"action": "create", "page_name": "x", "content": "c"}]},
        execute_operations=lambda ops: {"operations_executed": len(ops)},
    )
    return AutoIngestService(
        wiki=wiki,
        wiki_id="test",
        config=cfg,
        llm_semaphore=asyncio.Semaphore(3),
    )


def test_process_file_auto_write_happy_path(tmp_path: Path):
    svc = _make_service(tmp_path)
    path = tmp_path / "raw" / "note.md"
    path.write_text("# hello")

    asyncio.run(svc._process_file(path))

    assert svc.stats["ingested"] == 1
    assert svc.stats["pages_written"] == 1
    assert svc.stats["failed"] == 0


def test_llm_failure_falls_back_to_proposal(tmp_path: Path):
    from types import SimpleNamespace as NS

    def boom(_r):
        raise RuntimeError("llm down")

    wiki = NS(
        raw_dir=tmp_path / "raw",
        ingest_source=lambda p: {"title": "t", "source_name": "s", "content": "hello"},
        _llm_process_source=boom,
    )
    (tmp_path / "raw").mkdir(exist_ok=True)
    svc = AutoIngestService(
        wiki=wiki, wiki_id="test",
        config=AutoIngestConfig(debounce_seconds=0.05),
        llm_semaphore=asyncio.Semaphore(1),
    )
    path = tmp_path / "raw" / "note.md"
    path.write_text("x")

    asyncio.run(svc._process_file(path))

    assert svc.stats["ingested"] == 1
    assert svc.stats["pages_written"] == 0
    assert svc.stats["fallback_proposals"] == 1
    pending = svc._proposal_manager.get_stats()
    assert pending.get("pending", 0) >= 1


def test_write_mode_proposal_skips_llm(tmp_path: Path):
    calls = {"llm": 0}

    def llm(_r):
        calls["llm"] += 1
        return {"operations": []}

    from types import SimpleNamespace as NS
    wiki = NS(
        raw_dir=tmp_path / "raw",
        ingest_source=lambda p: {"title": "t", "source_name": "s", "content": "hi"},
        _llm_process_source=llm,
    )
    (tmp_path / "raw").mkdir(exist_ok=True)
    svc = AutoIngestService(
        wiki=wiki, wiki_id="test",
        config=AutoIngestConfig(write_mode="proposal", debounce_seconds=0.05),
        llm_semaphore=asyncio.Semaphore(1),
    )
    path = tmp_path / "raw" / "note.md"
    path.write_text("x")

    asyncio.run(svc._process_file(path))

    assert calls["llm"] == 0
    assert svc.stats["fallback_proposals"] == 1


def test_ingest_error_recorded_not_raised(tmp_path: Path):
    from types import SimpleNamespace as NS

    def bad_ingest(_p):
        raise ValueError("corrupt file")

    wiki = NS(raw_dir=tmp_path / "raw", ingest_source=bad_ingest)
    (tmp_path / "raw").mkdir(exist_ok=True)
    svc = AutoIngestService(
        wiki=wiki, wiki_id="test",
        config=AutoIngestConfig(debounce_seconds=0.05),
        llm_semaphore=asyncio.Semaphore(1),
    )
    path = tmp_path / "raw" / "note.md"
    path.write_text("x")

    asyncio.run(svc._process_file(path))  # must not raise

    assert svc.stats["failed"] == 1
    assert "corrupt file" in svc.stats["last_error"]


def test_on_watch_event_skips_processed_and_unsupported(tmp_path: Path):
    svc = _make_service(tmp_path)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_noop_start(svc))

        md = tmp_path / "raw" / "a.md"
        md.write_text("x")
        svc._processed.add(str(md))
        svc._on_watch_event("created", md)
        assert str(md) not in svc._pending  # already processed → dropped

        bad = tmp_path / "raw" / "virus.exe"
        bad.write_text("x")
        svc._on_watch_event("created", bad)
        assert str(bad) not in svc._pending  # unsupported ext → dropped

        ok = tmp_path / "raw" / "b.md"
        ok.write_text("x")
        svc._on_watch_event("created", ok)
        # let call_soon_threadsafe callbacks execute
        loop.run_until_complete(asyncio.sleep(0.02))
        assert str(ok) in svc._pending  # queued for debounce
    finally:
        loop.run_until_complete(svc.stop())
        loop.close()


async def _noop_start(svc: AutoIngestService) -> None:
    svc._loop = asyncio.get_running_loop()
