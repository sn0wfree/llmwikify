"""Robustness tests for AutoIngestService: watchdog degradation and
concurrency isolation.

The watchdog-missing path used to bail out before replaying the backlog,
so historical files in raw/ were never processed (and the service was
not even registered, leaking the backlog task if one had started).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from llmwikify.apps.agent.maintenance import auto_ingest as ai_module
from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
from llmwikify.apps.agent.maintenance.config import AutoIngestConfig


class _NoWatchdog:
    """FileSystemWatcher stand-in whose start() fails like a missing package."""

    def __init__(self, **kwargs) -> None:
        pass

    def start(self, on_event=None):
        raise ImportError("watchdog is not installed")

    def stop(self) -> None:
        pass


def _wiki_stub(raw_dir: Path, calls: list) -> SimpleNamespace:
    def ingest_source(path):
        calls.append(("ingest", Path(path).name))
        return {
            "title": "T",
            "source_name": Path(path).name,
            "content": "hello",
            "error": None,
        }

    def llm_plan(_result):
        calls.append(("llm", None))
        return {"operations": [], "relations": []}

    def execute(ops):
        calls.append(("exec", len(ops)))
        return {"operations_executed": len(ops), "results": []}

    return SimpleNamespace(
        raw_dir=raw_dir,
        config={"llm": {"enabled": False}},
        ingest_source=ingest_source,
        _llm_process_source=llm_plan,
        execute_operations=execute,
    )


def _service(wiki, **overrides) -> AutoIngestService:
    return AutoIngestService(
        wiki=wiki,
        wiki_id="robust",
        config=AutoIngestConfig(debounce_seconds=0.01, **overrides),
        llm_semaphore=asyncio.Semaphore(1),
    )


# ── watchdog degradation ────────────────────────────────────────────


def test_start_succeeds_without_watchdog(tmp_path: Path, monkeypatch):
    """No watchdog must not disable the service: backlog still runs."""
    monkeypatch.setattr(ai_module, "FileSystemWatcher", _NoWatchdog)

    raw = tmp_path / "raw"
    raw.mkdir()
    calls: list = []
    svc = _service(_wiki_stub(raw, calls))

    async def go():
        started = await svc.start()
        if svc._backlog_task:
            await svc._backlog_task
        await svc.stop()
        return started

    started = asyncio.run(go())
    assert started is True, "service must stay registered without watchdog"
    assert svc._watcher is None


def test_backlog_replays_without_watchdog(tmp_path: Path, monkeypatch):
    """Historical raw/ files must be replayed even without watchdog."""
    monkeypatch.setattr(ai_module, "FileSystemWatcher", _NoWatchdog)

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "old.md").write_text("# Old\n\nHistorical content.\n", encoding="utf-8")
    calls: list = []
    svc = _service(_wiki_stub(raw, calls))

    async def go():
        await svc.start()
        if svc._backlog_task:
            await svc._backlog_task
        await svc.stop()

    asyncio.run(go())

    ingested = [name for kind, name in calls if kind == "ingest"]
    assert "old.md" in ingested, f"backlog did not replay: {calls}"
    assert svc.stats["backlog_replayed"] == 1


def test_stop_cancels_backlog_without_watchdog(tmp_path: Path, monkeypatch):
    """The service must be stoppable (no leaked backlog task)."""
    monkeypatch.setattr(ai_module, "FileSystemWatcher", _NoWatchdog)

    raw = tmp_path / "raw"
    raw.mkdir()
    svc = _service(_wiki_stub(raw, []))

    async def go():
        await svc.start()
        task = svc._backlog_task
        assert task is not None
        await svc.stop()
        return task

    task = asyncio.run(go())
    assert task.cancelled() or task.done()


def test_start_returns_false_without_raw(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ai_module, "FileSystemWatcher", _NoWatchdog)
    svc = _service(_wiki_stub(tmp_path / "missing", []))

    assert asyncio.run(svc.start()) is False


# ── concurrency isolation ───────────────────────────────────────────


def test_same_file_processed_once_under_concurrency(tmp_path: Path):
    """Two concurrent _process_file calls for one file must not double-write."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "doc.md").write_text("# D\n\nbody\n", encoding="utf-8")
    calls: list = []
    svc = _service(_wiki_stub(raw, calls))

    async def go():
        doc = raw / "doc.md"
        await asyncio.gather(
            svc._process_file(doc),
            svc._process_file(doc),
        )

    asyncio.run(go())

    ingests = [name for kind, name in calls if kind == "ingest"]
    assert len(ingests) == 1, f"file processed {len(ingests)} times: {calls}"
    assert svc.stats["ingested"] == 1


def test_different_files_process_independently(tmp_path: Path):
    """Concurrent processing of two files must touch both."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "a.md").write_text("# A\n", encoding="utf-8")
    (raw / "b.md").write_text("# B\n", encoding="utf-8")
    calls: list = []
    svc = _service(_wiki_stub(raw, calls))

    async def go():
        await asyncio.gather(
            svc._process_file(raw / "a.md"),
            svc._process_file(raw / "b.md"),
        )

    asyncio.run(go())

    ingested = sorted(name for kind, name in calls if kind == "ingest")
    assert ingested == ["a.md", "b.md"], f"got {ingested}"
    assert svc.stats["ingested"] == 2
