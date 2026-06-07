"""Harness — eval framework for chat apps (Sprint C, new in C1).

A lightweight testing scaffold that complements pytest.
Use cases:

- **Golden test cases** — a set of (input, expected output)
  pairs the chat app should always get right.
- **LLM-as-judge scoring** — when expected output is fuzzy,
  ask a judge LLM to grade the candidate reply on a 0–1
  scale.
- **Regression detection** — track pass rates over time,
  fail the build if a refactor drops the score below the
  baseline.

Usage::

    from llmwikify.apps.chat.harness import Harness, GoldenCase

    harness = Harness(judge_client=my_judge)
    harness.add(GoldenCase(
        name="factual_recall",
        inputs={"query": "What is X?"},
        expected_contains=["X"],
    ))

    async def run_my_app(inputs):
        return await app.research(inputs["query"])

    results = await harness.run(run_my_app)
    print(results.summary())
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class GoldenCase:
    """A single test case in the harness.

    Either ``expected_contains`` (substring match, any of)
    or ``expected_judge_prompt`` (LLM-as-judge) is required.
    """

    name: str
    inputs: dict
    expected_contains: list[str] = field(default_factory=list)
    expected_judge_prompt: str = ""


@dataclass
class CaseResult:
    """The outcome of a single golden case."""

    name: str
    passed: bool
    details: str = ""


@dataclass
class HarnessReport:
    """Aggregated results from a harness run."""

    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 1.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    def failed(self) -> list[CaseResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        return f"{passed}/{total} passed ({self.pass_rate:.0%})"


class Harness:
    """Lightweight eval harness for chat apps.

    Args:
        judge_client: optional LLM client used as a judge for
            fuzzy matches. If None, ``expected_judge_prompt``
            cases are skipped.
    """

    def __init__(self, judge_client: object | None = None) -> None:
        self.cases: list[GoldenCase] = []
        self.judge_client = judge_client

    def add(self, case: GoldenCase) -> None:
        """Register a golden case."""
        self.cases.append(case)

    async def run(
        self,
        runner: Callable[[dict], Awaitable[str]],
    ) -> HarnessReport:
        """Run every case against ``runner(inputs)`` and return a report.

        ``runner`` should accept the case's ``inputs`` dict and
        return the candidate reply as a string.
        """
        report = HarnessReport()
        for case in self.cases:
            try:
                reply = await runner(case.inputs)
            except Exception as e:
                report.results.append(
                    CaseResult(name=case.name, passed=False, details=f"runner raised: {e}")
                )
                continue

            ok, details = self._grade(case, reply)
            report.results.append(CaseResult(name=case.name, passed=ok, details=details))
        return report

    def _grade(self, case: GoldenCase, reply: str) -> tuple[bool, str]:
        if case.expected_contains:
            missing = [s for s in case.expected_contains if s not in reply]
            if missing:
                return False, f"missing substrings: {missing}"
            return True, f"matched {len(case.expected_contains)} substrings"
        if case.expected_judge_prompt:
            if not self.judge_client:
                return True, "skipped (no judge_client)"
            return asyncio.run(self._judge(case, reply))
        return True, "no expectation set"

    async def _judge(self, case: GoldenCase, reply: str) -> tuple[bool, str]:
        prompt = (
            f"{case.expected_judge_prompt}\n\n"
            f"--- candidate reply ---\n{reply}\n--- end ---\n\n"
            "Reply with PASS or FAIL on the first line, then a one-sentence rationale."
        )
        try:
            verdict = self.judge_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
            )
        except Exception as e:
            return False, f"judge raised: {e}"
        first_line = verdict.splitlines()[0].strip().upper() if verdict else ""
        passed = first_line.startswith("PASS")
        return passed, f"judge: {verdict[:120]}"
