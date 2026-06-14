"""Streamable LLM client — supports streaming, async, and function calling.

Canonical location for the streaming-capable LLM client. The historical
home in ``llmwikify.agent.backend.adapters`` is preserved as a thin
deprecation shim; new code should import from
``llmwikify.foundation.llm.streamable`` instead.

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

import json
import os
from typing import Any

from ..llm_client import LLMClient, _legacy_fallback_enabled
from .budget_decorator import check_token_budget
from .errors import LLMNotConfiguredError
from .resolver import resolve_chat_llm, resolver_enabled
from .spec import LLMSpec
from .token_budget import TokenBudgetChecker, TokenBudgetConfig


class LLMRequestError(RuntimeError):
    """Raised when the LLM provider returns a 4xx/5xx response.

    Unlike ``httpx.HTTPStatusError`` or ``requests.HTTPError`` (which
    only embed the status line and URL), this exception carries the
    provider's error body so the user can see *why* the call failed —
    e.g. MiniMax's ``{"error":{"message":"invalid params, messages
    is empty (2013)"}}`` instead of a bare ``400 Bad Request``.
    """

    def __init__(self, status_code: int, url: str, body: str):
        self.status_code = status_code
        self.url = url
        self.body = body
        # Truncate body to keep logs readable
        preview = body[:500] + ("…" if len(body) > 500 else "")
        super().__init__(
            f"LLM API returned {status_code} for {url}: {preview}"
        )


def _validate_request(
    messages: list[dict[str, Any]] | None,
    generation_params: dict[str, Any] | None = None,
) -> None:
    """Pre-flight validation for chat completion requests.

    Catches the most common provider-side rejections *before* they
    cost a network round-trip:

      - Empty ``messages`` (MiniMax error 2013)
      - ``top_p`` outside the OpenAI-compatible (0, 1] range
      - ``temperature`` outside [0, 2] (Anthropic-compatible ceiling)

    Provider-specific quirks (e.g. MiniMax reasoning_split + tools
    combinations) are not validated here — they will surface as
    ``LLMRequestError`` with the full body, which is informative
    enough to diagnose.
    """
    if not messages:
        raise ValueError(
            "messages must be a non-empty list of role/content dicts; "
            "got empty list. Add at least one system or user message "
            "before calling the LLM."
        )
    params = generation_params or {}
    if "top_p" in params:
        top_p = params["top_p"]
        if not isinstance(top_p, (int, float)) or not (0.0 < top_p <= 1.0):
            raise ValueError(
                f"top_p must be a number in (0, 1]; got {top_p!r}"
            )
    if "temperature" in params:
        temp = params["temperature"]
        if not isinstance(temp, (int, float)) or not (0.0 <= temp <= 2.0):
            raise ValueError(
                f"temperature must be a number in [0, 2]; got {temp!r}"
            )


def _format_http_error(
    status_code: int,
    url: str,
    body: bytes | str | None,
) -> LLMRequestError:
    """Build an ``LLMRequestError`` with a best-effort decoded body."""
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = repr(body[:200])
    else:
        text = body or ""
    # Try to extract the message from common OpenAI-compatible shapes
    # so the preview is more useful than the full JSON blob.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            err = parsed.get("error") or parsed.get("message")
            if isinstance(err, dict) and "message" in err:
                text = str(err["message"])
            elif isinstance(err, str):
                text = err
    except (json.JSONDecodeError, ValueError):
        pass
    return LLMRequestError(status_code, url, text)


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
        self.base_url = raw_base.rstrip("/").removesuffix("/v1")
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
        defaults = {
            "openai": "https://api.openai.com",
            "ollama": "http://localhost:11434/v1",
            "lmstudio": "http://localhost:1234/v1",
            "minimax": "https://api.minimaxi.com/v1",
            "xiaomi": "https://token-plan-cn.xiaomimimo.com",
        }
        return defaults.get(provider, "https://api.openai.com")

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

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with appropriate auth scheme."""
        headers = {"Content-Type": "application/json"}
        if self.auth_header == "api-key":
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @check_token_budget(lambda self: self._budget_checker)
    def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Non-streaming chat completion."""
        try:
            import requests
        except ImportError:
            raise ImportError("requests is required")

        _validate_request(messages, generation_params)

        url = f"{self.base_url}/v1/chat/completions"
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        resp = requests.post(url, headers=headers, json=payload, timeout=self.request_timeout_seconds)
        if resp.status_code >= 400:
            raise _format_http_error(resp.status_code, url, resp.content)
        data = resp.json()
        return data["choices"][0]["message"]["content"]

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
        try:
            import requests
        except ImportError:
            raise ImportError("requests is required")

        _validate_request(messages, generation_params)

        url = f"{self.base_url}/v1/chat/completions"
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        resp = requests.post(url, headers=headers, json=payload, timeout=self.request_timeout_seconds)
        if resp.status_code >= 400:
            raise _format_http_error(resp.status_code, url, resp.content)
        data = resp.json()
        message = data["choices"][0]["message"]

        result: dict[str, Any] = {"content": message.get("content", "")}
        if "tool_calls" in message and message["tool_calls"]:
            result["tool_calls"] = [
                {
                    "name": tc["function"]["name"],
                    "args": tc["function"]["arguments"],
                }
                for tc in message["tool_calls"]
            ]
        return result

    @check_token_budget(lambda self: self._budget_checker)
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ):
        """Streaming chat completion (yield chunks) — sync version using requests.

        Yields:
            dict: {"type": "content", "text": str} or
                  {"type": "tool_call", "tool": str, "args": dict} or
                  {"type": "done", "content": str}
        """
        try:
            import requests
        except ImportError:
            raise ImportError("requests is required")

        _validate_request(messages, generation_params)

        url = f"{self.base_url}/v1/chat/completions"
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        with requests.post(url, headers=headers, json=payload, timeout=self.request_timeout_seconds, stream=True) as resp:
            if resp.status_code >= 400:
                # Drain body so we can include it in the error.
                body = resp.content
                resp.close()
                raise _format_http_error(resp.status_code, url, body)
            accumulated = ""
            tool_call_buffer: dict[int, dict] = {}
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith(b"data: "):
                    line = line[6:]
                if line == b"[DONE]":
                    yield {"type": "done", "content": accumulated}
                    return
                try:
                    import json as _json
                    chunk = _json.loads(line)
                except Exception:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                # Handle reasoning_content (MiniMax reasoning_split mode).
                # Chain-of-thought is yielded as a "thinking" event but is
                # NOT mixed into the final "content" — downstream consumers
                # that wait for the final string should get only the answer.
                if "reasoning_content" in delta and delta["reasoning_content"]:
                    yield {"type": "thinking", "text": delta["reasoning_content"]}
                # Handle regular content (only this goes into accumulated)
                if "content" in delta and delta["content"]:
                    accumulated += delta["content"]
                    yield {"type": "content", "text": delta["content"]}

                if "tool_calls" in delta:
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        if idx not in tool_call_buffer:
                            tool_call_buffer[idx] = {
                                "id": tc.get("id", ""),
                                "name": "",
                                "args_parts": [],
                            }
                        entry = tool_call_buffer[idx]
                        if "id" in tc and tc["id"]:
                            entry["id"] = tc["id"]
                        func = tc.get("function", {})
                        if "name" in func and func["name"]:
                            entry["name"] = func["name"]
                        if "arguments" in func and func["arguments"]:
                            entry["args_parts"].append(func["arguments"])

                finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
                # "length" must also emit "done" — otherwise callers waiting
                # for the done event would hang when the model hits
                # max_tokens mid-stream.
                if finish in ("stop", "tool_calls", "length"):
                    for entry in tool_call_buffer.values():
                        yield {
                            "type": "tool_call",
                            "tool": entry["name"],
                            "args": "".join(entry["args_parts"]),
                        }
                    tool_call_buffer.clear()
                    yield {
                        "type": "done",
                        "content": accumulated,
                        "finish_reason": finish,
                    }
                    return

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
        """
        import httpx

        _validate_request(messages, generation_params)

        url = f"{self.base_url}/v1/chat/completions"
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        async with httpx.AsyncClient(timeout=httpx.Timeout(self.request_timeout_seconds, read=60)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    # Drain the body so we can include the API's
                    # diagnostic in the raised error.
                    body = await resp.aread()
                    raise _format_http_error(resp.status_code, url, body)
                accumulated = ""
                tool_call_buffer: dict[int, dict] = {}
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if line == "[DONE]":
                        yield {"type": "done", "content": accumulated}
                        return
                    try:
                        import json as _json
                        chunk = _json.loads(line)
                    except Exception:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    # Handle reasoning_content (MiniMax reasoning_split mode).
                    # Chain-of-thought is yielded as a "thinking" event but is
                    # NOT mixed into the final "content" — downstream consumers
                    # that wait for the final string should get only the answer.
                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        yield {"type": "thinking", "text": delta["reasoning_content"]}
                    # Handle regular content (only this goes into accumulated)
                    if "content" in delta and delta["content"]:
                        accumulated += delta["content"]
                        yield {"type": "content", "text": delta["content"]}

                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_call_buffer:
                                tool_call_buffer[idx] = {
                                    "id": tc.get("id", ""),
                                    "name": "",
                                    "args_parts": [],
                                }
                            entry = tool_call_buffer[idx]
                            if "id" in tc and tc["id"]:
                                entry["id"] = tc["id"]
                            func = tc.get("function", {})
                            if "name" in func and func["name"]:
                                entry["name"] = func["name"]
                            if "arguments" in func and func["arguments"]:
                                entry["args_parts"].append(func["arguments"])

                    finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
                    # "length" must also emit "done" — otherwise callers waiting
                    # for the done event would hang when the model hits
                    # max_tokens mid-stream.
                    if finish in ("stop", "tool_calls", "length"):
                        for entry in tool_call_buffer.values():
                            yield {
                                "type": "tool_call",
                                "tool": entry["name"],
                                "args": "".join(entry["args_parts"]),
                            }
                        tool_call_buffer.clear()
                        yield {
                            "type": "done",
                            "content": accumulated,
                            "finish_reason": finish,
                        }
                        return

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

        url = f"{self.base_url}/v1/chat/completions"
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        async with httpx.AsyncClient(timeout=httpx.Timeout(self.request_timeout_seconds, read=60)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise _format_http_error(resp.status_code, url, resp.content)
            data = resp.json()
            return data["choices"][0]["message"]["content"]
