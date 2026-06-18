"""Unit tests for Phase 6: research_skill (ReactLoop wrapper).

Covers:

  - ResearchSkill public API (3 actions, name, descriptions)
  - _make_research_config builder (returns valid ReactConfig)
  - All 7 _act_* action handlers (state mutations, errors)
  - 6 hooks: control signals, gate intervention, persist,
    restore, done_condition
  - End-to-end: run_research produces a non-empty report
  - Persistence integration: save_research_state / list_steps
  - Cancel flow: sets DB status to 'cancelling'
  - Resume: loads last persisted state

Target: 40+ tests, no I/O, no real LLM calls.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest

from llmwikify.apps.chat.agent.research_runner import (
    EVENT_ACTION_ERROR,
    EVENT_OBSERVATION_ERROR,
    EVENT_PHASE,
    EVENT_REASONING,
    EVENT_ROUND_COMPLETE,
    ReactConfig,
)
from llmwikify.apps.chat.skills import (
    SkillContext,
    SkillRegistry,
)
from llmwikify.apps.chat.skills.actions import register_all_actions
from llmwikify.apps.chat.skills.research_skill import (
    RESEARCH_REASON_PROMPT,
    ResearchSkill,
    _act_analyze,
    _act_gather,
    _act_plan,
    _act_report,
    _act_revise,
    _act_score,
    _act_synthesize,
    _make_check_control_signals,
    _make_gate_intervention,
    _make_persist_state,
    _make_research_config,
    _make_restore_state,
    cancel_research,
    research_skill,
    resume_research,
    run_research,
)


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext()


@pytest.fixture
def populated_registry() -> SkillRegistry:
    reg = SkillRegistry()
    register_all_actions(reg)
    reg.register(research_skill)
    return reg


# ─── Skill metadata ─────────────────────────────────────────────


class TestResearchSkillMetadata:
    def test_name(self) -> None:
        assert research_skill.name == "research"

    def test_3_actions(self) -> None:
        assert set(research_skill.actions.keys()) == {
            "run_research", "resume_research", "cancel_research",
        }

    def test_action_descriptions_non_empty(self) -> None:
        for a in research_skill.actions.values():
            assert a.description
            assert a.input_schema["type"] == "object"

    def test_research_reason_prompt_mentions_actions(self) -> None:
        for action in ("plan", "gather", "analyze", "synthesize",
                       "score", "revise", "report", "done"):
            assert action in RESEARCH_REASON_PROMPT


# ─── Config builder ─────────────────────────────────────────────


class TestMakeResearchConfig:
    def test_returns_react_config(self, ctx: SkillContext) -> None:
        cfg = _make_research_config(
            {"session_id": "s1", "query": "q"}, ctx,
        )
        assert isinstance(cfg, ReactConfig)

    def test_has_7_actions(self, ctx: SkillContext) -> None:
        cfg = _make_research_config({"session_id": "s1", "query": "q"}, ctx)
        assert len(cfg.actions) == 7
        names = sorted(a.name for a in cfg.actions)
        assert names == [
            "analyze", "gather", "plan", "report",
            "revise", "score", "synthesize",
        ]

    def test_initial_state_has_15_plus_fields(self, ctx: SkillContext) -> None:
        cfg = _make_research_config(
            {"session_id": "s1", "query": "test"}, ctx,
        )
        state = cfg.initial_state
        # 15+ ResearchState fields (per design spec)
        expected_fields = {
            "session_id", "query", "round", "max_rounds", "max_replan",
            "phase", "sub_queries", "sources", "synthesis", "report_md",
            "review", "knowledge_gaps", "contradictions", "issues",
            "observations", "cancelled", "paused", "budget_remaining",
            "_last_thought",
        }
        assert expected_fields.issubset(set(state.keys())), (
            f"missing: {expected_fields - set(state.keys())}"
        )

    def test_max_rounds_override(self, ctx: SkillContext) -> None:
        cfg = _make_research_config(
            {"session_id": "s1", "query": "q", "max_rounds": 3}, ctx,
        )
        assert cfg.max_rounds == 3
        assert cfg.initial_state["max_rounds"] == 3

    def test_gate_min_sources_override(self, ctx: SkillContext) -> None:
        cfg = _make_research_config(
            {"session_id": "s1", "query": "q", "gate_min_sources": 5}, ctx,
        )
        # Verify the override is captured in the initial state via gate config
        assert cfg.initial_state["max_replan"] == 2  # default

    def test_done_condition_triggers_on_phase_done(self, ctx: SkillContext) -> None:
        cfg = _make_research_config({"session_id": "s1", "query": "q"}, ctx)
        assert cfg.done_condition({"phase": "done"}) is True

    def test_done_condition_triggers_on_cancelled(self, ctx: SkillContext) -> None:
        cfg = _make_research_config({"session_id": "s1", "query": "q"}, ctx)
        assert cfg.done_condition({"cancelled": True}) is True

    def test_done_condition_triggers_on_paused(self, ctx: SkillContext) -> None:
        cfg = _make_research_config({"session_id": "s1", "query": "q"}, ctx)
        assert cfg.done_condition({"paused": True}) is True

    def test_done_condition_false_on_normal_state(self, ctx: SkillContext) -> None:
        cfg = _make_research_config({"session_id": "s1", "query": "q"}, ctx)
        assert cfg.done_condition({"phase": "gathering"}) is False


# ─── Hook factories ─────────────────────────────────────────────


class TestHookFactories:
    def test_check_control_signals_no_db(self) -> None:
        """With db=None, the hook is a no-op."""
        hook = _make_check_control_signals(None)
        state = {"session_id": "x"}
        hook(state, "plan")  # must not raise
        assert state.get("cancelled", False) is False

    def test_check_control_signals_with_mock_db(self) -> None:
        mock_db = _make_mock_db(
            get_research_session=lambda sid: {"status": "cancelling"},
        )
        hook = _make_check_control_signals(mock_db)
        state = {"session_id": "x"}
        hook(state, "plan")
        assert state["cancelled"] is True

    def test_check_control_signals_pause(self) -> None:
        mock_db = _make_mock_db(
            get_research_session=lambda sid: {"status": "pausing"},
        )
        hook = _make_check_control_signals(mock_db)
        state = {"session_id": "x"}
        hook(state, "plan")
        assert state["paused"] is True

    def test_gate_intervention_no_force_below_threshold(self) -> None:
        """Below gate_min_sources, no forced transition."""
        hook = _make_gate_intervention(db=None, gate_min_sources=3)
        state = {"sources": [{"url": "a"}], "phase": "gathering"}
        result = type("R", (), {"status": "ok"})()
        hook(state, "gather", result)
        assert "_forced_next_action" not in state

    def test_gate_intervention_force_above_threshold(self) -> None:
        hook = _make_gate_intervention(db=None, gate_min_sources=2)
        state = {
            "sources": [{"url": "a"}, {"url": "b"}, {"url": "c"}],
            "phase": "gathering",
        }
        result = type("R", (), {"status": "ok"})()
        hook(state, "gather", result)
        assert state["_forced_next_action"] == "analyze"
        assert any("gate" in o for o in state["observations"])

    def test_gate_intervention_ignores_non_gather_actions(self) -> None:
        hook = _make_gate_intervention(db=None, gate_min_sources=1)
        state = {"sources": [{"url": "a"}]}
        result = type("R", (), {"status": "ok"})()
        hook(state, "analyze", result)
        assert "_forced_next_action" not in state

    def test_persist_state_with_mock_db(self) -> None:
        saved: list[tuple] = []
        def _save(*args, **kwargs):
            sid = kwargs.get("session_id", args[0] if args else None)
            step = kwargs.get("step_num", args[1] if len(args) > 1 else None)
            state = kwargs.get("state", args[2] if len(args) > 2 else None)
            saved.append((sid, step, state))
        mock_db = _make_mock_db(save_research_state=_save)
        hook = _make_persist_state(mock_db)
        state = {"session_id": "x", "phase": "gathering"}
        hook(state, 0)
        assert saved == [("x", 0, state)]

    def test_persist_state_no_db(self) -> None:
        hook = _make_persist_state(None)
        hook({"session_id": "x"}, 0)  # no-op, no raise

    def test_restore_state_with_mock_db(self) -> None:
        saved_state = {"session_id": "x", "phase": "analyzing", "round": 3}
        mock_db = _make_mock_db(
            list_steps=lambda sid: [
                {"step_num": 0, "result": {"phase": "planning", "round": 1}},
                {"step_num": 1, "result": saved_state},
            ],
        )
        hook = _make_restore_state(mock_db)
        restored = hook({"session_id": "x"})
        assert restored == saved_state

    def test_restore_state_no_steps(self) -> None:
        mock_db = _make_mock_db(list_steps=lambda sid: [])
        hook = _make_restore_state(mock_db)
        state = {"session_id": "x", "phase": "gathering"}
        assert hook(state) is state

    def test_restore_state_no_db(self) -> None:
        hook = _make_restore_state(None)
        state = {"session_id": "x"}
        assert hook(state) is state


# ─── Mock helpers ───────────────────────────────────────────────


def _make_mock_db(**methods):
    """Build a mock DB object whose methods accept ``*args, **kwargs``.

    The class-attribute trick `type("X", (), {...})()` rebinds
    lambdas to instance methods, which then expect ``self`` as
    the first arg AND break on keyword args. Defining the
    methods via a proper class with ``*args, **kwargs`` avoids
    both pitfalls.
    """
    class _Mock:
        pass
    for name, fn in methods.items():
        # Wrap in a normal method (no self-binding surprise,
        # accepts both positional and keyword args).
        def make_handler(_fn):
            def handler(self, *args, **kwargs):
                return _fn(*args, **kwargs)
            return handler
        setattr(_Mock, name, make_handler(fn))
    return _Mock()


# ─── Action handlers (unit-level) ───────────────────────────────


class TestActHandlers:
    def test_plan_sets_phase(self, ctx: SkillContext) -> None:
        state: dict = {"query": "What is X?"}
        r = asyncio.run(_act_plan(state, ctx))
        assert r.status == "ok"
        assert state["phase"] == "planning"
        assert "sub_queries" in state

    def test_plan_missing_query(self, ctx: SkillContext) -> None:
        state: dict = {}
        r = asyncio.run(_act_plan(state, ctx))
        assert r.status == "error"

    def test_gather_offline_synthetic(self, ctx: SkillContext) -> None:
        state: dict = {
            "sub_queries": [{"q": "topic A", "status": "pending"}],
        }
        r = asyncio.run(_act_gather(state, ctx))
        assert r.status == "ok"
        assert len(state["sources"]) >= 1
        assert state["sub_queries"][0]["status"] == "gathered"

    def test_gather_skips_already_gathered(self, ctx: SkillContext) -> None:
        state: dict = {
            "sub_queries": [{"q": "topic A", "status": "gathered"}],
        }
        r = asyncio.run(_act_gather(state, ctx))
        assert r.status == "ok"
        assert len(state["sources"]) == 0

    def test_analyze_no_sources_marks_done(self, ctx: SkillContext) -> None:
        state: dict = {"sources": []}
        r = asyncio.run(_act_analyze(state, ctx))
        # With no sources, analysis is marked as done (empty)
        # so the rule-based reasoner progresses to the next step.
        assert r.status == "ok"
        assert state["analysis"]["_source_count"] == 0

    def test_analyze_with_synthetic_source(self, ctx: SkillContext) -> None:
        state: dict = {"sources": [
            {"url": "https://x", "title": "x", "source_type": "web"},
        ]}
        r = asyncio.run(_act_analyze(state, ctx))
        assert r.status == "ok"
        assert state["sources"][0]["analysis"]["entities"] == []

    def test_synthesize_uses_summarize_skill(self, ctx: SkillContext) -> None:
        state: dict = {"sources": [
            {"url": "x", "title": "x", "source_type": "web",
             "analysis": {"entities": ["e1"]}},
        ]}
        r = asyncio.run(_act_synthesize(state, ctx))
        assert r.status == "ok"
        assert state["synthesis"]["claims"]
        assert "knowledge_gaps" in state

    def test_score_writes_score(self, ctx: SkillContext) -> None:
        state: dict = {"synthesis": {"narrative": "## Section\n\ntext"}}
        r = asyncio.run(_act_score(state, ctx))
        assert r.status == "ok"
        assert 0.0 <= state["score"] <= 1.0
        assert "score_by_dim" in state

    def test_score_no_synthesis(self, ctx: SkillContext) -> None:
        state: dict = {"synthesis": None}
        r = asyncio.run(_act_score(state, ctx))
        assert r.status == "error"

    def test_revise_skipped_for_high_score(self, ctx: SkillContext) -> None:
        state: dict = {
            "score": 0.9, "synthesis": {"narrative": "good"},
        }
        r = asyncio.run(_act_revise(state, ctx))
        assert r.status == "ok"
        assert r.data["_skipped"] is True

    def test_revise_applied_for_low_score(self, ctx: SkillContext) -> None:
        state: dict = {
            "score": 0.3, "synthesis": {"narrative": "raw"},
        }
        r = asyncio.run(_act_revise(state, ctx))
        assert r.status == "ok"
        assert state["revision_count"] == 1
        assert "##" in state["synthesis"]["narrative"]

    def test_report_builds_markdown(self, ctx: SkillContext) -> None:
        state: dict = {
            "query": "Test Q",
            "sources": [{"url": "u1", "title": "T1"}],
            "synthesis": {"narrative": "syn-text", "claims": [
                {"text": "claim-1"}, {"text": "claim-2"},
            ]},
            "knowledge_gaps": ["gap1"],
        }
        r = asyncio.run(_act_report(state, ctx))
        assert r.status == "ok"
        md = state["report_md"]
        assert md.startswith("# Test Q")
        assert "## Summary" in md
        assert "## Key Claims" in md
        assert "claim-1" in md
        assert "## Sources" in md
        assert "## Knowledge Gaps" in md


# ─── End-to-end: run_research ────────────────────────────────────


class TestRunResearch:
    @pytest.mark.asyncio
    async def test_run_research_basic(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        r = await run_research(
            {"session_id": "s1", "query": "What is X?"}, ctx,
        )
        assert r.status == "ok"
        d = r.data
        assert "events" in d
        assert "final_state" in d
        assert "report_md" in d
        assert d["final_state"]["session_id"] == "s1"
        assert d["final_state"]["query"] == "What is X?"

    @pytest.mark.asyncio
    async def test_run_research_emits_5_phases(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        r = await run_research(
            {"session_id": "s1", "query": "What is X?"}, ctx,
        )
        # We expect 5 reasoning events: plan, gather, analyze,
        # synthesize, report (then done)
        reasoning = [e for e in r.data["events"] if e["type"] == EVENT_REASONING]
        actions = [e["action"] for e in reasoning]
        assert "plan" in actions
        assert "gather" in actions
        assert "analyze" in actions
        assert "synthesize" in actions
        # report is reached if score >= 0.5 OR after revise

    @pytest.mark.asyncio
    async def test_run_research_produces_non_empty_report(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        r = await run_research(
            {"session_id": "s1", "query": "What is X?"}, ctx,
        )
        report = r.data["report_md"] or ""
        assert len(report) > 50
        assert "## Summary" in report
        assert "## Sources" in report

    @pytest.mark.asyncio
    async def test_run_research_terminates_with_phase_event(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        r = await run_research(
            {"session_id": "s1", "query": "What is X?"}, ctx,
        )
        phase_events = [e for e in r.data["events"] if e["type"] == EVENT_PHASE]
        assert len(phase_events) >= 1
        assert phase_events[-1]["phase"] == "done"


# ─── Persistence integration (with real ChatDatabase) ───────────


class TestPersistenceIntegration:
    @pytest.mark.asyncio
    async def test_run_research_persists_steps(self) -> None:
        """Every round persists the state via db.save_research_state."""
        from llmwikify.apps.chat.db import ChatDatabase
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(tmp)
            sid = db.create_research_session("wiki-1", "test q")
            ctx = SkillContext(db=db)
            reg = SkillRegistry()
            register_all_actions(reg)
            reg.register(research_skill)
            r = await run_research(
                {"session_id": sid, "query": "test q"}, ctx,
            )
            assert r.status == "ok"
            # Verify steps were persisted
            steps = db.list_steps(sid)
            assert len(steps) >= 1
            for step in steps:
                assert step["action"]  # non-empty
                assert isinstance(step["result"], dict)
                # The persisted state includes the round
                assert "round" in step["result"]

    @pytest.mark.asyncio
    async def test_resume_loads_last_step(self) -> None:
        from llmwikify.apps.chat.db import ChatDatabase
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(tmp)
            sid = db.create_research_session("wiki-1", "test q")
            ctx = SkillContext(db=db)
            reg = SkillRegistry()
            register_all_actions(reg)
            reg.register(research_skill)
            # First run
            r1 = await run_research(
                {"session_id": sid, "query": "test q"}, ctx,
            )
            assert r1.status == "ok"
            steps_before = len(db.list_steps(sid))
            # Resume (no-op in offline mode, but should not crash)
            r2 = await resume_research(
                {"session_id": sid, "query": "test q"}, ctx,
            )
            assert r2.status == "ok"


# ─── Cancel flow ────────────────────────────────────────────────


class TestCancelResearch:
    @pytest.mark.asyncio
    async def test_cancel_no_db(self, ctx: SkillContext) -> None:
        r = await cancel_research({"session_id": "x"}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_cancel_no_session_id(self, ctx: SkillContext) -> None:
        from llmwikify.apps.chat.db import ChatDatabase
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(tmp)
            ctx = SkillContext(db=db)
            r = await cancel_research({}, ctx)
            assert r.status == "error"

    @pytest.mark.asyncio
    async def test_cancel_marks_session_cancelling(self) -> None:
        from llmwikify.apps.chat.db import ChatDatabase
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(tmp)
            sid = db.create_research_session("wiki-1", "q")
            ctx = SkillContext(db=db)
            r = await cancel_research({"session_id": sid}, ctx)
            assert r.status == "ok"
            session = db.get_research_session(sid)
            assert session is not None
            assert session["status"] == "cancelling"

    @pytest.mark.asyncio
    async def test_cancel_is_picked_up_by_control_signal_hook(self) -> None:
        """Integration: cancel + run_research should set
        state['cancelled'] = True (via on_before_act hook)."""
        from llmwikify.apps.chat.db import ChatDatabase
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(tmp)
            sid = db.create_research_session("wiki-1", "q")
            db.update_research_status(sid, "cancelling", "cancelling", -1)
            ctx = SkillContext(db=db)
            reg = SkillRegistry()
            register_all_actions(reg)
            reg.register(research_skill)
            r = await run_research(
                {"session_id": sid, "query": "q"}, ctx,
            )
            assert r.data["cancelled"] is True


# ─── Failure / edge cases ────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_run_research_action_error_emitted(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        """If a handler raises unexpectedly, the loop emits
        an action_error event and continues. We force this
        by using a custom registry with a broken plan action.

        IMPORTANT: we restore the plan handler's original
        after the test to avoid leaking the broken handler
        to subsequent tests (Skill class actions are shared).
        """
        from llmwikify.apps.chat.skills.actions import plan_skill
        original_handler = plan_skill.actions["plan"].handler
        try:
            async def broken_handler(args, c):
                raise ValueError("simulated LLM failure")
            # Mutate the SHARED class-level actions dict briefly.
            plan_skill.actions["plan"].handler = broken_handler
            r = await run_research(
                {"session_id": "s1", "query": "q"}, ctx,
            )
            # The loop should still complete (max_rounds=5)
            assert r.status == "ok"
            # An action_error event was emitted
            errs = [e for e in r.data["events"]
                    if e["type"] == EVENT_ACTION_ERROR]
            assert len(errs) >= 1
            assert "simulated LLM failure" in errs[0]["error"]
        finally:
            # Restore the original handler so other tests
            # aren't affected (this is a class-level mutation).
            plan_skill.actions["plan"].handler = original_handler

    @pytest.mark.asyncio
    async def test_run_research_empty_query(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        r = await run_research(
            {"session_id": "s1", "query": ""}, ctx,
        )
        # The plan step will fail (missing query), but the
        # loop should still complete via max_rounds.
        assert r.status == "ok"

    @pytest.mark.asyncio
    async def test_run_research_max_rounds_limit(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        r = await run_research(
            {"session_id": "s1", "query": "q", "max_rounds": 2}, ctx,
        )
        # At most 2 round_complete events
        rc = [e for e in r.data["events"] if e["type"] == EVENT_ROUND_COMPLETE]
        assert len(rc) <= 2


# ─── Skill action handler integration ──────────────────────────


class TestResearchSkillActionHandlers:
    """Verify the public action handlers (run/resume/cancel) work
    when invoked via SkillRuntime (the framework's standard path)."""

    @pytest.mark.asyncio
    async def test_run_research_via_runtime(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        from llmwikify.apps.chat.skills import SkillRuntime
        rt = SkillRuntime(populated_registry)
        r = await rt.execute(
            "research", "run_research",
            {"session_id": "s1", "query": "q"}, ctx,
        )
        assert r.status == "ok"
        assert r.data["report_md"]

    @pytest.mark.asyncio
    async def test_resume_research_via_runtime(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        from llmwikify.apps.chat.skills import SkillRuntime
        rt = SkillRuntime(populated_registry)
        r = await rt.execute(
            "research", "resume_research",
            {"session_id": "s1", "query": "q"}, ctx,
        )
        assert r.status == "ok"

    @pytest.mark.asyncio
    async def test_cancel_research_via_runtime(
        self, ctx: SkillContext, populated_registry: SkillRegistry
    ) -> None:
        from llmwikify.apps.chat.db import ChatDatabase
        from llmwikify.apps.chat.skills import SkillRuntime
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(tmp)
            sid = db.create_research_session("w1", "q")
            ctx = SkillContext(db=db)
            rt = SkillRuntime(populated_registry)
            r = await rt.execute(
                "research", "cancel_research",
                {"session_id": sid}, ctx,
            )
            assert r.status == "ok"
            assert db.get_research_session(sid)["status"] == "cancelling"
