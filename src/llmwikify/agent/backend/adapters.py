"""LLM Adapter Layer - Supports streaming + function calling for Agent."""

from __future__ import annotations

import os
from typing import Any


class StreamableLLMClient:
    """LLM client with streaming and function calling support.

    Wraps existing LLMClient and extends it with:
    - stream_chat(): SSE-compatible streaming
    - chat_with_tools(): Function calling support
    """

    def __init__(
        self,
        provider: str = "openai",
        base_url: str = "",
        api_key: str = "",
        model: str = "gpt-4o",
        reasoning_split: bool = False,
        auth_header: str = "bearer",
    ):
        self.provider = provider
        raw_base = base_url if base_url else self._default_base_url(provider)
        self.base_url = raw_base.rstrip("/").removesuffix("/v1")
        self.api_key = api_key
        self.model = model
        self.reasoning_split = reasoning_split
        self.auth_header = auth_header  # "bearer" or "api-key"

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
        from .providers.registry import create_llm

        return create_llm(config)

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with appropriate auth scheme."""
        headers = {"Content-Type": "application/json"}
        if self.auth_header == "api-key":
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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

        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

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

        resp = requests.post(url, headers=headers, json=payload, timeout=120)
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

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ):
        """Streaming chat completion (yield chunks).

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

        with requests.post(url, headers=headers, json=payload, timeout=120, stream=True) as resp:
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
                if finish in ("stop", "tool_calls"):
                    yield {"type": "done", "content": accumulated}
                    return