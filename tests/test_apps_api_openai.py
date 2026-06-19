"""Tests for the OpenAI-compatible API router (P1-1 vendored from nanobot).

Covers:
  - Response shape helpers: openai_error_response, openai_chat_completion_response,
    openai_sse_chunk.
  - Event translator: OpenAIStreamTranslator maps llmwikify events
    (``message_delta``, ``thinking``, ``tool_call_*``, ``done``, ``error``,
    ``save_warning``) to OpenAI streaming chunks and final ``[DONE]``.
  - Request body parsing: single-user-message contract, multi-message rejection,
    empty content rejection, vision-format text extraction.
  - Router factory: create_openai_router exposes 3 routes (chat/completions,
    models, health) with correct methods.
  - End-to-end via FastAPI TestClient: /v1/models + /v1/health + streaming
    /v1/chat/completions + non-streaming /v1/chat/completions.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _parse_sse_payloads(body: bytes) -> list[dict[str, Any]]:
    """Parse a streamed SSE body into a list of decoded JSON payloads.

    Drops the ``data: [DONE]`` sentinel.
    """
    payloads: list[dict[str, Any]] = []
    for raw_line in body.split(b"\n\n"):
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[len(b"data:"):].strip()
        if data == b"[DONE]":
            continue
        if data:
            payloads.append(json.loads(data))
    return payloads


def _make_mock_service(events: list[dict[str, Any]]) -> MagicMock:
    """Build a fake AgentService whose ``chat`` is an async iterator of events."""
    service = MagicMock(name="AgentService")
    service.chat = MagicMock()
    service.chat.side_effect = lambda **_kw: _async_iter(events)
    return service


async def _async_iter(items: list[Any]):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# 1. Response shape helpers
# ---------------------------------------------------------------------------


class TestOpenAIResponseHelpers:
    def test_error_response_default_type(self):
        from llmwikify.apps.api.openai_server import openai_error_response

        resp = openai_error_response(400, "bad request")
        assert resp.status_code == 400
        body = json.loads(resp.body)
        assert body == {
            "error": {
                "message": "bad request",
                "type": "invalid_request_error",
                "code": 400,
            }
        }

    def test_error_response_custom_type(self):
        from llmwikify.apps.api.openai_server import openai_error_response

        resp = openai_error_response(500, "boom", err_type="server_error")
        body = json.loads(resp.body)
        assert body["error"]["type"] == "server_error"
        assert body["error"]["code"] == 500

    def test_chat_completion_response_shape(self):
        from llmwikify.apps.api.openai_server import openai_chat_completion_response

        body = openai_chat_completion_response("hello", "llmwikify-chat")
        assert body["object"] == "chat.completion"
        assert body["model"] == "llmwikify-chat"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["message"]["content"] == "hello"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["id"].startswith("chatcmpl-")
        assert body["usage"]["total_tokens"] == 0

    def test_sse_chunk_content_only(self):
        from llmwikify.apps.api.openai_server import openai_sse_chunk

        chunk = openai_sse_chunk("hi", "m", "chatcmpl-abc")
        assert chunk.startswith(b"data: ")
        payload = json.loads(chunk[len(b"data: "):].rstrip(b"\n\n"))
        assert payload["choices"][0]["delta"] == {"content": "hi"}
        assert payload["choices"][0]["finish_reason"] is None
        assert payload["model"] == "m"

    def test_sse_chunk_first_chunk_has_role(self):
        from llmwikify.apps.api.openai_server import openai_sse_chunk

        chunk = openai_sse_chunk("", "m", "chatcmpl-abc")
        payload = json.loads(chunk[len(b"data: "):].rstrip(b"\n\n"))
        # Empty content + no finish_reason → first-chunk role signal.
        assert payload["choices"][0]["delta"] == {"role": "assistant", "content": ""}

    def test_sse_chunk_finish_reason_only(self):
        from llmwikify.apps.api.openai_server import openai_sse_chunk

        chunk = openai_sse_chunk("", "m", "chatcmpl-abc", finish_reason="stop")
        payload = json.loads(chunk[len(b"data: "):].rstrip(b"\n\n"))
        assert payload["choices"][0]["delta"] == {}
        assert payload["choices"][0]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# 2. Event translator
# ---------------------------------------------------------------------------


class TestOpenAIStreamTranslator:
    def test_message_delta_becomes_content(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        chunk = t.translate({"type": "message_delta", "content": "hi"})
        assert chunk is not None
        payload = json.loads(chunk[len(b"data: "):].rstrip(b"\n\n"))
        assert payload["choices"][0]["delta"] == {"content": "hi"}
        assert t.emitted_content is True

    def test_empty_message_delta_skipped(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        assert t.translate({"type": "message_delta", "content": ""}) is None
        assert t.emitted_content is False

    def test_thinking_skipped(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        assert t.translate({"type": "thinking", "content": "hmm"}) is None

    def test_tool_call_events_skipped(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        for ev in [
            {"type": "tool_call_start", "tool": "x", "args": {}, "call_id": "c1"},
            {"type": "tool_call_end", "tool": "x", "result": "r", "call_id": "c1"},
            {"type": "tool_call_error", "tool": "x", "error": "e", "call_id": "c1"},
            {"type": "save_warning", "reason": "x"},
            {"type": "session_created", "session_id": "s1"},
        ]:
            assert t.translate(ev) is None

    def test_done_emits_final_then_signals_stop(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        # No content emitted yet → done.final_response emitted as content.
        assert t.translate({"type": "done", "final_response": "answer"}) is not None
        # Subsequent events are ignored.
        assert t.translate({"type": "message_delta", "content": "late"}) is None

    def test_done_after_streaming_emits_no_extra_content(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        t.translate({"type": "message_delta", "content": "hi"})
        # done.final_response is NOT re-emitted; final_chunk() handles stop.
        assert t.translate({"type": "done", "final_response": "hi"}) is None

    def test_error_ends_stream_no_done(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        assert t.translate({"type": "message_delta", "content": "partial"}) is not None
        assert t.translate({"type": "error", "message": "boom"}) is None
        # After error, further events are ignored.
        assert t.translate({"type": "done", "final_response": "x"}) is None

    def test_final_chunk_has_stop(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        chunk = t.final_chunk()
        payload = json.loads(chunk[len(b"data: "):].rstrip(b"\n\n"))
        assert payload["choices"][0]["finish_reason"] == "stop"

    def test_final_sentinel(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m", chunk_id="chatcmpl-1")
        assert t.final_sentinel() == b"data: [DONE]\n\n"

    def test_default_chunk_id_assigned(self):
        from llmwikify.apps.api.openai_server import OpenAIStreamTranslator

        t = OpenAIStreamTranslator(model="m")
        assert t._chunk_id.startswith("chatcmpl-")


# ---------------------------------------------------------------------------
# 3. Request body parsing
# ---------------------------------------------------------------------------


class TestParseUserMessage:
    def test_simple_string(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        text, sid, stream = _parse_user_message({
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "session_id": "abc",
        })
        assert text == "hello"
        assert sid == "abc"
        assert stream is True

    def test_vision_format_extracts_text(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        text, _, _ = _parse_user_message({
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe"},
                        {"type": "image_url", "image_url": {"url": "data:..."}},
                        {"type": "text", "text": "this"},
                    ],
                }
            ],
        })
        assert text == "describe this"

    def test_multi_message_rejected(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        with pytest.raises(ValueError, match="single user message"):
            _parse_user_message({
                "messages": [
                    {"role": "user", "content": "a"},
                    {"role": "user", "content": "b"},
                ],
            })

    def test_non_user_role_rejected(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        with pytest.raises(ValueError, match="single user message"):
            _parse_user_message({
                "messages": [{"role": "system", "content": "x"}],
            })

    def test_empty_content_rejected(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        with pytest.raises(ValueError, match="Empty message"):
            _parse_user_message({
                "messages": [{"role": "user", "content": "   "}],
            })

    def test_invalid_content_type_rejected(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        with pytest.raises(ValueError, match="Invalid content"):
            _parse_user_message({
                "messages": [{"role": "user", "content": 42}],
            })

    def test_stream_defaults_false(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        _, _, stream = _parse_user_message({
            "messages": [{"role": "user", "content": "x"}],
        })
        assert stream is False

    def test_session_id_optional(self):
        from llmwikify.apps.api.openai_server import _parse_user_message

        text, sid, _ = _parse_user_message({
            "messages": [{"role": "user", "content": "x"}],
        })
        assert text == "x"
        assert sid is None


# ---------------------------------------------------------------------------
# 4. Router factory
# ---------------------------------------------------------------------------


class TestCreateOpenaiRouter:
    def test_default_routes(self):
        from llmwikify.apps.api.openai_server import create_openai_router

        router = create_openai_router()
        paths = sorted({r.path for r in router.routes})
        assert "/v1/chat/completions" in paths
        assert "/v1/models" in paths
        assert "/v1/health" in paths

    def test_routes_have_correct_methods(self):
        from llmwikify.apps.api.openai_server import create_openai_router

        router = create_openai_router()
        methods_by_path = {}
        for r in router.routes:
            methods_by_path[r.path] = sorted(r.methods or [])
        assert "POST" in methods_by_path["/v1/chat/completions"]
        assert "GET" in methods_by_path["/v1/models"]
        assert "GET" in methods_by_path["/v1/health"]

    def test_custom_model_and_timeout(self):
        from llmwikify.apps.api.openai_server import create_openai_router

        # Just verify construction doesn't blow up with custom args.
        router = create_openai_router(model="custom-m", request_timeout=5.0)
        assert len(list(router.routes)) >= 3


# ---------------------------------------------------------------------------
# 5. End-to-end via FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_mock_service(monkeypatch):
    """Build a FastAPI app with the OpenAI router and a mocked AgentService."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from llmwikify.apps.api.openai_server import create_openai_router

    # The router depends on get_agent_service() being set.
    # Patch the chat_sse module to return our mock.
    mock_service = MagicMock(name="AgentService")

    events = [
        {"type": "message_delta", "content": "Hello"},
        {"type": "message_delta", "content": " world"},
        {"type": "done", "final_response": "Hello world"},
    ]
    mock_service.chat = lambda **_: _async_iter(events)

    import llmwikify.apps.api.openai_server as openai_mod
    monkeypatch.setattr(openai_mod, "_AGENT_SERVICE", mock_service)
    monkeypatch.setattr(openai_mod, "get_agent_service", lambda: mock_service)

    app = FastAPI()
    app.include_router(create_openai_router(model="llmwikify-chat"))
    return app, mock_service


class TestOpenAIE2E:
    def test_models_endpoint(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, _ = app_with_mock_service
        client = TestClient(app)
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert len(body["data"]) == 1
        assert body["data"][0]["id"] == "llmwikify-chat"
        assert body["data"][0]["owned_by"] == "llmwikify"

    def test_health_endpoint(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, _ = app_with_mock_service
        client = TestClient(app)
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_chat_completion_streaming(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, _ = app_with_mock_service
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llmwikify-chat",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        payloads = _parse_sse_payloads(resp.content)
        # 2 content deltas + 1 stop chunk
        assert len(payloads) == 3
        assert payloads[0]["choices"][0]["delta"] == {"content": "Hello"}
        assert payloads[1]["choices"][0]["delta"] == {"content": " world"}
        assert payloads[2]["choices"][0]["finish_reason"] == "stop"
        # [DONE] sentinel present
        assert b"data: [DONE]\n\n" in resp.content

    def test_chat_completion_non_streaming(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, _ = app_with_mock_service
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llmwikify-chat",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["choices"][0]["message"]["content"] == "Hello world"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["model"] == "llmwikify-chat"

    def test_chat_completion_rejects_wrong_model(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, _ = app_with_mock_service
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "Only configured model" in body["error"]["message"]

    def test_chat_completion_rejects_multi_message(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, _ = app_with_mock_service
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llmwikify-chat",
                "messages": [
                    {"role": "user", "content": "a"},
                    {"role": "user", "content": "b"},
                ],
            },
        )
        assert resp.status_code == 400

    def test_chat_completion_invalid_json_body(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, _ = app_with_mock_service
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            content="not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]["message"]

    def test_session_id_passed_to_service(self, app_with_mock_service):
        from fastapi.testclient import TestClient

        app, mock_service = app_with_mock_service
        # Replace the lambda with a MagicMock so we can inspect call_args.
        chat_mock = MagicMock(name="chat")
        chat_mock.side_effect = lambda **_: _async_iter([
            {"type": "message_delta", "content": "ok"},
            {"type": "done", "final_response": "ok"},
        ])
        mock_service.chat = chat_mock

        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "llmwikify-chat",
                "stream": False,
                "session_id": "user-42",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 200
        # Verify the session_id was forwarded to the service.
        assert chat_mock.called
        kwargs = chat_mock.call_args.kwargs
        assert kwargs["session_id"] == "api:user-42"
        assert kwargs["message"] == "hi"
