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
    ):
        self.provider = provider
        self.base_url = base_url.rstrip("/") if base_url else self._default_base_url(provider)
        self.api_key = api_key
        self.model = model

    @staticmethod
    def _default_base_url(provider: str) -> str:
        defaults = {
            "openai": "https://api.openai.com",
            "ollama": "http://localhost:11434/v1",
            "lmstudio": "http://localhost:1234/v1",
        }
        return defaults.get(provider, "https://api.openai.com")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "StreamableLLMClient":
        llm_cfg = config.get("llm", {})
        if not llm_cfg.get("enabled", False):
            raise ValueError("LLM is not enabled. Set llm.enabled=true in config.")

        api_key = llm_cfg.get("api_key", "")
        if isinstance(api_key, str) and api_key.startswith("env:"):
            api_key = os.environ.get(api_key[4:], "")

        api_key = os.environ.get("LLM_API_KEY", api_key)
        base_url = os.environ.get("LLM_BASE_URL", llm_cfg.get("base_url", ""))
        model = os.environ.get("LLM_MODEL", llm_cfg.get("model", "gpt-4o"))
        provider = os.environ.get("LLM_PROVIDER", llm_cfg.get("provider", "openai"))

        if not api_key:
            raise ValueError("LLM API key not configured.")

        return cls(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

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
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
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
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

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
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

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