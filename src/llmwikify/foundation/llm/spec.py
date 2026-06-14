"""LLMSpec — the canonical, immutable LLM configuration contract.

Part of the LLM Access Layer (LAL). See
``docs/designs/llm-access-layer.md`` for the full design.

``LLMSpec`` is the single source of truth for *what LLM to use*. All
callers — Chat orchestrator, subagent drivers, kernel engines, workflow
actors — receive a fully-resolved ``LLMSpec`` and never parse config
themselves. The resolver (``foundation.llm.resolver.resolve_chat_llm``)
is the only function allowed to construct one.

Design contract:

- ``frozen=True`` — downstream code cannot mutate fields. To change a
  field, callers must use ``dataclasses.replace(llm_spec, model=...)``
  to produce a new instance.
- ``source`` — records where the values came from (``"ui"``,
  ``"env"``, ``"config"``, ``"merged"``). Useful for observability
  and debugging "why is the model X?".
- ``extra_headers`` uses ``default_factory=dict`` so each instance has
  its own dict (frozen=True only prevents rebinding, not mutation of
  mutable contents). Callers MUST NOT mutate the dict in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMSpec:
    """Immutable LLM configuration contract.

    All fields are required unless noted. Construction is normally
    done by ``resolve_chat_llm(config)``; direct construction is
    allowed for tests and explicit override paths (e.g. a workflow
    actor that wants a different model than the parent).
    """

    provider: str
    base_url: str
    api_key: str
    model: str
    context_window: int | None
    timeout: float
    reasoning_split: bool
    auth_scheme: str  # "bearer" | "api-key"
    budget_on_exceed: str = "warn"  # "warn" | "raise" | "truncate"
    extra_headers: dict[str, str] = field(default_factory=dict)
    source: str = "config"  # "ui" | "env" | "config" | "merged" | "test"

    def to_client_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for ``StreamableLLMClient.__init__``.

        This is the bridge between ``LLMSpec`` and the existing client
        constructor. It does NOT include ``api_key`` redaction — the
        spec holds the real key and the client receives it directly.
        """
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "context_window": self.context_window,
            "request_timeout_seconds": self.timeout,
            "reasoning_split": self.reasoning_split,
            "auth_header": self.auth_scheme,
            "budget_on_exceed": self.budget_on_exceed,
        }

    def with_model_override(self, model: str) -> LLMSpec:
        """Return a new ``LLMSpec`` with ``model`` replaced.

        Used by workflow subagent drivers to apply an actor's
        ``actor.model`` override on top of an inherited spec.
        """
        if model == self.model:
            return self
        from dataclasses import replace
        return replace(self, model=model)


__all__ = ["LLMSpec"]
