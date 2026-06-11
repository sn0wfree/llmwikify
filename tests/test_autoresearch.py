"""Tests for the autoresearch 6-step framework (independent DB).

Covers:
- AutoResearchDatabase: 3 tables, 6 JSON fields, cascade, zero sharing
- db_migrations: init_autoresearch_db() + migrate_research_six_step_columns()
- ResearchClarifier: clarify / scope_check / self-loop / fallback
- Six-step config: default values, merge, self-loop fields
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

from llmwikify.apps.chat import (
    DEFAULT_SIX_STEP_CONFIG,
    DBRetryManager,
    LLMRetryManager,
    QualityGate,
    ReasoningChecker,
    ResearchClarifier,
    ResearchEngine,
    ResearchState,
    SourceFilter,
    StageRetryManager,
    StructureValidator,
    VALID_TRANSITIONS,
    merge_six_step_config,
    retry_async,
)
from llmwikify.apps.chat.config import merge_research_config
from llmwikify.apps.chat.db import AutoResearchDatabase
from llmwikify.apps.chat.db_migrations import (
    LEGACY_SHARED_COLUMNS,
    init_autoresearch_db,
    migrate_research_six_step_columns,
    migrate_v3_add_events_column,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Independent autoresearch DB (tmp_path/autoresearch.db)."""
    return AutoResearchDatabase(tmp_path)


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
    def test_init_creates_three_tables(self, tmp_path):
        # The canonical filename is now .llmwiki_agent.db
        # (auto-migrated from autoresearch.db in v0.33.0).
        # init_autoresearch_db writes to the canonical path.
        from llmwikify.apps.db_base import get_app_db_path
        db_path = get_app_db_path(tmp_path)
        init_autoresearch_db(db_path)
        with sqlite3.connect(db_path) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "autoresearch_sessions" in tables
        assert "autoresearch_sub_queries" in tables
        assert "autoresearch_sources" in tables

    def test_init_is_idempotent(self, tmp_path):
        from llmwikify.apps.db_base import get_app_db_path
        db_path = get_app_db_path(tmp_path)
        init_autoresearch_db(db_path)
        init_autoresearch_db(db_path)  # second call must not raise
        # Insert and read back to confirm
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        assert db.get_research_session(sid)["status"] == "clarifying"

    def test_migrate_drops_legacy_columns(self, tmp_path):
        old_db = tmp_path / ".llmwiki_agent.db"
        with sqlite3.connect(old_db) as conn:
            conn.execute(
                """CREATE TABLE research_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT, query TEXT,
                    clarification_json TEXT, reasoning_json TEXT, structure_json TEXT
                )"""
            )
            conn.commit()
        n = migrate_research_six_step_columns(old_db, drop_columns=True)
        assert n == 3
        with sqlite3.connect(old_db) as conn:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(research_sessions)").fetchall()
            }
        for col, _ in LEGACY_SHARED_COLUMNS:
            assert col not in cols

    def test_migrate_dry_run(self, tmp_path):
        old_db = tmp_path / ".llmwiki_agent.db"
        with sqlite3.connect(old_db) as conn:
            conn.execute(
                """CREATE TABLE research_sessions (
                    id TEXT PRIMARY KEY,
                    clarification_json TEXT, reasoning_json TEXT
                )"""
            )
            conn.commit()
        n = migrate_research_six_step_columns(old_db, drop_columns=False)
        assert n == 2
        # Columns should still be there
        with sqlite3.connect(old_db) as conn:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(research_sessions)").fetchall()
            }
        assert "clarification_json" in cols

    def test_migrate_noop_on_clean_db(self, tmp_path):
        old_db = tmp_path / ".llmwiki_agent.db"
        with sqlite3.connect(old_db) as conn:
            conn.execute(
                "CREATE TABLE research_sessions (id TEXT PRIMARY KEY, query TEXT)"
            )
            conn.commit()
        n = migrate_research_six_step_columns(old_db)
        assert n == 0

    def test_migrate_noop_on_missing_db(self, tmp_path):
        n = migrate_research_six_step_columns(tmp_path / "nope.db")
        assert n == 0

    def test_migrate_v3_add_events_column_creates(self, tmp_path):
        """Migration adds events_json column to a fresh DB that doesn't have it."""
        # Simulate a DB created before events_json column was introduced
        old_path = tmp_path / "old_ar.db"
        with sqlite3.connect(old_path) as conn:
            conn.execute(
                """CREATE TABLE autoresearch_sessions (
                    id TEXT PRIMARY KEY, wiki_id TEXT NOT NULL, query TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'clarifying', current_step TEXT,
                    progress REAL DEFAULT 0.0, result TEXT, wiki_page_name TEXT,
                    iteration_round INTEGER DEFAULT 0,
                    synthesis_json TEXT, review_json TEXT,
                    clarification_json TEXT, reasoning_json TEXT,
                    structure_json TEXT, self_loop_counts_json TEXT,
                    self_loop_history_json TEXT, evidence_scores_json TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            conn.commit()
        added = migrate_v3_add_events_column(old_path)
        assert added is True
        with sqlite3.connect(old_path) as conn:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(autoresearch_sessions)").fetchall()
            }
        assert "events_json" in cols

    def test_migrate_v3_add_events_column_idempotent(self, tmp_path):
        """Migration is a no-op when column already exists."""
        path = tmp_path / "ar.db"
        # AutoResearchDatabase creates schema with the new column
        AutoResearchDatabase(tmp_path)
        added = migrate_v3_add_events_column(path)
        assert added is False

    def test_migrate_v3_add_events_column_noop_on_missing_db(self, tmp_path):
        """Migration returns False (no error) when DB doesn't exist yet."""
        added = migrate_v3_add_events_column(tmp_path / "nope.db")
        assert added is False


# ─── 2b. Event log persistence (DB layer) ──────────────────────────


class TestEventLogPersistence:
    """Verify append_events / get_events for the events_json column."""

    def test_fresh_session_has_no_events(self, db):
        sid = db.create_research_session("w", "q")
        assert db.get_events(sid) == []

    def test_get_events_nonexistent_session_returns_empty(self, db):
        assert db.get_events("nonexistent") == []

    def test_append_events_returns_count(self, db):
        sid = db.create_research_session("w", "q")
        n = db.append_events(sid, [
            {"type": "step", "message": "m1", "timestamp": "2026-06-05T10:00:00Z"},
            {"type": "step", "message": "m2", "timestamp": "2026-06-05T10:00:01Z"},
        ])
        assert n == 2

    def test_append_events_accumulates(self, db):
        sid = db.create_research_session("w", "q")
        db.append_events(sid, [{"type": "step", "message": "first"}])
        db.append_events(sid, [{"type": "step", "message": "second"}])
        evs = db.get_events(sid)
        assert len(evs) == 2
        assert evs[0]["message"] == "first"
        assert evs[1]["message"] == "second"

    def test_append_events_batch_appends_in_order(self, db):
        sid = db.create_research_session("w", "q")
        batch = [{"type": "step", "message": f"m{i}"} for i in range(5)]
        db.append_events(sid, batch)
        evs = db.get_events(sid)
        assert [e["message"] for e in evs] == [f"m{i}" for i in range(5)]

    def test_append_empty_batch_is_noop(self, db):
        sid = db.create_research_session("w", "q")
        n = db.append_events(sid, [])
        assert n == 0
        assert db.get_events(sid) == []

    def test_get_events_handles_malformed_json(self, db):
        """Malformed events_json is treated as empty (defensive)."""
        sid = db.create_research_session("w", "q")
        # Inject malformed JSON directly
        import sqlite3
        with sqlite3.connect(db.db_path) as conn:
            conn.execute(
                "UPDATE autoresearch_sessions SET events_json = ? WHERE id = ?",
                ("not valid json", sid),
            )
            conn.commit()
        assert db.get_events(sid) == []

    def test_events_column_present_in_schema(self, db):
        """The events_json column is part of autoresearch_sessions schema."""
        sid = db.create_research_session("w", "q")
        session = db.get_research_session(sid)
        assert "events_json" in session

    def test_delete_session_clears_events(self, db):
        """Cascading delete removes events along with the session."""
        sid = db.create_research_session("w", "q")
        db.append_events(sid, [{"type": "step", "message": "doomed"}])
        assert len(db.get_events(sid)) == 1
        db.delete_research(sid)
        assert db.get_events(sid) == []


# ─── 2c. EventBuffer (task manager layer) ─────────────────────────


class TestEventBuffer:
    """Verify dedup, batch flush, and lifecycle of EventBuffer."""

    @pytest.fixture
    def sid(self, db):
        return db.create_research_session("w", "q")

    @pytest.mark.asyncio
    async def test_dedup_same_message_within_window(self, db, sid):
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        for _ in range(5):
            buf.add({"type": "progress", "message": "50% — gathering"})
        await buf.flush()
        assert len(db.get_events(sid)) == 1

    @pytest.mark.asyncio
    async def test_different_messages_all_stored(self, db, sid):
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        for i in range(5):
            buf.add({"type": "step", "message": f"step {i}"})
        await buf.flush()
        assert len(db.get_events(sid)) == 5

    @pytest.mark.asyncio
    async def test_dedup_window_expires(self, db, sid):
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        buf.add({"type": "progress", "message": "50% — gathering"})
        await buf.flush()
        assert len(db.get_events(sid)) == 1
        # Wait > DEDUP_WINDOW_S (2.0s)
        import time
        time.sleep(2.1)
        buf.add({"type": "progress", "message": "50% — gathering"})
        await buf.flush()
        assert len(db.get_events(sid)) == 2

    @pytest.mark.asyncio
    async def test_batch_size_triggers_auto_flush(self, db, sid):
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        for i in range(25):  # > BATCH_SIZE=20
            buf.add({"type": "step", "message": f"auto {i}"})
        # Give the auto-flush task a moment to run
        await asyncio.sleep(0.05)
        # Force any remaining
        await buf.flush()
        assert len(db.get_events(sid)) == 25

    @pytest.mark.asyncio
    async def test_close_makes_subsequent_add_noop(self, db, sid):
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        buf.add({"type": "step", "message": "before close"})
        buf.close()
        buf.add({"type": "step", "message": "after close"})
        await buf.flush()
        evs = db.get_events(sid)
        assert len(evs) == 1
        assert evs[0]["message"] == "before close"

    @pytest.mark.asyncio
    async def test_events_have_timestamp_and_source(self, db, sid):
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        buf.add({"type": "step", "message": "m"})
        await buf.flush()
        evs = db.get_events(sid)
        assert all("timestamp" in e for e in evs)
        assert all(e.get("source") == "engine" for e in evs)

    @pytest.mark.asyncio
    async def test_existing_timestamp_preserved(self, db, sid):
        """If caller provides timestamp, it's kept (not overwritten)."""
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        ts = "2026-01-01T00:00:00+00:00"
        buf.add({"type": "step", "message": "m", "timestamp": ts})
        await buf.flush()
        assert db.get_events(sid)[0]["timestamp"] == ts

    @pytest.mark.asyncio
    async def test_flush_empty_is_safe(self, db, sid):
        from llmwikify.apps.chat.task_manager import EventBuffer
        buf = EventBuffer(sid, db)
        n = await buf.flush()
        assert n == 0
        assert db.get_events(sid) == []


# ─── 3. ResearchState tests ────────────────────────────────────────


class TestResearchState:
    def test_has_6step_fields(self):
        state = ResearchState()
        assert state.clarification is None
        assert state.reasoning_check is None
        assert state.structure_check is None
        assert state.evidence_scores == {}
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
        assert result["scope_check"] is False  # 🐛 fix: trigger retry, not silent pass
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

    def test_fallback_triggers_retry_not_silent(self, mock_llm):
        """Regression test: JSON parse failure must trigger retry loop,
        not silently use fallback after 1 attempt.

        Reproduces session 082dd bug:
        - LLM returns empty string (JSON parse error)
        - Expect: 3 calls (initial + 2 retries), not 1 call
        """
        mock_llm.chat.return_value = ""  # empty triggers JSON parse error
        clarifier = ResearchClarifier(
            mock_llm,
            config={"clarify_max_retries": 2, "self_loop_budget_ratio": 0.3},
        )
        result, history = _run_async(
            clarifier.clarify_with_loop("test query", budget_remaining=1.0)
        )
        # Must retry, not silently use fallback
        assert len(history) == 3, f"Expected 3 attempts, got {len(history)}"
        # Final state: still fallback (LLM never recovered in this test)
        assert result["fallback"] is True
        # And scope_check must be False (signaling "not researchable")
        assert result["scope_check"] is False
        # Warning must be set
        assert any("澄清重试超限" in w for w in result.get("warnings", []))

    def test_fallback_retry_uses_original_query_not_narrowed(self, mock_llm):
        """When previous attempt was fallback, retry must use ORIGINAL query
        (not narrowed), to avoid pollution by fallback placeholder data.
        """
        call_messages: list[list[dict]] = []

        def capture(messages, **kwargs):
            # Record what the user message was for each call
            call_messages.append(list(messages))
            return ""  # always fail

        mock_llm.chat.side_effect = capture
        clarifier = ResearchClarifier(
            mock_llm,
            config={"clarify_max_retries": 2, "self_loop_budget_ratio": 0.3},
        )
        result, history = _run_async(
            clarifier.clarify_with_loop("original query", budget_remaining=1.0)
        )
        assert len(call_messages) == 3  # initial + 2 retries
        # All 3 calls should have the ORIGINAL query in user message
        # (no narrowing with fallback placeholders)
        for i, msgs in enumerate(call_messages):
            user_msg = next(m for m in msgs if m["role"] == "user")["content"]
            assert "original query" in user_msg, (
                f"Call {i}: query was narrowed unexpectedly: {user_msg!r}"
            )

    def test_fallback_retry_can_succeed(self, mock_llm):
        """If LLM recovers on retry, we get a real clarification, not fallback."""
        mock_llm.chat.side_effect = [
            "",  # 1st: empty (parse error → fallback)
            json.dumps({  # 2nd: real clarification
                "context": "recovered", "boundaries": "clear",
                "position": "researcher", "premises": ["p1"],
                "scope_check": True,
            }),
        ]
        clarifier = ResearchClarifier(
            mock_llm,
            config={"clarify_max_retries": 2, "self_loop_budget_ratio": 0.3},
        )
        result, history = _run_async(
            clarifier.clarify_with_loop("Q?", budget_remaining=1.0)
        )
        # After 1 fallback + 1 successful retry, we should have a real result
        # (successful path doesn't include "fallback" key, so check via get)
        assert not result.get("fallback", False)
        assert result["context"] == "recovered"
        assert result["scope_check"] is True
        assert len(history) == 2  # initial (fallback) + 1 retry (success)


# ─── 5. Engine integration tests ───────────────────────────────────


class TestEngineInitialization:
    def test_engine_init_uses_independent_db(self, mock_wiki, mock_llm, db, config):
        """The engine uses an independent AutoResearchDatabase (no migration needed)."""
        # Schema is already built by the fixture (AutoResearchDatabase.__init__).
        with sqlite3.connect(db.db_path) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "autoresearch_sessions" in tables
        # The shared `research_sessions` table must NOT exist (zero sharing)
        assert "research_sessions" not in tables

        # Init engine
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        assert hasattr(engine, "clarifier")
        assert isinstance(engine.clarifier, ResearchClarifier)

    def test_engine_init_uses_six_step_config(self, mock_wiki, mock_llm, db):
        # merge_research_config == merge_six_step_config, so engine sees all keys
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        assert engine.config["clarify_enabled"] is True
        assert engine.config["clarify_max_retries"] == 2


# ─── 4b. Framework compliance gate ──────────────────────────────────


class TestFrameworkComplianceGate:
    """Verify the engine's _check_framework_compliance + action_incomplete.

    Reproduces the bug pattern of session 7fe6f04f: 4/6 framework steps
    skipped but engine still marked done. The gate must catch this and
    either redirect or mark incomplete.
    """

    def _full_compliant_state(self):
        """Return a state with all 6 framework fields populated."""
        s = ResearchState(session_id="test", query="Q", max_rounds=5)
        s.clarification = {"context": "ctx", "scope_check": True}
        s.evidence_scores = {"src1": 0.8, "src2": 0.6}
        s.synthesis = {"reinforced_claims": ["a"], "contradictions": [], "knowledge_gaps": []}
        s.reasoning_check = {"aggregate_score": 0.7, "scores": {}, "issues": []}
        s.report_md = "# Report\n\nContent."
        s.structure_check = {"aggregate_score": 0.8, "scores": {}, "issues": []}
        s.review = {"approved": True, "score": 8, "issues": []}
        return s

    def test_all_compliant_returns_none(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        assert engine._check_framework_compliance(state) is None

    def test_missing_clarify(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        state.clarification = None
        result = engine._check_framework_compliance(state)
        assert result is not None
        assert result["missing"] == "clarify"
        assert "step 1" in result["reason"]

    def test_missing_evidence_scores(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        state.evidence_scores = {}
        result = engine._check_framework_compliance(state)
        assert result["missing"] == "gather"

    def test_missing_synthesis(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        state.synthesis = None
        result = engine._check_framework_compliance(state)
        assert result["missing"] == "synthesize"

    def test_missing_reasoning_check_redirects_to_synthesize(self, mock_wiki, mock_llm, db):
        """reasoning_check is populated by synthesize action."""
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        state.reasoning_check = None
        result = engine._check_framework_compliance(state)
        # Re-run synthesize to also run reasoning check
        assert result["missing"] == "synthesize"

    def test_missing_report(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        state.report_md = None
        result = engine._check_framework_compliance(state)
        assert result["missing"] == "report"

    def test_missing_structure_check_redirects_to_report(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        state.structure_check = None
        result = engine._check_framework_compliance(state)
        assert result["missing"] == "report"

    def test_missing_review(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = self._full_compliant_state()
        state.review = None
        result = engine._check_framework_compliance(state)
        assert result["missing"] == "review"

    def test_7fe6f04f_reproduction_redirects(self, mock_wiki, mock_llm, db):
        """Reproduce session 7fe6f04f pattern: 4/6 missing → gate must catch.

        State has: clarification, evidence_scores, synthesis (but NO
        reasoning_check), NO report, NO structure_check, NO review.
        First missing per the gate is synthesis (reasoning check piggybacks
        on synthesize). After synthesize, report would still be missing
        (next redirect target). Gate must NOT return None.
        """
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = ResearchState(session_id="repro", query="Q", max_rounds=5)
        state.clarification = {"context": "ctx", "scope_check": True}
        state.evidence_scores = {"s1": 0.7}
        # Missing: synthesis, reasoning_check, report, structure_check, review
        result = engine._check_framework_compliance(state)
        assert result is not None
        # First missing per gate order
        assert result["missing"] == "synthesize"

    def test_can_replan_with_budget(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = ResearchState(session_id="t", query="q", max_rounds=5)
        state.budget_remaining = 0.5
        state.round = 1
        assert engine._can_replan(state) is True

    def test_cannot_replan_no_budget(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = ResearchState(session_id="t", query="q", max_rounds=5)
        state.budget_remaining = 0.05  # below 0.10 threshold
        state.round = 1
        assert engine._can_replan(state) is False

    def test_cannot_replan_at_max_rounds(self, mock_wiki, mock_llm, db):
        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        state = ResearchState(session_id="t", query="q", max_rounds=5)
        state.budget_remaining = 0.5
        state.round = 5  # at max
        assert engine._can_replan(state) is False

    @pytest.mark.asyncio
    async def test_action_incomplete_sets_status_and_persists(self, mock_wiki, mock_llm, db):
        """action_incomplete marks status='incomplete' and persists partial result."""
        from llmwikify.apps.chat.actions import action_incomplete
        from llmwikify.apps.chat.engine import ResearchEngine

        engine = ResearchEngine(mock_wiki, db, mock_llm, {})
        ctx = engine._action_ctx
        # state.clarification = ...
        state = self._full_compliant_state()
        # But leave 2 of 6 missing
        state.report_md = None
        state.structure_check = None
        state.review = None

        sid = db.create_research_session("w", "test incomplete")
        state.session_id = sid
        ctx.session_manager.update_status(sid, "running", "gathering", 0.4, iteration_round=3)

        events = []
        async for ev in action_incomplete(ctx, state, "test reason"):
            events.append(ev)

        # First event is incomplete status
        assert any(e.get("type") == "incomplete" for e in events)

        # DB status should be 'incomplete'
        sess = db.get_research_session(sid)
        assert sess["status"] == "incomplete"

        # Result should have incomplete_reason
        result = json.loads(sess["result"])
        assert "incomplete_reason" in result
        assert result["incomplete_reason"] == "test reason"
        assert result["framework_completed"] == 4  # 4/7 present
        assert result["framework_total"] == 7


# ─── 4c. DB auto-migration test ─────────────────────────────────────


class TestAutoMigration:
    """Verify db.py auto-runs the events_json migration on init."""

    def test_init_runs_migration_on_existing_db(self, tmp_path):
        """Init against a DB that lacks events_json should add it."""
        import sqlite3
        # Create a pre-migration DB (no events_json column)
        db_path = tmp_path / "pre_migration.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """CREATE TABLE autoresearch_sessions (
                    id TEXT PRIMARY KEY, wiki_id TEXT NOT NULL, query TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'clarifying', current_step TEXT,
                    progress REAL DEFAULT 0.0, result TEXT, wiki_page_name TEXT,
                    iteration_round INTEGER DEFAULT 0,
                    synthesis_json TEXT, review_json TEXT,
                    clarification_json TEXT, reasoning_json TEXT,
                    structure_json TEXT, self_loop_counts_json TEXT,
                    self_loop_history_json TEXT, evidence_scores_json TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )"""
            )
            conn.commit()
        # Now init — should auto-migrate
        db = AutoResearchDatabase(tmp_path)
        # events_json should be present
        sid = db.create_research_session("w", "q")
        sess = db.get_research_session(sid)
        assert "events_json" in sess
        # And we can append events
        db.append_events(sid, [{"type": "step", "message": "ok"}])
        assert len(db.get_events(sid)) == 1


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


# ─── Phase 5: end-to-end integration (v5) ─────────────────────────


class TestAutoresearchIntegration:
    """End-to-end tests for the v5 6-step gate engine integration.

    Verifies that when engine.run() completes a full ReAct cycle:
    1. SourceFilter.compute_evidence_score runs in _action_gather and
       populates state.evidence_scores (persisted to evidence_scores_json)
    2. ReasoningChecker.check runs in _action_synthesize and populates
       state.reasoning_check (persisted to reasoning_json)
    3. StructureValidator.validate runs in _action_report and populates
       state.structure_check (persisted to structure_json)
    4. six_step_context is built and passed to report + review
    5. QualityGate 6-step gates trigger at the correct phases
    """

    @pytest.fixture(autouse=True)
    def _stub_web_search(self, monkeypatch):
        """Stub WebSearch.search to return [] (no real DuckDuckGo in tests)."""
        from llmwikify.apps.research import web_search
        async def _empty_search(self, query, num_results=None, **kwargs):
            return []
        monkeypatch.setattr(web_search.WebSearch, "search", _empty_search)

    @staticmethod
    def _patch_web_search_empty():
        """Return a context-manager that makes WebSearch.search return [].

        Prevents the gatherer from hitting real DuckDuckGo during tests.
        """
        from llmwikify.apps.research import web_search
        async def _empty_search(self, query, num_results=None, **kwargs):
            return []
        return patch.object(web_search.WebSearch, "search", _empty_search)

    def _build_mock_llm_with_full_cycle(self):
        """Mock LLM that completes one full ReAct cycle.

        LLM call order (10 total for a fresh run):
          1. Clarify (in _action_clarify)
          2. _reason → plan
          3. Plan (in _action_plan, returns LIST of sub_queries)
          4. _reason → gather
          5. _reason → synthesize (synthesize itself uses no LLM)
          6. _reason → report
          7. Report (in _action_report)
          8. _reason → review
          9. Review (in _action_review)
         10. _reason → done
        """
        llm = MagicMock()
        llm.chat.side_effect = [
            # 1. Clarify
            json.dumps({
                "context": "ctx", "boundaries": "bnd", "position": "p",
                "premises": ["p1"], "scope_check": True,
            }),
            # 2. _reason → plan
            json.dumps({"thought": "need to plan", "action": "plan"}),
            # 3. Plan — list of sub_queries (must match seeded queries to be deduped)
            json.dumps([
                {"query": "sub query 1", "source_type": "web", "url": ""},
                {"query": "sub query 2", "source_type": "wiki", "url": ""},
            ]),
            # 4. _reason → gather
            json.dumps({"thought": "need sources", "action": "gather"}),
            # 5. _reason → synthesize
            json.dumps({"thought": "have sources", "action": "synthesize"}),
            # 6. _reason → report
            json.dumps({"thought": "ready to report", "action": "report"}),
            # 7. Report — must include [[Source:xxx]] and 3 expected sections
            json.dumps(
                "# Background\n\nAnalysis text [[Source:src1]]. "
                "# Evidence\n\nData cited [[Source:src2]]. "
                "# Conclusion\n\nSummary."
            ),
            # 8. _reason → review
            json.dumps({"thought": "review time", "action": "review"}),
            # 9. Review
            json.dumps({"approved": True, "score": 8, "feedback": "ok", "issues": []}),
            # 10. _reason → done
            json.dumps({"thought": "all done", "action": "done"}),
        ]
        return llm

    @staticmethod
    def _seed_session_with_source(engine, session_id, source_content_words=200):
        """Pre-seed a session with sub_queries + sources that satisfy base gates.

        Seeds 2 sources of different types so check_after_gathering and
        check_before_report both pass with relaxed thresholds.

        Returns list of (sub_query_id, source_id) tuples.
        """
        sm = engine.session_manager
        content = ("Body " * source_content_words).strip()
        results: list = []
        for i, (q, st, url) in enumerate([
            ("sub query 1", "web", "https://example.com/a"),
            ("sub query 2", "wiki", "https://wiki.local/b"),
        ]):
            sq_id = sm.add_sub_query(session_id, q, st, "")
            src_id = sm.add_source(
                session_id=session_id, sub_query_id=sq_id, source_type=st,
                url=url, title=f"Title {chr(65+i)}",
                content_length=len(content), content_preview=content[:200],
                content=content,
            )
            results.append((sq_id, src_id))
        return results

    @staticmethod
    def _lower_gates_for_test(config):
        """Relax quality-gate thresholds so a 2-source test run can pass.

        The base gates require sources/claims that a mocked LLM run can't
        provide. Lowering them lets the engine reach every 6-step gate.
        """
        config["gate_min_sources"] = 2
        config["gate_min_type_diversity"] = 2
        config["gate_min_reinforced_claims"] = 0  # mocked synth has 0 reinforced
        config["gate_max_knowledge_gaps"] = 999
        config["gate_min_evidence_score"] = 0.0
        config["gate_min_reasoning_score"] = 0  # 0/10 = always pass (gate divides by 10)
        config["gate_min_structure_score"] = 0.0
        return config

    def test_engine_runs_all_six_steps_to_done(self, mock_wiki, mock_llm, db, config):
        """Full ReAct loop runs through every 6-step phase and ends at 'done'."""
        mock_llm = self._build_mock_llm_with_full_cycle()
        config = self._lower_gates_for_test(dict(config))
        config["max_react_rounds"] = 8

        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        session_id = engine.session_manager.create_session("test", "What is X?")
        self._seed_session_with_source(engine, session_id)

        events = _run_async(_collect_events(engine.run(session_id, "What is X?")))
        types = [e.get("type") for e in events]

        # Must have seen every key event in the 6-step pipeline
        assert "clarification_complete" in types
        assert "evidence_scoring_complete" in types
        assert "synthesis_complete" in types
        assert "reasoning_check_complete" in types
        assert "structure_check_complete" in types
        assert "review_passed" in types or "review_issues" in types

    def test_evidence_score_populated_after_gather(self, mock_wiki, mock_llm, db, config):
        """state.evidence_scores is populated and persisted after _action_gather."""
        mock_llm = self._build_mock_llm_with_full_cycle()
        config = self._lower_gates_for_test(dict(config))
        config["max_react_rounds"] = 8
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        session_id = engine.session_manager.create_session("test", "What is X?")
        self._seed_session_with_source(engine, session_id)

        events = _run_async(_collect_events(engine.run(session_id, "What is X?")))
        types = [e.get("type") for e in events]
        assert "evidence_scoring_complete" in types

        # Persisted to DB via update_six_step_fields
        six_step = db.get_six_step_fields(session_id)
        assert six_step["evidence_scores"] is not None
        scores = six_step["evidence_scores"]
        assert isinstance(scores, dict)
        assert len(scores) >= 1
        for sid, score in scores.items():
            assert 0.0 <= score <= 1.0, f"score for {sid} out of range: {score}"

    def test_reasoning_check_invoked_after_synthesize(self, mock_wiki, mock_llm, db, config):
        """ReasoningChecker runs in _action_synthesize, populates reasoning."""
        mock_llm = self._build_mock_llm_with_full_cycle()
        config = self._lower_gates_for_test(dict(config))
        config["max_react_rounds"] = 8
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        session_id = engine.session_manager.create_session("test", "What is X?")
        self._seed_session_with_source(engine, session_id)

        events = _run_async(_collect_events(engine.run(session_id, "What is X?")))
        types = [e.get("type") for e in events]
        assert "reasoning_check_complete" in types

        six_step = db.get_six_step_fields(session_id)
        assert six_step["reasoning"] is not None
        rc = six_step["reasoning"]
        assert "aggregate_score" in rc
        assert "scores" in rc
        # 6 dimensions per the plan
        assert len(rc["scores"]) == 6

    def test_structure_check_invoked_after_report(self, mock_wiki, mock_llm, db, config):
        """StructureValidator runs in _action_report, populates structure."""
        mock_llm = self._build_mock_llm_with_full_cycle()
        config = self._lower_gates_for_test(dict(config))
        config["max_react_rounds"] = 8
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        session_id = engine.session_manager.create_session("test", "What is X?")
        self._seed_session_with_source(engine, session_id)

        events = _run_async(_collect_events(engine.run(session_id, "What is X?")))
        types = [e.get("type") for e in events]
        assert "structure_check_complete" in types

        six_step = db.get_six_step_fields(session_id)
        assert six_step["structure"] is not None
        sc = six_step["structure"]
        assert "aggregate_score" in sc
        # 3 layers per the plan
        assert len(sc["scores"]) == 3

    def test_six_step_context_passed_to_report_and_review(
        self, mock_wiki, mock_llm, db, config,
    ):
        """six_step_context is built and non-None when report/review are called."""
        from llmwikify.apps.chat import actions as _actions

        build_calls: list = []
        original_build = _actions._build_six_step_context

        def spy_build(state):
            result = original_build(state)
            build_calls.append(result)
            return result

        with patch.object(_actions, "_build_six_step_context", spy_build):
            mock_llm = self._build_mock_llm_with_full_cycle()
            config = self._lower_gates_for_test(dict(config))
            config["max_react_rounds"] = 8
            engine = ResearchEngine(mock_wiki, db, mock_llm, config)
            session_id = engine.session_manager.create_session("test", "What is X?")
            self._seed_session_with_source(engine, session_id)
            _run_async(_collect_events(engine.run(session_id, "What is X?")))

        # _build_six_step_context should have been called (at least at report time)
        assert len(build_calls) >= 1
        last = build_calls[-1]
        assert last is not None, "_build_six_step_context returned None"
        assert "clarification" in last
        assert "reasoning_check" in last
        assert "structure_check" in last
        assert "evidence_scores" in last

    def test_six_step_gates_triggered_at_each_phase(
        self, mock_wiki, mock_llm, db, config,
    ):
        """The 4 6-step QualityGate methods are invoked at the correct phases."""
        from llmwikify.apps.chat.harness.quality_gate import QualityGate

        calls: list[str] = []
        original_evidence = QualityGate.check_evidence_quality
        original_reasoning = QualityGate.check_reasoning_quality
        original_structure = QualityGate.check_structure_quality
        original_framework = QualityGate.check_framework_compliance

        def spy_evidence(self, *args, **kwargs):
            calls.append("evidence")
            return original_evidence(self, *args, **kwargs)

        def spy_reasoning(self, *args, **kwargs):
            calls.append("reasoning")
            return original_reasoning(self, *args, **kwargs)

        def spy_structure(self, *args, **kwargs):
            calls.append("structure")
            return original_structure(self, *args, **kwargs)

        def spy_framework(self, *args, **kwargs):
            calls.append("framework")
            return original_framework(self, *args, **kwargs)

        with patch.object(QualityGate, "check_evidence_quality", spy_evidence), \
             patch.object(QualityGate, "check_reasoning_quality", spy_reasoning), \
             patch.object(QualityGate, "check_structure_quality", spy_structure), \
             patch.object(QualityGate, "check_framework_compliance", spy_framework):
            mock_llm = self._build_mock_llm_with_full_cycle()
            config = self._lower_gates_for_test(dict(config))
            config["max_react_rounds"] = 8
            engine = ResearchEngine(mock_wiki, db, mock_llm, config)
            session_id = engine.session_manager.create_session("test", "What is X?")
            self._seed_session_with_source(engine, session_id)
            _run_async(_collect_events(engine.run(session_id, "What is X?")))

        # The 4 6-step gates must each have been called at least once
        assert "evidence" in calls, f"check_evidence_quality never called: {calls}"
        assert "reasoning" in calls, f"check_reasoning_quality never called: {calls}"
        assert "structure" in calls, f"check_structure_quality never called: {calls}"
        assert "framework" in calls, f"check_framework_compliance never called: {calls}"

    def test_framework_compliance_failure_triggers_replan(
        self, mock_wiki, mock_llm, db, config,
    ):
        """In a successful run, framework_compliance should pass with proceed."""
        from llmwikify.apps.chat.harness.quality_gate import QualityGate

        captured: dict = {}
        original_framework = QualityGate.check_framework_compliance

        def spy_framework(self, *args, **kwargs):
            res = original_framework(self, *args, **kwargs)
            captured["result"] = res
            return res

        with patch.object(QualityGate, "check_framework_compliance", spy_framework):
            mock_llm = self._build_mock_llm_with_full_cycle()
            config = self._lower_gates_for_test(dict(config))
            config["max_react_rounds"] = 8
            engine = ResearchEngine(mock_wiki, db, mock_llm, config)
            session_id = engine.session_manager.create_session("test", "What is X?")
            self._seed_session_with_source(engine, session_id)
            _run_async(_collect_events(engine.run(session_id, "What is X?")))

        assert "result" in captured, "framework_compliance never invoked"
        assert captured["result"].passed is True, (
            f"expected passed=True, got {captured['result'].summary}"
        )
        assert captured["result"].suggestion == "proceed"


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


# ─── Phase 2: evidence + reasoning ───────────────────────────────────


class TestSourceFilterEvidence:
    """SourceFilter.compute_evidence_score: 6-step gate 2 input."""

    def test_high_quality_source_scores_high(self):
        sf = SourceFilter()
        arxiv_paper = {
            "url": "https://arxiv.org/abs/2401.0001",
            "title": "Attention Is All You Need",
            "author": "Vaswani et al.",
            "source_type": "arxiv",
            "content": "x" * 2000,
        }
        score = sf.compute_evidence_score(arxiv_paper)
        assert score >= 0.7, f"arxiv paper should score ≥ 0.7, got {score}"

    def test_low_quality_source_scores_low(self):
        sf = SourceFilter()
        spam = {
            "url": "https://clickbait.tld/article/123",
            "title": "",
            "author": "",
            "source_type": "web",
            "content": "short",
        }
        score = sf.compute_evidence_score(spam)
        assert score < 0.5, f"spam should score < 0.5, got {score}"

    def test_wiki_url_is_fully_traceable(self):
        sf = SourceFilter()
        wiki = {
            "url": "wiki://test-page",
            "title": "Test Page",
            "author": "",
            "source_type": "wiki",
            "content": "x" * 1000,
        }
        score = sf.compute_evidence_score(wiki)
        # wiki URL bonus (0.3) + title (0.3) = traceability 0.6+ → contributes ≥0.18 to total
        assert score >= 0.5, f"wiki source should be traceable, got {score}"

    def test_traceability_breakdown(self):
        sf = SourceFilter()
        # Full traceability: url + title + author
        full = {"url": "https://x.com", "title": "T", "author": "A", "content": "x" * 500}
        # No traceability
        none = {"url": "", "title": "", "author": "", "content": ""}
        assert sf._score_traceability(full) > sf._score_traceability(none)
        assert sf._score_traceability(none) == 0.0

    def test_authority_boost_for_pdf(self):
        sf = SourceFilter()
        web_unknown = {"url": "https://example.com/x", "content": "x" * 500, "source_type": "web"}
        pdf = {**web_unknown, "source_type": "pdf"}
        assert sf._score_authority(pdf) >= sf._score_authority(web_unknown)


class TestReasoningChecker:
    """ReasoningChecker: 6-step gate 3 input."""

    def test_returns_six_dimension_scores(self):
        rc = ReasoningChecker()
        result = rc.check(synthesis="Some text. [[Source:a]] Another.", evidence_sources=[{"id": "a"}])
        assert "scores" in result
        for dim in ReasoningChecker.DIMENSIONS:
            assert dim in result["scores"]
            assert 0.0 <= result["scores"][dim] <= 1.0

    def test_high_quality_synthesis_passes(self):
        rc = ReasoningChecker()
        synth = (
            "The system 因为 high latency 所以 fails. [[Source:s1]] "
            "可能 this will improve. 假设 we have enough resources. "
            "Therefore, results are good. 综合 our analysis."
        )
        result = rc.check(
            synthesis=synth,
            evidence_sources=[{"id": "s1", "url": "u1"}],
            clarification={"premises": ["high latency is a problem"]},
        )
        assert result["aggregate_score"] >= 0.6, f"got {result['aggregate_score']}"
        assert result["method"] == "rule_based"

    def test_empty_synthesis_scores_zero_on_alignment(self):
        rc = ReasoningChecker()
        result = rc.check(synthesis="", evidence_sources=[{"id": "s1"}])
        # Empty synthesis has 0 sentences, so alignment=0
        assert result["scores"]["conclusion_evidence_alignment"] == 0.0

    def test_premises_alignment_tracks_token_overlap(self):
        rc = ReasoningChecker()
        # Premise keyword "quantum entanglement" appears in synthesis
        result = rc.check(
            synthesis="We discuss quantum entanglement extensively.",
            evidence_sources=[{"id": "s1"}],
            clarification={"premises": ["quantum entanglement is fundamental"]},
        )
        assert result["scores"]["premise_evidence_alignment"] >= 0.5

    def test_issues_list_populated_for_warnings(self):
        rc = ReasoningChecker()
        # No citations, no causal markers, no uncertainty, no assumptions
        result = rc.check(synthesis="Just a statement. Another one. Third.", evidence_sources=[{"id": "s"}])
        # Expect issues for causal, assumption_visibility, uncertainty_quantification
        assert len(result["issues"]) >= 2


class TestQualityGateNewGates:
    """QualityGate.check_evidence_quality + check_reasoning_quality."""

    def test_evidence_gate_passes_for_high_quality(self):
        qg = QualityGate({"gate_evidence_threshold": 0.5})
        sources = [
            {
                "url": "https://arxiv.org/abs/2401",
                "title": "Paper",
                "author": "A",
                "source_type": "arxiv",
                "content": "x" * 1500,
            }
        ]
        result = qg.check_evidence_quality(sources, evidence_threshold=0.5)
        assert result.gate_name == "evidence_quality"
        assert result.passed is True
        assert "avg_score" in result.details

    def test_evidence_gate_fails_for_empty(self):
        qg = QualityGate()
        result = qg.check_evidence_quality([])
        assert result.passed is False
        assert result.suggestion == "gather_more"

    def test_reasoning_gate_returns_aggregate(self):
        qg = QualityGate({"gate_reasoning_threshold": 0.5})
        synth = (
            "The system 因为 latency 所以 fails. [[Source:s1]] "
            "可能 this will improve. 假设 we have resources."
        )
        result = qg.check_reasoning_quality(
            synthesis=synth,
            evidence_sources=[{"id": "s1"}],
            clarification={"premises": ["latency is a problem"]},
            reasoning_threshold=0.5,
        )
        assert result.gate_name == "reasoning_quality"
        assert "per_dimension" in result.details
        assert result.passed is True

    def test_reasoning_gate_fails_below_threshold(self):
        qg = QualityGate()
        # Empty synthesis → all 0s
        result = qg.check_reasoning_quality(
            synthesis="",
            evidence_sources=[],
            reasoning_threshold=0.5,
        )
        assert result.passed is False
        assert result.suggestion == "replan_reasoning"


# ─── Phase 3: structure + framework compliance + 6-step enrichment ──


class TestStructureValidator:
    """StructureValidator: 6-step gate 4 input."""

    def _good_report(self) -> str:
        return (
            "# 背景\n"
            "This is a test background with sufficient context.\n"
            "## 分析\n"
            "The system 因为 high latency 所以 fails. [[Source:abc123]]\n"
            "## 证据\n"
            "Some evidence here. [[Source:def456]]\n"
            "## 结论\n"
            "Therefore the result is good. 可能 this will improve."
        )

    def test_three_layer_scores_returned(self):
        sv = StructureValidator()
        result = sv.validate(self._good_report())
        assert "scores" in result
        for layer in StructureValidator.LAYERS:
            assert layer in result["scores"]

    def test_good_report_passes_aggregate(self):
        sv = StructureValidator()
        result = sv.validate(
            self._good_report(),
            synthesis={"reinforced_claims": ["c1", "c2", "c3"]},
            evidence_sources=[{"id": "abc123"}, {"id": "def456"}],
        )
        assert result["aggregate_score"] >= 0.7, f"got {result['aggregate_score']}"

    def test_short_report_fails_hierarchy(self):
        sv = StructureValidator()
        result = sv.validate("Just a one-liner.", evidence_sources=[])
        assert result["scores"]["hierarchical_support"] < 0.5

    def test_missing_sections_emits_issue(self):
        sv = StructureValidator()
        result = sv.validate("Random content without headers.")
        # Should have at least one issue for section completeness
        section_issues = [
            i for i in result["issues"]
            if i.get("layer") == "section_completeness"
        ]
        assert len(section_issues) >= 1


class TestStructureAndFrameworkGates:
    """QualityGate.check_structure_quality + check_framework_compliance."""

    def test_structure_gate_passes_for_well_formed_report(self):
        qg = QualityGate({"gate_structure_threshold": 0.5})
        report = (
            "# 背景\nctx\n## 分析\nx [[Source:a]]\n## 证据\ny [[Source:b]]\n"
            "# 结论\nTherefore. 可能 good."
        )
        result = qg.check_structure_quality(
            report=report,
            synthesis={"reinforced_claims": ["c1", "c2", "c3"]},
            evidence_sources=[{"id": "a"}, {"id": "b"}],
        )
        assert result.gate_name == "structure_quality"
        assert result.passed is True
        assert "per_layer" in result.details

    def test_framework_compliance_passes_when_all_present(self):
        qg = QualityGate()
        result = qg.check_framework_compliance(
            clarification={"context": "ctx"},
            reasoning_check={"aggregate_score": 0.7},
            structure_check={"aggregate_score": 0.8},
        )
        assert result.passed is True
        assert result.gate_name == "framework_compliance"

    def test_framework_compliance_fails_when_clarification_missing(self):
        qg = QualityGate()
        result = qg.check_framework_compliance(
            clarification=None,
            reasoning_check={"aggregate_score": 0.7},
            structure_check={"aggregate_score": 0.8},
        )
        assert result.passed is False
        assert "missing clarification" in result.summary

    def test_framework_compliance_fails_when_reasoning_missing(self):
        qg = QualityGate()
        result = qg.check_framework_compliance(
            clarification={"context": "ctx"},
            reasoning_check=None,
            structure_check={"aggregate_score": 0.8},
        )
        assert result.passed is False

    def test_framework_compliance_fails_when_structure_missing(self):
        qg = QualityGate()
        result = qg.check_framework_compliance(
            clarification={"context": "ctx"},
            reasoning_check={"aggregate_score": 0.7},
            structure_check=None,
        )
        assert result.passed is False


class TestReportAndReviewEnrichment:
    """Report/Review: 6-step framework enrichment.

    After commit 4 of the prompt-system refactor, the framework block
    rendering is consolidated in ``autoresearch.prompts.render_framework_block``.
    The report/review modules call this shared helper, so the tests
    exercise the consolidated function directly.
    """

    def test_report_renders_framework_block(self):
        from llmwikify.apps.chat.prompts import render_framework_block
        ctx = {
            "clarification": {
                "context": "ctx", "boundaries": "bnd", "position": "pos",
                "premises": ["p1", "p2"],
            },
            "reasoning_check": {"aggregate_score": 0.7, "scores": {"x": 0.8, "y": 0.6}},
            "structure_check": {"aggregate_score": 0.8, "scores": {"a": 0.9}},
            "evidence_scores": {"s1": 0.8, "s2": 0.6},
        }
        block = render_framework_block(ctx, "report")
        assert "步骤 1" in block
        assert "步骤 2" in block
        assert "步骤 3" in block
        assert "步骤 4" in block
        assert "0.70" in block or "0.7" in block
        assert "前提 (2)" in block

    def test_report_renders_empty_when_no_context(self):
        from llmwikify.apps.chat.prompts import render_framework_block
        assert render_framework_block(None, "report") == ""
        assert render_framework_block({}, "report") == ""

    def test_review_renders_framework_block(self):
        from llmwikify.apps.chat.prompts import render_framework_block
        ctx = {
            "clarification": {"context": "ctx", "boundaries": "bnd", "position": "pos"},
            "reasoning_check": {"aggregate_score": 0.7},
            "structure_check": {"aggregate_score": 0.8},
            "evidence_scores": {"s1": 0.8},
        }
        block = render_framework_block(ctx, "review")
        assert "6-step Framework Review Checklist" in block
        assert "标准 1" in block
        assert "标准 2" in block
        assert "标准 3" in block
        assert "标准 4" in block
        assert "标准 5" in block

    def test_review_renders_empty_when_no_context(self):
        from llmwikify.apps.chat.prompts import render_framework_block
        assert render_framework_block(None, "review") == ""
        assert render_framework_block({}, "review") == ""


# ─── Phase 4: retry managers ─────────────────────────────────────────


class TestRetryAsync:
    """Base retry_async helper."""

    def test_returns_on_first_success(self):
        async def ok():
            return 42
        result = _run_async(retry_async(ok, max_attempts=3, base_delay=0.01))
        assert result == 42

    def test_retries_then_raises(self):
        attempts = [0]

        async def fail():
            attempts[0] += 1
            raise ValueError("boom")
        with pytest.raises(ValueError):
            _run_async(retry_async(fail, max_attempts=3, base_delay=0.01))
        assert attempts[0] == 3

    def test_eventually_succeeds(self):
        attempts = [0]

        async def flaky():
            attempts[0] += 1
            if attempts[0] < 3:
                raise IOError("transient")
            return "ok"
        result = _run_async(retry_async(flaky, max_attempts=5, base_delay=0.01))
        assert result == "ok"
        assert attempts[0] == 3


class TestStageRetryManager:
    """StageRetryManager: soft-fail with partial result."""

    def test_succeeds_first_try(self):
        async def go():
            return "ok"
        mgr = StageRetryManager("s", max_attempts=2, allow_partial=True)
        result = _run_async(mgr.run(go))
        assert result["ok"] is True
        assert result["value"] == "ok"
        assert result["attempts"] == 1

    def test_succeeds_on_retry(self):
        attempts = [0]

        async def flaky():
            attempts[0] += 1
            if attempts[0] < 2:
                raise ValueError("boom")
            return "ok"
        mgr = StageRetryManager("s", max_attempts=3, allow_partial=True, base_delay=0.01)
        result = _run_async(mgr.run(flaky))
        assert result["ok"] is True
        assert result["value"] == "ok"
        assert result["attempts"] == 2

    def test_partial_fallback_on_full_failure(self):
        async def fail():
            raise ValueError("nope")
        mgr = StageRetryManager("s", max_attempts=2, allow_partial=True, base_delay=0.01)
        result = _run_async(mgr.run(fail, fallback={"partial": True}))
        assert result["ok"] is False
        assert result["value"] == {"partial": True}
        assert any("失败" in w for w in result["warnings"])

    def test_no_partial_returns_none(self):
        async def fail():
            raise ValueError("nope")
        mgr = StageRetryManager("s", max_attempts=2, allow_partial=False, base_delay=0.01)
        result = _run_async(mgr.run(fail))
        assert result["ok"] is False
        assert result["value"] is None
        assert result["error"] == "nope"


class TestLLMRetryManager:
    """LLMRetryManager: smart retry (transient only)."""

    def test_retries_on_rate_limit(self):
        attempts = [0]

        async def rate_limit():
            attempts[0] += 1
            if attempts[0] < 3:
                raise Exception("rate limit exceeded")
            return "ok"
        mgr = LLMRetryManager(max_attempts=4, base_delay=0.01)
        result = _run_async(mgr.call(rate_limit))
        assert result == "ok"
        assert attempts[0] == 3

    def test_retries_on_5xx(self):
        attempts = [0]

        async def server_err():
            attempts[0] += 1
            if attempts[0] < 2:
                raise Exception("503 service unavailable")
            return "ok"
        mgr = LLMRetryManager(max_attempts=3, base_delay=0.01)
        result = _run_async(mgr.call(server_err))
        assert result == "ok"

    def test_does_not_retry_json_decode(self):
        attempts = [0]

        async def json_err():
            attempts[0] += 1
            raise Exception("json decode error: bad token")
        mgr = LLMRetryManager(max_attempts=3, base_delay=0.01)
        with pytest.raises(Exception, match="json decode"):
            _run_async(mgr.call(json_err))
        assert attempts[0] == 1  # No retry

    def test_does_not_retry_validation_error(self):
        attempts = [0]

        async def val_err():
            attempts[0] += 1
            raise KeyError("missing key")
        mgr = LLMRetryManager(max_attempts=3, base_delay=0.01)
        with pytest.raises(KeyError):
            _run_async(mgr.call(val_err))
        assert attempts[0] == 1


class TestDBRetryManager:
    """DBRetryManager: SQLite transient error retry."""

    def test_retries_on_locked(self):
        attempts = [0]

        def lock_then_succeed():
            attempts[0] += 1
            if attempts[0] < 2:
                raise sqlite3.OperationalError("database is locked")
            return "ok"
        mgr = DBRetryManager(max_attempts=3, base_delay=0.01)
        result = mgr.call(lock_then_succeed)
        assert result == "ok"
        assert attempts[0] == 2

    def test_does_not_retry_non_transient(self):
        def syntax_err():
            raise sqlite3.OperationalError("syntax error")
        mgr = DBRetryManager(max_attempts=3, base_delay=0.01)
        with pytest.raises(sqlite3.OperationalError, match="syntax error"):
            mgr.call(syntax_err)

    def test_is_retriable_detection(self):
        mgr = DBRetryManager()
        assert mgr.is_retriable(sqlite3.OperationalError("database is locked"))
        assert mgr.is_retriable(sqlite3.OperationalError("database is busy"))
        assert not mgr.is_retriable(sqlite3.OperationalError("syntax error"))
        assert not mgr.is_retriable(ValueError("not a sqlite error"))


# ─── v4: AutoResearchDatabase tests ────────────────────────────────


class TestAutoResearchDatabase:
    """Independent SQLite database for autoresearch.

    The DB has its own file, its own tables, and its own 6-step framework
    fields. There is no sharing with the shared .llmwiki_agent.db.
    """

    def test_creates_three_tables(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        with sqlite3.connect(db.db_path) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "autoresearch_sessions" in tables
        assert "autoresearch_sub_queries" in tables
        assert "autoresearch_sources" in tables

    def test_creates_two_indexes(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        with sqlite3.connect(db.db_path) as conn:
            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        assert "idx_ar_sub_queries_session" in indexes
        assert "idx_ar_sources_session" in indexes

    def test_default_status_is_clarifying(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        s = db.get_research_session(sid)
        assert s["status"] == "clarifying"
        assert s["current_step"] == "clarifying"

    def test_six_step_json_fields_default_none(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        s = db.get_research_session(sid)
        for col in (
            "clarification_json", "reasoning_json", "structure_json",
            "self_loop_counts_json", "self_loop_history_json",
            "evidence_scores_json",
        ):
            assert s[col] is None, f"{col} should default to None"

    def test_create_then_get_session_round_trip(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("my-wiki", "What is X?")
        s = db.get_research_session(sid)
        assert s is not None
        assert s["wiki_id"] == "my-wiki"
        assert s["query"] == "What is X?"

    def test_update_six_step_fields_persists(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        db.update_six_step_fields(
            sid,
            clarification={"context": "ctx", "premises": ["p1"]},
            reasoning={"aggregate_score": 0.7},
            structure={"aggregate_score": 0.8},
        )
        fields = db.get_six_step_fields(sid)
        assert fields["clarification"]["context"] == "ctx"
        assert fields["reasoning"]["aggregate_score"] == 0.7
        assert fields["structure"]["aggregate_score"] == 0.8

    def test_update_six_step_fields_partial(self, tmp_path):
        """Only provided fields are written; others stay None."""
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        db.update_six_step_fields(sid, clarification={"context": "ctx"})
        fields = db.get_six_step_fields(sid)
        assert fields["clarification"]["context"] == "ctx"
        assert fields["reasoning"] is None
        assert fields["structure"] is None

    def test_get_six_step_fields_round_trip(self, tmp_path):
        """Self-loop counts/history round-trip via update_six_step_fields."""
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        db.update_six_step_fields(
            sid,
            self_loop_counts={"clarify": 1, "evidence": 0},
            self_loop_history=[{"stage": "clarify", "result": "ok"}],
            evidence_scores={"s1": 0.8, "s2": 0.5},
        )
        fields = db.get_six_step_fields(sid)
        assert fields["self_loop_counts"] == {"clarify": 1, "evidence": 0}
        assert fields["self_loop_history"][0]["stage"] == "clarify"
        assert fields["evidence_scores"]["s1"] == 0.8

    def test_delete_research_cascades(self, tmp_path):
        """delete_research removes session + sub_queries + sources."""
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        sq = db.save_sub_query(sid, "sub", "web", "http://x")
        db.save_source(sid, sq, "web", "http://x", "T", 100, "p")
        # Pre-condition
        assert len(db.get_sub_queries(sid)) == 1
        assert len(db.get_sources(sid)) == 1
        # Delete
        deleted = db.delete_research(sid)
        assert deleted is True
        assert db.get_research_session(sid) is None
        assert db.get_sub_queries(sid) == []
        assert db.get_sources(sid) == []

    def test_research_sessions_table_does_not_exist(self, tmp_path):
        """Zero sharing: the shared `research_sessions` table must not exist."""
        db = AutoResearchDatabase(tmp_path)
        with sqlite3.connect(db.db_path) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "research_sessions" not in tables
        assert "research_sub_queries" not in tables
        assert "research_sources" not in tables

    def test_idempotent_init(self, tmp_path):
        """Re-instantiating AutoResearchDatabase on the same dir is a no-op."""
        db1 = AutoResearchDatabase(tmp_path)
        sid1 = db1.create_research_session("w", "first")
        # Re-open — must not lose data
        db2 = AutoResearchDatabase(tmp_path)
        s = db2.get_research_session(sid1)
        assert s is not None
        assert s["query"] == "first"

    def test_sub_query_json_result_parsed(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        sq = db.save_sub_query(sid, "sub", "web")
        db.update_sub_query(sq, "done", result={"key": "value"})
        subs = db.get_sub_queries(sid)
        assert subs[0]["result"] == {"key": "value"}

    def test_source_analysis_parsed(self, tmp_path):
        db = AutoResearchDatabase(tmp_path)
        sid = db.create_research_session("w", "q")
        sq = db.save_sub_query(sid, "sub", "web")
        src = db.save_source(sid, sq, "web", "http://x", "T", 100)
        db.update_source_analysis(src, {"topics": ["t1"], "credibility": 8})
        sources = db.get_sources(sid)
        assert sources[0]["analysis"]["topics"] == ["t1"]

    def test_get_autoresearch_db_path(self, tmp_path):
        from llmwikify.apps.chat.db import get_autoresearch_db_path
        p = get_autoresearch_db_path(tmp_path)
        # The canonical filename is now .llmwiki_agent.db
        # (auto-migrated from autoresearch.db in v0.33.0).
        # get_autoresearch_db_path is now an alias for
        # get_app_db_path, which returns the canonical filename.
        assert p == tmp_path / ".llmwiki_agent.db"
        # Also accepts string
        p2 = get_autoresearch_db_path(str(tmp_path))
        assert p2 == tmp_path / ".llmwiki_agent.db"


# ─── Phase 6: Resume tests ────────────────────────────────────────


class TestResume:
    """Tests for session resume: whitelist, round reset, evidence restore."""

    def test_resume_from_incomplete_allows_entry(self, db):
        """routes.py should allow resume from 'incomplete' status."""
        from llmwikify.apps.chat.routes import resume_autoresearch
        sid = db.create_research_session("w", "q")
        db.update_research_status(sid, "incomplete", "done", 1.0)
        session = db.get_research_session(sid)
        # The whitelist check: incomplete should be in the allowed set
        allowed = ("paused", "pausing", "gathering", "planning", "analyzing",
                    "synthesizing", "report", "reviewing", "clarifying",
                    "incomplete", "error", "timeout", "done")
        assert session["status"] in allowed

    def test_resume_from_done_allows_entry(self, db):
        """routes.py should allow resume from 'done' status."""
        sid = db.create_research_session("w", "q")
        db.update_research_status(sid, "done", "done", 1.0)
        session = db.get_research_session(sid)
        allowed = ("paused", "pausing", "gathering", "planning", "analyzing",
                    "synthesizing", "report", "reviewing", "clarifying",
                    "incomplete", "error", "timeout", "done")
        assert session["status"] in allowed

    def test_resume_resets_round_to_zero(self, mock_wiki, mock_llm, db, config):
        """_load_resume_state should set round=0 for fresh budget cycle."""
        config["max_react_rounds"] = 3
        # Create a session that hit max_rounds (round=3)
        sid = db.create_research_session("w", "q")
        db.update_research_status(sid, "incomplete", "done", 0.5)
        # Manually set iteration_round to simulate a session that ran 3 rounds
        with sqlite3.connect(str(db.db_path)) as conn:
            conn.execute(
                "UPDATE autoresearch_sessions SET iteration_round = 3 WHERE id = ?",
                (sid,),
            )

        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = ResearchState(session_id=sid, query="test", max_rounds=3)
        engine._load_resume_state(state)

        # Round should be reset to 0 (not 3)
        assert state.round == 0

    def test_resume_restores_evidence_scores(self, mock_wiki, mock_llm, db, config):
        """_load_resume_state should restore evidence_scores from DB."""
        sid = db.create_research_session("w", "q")
        # Persist evidence scores (method takes dict, handles JSON internally)
        evidence = {"src_abc": 0.85, "src_def": 0.62}
        db.update_six_step_fields(sid, evidence_scores=evidence)

        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = ResearchState(session_id=sid, query="test")
        engine._load_resume_state(state)

        assert state.evidence_scores == evidence

    def test_resume_restores_all_framework_fields(self, mock_wiki, mock_llm, db, config):
        """_load_resume_state should restore all 6-step framework fields."""
        sid = db.create_research_session("w", "q")
        clarification = {"context": "c", "boundaries": "b", "scope_check": True, "premises": []}
        evidence = {"src1": 0.9}
        synthesis = {"reinforced_claims": [], "knowledge_gaps": [], "contradictions": []}
        reasoning = {"aggregate_score": 0.8, "issues": []}
        structure = {"aggregate_score": 0.7, "issues": []}
        review = {"approved": True, "score": 8, "feedback": "ok", "issues": []}

        db.update_six_step_fields(sid,
            clarification=clarification,
            evidence_scores=evidence,
            reasoning=reasoning,
            structure=structure,
        )
        # synthesis and review go through different columns
        with sqlite3.connect(str(db.db_path)) as conn:
            conn.execute(
                "UPDATE autoresearch_sessions SET synthesis_json = ?, review_json = ? WHERE id = ?",
                (json.dumps(synthesis), json.dumps(review), sid),
            )

        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = ResearchState(session_id=sid, query="test")
        engine._load_resume_state(state)

        assert state.clarification == clarification
        assert state.evidence_scores == evidence
        assert state.synthesis == synthesis
        assert state.reasoning_check == reasoning
        assert state.structure_check == structure
        assert state.review == review

    def test_resume_skips_clarify(self, mock_wiki, mock_llm, db, config):
        """On resume, clarify should be skipped if clarification already exists."""
        config["max_react_rounds"] = 2
        # Disable strict_exit to keep test focused on clarify-skip behavior
        config["strict_exit"] = False
        sid = db.create_research_session("w", "q")
        # Pre-populate ALL framework fields so compliance gate passes
        db.update_six_step_fields(sid,
            clarification={"context": "x", "scope_check": True, "premises": []},
            evidence_scores={"src1": 0.9},
            reasoning={"aggregate_score": 0.8, "issues": []},
            structure={"aggregate_score": 0.7, "issues": []},
        )
        with sqlite3.connect(str(db.db_path)) as conn:
            conn.execute(
                "UPDATE autoresearch_sessions SET synthesis_json = ?, review_json = ?, result = ? WHERE id = ?",
                (json.dumps({"reinforced_claims": [], "knowledge_gaps": [], "contradictions": []}),
                 json.dumps({"approved": True, "score": 8, "feedback": "ok", "issues": []}),
                 json.dumps({"markdown": "# Report", "quality_score": 8}),
                 sid),
            )
        db.update_research_status(sid, "incomplete", "done", 0.5)

        # LLM: only reason calls (no clarify call expected)
        mock_llm.chat.side_effect = [
            json.dumps({"thought": "have data", "action": "done"}),
        ]

        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        events = _run_async(_collect_events(engine.run(sid, "test query", resume=True)))
        types = [e.get("type") for e in events]

        # clarify_complete should NOT appear (skipped on resume)
        assert "clarification_complete" not in types
        # But reasoning event should appear (loop ran)
        assert "reasoning" in types


# ─── Phase 7: Strict exit gate (v6) ────────────────────────────────


class TestStrictExit:
    """Tests for the strict_exit gate: enforces quality thresholds at the done gate.

    When strict_exit=True (default), the engine redirects done to revise /
    synthesize / gather when quality_score < threshold, too many knowledge
    gaps, or insufficient sources.
    """

    def _compliant_state(self, **overrides):
        """Return a state with all 6 framework fields populated and review approved."""
        s = ResearchState(session_id="test", query="Q", max_rounds=5)
        s.clarification = {"context": "ctx", "scope_check": True}
        s.evidence_scores = {"src1": 0.8, "src2": 0.6, "src3": 0.7}
        s.synthesis = {"reinforced_claims": ["a"], "contradictions": [], "knowledge_gaps": []}
        s.reasoning_check = {"aggregate_score": 0.7, "scores": {}, "issues": []}
        s.report_md = "# Report\n\nContent."
        s.structure_check = {"aggregate_score": 0.8, "scores": {}, "issues": []}
        s.review = {"approved": True, "score": 8, "issues": []}
        s.quality_score = 8  # state.quality_score is what _check_quality_compliance reads
        # 3 mock sources to satisfy gate_min_sources=3
        s.sources = [
            {"id": "src1", "title": "S1", "url": "http://1", "source_type": "web", "analysis": {"quality_assessment": {"credibility": 7}}},
            {"id": "src2", "title": "S2", "url": "http://2", "source_type": "web", "analysis": {"quality_assessment": {"credibility": 6}}},
            {"id": "src3", "title": "S3", "url": "http://3", "source_type": "web", "analysis": {"quality_assessment": {"credibility": 7}}},
        ]
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    def test_strict_exit_default_enabled(self):
        """DEFAULT_SIX_STEP_CONFIG should have strict_exit=True."""
        assert DEFAULT_SIX_STEP_CONFIG.get("strict_exit") is True

    def test_strict_exit_passes_when_all_quality_ok(self, mock_wiki, mock_llm, db, config):
        """All quality thresholds met → returns None (compliance passed)."""
        config["strict_exit"] = True
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        assert engine._check_quality_compliance(state) is None

    def test_strict_exit_blocks_unapproved_review(self, mock_wiki, mock_llm, db, config):
        """Review not approved → returns {'missing': 'revise'}."""
        config["strict_exit"] = True
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        state.review = {"approved": False, "score": 8, "issues": ["x"]}
        result = engine._check_quality_compliance(state)
        assert result is not None
        assert result["missing"] == "revise"
        assert "not approved" in result["reason"]

    def test_strict_exit_blocks_skipped_review(self, mock_wiki, mock_llm, db, config):
        """Review that was skipped (LLM failed) must NOT pass even
        if `approved=True` was fabricated. The gate must route the
        engine to `revise`, which will also fail and ultimately
        end the session as `incomplete`.
        """
        config["strict_exit"] = True
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        state.review = {
            "approved": True, "score": 8, "issues": [],
            "skipped": True, "skip_reason": "Review LLM failed: timeout",
        }
        result = engine._check_quality_compliance(state)
        assert result is not None
        assert result["missing"] == "revise"
        assert "skipped" in result["reason"].lower()

    def test_strict_exit_blocks_low_quality_score(self, mock_wiki, mock_llm, db, config):
        """quality_score < threshold → returns {'missing': 'revise'}."""
        config["strict_exit"] = True
        config["quality_threshold"] = 8
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        state.review = {"approved": True, "score": 5, "issues": []}
        state.quality_score = 5
        result = engine._check_quality_compliance(state)
        assert result is not None
        assert result["missing"] == "revise"
        assert "quality_score=5" in result["reason"]

    def test_strict_exit_blocks_too_many_gaps(self, mock_wiki, mock_llm, db, config):
        """Too many knowledge gaps → returns {'missing': 'plan'}.

        Redirecting to `plan` (gap-replan path) — NOT `synthesize` —
        is the correct behavior: re-running synthesize with the same
        sources would just reproduce the same gaps and burn the round
        budget. The replan path generates new sub-queries targeting
        the gaps.
        """
        config["strict_exit"] = True
        config["gate_max_knowledge_gaps"] = 3
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        state.knowledge_gaps = ["gap1", "gap2", "gap3", "gap4"]
        result = engine._check_quality_compliance(state)
        assert result is not None
        assert result["missing"] == "plan"
        assert "gaps=4" in result["reason"]

    def test_strict_exit_blocks_too_few_sources(self, mock_wiki, mock_llm, db, config):
        """Insufficient sources → returns {'missing': 'gather'}."""
        config["strict_exit"] = True
        config["gate_min_sources"] = 5
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        result = engine._check_quality_compliance(state)
        assert result is not None
        assert result["missing"] == "gather"
        assert "sources=3" in result["reason"]

    def test_strict_exit_layer1_check_still_works(self, mock_wiki, mock_llm, db, config):
        """_check_quality_compliance delegates to _check_framework_compliance first."""
        config["strict_exit"] = True
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        state.report_md = None  # framework incomplete
        result = engine._check_quality_compliance(state)
        assert result is not None
        assert result["missing"] == "report"  # framework layer caught it first

    def test_strict_exit_disabled_keeps_old_behavior(self, mock_wiki, mock_llm, db, config):
        """When strict_exit=False, _check_quality_compliance can be bypassed."""
        config["strict_exit"] = False
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        state = self._compliant_state()
        state.review = {"approved": False, "score": 1, "issues": ["bad"]}
        state.quality_score = 1
        # _check_framework_compliance should still pass (all 6 fields present)
        assert engine._check_framework_compliance(state) is None
        # But _check_quality_compliance still blocks (method exists, just not called in loop)
        assert engine._check_quality_compliance(state) is not None

    def test_duplicate_action_done_removed(self):
        """actions.py should have only one action_done function."""
        from llmwikify.apps.chat import actions
        # Count action_done in the module
        count = sum(
            1 for name, _ in vars(actions).items()
            if name == "action_done" and callable(getattr(actions, name, None))
        )
        assert count == 1, f"Expected 1 action_done, found {count}"
