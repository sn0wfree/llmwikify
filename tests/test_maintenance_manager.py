"""Boundary tests for MaintenanceManager + config loading."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmwikify.apps.agent.maintenance import (
    MaintenanceConfig,
    MaintenanceManager,
    load_maintenance_config,
)
from llmwikify.kernel.multi_wiki.instance import WikiInstance, WikiType


def _make_registry(wiki_ids: list[str], remote_ids: list[str] | None = None):
    """Fake registry: get_wiki returns a stub wiki with the given id."""
    stub_wikis = {}
    instances = []
    for wid in wiki_ids + (remote_ids or []):
        is_remote = wid in (remote_ids or [])
        instances.append(
            WikiInstance(
                wiki_id=wid,
                name=wid,
                wiki_type=WikiType.REMOTE if is_remote else WikiType.LOCAL,
                root=None if is_remote else Path(f"/tmp/{wid}"),
            ),
        )
        stub_wikis[wid] = SimpleNamespace(
            wiki_id=wid,
            raw_dir=Path(f"/tmp/{wid}/raw"),
            db_path=Path(f"/tmp/{wid}/.llmwikify.db"),
            lint=lambda: {},
            search=lambda q, limit=5: [],
        )
    return SimpleNamespace(
        list_wikis=lambda: instances,
        get_wiki=lambda wid: stub_wikis.get(wid),
    )


# ── config ───────────────────────────────────────────────────────────


def test_config_defaults_when_file_missing(tmp_path: Path):
    cfg = load_maintenance_config(tmp_path / "nonexistent.json")
    assert cfg.enabled is True
    assert cfg.auto_ingest.write_mode == "auto"
    assert cfg.gap_filler.min_priority == 30
    assert cfg.lint_interval_seconds == 86400.0


def test_config_parses_full_section(tmp_path: Path):
    path = tmp_path / "llmwikify.json"
    path.write_text(json.dumps({
        "llm": {"provider": "x"},
        "maintenance": {
            "enabled": False,
            "auto_ingest": {"enabled": False, "write_mode": "proposal"},
            "gap_filler": {"max_per_cycle": 2, "min_priority": 50},
            "gaps_interval_seconds": 3600,
        },
    }))
    cfg = load_maintenance_config(path)
    assert cfg.enabled is False
    assert cfg.auto_ingest.enabled is False
    assert cfg.auto_ingest.write_mode == "proposal"
    assert cfg.gap_filler.max_per_cycle == 2
    assert cfg.gap_filler.min_priority == 50
    assert cfg.gaps_interval_seconds == 3600.0
    # untouched keys keep defaults
    assert cfg.gap_filler.auto_approve_mechanical is True


def test_config_survives_garbage_section(tmp_path: Path):
    path = tmp_path / "llmwikify.json"
    path.write_text(json.dumps({"maintenance": "not-a-dict"}))
    cfg = load_maintenance_config(path)
    assert cfg.enabled is True


# ── manager ──────────────────────────────────────────────────────────


def test_local_wikis_filters_remote():
    mgr = MaintenanceManager(
        registry=_make_registry(["a", "b"], remote_ids=["r"]),
        config=MaintenanceConfig(),
    )
    pairs = mgr._local_wikis()
    assert [wid for wid, _ in pairs] == ["a", "b"]


def test_start_disabled_is_noop():
    cfg = MaintenanceConfig(enabled=False)
    mgr = MaintenanceManager(registry=_make_registry(["a"]), config=cfg)
    asyncio.run(mgr.start())
    assert mgr.auto_ingest_services == {}
    assert mgr._tasks == []


def test_start_stops_idempotent():
    cfg = MaintenanceConfig()
    # disable both subsystems so no watcher/thread spawns; only loops start
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    cfg.db_maintenance_interval_seconds = 3600.0
    mgr = MaintenanceManager(registry=_make_registry(["a"]), config=cfg)

    async def scenario() -> None:
        await mgr.start()
        await mgr.start()  # second call must be a no-op
        assert len(mgr._tasks) == 2  # lint_loop + db_loop
        await mgr.stop()
        await mgr.stop()  # second stop must not raise

    asyncio.run(scenario())
    assert mgr._tasks == []


# ── db maintenance ───────────────────────────────────────────────────


def test_maintain_db_vacuum_reclaims_pages(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [("y" * 500,)] * 50)
    conn.commit()
    conn.execute("DELETE FROM t")
    conn.commit()
    conn.close()

    result = MaintenanceManager._maintain_db(db_path)
    assert result["status"] == "ok"
    assert result["pages_reclaimed"] > 0


def test_maintain_db_missing_file(tmp_path: Path):
    result = MaintenanceManager._maintain_db(tmp_path / "nope.db")
    assert result["status"] == "skipped"


async def _run_trigger(task: str) -> dict:
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    mgr = MaintenanceManager(registry=_make_registry(["a"]), config=cfg)
    return await mgr.trigger(task)


def test_trigger_unknown_task():
    result = asyncio.run(_run_trigger("bogus"))
    assert "error" in result


# ── dynamic wiki discovery ───────────────────────────────────────────


def test_sync_wikis_adds_new_wiki():
    instances = [WikiInstance(wiki_id="a", name="a", wiki_type=WikiType.LOCAL, root=Path("/tmp/a"))]
    wikis = {"a": SimpleNamespace(root=Path("/tmp/a"), raw_dir=Path("/tmp/a/raw"),
            db_path=Path("/tmp/a/.llmwikify.db"), lint=lambda **kw: {"issue_count": 0},
            config={"llm": {"enabled": False}})}

    def list_wikis():
        return instances

    def get_wiki(wid):
        return wikis.get(wid)

    registry = SimpleNamespace(list_wikis=list_wikis, get_wiki=get_wiki)
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    mgr = MaintenanceManager(registry=registry, config=cfg)

    async def scenario() -> None:
        await mgr.start()
        assert "a" not in mgr.gap_fillers  # gap disabled, so nothing to add
        # now add a new wiki to the registry
        instances.append(WikiInstance(wiki_id="b", name="b", wiki_type=WikiType.LOCAL, root=Path("/tmp/b")))
        wikis["b"] = SimpleNamespace(root=Path("/tmp/b"), raw_dir=Path("/tmp/b/raw"),
                db_path=Path("/tmp/b/.llmwikify.db"), lint=lambda **kw: {"issue_count": 0},
                config={"llm": {"enabled": False}})
        cfg.gap_filler.enabled = True
        await mgr._sync_wikis()
        assert "b" in mgr.gap_fillers  # discovered and added
        await mgr.stop()

    asyncio.run(scenario())


def test_sync_wikis_removes_vanished_wiki():
    from llmwikify.kernel.multi_wiki.instance import WikiInstance, WikiType

    instances = [
        WikiInstance(wiki_id="a", name="a", wiki_type=WikiType.LOCAL, root=Path("/tmp/a")),
        WikiInstance(wiki_id="b", name="b", wiki_type=WikiType.LOCAL, root=Path("/tmp/b")),
    ]
    wikis = {
        "a": SimpleNamespace(root=Path("/tmp/a"), raw_dir=Path("/tmp/a/raw"),
            db_path=Path("/tmp/a/.llmwikify.db"), lint=lambda **kw: {"issue_count": 0},
            config={"llm": {"enabled": False}}),
        "b": SimpleNamespace(root=Path("/tmp/b"), raw_dir=Path("/tmp/b/raw"),
            db_path=Path("/tmp/b/.llmwikify.db"), lint=lambda **kw: {"issue_count": 0},
            config={"llm": {"enabled": False}}),
    }
    registry = SimpleNamespace(
        list_wikis=lambda: instances, get_wiki=lambda wid: wikis.get(wid))
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    mgr = MaintenanceManager(registry=registry, config=cfg)

    async def scenario() -> None:
        await mgr.start()
        assert "b" in mgr.gap_fillers
        # remove b from registry
        instances[:] = [i for i in instances if i.wiki_id != "a"]
        await mgr._sync_wikis()
        assert "a" not in mgr.gap_fillers  # removed
        await mgr.stop()

    asyncio.run(scenario())


def test_lint_tick_records_to_health_history():
    from llmwikify.kernel.multi_wiki.instance import WikiInstance, WikiType

    wiki = SimpleNamespace(
        root=Path("/tmp/x"), raw_dir=Path("/tmp/x/raw"),
        db_path=Path("/tmp/x/.llmwikify.db"),
        config={"llm": {"enabled": False}},
        lint=lambda **kw: {"issue_count": 2, "hints": {"critical": ["a"], "informational": ["b"]}},
    )
    registry = SimpleNamespace(
        list_wikis=lambda: [WikiInstance(wiki_id="x", name="x", wiki_type=WikiType.LOCAL, root=Path("/tmp/x"))],
        get_wiki=lambda wid: wiki,
    )
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    mgr = MaintenanceManager(registry=registry, config=cfg)

    async def scenario() -> None:
        await mgr.start()
        await mgr._lint_tick()
        await mgr.stop()

    asyncio.run(scenario())
    lint_entries = [h for h in mgr._health_history if h["type"] == "lint"]
    assert len(lint_entries) == 1
    assert lint_entries[0]["wiki_id"] == "x"
    assert lint_entries[0]["issue_count"] == 2
    assert lint_entries[0]["hint_count"] == 2
