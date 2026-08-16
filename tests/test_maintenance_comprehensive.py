"""Comprehensive tests covering maintenance subsystem gaps.

Targets:
- llm_support.py (direct unit tests)
- section_selection schema validation (prompt_registry)
- gap_filler run_cycle orchestration
- auto_ingest edge cases (fallback failure, status, _flush_pending)
- config edge cases (to_dict, non-dict sub-sections, JSON errors)
- maintenance_routes trigger tasks
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════
# llm_support.py — direct unit tests
# ═══════════════════════════════════════════════════════════════════════


def test_ensure_global_llm_fallback_returns_false_when_config_not_dict():
    from llmwikify.apps.agent.maintenance.llm_support import ensure_global_llm_fallback

    wiki = SimpleNamespace(config="not-a-dict")
    assert ensure_global_llm_fallback(wiki, "x") is False


def test_ensure_global_llm_fallback_merges_when_no_llm_key(monkeypatch):
    import llmwikify.foundation.llm.client as llm_client_mod
    from llmwikify.apps.agent.maintenance.llm_support import ensure_global_llm_fallback

    monkeypatch.setattr(
        llm_client_mod, "load_llm_config",
        lambda: {"enabled": True, "provider": "minimax", "api_key": "k"},
    )
    wiki = SimpleNamespace(config={"other": 123})  # no "llm" key at all
    result = ensure_global_llm_fallback(wiki, "x")
    assert result is True  # should merge global
    assert wiki.config["llm"]["enabled"] is True


def test_ensure_global_llm_fallback_returns_false_when_global_disabled(
    monkeypatch,
):
    import llmwikify.foundation.llm.client as llm_client_mod
    from llmwikify.apps.agent.maintenance.llm_support import ensure_global_llm_fallback

    monkeypatch.setattr(
        llm_client_mod, "load_llm_config",
        lambda: {"enabled": False, "provider": "x"},
    )
    wiki = SimpleNamespace(config={"llm": {}})
    assert ensure_global_llm_fallback(wiki, "x") is False


def test_ensure_global_llm_fallback_preserves_local_keys(monkeypatch):
    import llmwikify.foundation.llm.client as llm_client_mod
    from llmwikify.apps.agent.maintenance.llm_support import ensure_global_llm_fallback

    monkeypatch.setattr(
        llm_client_mod, "load_llm_config",
        lambda: {"enabled": True, "provider": "minimax", "model": "m3", "api_key": "k"},
    )
    wiki = SimpleNamespace(config={"llm": {"timeout": 300}})
    result = ensure_global_llm_fallback(wiki, "x")
    assert result is True
    assert wiki.config["llm"]["timeout"] == 300  # local key preserved
    assert wiki.config["llm"]["provider"] == "minimax"  # global merged
    assert wiki.config["llm"]["enabled"] is True


def test_ensure_global_llm_fallback_handles_load_exception(monkeypatch):
    import llmwikify.foundation.llm.client as llm_client_mod
    from llmwikify.apps.agent.maintenance.llm_support import ensure_global_llm_fallback

    def _raise():
        raise OSError("config broken")

    monkeypatch.setattr(llm_client_mod, "load_llm_config", _raise)
    wiki = SimpleNamespace(config={"llm": {}})
    assert ensure_global_llm_fallback(wiki, "x") is False


def test_ensure_global_llm_fallback_skips_when_local_usable():
    from llmwikify.apps.agent.maintenance.llm_support import ensure_global_llm_fallback

    wiki = SimpleNamespace(config={"llm": {"enabled": True, "api_key": "sk-xxx"}})
    assert ensure_global_llm_fallback(wiki, "x") is False


def test_ensure_global_llm_fallback_skips_when_local_has_base_url():
    from llmwikify.apps.agent.maintenance.llm_support import ensure_global_llm_fallback

    wiki = SimpleNamespace(config={"llm": {"enabled": True, "base_url": "http://localhost:11434"}})
    assert ensure_global_llm_fallback(wiki, "x") is False


# ═══════════════════════════════════════════════════════════════════════
# prompt_registry.py — section_selection schema validation
# ═══════════════════════════════════════════════════════════════════════


def test_section_selection_valid():
    from llmwikify.foundation.prompts.prompt_registry import PromptRegistry

    reg = PromptRegistry()
    errors = reg.validate_output("select_sections", {
        "selected_sections": [1, 2, 3],
        "reasoning": "Selected first 3 sections",
    })
    assert errors == []


def test_section_selection_missing_selected_sections():
    from llmwikify.foundation.prompts.prompt_registry import PromptRegistry

    reg = PromptRegistry()
    errors = reg.validate_output("select_sections", {
        "reasoning": "Some reasoning",
    })
    assert any("selected_sections" in e for e in errors)


def test_section_selection_missing_reasoning():
    from llmwikify.foundation.prompts.prompt_registry import PromptRegistry

    reg = PromptRegistry()
    errors = reg.validate_output("select_sections", {
        "selected_sections": [1],
    })
    assert any("reasoning" in e for e in errors)


def test_section_selection_rejects_list():
    from llmwikify.foundation.prompts.prompt_registry import PromptRegistry

    reg = PromptRegistry()
    errors = reg.validate_output("select_sections", [{"selected_sections": [1]}])
    assert len(errors) >= 1
    assert "list" in errors[0].lower() or "object" in errors[0].lower()


def test_section_selection_rejects_string():
    from llmwikify.foundation.prompts.prompt_registry import PromptRegistry

    reg = PromptRegistry()
    errors = reg.validate_output("select_sections", "not a dict")
    assert len(errors) >= 1


def test_validate_output_unknown_prompt_raises():
    from llmwikify.foundation.prompts.prompt_registry import PromptRegistry

    reg = PromptRegistry()
    with pytest.raises(FileNotFoundError):
        reg.validate_output("nonexistent_prompt_xyz", {"anything": True})


# ═══════════════════════════════════════════════════════════════════════
# gap_filler.py — run_cycle orchestration
# ═══════════════════════════════════════════════════════════════════════


def _make_gap_wiki(tmp_path, lint_result=None, search_results=None):
    """Build a stub wiki for gap_filler testing."""
    if lint_result is None:
        lint_result = {"hints": {"informational": []}, "investigations": {"knowledge_gaps": []}}
    if search_results is None:
        search_results = []

    def _lint(**kw):
        return lint_result

    def _search(q, limit=5):
        return search_results

    return SimpleNamespace(
        root=tmp_path,
        raw_dir=tmp_path / "raw",
        wiki_dir=tmp_path / "wiki",
        config={"llm": {"enabled": False}},
        lint=_lint,
        search=_search,
    )


def test_run_cycle_no_gaps(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    result = asyncio.run(filler.run_cycle())
    assert result.detected == 0
    assert result.processed == 0
    assert result.errors == 0


def test_run_cycle_lint_failure_recorded(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    def _lint(**kw):
        raise RuntimeError("lint broke")

    wiki_instance.lint = _lint
    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    result = asyncio.run(filler.run_cycle())
    assert result.errors == 1
    assert result.detected == 0


def test_run_cycle_budget_exhausted(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller, GapItem

    lint_result = {
        "hints": {
            "informational": [
                {"type": "missing_cross_ref", "concept": "A", "mention_count": 5,
                 "mentioning_pages": ["p1"]},
                {"type": "missing_cross_ref", "concept": "B", "mention_count": 4,
                 "mentioning_pages": ["p2"]},
                {"type": "missing_cross_ref", "concept": "C", "mention_count": 3,
                 "mentioning_pages": ["p3"]},
            ],
        },
        "investigations": {"knowledge_gaps": []},
    }

    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(max_per_cycle=2, min_priority=0),
        llm_semaphore=asyncio.Semaphore(1),
    )
    # patch lint to return our result
    wiki_instance.lint = lambda **kw: lint_result
    result = asyncio.run(filler.run_cycle())
    assert result.detected == 3
    assert result.processed == 2  # budget = 2
    assert result.skipped_low_priority == 1  # 3rd gap skipped


def test_run_cycle_skips_low_priority(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    lint_result = {
        "hints": {"informational": []},
        "investigations": {
            "knowledge_gaps": [
                {"type": "isolated_source", "page": "lonely"},  # priority 20
            ],
        },
    }

    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(min_priority=30),
        llm_semaphore=asyncio.Semaphore(1),
    )
    wiki_instance.lint = lambda **kw: lint_result
    result = asyncio.run(filler.run_cycle())
    assert result.detected == 1
    assert result.processed == 0
    assert result.skipped_low_priority == 1


def test_run_cycle_records_health_history(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    result = asyncio.run(filler.run_cycle())
    assert filler.last_result is result
    assert filler.last_result.ran_at > 0


def test_status_no_cycle_yet(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    s = filler.status()
    assert s["wiki_id"] == "test"
    assert s["last_cycle"] is None


def test_fix_missing_cross_ref_empty_concept(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(auto_approve_mechanical=True),
        llm_semaphore=asyncio.Semaphore(1),
    )
    gap = SimpleNamespace(
        gap_type="missing_cross_ref", concept="", priority=50,
        data={"mentioning_pages": ["p1"]},
    )
    assert asyncio.run(filler._fix_missing_cross_ref(gap)) == 0


def test_propose_entity_empty_concept(wiki_instance):
    from llmwikify.apps.agent.maintenance.config import GapFillerConfig
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    filler = GapFiller(
        wiki=wiki_instance, wiki_id="test",
        config=GapFillerConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    gap = SimpleNamespace(concept="", priority=50, data={})
    assert asyncio.run(filler._propose_entity_page(gap)) == 0


def test_stub_draft_format():
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller

    draft = GapFiller._stub_draft("My Concept", ["Page A", "Page B"])
    assert "# My Concept" in draft
    assert "[[Page A]]" in draft
    assert "[[Page B]]" in draft
    assert "stub" in draft.lower()


# ═══════════════════════════════════════════════════════════════════════
# auto_ingest.py — edge cases
# ═══════════════════════════════════════════════════════════════════════


def test_fallback_failure_leaves_unprocessed(tmp_path):
    """When _fallback_to_proposal fails, file stays unprocessed for retry."""
    from types import SimpleNamespace as NS

    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    def boom(_r):
        raise RuntimeError("llm down")

    def bad_proposal(**kw):
        raise OSError("db full")

    wiki = NS(
        root=tmp_path, raw_dir=tmp_path / "raw",
        ingest_source=lambda p: {"title": "t", "source_name": "s", "content": "x", "error": None},
        _llm_process_source=boom,
    )
    (tmp_path / "raw").mkdir()
    f = tmp_path / "raw" / "a.md"
    f.write_text("x")

    svc = AutoIngestService(
        wiki=wiki, wiki_id="t",
        config=AutoIngestConfig(debounce_seconds=0.05, fallback_to_proposal=True),
        llm_semaphore=asyncio.Semaphore(1),
    )
    # make proposal manager's create_proposal fail
    svc._proposal_manager.create_proposal = bad_proposal

    asyncio.run(svc._process_file(f))

    assert svc.stats["failed"] >= 1
    assert svc.stats["fallback_proposals"] == 0
    # file NOT marked processed — will retry on next start
    assert str(f.name) not in svc._processed


def test_llm_write_pages_no_ops_marks_processed(tmp_path):
    """When LLM returns empty operations, file is marked processed (no-op)."""
    from types import SimpleNamespace as NS

    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    wiki = NS(
        root=tmp_path, raw_dir=tmp_path / "raw",
        ingest_source=lambda p: {"title": "t", "source_name": "s", "content": "x", "error": None},
        _llm_process_source=lambda r: {"operations": []},
        execute_operations=lambda ops: {"operations_executed": 0},
    )
    (tmp_path / "raw").mkdir()
    f = tmp_path / "raw" / "a.md"
    f.write_text("x")

    svc = AutoIngestService(
        wiki=wiki, wiki_id="t",
        config=AutoIngestConfig(debounce_seconds=0.05),
        llm_semaphore=asyncio.Semaphore(1),
    )
    asyncio.run(svc._process_file(f))
    assert svc.stats["skipped"] == 1
    assert str(f.name) in svc._processed


def test_status_method(tmp_path):
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    (tmp_path / "raw").mkdir()
    svc = AutoIngestService(
        wiki=SimpleNamespace(root=tmp_path, raw_dir=tmp_path / "raw"),
        wiki_id="t",
        config=AutoIngestConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    s = svc.status()
    assert s["wiki_id"] == "t"
    assert s["watching"] is False
    assert s["events"] == 0


def test_load_processed_corrupt_json(tmp_path):
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    (tmp_path / "raw").mkdir()
    state_file = tmp_path / ".llmwikify" / "maintenance" / "processed.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("{corrupt json!!")

    svc = AutoIngestService(
        wiki=SimpleNamespace(root=tmp_path, raw_dir=tmp_path / "raw"),
        wiki_id="t",
        config=AutoIngestConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    svc._load_processed()
    assert svc._processed == {}  # falls back to empty


def test_load_processed_wrong_version(tmp_path):
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    (tmp_path / "raw").mkdir()
    state_file = tmp_path / ".llmwikify" / "maintenance" / "processed.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(json.dumps({"version": 999, "files": {"a.md": {}}}))

    svc = AutoIngestService(
        wiki=SimpleNamespace(root=tmp_path, raw_dir=tmp_path / "raw"),
        wiki_id="t",
        config=AutoIngestConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    svc._load_processed()
    assert svc._processed == {}  # wrong version → empty


def test_file_state_oserror(tmp_path):
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    (tmp_path / "raw").mkdir()
    svc = AutoIngestService(
        wiki=SimpleNamespace(root=tmp_path, raw_dir=tmp_path / "raw"),
        wiki_id="t",
        config=AutoIngestConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    # nonexistent file → OSError → empty dict
    assert svc._file_state(tmp_path / "nonexistent.md") == {}


def test_on_watch_event_deleted_removes_from_pending(tmp_path):
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    (tmp_path / "raw").mkdir()
    svc = AutoIngestService(
        wiki=SimpleNamespace(root=tmp_path, raw_dir=tmp_path / "raw"),
        wiki_id="t",
        config=AutoIngestConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    svc._pending["/some/path.md"] = (1.0, 100)
    svc._on_watch_event("deleted", Path("/some/path.md"))
    assert "/some/path.md" not in svc._pending


def test_on_watch_event_no_loop(tmp_path):
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    (tmp_path / "raw").mkdir()
    svc = AutoIngestService(
        wiki=SimpleNamespace(root=tmp_path, raw_dir=tmp_path / "raw"),
        wiki_id="t",
        config=AutoIngestConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    svc._loop = None
    # should not crash
    svc._on_watch_event("created", Path("/some/new.md"))


# ═══════════════════════════════════════════════════════════════════════
# config.py — edge cases
# ═══════════════════════════════════════════════════════════════════════


def test_to_dict_roundtrip(tmp_path):
    from llmwikify.apps.agent.maintenance.config import (
        MaintenanceConfig,
        load_maintenance_config,
        to_dict,
    )

    path = tmp_path / "llmwikify.json"
    path.write_text(json.dumps({
        "maintenance": {
            "enabled": False,
            "auto_ingest": {"write_mode": "proposal", "max_backlog_per_start": 5},
            "gap_filler": {"max_per_cycle": 3, "use_llm_draft": False},
            "llm_rate_limit": {"max_requests": 10, "window_seconds": 2.0},
            "lint_interval_seconds": 7200,
            "gaps_interval_seconds": 1209600,
            "db_maintenance_interval_seconds": 259200,
        },
    }))
    cfg = load_maintenance_config(path)
    d = to_dict(cfg)
    assert d["enabled"] is False
    assert d["auto_ingest"]["write_mode"] == "proposal"
    assert d["auto_ingest"]["max_backlog_per_start"] == 5
    assert d["gap_filler"]["max_per_cycle"] == 3
    assert d["gap_filler"]["use_llm_draft"] is False
    assert d["llm_rate_limit"]["max_requests"] == 10
    assert d["llm_rate_limit"]["window_seconds"] == 2.0
    assert d["lint_interval_seconds"] == 7200


def test_config_non_dict_subsections_ignored(tmp_path):
    from llmwikify.apps.agent.maintenance.config import load_maintenance_config

    path = tmp_path / "llmwikify.json"
    path.write_text(json.dumps({
        "maintenance": {
            "auto_ingest": "not-a-dict",
            "gap_filler": 42,
            "llm_rate_limit": True,
        },
    }))
    cfg = load_maintenance_config(path)
    # defaults preserved when sub-sections are non-dict
    assert cfg.auto_ingest.enabled is True
    assert cfg.gap_filler.max_per_cycle == 5
    assert cfg.llm_rate_limit.max_requests == 5


def test_config_json_parse_error(tmp_path):
    from llmwikify.apps.agent.maintenance.config import load_maintenance_config

    path = tmp_path / "llmwikify.json"
    path.write_text("{not valid json")
    cfg = load_maintenance_config(path)
    assert cfg.enabled is True  # defaults


def test_config_maintenance_not_dict(tmp_path):
    from llmwikify.apps.agent.maintenance.config import load_maintenance_config

    path = tmp_path / "llmwikify.json"
    path.write_text(json.dumps({"maintenance": "string-not-dict"}))
    cfg = load_maintenance_config(path)
    assert cfg.enabled is True


# ═══════════════════════════════════════════════════════════════════════
# rate_limit.py — edge cases
# ═══════════════════════════════════════════════════════════════════════


def test_rate_limit_clamps_min_values():
    from llmwikify.apps.agent.maintenance.rate_limit import SlidingWindowRateLimiter

    rl = SlidingWindowRateLimiter(max_requests=0, window_seconds=-1)
    assert rl.max_requests == 1  # clamped
    assert rl.window_seconds == 0.01  # clamped


def test_rate_limit_cancellation():
    from llmwikify.apps.agent.maintenance.rate_limit import SlidingWindowRateLimiter

    rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)

    async def scenario():
        await rl.acquire()  # fills the single slot
        task = asyncio.create_task(rl.acquire())  # will wait
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # limiter still works after cancellation
        assert await rl.acquire() is True

    asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════════════════
# maintenance_manager — trigger and trim
# ═══════════════════════════════════════════════════════════════════════


def test_trigger_db_task():
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager

    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    mgr = MaintenanceManager(
        registry=SimpleNamespace(list_wikis=lambda: [], get_wiki=lambda w: None),
        config=cfg,
    )

    async def scenario():
        await mgr.start()
        result = await mgr.trigger("db")
        await mgr.stop()
        return result

    result = asyncio.run(scenario())
    assert result["task"] == "db"
    assert "db" in result


def test_trim_history():
    from llmwikify.apps.agent.maintenance import (
        HEALTH_HISTORY_LIMIT,
        MaintenanceConfig,
        MaintenanceManager,
    )

    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    mgr = MaintenanceManager(
        registry=SimpleNamespace(list_wikis=lambda: [], get_wiki=lambda w: None),
        config=cfg,
    )
    # simulate 50 history entries
    mgr._health_history = [{"i": i} for i in range(50)]
    mgr._trim_history()
    assert len(mgr._health_history) == HEALTH_HISTORY_LIMIT


def test_get_proposal_db_none_data_dir():
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager

    cfg = MaintenanceConfig()
    mgr = MaintenanceManager(
        registry=SimpleNamespace(list_wikis=lambda: [], get_wiki=lambda w: None),
        config=cfg,
        data_dir=None,
    )
    assert mgr._get_proposal_db() is None


def test_health_report_includes_rate_limit():
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager

    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    mgr = MaintenanceManager(
        registry=SimpleNamespace(list_wikis=lambda: [], get_wiki=lambda w: None),
        config=cfg,
    )
    report = mgr.health_report()
    assert "llm_rate_limit" in report
    assert report["llm_rate_limit"]["max_requests"] == 5


# ═══════════════════════════════════════════════════════════════════════
# maintenance_routes — trigger integration
# ═══════════════════════════════════════════════════════════════════════


def test_trigger_db_via_api(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager
    from llmwikify.interfaces.server.http.maintenance_routes import (
        register_maintenance_routes,
    )

    app = FastAPI()
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    mgr = MaintenanceManager(
        registry=SimpleNamespace(list_wikis=lambda: [], get_wiki=lambda w: None),
        config=cfg,
    )
    mgr._running = True
    app.state.maintenance_manager = mgr
    register_maintenance_routes(app)

    with TestClient(app) as client:
        resp = client.post("/api/maintenance/trigger?task=db")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"] == "db"
        assert "db" in body


def test_trigger_gaps_via_api(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager
    from llmwikify.interfaces.server.http.maintenance_routes import (
        register_maintenance_routes,
    )

    app = FastAPI()
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    mgr = MaintenanceManager(
        registry=SimpleNamespace(list_wikis=lambda: [], get_wiki=lambda w: None),
        config=cfg,
    )
    mgr._running = True
    app.state.maintenance_manager = mgr
    register_maintenance_routes(app)

    with TestClient(app) as client:
        resp = client.post("/api/maintenance/trigger?task=gaps")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"] == "gaps"


def test_health_report_api_includes_rate_limit():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager
    from llmwikify.interfaces.server.http.maintenance_routes import (
        register_maintenance_routes,
    )

    app = FastAPI()
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    cfg.gap_filler.enabled = False
    mgr = MaintenanceManager(
        registry=SimpleNamespace(list_wikis=lambda: [], get_wiki=lambda w: None),
        config=cfg,
    )
    mgr._running = True
    app.state.maintenance_manager = mgr
    register_maintenance_routes(app)

    with TestClient(app) as client:
        resp = client.get("/api/maintenance/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "llm_rate_limit" in body
        assert body["llm_rate_limit"]["max_requests"] == 5


# ═══════════════════════════════════════════════════════════════════════
# P2: health history persistence
# ═══════════════════════════════════════════════════════════════════════


def test_health_history_persists_across_instances(tmp_path):
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager
    from llmwikify.kernel.multi_wiki.instance import WikiInstance, WikiType

    wiki = SimpleNamespace(
        root=tmp_path, raw_dir=tmp_path / "raw", db_path=tmp_path / ".db",
        config={"llm": {"enabled": False}},
        lint=lambda **kw: {"issue_count": 1, "hints": {"critical": [], "informational": []}},
    )
    registry = SimpleNamespace(
        list_wikis=lambda: [WikiInstance(wiki_id="x", name="x", wiki_type=WikiType.LOCAL, root=tmp_path)],
        get_wiki=lambda wid: wiki,
    )

    # first instance: add history
    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    mgr1 = MaintenanceManager(registry=registry, config=cfg)
    asyncio.run(mgr1.start())
    asyncio.run(mgr1._lint_tick())
    asyncio.run(mgr1.stop())
    assert len(mgr1._health_history) >= 1

    # second instance: should load from disk
    mgr2 = MaintenanceManager(registry=registry, config=cfg)
    asyncio.run(mgr2.start())
    assert len(mgr2._health_history) >= 1  # loaded from disk
    asyncio.run(mgr2.stop())


def test_health_history_survives_restart(tmp_path):
    from llmwikify.apps.agent.maintenance import MaintenanceConfig, MaintenanceManager
    from llmwikify.kernel.multi_wiki.instance import WikiInstance, WikiType

    wiki = SimpleNamespace(
        root=tmp_path, raw_dir=tmp_path / "raw", db_path=tmp_path / ".db",
        config={"llm": {"enabled": False}},
        lint=lambda **kw: {"issue_count": 0, "hints": {}},
    )
    registry = SimpleNamespace(
        list_wikis=lambda: [WikiInstance(wiki_id="x", name="x", wiki_type=WikiType.LOCAL, root=tmp_path)],
        get_wiki=lambda wid: wiki,
    )

    cfg = MaintenanceConfig()
    cfg.auto_ingest.enabled = False
    mgr = MaintenanceManager(registry=registry, config=cfg)
    asyncio.run(mgr.start())
    asyncio.run(mgr._lint_tick())
    asyncio.run(mgr.stop())

    # verify file exists
    state_file = tmp_path / ".llmwikify" / "maintenance" / "health_history.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert len(data) >= 1
    assert data[0]["type"] == "lint"
