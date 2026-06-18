"""Tests for adaptive Pass 2 multi-turn helpers (v2).

Covers:
- _get_signal_context: Option B fallback for old SignalStub
- _supplement_context: a/b/c level slicing
- SignalStub with new fields (context_excerpt, context_start, context_end)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from llmwikify.reproduction.llm_extraction.planner import PlanResult
from llmwikify.reproduction.llm_extraction.track_b import (
    SignalDetail,
    SignalStub,
    _get_signal_context,
    _run_pass2_adaptive,
    _supplement_context,
    estimate_complexity,
    select_pass2_mode,
)

# ── SignalStub new fields ──────────────────────────────────────


class TestSignalStubNewFields:
    """SignalStub v2: context_excerpt, context_start, context_end."""

    def test_default_values(self):
        s = SignalStub(index=1, name="Alpha#1", formula_brief="rank(x)")
        assert s.context_excerpt == ""
        assert s.context_start == 0
        assert s.context_end == 0

    def test_with_context(self):
        s = SignalStub(
            index=1,
            name="Alpha#1",
            formula_brief="rank(x)",
            context_excerpt="some context",
            context_start=100,
            context_end=200,
        )
        assert s.context_excerpt == "some context"
        assert s.context_start == 100
        assert s.context_end == 200

    def test_to_dict_includes_new_fields(self):
        s = SignalStub(
            index=5, name="X", formula_brief="f",
            context_excerpt="ctx", context_start=10, context_end=20,
        )
        d = s.to_dict()
        assert d["context_excerpt"] == "ctx"
        assert d["context_start"] == 10
        assert d["context_end"] == 20

    def test_backward_compat_construction(self):
        """Old code can construct SignalStub without new fields."""
        s = SignalStub(index=1, name="X", formula_brief="f")
        # Should not raise
        assert s.context_excerpt == ""


# ── _get_signal_context ────────────────────────────────────────


class TestGetSignalContext:
    """Option B fallback: new SignalStub uses context_excerpt, old uses paper slice."""

    def test_uses_context_excerpt_when_present(self):
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_excerpt="This is the relevant context. " * 20,  # > 50 chars
        )
        result = _get_signal_context(s, "any full paper text here")
        assert result.startswith("This is the relevant context.")

    def test_uses_context_excerpt_even_if_paper_is_different(self):
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_excerpt="real context from paper " * 10,  # > 50 chars
        )
        result = _get_signal_context(s, "completely different paper content")
        assert result.startswith("real context from paper")

    def test_fallback_to_paper_slice_when_empty(self):
        s = SignalStub(index=3, name="X", formula_brief="f", context_excerpt="")
        paper = "A" * 20000  # 20k chars
        result = _get_signal_context(s, paper)
        # index=3 → start = 2*5000 = 10000, end = 15000
        assert result == "A" * 5000
        assert len(result) == 5000

    def test_fallback_to_paper_slice_when_too_short(self):
        """context_excerpt < 50 chars → fallback."""
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_excerpt="short",  # < 50
        )
        paper = "B" * 20000
        result = _get_signal_context(s, paper)
        # Fallback: index=1 → start=0, end=5000
        assert result == "B" * 5000

    def test_fallback_handles_short_paper(self):
        s = SignalStub(index=10, name="X", formula_brief="f", context_excerpt="")
        paper = "C" * 1000  # shorter than expected
        result = _get_signal_context(s, paper)
        # start=9*5000=45000, paper only 1000 → clamp
        # start = max(0, 1000 - 5000) = 0
        # end = min(1000, 45000+5000) = 1000
        assert result == "C" * 1000

    def test_long_context_excerpt_preserved(self):
        long_ctx = "X" * 5000
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_excerpt=long_ctx,
        )
        result = _get_signal_context(s, "paper")
        assert result == long_ctx


# ── _supplement_context (a/b/c levels) ──────────────────────────


PAPER_TEXT = "".join(chr(65 + (i % 26)) for i in range(50000))  # 50k chars


class TestSupplementContext:
    """Level a/b/c context slicing."""

    def test_level_a_paragraph(self):
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_start=1000,
        )
        result = _supplement_context(
            s, {"level": "a", "reason": "test"}, PAPER_TEXT,
        )
        # Level a: 2000 chars from context_start
        assert len(result) == 2000
        assert result == PAPER_TEXT[1000:3000]

    def test_level_b_section(self):
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_start=2000,
        )
        result = _supplement_context(
            s, {"level": "b", "reason": "test"}, PAPER_TEXT,
        )
        # Level b: ~7000 chars, anchored at context_start - 1000
        assert len(result) == 7000
        assert result == PAPER_TEXT[1000:8000]

    def test_level_c_full_paper(self):
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_start=5000,
        )
        result = _supplement_context(
            s, {"level": "c", "reason": "test"}, PAPER_TEXT,
        )
        assert result == PAPER_TEXT

    def test_level_a_handles_short_paper(self):
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_start=48000,  # near end
        )
        result = _supplement_context(
            s, {"level": "a", "reason": "test"}, PAPER_TEXT,
        )
        # 48000 to 50000 = 2000 chars
        assert result == PAPER_TEXT[48000:50000]
        assert len(result) == 2000

    def test_level_a_with_no_context_start(self):
        """Old SignalStub with context_start=0."""
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_start=0, context_end=0,
        )
        result = _supplement_context(
            s, {"level": "a", "reason": "test"}, PAPER_TEXT,
        )
        assert result == PAPER_TEXT[0:2000]

    def test_default_level_is_a(self):
        """Missing 'level' field → default to a."""
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_start=3000,
        )
        result = _supplement_context(
            s, {"reason": "no level specified"}, PAPER_TEXT,
        )
        # Default a: 2000 chars
        assert len(result) == 2000
        assert result == PAPER_TEXT[3000:5000]

    def test_unknown_level_falls_back_to_a(self):
        s = SignalStub(
            index=1, name="X", formula_brief="f",
            context_start=1000,
        )
        result = _supplement_context(
            s, {"level": "z", "reason": "invalid"}, PAPER_TEXT,
        )
        # Falls back to level a
        assert len(result) == 2000
        assert result == PAPER_TEXT[1000:3000]


# ── Adaptive multi-turn (mocked LLM) ───────────────────────────


class TestAdaptiveMultiTurn:
    """Test _run_pass2_adaptive with mocked LLM client."""

    def _make_plan(self) -> PlanResult:
        return PlanResult(
            paper_id="test", schema_choice="factor",
            n_signals_estimate=3, confidence=0.9,
            token_budget={"track_b_pass2_per_factor": 5500},
            success=True,
        )

    def _make_stubs(self, n=3) -> list[SignalStub]:
        return [
            SignalStub(
                index=i + 1, name=f"Alpha#{i+1}", formula_brief=f"f{i+1}(x)",
                context_excerpt="x" * 1000,  # > 200 chars
            )
            for i in range(n)
        ]

    def test_completes_batch_with_sufficient_context(self):
        """All signals complete in 1 round (no need_more_context)."""
        client = MagicMock()
        client.achat = AsyncMock(return_value=json.dumps({
            "factors": [
                {
                    "name": "Alpha#1", "description": "d1",
                    "l1": {"definition": "def1", "formula": "f1(x)"},
                    "l2": {}, "l3": {}, "l4": {"hypotheses": []},
                    "need_more_context": None,
                },
                {
                    "name": "Alpha#2", "description": "d2",
                    "l1": {"definition": "def2", "formula": "f2(x)"},
                    "l2": {}, "l3": {}, "l4": {"hypotheses": []},
                    "need_more_context": None,
                },
                {
                    "name": "Alpha#3", "description": "d3",
                    "l1": {"definition": "def3", "formula": "f3(x)"},
                    "l2": {}, "l3": {}, "l4": {"hypotheses": []},
                    "need_more_context": None,
                },
            ]
        }))
        stubs = self._make_stubs(3)
        details, latency = asyncio.run(
            _run_pass2_adaptive(
                client, self._make_plan(), "test", stubs, "x" * 1000,
            )
        )
        assert len(details) == 3
        assert all(d.success for d in details)
        assert client.achat.await_count == 1

    def test_handles_need_more_context_with_supplement(self):
        """Signal that needs more context gets a supplement, then completes."""
        # Round 1: signal 1 needs more, others complete
        # Round 2 (after supplement): signal 1 completes
        client = MagicMock()
        client.achat = AsyncMock(side_effect=[
            json.dumps({
                "factors": [
                    {
                        "name": "Alpha#1", "description": "needs more",
                        "l1": None, "l2": None, "l3": None, "l4": None,
                        "need_more_context": {
                            "level": "a", "reason": "missing params",
                        },
                    },
                    {
                        "name": "Alpha#2", "description": "d2",
                        "l1": {"definition": "def2"}, "l2": {}, "l3": {}, "l4": {},
                        "need_more_context": None,
                    },
                    {
                        "name": "Alpha#3", "description": "d3",
                        "l1": {"definition": "def3"}, "l2": {}, "l3": {}, "l4": {},
                        "need_more_context": None,
                    },
                ]
            }),
            # Round 2: after supplement, Alpha#1 completes
            json.dumps({
                "factors": [
                    {
                        "name": "Alpha#1", "description": "d1 now complete",
                        "l1": {"definition": "def1 with params"},
                        "l2": {}, "l3": {}, "l4": {},
                        "need_more_context": None,
                    },
                ]
            }),
        ])
        stubs = self._make_stubs(3)
        details, latency = asyncio.run(
            _run_pass2_adaptive(
                client, self._make_plan(), "test", stubs, "x" * 1000,
            )
        )
        assert len(details) == 3
        assert all(d.success for d in details)
        assert client.achat.await_count == 2  # 1 initial + 1 supplement

    def test_max_supplements_exceeded_marks_failed(self):
        """After 5 supplements without success, mark as failed."""
        client = MagicMock()
        # All responses say need_more_context
        always_need_more = json.dumps({
            "factors": [
                {
                    "name": "Alpha#1",
                    "l1": None, "l2": None, "l3": None, "l4": None,
                    "need_more_context": {"level": "a", "reason": "still missing"},
                },
            ]
        })
        client.achat = AsyncMock(return_value=always_need_more)
        stubs = [self._make_stubs(1)[0]]  # 1 signal
        details, latency = asyncio.run(
            _run_pass2_adaptive(
                client, self._make_plan(), "test", stubs, "x" * 1000,
            )
        )
        # Should exhaust 5 supplements then mark failed
        assert len(details) == 1
        assert details[0].success is False
        assert details[0].error == "max_supplements_exceeded"

    def test_json_parse_failure_continues_to_next_round(self):
        """If LLM returns unparseable JSON, continue trying."""
        client = MagicMock()
        client.achat = AsyncMock(side_effect=[
            "not valid json",  # Round 1: parse fail
            json.dumps({
                "factors": [
                    {
                        "name": "Alpha#1", "description": "d1",
                        "l1": {"definition": "def1"}, "l2": {}, "l3": {}, "l4": {},
                        "need_more_context": None,
                    },
                ]
            }),
        ])
        stubs = self._make_stubs(1)
        details, latency = asyncio.run(
            _run_pass2_adaptive(
                client, self._make_plan(), "test", stubs, "x" * 1000,
            )
        )
        assert len(details) == 1
        assert details[0].success is True
        assert client.achat.await_count == 2  # 1 failed + 1 success

    def test_legacy_single_factor_format_supported(self):
        """Legacy `{"factor": {...}}` format still works."""
        client = MagicMock()
        client.achat = AsyncMock(return_value=json.dumps({
            "factor": {
                "name": "Alpha#1", "description": "d1",
                "l1": {"definition": "def1"}, "l2": {}, "l3": {}, "l4": {},
            }
        }))
        stubs = self._make_stubs(1)
        details, latency = asyncio.run(
            _run_pass2_adaptive(
                client, self._make_plan(), "test", stubs, "x" * 1000,
            )
        )
        assert len(details) == 1
        assert details[0].success is True
        assert details[0].l1.get("definition") == "def1"

    def test_resume_skips_existing_details(self):
        """Resume mode: skip signals already in existing_details."""
        client = MagicMock()
        client.achat = AsyncMock(return_value=json.dumps({
            "factors": [
                {
                    "name": "Alpha#3", "description": "d3",
                    "l1": {"definition": "def3"}, "l2": {}, "l3": {}, "l4": {},
                    "need_more_context": None,
                },
            ]
        }))
        existing = [
            SignalDetail(
                name="Alpha#1", description="d1",
                l1={"definition": "def1"}, success=True,
            ),
            SignalDetail(
                name="Alpha#2", description="d2",
                l1={"definition": "def2"}, success=True,
            ),
        ]
        stubs = self._make_stubs(3)
        details, latency = asyncio.run(
            _run_pass2_adaptive(
                client, self._make_plan(), "test", stubs, "x" * 1000,
                existing_details=existing,
            )
        )
        # 2 existing + 1 new = 3 total
        assert len(details) == 3
        assert client.achat.await_count == 1  # Only processed Alpha#3

    def test_history_trimmed_after_max_messages(self):
        """Test that messages list is trimmed when exceeding max_history_messages.

        This is an indirect test - we run 25 rounds of need_more_context
        (max 5 supplements per signal) and verify it doesn't crash from
        message accumulation.
        """
        client = MagicMock()
        # Always return need_more_context to force many rounds
        always_need_more = json.dumps({
            "factors": [
                {
                    "name": "Alpha#1",
                    "l1": None, "l2": None, "l3": None, "l4": None,
                    "need_more_context": {"level": "a", "reason": "need more"},
                },
            ]
        })
        client.achat = AsyncMock(return_value=always_need_more)
        stubs = [self._make_stubs(1)[0]]
        # Should not raise; max_supplements=5 will eventually mark failed
        details, latency = asyncio.run(
            _run_pass2_adaptive(
                client, self._make_plan(), "test", stubs, "x" * 1000,
            )
        )
        # After 5 supplements, marked as failed
        assert len(details) == 1
        assert details[0].success is False
        assert details[0].error == "max_supplements_exceeded"
        # Should have made 5 LLM calls (one per supplement before failure)
        assert 1 <= client.achat.await_count <= 6


# ── Helper: _unwrap_factors ─────────────────────────────────────


class TestUnwrapFactors:
    """Test JSON response unwrapping."""

    def test_list_format(self):
        from llmwikify.reproduction.llm_extraction.track_b import _unwrap_factors
        result = _unwrap_factors([{"name": "A"}, {"name": "B"}])
        assert result == [{"name": "A"}, {"name": "B"}]

    def test_factors_key(self):
        from llmwikify.reproduction.llm_extraction.track_b import _unwrap_factors
        result = _unwrap_factors({"factors": [{"name": "A"}]})
        assert result == [{"name": "A"}]

    def test_legacy_factor_key(self):
        from llmwikify.reproduction.llm_extraction.track_b import _unwrap_factors
        result = _unwrap_factors({"factor": {"name": "A"}})
        assert result == [{"name": "A"}]

    def test_invalid_input(self):
        from llmwikify.reproduction.llm_extraction.track_b import _unwrap_factors
        assert _unwrap_factors(None) is None
        assert _unwrap_factors("not a dict") is None
        assert _unwrap_factors({"random": "key"}) is None


# ── Helper: _build_signal_detail ───────────────────────────────


class TestBuildSignalDetail:
    """Test _build_signal_detail with new and legacy schemas."""

    def test_new_schema(self):
        from llmwikify.reproduction.llm_extraction.track_b import _build_signal_detail
        stub = SignalStub(index=1, name="X", formula_brief="f")
        factor = {
            "name": "X", "description": "d",
            "l1": {"a": 1}, "l2": {"b": 2}, "l3": {"c": 3}, "l4": {"d": 4},
        }
        detail = _build_signal_detail(stub, factor, 1000)
        assert detail.success is True
        assert detail.l1 == {"a": 1}
        assert detail.l2 == {"b": 2}
        assert detail.latency_ms == 1000

    def test_invalid_factor(self):
        from llmwikify.reproduction.llm_extraction.track_b import _build_signal_detail
        stub = SignalStub(index=1, name="X", formula_brief="f")
        detail = _build_signal_detail(stub, "not a dict", 500)
        assert detail.success is False
        assert detail.error == "invalid_factor_format"

    def test_missing_l1_returns_empty_dict(self):
        from llmwikify.reproduction.llm_extraction.track_b import _build_signal_detail
        stub = SignalStub(index=1, name="X", formula_brief="f")
        factor = {"name": "X", "description": "d"}
        detail = _build_signal_detail(stub, factor, 0)
        assert detail.success is True
        assert detail.l1 == {}
        assert detail.l2 == {}


# ── Complexity estimation (v3.0) ──────────────────────────────


class TestEstimateComplexity:
    """Test complexity estimation for smart mode selection."""

    def test_empty_stubs_returns_parallel(self):
        result = estimate_complexity([])
        assert result["recommendation"] == "parallel"
        assert result["signal_count"] == 0

    def test_simple_paper_recommends_adaptive(self):
        """Few signals, short formulas, adequate context → adaptive."""
        stubs = [
            SignalStub(
                index=i + 1, name=f"S{i+1}", formula_brief="rank(close)",
                context_excerpt="x" * 2500,  # 2500 chars (>= 2000)
            )
            for i in range(50)
        ]
        result = estimate_complexity(stubs)
        assert result["signal_count"] == 50
        assert result["avg_formula_len"] < 80
        assert result["avg_context_len"] >= 2000
        assert result["recommendation"] == "adaptive"

    def test_too_few_signals_recommends_parallel(self):
        """< ADAPTIVE_MIN_SIGNALS → parallel (less overhead)."""
        stubs = [
            SignalStub(
                index=1, name="S1", formula_brief="rank(close)",
                context_excerpt="x" * 2500,
            )
        ]
        result = estimate_complexity(stubs)
        assert result["recommendation"] == "parallel"
        assert any("overhead" in r for r in result["reasons"])

    def test_too_many_signals_recommends_parallel(self):
        """> ADAPTIVE_MAX_SIGNALS → parallel (multi-turn too slow)."""
        stubs = [
            SignalStub(
                index=i + 1, name=f"S{i+1}", formula_brief="rank(close)",
                context_excerpt="x" * 2500,
            )
            for i in range(250)
        ]
        result = estimate_complexity(stubs)
        assert result["signal_count"] == 250
        assert result["recommendation"] == "parallel"
        assert any("too slow" in r for r in result["reasons"])

    def test_long_formulas_recommends_parallel(self):
        """Avg formula > 80 chars → complex → parallel."""
        stubs = [
            SignalStub(
                index=i + 1, name=f"S{i+1}",
                formula_brief="rank(" + "x" * 100,  # 105 chars
                context_excerpt="x" * 2500,
            )
            for i in range(50)
        ]
        result = estimate_complexity(stubs)
        assert result["avg_formula_len"] > 80
        assert result["recommendation"] == "parallel"
        assert any("formula" in r for r in result["reasons"])

    def test_short_context_recommends_parallel(self):
        """Avg context < 2000 chars → LLM will need many supplements."""
        stubs = [
            SignalStub(
                index=i + 1, name=f"S{i+1}", formula_brief="rank(close)",
                context_excerpt="x" * 500,  # only 500 chars
            )
            for i in range(50)
        ]
        result = estimate_complexity(stubs)
        assert result["avg_context_len"] < 2000
        assert result["recommendation"] == "parallel"
        assert any("context" in r for r in result["reasons"])

    def test_complexity_score_increases_with_complexity(self):
        """Score reflects complexity level."""
        simple = [
            SignalStub(
                index=1, name="S1", formula_brief="rank(x)",
                context_excerpt="x" * 2500,
            )
        ]
        complex_stubs = [
            SignalStub(
                index=1, name="S1",
                formula_brief="rank(" + "x" * 100,
                context_excerpt="x" * 500,
            )
        ]
        simple_result = estimate_complexity(simple)
        complex_result = estimate_complexity(complex_stubs)
        # Complex case should have higher score (or at least as high)
        assert complex_result["complexity_score"] >= simple_result["complexity_score"]


class TestSelectPass2Mode:
    """Test mode selection logic."""

    def test_auto_selects_parallel_for_simple_cases(self):
        """Few signals → auto selects parallel."""
        stubs = [
            SignalStub(
                index=1, name="S1", formula_brief="rank(close)",
                context_excerpt="x" * 2500,
            )
        ]
        mode = select_pass2_mode(stubs)
        assert mode == "parallel"

    def test_auto_selects_adaptive_for_good_fit(self):
        """Mid-size, simple formulas, good context → adaptive."""
        stubs = [
            SignalStub(
                index=i + 1, name=f"S{i+1}", formula_brief="rank(close)",
                context_excerpt="x" * 2500,
            )
            for i in range(50)
        ]
        mode = select_pass2_mode(stubs)
        assert mode == "adaptive"

    def test_empty_stubs_returns_parallel(self):
        mode = select_pass2_mode([])
        assert mode == "parallel"
