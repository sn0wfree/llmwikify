"""Tests for the plan→plan self-loop guard in ResearchReasoner.

Regression target:
    Before the anti-spin guard, the engine could be stuck at the
    "planning" phase for the user:
      - ``_llm_reason`` could keep returning "plan" because the
        ``research_reason`` prompt nudges replanning on knowledge gaps.
      - ``rule_based`` (the fallback) also returns "plan" while
        gaps+budget+round allow it (the legitimate replan path).
    With no upper bound on consecutive "plan" decisions, the
    engine spun forever and the UI looked frozen.

This file covers:
  - state._consecutive_plan field exists and is mutable
  - rule_based returns "gather" (then "report") after _max_replan+1
    consecutive plans, even when the gap-replan path would say "plan"
  - rule_based still returns "plan" for the normal "first round" case
    (no regression of legitimate replans)
  - _llm_reason returns rule_based when LLM says "plan" with a
    report already written
  - engine's reason callback increments/resets the counter

All tests are pure unit tests; no LLM, no DB, no FastAPI.
"""

from __future__ import annotations

import inspect

from llmwikify.apps.chat.state import ResearchState

# ─── Fixtures ──────────────────────────────────────────────────────


class _FakeDB:
    """Minimal DB stand-in returning empty sources for the reasoner."""

    def get_sources(self, session_id):
        return []


class _FakeEngine:
    def __init__(self, max_replan: int = 2):
        self.db = _FakeDB()
        self.config = {}
        self._action_ctx = None
        self._max_replan = max_replan


# ─── State field ───────────────────────────────────────────────────


class TestConsecutivePlanField:
    """ResearchState must carry the anti-spin counter."""

    def test_field_exists(self) -> None:
        state = ResearchState()
        assert hasattr(state, "_consecutive_plan"), (
            "ResearchState should expose a _consecutive_plan field "
            "for the anti-spin guard"
        )

    def test_default_zero(self) -> None:
        state = ResearchState()
        assert state._consecutive_plan == 0

    def test_mutable(self) -> None:
        state = ResearchState()
        state._consecutive_plan = 3
        assert state._consecutive_plan == 3

    def test_excluded_from_repr(self) -> None:
        """The counter is internal observation state; should not
        pollute repr() (avoids noise in error messages)."""
        state = ResearchState()
        state._consecutive_plan = 5
        r = repr(state)
        assert "_consecutive_plan" not in r, (
            f"_consecutive_plan should be excluded from repr, got {r!r}"
        )


# ─── rule_based anti-spin: gather branch ───────────────────────────


class TestRuleBasedAntiSpinGather:
    """After _max_replan consecutive plans, the rule-based reasoner
    must not return "plan" from the gap-replan path. Control must
    fall through to the next available action (synthesize → report
    → review → done).
    """

    def _build_state(self, consecutive_plan: int) -> ResearchState:
        """State where the gap-replan path would otherwise fire:
        all sub-queries gathered, sources analyzed, synthesis done,
        knowledge gaps present, no report yet, plenty of budget.
        """
        state = ResearchState(
            round=2,
            max_rounds=5,
            clarification={"q": "x"},
            sub_queries=[{"id": 1}],
            sources=[{"sub_query_id": 1, "analysis": {}}],
            synthesis={"text": "s", "knowledge_gaps": ["gap-a", "gap-b"]},
            report_md=None,
        )
        state.knowledge_gaps = ["gap-a", "gap-b"]
        state.budget_remaining = 0.9
        state._consecutive_plan = consecutive_plan
        return state

    def test_consecutive_plans_break_to_report(self) -> None:
        """When _consecutive_plan >= _max_replan and there is no
        report yet, the replan path must be suppressed; the next
        action is 'report' so the user sees a result.
        """
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = self._build_state(consecutive_plan=3)
        result = r.rule_based(state)
        assert result == "report", (
            f"plan anti-spin should break to 'report' when plan budget "
            f"is exhausted, got {result!r}"
        )

    def test_below_threshold_still_replans(self) -> None:
        """Regression: legitimate first-pass replans must still work.
        When _consecutive_plan is below _max_replan, the gap-replan
        path should trigger as designed.
        """
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = self._build_state(consecutive_plan=1)
        result = r.rule_based(state)
        assert result == "plan", (
            f"legitimate replan below the threshold should still return "
            f"'plan', got {result!r}"
        )

    def test_zero_consecutive_plans_still_replans(self) -> None:
        """The very first plan call is a normal 'plan'."""
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = self._build_state(consecutive_plan=0)
        assert r.rule_based(state) == "plan"

    def test_error_state_unaffected_by_anti_spin(self) -> None:
        """The anti-spin guard must come AFTER the error-state short
        circuit — a phase=error session should still terminate, not
        get redirected to report.
        """
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = self._build_state(consecutive_plan=10)
        state.phase = "error"
        result = r.rule_based(state)
        assert result == "done", (
            f"error phase should short-circuit to 'done' regardless of "
            f"anti-spin counter, got {result!r}"
        )

    def test_at_exact_threshold_breaks(self) -> None:
        """The boundary condition: when _consecutive_plan equals
        _max_replan, the guard fires. We use strict less-than in the
        plan condition so equality exhausts the budget.
        """
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = self._build_state(consecutive_plan=2)
        assert r.rule_based(state) == "report"

    def test_no_replan_when_synthesis_missing(self) -> None:
        """If synthesis is missing and we are anti-spinning, the
        next action is 'synthesize' (not 'report' or 'plan').
        """
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = ResearchState(
            round=2,
            max_rounds=5,
            clarification={"q": "x"},
            sub_queries=[{"id": 1}],
            sources=[{"sub_query_id": 1, "analysis": {}}],
            synthesis=None,  # ← no synthesis yet
            report_md=None,
        )
        state.knowledge_gaps = ["gap-a"]
        state.budget_remaining = 0.9
        state._consecutive_plan = 5
        # No synthesis → 'synthesize' comes before 'report'
        assert r.rule_based(state) == "synthesize"


# ─── _llm_reason anti-spin ────────────────────────────────────────


class TestLlmReasonAntiSpin:
    """_llm_reason must short-circuit 'plan' to rule_based when a
    report already exists. The rule_based decision then either
    forces review (normal) or uses its own anti-spin guard.
    """

    def _make_state(self, *, with_report: bool, consecutive_plan: int = 0):
        state = ResearchState(
            round=1,
            max_rounds=5,
            clarification={"q": "x"},
            sub_queries=[{"id": 1}],
            sources=[{"sub_query_id": 1, "analysis": {}}],
            synthesis={"text": "s", "knowledge_gaps": []},
            report_md="# Existing report" if with_report else None,
            review=None,
        )
        state.knowledge_gaps = []
        state.budget_remaining = 0.9
        state._consecutive_plan = consecutive_plan
        return state

    async def test_llm_says_plan_with_existing_report_falls_back(self) -> None:
        """If the LLM says 'plan' but report_md is already set, the
        reasoner must NOT call 'plan' (that would re-run the report
        action and re-emit the same markdown). It must apply the
        rule-based decision instead, which would normally return
        'review' (since report exists, review is missing).
        """
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = self._make_state(with_report=True)

        # Patch the LLM call inside the reasoner to always say "plan"
        async def fake_run_prompt(*args, **kwargs):
            return {"action": "plan", "thought": "thinking..."}

        r._action_ctx = object()  # avoid None checks
        import llmwikify.apps.chat.research_engine.reasoner as reasoner_mod

        original = reasoner_mod.run_prompt
        reasoner_mod.run_prompt = fake_run_prompt
        try:
            result = await r._llm_reason(state)
        finally:
            reasoner_mod.run_prompt = original

        # The fallback must not return 'plan' (which would re-trigger
        # report and waste budget).
        assert result != "plan", (
            f"LLM 'plan' with existing report should not return 'plan'; "
            f"got {result!r}"
        )
        # Should fall through to 'review' (report exists, review missing)
        assert result == "review", f"expected 'review', got {result!r}"

    async def test_llm_says_plan_without_report_passes_through(self) -> None:
        """When there is no report yet, the LLM's 'plan' decision is
        legitimate (it can mean 'replan') and must be honored.
        """
        from llmwikify.apps.chat.research_engine.reasoner import ResearchReasoner

        r = ResearchReasoner(_FakeEngine(max_replan=2))
        state = self._make_state(with_report=False)

        async def fake_run_prompt(*args, **kwargs):
            return {"action": "plan", "thought": "..."}

        r._action_ctx = object()
        import llmwikify.apps.chat.research_engine.reasoner as reasoner_mod

        original = reasoner_mod.run_prompt
        reasoner_mod.run_prompt = fake_run_prompt
        try:
            result = await r._llm_reason(state)
        finally:
            reasoner_mod.run_prompt = original

        assert result == "plan", (
            f"LLM 'plan' with no report should pass through, got {result!r}"
        )


# ─── Engine reason callback bookkeeping ────────────────────────────


class TestEngineReasonCallback:
    """The engine's reason callback must increment _consecutive_plan
    when it returns 'plan' and reset it on any other action.
    """

    def test_reason_callback_increments_plan(self) -> None:
        """Inspect the reason callback source to confirm the
        increment/reset logic exists.
        """
        import llmwikify.apps.chat.research_engine.engine as engine_mod

        src = inspect.getsource(engine_mod.ResearchEngine._build_react_config)
        assert "_consecutive_plan" in src, (
            "engine._build_react_config's reason callback should track "
            "_consecutive_plan on the state to break plan→plan loops"
        )
        # The increment path
        assert "if action == \"plan\"" in src, (
            "reason callback should branch on action == 'plan' for the counter"
        )
        # The reset path
        assert "else:\n                state._consecutive_plan = 0" in src or \
               "state._consecutive_plan = 0" in src, (
            "reason callback should reset _consecutive_plan on non-plan actions"
        )
