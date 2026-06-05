"""Tests for LLM call metrics (commit 7 of the prompt-system refactor).

Covers:
- LLMCallMetrics dataclass has all expected fields
- MetricsCollector.record_llm_call appends to llm_calls
- MetricsCollector.summary() includes LLM call section
- run_prompt records one LLMCallMetrics per invocation
- Fields populated correctly: prompt_name, llm_role, attempt_count,
  latency_ms, chars_in, chars_out, success, json_parsed, error
- attempt_count reflects retries (1 on first-try success, 3 on
  transient-then-success, 1 on non-retriable)
- chars_in includes framework augmentation block (report/review)
- chars_out is len(json.dumps(result)) for JSON, len(str) for raw
- error field populated on failure, empty on success
- ctx.metrics=None → silent skip (no exception)
- ctx.metrics.record_llm_call raising → silent skip (no exception)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from llmwikify.autoresearch import LLMCallMetrics, MetricsCollector
from llmwikify.autoresearch.llm_step import run_prompt


# ─── helpers ──────────────────────────────────────────────────────────


# Patch PromptRegistry.get_messages to return a 2-message list with
# known content sizes. The actual YAMLs are out of scope.
@pytest.fixture(autouse=True)
def _mock_prompt_registry():
    with patch(
        "llmwikify.core.prompt_registry.PromptRegistry.get_messages",
        return_value=[
            {"role": "system", "content": "system prompt"},  # 13 chars
            {"role": "user", "content": "user prompt"},  # 11 chars
        ],
    ):
        yield


def _make_llm(chat_return, side_effect=None):
    """Build a mock LLM with the given return value or side_effect."""
    llm = MagicMock()
    if side_effect is not None:
        llm.chat = MagicMock(side_effect=side_effect)
    else:
        llm.chat = MagicMock(return_value=chat_return)
    llm.provider = "openai"
    return llm


def _make_ctx(metrics=None, default_llm=None, planning_llm=None,
              report_llm=None, config=None):
    """Build a minimal ctx with optional metrics collector."""
    ctx = MagicMock()
    ctx.default_llm = default_llm or _make_llm(json.dumps({"x": 1}))
    ctx.planning_llm = planning_llm or _make_llm(json.dumps({"x": 1}))
    ctx.report_llm = report_llm or _make_llm(json.dumps({"x": 1}))
    ctx.metrics = metrics  # may be None
    ctx.config = config or {
        "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
    }
    return ctx


def _run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── LLMCallMetrics dataclass + MetricsCollector integration ──────────


class TestLLMCallMetricsDataclass:
    def test_has_all_expected_fields(self):
        m = LLMCallMetrics(
            prompt_name="research_clarify",
            llm_role="planning",
            attempt_count=2,
            latency_ms=150,
            chars_in=1000,
            chars_out=200,
            success=True,
            json_parsed=True,
        )
        assert m.prompt_name == "research_clarify"
        assert m.llm_role == "planning"
        assert m.attempt_count == 2
        assert m.latency_ms == 150
        assert m.chars_in == 1000
        assert m.chars_out == 200
        assert m.success is True
        assert m.json_parsed is True
        assert m.fallback_used is False
        assert m.error == ""

    def test_default_field_values(self):
        m = LLMCallMetrics(prompt_name="x", llm_role="default")
        assert m.attempt_count == 1
        assert m.latency_ms == 0
        assert m.chars_in == 0
        assert m.chars_out == 0
        assert m.fallback_used is False
        assert m.success is True
        assert m.json_parsed is True
        assert m.error == ""


class TestMetricsCollectorLLMCallIntegration:
    def test_llm_calls_starts_empty(self):
        mc = MetricsCollector(session_id="s1")
        assert mc.llm_calls == []

    def test_record_llm_call_appends(self):
        mc = MetricsCollector(session_id="s1")
        m1 = LLMCallMetrics(prompt_name="a", llm_role="default")
        m2 = LLMCallMetrics(prompt_name="b", llm_role="planning")
        mc.record_llm_call(m1)
        mc.record_llm_call(m2)
        assert mc.llm_calls == [m1, m2]

    def test_summary_includes_llm_call_section(self):
        mc = MetricsCollector(session_id="s1")
        mc.record_llm_call(LLMCallMetrics(
            prompt_name="research_clarify", llm_role="planning",
            attempt_count=1, latency_ms=100, chars_in=500, chars_out=200,
        ))
        mc.record_llm_call(LLMCallMetrics(
            prompt_name="research_report", llm_role="report",
            attempt_count=3, latency_ms=5000, chars_in=8000, chars_out=4000,
            success=False, error="timeout",
        ))
        s = mc.summary()
        assert "LLM calls: 2 total" in s
        assert "research_clarify" in s
        assert "research_report" in s
        assert "ok" in s  # first call succeeded
        assert "err: timeout" in s  # second call failed
        assert "5000ms, 3 attempt(s), 8000→4000 chars" in s

    def test_summary_omits_llm_section_when_empty(self):
        mc = MetricsCollector(session_id="s1")
        s = mc.summary()
        assert "LLM calls" not in s


# ─── run_prompt records metrics ──────────────────────────────────────


class TestRunPromptRecordsMetrics:
    def test_records_one_metric_per_call(self):
        mc = MetricsCollector(session_id="s1")
        ctx = _make_ctx(metrics=mc)
        _run(run_prompt(ctx, "research_clarify", query="q"))
        assert len(mc.llm_calls) == 1
        m = mc.llm_calls[0]
        assert m.prompt_name == "research_clarify"
        assert m.llm_role == "planning"
        assert m.success is True

    def test_records_attempt_count_1_on_first_try(self):
        mc = MetricsCollector(session_id="s1")
        ctx = _make_ctx(metrics=mc)
        _run(run_prompt(ctx, "research_clarify", query="q"))
        assert mc.llm_calls[0].attempt_count == 1

    def test_records_attempt_count_3_on_transient_retry_success(self):
        mc = MetricsCollector(session_id="s1")
        llm = _make_llm("anything", side_effect=[
            Exception("503 service unavailable"),  # 1st attempt
            Exception("503 service unavailable"),  # 2nd attempt
            json.dumps({"x": 1}),                  # 3rd attempt succeeds
        ])
        ctx = _make_ctx(
            metrics=mc, planning_llm=llm,
            config={"max_retry_attempts": 3, "llm_retry_base_delay": 0.001,
                    "llm_call_timeout_seconds": 30},
        )
        _run(run_prompt(ctx, "research_clarify", query="q"))
        assert mc.llm_calls[0].attempt_count == 3
        assert mc.llm_calls[0].success is True

    def test_records_attempt_count_1_on_non_retriable_error(self):
        mc = MetricsCollector(session_id="s1")
        llm = _make_llm("not valid json {{")  # JSON parse error
        ctx = _make_ctx(
            metrics=mc, planning_llm=llm,
            config={"max_retry_attempts": 3, "llm_call_timeout_seconds": 30},
        )
        with pytest.raises(Exception):
            _run(run_prompt(ctx, "research_clarify", query="q"))
        assert mc.llm_calls[0].attempt_count == 1
        assert mc.llm_calls[0].success is False

    def test_records_attempt_count_3_on_transient_exhausted(self):
        mc = MetricsCollector(session_id="s1")
        llm = _make_llm("anything", side_effect=Exception("503 unavailable"))
        ctx = _make_ctx(
            metrics=mc, planning_llm=llm,
            config={"max_retry_attempts": 3, "llm_retry_base_delay": 0.001,
                    "llm_call_timeout_seconds": 30},
        )
        with pytest.raises(Exception):
            _run(run_prompt(ctx, "research_clarify", query="q"))
        assert mc.llm_calls[0].attempt_count == 3
        assert mc.llm_calls[0].success is False
        assert "503" in mc.llm_calls[0].error

    def test_records_llm_role_per_step(self):
        mc = MetricsCollector(session_id="s1")
        ctx = _make_ctx(metrics=mc)
        # clarify → planning
        _run(run_prompt(ctx, "research_clarify", query="q"))
        # reason → default
        ctx2 = _make_ctx(
            metrics=mc, default_llm=_make_llm(json.dumps({"a": "done"})),
        )
        _run(run_prompt(ctx2, "research_reason", query="q", round=0,
                        max_rounds=5, phase="x", quality_score=0,
                        budget_remaining=1.0, sub_queries_count=0,
                        failed_sq=0, sources_count=0, analyzed_count=0,
                        report_exists=False, review_exists=False,
                        observations_text="(none)"))
        # report → report
        ctx3 = _make_ctx(
            metrics=mc, report_llm=_make_llm("# Report"),
        )
        _run(run_prompt(ctx3, "research_report", query="q",
                        source_contents=[], synthesis={}))

        assert mc.llm_calls[0].llm_role == "planning"
        assert mc.llm_calls[1].llm_role == "default"
        assert mc.llm_calls[2].llm_role == "report"

    def test_records_chars_in(self):
        mc = MetricsCollector(session_id="s1")
        ctx = _make_ctx(metrics=mc)
        _run(run_prompt(ctx, "research_clarify", query="q"))
        # Mocked messages: "system prompt" (13) + "user prompt" (11) = 24
        assert mc.llm_calls[0].chars_in == 24

    def test_records_chars_in_includes_framework_block(self):
        """For report/review with six_step_context, chars_in counts
        the framework block too."""
        mc = MetricsCollector(session_id="s1")
        report_llm = _make_llm("# R")
        ctx = _make_ctx(metrics=mc, report_llm=report_llm)
        six_step_context = {
            "clarification": {"context": "C"},
            "evidence_scores": {"s": 0.9},
            "reasoning_check": {"aggregate_score": 0.8},
            "structure_check": {"aggregate_score": 0.7},
        }
        _run(run_prompt(
            ctx, "research_report",
            six_step_context=six_step_context,
            query="q", source_contents=[], synthesis={},
        ))
        # chars_in should be > 24 (just YAML) because framework block was added
        assert mc.llm_calls[0].chars_in > 24

    def test_records_chars_out_for_json(self):
        mc = MetricsCollector(session_id="s1")
        llm = _make_llm(json.dumps({"x": 1, "y": 2}))
        ctx = _make_ctx(metrics=mc, planning_llm=llm)
        _run(run_prompt(ctx, "research_clarify", query="q"))
        # chars_out = len(json.dumps({"x": 1, "y": 2}, ensure_ascii=False))
        # = len('{"x": 1, "y": 2}') = 16
        assert mc.llm_calls[0].chars_out == len(json.dumps({"x": 1, "y": 2}, ensure_ascii=False))

    def test_records_chars_out_for_markdown(self):
        mc = MetricsCollector(session_id="s1")
        report_llm = _make_llm("# Hello\n\nWorld")
        ctx = _make_ctx(metrics=mc, report_llm=report_llm)
        _run(run_prompt(ctx, "research_report", query="q",
                        source_contents=[], synthesis={}))
        assert mc.llm_calls[0].chars_out == len("# Hello\n\nWorld")

    def test_records_latency_ms(self):
        mc = MetricsCollector(session_id="s1")
        ctx = _make_ctx(metrics=mc)
        _run(run_prompt(ctx, "research_clarify", query="q"))
        # Should be >= 0 (non-negative); 0 is possible for a fast mock call
        assert mc.llm_calls[0].latency_ms >= 0
        assert mc.llm_calls[0].latency_ms < 5000  # well under the timeout

    def test_records_error_message_on_failure(self):
        mc = MetricsCollector(session_id="s1")
        llm = _make_llm("not json {{")
        ctx = _make_ctx(metrics=mc, planning_llm=llm)
        with pytest.raises(Exception):
            _run(run_prompt(ctx, "research_clarify", query="q"))
        m = mc.llm_calls[0]
        assert m.success is False
        assert m.error != ""
        assert "Expecting" in m.error or "json" in m.error.lower()

    def test_records_json_parsed_true_for_json_step(self):
        mc = MetricsCollector(session_id="s1")
        ctx = _make_ctx(metrics=mc)
        _run(run_prompt(ctx, "research_clarify", query="q"))
        assert mc.llm_calls[0].json_parsed is True

    def test_records_json_parsed_false_for_markdown_step(self):
        """report/revise don't parse JSON, so json_parsed should be
        False (or the metric's notion of 'json_parsed' for non-JSON
        steps is False)."""
        mc = MetricsCollector(session_id="s1")
        report_llm = _make_llm("# R")
        ctx = _make_ctx(metrics=mc, report_llm=report_llm)
        _run(run_prompt(ctx, "research_report", query="q",
                        source_contents=[], synthesis={}))
        # For markdown steps, json_parsed is set to False in the
        # success path (it's a no-op field, kept False for clarity).
        assert mc.llm_calls[0].json_parsed is False


# ─── run_prompt is robust to metrics problems ─────────────────────────


class TestRunPromptMetricsRobustness:
    def test_metrics_none_silent_skip(self):
        """If ctx.metrics is None, run_prompt works fine (no exception)."""
        ctx = _make_ctx(metrics=None)
        result = _run(run_prompt(ctx, "research_clarify", query="q"))
        assert result == {"x": 1}

    def test_record_llm_call_raising_silent_skip(self):
        """If metrics.record_llm_call raises, run_prompt still returns."""
        mc = MagicMock()
        mc.record_llm_call = MagicMock(side_effect=RuntimeError("boom"))
        ctx = _make_ctx(metrics=mc)
        # Should not raise despite metrics raising
        result = _run(run_prompt(ctx, "research_clarify", query="q"))
        assert result == {"x": 1}
        # And the metric was attempted
        assert mc.record_llm_call.called

    def test_record_llm_call_raising_on_failure_still_raises_original(self):
        """If LLM fails AND metrics raises, the LLM exception wins
        (we don't swallow LLM errors for metrics problems)."""
        mc = MagicMock()
        mc.record_llm_call = MagicMock(side_effect=RuntimeError("boom"))
        ctx = _make_ctx(
            metrics=mc, planning_llm=_make_llm("not json {{"),
            config={"max_retry_attempts": 1, "llm_call_timeout_seconds": 30},
        )
        with pytest.raises(Exception, match="Expecting"):
            _run(run_prompt(ctx, "research_clarify", query="q"))


# ─── backward-compat: existing tests still pass ───────────────────────


class TestBackwardCompatWithExistingMetrics:
    def test_action_metrics_still_work(self):
        """The legacy action-level metrics path is unchanged."""
        from llmwikify.autoresearch import ActionMetrics
        mc = MetricsCollector(session_id="s1")
        a = ActionMetrics(action="plan", start_time=0.0)
        a.finish()
        mc.add_action(a)
        assert mc.actions == [a]
        assert mc.llm_calls == []  # still empty until record_llm_call is called

    def test_session_metrics_alias_still_works(self):
        """SessionMetrics is an alias for MetricsCollector."""
        from llmwikify.autoresearch import SessionMetrics
        assert SessionMetrics is MetricsCollector


# ─── Submodule constructors accept metrics kwarg ─────────────────────


class TestSubmoduleMetricsKwarg:
    """Each LLM-using submodule (clarifier, report, reviewer, revisor)
    accepts an optional ``metrics`` kwarg in its constructor and
    stores it as an attribute. This lets the engine propagate the
    session-level metrics collector to each LLM call.
    """

    def test_clarifier_accepts_metrics(self):
        from llmwikify.autoresearch.clarifier import ResearchClarifier
        mc = MetricsCollector(session_id="s")
        c = ResearchClarifier(MagicMock(), config={}, metrics=mc)
        assert c.metrics is mc

    def test_clarifier_metrics_defaults_to_none(self):
        from llmwikify.autoresearch.clarifier import ResearchClarifier
        c = ResearchClarifier(MagicMock())
        assert c.metrics is None

    def test_report_accepts_metrics(self):
        from llmwikify.autoresearch.report import ReportGenerator
        mc = MetricsCollector(session_id="s")
        r = ReportGenerator(MagicMock(), MagicMock(), config={}, metrics=mc)
        assert r.metrics is mc

    def test_reviewer_accepts_metrics(self):
        from llmwikify.autoresearch.review import ResearchReviewer
        mc = MetricsCollector(session_id="s")
        rv = ResearchReviewer(MagicMock(), MagicMock(), config={}, metrics=mc)
        assert rv.metrics is mc

    def test_revisor_accepts_metrics(self):
        from llmwikify.autoresearch.review import ResearchRevisor
        mc = MetricsCollector(session_id="s")
        rs = ResearchRevisor(MagicMock(), MagicMock(), config={}, metrics=mc)
        assert rs.metrics is mc

    def test_submodule_metrics_flows_to_run_prompt(self):
        """When a submodule has metrics, run_prompt records into it
        (not the engine's _action_ctx)."""
        from llmwikify.autoresearch.clarifier import ResearchClarifier

        # Submodule's own MetricsCollector
        sub_mc = MetricsCollector(session_id="sub")
        # LLM returns a proper clarification JSON
        c = ResearchClarifier(_make_llm(json.dumps({
            "context": "C", "boundaries": "B", "position": "P",
            "premises": ["p1"], "scope_check": True,
        })),
                              config={"max_retry_attempts": 1,
                                      "llm_call_timeout_seconds": 30},
                              metrics=sub_mc)
        result = _run(c.clarify("q"))
        # Result succeeded (clarify normalizes the response)
        assert result["context"] == "C"
        assert result["scope_check"] is True
        # Submodule's collector got 1 LLM call entry
        assert len(sub_mc.llm_calls) == 1
        assert sub_mc.llm_calls[0].prompt_name == "research_clarify"
