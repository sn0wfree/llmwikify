"""Phase 2 #5 / C2 — ResearchGates extracted from engine.py.

Tests cover the 5 gate methods + the synthesis_to_text helper
that now live in ``autoresearch.gates.ResearchGates``:

  1. Engine holds a ``self.gates`` instance
  2. The gates holds back-refs to engine's db, config, quality_gate
  3. ``_check_control_signals`` on engine delegates to
     ``gates.check_control_signals``
  4. ``_check_framework_compliance`` delegates to
     ``gates.check_framework_compliance``
  5. ``_check_quality_compliance`` delegates to
     ``gates.check_quality_compliance``
  6. ``_can_replan`` delegates to ``gates.can_replan``
  7. ``_evaluate_gate`` delegates to ``gates.evaluate_gate``
  8. ``_synthesis_to_text`` static method delegates to
     ``ResearchGates.synthesis_to_text``
  9. Framework compliance returns the right missing step for
     each incomplete framework field
 10. Regression guard: the framework compliance / quality
     compliance / evaluate_gate logic no longer lives in
     ``engine.py``.
"""

import inspect


def test_engine_constructs_gates():
    """ResearchEngine.__init__ creates a self.gates attribute."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine.__init__)
    assert "self.gates = ResearchGates(self)" in src, (
        "ResearchEngine.__init__ should construct a ResearchGates"
    )


def test_gates_holds_back_refs_to_engine_deps():
    """ResearchGates caches the engine's db, config, _quality_gate."""
    from llmwikify.apps.chat.gates import ResearchGates

    class FakeQualityGate:
        pass

    class FakeEngine:
        db = "fake_db"
        config = {"quality_threshold": 7, "gate_min_sources": 3}
        _quality_gate = FakeQualityGate()

    g = ResearchGates(FakeEngine())
    assert g._db == "fake_db"
    assert g._config == {"quality_threshold": 7, "gate_min_sources": 3}
    assert isinstance(g._quality_gate, FakeQualityGate)


def test_engine_check_control_signals_delegates_to_gates():
    """engine._check_control_signals → self.gates.check_control_signals."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._check_control_signals)
    assert "self.gates.check_control_signals" in src, (
        "engine._check_control_signals should delegate to self.gates"
    )


def test_engine_check_framework_compliance_delegates_to_gates():
    """engine._check_framework_compliance → self.gates.check_framework_compliance."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._check_framework_compliance)
    assert "self.gates.check_framework_compliance" in src, (
        "engine._check_framework_compliance should delegate to self.gates"
    )


def test_engine_check_quality_compliance_delegates_to_gates():
    """engine._check_quality_compliance → self.gates.check_quality_compliance."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._check_quality_compliance)
    assert "self.gates.check_quality_compliance" in src, (
        "engine._check_quality_compliance should delegate to self.gates"
    )


def test_engine_can_replan_delegates_to_gates():
    """engine._can_replan → self.gates.can_replan."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._can_replan)
    assert "self.gates.can_replan" in src, (
        "engine._can_replan should delegate to self.gates.can_replan"
    )


def test_engine_evaluate_gate_delegates_to_gates():
    """engine._evaluate_gate → self.gates.evaluate_gate."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._evaluate_gate)
    assert "self.gates.evaluate_gate" in src, (
        "engine._evaluate_gate should delegate to self.gates.evaluate_gate"
    )


def test_engine_synthesis_to_text_delegates_to_gates():
    """engine._synthesis_to_text → ResearchGates.synthesis_to_text (static)."""
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine._synthesis_to_text)
    assert "ResearchGates.synthesis_to_text" in src, (
        "engine._synthesis_to_text should delegate to "
        "ResearchGates.synthesis_to_text"
    )


def test_framework_compliance_returns_missing_step():
    """Each incomplete framework field produces the right ``missing`` action."""
    from llmwikify.apps.chat.gates import ResearchGates
    from llmwikify.apps.chat.state import ResearchState

    class FakeEngine:
        db = None
        config = {}
        _quality_gate = None

    g = ResearchGates(FakeEngine())

    # Step 1 missing → "clarify"
    s = ResearchState()
    assert g.check_framework_compliance(s)["missing"] == "clarify"

    # Step 2 missing → "gather"
    s = ResearchState(clarification={"q": "x"})
    assert g.check_framework_compliance(s)["missing"] == "gather"

    # Step 3 missing → "synthesize" (reasoning_check)
    s = ResearchState(clarification={"q": "x"}, evidence_scores={"a": 0.5},
                      synthesis={"text": "s"})
    assert g.check_framework_compliance(s)["missing"] == "synthesize"

    # Step 4 missing → "report" (structure_check)
    s = ResearchState(
        clarification={"q": "x"}, evidence_scores={"a": 0.5},
        synthesis={"text": "s"}, reasoning_check={"ok": True},
    )
    assert g.check_framework_compliance(s)["missing"] == "report"

    # Step 5 missing → "report"
    s = ResearchState(
        clarification={"q": "x"}, evidence_scores={"a": 0.5},
        synthesis={"text": "s"}, reasoning_check={"ok": True},
        structure_check={"ok": True},
    )
    assert g.check_framework_compliance(s)["missing"] == "report"

    # Step 6 missing → "review"
    s = ResearchState(
        clarification={"q": "x"}, evidence_scores={"a": 0.5},
        synthesis={"text": "s"}, reasoning_check={"ok": True},
        structure_check={"ok": True}, report_md="# Report",
    )
    assert g.check_framework_compliance(s)["missing"] == "review"

    # All present → None
    s = ResearchState(
        clarification={"q": "x"}, evidence_scores={"a": 0.5},
        synthesis={"text": "s"}, reasoning_check={"ok": True},
        structure_check={"ok": True}, report_md="# Report",
        review={"approved": True},
    )
    assert g.check_framework_compliance(s) is None


def test_legacy_gate_logic_not_in_engine():
    """Regression guard: gate logic should not be inlined in engine.py.

    The framework compliance / quality compliance / gate
    evaluation logic used to live inside engine.py. After
    C2, only the 1-line delegators remain. This test
    catches re-introduction of the inline logic.
    """
    import llmwikify.apps.chat.engine as engine_mod

    src = inspect.getsource(engine_mod.ResearchEngine)
    # The 6-step framework check (step 1/2/3/4/5/6) should NOT
    # appear in the engine anymore.
    assert "step 1 (clarification) missing" not in src, (
        "The framework compliance logic should not be inlined "
        "in engine.py. Phase 2 #5 / C2 extracted it to gates.py. "
        "If you see this error, the framework check was "
        "re-introduced into the engine."
    )
    # And the quality threshold logic
    assert "quality_score < threshold" not in src, (
        "The quality compliance logic should not be inlined in "
        "engine.py. Move it to gates.py."
    )
    # And the per-phase base gate dispatch
    assert "check_after_gathering" not in src, (
        "The evaluate_gate dispatch should not be inlined in "
        "engine.py. Move it to gates.py."
    )
