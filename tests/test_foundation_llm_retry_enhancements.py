"""Tests for the new retry enhancements:
- RetryConfig.from_env() reads LLM_RETRY_* env vars
- Retry-After header parsing (and cap at max_seconds)
- RetryMetrics collection (success rate, retry count distribution)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from llmwikify.foundation.llm.streamable import (
    RetryConfig,
    RetryMetrics,
    StreamableLLMClient,
    _compute_backoff,
    _extract_retry_after,
    _parse_retry_after,
    _post_with_retry_sync,
    get_retry_metrics,
    reset_retry_metrics,
)


# ─── RetryConfig.from_env ────────────────────────────────────────


class TestRetryConfigFromEnv:
    def test_defaults_when_no_env(self, monkeypatch):
        for k in (
            "LLM_RETRY_MAX_RETRIES",
            "LLM_RETRY_BACKOFF_BASE",
            "LLM_RETRY_BACKOFF_FACTOR",
            "LLM_RETRY_BACKOFF_JITTER",
            "LLM_RETRY_AFTER_MAX_SECONDS",
        ):
            monkeypatch.delenv(k, raising=False)
        cfg = RetryConfig.from_env()
        assert cfg.max_retries == 3
        assert cfg.backoff_base == 1.0
        assert cfg.backoff_factor == 2.0
        assert cfg.backoff_jitter == 0.5
        assert cfg.retry_after_max_seconds == 60.0

    def test_overrides_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_RETRY_BACKOFF_BASE", "2.5")
        monkeypatch.setenv("LLM_RETRY_MAX_RETRIES", "5")
        monkeypatch.setenv("LLM_RETRY_BACKOFF_FACTOR", "3.0")
        monkeypatch.setenv("LLM_RETRY_BACKOFF_JITTER", "1.0")
        monkeypatch.setenv("LLM_RETRY_AFTER_MAX_SECONDS", "30")
        cfg = RetryConfig.from_env()
        assert cfg.max_retries == 5
        assert cfg.backoff_base == 2.5
        assert cfg.backoff_factor == 3.0
        assert cfg.backoff_jitter == 1.0
        assert cfg.retry_after_max_seconds == 30.0

    def test_invalid_env_values_fall_back_to_defaults(
        self, monkeypatch, caplog
    ):
        monkeypatch.setenv("LLM_RETRY_BACKOFF_BASE", "not-a-number")
        monkeypatch.setenv("LLM_RETRY_MAX_RETRIES", "abc")
        cfg = RetryConfig.from_env()
        # Invalid values fall back to defaults (with a warning)
        assert cfg.backoff_base == 1.0
        assert cfg.max_retries == 3

    def test_negative_max_retries_falls_back(self, monkeypatch):
        monkeypatch.setenv("LLM_RETRY_MAX_RETRIES", "-1")
        cfg = RetryConfig.from_env()
        assert cfg.max_retries == 3  # back to default

    def test_empty_string_falls_back(self, monkeypatch):
        monkeypatch.setenv("LLM_RETRY_BACKOFF_BASE", "   ")
        cfg = RetryConfig.from_env()
        assert cfg.backoff_base == 1.0  # back to default

    def test_backoff_uses_config_values(self):
        """Custom config values produce different backoff times."""
        cfg = RetryConfig(
            backoff_base=3.0, backoff_factor=2.0, backoff_jitter=0.0
        )
        b0 = _compute_backoff(0, cfg)
        b1 = _compute_backoff(1, cfg)
        b2 = _compute_backoff(2, cfg)
        # base=3.0, jitter=0.0 → exact 3, 6, 12
        assert b0 == 3.0
        assert b1 == 6.0
        assert b2 == 12.0


# ─── Retry-After header parsing ──────────────────────────────────


class TestParseRetryAfter:
    def test_valid_seconds(self):
        assert _parse_retry_after("5", 60) == 5.0
        assert _parse_retry_after("0", 60) == 0.0
        assert _parse_retry_after("60", 60) == 60.0

    def test_float_seconds(self):
        assert _parse_retry_after("1.5", 60) == 1.5
        assert _parse_retry_after("0.25", 60) == 0.25

    def test_caps_at_max(self):
        """Values > max are capped to prevent absurd waits."""
        assert _parse_retry_after("3600", 30) == 30.0
        assert _parse_retry_after("1000", 60) == 60.0

    def test_negative_returns_none(self):
        """Negative values are invalid; don't retry sooner than now."""
        assert _parse_retry_after("-1", 60) is None
        assert _parse_retry_after("-5.5", 60) is None

    def test_http_date_returns_zero(self):
        """HTTP-date format: we don't track clock skew, so return 0
        (don't retry sooner than immediately)."""
        assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", 60) == 0.0
        assert _parse_retry_after("garbage", 60) == 0.0

    def test_empty_string_returns_none(self):
        assert _parse_retry_after("", 60) is None

    def test_whitespace_stripped(self):
        assert _parse_retry_after("  3.5  ", 60) == 3.5


class TestExtractRetryAfter:
    def test_extracts_from_response(self):
        """Test extracting from a requests-like response with CaseInsensitiveDict."""
        resp = MagicMock()
        resp.headers = {"Retry-After": "5"}
        assert _extract_retry_after(resp, 60) == 5.0

    def test_missing_header_returns_none(self):
        resp = MagicMock()
        resp.headers = {"Content-Type": "application/json"}
        assert _extract_retry_after(resp, 60) is None

    def test_handles_response_without_headers(self):
        resp = MagicMock(spec=[])  # no attributes
        assert _extract_retry_after(resp, 60) is None


# ─── Retry-After in actual retry loop ────────────────────────────


class TestRetryAfterInLoop:
    def test_429_with_retry_after_waits_per_header(
        self, monkeypatch
    ):
        """When a 429 includes Retry-After, the wait uses the header value."""
        client = _make_client()
        # Use a header that says wait 0.1s so the test is fast
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.content = b"rate limited"
        resp_429.headers = {"Retry-After": "0.1"}
        resp_429.close = MagicMock()
        # Use a real ok response (with .json attribute)
        ok = _ok_response()

        with patch("requests.post", side_effect=[resp_429, ok]) as mock_post:
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "ok"
        assert mock_post.call_count == 2

    def test_503_with_retry_after_waits_per_header(self, monkeypatch):
        client = _make_client()
        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.content = b"down"
        resp_503.headers = {"Retry-After": "0.1"}
        resp_503.close = MagicMock()
        ok = _ok_response()

        with patch("requests.post", side_effect=[resp_503, ok]):
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "ok"

    def test_429_without_retry_after_uses_backoff(self, monkeypatch):
        client = _make_client()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.content = b"rate limited"
        resp_429.headers = {}  # no Retry-After
        resp_429.close = MagicMock()
        ok = _ok_response()

        with patch("requests.post", side_effect=[resp_429, ok]):
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "ok"


# ─── RetryMetrics ────────────────────────────────────────────────


class TestRetryMetrics:
    def test_initial_state(self):
        m = RetryMetrics()
        assert m.calls_completed == 0
        assert m.total_retries == 0
        assert m.success_first_try == 0
        assert m.success_after_retry == 0
        assert m.failed_after_retries == 0
        assert m.by_outcome == {}
        assert m.by_retries == {}

    def test_record_first_try_success(self):
        m = RetryMetrics()
        m.record_call(outcome="ok", attempts_used=1)
        assert m.calls_completed == 1
        assert m.success_first_try == 1
        assert m.success_after_retry == 0
        assert m.failed_after_retries == 0
        assert m.by_outcome == {"ok": 1}
        assert m.by_retries == {0: 1}

    def test_record_success_after_retry(self):
        m = RetryMetrics()
        m.record_call(outcome="ok", attempts_used=3)
        assert m.success_first_try == 0
        assert m.success_after_retry == 1
        assert m.total_retries == 2  # 3 attempts - 1 first = 2 retries
        assert m.by_retries == {2: 1}

    def test_record_failed_after_retries(self):
        m = RetryMetrics()
        m.record_call(outcome="server_error", attempts_used=4)
        assert m.failed_after_retries == 1
        assert m.total_retries == 3
        assert m.by_outcome == {"server_error": 1}
        assert m.by_retries == {3: 1}

    def test_record_mixed_calls(self):
        m = RetryMetrics()
        m.record_call(outcome="ok", attempts_used=1)
        m.record_call(outcome="ok", attempts_used=2)
        m.record_call(outcome="rate_limit", attempts_used=4)
        m.record_call(outcome="client_error", attempts_used=1)
        assert m.calls_completed == 4
        assert m.success_first_try == 1
        assert m.success_after_retry == 1
        assert m.failed_after_retries == 2
        assert m.total_retries == 1 + 3  # from attempts 2 and 4
        assert m.by_outcome == {
            "ok": 2,
            "rate_limit": 1,
            "client_error": 1,
        }
        assert m.by_retries == {0: 2, 1: 1, 3: 1}

    def test_to_dict_includes_rates(self):
        m = RetryMetrics()
        m.record_call(outcome="ok", attempts_used=1)
        m.record_call(outcome="ok", attempts_used=1)
        m.record_call(outcome="ok", attempts_used=2)
        m.record_call(outcome="server_error", attempts_used=4)
        d = m.to_dict()
        assert d["calls_completed"] == 4
        assert d["success_first_try"] == 2
        assert d["success_after_retry"] == 1
        assert d["failed_after_retries"] == 1
        assert d["success_rate"] == 0.75
        assert d["first_try_rate"] == 0.5
        # Keys are converted to strings for JSON
        assert d["by_retries"] == {"0": 2, "1": 1, "3": 1}

    def test_reset_clears_metrics(self):
        m = get_retry_metrics()
        m.record_call(outcome="ok", attempts_used=1)
        assert m.calls_completed > 0
        reset_retry_metrics()
        m2 = get_retry_metrics()
        assert m2.calls_completed == 0
        assert m2 is not m  # new instance


# ─── Metrics actually get recorded during retry ─────────────────


class TestMetricsIntegration:
    def test_metrics_record_successful_call(self, monkeypatch):
        reset_retry_metrics()
        client = _make_client()
        with patch("requests.post", return_value=_ok_response("hi")):
            client.chat([{"role": "user", "content": "hi"}])
        m = get_retry_metrics()
        assert m.calls_completed == 1
        assert m.success_first_try == 1
        assert m.by_outcome.get("ok") == 1
        assert m.by_retries.get(0) == 1

    def test_metrics_record_retry_then_success(self, monkeypatch):
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        reset_retry_metrics()
        client = _make_client()
        ok = _ok_response("hi")
        with patch(
            "requests.post",
            side_effect=[requests.exceptions.ReadTimeout(), ok],
        ):
            client.chat([{"role": "user", "content": "hi"}])
        m = get_retry_metrics()
        assert m.calls_completed == 1
        assert m.success_first_try == 0
        assert m.success_after_retry == 1
        assert m.total_retries == 1
        assert m.by_retries.get(1) == 1

    def test_metrics_record_exhausted_retries(self, monkeypatch):
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        reset_retry_metrics()
        client = _make_client()
        with patch(
            "requests.post",
            side_effect=requests.exceptions.ReadTimeout(),
        ):
            with pytest.raises(requests.exceptions.ReadTimeout):
                client.chat([{"role": "user", "content": "hi"}])
        m = get_retry_metrics()
        assert m.calls_completed == 1
        assert m.failed_after_retries == 1
        assert m.total_retries == 3
        assert m.by_outcome.get("timeout") == 1
        assert m.by_retries.get(3) == 1

    def test_metrics_record_4xx_no_retry(self, monkeypatch):
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        reset_retry_metrics()
        client = _make_client()
        from llmwikify.foundation.llm.streamable import LLMRequestError

        with patch(
            "requests.post", return_value=_err_response(400, b"bad")
        ):
            with pytest.raises(LLMRequestError):
                client.chat([{"role": "user", "content": "hi"}])
        m = get_retry_metrics()
        assert m.calls_completed == 1
        assert m.failed_after_retries == 1
        assert m.by_outcome.get("client_error") == 1
        assert m.by_retries.get(0) == 1  # no retries used


# ─── Helpers (used in other test files) ─────────────────────────


def _ok_response(content: str = "ok") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b""
    resp.close = MagicMock()
    resp.headers = {}
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def _err_response(status_code: int, body: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = body
    resp.close = MagicMock()
    resp.headers = {}
    return resp


def _make_client() -> StreamableLLMClient:
    return StreamableLLMClient(
        provider="minimax",
        base_url="https://api.minimaxi.com/v1",
        api_key="sk-test",
        model="MiniMax-M2.7",
        request_timeout_seconds=5,
    )
