"""Tests for the LLM client's retry+backoff helper.

Covers the retry behavior added to StreamableLLMClient:
- ReadTimeout is retried with exponential backoff
- ConnectionError is retried
- HTTP 429, 500, 502, 503, 504 are retried
- 4xx (except 429), 401, 403 are NOT retried
- Successful response is returned unchanged
- All retries exhausted → last exception re-raised
- Backoff timing: 1s, 2s, 4s with up to 0.5s jitter
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from llmwikify.foundation.llm.streamable import (
    RetryConfig,
    StreamableLLMClient,
    _compute_backoff,
    _is_retryable_status,
    _post_with_retry_sync,
)


def _make_client() -> StreamableLLMClient:
    return StreamableLLMClient(
        provider="minimax",
        base_url="https://api.minimaxi.com/v1",
        api_key="sk-test",
        model="MiniMax-M2.7",
        request_timeout_seconds=5,
    )


def _ok_response(content: str = "ok") -> MagicMock:
    """Build a mock 200 response with the given message content."""
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b""
    resp.close = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def _err_response(status_code: int, body: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = body
    resp.close = MagicMock()
    return resp


# ─── Helpers ─────────────────────────────────────────────────────


class TestBackoffMath:
    def test_backoff_grows_exponentially(self):
        cfg = RetryConfig()  # default: base=1.0, factor=2.0, jitter=0.5
        b0 = _compute_backoff(0, cfg)
        b1 = _compute_backoff(1, cfg)
        b2 = _compute_backoff(2, cfg)
        # Base is 1.0, factor 2.0 → 1, 2, 4 seconds + 0..0.5 jitter
        assert 1.0 <= b0 < 1.5
        assert 2.0 <= b1 < 2.5
        assert 4.0 <= b2 < 4.5

    def test_retryable_status_codes(self):
        assert _is_retryable_status(429)
        assert _is_retryable_status(500)
        assert _is_retryable_status(502)
        assert _is_retryable_status(503)
        assert _is_retryable_status(504)
        # Not retryable
        assert not _is_retryable_status(200)
        assert not _is_retryable_status(400)
        assert not _is_retryable_status(401)
        assert not _is_retryable_status(403)
        assert not _is_retryable_status(404)


# ─── chat() retry behavior ───────────────────────────────────────


class TestChatRetry:
    def test_chat_succeeds_first_try(self):
        client = _make_client()
        with patch("requests.post", return_value=_ok_response("hi")) as mock_post:
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "hi"
        assert mock_post.call_count == 1

    def test_chat_retries_on_read_timeout(self, monkeypatch):
        """ReadTimeout is retried; success on attempt 2."""
        client = _make_client()
        # Make time.sleep a no-op so the test is fast
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )

        ok = _ok_response("recovered")
        with patch(
            "requests.post",
            side_effect=[
                requests.exceptions.ReadTimeout("first attempt timed out"),
                ok,
            ],
        ) as mock_post:
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "recovered"
        assert mock_post.call_count == 2

    def test_chat_retries_on_connection_error(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        ok = _ok_response("recovered")
        with patch(
            "requests.post",
            side_effect=[
                requests.exceptions.ConnectionError("ECONNRESET"),
                requests.exceptions.ConnectionError("ECONNRESET"),
                ok,
            ],
        ) as mock_post:
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "recovered"
        assert mock_post.call_count == 3

    def test_chat_retries_on_429(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        ok = _ok_response("recovered")
        with patch(
            "requests.post",
            side_effect=[_err_response(429, b"rate limited"), ok],
        ) as mock_post:
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "recovered"
        assert mock_post.call_count == 2

    def test_chat_retries_on_5xx(self, monkeypatch):
        """All 5xx codes are retried: 500, 502, 503, 504."""
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        for status in (500, 502, 503, 504):
            ok = _ok_response(f"recovered from {status}")
            with patch(
                "requests.post",
                side_effect=[_err_response(status, b"transient"), ok],
            ) as mock_post:
                result = client.chat([{"role": "user", "content": "hi"}])
            assert result == f"recovered from {status}"
            assert mock_post.call_count == 2

    def test_chat_does_not_retry_400(self, monkeypatch):
        """4xx (except 429) is a client error — no retry."""
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        with patch(
            "requests.post", return_value=_err_response(400, b"bad request")
        ) as mock_post:
            from llmwikify.foundation.llm.streamable import LLMRequestError

            with pytest.raises(LLMRequestError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
            assert exc_info.value.status_code == 400
        assert mock_post.call_count == 1

    def test_chat_does_not_retry_401(self, monkeypatch):
        """Auth errors are not retryable."""
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        with patch(
            "requests.post", return_value=_err_response(401, b"invalid api key")
        ) as mock_post:
            from llmwikify.foundation.llm.streamable import LLMRequestError

            with pytest.raises(LLMRequestError):
                client.chat([{"role": "user", "content": "hi"}])
        assert mock_post.call_count == 1

    def test_chat_exhausts_retries_on_persistent_read_timeout(self, monkeypatch):
        """After max_retries+1 attempts, the last exception is re-raised."""
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        with patch(
            "requests.post",
            side_effect=requests.exceptions.ReadTimeout("persistent"),
        ) as mock_post:
            with pytest.raises(requests.exceptions.ReadTimeout):
                client.chat([{"role": "user", "content": "hi"}])
        # 1 initial + 3 retries = 4 total attempts
        assert mock_post.call_count == 4

    def test_chat_exhausts_retries_on_persistent_5xx(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        with patch(
            "requests.post", return_value=_err_response(503, b"down")
        ) as mock_post:
            from llmwikify.foundation.llm.streamable import LLMRequestError

            with pytest.raises(LLMRequestError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
            assert exc_info.value.status_code == 503
        assert mock_post.call_count == 4

    def test_chat_retries_sslerror_via_connection_error(self, monkeypatch):
        """SSLError is a subclass of ConnectionError in this requests
        version, so it gets retried. (Cert rotation during a deploy can
        cause transient SSL failures that resolve on retry.)
        """
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        ok = _ok_response("recovered")
        with patch(
            "requests.post",
            side_effect=[
                requests.exceptions.SSLError("cert verify failed"),
                ok,
            ],
        ) as mock_post:
            result = client.chat([{"role": "user", "content": "hi"}])
        assert result == "recovered"
        assert mock_post.call_count == 2


# ─── chat_with_tools() retry behavior ───────────────────────────


class TestChatWithToolsRetry:
    def test_chat_with_tools_retries_on_read_timeout(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b""
        ok.close = MagicMock()
        ok.json.return_value = {
            "choices": [{"message": {"content": "hi", "tool_calls": None}}]
        }
        with patch(
            "requests.post",
            side_effect=[requests.exceptions.ReadTimeout(), ok],
        ) as mock_post:
            result = client.chat_with_tools([{"role": "user", "content": "hi"}])
        # Mock response has no tool_calls field, so result only has "content"
        assert result == {"content": "hi"}
        assert mock_post.call_count == 2


# ─── stream_chat() retry behavior ───────────────────────────────


class TestStreamChatRetry:
    def test_stream_chat_retries_on_read_timeout(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )

        # Successful streaming response
        ok = MagicMock()
        ok.status_code = 200
        ok.content = b""
        ok.close = MagicMock()
        ok.iter_lines.return_value = [
            b'data: {"choices": [{"delta": {"content": "hello"}}]}',
            b"data: [DONE]",
        ]

        with patch(
            "requests.post",
            side_effect=[requests.exceptions.ReadTimeout(), ok],
        ) as mock_post:
            chunks = list(
                client.stream_chat([{"role": "user", "content": "hi"}])
            )
        # Got the content + done
        assert any(c.get("text") == "hello" for c in chunks)
        assert any(c.get("type") == "done" for c in chunks)
        assert mock_post.call_count == 2

    def test_stream_chat_does_not_retry_400(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        bad = MagicMock()
        bad.status_code = 400
        bad.content = b'{"error":{"message":"bad"}}'
        bad.close = MagicMock()
        with patch("requests.post", return_value=bad) as mock_post:
            from llmwikify.foundation.llm.streamable import LLMRequestError

            with pytest.raises(LLMRequestError):
                list(client.stream_chat([{"role": "user", "content": "hi"}]))
        assert mock_post.call_count == 1


# ─── _post_with_retry_sync direct unit tests ────────────────────


class TestPostWithRetryDirect:
    def test_returns_response_on_success(self, monkeypatch):
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        ok = _ok_response()
        with patch("requests.post", return_value=ok) as mock_post:
            resp = _post_with_retry_sync(
                "http://test/x",
                {"Content-Type": "application/json"},
                {"x": 1},
                timeout_seconds=5,
            )
        assert resp is ok
        assert mock_post.call_count == 1

    def test_passes_stream_flag(self):
        ok = _ok_response()
        with patch("requests.post", return_value=ok) as mock_post:
            _post_with_retry_sync(
                "http://test/x",
                {},
                {},
                timeout_seconds=5,
                stream=True,
            )
        # stream=True should be forwarded to requests.post
        assert mock_post.call_count == 1
        kwargs = mock_post.call_args.kwargs
        assert kwargs.get("stream") is True

    def test_raises_after_exhaustion(self, monkeypatch):
        monkeypatch.setattr(
            "llmwikify.foundation.llm.streamable.time.sleep", lambda s: None
        )
        with patch(
            "requests.post",
            side_effect=requests.exceptions.ReadTimeout(),
        ) as mock_post:
            with pytest.raises(requests.exceptions.ReadTimeout):
                _post_with_retry_sync(
                    "http://test/x", {}, {}, timeout_seconds=5
                )
        assert mock_post.call_count == 4  # 1 + 3 retries
