"""Tests for the autoresearch 6-step framework (Phase 1: clarify).

Covers:
- ResearchClarifier: clarify / scope_check / self-loop / fallback
- Six-step config: default values, merge, self-loop fields
- db_migrations: idempotent ALTER TABLE
- ResearchState: 6-step fields
- Engine: clarifies before plan on first run
"""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmwikify.agent.backend.db import AgentDatabase
from llmwikify.autoresearch import (
    DEFAULT_SIX_STEP_CONFIG,
    ResearchClarifier,
    ResearchEngine,
    ResearchState,
    VALID_TRANSITIONS,
    merge_six_step_config,
)
from llmwikify.autoresearch.config import merge_research_config
from llmwikify.autoresearch.db_migrations import (
    SIX_STEP_COLUMNS,
    ensure_six_step_columns,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return AgentDatabase(tmp_path / "test_autoresearch.db")


@pytest.fixture
def mock_wiki(tmp_path):
    wiki = MagicMock()
    wiki.root = tmp_path / "wiki"
    wiki.root.mkdir(parents=True, exist_ok=True)
    wiki.index_file = tmp_path / "wiki" / "index.md"
    wiki.index_file.write_text("# Test Wiki\n")
    wiki.search.return_value = []
    wiki.read_page.return_value = None
    return wiki


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    # Default JSON response for clarify calls
    llm.chat.return_value = json.dumps({
        "context": "test context",
        "boundaries": "test boundaries",
        "position": "researcher view",
        "premises": ["premise 1", "premise 2"],
        "scope_check": True,
    })
    return llm


@pytest.fixture
def config():
    return dict(DEFAULT_SIX_STEP_CONFIG)


# ─── 1. Config tests ──────────────────────────────────────────────


class TestAutoresearchConfig:
    def test_default_config_has_six_step_fields(self):
        assert "clarify_enabled" in DEFAULT_SIX_STEP_CONFIG
        assert "reasoning_check_enabled" in DEFAULT_SIX_STEP_CONFIG
        assert "structure_check_enabled" in DEFAULT_SIX_STEP_CONFIG
        assert "framework_check_enabled" in DEFAULT_SIX_STEP_CONFIG

    def test_default_self_loop_fields(self):
        assert DEFAULT_SIX_STEP_CONFIG["clarify_max_retries"] == 2
        assert DEFAULT_SIX_STEP_CONFIG["evidence_max_retries"] == 2
        assert DEFAULT_SIX_STEP_CONFIG["self_loop_budget_ratio"] == 0.3

    def test_default_retry_managers(self):
        assert DEFAULT_SIX_STEP_CONFIG["stage_max_retries"] == 2
        assert DEFAULT_SIX_STEP_CONFIG["llm_parse_max_retries"] == 3
        assert DEFAULT_SIX_STEP_CONFIG["db_retry_max_retries"] == 3

    def test_default_six_step_thresholds(self):
        assert DEFAULT_SIX_STEP_CONFIG["gate_min_evidence_score"] == 0.5
        assert DEFAULT_SIX_STEP_CONFIG["gate_min_traceable_sources"] == 2
        assert DEFAULT_SIX_STEP_CONFIG["gate_min_reasoning_score"] == 7
        assert DEFAULT_SIX_STEP_CONFIG["gate_min_structure_score"] == 7
        assert DEFAULT_SIX_STEP_CONFIG["gate_min_source_refs"] == 3

    def test_merge_research_config_alias(self):
        # The copied engine.py uses merge_research_config; it must exist.
        assert merge_research_config is merge_six_step_config
        merged = merge_six_step_config({"clarify_enabled": False})
        assert merged["clarify_enabled"] is False
        merged2 = merge_six_step_config({"clarify_max_retries": 5})
        assert merged2["clarify_max_retries"] == 5

    def test_merge_ignores_unknown_keys(self):
        merged = merge_six_step_config({"unknown_key": "x"})
        assert "unknown_key" not in merged


# ─── 2. DB migration tests ─────────────────────────────────────────


class TestDBMigrations:
    def test_ensure_columns_adds_three(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        # Create a minimal research_sessions table to match the base
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE research_sessions (id TEXT PRIMARY KEY, query TEXT)"
            )
            conn.commit()

        ensure_six_step_columns(db_path)

        with sqlite3.connect(db_path) as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(research_sessions)").fetchall()]
        for col, _ in SIX_STEP_COLUMNS:
            assert col in cols

    def test_ensure_columns_is_idempotent(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE research_sessions (id TEXT PRIMARY KEY)")
            conn.commit()

        # Run twice; second call should not raise
        ensure_six_step_columns(db_path)
        ensure_six_step_columns(db_path)

        with sqlite3.connect(db_path) as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(research_sessions)").fetchall()]
        assert len([c for c in cols if c in (c for c, _ in SIX_STEP_COLUMNS)]) == 3


# ─── 3. ResearchState tests ────────────────────────────────────────


class TestResearchState:
    def test_has_6step_fields(self):
        state = ResearchState()
        assert state.clarification is None
        assert state.reasoning_check is None
        assert state.structure_check is None
        assert state.evidence_scores == []
        assert state.self_loop_counts == {}
        assert state.self_loop_history == []

    def test_inherits_base_fields(self):
        state = ResearchState()
        assert state.phase == ""
        assert state.sources == []
        assert state.sub_queries == []
        assert state.budget_remaining == 1.0


class TestValidTransitions:
    def test_clarifying_state_present(self):
        assert "clarifying" in VALID_TRANSITIONS
        assert VALID_TRANSITIONS["clarifying"] == ["plan"]

    def test_none_can_go_to_clarifying(self):
        assert "clarifying" in VALID_TRANSITIONS[None]

    def test_all_base_transitions_preserved(self):
        for state, targets in [
            ("planning", ["gather"]),
            ("gathering", ["analyze", "plan"]),
            ("synthesizing", ["reporting", "plan"]),
            ("reporting", ["reviewing"]),
            ("reviewing", ["revise", "done"]),
        ]:
            assert VALID_TRANSITIONS[state] == targets


# ─── 4. ResearchClarifier tests ────────────────────────────────────


class TestResearchClarifier:
    def test_clarify_success(self, mock_llm):
        clarifier = ResearchClarifier(mock_llm)
        result = _run_async(clarifier.clarify("What is X?"))
        assert result["scope_check"] is True
        assert result["context"] == "test context"
        assert len(result["premises"]) == 2

    def test_clarify_handles_code_fence(self, mock_llm):
        mock_llm.chat.return_value = "```json\n" + json.dumps({
            "context": "ctx", "boundaries": "bnd", "position": "pos",
            "premises": ["p1"], "scope_check": True,
        }) + "\n```"
        clarifier = ResearchClarifier(mock_llm)
        result = _run_async(clarifier.clarify("Q?"))
        assert result["context"] == "ctx"

    def test_clarify_falls_back_on_llm_error(self, mock_llm):
        mock_llm.chat.side_effect = RuntimeError("LLM down")
        clarifier = ResearchClarifier(mock_llm)
        result = _run_async(clarifier.clarify("Q?"))
        assert result["fallback"] is True
        assert result["scope_check"] is True
        assert "fallback_reason" in result

    def test_clarify_falls_back_on_invalid_json(self, mock_llm):
        mock_llm.chat.return_value = "not json at all"
        clarifier = ResearchClarifier(mock_llm)
        result = _run_async(clarifier.clarify("Q?"))
        assert result["fallback"] is True

    def test_scope_check_false_triggers_retry(self, mock_llm):
        # First call: scope_check=false; second call: true
        mock_llm.chat.side_effect = [
            json.dumps({
                "context": "broad", "boundaries": "wide",
                "position": "researcher", "premises": ["vague"],
                "scope_check": False,
            }),
            json.dumps({
                "context": "narrowed", "boundaries": "tight",
                "position": "researcher", "premises": ["specific"],
                "scope_check": True,
            }),
        ]
        clarifier = ResearchClarifier(mock_llm, config={"clarify_max_retries": 2, "self_loop_budget_ratio": 0.3})
        result, history = _run_async(clarifier.clarify_with_loop("Q?", budget_remaining=1.0))
        assert result["scope_check"] is True
        assert len(history) == 2  # initial + 1 retry

    def test_self_loop_respects_budget(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "context": "x", "boundaries": "y", "position": "z",
            "premises": [], "scope_check": False,
        })
        clarifier = ResearchClarifier(mock_llm, config={"clarify_max_retries": 5, "self_loop_budget_ratio": 0.5})
        result, history = _run_async(clarifier.clarify_with_loop("Q?", budget_remaining=0.1))  # < 0.5
        # Should stop after initial attempt
        assert len(history) == 1

    def test_self_loop_exhausted_adds_warning(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "context": "x", "boundaries": "y", "position": "z",
            "premises": [], "scope_check": False,
        })
        clarifier = ResearchClarifier(mock_llm, config={"clarify_max_retries": 1, "self_loop_budget_ratio": 0.0})
        result, history = _run_async(clarifier.clarify_with_loop("Q?", budget_remaining=0.5))
        # 2 attempts (initial + 1 retry), but scope_check still false
        assert len(history) == 2
        assert "warnings" in result
        assert any("澄清重试超限" in w for w in result["warnings"])


# ─── 5. Engine integration tests ───────────────────────────────────


class TestEngineInitialization:
    def test_engine_init_runs_db_migration(self, mock_wiki, mock_llm, db, config):
        # Before init, no six-step columns
        with sqlite3.connect(db.db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(research_sessions)").fetchall()]
        assert not any(c in (cc for cc, _ in SIX_STEP_COLUMNS) for c in cols)

        # Init engine (should run migration)
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        assert hasattr(engine, "clarifier")
        assert isinstance(engine.clarifier, ResearchClarifier)

        # After init, columns exist
        with sqlite3.connect(db.db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(research_sessions)").fetchall()]
        for col, _ in SIX_STEP_COLUMNS:
            assert col in cols

    def test_engine_init_uses_six_step_config(self, mock_wiki, mock_llm, db):
        # merge_research_config == merge_six_step_config, so engine sees all keys
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        assert engine.config["clarify_enabled"] is True
        assert engine.config["clarify_max_retries"] == 2


class TestEngineClarifyIntegration:
    def test_run_starts_with_clarify_event(self, mock_wiki, mock_llm, db, config):
        """The first event after reasoning should be a clarification_complete."""
        config["max_react_rounds"] = 2
        # Engine.run needs LLM for clarify + planning + report. Mock in order:
        mock_llm.chat.side_effect = [
            # 1. Clarifier LLM call
            json.dumps({
                "context": "ctx", "boundaries": "bnd", "position": "p",
                "premises": ["p1"], "scope_check": True,
            }),
            # 2. Plan LLM
            json.dumps([{"query": "sub", "source_type": "web", "url": ""}]),
            # 3. Reason: gather
            json.dumps({"thought": "sub_queries ready", "action": "gather"}),
            # 4. Reason: synthesize
            json.dumps({"thought": "have sources", "action": "synthesize"}),
            # 5. Reason: report
            json.dumps({"thought": "synth done", "action": "report"}),
            # 6. Report LLM
            "# Report\n\nContent [[Source:abc]]",
            # 7. Reason: review
            json.dumps({"thought": "report done", "action": "review"}),
            # 8. Review LLM
            json.dumps({"approved": True, "score": 8, "feedback": "ok", "issues": []}),
            # 9. Reason: done
            json.dumps({"thought": "all approved", "action": "done"}),
        ]

        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        session_id = engine.session_manager.create_session("test wiki", "What is X?")
        events = _run_async(_collect_events(engine.run(session_id, "What is X?")))
        types = [e.get("type") for e in events]

        # Must see clarify event early
        assert "clarification_complete" in types
        # The clarify must come before the first plan (in events list)
        clarify_idx = types.index("clarification_complete")
        first_plan_step = next(
            (i for i, ev in enumerate(events)
             if ev.get("type") == "step" and "Planning" in ev.get("message", "")),
            None,
        )
        # Clarification happens first in our flow (before _react_loop even starts)
        if first_plan_step is not None:
            assert clarify_idx < first_plan_step


# ─── Helpers ───────────────────────────────────────────────────────


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        raise


async def _collect_events(aiter):
    out = []
    async for e in aiter:
        out.append(e)
    return out
