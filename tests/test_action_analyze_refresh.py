"""Tests for action_analyze state-refresh fix.

Regression target:
    After analyze_sources() writes analysis JSON to the DB, the
    in-memory ``state.sources`` list was NOT refreshed. This caused
    the LLM-based reasoner's ``analyzed_count`` (computed from
    ``state.sources``) to stay at 0, and the engine kept returning
    "analyze" forever (analyze → analyze loop). The observer's
    Issue#8 source-count-skip optimization masked the staleness
    because analysis updates don't change source count.

This test verifies:
  - action_analyze refreshes state.sources from DB after analysis
  - state._cached_source_count is updated to invalidate observer cache
  - Subsequent reasoner calls see the analyzed state and don't loop
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.state import ResearchState


@pytest.fixture
def tmp_db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def db_with_sources(tmp_db_path):
    """Build a real AutoResearchDatabase with 3 sources: 1 analyzed, 2 not."""
    from llmwikify.apps.chat.db import AutoResearchDatabase

    db = AutoResearchDatabase(tmp_db_path)

    # Create session
    sid = db.create_research_session("wiki-1", "test query")

    # Insert 3 sources via the DB API
    sub_qid = db.save_sub_query(
        session_id=sid,
        query="test sub query",
        source_type="web",
        url="",
    )
    for i in range(3):
        src_id = db.save_source(
            session_id=sid,
            sub_query_id=sub_qid,
            source_type="web",
            url=f"https://example.com/{i}",
            title=f"Source {i}",
            content_length=100,
            content_preview=f"Content for source {i}",
        )
        # Mark only source 0 as analyzed
        if i == 0:
            db.update_source_analysis(src_id, {"status": "ok", "score": 8})

    yield db, sid


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
    llm.chat.return_value = json.dumps({
        "context": "test context",
        "boundaries": "test boundaries",
        "position": "researcher view",
        "premises": ["premise 1", "premise 2"],
        "scope_check": True,
    })
    return llm


@pytest.fixture
def engine_with_db(db_with_sources, mock_wiki, mock_llm):
    """Build a ResearchEngine wired to the test DB."""
    from llmwikify.apps.research.engine import ResearchEngine

    db, sid = db_with_sources
    engine = ResearchEngine(mock_wiki, db, mock_llm, {})
    # action_analyze uses _step_event which needs ctx.session_manager
    # and update_status; both come from engine._action_ctx already.
    # Some helpers (like metrics) are set in engine.run(), so provide
    # a stub to avoid AttributeError when called directly.
    if engine._action_ctx.metrics is None:
        engine._action_ctx.metrics = MagicMock()
    # Make analyzer._analyze_one return success so all 3 sources are
    # analyzed in the test (otherwise it fails because mock_wiki.analyze_source
    # returns a MagicMock that doesn't match {"status": ...}).
    def fake_analyze_one(src):
        return {
            "status": "ok",
            "quality_assessment": {"credibility": 7},
            "topics": ["test"],
            "entities": ["test"],
        }
    engine._action_ctx.analyzer._analyze_one = fake_analyze_one
    return engine, sid


class TestActionAnalyzeRefreshesState:
    """action_analyze must refresh state.sources after analysis so the
    next reasoner iteration sees the updated analysis status.
    """

    @pytest.mark.asyncio
    async def test_refreshes_state_sources_after_analysis(
        self, engine_with_db, db_with_sources,
    ) -> None:
        """After action_analyze, state.sources should reflect the
        DB state (with analysis populated for all sources).
        """
        from llmwikify.apps.research.actions import action_analyze

        engine, sid = engine_with_db

        state = ResearchState(session_id=sid)
        # Set initial stale state.sources (simulate observer's stale state)
        state.sources = [{"id": "stale-id", "sub_query_id": "sq-1", "analysis": None}]
        state._cached_source_count = 1  # stale count

        ctx = engine._action_ctx

        # Collect events yielded by action_analyze
        events = []
        async for ev in action_analyze(ctx, state):
            events.append(ev)

        # After analyze, state.sources must be refreshed from DB
        assert len(state.sources) == 3, (
            f"state.sources should have 3 entries (refreshed from DB), "
            f"got {len(state.sources)}: {state.sources!r}"
        )

        # All sources should now show analysis populated
        analyzed = [s for s in state.sources if s.get("analysis")]
        assert len(analyzed) == 3, (
            f"All 3 sources should have analysis after action_analyze, "
            f"got {len(analyzed)} analyzed"
        )

    @pytest.mark.asyncio
    async def test_updates_cached_source_count(
        self, engine_with_db, db_with_sources,
    ) -> None:
        """state._cached_source_count must be updated so the observer's
        Issue#8 skip optimization doesn't skip the next refresh.
        """
        from llmwikify.apps.research.actions import action_analyze

        engine, sid = engine_with_db
        state = ResearchState(session_id=sid)
        state.sources = []
        state._cached_source_count = 0

        ctx = engine._action_ctx

        async for _ev in action_analyze(ctx, state):
            pass

        assert state._cached_source_count == 3, (
            f"state._cached_source_count should be updated to 3, "
            f"got {state._cached_source_count}"
        )

    @pytest.mark.asyncio
    async def test_analyzed_count_visible_to_subsequent_reasoner(
        self, engine_with_db, db_with_sources,
    ) -> None:
        """After action_analyze, computing analyzed_count from
        state.sources (as _llm_reason does) should show all sources
        as analyzed, so the reasoner doesn't loop on 'analyze'.
        """
        from llmwikify.apps.research.actions import action_analyze

        engine, sid = engine_with_db
        state = ResearchState(session_id=sid)
        # Start with stale state (analysis missing)
        state.sources = []
        state._cached_source_count = 0

        ctx = engine._action_ctx

        async for _ev in action_analyze(ctx, state):
            pass

        # Simulate what _llm_reason computes
        analyzed_count = sum(1 for s in state.sources if s.get("analysis"))
        sources_count = len(state.sources)
        assert analyzed_count == sources_count, (
            f"After action_analyze, analyzed_count ({analyzed_count}) "
            f"should equal sources_count ({sources_count}); otherwise "
            f"reasoner keeps returning 'analyze'"
        )

    @pytest.mark.asyncio
    async def test_no_analyze_no_loop_when_all_already_analyzed(
        self, engine_with_db, db_with_sources,
    ) -> None:
        """If all sources are already analyzed, action_analyze should
        not loop or yield source_analyzed events; just the step + progress.
        """
        from llmwikify.apps.research.actions import action_analyze

        engine, sid = engine_with_db

        # Manually mark all 3 sources as analyzed before running
        db, _ = db_with_sources
        sources = db.get_sources(sid)
        for s in sources:
            db.update_source_analysis(s["id"], {"status": "ok", "score": 8})

        state = ResearchState(session_id=sid)
        ctx = engine._action_ctx

        events = []
        async for ev in action_analyze(ctx, state):
            events.append(ev)

        # No source_analyzed events should fire
        analyzed_events = [e for e in events if e.get("type") == "source_analyzed"]
        assert not analyzed_events, (
            f"No new analysis should occur when all are already analyzed; "
            f"got: {analyzed_events}"
        )

        # But state.sources must still be refreshed
        assert len(state.sources) == 3
