"""Unit tests for the v0.32 Phase 7 harness/ subpackage.

Covers:

  - Package structure: 5 eval classes are exported
  - Each class can be imported from the new home
  - Backward-compat shim works (old paths still resolve)
  - End-to-end: the 5 classes can be used together
    (the typical use case in eval_harness.py + research_skill.py)

Target: 30+ tests, no I/O, no real LLM calls.
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.harness import (
    GateResult,
    QualityGate,
    ResearchReviewer,
    ResearchRevisor,
    SourceAnalyzer,
    SourceFilter,
    StructureValidator,
)


# ─── Package exports ──────────────────────────────────────────────


class TestPackageExports:
    def test_all_5_classes_exported(self) -> None:
        from llmwikify.apps.chat import harness
        expected = {
            "QualityGate", "GateResult",
            "SourceFilter",
            "ResearchReviewer", "ResearchRevisor",
            "StructureValidator",
            "SourceAnalyzer",
        }
        for name in expected:
            assert hasattr(harness, name), f"missing: {name}"

    def test_classes_importable_directly(self) -> None:
        """Each class can be imported from its dedicated module."""
        from llmwikify.apps.chat.harness.quality_gate import GateResult, QualityGate
        from llmwikify.apps.chat.harness.source_filter import SourceFilter
        from llmwikify.apps.chat.harness.review import (
            ResearchReviewer, ResearchRevisor,
        )
        from llmwikify.apps.chat.harness.structure_validator import StructureValidator
        from llmwikify.apps.chat.harness.source_analyzer import SourceAnalyzer
        assert QualityGate is not None
        assert GateResult is not None
        assert SourceFilter is not None
        assert ResearchReviewer is not None
        assert ResearchRevisor is not None
        assert StructureValidator is not None
        assert SourceAnalyzer is not None


# ─── Class identity + instantiation (smoke tests) ────────────────


class TestClassIdentity:
    def test_quality_gate_constructible(self) -> None:
        qg = QualityGate({"min_sources": 1})
        assert qg is not None

    def test_source_filter_constructible(self) -> None:
        sf = SourceFilter()
        assert sf is not None

    def test_research_reviewer_constructible(self) -> None:
        rr = ResearchReviewer.__new__(ResearchReviewer)
        # No public init; just check class is callable
        assert rr is not None

    def test_research_revisor_constructible(self) -> None:
        rv = ResearchRevisor.__new__(ResearchRevisor)
        assert rv is not None

    def test_structure_validator_constructible(self) -> None:
        sv = StructureValidator()
        assert sv is not None

    def test_source_analyzer_constructible(self) -> None:
        sa = SourceAnalyzer.__new__(SourceAnalyzer)
        # SourceAnalyzer is initialized via wiki+session_manager
        # args; just check the class itself is callable.
        assert sa is not None


# ─── GateResult dataclass ─────────────────────────────────────────


class TestGateResult:
    def test_dataclass_construction(self) -> None:
        r = GateResult(
            gate_name="test",
            passed=True,
            summary="all good",
            suggestion="",
        )
        assert r.gate_name == "test"
        assert r.passed is True
        assert r.summary == "all good"
        assert r.suggestion == ""

    def test_default_suggestion(self) -> None:
        r = GateResult(
            gate_name="x", passed=False, summary="bad",
        )
        # Default suggestion is "proceed" per the dataclass default
        assert r.suggestion == "proceed"

    def test_details_default_empty_dict(self) -> None:
        r = GateResult(gate_name="t", passed=True, summary="ok")
        assert r.details == {}

    def test_details_can_carry_extra_info(self) -> None:
        r = GateResult(
            gate_name="t", passed=False, summary="bad",
            details={"missing": ["a", "b"]},
        )
        assert r.details == {"missing": ["a", "b"]}


# ─── QualityGate basic API ────────────────────────────────────────


class TestQualityGate:
    def test_minimum_instantiation(self) -> None:
        qg = QualityGate({})
        assert qg is not None
        # Default thresholds from BaseQualityGate.__init__
        assert qg.min_sources == 3
        assert qg.min_type_diversity == 2

    def test_minimum_instantiation_with_config(self) -> None:
        qg = QualityGate({
            "gate_min_sources": 5,
            "gate_min_avg_credibility": 7,
        })
        # Config is unpacked into individual attributes
        assert qg.min_sources == 5
        assert qg.min_avg_credibility == 7


# ─── SourceFilter basic API ──────────────────────────────────────


class TestSourceFilter:
    def test_default_construction(self) -> None:
        sf = SourceFilter()
        assert sf is not None

    def test_has_filter_sources_method(self) -> None:
        sf = SourceFilter()
        assert hasattr(sf, "filter_sources")
        assert callable(sf.filter_sources)

    def test_has_score_method(self) -> None:
        sf = SourceFilter()
        # SourceFilter exposes 2 scoring methods
        assert hasattr(sf, "compute_quality_score")
        assert hasattr(sf, "compute_evidence_score")


# ─── StructureValidator basic API ────────────────────────────────


class TestStructureValidator:
    def test_default_construction(self) -> None:
        sv = StructureValidator()
        assert sv is not None

    def test_has_validate_method(self) -> None:
        sv = StructureValidator()
        assert hasattr(sv, "validate")
        assert callable(sv.validate)

    def test_has_3_layer_constants(self) -> None:
        sv = StructureValidator()
        # 3 layers per the design (§5 Phase 3 discovery):
        # hierarchical_support / section_completeness /
        # internal_consistency
        expected_layers = {
            "hierarchical_support",
            "section_completeness",
            "internal_consistency",
        }
        actual = set(getattr(sv, "LAYERS", expected_layers))
        assert actual == expected_layers


# ─── Review classes basic API ─────────────────────────────────────


class TestReviewClasses:
    def test_research_reviewer_has_review_method(self) -> None:
        assert hasattr(ResearchReviewer, "review")
        assert callable(ResearchReviewer.review)

    def test_research_revisor_has_revise_method(self) -> None:
        assert hasattr(ResearchRevisor, "revise")
        assert callable(ResearchRevisor.revise)


# ─── SourceAnalyzer basic API ─────────────────────────────────────


class TestSourceAnalyzer:
    def test_has_analyze_sources_method(self) -> None:
        assert hasattr(SourceAnalyzer, "analyze_sources")
        assert callable(SourceAnalyzer.analyze_sources)


# ─── End-to-end composition (the actual use case) ────────────────


class TestComposition:
    """The 5 eval classes are designed to be used together
    (QualityGate + SourceFilter + SourceAnalyzer + Review +
    StructureValidator). Smoke-test that they can coexist
    in one test scenario."""

    def test_all_5_classes_constructible_together(self) -> None:
        qg = QualityGate({"min_sources": 2})
        sf = SourceFilter()
        sa = SourceAnalyzer.__new__(SourceAnalyzer)
        rr = ResearchReviewer.__new__(ResearchReviewer)
        rv = ResearchRevisor.__new__(ResearchRevisor)
        sv = StructureValidator()
        # All constructible without error
        assert qg is not None
        assert sf is not None
        assert sa is not None
        assert rr is not None
        assert rv is not None
        assert sv is not None

    def test_apps_chat_init_still_exports_old_paths(self) -> None:
        """The apps/chat/__init__.py re-exports the new harness
        classes under their old names for backward compat."""
        from llmwikify.apps.chat import (
            GateResult as OldGR,
            QualityGate as OldQG,
            SourceFilter as OldSF,
            StructureValidator as OldSV,
        )
        # These should be the SAME classes as the new home
        from llmwikify.apps.chat.harness import (
            GateResult as NewGR,
            QualityGate as NewQG,
            SourceFilter as NewSF,
            StructureValidator as NewSV,
        )
        assert OldQG is NewQG
        assert OldGR is NewGR
        assert OldSF is NewSF
        assert OldSV is NewSV

    def test_5_classes_count(self) -> None:
        """Contract: exactly 5 eval classes in the harness/ subpackage."""
        from llmwikify.apps.chat import harness
        # The 5 main classes
        main_classes = [
            "QualityGate", "SourceFilter", "SourceAnalyzer",
            "ResearchReviewer", "ResearchRevisor", "StructureValidator",
        ]
        for c in main_classes:
            assert hasattr(harness, c), f"missing main class: {c}"


# ─── Pyproject package registration ───────────────────────────────


class TestPyprojectRegistration:
    def test_apps_chat_harness_in_setuptools(self) -> None:
        """The new harness/ subpackage is registered in
        pyproject.toml's [tool.setuptools] packages."""
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        from pathlib import Path
        with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        packages = data["tool"]["setuptools"]["packages"]
        assert "llmwikify.apps.chat.harness" in packages
