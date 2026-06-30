#!/usr/bin/env python3
"""Unit tests for retry decorator (P6: Layer 1).

Coverage:
  - Default config: 3 attempts, exp backoff
  - max_attempts=1: no retry
  - Success on first try: no retry
  - Success on retry: 1 fail then success
  - All attempts fail: raise DeferError
  - retry_on filter: only specific exceptions trigger retry
  - Backoff timing: sleeps accumulate (mocked)
  - L3 fallback (on_defer hook): invoked on exhaustion
  - on_defer returns None: no fallback, raise DeferError
  - on_defer raises: wrap in DeferError
  - Logging: each attempt logged via run_logger
  - Stacking: @with_logging @with_retry works
  - functools.wraps preserves name
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.paper_understanding.llm_extraction.log_decorator import (
    with_logging,
)
from llmwikify.reproduction.paper_understanding.llm_extraction.retry import (
    DeferError,
    RetryConfig,
    with_retry,
)
from llmwikify.reproduction.paper_understanding.llm_extraction.runlog import RunLogger

# ── Helpers ────────────────────────────────────────────


class CallCounter:
    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.calls = 0
        self.fail_times = fail_times
        self.exc = exc or RuntimeError("transient failure")

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return f"ok-{self.calls}"


# ── Basic behavior ─────────────────────────────────────


class TestBasicRetry:
    def test_success_first_try_no_retry(self):
        counter = CallCounter(fail_times=0)

        @with_retry(stage="s")
        def fn():
            return counter()

        assert fn() == "ok-1"
        assert counter.calls == 1

    def test_success_after_one_retry(self):
        counter = CallCounter(fail_times=1)

        @with_retry(stage="s")
        def fn():
            return counter()

        assert fn() == "ok-2"
        assert counter.calls == 2

    def test_success_after_two_retries(self):
        counter = CallCounter(fail_times=2)

        @with_retry(stage="s")
        def fn():
            return counter()

        assert fn() == "ok-3"
        assert counter.calls == 3

    def test_all_attempts_fail_raises_defer_error(self):
        counter = CallCounter(fail_times=10)

        @with_retry(stage="s", config=RetryConfig(max_attempts=3))
        def fn():
            return counter()

        with pytest.raises(DeferError) as exc_info:
            fn()
        assert "after 3 attempts" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert counter.calls == 3

    def test_max_attempts_one_means_no_retry(self):
        counter = CallCounter(fail_times=10)

        @with_retry(stage="s", config=RetryConfig(max_attempts=1))
        def fn():
            return counter()

        with pytest.raises(DeferError) as exc_info:
            fn()
        assert "after 1 attempts" in str(exc_info.value)
        assert counter.calls == 1


# ── Backoff ───────────────────────────────────────────


class TestBackoff:
    def test_sleeps_between_attempts(self):
        @with_retry(stage="s", config=RetryConfig(
            max_attempts=3, backoff_base=0.01, backoff_jitter=0,
        ))
        def fn():
            raise RuntimeError("fail")

        with patch("llmwikify.reproduction.paper_understanding.llm_extraction.retry.time.sleep") as mock_sleep:
            with pytest.raises(DeferError):
                fn()
            # 2 sleeps for 3 attempts
            assert mock_sleep.call_count == 2
            # Sleep durations: ~0.01 then ~0.02 (factor=2)
            first_sleep = mock_sleep.call_args_list[0][0][0]
            second_sleep = mock_sleep.call_args_list[1][0][0]
            assert first_sleep < second_sleep

    def test_backoff_capped_at_max(self):
        @with_retry(stage="s", config=RetryConfig(
            max_attempts=5,
            backoff_base=10.0,
            backoff_factor=10.0,
            backoff_max=15.0,
            backoff_jitter=0,
        ))
        def fn():
            raise RuntimeError("fail")

        with patch("llmwikify.reproduction.paper_understanding.llm_extraction.retry.time.sleep") as mock_sleep:
            with pytest.raises(DeferError):
                fn()
            for call in mock_sleep.call_args_list:
                sleep_val = call[0][0]
                assert sleep_val <= 15.0

    def test_jitter_adds_randomness(self):
        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=1.0, backoff_jitter=0.5,
        ))
        def fn():
            raise RuntimeError("fail")

        with patch("llmwikify.reproduction.paper_understanding.llm_extraction.retry.time.sleep") as mock_sleep:
            with pytest.raises(DeferError):
                fn()
            # 1 sleep for 2 attempts, base=1.0, jitter adds up to 0.5
            sleep_val = mock_sleep.call_args_list[0][0][0]
            assert 1.0 <= sleep_val <= 1.5


# ── retry_on filter ────────────────────────────────────


class TestRetryOnFilter:
    def test_only_listed_exceptions_trigger_retry(self):
        counter = {"n": 0}

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=3, retry_on=(TimeoutError,),
        ))
        def fn():
            counter["n"] += 1
            if counter["n"] < 2:
                raise ValueError("won't retry this")
            return "ok"

        with pytest.raises(ValueError):
            fn()
        # ValueError NOT in retry_on → no retry, 1 call total
        assert counter["n"] == 1

    def test_retry_on_timeout(self):
        counter = {"n": 0}

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=3, retry_on=(TimeoutError,), backoff_base=0,
        ))
        def fn():
            counter["n"] += 1
            if counter["n"] < 3:
                raise TimeoutError("slow")
            return "ok"

        assert fn() == "ok"
        assert counter["n"] == 3


# ── L3 fallback (on_defer hook) ───────────────────────


class TestL3Fallback:
    def test_fallback_invoked_on_exhaustion(self):
        primary_calls = {"n": 0}

        def on_defer(exc, args, kwargs):
            return (("fallback-arg",), {})

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=0,
            on_defer=on_defer,
        ))
        def fn(x):
            primary_calls["n"] += 1
            if x != "fallback-arg":
                raise RuntimeError("primary fail")
            return f"got-{x}"

        # Fallback succeeds, so no DeferError raised
        result = fn("primary-arg")
        assert result == "got-fallback-arg"
        # 2 primary + 1 fallback = 3 calls
        assert primary_calls["n"] == 3

    def test_fallback_succeeds(self):
        def on_defer(exc, args, kwargs):
            return (("fallback",), {})

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=0,
            on_defer=on_defer,
        ))
        def fn(x):
            if x != "fallback":
                raise RuntimeError("primary")
            return f"fb-{x}"

        assert fn("primary") == "fb-fallback"

    def test_fallback_returns_none_no_fallback(self):
        primary_calls = {"n": 0}

        def on_defer(exc, args, kwargs):
            return None  # no fallback

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=0,
            on_defer=on_defer,
        ))
        def fn():
            primary_calls["n"] += 1
            raise RuntimeError("fail")

        with pytest.raises(DeferError) as exc_info:
            fn()
        assert primary_calls["n"] == 2  # no fallback attempt

    def test_fallback_raises_wraps_in_defer_error(self):
        def on_defer(exc, args, kwargs):
            raise ValueError("hook broke")

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=0,
            on_defer=on_defer,
        ))
        def fn():
            raise RuntimeError("primary fail")

        with pytest.raises(DeferError) as exc_info:
            fn()
        assert "hook broke" in str(exc_info.value)

    def test_fallback_call_also_fails(self):
        primary_calls = {"n": 0}
        fallback_calls = {"n": 0}

        def on_defer(exc, args, kwargs):
            return (("fallback-arg",), {})

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=0,
            on_defer=on_defer,
        ))
        def fn(x):
            if x == "fallback-arg":
                fallback_calls["n"] += 1
            else:
                primary_calls["n"] += 1
            raise RuntimeError(f"fail-{x}")

        with pytest.raises(DeferError) as exc_info:
            fn("primary")
        assert "fallback failed" in str(exc_info.value)
        assert primary_calls["n"] == 2
        assert fallback_calls["n"] == 1


# ── RunLogger integration ─────────────────────────────


class TestLoggingIntegration:
    def test_success_logs_one_llm_call(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")

        @with_retry(stage="s", run_logger=rl)
        def fn():
            return "ok"

        fn()
        events = rl.read_all()
        assert len(events) == 1
        assert events[0]["event"] == "llm_call"
        assert events[0]["detail"]["attempt"] == 1

    def test_retry_logs_each_attempt(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        counter = CallCounter(fail_times=2)

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=3, backoff_base=0,
        ), run_logger=rl)
        def fn():
            return counter()

        fn()
        events = rl.read_all()
        # 2 llm_call (fail) + 1 retry event (between attempts 1-2) +
        # 1 retry event (between attempts 2-3) + 1 llm_call (success)
        assert sum(1 for e in events if e["event"] == "llm_call") == 3
        assert sum(1 for e in events if e["event"] == "retry") == 2

    def test_exhaustion_logs_fail(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        counter = CallCounter(fail_times=10)

        @with_retry(stage="s", config=RetryConfig(
            max_attempts=3, backoff_base=0,
        ), run_logger=rl)
        def fn():
            return counter()

        with pytest.raises(DeferError):
            fn()
        events = rl.read_all()
        # 3 llm_call + 2 retry + 1 fail
        assert sum(1 for e in events if e["event"] == "fail") == 1
        assert "after 3 attempts" in events[-1]["error"]


# ── Stacking: with_logging + with_retry ────────────────


class TestStacking:
    def test_logging_outer_retry_inner(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        counter = CallCounter(fail_times=1)

        @with_logging(stage="s", run_logger=rl)
        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=0,
        ), run_logger=rl)
        def fn():
            return counter()

        result = fn()
        assert result == "ok-2"
        events = rl.read_all()
        # Order: start (logging) → llm_call fail → retry → llm_call success
        # logging catches success → success event
        assert events[0]["event"] == "start"
        # Last event is success (from with_logging)
        assert events[-1]["event"] == "success"

    def test_logging_logs_fail_when_retry_raises(self, tmp_path):
        rl = RunLogger(tmp_path, "p1")
        counter = CallCounter(fail_times=10)

        @with_logging(stage="s", run_logger=rl)
        @with_retry(stage="s", config=RetryConfig(
            max_attempts=2, backoff_base=0,
        ), run_logger=rl)
        def fn():
            return counter()

        with pytest.raises(DeferError):
            fn()
        events = rl.read_all()
        # Last event is fail (from with_logging catching DeferError)
        assert events[-1]["event"] == "fail"
        assert "DeferError" in events[-1]["error"] or "failed" in events[-1]["error"]


# ── Decorator metadata ──────────────────────────────


class TestMetadata:
    def test_preserves_function_name(self):
        @with_retry(stage="s", config=RetryConfig(max_attempts=1, backoff_base=0))
        def my_llm_call():
            return "ok"

        assert my_llm_call.__name__ == "my_llm_call"

    def test_passes_args_and_kwargs(self):
        @with_retry(stage="s", config=RetryConfig(
            max_attempts=1, backoff_base=0,
        ))
        def fn(a, b, *, c=10):
            return a + b + c

        assert fn(1, 2, c=3) == 6


# ── DeferError ──────────────────────────────────────


class TestDeferError:
    def test_carries_original_exception_as_cause(self):
        @with_retry(stage="s", config=RetryConfig(max_attempts=1))
        def fn():
            raise ValueError("original")

        with pytest.raises(DeferError) as exc_info:
            fn()
        assert isinstance(exc_info.value.__cause__, ValueError)
        assert "original" in str(exc_info.value.__cause__)

    def test_message_includes_stage(self):
        @with_retry(stage="my_stage", config=RetryConfig(max_attempts=1))
        def fn():
            raise RuntimeError("oops")

        with pytest.raises(DeferError) as exc_info:
            fn()
        assert "my_stage" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
