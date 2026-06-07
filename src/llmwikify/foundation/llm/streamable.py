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

import os
from typing import Any

from ..llm_client import LLMClient
from .budget_decorator import check_token_budget
from .token_budget import TokenBudgetChecker, TokenBudgetConfig


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
        provider: str = "openai",
        base_url: str = "",
        api_key: str = "",
        model: str = "gpt-4o",
        reasoning_split: bool = False,
        auth_header: str = "bearer",
        context_window: int | None = None,
        budget_on_exceed: str = "warn",
        request_timeout_seconds: float = 120,
    ):
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
    def from_config(cls, config: dict[str, Any]) -> "StreamableLLMClient":
        from llmwikify.agent.backend.providers.registry import create_llm

        return create_llm(config)

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
        resp.raise_for_status()
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
        resp.raise_for_status()
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
            resp.raise_for_status()
            accumulated = ""
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
                        func = tc.get("function", {})
                        yield {
                            "type": "tool_call",
                            "tool": func.get("name", ""),
                            "args": func.get("arguments", ""),
                        }

                finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
                # "length" must also emit "done" — otherwise callers waiting
                # for the done event would hang when the model hits
                # max_tokens mid-stream.
                if finish in ("stop", "tool_calls", "length"):
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
                resp.raise_for_status()
                accumulated = ""
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
                            func = tc.get("function", {})
                            yield {
                                "type": "tool_call",
                                "tool": func.get("name", ""),
                                "args": func.get("arguments", ""),
                            }

                    finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
                    # "length" must also emit "done" — otherwise callers waiting
                    # for the done event would hang when the model hits
                    # max_tokens mid-stream.
                    if finish in ("stop", "tool_calls", "length"):
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
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
