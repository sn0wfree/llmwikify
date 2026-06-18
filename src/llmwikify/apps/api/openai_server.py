"""OpenAI-compatible HTTP API endpoints for llmwikify.

Vendored and adapted from nanobot ``api/server.py`` (399 LOC, MIT).
Provides:
  - POST /v1/chat/completions   (streaming + non-streaming)
  - GET  /v1/models
  - GET  /v1/health

The original nanobot server used aiohttp; this port uses FastAPI
(``StreamingResponse`` for SSE) to slot into llmwikify's existing
HTTP stack (``interfaces/server/http/``).

Adaptation from the upstream source:
  - ``aiohttp.web`` → ``fastapi`` (routers + ``StreamingResponse``)
  - ``agent_loop.process_direct(...)`` → ``AgentService.chat(...)``
    (the existing llmwikify orchestrator; yields ``message_delta`` /
    ``thinking`` / ``tool_call_*`` / ``done`` SSE events).
  - Removed multipart file upload path — llmwikify has a separate
    upload story via the wiki API (``POST /api/wiki/page``). JSON
    request body only keeps the surface small and focused.
  - Session model: nanobot used a single persistent ``api:default``
    session per request. We forward an explicit ``session_id`` from
    the request (default ``"api:default"``) and reuse the existing
    llmwikify chat session DB.
  - Per-session asyncio.Lock replaces nanobot's app-state ``session_locks``
    dict, so concurrent requests on the same session_id serialize.
"""

from __future__ import annotations

import asyncio
import json as _json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from llmwikify.apps.chat.agent.agent_service import AgentService
from llmwikify.interfaces.server.http.chat_sse import get_agent_service

__all__ = (
    "API_SESSION_KEY",
    "OpenAIStreamTranslator",
    "create_openai_router",
    "openai_chat_completion_response",
    "openai_error_response",
    "openai_sse_chunk",
)


API_SESSION_KEY = "api:default"

_OPENAI_SSE_DONE = b"data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# OpenAI response helpers
# ---------------------------------------------------------------------------


def openai_error_response(
    status: int,
    message: str,
    err_type: str = "invalid_request_error",
) -> JSONResponse:
    """Format an OpenAI-style error JSON response."""
    return JSONResponse(
        status_code=status,
        content={
            "error": {"message": message, "type": err_type, "code": status},
        },
    )


def openai_chat_completion_response(content: str, model: str) -> dict[str, Any]:
    """Build a non-streaming OpenAI ``chat.completion`` payload."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def openai_sse_chunk(
    delta_content: str | None,
    model: str,
    chunk_id: str,
    finish_reason: str | None = None,
) -> bytes:
    """Format a single OpenAI-compatible ``chat.completion.chunk`` SSE line.

    The ``delta`` field always includes ``role: assistant`` on the first
    chunk (when ``delta_content`` is empty AND no finish_reason), per
    the OpenAI streaming protocol. Subsequent content chunks omit
    ``role`` and only carry the new ``content`` fragment.
    """
    if delta_content:
        delta: dict[str, Any] = {"content": delta_content}
    elif finish_reason is None:
        delta = {"role": "assistant", "content": ""}
    else:
        delta = {}
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n".encode()


# ---------------------------------------------------------------------------
# SSE translator: llmwikify event vocabulary → OpenAI chunks
# ---------------------------------------------------------------------------


class OpenAIStreamTranslator:
    """Translate ``AgentService.chat`` events into OpenAI SSE chunks.

    llmwikify event vocabulary (from ``ChatEvent`` factory in
    ``apps/chat/agent/orchestrator.py``):

      - ``{"type": "message_delta", "content": "..."}``   → OpenAI content delta
      - ``{"type": "thinking", "content": "..."}``         → ignored (OpenAI has no thinking channel)
      - ``{"type": "tool_call_start", "tool": "...", ...}`` → ignored (we don't expose tool_calls to OpenAI clients)
      - ``{"type": "tool_call_end", ...}``                  → ignored
      - ``{"type": "tool_call_error", ...}``               → ignored
      - ``{"type": "done", "final_response": "..."}``      → final stop chunk
      - ``{"type": "error", "message": "..."}``            → end stream (no [DONE])
      - ``{"type": "save_warning", "reason": "..."}``      → ignored (internal signal)

    ``finish_reason`` is only emitted on the final chunk, after the
    ``done`` event arrives.
    """

    def __init__(self, model: str, chunk_id: str | None = None) -> None:
        self._model = model
        self._chunk_id = chunk_id or f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self._emitted_content = False
        self._done = False

    @property
    def emitted_content(self) -> bool:
        return self._emitted_content

    def translate(self, event: dict[str, Any]) -> bytes | None:
        """Convert one llmwikify event into an SSE chunk (or ``None`` to skip)."""
        if self._done:
            return None
        etype = event.get("type")
        if etype == "message_delta":
            content = event.get("content", "")
            if content:
                self._emitted_content = True
                return openai_sse_chunk(content, self._model, self._chunk_id)
            return None
        if etype == "done":
            self._done = True
            final = event.get("final_response") or ""
            if final and not self._emitted_content:
                # No streaming content was emitted but a final answer
                # exists — emit it as a single content delta before
                # the stop chunk.
                self._emitted_content = True
                return openai_sse_chunk(final, self._model, self._chunk_id)
            return None
        if etype == "error":
            # End the stream without [DONE] so the client sees the
            # partial response it received and surfaces the error.
            self._done = True
            return None
        # thinking / tool_call_* / save_warning / session_created → skip
        return None

    def final_chunk(self) -> bytes:
        """Emit the closing stop chunk (called once at stream end)."""
        return openai_sse_chunk("", self._model, self._chunk_id, finish_reason="stop")

    def final_sentinel(self) -> bytes:
        """Emit ``data: [DONE]`` marker (OpenAI streaming termination)."""
        return _OPENAI_SSE_DONE


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------


def _parse_user_message(body: dict[str, Any]) -> tuple[str, str | None, bool]:
    """Parse an OpenAI-format request body.

    Returns ``(text, session_id, stream)``. Only single-message
    conversations are supported (matches nanobot's contract); multi-
    turn history is forwarded via the ``session_id`` of an existing
    llmwikify chat session.

    Raises ``ValueError`` on schema violations.
    """
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        raise ValueError("Only a single user message is supported")
    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        raise ValueError("Only a single user message is supported")
    user_content = message.get("content", "")
    if isinstance(user_content, list):
        # OpenAI vision format: extract text parts; ignore image_url
        # (llmwikify has its own upload story; not exposed here).
        text_parts = [
            part.get("text", "")
            for part in user_content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = " ".join(text_parts)
    elif isinstance(user_content, str):
        text = user_content
    else:
        raise ValueError("Invalid content format")
    if not text.strip():
        raise ValueError("Empty message content")
    session_id = body.get("session_id")
    stream = bool(body.get("stream", False))
    return text, session_id, stream


# ---------------------------------------------------------------------------
# Per-session concurrency lock (mirrors nanobot's session_locks dict)
# ---------------------------------------------------------------------------


class _SessionLockRegistry:
    """Per-session asyncio.Lock for serializing concurrent requests."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def lock_for(self, session_key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(session_key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_key] = lock
            return lock


_LOCKS = _SessionLockRegistry()


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def _stream_chat_completion(
    service: AgentService,
    text: str,
    session_key: str,
    model: str,
    timeout_s: float,
) -> AsyncIterator[bytes]:
    """Run ``service.chat`` and yield OpenAI-formatted SSE bytes."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    translator = OpenAIStreamTranslator(model=model, chunk_id=chunk_id)
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    stream_failed = False

    async def _pump() -> None:
        nonlocal stream_failed
        try:
            async for event in service.chat(
                message=text,
                session_id=session_key,
            ):
                chunk = translator.translate(event)
                if chunk is not None:
                    await queue.put(chunk)
        except Exception:
            stream_failed = True
        finally:
            await queue.put(None)

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            chunk = await asyncio.wait_for(queue.get(), timeout=timeout_s)
            if chunk is None:
                break
            yield chunk
    except asyncio.TimeoutError:
        stream_failed = True
    finally:
        if not pump_task.done():
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass

    if not stream_failed:
        yield translator.final_chunk()
        yield translator.final_sentinel()


def _make_chat_handler(model: str, request_timeout: float):
    """Build a chat-completions handler bound to ``model`` + ``request_timeout``.

    Mirrors nanobot's ``create_app(agent_loop, model_name, request_timeout)``
    pattern: route handlers capture config via closure, so the router
    factory can produce a fully-wired APIRouter in one call.
    """
    async def handle_chat_completions(request: Request) -> Any:
        """POST /v1/chat/completions — JSON body, OpenAI-shaped."""
        service: AgentService = get_agent_service()

        try:
            try:
                body = await request.json()
            except Exception:
                return openai_error_response(400, "Invalid JSON body")
            if not isinstance(body, dict):
                return openai_error_response(400, "Body must be a JSON object")
            requested_model = body.get("model")
            if requested_model and requested_model != model:
                return openai_error_response(
                    400,
                    f"Only configured model '{model}' is available",
                )
            text, session_id, stream = _parse_user_message(body)
        except ValueError as e:
            return openai_error_response(400, str(e))

        session_key = f"api:{session_id}" if session_id else API_SESSION_KEY
        lock = await _LOCKS.lock_for(session_key)

        if stream:
            async def _body() -> AsyncIterator[bytes]:
                async with lock:
                    async for chunk in _stream_chat_completion(
                        service=service,
                        text=text,
                        session_key=session_key,
                        model=model,
                        timeout_s=request_timeout,
                    ):
                        yield chunk

            return StreamingResponse(
                _body(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # Non-streaming path
        accumulated: list[str] = []
        final_response: str | None = None
        try:
            async with lock:
                try:
                    async for event in service.chat(
                        message=text,
                        session_id=session_key,
                    ):
                        if event.get("type") == "message_delta":
                            accumulated.append(event.get("content", ""))
                        elif event.get("type") == "done":
                            fr = event.get("final_response")
                            if isinstance(fr, str) and fr:
                                final_response = fr
                except asyncio.TimeoutError:
                    return openai_error_response(
                        504,
                        f"Request timed out after {request_timeout}s",
                    )
                except Exception:
                    return openai_error_response(
                        500, "Internal server error", err_type="server_error",
                    )
        except Exception:
            return openai_error_response(
                500, "Internal server error", err_type="server_error",
            )

        # Prefer the final_response (already complete) when present;
        # otherwise stitch the streaming deltas together. This mirrors
        # nanobot's behavior: process_direct returns the full message.
        if final_response is not None:
            response_text = final_response.strip()
        else:
            response_text = "".join(accumulated).strip()

        response_text = "".join(accumulated).strip()
        if not response_text:
            return openai_error_response(502, "Empty response from agent")
        return JSONResponse(
            content=openai_chat_completion_response(response_text, model),
        )

    return handle_chat_completions


def _make_models_handler(model: str):
    """Build a /v1/models handler bound to ``model``."""
    async def handle_models(_request: Request) -> JSONResponse:
        """GET /v1/models — return the single configured model."""
        return JSONResponse(
            content={
                "object": "list",
                "data": [
                    {
                        "id": model,
                        "object": "model",
                        "created": 0,
                        "owned_by": "llmwikify",
                    }
                ],
            }
        )

    return handle_models


async def handle_health(_request: Request) -> JSONResponse:
    """GET /v1/health — liveness probe."""
    return JSONResponse(content={"status": "ok"})


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_openai_router(
    model: str = "llmwikify-chat",
    request_timeout: float = 120.0,
) -> APIRouter:
    """Build the OpenAI-compat APIRouter.

    Args:
        model: The model name to advertise in ``/v1/models`` and echo
            back in chat completion responses. Defaults to
            ``"llmwikify-chat"``.
        request_timeout: Per-request timeout in seconds (default 120s).
    """
    router = APIRouter(prefix="/v1", tags=["openai"])
    chat_handler = _make_chat_handler(model, request_timeout)
    models_handler = _make_models_handler(model)
    router.add_api_route(
        "/chat/completions",
        chat_handler,
        methods=["POST"],
        summary="OpenAI-compatible chat completions",
    )
    router.add_api_route(
        "/models",
        models_handler,
        methods=["GET"],
        summary="List available models",
    )
    router.add_api_route(
        "/health",
        handle_health,
        methods=["GET"],
        summary="Liveness probe",
    )
    return router
