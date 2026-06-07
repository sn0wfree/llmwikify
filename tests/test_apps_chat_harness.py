"""Unit tests for the C1 eval framework: Harness, GoldenCase, CaseResult, HarnessReport.

Per the 4-layer refactor design doc §4 (Sprint C, sub-batch C5.4,
target ~15 tests for Harness).

The tests use stub LLM judges and stub runners. The point is
to exercise the harness grading machinery (substring match,
judge dispatch, error handling, aggregation), not the LLM
client.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

import pytest

from llmwikify.apps.chat.harness import (
    CaseResult,
    GoldenCase,
    Harness,
    HarnessReport,
)


# ─── GoldenCase dataclass ──────────────────────────────────────


class TestGoldenCase:
    def test_minimal(self) -> None:
        c = GoldenCase(name="t", inputs={"q": "x"})
        assert c.name == "t"
        assert c.inputs == {"q": "x"}
        assert c.expected_contains == []
        assert c.expected_judge_prompt == ""

    def test_full(self) -> None:
        c = GoldenCase(
            name="t",
            inputs={"q": "x"},
            expected_contains=["42"],
            expected_judge_prompt="is it 42?",
        )
        assert c.expected_contains == ["42"]
        assert c.expected_judge_prompt == "is it 42?"


# ─── CaseResult dataclass ──────────────────────────────────────


class TestCaseResult:
    def test_defaults(self) -> None:
        r = CaseResult(name="t", passed=True)
        assert r.name == "t"
        assert r.passed is True
        assert r.details == ""

    def test_failed_with_details(self) -> None:
        r = CaseResult(name="t", passed=False, details="oops")
        assert r.passed is False
        assert r.details == "oops"


# ─── HarnessReport aggregation ──────────────────────────────────


class TestHarnessReport:
    def test_empty_report_passes(self) -> None:
        r = HarnessReport()
        assert r.pass_rate == 1.0
        assert r.failed() == []
        assert r.summary() == "0/0 passed (100%)"

    def test_all_pass(self) -> None:
        r = HarnessReport(results=[
            CaseResult(name="a", passed=True),
            CaseResult(name="b", passed=True),
        ])
        assert r.pass_rate == 1.0
        assert r.failed() == []
        assert r.summary() == "2/2 passed (100%)"

    def test_partial_pass(self) -> None:
        r = HarnessReport(results=[
            CaseResult(name="a", passed=True),
            CaseResult(name="b", passed=False),
            CaseResult(name="c", passed=True),
            CaseResult(name="d", passed=False),
        ])
        assert r.pass_rate == 0.5
        assert sorted(r.failed(), key=lambda c: c.name) == [
            CaseResult(name="b", passed=False),
            CaseResult(name="d", passed=False),
        ]
        assert r.summary() == "2/4 passed (50%)"

    def test_all_fail(self) -> None:
        r = HarnessReport(results=[
            CaseResult(name="a", passed=False),
            CaseResult(name="b", passed=False),
        ])
        assert r.pass_rate == 0.0
        assert r.summary() == "0/2 passed (0%)"


# ─── Harness.add() and run() ──────────────────────────────────


class TestHarness:
    def test_add_accumulates(self) -> None:
        h = Harness()
        c1 = GoldenCase(name="a", inputs={})
        c2 = GoldenCase(name="b", inputs={})
        h.add(c1)
        h.add(c2)
        assert h.cases == [c1, c2]

    def test_grading_substring_match(self) -> None:
        h = Harness()
        h.add(GoldenCase(
            name="has_number",
            inputs={},
            expected_contains=["42", "the"],
        ))

        async def runner(inputs: dict) -> str:
            return "the answer is 42"

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is True
        assert "matched" in report.results[0].details

    def test_grading_substring_miss(self) -> None:
        h = Harness()
        h.add(GoldenCase(
            name="has_number",
            inputs={},
            expected_contains=["42"],
        ))

        async def runner(inputs: dict) -> str:
            return "no number here"

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is False
        assert "missing substrings: ['42']" in report.results[0].details

    def test_grading_partial_substring_match(self) -> None:
        """All expected substrings must be present (AND semantics)."""
        h = Harness()
        h.add(GoldenCase(
            name="both",
            inputs={},
            expected_contains=["a", "b"],
        ))

        async def runner(inputs: dict) -> str:
            return "only a here"

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is False
        assert "['b']" in report.results[0].details

    def test_grading_judge_skipped_when_no_judge_client(self) -> None:
        h = Harness(judge_client=None)
        h.add(GoldenCase(
            name="fuzzy",
            inputs={},
            expected_judge_prompt="is it good?",
        ))

        async def runner(inputs: dict) -> str:
            return "anything"

        report = asyncio.run(h.run(runner))
        # Without a judge, judge-only cases are skipped (passed=True)
        assert report.results[0].passed is True
        assert "skipped" in report.results[0].details

    def test_grading_judge_pass(self) -> None:
        class StubJudge:
            def __init__(self, verdict: str) -> None:
                self._v = verdict

            def chat(self, messages, **kw):
                return self._v

        h = Harness(judge_client=StubJudge("PASS\nlooks good"))
        h.add(GoldenCase(
            name="fuzzy",
            inputs={},
            expected_judge_prompt="is it good?",
        ))

        async def runner(inputs: dict) -> str:
            return "answer"

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is True
        assert "judge" in report.results[0].details

    def test_grading_judge_fail(self) -> None:
        class StubJudge:
            def chat(self, messages, **kw):
                return "FAIL\nno it isn't"

        h = Harness(judge_client=StubJudge())
        h.add(GoldenCase(
            name="fuzzy",
            inputs={},
            expected_judge_prompt="is it good?",
        ))

        async def runner(inputs: dict) -> str:
            return "answer"

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is False
        assert "judge" in report.results[0].details

    def test_grading_judge_raises(self) -> None:
        class FailingJudge:
            def chat(self, messages, **kw):
                raise RuntimeError("judge down")

        h = Harness(judge_client=FailingJudge())
        h.add(GoldenCase(
            name="fuzzy",
            inputs={},
            expected_judge_prompt="is it good?",
        ))

        async def runner(inputs: dict) -> str:
            return "answer"

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is False
        assert "judge raised" in report.results[0].details

    def test_runner_exception_is_recorded_as_failure(self) -> None:
        h = Harness()
        h.add(GoldenCase(name="explodes", inputs={}))

        async def runner(inputs: dict) -> str:
            raise ValueError("bad input")

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is False
        assert "runner raised" in report.results[0].details
        assert "bad input" in report.results[0].details

    def test_no_expectation_passes(self) -> None:
        """A case with no expected_contains and no expected_judge_prompt passes trivially."""
        h = Harness()
        h.add(GoldenCase(name="noop", inputs={}))

        async def runner(inputs: dict) -> str:
            return "anything"

        report = asyncio.run(h.run(runner))
        assert report.results[0].passed is True
        assert "no expectation set" in report.results[0].details

    def test_run_passes_inputs_to_runner(self) -> None:
        h = Harness()
        h.add(GoldenCase(name="t", inputs={"q": "what is X?"}))

        received: list[dict] = []

        async def runner(inputs: dict) -> str:
            received.append(dict(inputs))
            return "ok"

        report = asyncio.run(h.run(runner))
        assert received == [{"q": "what is X?"}]
        assert report.results[0].passed is True

    def test_run_multiple_cases(self) -> None:
        h = Harness()
        h.add(GoldenCase(name="a", inputs={}, expected_contains=["A"]))
        h.add(GoldenCase(name="b", inputs={}, expected_contains=["B"]))
        h.add(GoldenCase(name="c", inputs={}, expected_contains=["C"]))

        async def runner(inputs: dict) -> str:
            return "A B"  # has A and B but not C

        report = asyncio.run(h.run(runner))
        assert [r.passed for r in report.results] == [True, True, False]
        assert report.pass_rate == pytest.approx(2 / 3)

    def test_summary_format(self) -> None:
        r = HarnessReport(results=[
            CaseResult(name="a", passed=True),
            CaseResult(name="b", passed=False),
            CaseResult(name="c", passed=True),
        ])
        assert r.summary() == "2/3 passed (67%)"
