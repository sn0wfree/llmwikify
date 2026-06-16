"""Tests for LLM request validation and 4xx error handling.

Regression coverage for the "400 Bad Request with no body shown"
problem: when a chat completion failed, users saw only
``Client error '400 Bad Request' for url '...'`` and had no way to
know *why* (e.g. ``invalid params, messages is empty (2013)``).

The fix:

  1. ``_validate_request`` rejects the most common client-side
     mistakes *before* they cost a network round-trip:
       - empty ``messages``
       - ``top_p`` outside (0, 1]
       - ``temperature`` outside [0, 2]
  2. On a 4xx response, the LLM client raises ``LLMRequestError``
     carrying the provider's body so callers can show a useful
     diagnostic in logs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llmwikify.foundation.llm.streamable import (
    LLMRequestError,
    StreamableLLMClient,
    _format_http_error,
    _validate_request,
)


def _make_client() -> StreamableLLMClient:
    """Build a client without hitting the network for construction."""
    return StreamableLLMClient(
        provider="minimax",
        base_url="https://api.minimaxi.com/v1",
        api_key="sk-test",
        model="MiniMax-M2.7",
    )


class TestValidateRequest:
    def test_empty_messages_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate_request([])

    def test_none_messages_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            _validate_request(None)

    def test_valid_messages_passes(self):
        _validate_request([{"role": "user", "content": "hi"}])

    def test_top_p_too_high(self):
        with pytest.raises(ValueError, match="top_p must be"):
            _validate_request(
                [{"role": "user", "content": "hi"}],
                {"top_p": 1.5},
            )

    def test_top_p_zero_rejected(self):
        """OpenAI-compatible range is (0, 1] — 0 is not allowed."""
        with pytest.raises(ValueError, match="top_p must be"):
            _validate_request(
                [{"role": "user", "content": "hi"}],
                {"top_p": 0.0},
            )

    def test_top_p_one_accepted(self):
        _validate_request(
            [{"role": "user", "content": "hi"}],
            {"top_p": 1.0},
        )

    def test_top_p_non_numeric_rejected(self):
        with pytest.raises(ValueError, match="top_p must be"):
            _validate_request(
                [{"role": "user", "content": "hi"}],
                {"top_p": "high"},
            )

    def test_temperature_too_high(self):
        with pytest.raises(ValueError, match="temperature must be"):
            _validate_request(
                [{"role": "user", "content": "hi"}],
                {"temperature": 2.5},
            )

    def test_temperature_zero_accepted(self):
        _validate_request(
            [{"role": "user", "content": "hi"}],
            {"temperature": 0.0},
        )


class TestFormatHttpError:
    def test_extracts_openai_error_message(self):
        """OpenAI-shaped body: {"error": {"message": "..."}}."""
        err = _format_http_error(
            400,
            "https://api.test/v1/chat/completions",
            b'{"error":{"message":"invalid params, messages is empty (2013)"}}',
        )
        assert err.status_code == 400
        assert "invalid params, messages is empty" in str(err)
        assert "(2013)" in str(err)

    def test_extracts_string_error(self):
        """Body shaped as {"error": "plain string"}."""
        err = _format_http_error(
            401,
            "https://api.test/v1/chat/completions",
            b'{"error":"invalid api key"}',
        )
        assert err.status_code == 401
        assert "invalid api key" in str(err)

    def test_handles_non_json_body(self):
        """Body that isn't JSON (e.g. HTML 502 page) is passed through verbatim."""
        err = _format_http_error(
            502,
            "https://api.test/v1/chat/completions",
            b"<html>Bad Gateway</html>",
        )
        assert err.status_code == 502
        assert "Bad Gateway" in str(err)

    def test_handles_empty_body(self):
        err = _format_http_error(500, "https://api.test", b"")
        assert err.status_code == 500
        assert "https://api.test" in str(err)

    def test_truncates_long_body(self):
        """500+ char bodies are truncated to keep logs readable."""
        long_body = b'{"error":{"message":"' + b"x" * 1000 + b'"}}'
        err = _format_http_error(400, "https://api.test", long_body)
        assert err.status_code == 400
        # The full 1000-char body shouldn't be in the message
        assert "x" * 1000 not in str(err)
        # But at least some of it should be
        assert "x" in str(err)


class TestChatMethodErrors:
    """Verify that chat() raises LLMRequestError with the body on 4xx."""

    def test_chat_raises_with_body_on_400(self):
        client = _make_client()
        body = b'{"error":{"message":"invalid params, messages is empty (2013)"}}'
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.content = body

        with patch("httpx.Client.post", return_value=mock_resp):
            with pytest.raises(LLMRequestError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
            assert exc_info.value.status_code == 400
            assert "messages is empty" in str(exc_info.value)

    def test_chat_raises_with_body_on_401(self):
        client = _make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.content = b'{"error":{"message":"invalid api key"}}'

        with patch("httpx.Client.post", return_value=mock_resp):
            with pytest.raises(LLMRequestError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
            assert exc_info.value.status_code == 401
            assert "invalid api key" in str(exc_info.value)

    def test_chat_rejects_empty_messages_before_request(self):
        """Empty messages raise ValueError, not a network call."""
        client = _make_client()
        with patch("httpx.Client.post") as mock_post:
            with pytest.raises(ValueError, match="non-empty"):
                client.chat([])
            mock_post.assert_not_called()

    def test_chat_rejects_invalid_top_p_before_request(self):
        client = _make_client()
        with patch("httpx.Client.post") as mock_post:
            with pytest.raises(ValueError, match="top_p"):
                client.chat(
                    [{"role": "user", "content": "hi"}],
                    top_p=1.5,
                )
            mock_post.assert_not_called()


class TestStreamMethodErrors:
    """stream_chat and astream_chat must also raise with the body on 4xx."""

    def test_stream_chat_raises_on_400(self):
        client = _make_client()
        body = b'{"error":{"message":"invalid params, top_p (2013)"}}'
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.read.return_value = body
        mock_resp.close = MagicMock()

        # stream_chat uses httpx.Client.stream() context manager
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=mock_resp)
        stream_ctx.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client.stream", return_value=stream_ctx):
            with pytest.raises(LLMRequestError) as exc_info:
                list(client.stream_chat([{"role": "user", "content": "hi"}]))
            assert exc_info.value.status_code == 400
            assert "top_p" in str(exc_info.value)

    def test_astream_chat_rejects_empty_messages(self):
        import asyncio

        client = _make_client()

        async def _collect():
            return [ev async for ev in client.astream_chat([])]

        with pytest.raises(ValueError, match="non-empty"):
            asyncio.run(_collect())


class TestErrorInheritance:
    def test_llm_request_error_is_runtime_error(self):
        """LLMRequestError must be catchable as RuntimeError for compat."""
        err = LLMRequestError(400, "http://x", "bad")
        assert isinstance(err, RuntimeError)

    def test_str_includes_status_url_and_body(self):
        err = LLMRequestError(400, "http://api.test/chat", "messages is empty")
        s = str(err)
        assert "400" in s
        assert "http://api.test/chat" in s
        assert "messages is empty" in s
