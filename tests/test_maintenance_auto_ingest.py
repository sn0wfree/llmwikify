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
        svc._mark_processed(md)  # record mtime+size as processed
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


# ── B1a: startup backlog replay ──────────────────────────────────────


def _backlog_wiki(tmp_path: Path, calls: list):
    from types import SimpleNamespace as NS
    return NS(
        root=tmp_path,
        raw_dir=tmp_path / "raw",
        ingest_source=lambda p: calls.append(p) or {
            "title": "t", "source_name": "s", "content": "hello", "error": None,
        },
        _llm_process_source=lambda r: {"operations": [{"action": "create"}]},
        execute_operations=lambda ops: {"operations_executed": len(ops)},
    )


def test_backlog_replays_unprocessed_files(tmp_path: Path):
    calls: list = []
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.md").write_text("aaa")
    (tmp_path / "raw" / "b.md").write_text("bbb")
    (tmp_path / "raw" / "ignored.exe").write_text("zzz")  # unsupported ext

    svc = _make_service(tmp_path, wiki=_backlog_wiki(tmp_path, calls))
    asyncio.run(svc._scan_backlog())

    assert len(calls) == 2
    assert svc.stats["backlog_replayed"] == 2
    # state file persisted with both files
    assert set(svc._processed.keys()) == {"a.md", "b.md"}


def test_backlog_idempotent_across_restart(tmp_path: Path):
    calls: list = []
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.md").write_text("aaa")

    first = _make_service(tmp_path, wiki=_backlog_wiki(tmp_path, calls))
    first._load_processed()
    asyncio.run(first._scan_backlog())
    assert len(calls) == 1

    # "restart": fresh service instance reads the same state file
    second = _make_service(tmp_path, wiki=_backlog_wiki(tmp_path, calls))
    second._load_processed()
    asyncio.run(second._scan_backlog())
    assert len(calls) == 1  # no double-ingest


def test_backlog_requeues_modified_file(tmp_path: Path):
    calls: list = []
    f = tmp_path / "raw" / "a.md"
    (tmp_path / "raw").mkdir()
    f.write_text("v1")

    first = _make_service(tmp_path, wiki=_backlog_wiki(tmp_path, calls))
    first._load_processed()
    asyncio.run(first._scan_backlog())
    assert len(calls) == 1

    # simulate modification after processing (different content + mtime)
    import os
    f.write_text("v2 - changed")
    os.utime(f, (f.stat().st_atime + 10, f.stat().st_mtime + 10))

    second = _make_service(tmp_path, wiki=_backlog_wiki(tmp_path, calls))
    second._load_processed()
    asyncio.run(second._scan_backlog())
    assert len(calls) == 2  # re-ingested after modification


def test_backlog_respects_limit(tmp_path: Path):
    calls: list = []
    raw = tmp_path / "raw"
    raw.mkdir()
    for i in range(3):
        (raw / f"f{i}.md").write_text(f"content {i}")

    svc = _make_service(tmp_path, wiki=_backlog_wiki(tmp_path, calls), max_backlog_per_start=2)
    asyncio.run(svc._scan_backlog())

    assert len(calls) == 2
    assert svc.stats["backlog_replayed"] == 2
    assert svc.stats["backlog_deferred"] == 1


def test_failed_ingest_not_marked_processed(tmp_path: Path):
    """Hard ingest failure leaves the file un-marked → retried next start."""
    from types import SimpleNamespace as NS

    def bad_ingest(_p):
        raise RuntimeError("corrupt")

    wiki = NS(root=tmp_path, raw_dir=tmp_path / "raw", ingest_source=bad_ingest)
    (tmp_path / "raw").mkdir()
    f = tmp_path / "raw" / "bad.md"
    f.write_text("x")

    svc = AutoIngestService(
        wiki=wiki, wiki_id="t",
        config=AutoIngestConfig(debounce_seconds=0.05),
        llm_semaphore=asyncio.Semaphore(1),
    )
    asyncio.run(svc._process_file(f))
    assert svc.stats["failed"] == 1
    assert "bad.md" not in svc._processed


# ── B1b: proposal persistence via shared WikiDatabase ────────────────


def test_fallback_proposal_persists_to_db(tmp_path: Path):
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager
    from llmwikify.apps.wiki.db import WikiDatabase
    from llmwikify.kernel.multi_wiki.instance import WikiInstance, WikiType

    raw = tmp_path / "raw"
    raw.mkdir()
    ingest_calls: list = []

    def boom(_r):
        raise RuntimeError("llm down")

    from types import SimpleNamespace as NS
    wiki = NS(
        root=tmp_path,
        raw_dir=raw,
        ingest_source=lambda p: ingest_calls.append(p) or {
            "title": "Persisted", "source_name": "s", "content": "hello", "error": None,
        },
        _llm_process_source=boom,
    )
    instance = WikiInstance(wiki_id="w1", name="w1", wiki_type=WikiType.LOCAL, root=tmp_path)
    registry = NS(list_wikis=lambda: [instance], get_wiki=lambda wid: wiki)

    data_dir = tmp_path / "agent-data"
    cfg = MaintenanceConfig()
    cfg.gap_filler.enabled = False
    cfg.auto_ingest.debounce_seconds = 0.05
    mgr = MaintenanceManager(registry=registry, config=cfg, data_dir=data_dir)

    async def scenario() -> None:
        await mgr.start()
        svc = mgr.auto_ingest_services["w1"]
        f = raw / "note.md"
        f.write_text("x")
        await svc._process_file(f)

    asyncio.run(scenario())

    assert len(ingest_calls) == 1
    # proposal visible through a fresh WikiDatabase on the same data_dir
    db = WikiDatabase(data_dir)
    rows = db.get_dream_proposals("w1", status=None)
    assert any(
        r["page_name"] == "Persisted" and r["status"] == "pending"
        for r in rows
    )
