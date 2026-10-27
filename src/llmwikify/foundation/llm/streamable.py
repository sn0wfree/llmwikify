"""Streamable LLM client — supports streaming, async, and function calling.

Canonical location for the streaming-capable LLM client. The historical
home in ``llmwikify.agent.backend.adapters`` is preserved as a thin
deprecation shim; new code should import from
``llmwikify.foundation.llm.streamable`` instead.

Retry / SSE / wire-format helpers were split into sibling modules
(``connection.py``, ``sse.py``, ``wire.py``, ``errors.py``). All previous
names — including private ones used by tests — are re-exported below for
compatibility. Prefer importing from the new homes in new code.

Usage::

    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    client = StreamableLLMClient.from_config(config_dict)
    text = client.chat(messages, temperature=0.3)
    async for chunk in client.astream_chat(messages):
        ...

Token budget checking is applied automatically via decorator.
Pass ``_prompt_name="..."`` in generation_params to label calls in logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from .base import LLMClient, _legacy_fallback_enabled
from .budget_decorator import check_token_budget
from .connection import (
    RetryConfig,
    RetryMetrics,
    _compute_backoff,
    _extract_retry_after,
    _is_retryable_request_exception,
    _is_retryable_status,
    _parse_retry_after,
    _post_with_retry_async,
    _post_with_retry_sync,
    _record_retry_outcome,
    get_retry_metrics,
    reset_retry_metrics,
)
from .errors import (
    LLMNotConfiguredError,
    LLMRequestError,
    _extract_error_type_code,
    _format_http_error,
    _is_retryable_429_text,
    _normalize_error_token,
    is_arrearage_response,
)
from .resolver import resolve_chat_llm, resolver_enabled
from .spec import LLMSpec
from .sse import _parse_sse_line
from .token_budget import TokenBudgetChecker, TokenBudgetConfig
from .wire import (
    _enforce_role_alternation,
    _normalize_tool_call_ids,
    _validate_request,
    build_thinking_extra_body,
)

logger = logging.getLogger(__name__)


# ─── Backwards-compatible re-exports ────────────────────────────
# Tests and downstream callers import these private helpers from
# ``llmwikify.foundation.llm.streamable``. Keep until imports migrate
# to connection/sse/wire/errors (see docs/designs/
# foundation-llm-merge-streamable-split.md).
__all__ = [
    "StreamableLLMClient",
    "LLMRequestError",
    "is_arrearage_response",
    "build_thinking_extra_body",
    "RetryConfig",
    "RetryMetrics",
    "get_retry_metrics",
    "reset_retry_metrics",
]


class StreamableLLMClient(LLMClient):
    """LLM client with streaming and function calling support.

    Extends basic LLMClient with:
    - stream_chat(): SSE-compatible streaming
    - chat_with_tools(): Function calling support
    - astream_chat(): Async streaming
    - achat(): Async non-streaming
    - reasoning_split mode (chain-of-thought separation)
    - Configurable auth header (bearer / api-key)

    Token budget checking is applied automatically via decorator.
    Pass ``_prompt_name="..."`` in generation_params to label calls in logs.

    .. note::

        This class extends :class:`LLMClient` purely for type hierarchy
        (``isinstance(client, LLMClient) == True``). It does **not** call
        ``super().__init__()`` because its ``__init__`` signature is a
        strict superset of ``LLMClient.__init__`` (adds ``reasoning_split``
        and ``auth_header``) AND its ``base_url`` normalization strips a
        trailing ``/v1`` segment that LLMClient's does not.

        As a result, code that takes an ``LLMClient`` argument will accept
        a ``StreamableLLMClient`` instance, but the converse is not true:
        an LLMClient-only consumer cannot call ``stream_chat`` etc.
    """

    def __init__(
        self,
        provider: str | None = None,
        base_url: str = "",
        api_key: str = "",
        model: str | None = None,
        reasoning_split: bool = False,
        auth_header: str = "bearer",
        context_window: int | None = None,
        budget_on_exceed: str = "warn",
        request_timeout_seconds: float = 120,
    ):
        # LAL (PR 4): default provider/model are None. When neither
        # is supplied, raise LLMNotConfiguredError unless the
        # historical fallback kill-switch is on.
        if not _legacy_fallback_enabled():
            if provider is None:
                raise LLMNotConfiguredError(
                    "StreamableLLMClient() requires a provider; pass "
                    "provider=... or use StreamableLLMClient.from_spec()."
                )
            if model is None:
                raise LLMNotConfiguredError(
                    "StreamableLLMClient() requires a model; pass "
                    "model=... or use StreamableLLMClient.from_spec()."
                )
        else:
            provider = provider or "openai"
            model = model or "gpt-4o"
        self.provider = provider
        raw_base = base_url if base_url else self._default_base_url(provider)
        self.base_url = raw_base.rstrip("/").removesuffix("/v1") if raw_base else ""
        self.api_key = api_key
        self.model = model
        self.reasoning_split = reasoning_split
        self.auth_header = auth_header  # "bearer" or "api-key"
        self.request_timeout_seconds = request_timeout_seconds

        self._budget_checker = TokenBudgetChecker(
            TokenBudgetConfig(
                model=model,
                context_window=context_window,
                base_url=self.base_url,
                api_key=api_key,
                on_exceed=budget_on_exceed,
            )
        )

    @staticmethod
    def _default_base_url(provider: str) -> str:
        """Get default base_url from providers.yaml (v0.41+).

        Delegates to resolver.get_provider_metadata() so all provider
        metadata has a single source of truth.

        Unknown providers fall back to the OpenAI base URL — most
        OpenAI-compatible APIs (vLLM, OpenRouter, Together, etc.)
        can be reached by simply swapping the api_key.
        """
        from llmwikify.foundation.llm.resolver import get_provider_metadata

        meta = get_provider_metadata(provider)
        if meta.get("base_url"):
            return meta["base_url"]
        # Fallback for unknown providers
        openai_meta = get_provider_metadata("openai")
        return openai_meta.get("base_url", "https://api.openai.com/v1")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> StreamableLLMClient:
        """Build a client from the ``llm.*`` section of a wiki config.

        This is a pure config-to-constructor translation; it does
        NOT consult the LLM provider registry (that lives at
        L3 in ``llmwikify.apps.chat.providers.registry``).
        Callers that need the registry's provider discovery
        should call ``apps.chat.providers.registry.create_llm``
        directly.

        LAL: delegates to ``resolve_chat_llm`` (the single resolver
        entry point) when ``LLM_USE_RESOLVER`` is not set to
        ``"false"``. The legacy inline path is preserved as a
        kill-switch fallback for resolver regressions.
        """
        if resolver_enabled():
            spec = resolve_chat_llm(config)
            return cls.from_spec(spec)
        llm_cfg = config.get("llm", config)
        return cls(
            provider=llm_cfg.get("provider", "openai"),
            base_url=llm_cfg.get("base_url", ""),
            api_key=llm_cfg.get("api_key", ""),
            model=llm_cfg.get("model", "gpt-4o"),
            context_window=llm_cfg.get("context_window"),
            budget_on_exceed=llm_cfg.get("budget_on_exceed", "warn"),
            request_timeout_seconds=llm_cfg.get("timeout", 120),
        )

    @classmethod
    def from_spec(cls, spec: LLMSpec) -> StreamableLLMClient:
        """Build a client from a fully-resolved ``LLMSpec``.

        This is the canonical construction path for code that has
        already resolved LLM configuration via
        ``resolve_chat_llm``. Unlike ``from_config`` it does NOT
        re-parse env vars or config dicts — it trusts the spec.
        """
        return cls(
            provider=spec.provider,
            base_url=spec.base_url,
            api_key=spec.api_key,
            model=spec.model,
            context_window=spec.context_window,
            reasoning_split=spec.reasoning_split,
            auth_header=spec.auth_scheme,
            request_timeout_seconds=spec.timeout,
            budget_on_exceed=spec.budget_on_exceed,
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Synchronous non-streaming chat completion (canonical LAL name).

        LAL: this is the canonical sync entry point. It is currently
        a thin alias for ``chat``; the name is preferred in new code
        so that the LAL contract is uniform across providers.
        """
        return self.chat(messages, json_mode=json_mode, **generation_params)

    def _chat_url(self) -> str:
        """Build chat completions URL, avoiding double /v1/v1/."""
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with appropriate auth scheme."""
        headers = {"Content-Type": "application/json"}
        if self.auth_header == "api-key":
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        stream: bool = False,
        json_mode: bool = False,
        **generation_params: Any,
    ) -> dict[str, Any]:
        """Build the JSON payload for an OpenAI-compatible chat request.

        Centralises model, messages, tools, stream flag, reasoning_split,
        and generation-parameter injection that was previously duplicated
        across ``chat_with_tools``, ``stream_chat``, ``astream_chat`` and
        ``achat``.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if stream:
            payload["stream"] = True
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]
        return payload

    @check_token_budget(lambda self: self._budget_checker)
    def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Chat completion — sync wrapper around stream_chat().

        Uses streaming internally to avoid timeout for large outputs.
        Only accumulates "content" events (the actual answer).
        Falls back to "thinking" events (reasoning_content) if
        "content" is empty — M2.7 sometimes puts the answer there.
        """
        _validate_request(messages, generation_params)
        content = ""
        thinking = ""
        for event in self.stream_chat(
            messages, json_mode=json_mode, **generation_params
        ):
            etype = event.get("type")
            if etype == "content":
                content += event.get("text", "")
            elif etype == "thinking":
                thinking += event.get("text", "")
            elif etype == "done":
                done_content = event.get("content", "")
                if done_content and not content:
                    content = done_content
        # Prefer content; fall back to thinking if content is empty
        result = content if content.strip() else thinking
        # Strip <think>...</think> tags (some providers embed them in content)
        result = re.sub(r"<think>.*?</think>\s*", "", result, flags=re.DOTALL)
        result = re.sub(r"<think>.*$", "", result, flags=re.DOTALL)
        return result.strip()

    @check_token_budget(lambda self: self._budget_checker)
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ) -> dict[str, Any]:
        """Chat with function calling support.

        Returns:
            {"content": str, "tool_calls": [{"name": str, "args": dict}] | None}
        """
        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload = self._build_payload(messages, tools=tools, **generation_params)

        resp = _post_with_retry_sync(
            url,
            headers,
            payload,
            timeout_seconds=self.request_timeout_seconds,
        )
        try:
            if resp.status_code >= 400:
                raise _format_http_error(resp.status_code, url, resp.content)
            data = resp.json()
            message = data["choices"][0]["message"]

            result: dict[str, Any] = {"content": message.get("content", "")}
            if "tool_calls" in message and message["tool_calls"]:
                result["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "args": tc["function"]["arguments"],
                    }
                    for tc in message["tool_calls"]
                ]
            return result
        finally:
            resp.close()

    @check_token_budget(lambda self: self._budget_checker)
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ):
        """Streaming chat completion (yield chunks) — sync version using httpx.

        Yields:
            dict: {"type": "content", "text": str} or
                  {"type": "tool_call", "tool": str, "args": dict} or
                  {"type": "done", "content": str}

        Retry+backoff is applied to the initial connection. Mid-stream
        failures are NOT retried (the request has been billed and the
        caller is consuming the body).
        """
        import httpx

        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload = self._build_payload(
            messages, tools=tools, stream=True, **generation_params
        )

        config = RetryConfig.from_env()

        with httpx.Client(
            timeout=httpx.Timeout(connect=30, read=300, write=30, pool=30)
        ) as client:
            last_exc: BaseException | None = None

            for attempt in range(config.max_retries + 1):
                attempts_used = attempt + 1
                try:
                    stream_ctx = client.stream(
                        "POST", url, headers=headers, json=payload
                    )
                    resp = stream_ctx.__enter__()
                except (
                    httpx.ReadTimeout,
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.NetworkError,
                ) as e:
                    if (
                        _is_retryable_request_exception(e)
                        and attempt < config.max_retries
                    ):
                        wait = _compute_backoff(attempt, config)
                        logger.warning(
                            "LLM stream %s failed with %s (attempt %d/%d), "
                            "retrying in %.1fs: %s",
                            url,
                            type(e).__name__,
                            attempt + 1,
                            config.max_retries + 1,
                            wait,
                            e,
                        )
                        last_exc = e
                        time.sleep(wait)
                        continue
                    _record_retry_outcome(
                        success=False,
                        status_code=None,
                        exc=e,
                        attempts_used=attempts_used,
                    )
                    raise
                except Exception as e:
                    logger.warning("LLM stream %s unexpected error: %s", url, e)
                    _record_retry_outcome(
                        success=False,
                        status_code=None,
                        exc=e,
                        attempts_used=attempts_used,
                    )
                    raise

                if (
                    _is_retryable_status(resp.status_code)
                    and attempt < config.max_retries
                ):
                    retry_after = _extract_retry_after(
                        resp, config.retry_after_max_seconds
                    )
                    wait = (
                        retry_after
                        if retry_after is not None
                        else _compute_backoff(attempt, config)
                    )
                    reason = "Retry-After" if retry_after is not None else "backoff"
                    logger.warning(
                        "LLM stream %s returned %d (attempt %d/%d), "
                        "retrying in %.1fs (%s)",
                        url,
                        resp.status_code,
                        attempt + 1,
                        config.max_retries + 1,
                        wait,
                        reason,
                    )
                    stream_ctx.__exit__(None, None, None)
                    time.sleep(wait)
                    continue

                _record_retry_outcome(
                    success=200 <= resp.status_code < 300,
                    status_code=resp.status_code,
                    exc=None,
                    attempts_used=attempts_used,
                )
                break
            else:
                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("stream retry loop exited unexpectedly")

            try:
                if resp.status_code >= 400:
                    body = resp.read()
                    raise _format_http_error(resp.status_code, url, body)
                accumulated = ""
                tool_call_buffer: dict[int, dict] = {}
                for line in resp.iter_lines():
                    result = _parse_sse_line(line, accumulated, tool_call_buffer)
                    if result is None:
                        continue
                    events, accumulated, chunk = result
                    yield from events
                    # Some providers return full content in first chunk via
                    # message.content (not streaming despite stream=True).
                    # This is sync-only; async variant does not need it.
                    if chunk is not None:
                        msg = chunk.get("choices", [{}])[0].get("message", {})
                        msg_content = msg.get("content", "") or msg.get(
                            "reasoning_content", ""
                        )
                        if msg_content:
                            accumulated += msg_content
                            yield {"type": "content", "text": msg_content}
                    if events and events[-1].get("type") == "done":
                        return
            finally:
                stream_ctx.__exit__(None, None, None)

    @check_token_budget(lambda self: self._budget_checker)
    async def astream_chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ):
        """Async streaming chat completion using httpx.

        Yields:
            dict: {"type": "content", "text": str} or
                  {"type": "tool_call", "tool": str, "args": dict} or
                  {"type": "done", "content": str}

        Retry+backoff is applied to the initial connection. Mid-stream
        failures are NOT retried (the request has been billed and the
        caller is consuming the body).
        """
        import httpx

        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload = self._build_payload(
            messages, tools=tools, stream=True, **generation_params
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30, read=300, write=30, pool=30)
        ) as client:
            config = RetryConfig.from_env()
            last_exc: BaseException | None = None

            for attempt in range(config.max_retries + 1):
                attempts_used = attempt + 1
                try:
                    stream_ctx = client.stream(
                        "POST", url, headers=headers, json=payload
                    )
                    resp = await stream_ctx.__aenter__()
                except (
                    httpx.ReadTimeout,
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.NetworkError,
                ) as e:
                    if (
                        _is_retryable_request_exception(e)
                        and attempt < config.max_retries
                    ):
                        wait = _compute_backoff(attempt, config)
                        logger.warning(
                            "LLM astream %s failed with %s (attempt %d/%d), "
                            "retrying in %.1fs: %s",
                            url,
                            type(e).__name__,
                            attempt + 1,
                            config.max_retries + 1,
                            wait,
                            e,
                        )
                        last_exc = e
                        await asyncio.sleep(wait)
                        continue
                    _record_retry_outcome(
                        success=False,
                        status_code=None,
                        exc=e,
                        attempts_used=attempts_used,
                    )
                    raise
                except Exception as e:
                    logger.warning("LLM astream %s unexpected error: %s", url, e)
                    _record_retry_outcome(
                        success=False,
                        status_code=None,
                        exc=e,
                        attempts_used=attempts_used,
                    )
                    raise

                if (
                    _is_retryable_status(resp.status_code)
                    and attempt < config.max_retries
                ):
                    retry_after = _extract_retry_after(
                        resp, config.retry_after_max_seconds
                    )
                    wait = (
                        retry_after
                        if retry_after is not None
                        else _compute_backoff(attempt, config)
                    )
                    reason = "Retry-After" if retry_after is not None else "backoff"
                    logger.warning(
                        "LLM astream %s returned %d (attempt %d/%d), "
                        "retrying in %.1fs (%s)",
                        url,
                        resp.status_code,
                        attempt + 1,
                        config.max_retries + 1,
                        wait,
                        reason,
                    )
                    await stream_ctx.__aexit__(None, None, None)
                    await asyncio.sleep(wait)
                    continue

                _record_retry_outcome(
                    success=200 <= resp.status_code < 300,
                    status_code=resp.status_code,
                    exc=None,
                    attempts_used=attempts_used,
                )
                break
            else:
                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("astream retry loop exited unexpectedly")

            try:
                if resp.status_code >= 400:
                    # Drain the body so we can include the API's
                    # diagnostic in the raised error.
                    body = await resp.aread()
                    raise _format_http_error(resp.status_code, url, body)
                accumulated = ""
                tool_call_buffer: dict[int, dict] = {}
                async for line in resp.aiter_lines():
                    result = _parse_sse_line(line, accumulated, tool_call_buffer)
                    if result is None:
                        continue
                    events, accumulated, _chunk = result
                    for ev in events:
                        yield ev
                    if events and events[-1].get("type") == "done":
                        return
            finally:
                await stream_ctx.__aexit__(None, None, None)

    @check_token_budget(lambda self: self._budget_checker)
    async def achat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Async non-streaming chat completion using httpx."""
        import httpx

        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload = self._build_payload(
            messages, json_mode=json_mode, **generation_params
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30, read=300, write=30, pool=30)
        ) as client:
            resp = await _post_with_retry_async(
                client,
                "POST",
                url,
                headers,
                payload,
            )
            try:
                if resp.status_code >= 400:
                    raise _format_http_error(resp.status_code, url, resp.content)
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            finally:
                await resp.aclose()
