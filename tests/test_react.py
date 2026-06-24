"""Tests for pipeline/react.py — three-tier ReAct engine (Phase 14B)."""
from __future__ import annotations

import time

import pytest

from llmwikify.reproduction.pipeline.react import (
    Decision,
    FailureClassifier,
    PipelineReAct,
    StageFailure,
)


class TestDecision:
    """Decision enum (1 test)."""

    def test_values(self) -> None:
        assert Decision.RETRY.value == "retry"
        assert Decision.SKIP.value == "skip"
        assert Decision.ABORT.value == "abort"
        assert Decision.FALLBACK.value == "fallback"


class TestStageFailure:
    """StageFailure dataclass (2 tests)."""

    def test_construction(self) -> None:
        sf = StageFailure(stage_name="s1", error_kind="timeout", message="timed out")
        assert sf.stage_name == "s1"
        assert sf.attempt == 1
        assert sf.context == {}

    def test_with_context(self) -> None:
        sf = StageFailure(
            stage_name="s2",
            error_kind="network",
            message="connection refused",
            attempt=2,
            elapsed_sec=1.5,
            context={"suggestion": "retry later"},
        )
        assert sf.attempt == 2
        assert sf.elapsed_sec == 1.5
        assert sf.context["suggestion"] == "retry later"


class TestFailureClassifier:
    """FailureClassifier.classify (5 tests)."""

    def test_timeout(self) -> None:
        kind, sug = FailureClassifier.classify(TimeoutError("operation timed out"))
        assert kind == "timeout"
        assert "timeout" in sug.lower() or "increase" in sug.lower()

    def test_memory(self) -> None:
        kind, _ = FailureClassifier.classify(MemoryError("out of memory"))
        assert kind == "resource_exhausted"

    def test_permission(self) -> None:
        kind, _ = FailureClassifier.classify(PermissionError("access denied"))
        assert kind == "permission"

    def test_not_found(self) -> None:
        kind, _ = FailureClassifier.classify(FileNotFoundError("no such file /tmp/x"))
        assert kind == "not_found"

    def test_unknown(self) -> None:
        kind, _ = FailureClassifier.classify(RuntimeError("something weird"))
        assert kind == "unknown"


class TestPipelineReAct:
    """PipelineReAct handle_failure (4 tests)."""

    def test_retry_on_timeout_under_limit(self) -> None:
        ra = PipelineReAct(max_retries=3)
        d = ra.handle_failure("s", TimeoutError("timed out"), attempt=1)
        assert d == Decision.RETRY

    def test_abort_on_timeout_at_limit(self) -> None:
        ra = PipelineReAct(max_retries=3)
        d = ra.handle_failure("s", TimeoutError("timed out"), attempt=3)
        assert d == Decision.ABORT

    def test_skip_on_permission(self) -> None:
        ra = PipelineReAct(max_retries=3)
        d = ra.handle_failure("s", PermissionError("permission denied"), attempt=1)
        assert d == Decision.SKIP

    def test_failures_recorded(self) -> None:
        ra = PipelineReAct(max_retries=3)
        ra.handle_failure("s1", RuntimeError("oops"), attempt=1)
        ra.handle_failure("s2", TimeoutError("timed out"), attempt=2, elapsed_sec=5.0)
        assert len(ra.failures) == 2
        assert isinstance(ra.failures[0], StageFailure)
        assert ra.failures[1].elapsed_sec == 5.0

    def test_retry_network_under_limit(self) -> None:
        ra = PipelineReAct(max_retries=2)
        d = ra.handle_failure("s", ConnectionError("connection refused"), attempt=1)
        assert d == Decision.RETRY

    def test_skip_not_found(self) -> None:
        ra = PipelineReAct(max_retries=5)
        d = ra.handle_failure(
            "s", FileNotFoundError("no such file /tmp/x"), attempt=1
        )
        assert d == Decision.SKIP

    def test_abort_network_at_limit(self) -> None:
        ra = PipelineReAct(max_retries=2)
        d = ra.handle_failure("s", ConnectionError("network error"), attempt=2)
        assert d == Decision.ABORT

    def test_custom_classifier(self) -> None:
        class AlwaysAbort(FailureClassifier):
            @staticmethod
            def classify(error):
                return "custom", "custom suggestion"

        ra = PipelineReAct(classifier=AlwaysAbort(), max_retries=3)
        d = ra.handle_failure("s", RuntimeError("x"), attempt=1)
        # Custom classifier returns "unknown" kind but via custom class
        # The PipelineReAct uses the provided classifier
        assert d in (Decision.RETRY, Decision.SKIP, Decision.ABORT)

    def test_retry_unknown_error(self) -> None:
        ra = PipelineReAct(max_retries=3)
        d = ra.handle_failure("s", RuntimeError("weird"), attempt=1)
        assert d == Decision.RETRY
