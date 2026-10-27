"""LLMClient base class + process-level client memo (canonical home).

Moved from ``foundation/llm_client.py`` in the dual-stack merge
(see docs/designs/foundation-llm-merge-streamable-split.md).
Imports stay inside ``foundation/llm/`` - no ``..llm_client`` cycle.
"""

import hashlib
import json
import os
import re
import threading
from typing import Any

from .budget_decorator import check_token_budget
from .errors import LLMNotConfiguredError
from .resolver import resolve_chat_llm, resolver_enabled
from .spec import LLMSpec
from .token_budget import TokenBudgetChecker, TokenBudgetConfig

# Process-level client memo: from_config is called on every LLM-layer
# request (lint/gaps). Rebuilding clients is pure overhead once config
# is unchanged. Key is a hash of LLM config + relevant env — never
# stores raw secrets in the key string.
_CLIENT_MEMO: dict[str, "LLMClient"] = {}
_CLIENT_MEMO_LOCK = threading.Lock()


def _client_memo_key(llm_cfg: dict[str, Any]) -> str:
    payload = {
        "enabled": llm_cfg.get("enabled"),
        "provider": os.environ.get("LLM_PROVIDER") or llm_cfg.get("provider"),
        "model": os.environ.get("LLM_MODEL") or llm_cfg.get("model"),
        "base_url": os.environ.get("LLM_BASE_URL") or llm_cfg.get("base_url"),
        "context_window": llm_cfg.get("context_window"),
        "budget_on_exceed": llm_cfg.get("budget_on_exceed"),
        "api_key_fingerprint": hashlib.sha256(
            (
                os.environ.get("LLM_API_KEY")
                or str(llm_cfg.get("api_key") or "")
            ).encode()
        ).hexdigest()[:16],
        "legacy_fallback": os.environ.get("LLM_LEGACY_FALLBACK"),
    }
    return json.dumps(payload, sort_keys=True)


def clear_llm_client_memo() -> None:
    """Drop cached clients (e.g. after config reload)."""
    with _CLIENT_MEMO_LOCK:
        _CLIENT_MEMO.clear()


def _legacy_fallback_enabled() -> bool:
    """Return True if the historical gpt-4o / openai defaults are accepted.

    Set ``LLM_LEGACY_FALLBACK=true`` to keep the old behaviour
    where ``LLMClient()`` constructs with default provider/model
    even when no config is provided. Default is ``false`` —
    ``LLMClient()`` raises ``LLMNotConfiguredError`` instead.
    """
    val = os.environ.get("LLM_LEGACY_FALLBACK", "false").strip().lower()
    return val in ("true", "1", "yes", "on")


class LLMClient:
    """Minimal client for OpenAI-compatible APIs.

    Supports any provider with a /v1/chat/completions endpoint:
    OpenAI, Ollama, LocalAI, vLLM, LM Studio, etc.

    Token budget checking is applied automatically via decorator.
    Pass ``_prompt_name="..."`` in generation_params to label calls in logs.
    """

    def __init__(
        self,
        provider: str | None = None,
        base_url: str = "",
        api_key: str = "",
        model: str | None = None,
        context_window: int | None = None,
        budget_on_exceed: str = "warn",
        request_timeout_seconds: float = 120,
    ):
        # LAL (PR 4): default provider/model are None. LAL raises
        # LLMNotConfiguredError on missing config; the historical
        # gpt-4o / openai defaults are removed. Set
        # LLM_LEGACY_FALLBACK=true to keep the old behaviour for
        # one release as a kill switch.
        if not _legacy_fallback_enabled():
            if provider is None:
                raise LLMNotConfiguredError(
                    "LLMClient() requires a provider; pass provider=... "
                    "or use LLMClient.from_spec(LLMSpec(...))."
                )
            if model is None:
                raise LLMNotConfiguredError(
                    "LLMClient() requires a model; pass model=... or "
                    "use LLMClient.from_spec(LLMSpec(...))."
                )
        else:
            provider = provider or "openai"
            model = model or "gpt-4o"
        self.provider = provider
        self.base_url = (
            base_url.rstrip("/") if base_url else self._default_base_url(provider)
        )
        self.api_key = api_key
        self.model = model
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
        }
        return defaults.get(provider, "https://api.openai.com")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LLMClient":
        """Create from merged config (supports env var overrides).

        LAL: delegates to ``resolve_chat_llm`` (the single resolver
        entry point) when ``LLM_USE_RESOLVER`` is not set to
        ``"false"``. The original validation rules (``enabled``
        check, ``api_key`` presence) are preserved unchanged.

        Clients are memoized per config/env fingerprint so repeated
        calls do not rebuild the HTTP client. Use
        :func:`clear_llm_client_memo` after config reload.
        """
        llm_cfg = config.get("llm", {})
        memo_key = _client_memo_key(llm_cfg)
        with _CLIENT_MEMO_LOCK:
            hit = _CLIENT_MEMO.get(memo_key)
            if hit is not None:
                return hit

        # Check if LLM is enabled
        if not llm_cfg.get("enabled", False):
            raise ValueError("LLM is not enabled. Set llm.enabled=true in config.")

        if resolver_enabled():
            spec = resolve_chat_llm(config)
            if not spec.api_key:
                raise ValueError(
                    "LLM API key not configured. Set api_key or LLM_API_KEY env var."
                )
            client = cls.from_spec(spec)
            with _CLIENT_MEMO_LOCK:
                _CLIENT_MEMO[memo_key] = client
            return client

        # Resolve API key: env:VAR_NAME syntax or literal value
        api_key = llm_cfg.get("api_key", "")
        if isinstance(api_key, str) and api_key.startswith("env:"):
            var_name = api_key[4:]
            api_key = os.environ.get(var_name, "")

        # Env var overrides
        api_key = os.environ.get("LLM_API_KEY", api_key)
        base_url = os.environ.get("LLM_BASE_URL", llm_cfg.get("base_url", ""))
        model = os.environ.get("LLM_MODEL", llm_cfg.get("model", "gpt-4o"))
        provider = os.environ.get("LLM_PROVIDER", llm_cfg.get("provider", "openai"))

        if not api_key:
            raise ValueError(
                "LLM API key not configured. Set api_key or LLM_API_KEY env var."
            )

        client = cls(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            context_window=llm_cfg.get("context_window"),
            budget_on_exceed=llm_cfg.get("budget_on_exceed", "warn"),
        )
        with _CLIENT_MEMO_LOCK:
            _CLIENT_MEMO[memo_key] = client
        return client

    @classmethod
    def from_spec(cls, spec: "LLMSpec") -> "LLMClient":
        """Build a client from a fully-resolved ``LLMSpec``.

        LAL: this is the canonical construction path for code that
        has already resolved LLM configuration via
        ``resolve_chat_llm``. Unlike ``from_config`` it does NOT
        re-parse env vars, ``enabled`` flags, or validate
        ``api_key`` — it trusts the spec.
        """
        return cls(
            provider=spec.provider,
            base_url=spec.base_url,
            api_key=spec.api_key,
            model=spec.model,
            context_window=spec.context_window,
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

    @check_token_budget(lambda self: self._budget_checker)
    def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Send chat completion request.

        Args:
            messages: List of {role, content} dicts
            json_mode: If True, request JSON response format
            **generation_params: Optional params like temperature, max_tokens, top_p
                Use _prompt_name="..." to label this call in budget logs.

        Returns:
            Assistant response text
        """
        try:
            import requests
        except ImportError:
            raise ImportError(
                "requests is required for LLM client: pip install requests"
            ) from None

        url = (
            f"{self.base_url}/chat/completions"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/chat/completions"
        )

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

        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.request_timeout_seconds
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"LLM API request failed: {e}") from e
        except (KeyError, IndexError) as e:
            raise ValueError(f"Unexpected LLM API response format: {e}") from e

    @check_token_budget(lambda self: self._budget_checker)
    def chat_json(
        self,
        messages: list[dict[str, str]],
        **generation_params: Any,
    ) -> Any:
        """Send chat completion and parse JSON response.

        Handles markdown code blocks: ```json\n{...}\n```
        """
        raw = self.chat(messages, json_mode=True, **generation_params)
        return self._parse_json_response(raw)

    @staticmethod
    def _parse_json_response(raw: str) -> Any:
        """Extract JSON from potentially markdown-wrapped response."""
        # Strip <think> blocks (minimax thinking mode) — sometimes the LLM
        # returns thinking text without a JSON code block after it.
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON array or object in text
        for pattern in (r"\[.*\]", r"\{.*\}"):
            match = re.search(pattern, raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass

        raise ValueError(f"Could not parse JSON from LLM response:\n{raw}")
