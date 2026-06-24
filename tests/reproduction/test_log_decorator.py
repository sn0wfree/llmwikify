#!/usr/bin/env python3
"""Unit tests for log_decorator (with_logging).

Coverage:
  - Success path: logs start + success, measures latency
  - Failure path: logs start + fail, re-raises exception
  - No run_logger: passes through (no errors, no side effects)
  - Multiple invocations: appends events
  - Preserves return value and args
  - Preserves function name (functools.wraps)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.log_decorator import with_logging
from llmwikify.reproduction.paper_understanding.llm_extraction.runlog import RunLogger, make_run_logger


# ── Success path ──────────────────────────────────────


class TestSuccessPath:
    def test_logs_start_and_success(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def do_work():
            return "ok"

        result = do_work()
        assert result == "ok"
        events = rl.read_all()
        assert len(events) == 2
        assert events[0]["event"] == "start"
        assert events[0]["stage"] == "stage0"
        assert events[1]["event"] == "success"
        assert events[1]["stage"] == "stage0"

    def test_measures_latency(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def slow_work():
            time.sleep(0.05)
            return "ok"

        slow_work()
        events = rl.read_all()
        success = events[-1]
        assert success["latency_ms"] >= 50
        assert success["latency_ms"] < 500  # sanity bound

    def test_preserves_return_value(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def returns_dict():
            return {"a": 1, "b": [1, 2, 3]}

        result = returns_dict()
        assert result == {"a": 1, "b": [1, 2, 3]}

    def test_passes_args_kwargs(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def with_args(a, b, *, c=10):
            return a + b + c

        assert with_args(1, 2, c=3) == 6
        assert with_args(5, 5) == 20


# ── Failure path ──────────────────────────────────────


class TestFailurePath:
    def test_logs_fail_and_reraises(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def boom():
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            boom()
        events = rl.read_all()
        assert events[0]["event"] == "start"
        assert events[1]["event"] == "fail"
        assert events[1]["error"] == "nope"
        assert "nope" not in events[1].get("detail", {}).get("traceback", "")

    def test_records_latency_on_failure(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def slow_boom():
            time.sleep(0.02)
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            slow_boom()
        events = rl.read_all()
        assert events[1]["latency_ms"] >= 20

    def test_preserves_exception_type(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def key_error():
            return {}["missing"]

        with pytest.raises(KeyError):
            key_error()


# ── No run_logger (no-op) ────────────────────────────


class TestNoLogger:
    def test_no_logger_no_side_effects(self, tmp_path):
        """When run_logger=None, decorator still wraps but writes nothing."""

        @with_logging(stage="stage0", run_logger=None)
        def do_work(x):
            return x * 2

        # No exception, returns value
        assert do_work(5) == 10
        # No log file created (we passed tmp_path but it was unused)
        # (RunLogger wasn't even instantiated, so nothing to check)

    def test_no_logger_with_failure(self):
        @with_logging(stage="stage0", run_logger=None)
        def boom():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            boom()


# ── Multiple invocations ─────────────────────────────


class TestMultipleInvocations:
    def test_appends_events(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_logging(stage="stage0", run_logger=rl)
        def repeat():
            return 1

        for _ in range(5):
            repeat()

        events = rl.read_all()
        # 5 invocations × 2 events each (start + success)
        assert len(events) == 10
        assert sum(1 for e in events if e["event"] == "start") == 5
        assert sum(1 for e in events if e["event"] == "success") == 5

    def test_mixed_success_and_failure(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        call_count = {"n": 0}

        @with_logging(stage="stage0", run_logger=rl)
        def sometimes_boom():
            call_count["n"] += 1
            if call_count["n"] % 2 == 0:
                raise ValueError(f"fail #{call_count['n']}")
            return "ok"

        sometimes_boom()
        with pytest.raises(ValueError):
            sometimes_boom()
        sometimes_boom()
        with pytest.raises(ValueError):
            sometimes_boom()

        events = rl.read_all()
        # 4 invocations × 2 events = 8
        assert len(events) == 8
        assert sum(1 for e in events if e["event"] == "success") == 2
        assert sum(1 for e in events if e["event"] == "fail") == 2


# ── Decorator metadata ──────────────────────────────


class TestMetadata:
    def test_preserves_function_name(self):
        @with_logging(stage="stage0", run_logger=None)
        def my_special_function():
            return 1

        assert my_special_function.__name__ == "my_special_function"


# ── Integration with make_run_logger ────────────────


class TestIntegrationWithRunLogger:
    def test_full_flow_via_make_run_logger(self, tmp_path):
        work = tmp_path / "paper1"
        work.mkdir()
        rl = make_run_logger(work)

        @with_logging(stage="track_a", run_logger=rl)
        def fake_extract():
            time.sleep(0.01)
            return {"n": 3}

        result = fake_extract()
        assert result == {"n": 3}

        log = (work / "run_log.jsonl").read_text(encoding="utf-8")
        assert "track_a" in log
        assert "success" in log


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
