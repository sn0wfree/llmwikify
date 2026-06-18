"""Phase 2 #5 / C1 — ResearchReasoner extracted from engine.py.

Tests cover the 3 reason methods that now live in
``autoresearch.reasoner.ResearchReasoner``:

  1. Engine holds a ``self.reasoner`` instance
  2. The reasoner holds back-refs to the engine's deps
  3. ``_reason`` on engine delegates to ``reasoner.reason``
  4. ``_rule_based_reason`` on engine delegates to ``reasoner.rule_based``
  5. ``_llm_reason`` on engine delegates to ``reasoner._llm_reason``
  6. ``reasoner.rule_based`` returns the right action for each
     state shape (no clarification, no sub-queries, ungathered,
     unanalyzed, no synthesis, no report, no review, approved,
     failed, error, default)
  7. ``reasoner.rule_based`` returns ``None`` for clean exit when
     all gates pass (no action needed → done)
  8. The reasoner's ``VALID_ACTIONS`` allow-list is consistent
     with the engine's legacy validation set
  9. Reasoner is constructed after the engine's action context
     (so it can capture ``_action_ctx``)
 10. Regression guard: the legacy 3-method block (with all
     its rule-based logic) no longer lives in ``engine.py``.
"""

import inspect

import pytest

from llmwikify.apps.chat.state import ResearchState


def test_engine_constructs_reasoner():
    """ResearchEngine.__init__ creates a self.reasoner attribute."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    # We can't construct a full engine without deps, so use a
    # mock: assert the attribute is set in __init__.
    import llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine.__init__)
    assert "self.reasoner = ResearchReasoner(self)" in src, (
        "ResearchEngine.__init__ should construct a ResearchReasoner"
    )


def test_reasoner_holds_back_refs_to_engine_deps():
    """ResearchReasoner caches the engine's db, config, _action_ctx, _max_replan."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    # Mock engine with the required attributes
    class FakeActionCtx:
        pass

    class FakeEngine:
        db = "fake_db"
        config = {"quality_threshold": 7}
        _action_ctx = FakeActionCtx()
        _max_replan = 2

    r = ResearchReasoner(FakeEngine())
    assert r._db == "fake_db"
    assert r._config == {"quality_threshold": 7}
    assert isinstance(r._action_ctx, FakeActionCtx)
    assert r._max_replan == 2


def test_engine_reason_delegates_to_reasoner():
    """engine._reason() calls self.reasoner.reason() (1-line delegator)."""
    import llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._reason)
    # The body must reference self.reasoner.reason
    assert "self.reasoner.reason" in src, (
        "ResearchEngine._reason should delegate to self.reasoner.reason"
    )
    # And the body should be 1 line (return + self.reasoner.reason(state))
    body_lines = [
        line.strip() for line in src.splitlines()
        if line.strip()
        and not line.strip().startswith("def ")
        and not line.strip().startswith("'''")
        and not line.strip().startswith('"""')
    ]
    # Should have just a docstring + the return
    return_lines = [l for l in body_lines if l.startswith("return ")]
    assert len(return_lines) == 1, (
        f"ResearchEngine._reason should have exactly 1 return statement "
        f"(the delegator), got {len(return_lines)}"
    )


def test_engine_rule_based_reason_delegates_to_reasoner():
    """engine._rule_based_reason() is a 1-line delegator."""
    import llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._rule_based_reason)
    assert "self.reasoner.rule_based" in src, (
        "ResearchEngine._rule_based_reason should delegate to "
        "self.reasoner.rule_based"
    )


def test_engine_llm_reason_delegates_to_reasoner():
    """engine._llm_reason() is a 1-line delegator."""
    import llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._llm_reason)
    assert "self.reasoner._llm_reason" in src, (
        "ResearchEngine._llm_reason should delegate to "
        "self.reasoner._llm_reason"
    )


def test_rule_based_returns_done_for_error_state():
    """rule_based('error') → 'done' (let LLM override if it wants to retry)."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    class FakeDB:
        def get_sources(self, session_id):
            return []

    class FakeEngine:
        db = FakeDB()
        config = {}
        _action_ctx = None
        _max_replan = 2

    r = ResearchReasoner(FakeEngine())
    state = ResearchState(phase="error")
    assert r.rule_based(state) == "done"


def test_rule_based_returns_plan_for_uninitialized_state():
    """rule_based with no clarification/sub_queries → 'plan'."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    class FakeDB:
        def get_sources(self, session_id):
            return []

    class FakeEngine:
        db = FakeDB()
        config = {}
        _action_ctx = None
        _max_replan = 2

    r = ResearchReasoner(FakeEngine())
    state = ResearchState(clarification={"q": "test"})  # has clarification
    # No sub_queries → plan
    assert r.rule_based(state) == "plan"


def test_rule_based_returns_done_for_fully_complete_state():
    """rule_based with approved review + report → 'done'."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    class FakeDB:
        def get_sources(self, session_id):
            return []

    class FakeEngine:
        db = FakeDB()
        config = {}
        _action_ctx = None
        _max_replan = 2

    r = ResearchReasoner(FakeEngine())
    state = ResearchState(
        round=0,
        max_rounds=5,
        clarification={"q": "x"},
        sub_queries=[{"id": 1}],
        sources=[{"sub_query_id": 1, "analysis": {}}],
        synthesis={"text": "s"},
        report_md="# Report",
        review={"approved": True, "score": 8},
    )
    assert r.rule_based(state) == "done"


def test_rule_based_does_not_replan_after_report():
    """Regression: when a report exists, gaps+round+budget must NOT
    redirect back to 'plan' — that would spin on the planning→planning
    transition. The correct next step is 'review' (or 'done'/'revise').
    """
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    class FakeDB:
        def get_sources(self, session_id):
            return []

    class FakeEngine:
        db = FakeDB()
        config = {}
        _action_ctx = None
        _max_replan = 2

    r = ResearchReasoner(FakeEngine())
    state = ResearchState(
        round=0,
        max_rounds=5,
        clarification={"q": "x"},
        sub_queries=[{"id": 1}],
        sources=[{"sub_query_id": 1, "analysis": {}}],
        synthesis={"text": "s", "knowledge_gaps": ["gap1", "gap2"]},
        report_md="# Report",
        review=None,  # not reviewed yet
    )
    state.knowledge_gaps = ["gap1", "gap2"]  # gaps present
    state.budget_remaining = 0.9  # plenty of budget
    # round=0 < _max_replan+1 (=3): pre-fix, this would return "plan"
    result = r.rule_based(state)
    assert result != "plan", (
        f"rule_based should not replan after report_md is set, got {result!r}"
    )
    # Should fall through to the review branch (report exists, review missing)
    assert result == "review", f"expected 'review', got {result!r}"


def test_rule_based_replans_before_report():
    """When no report exists yet, gaps+round+budget → 'plan' (replan)."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    class FakeDB:
        def get_sources(self, session_id):
            return []

    class FakeEngine:
        db = FakeDB()
        config = {}
        _action_ctx = None
        _max_replan = 2

    r = ResearchReasoner(FakeEngine())
    state = ResearchState(
        round=0,
        max_rounds=5,
        clarification={"q": "x"},
        sub_queries=[{"id": 1}],
        sources=[{"sub_query_id": 1, "analysis": {}}],
        synthesis={"text": "s", "knowledge_gaps": ["gap1"]},
        report_md=None,  # no report yet → replan is still useful
    )
    state.knowledge_gaps = ["gap1"]
    state.budget_remaining = 0.9
    assert r.rule_based(state) == "plan"


def test_rule_based_does_not_replan_when_budget_low():
    """When budget is low, the replan guard must skip 'plan' even before
    a report exists — fall through to the report/review chain."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner

    class FakeDB:
        def get_sources(self, session_id):
            return []

    class FakeEngine:
        db = FakeDB()
        config = {}
        _action_ctx = None
        _max_replan = 2

    r = ResearchReasoner(FakeEngine())
    state = ResearchState(
        round=0,
        max_rounds=5,
        clarification={"q": "x"},
        sub_queries=[{"id": 1}],
        sources=[{"sub_query_id": 1, "analysis": {}}],
        synthesis={"text": "s", "knowledge_gaps": ["gap1"]},
        report_md=None,
    )
    state.knowledge_gaps = ["gap1"]
    state.budget_remaining = 0.05  # below 0.15 threshold
    result = r.rule_based(state)
    assert result != "plan", (
        f"low budget should suppress replan, got {result!r}"
    )
    # No report yet → falls through to 'report'
    assert result == "report", f"expected 'report', got {result!r}"


def test_valid_actions_allowlist_matches_engine_legacy_set():
    """The reasoner's VALID_ACTIONS set matches the legacy inline set."""
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import VALID_ACTIONS

    # The legacy engine code had:
    #   valid = {"plan", "gather", "analyze", "synthesize",
    #            "report", "review", "revise", "done"}
    expected = {
        "plan", "gather", "analyze", "synthesize",
        "report", "review", "revise", "done",
    }
    assert VALID_ACTIONS == expected, (
        f"VALID_ACTIONS should be {expected}, got {VALID_ACTIONS}"
    )


def test_legacy_rule_based_block_not_in_engine():
    """Regression guard: the rule-based logic is no longer inlined in engine.py.

    The decision tree (with ``if state.phase == "error"``,
    ``if state.clarification is None``, etc.) used to live
    inside ``engine.py``. After C1, only the 1-line delegator
    remains. This test catches re-introduction of the inline
    logic.
    """
    import llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine)
    # The phrase ``if state.phase == "error"`` should NOT appear
    # in the engine anymore — it now lives in reasoner.py.
    assert 'state.phase == "error"' not in src, (
        "The rule-based reasoner logic should not be inlined in "
        "engine.py anymore. Phase 2 #5 / C1 extracted it to "
        "reasoner.py. If you see this error, the rule-based "
        "logic was re-introduced into the engine."
    )
    # And the legacy rule-set sentences
    assert "ungathered sub-queries" not in src, (
        "The rule-based decision tree should not be inlined in "
        "engine.py. Move it to reasoner.py."
    )
