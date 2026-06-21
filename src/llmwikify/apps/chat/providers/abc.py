"""Phase 16 — LLMProvider ABC + ProviderConfig + RetryMode + ThinkingStyle
(borrowed from nanobot v0.2.1).

借鉴 nanobot v0.2.1 ``providers/base.py`` (~843 LOC) 设计：

  - ``LLMProvider`` ABC — 替代既有 ``Protocol``\uff0c\u589e\u52a0 ``apply_snapshot()`` hot-swap\u3001\u7edf\u4e00 ``from_config()`` factory\u3001thinking_style \u8c03\u7528\u70b9
  - ``ProviderConfig`` dataclass — 替代\u88f8 dict\uff0c\u7edf\u4e00\u5b57\u6bb5\uff08provider/model/api_key/base_url/enabled/retry_mode/thinking_style/max_tokens/temperature\uff09
  - ``RetryMode`` enum — 4 \u79cd\u91cd\u8bd5\u7b56\u7565\uff08transient / persistent / off / aggressive\uff09\uff0c\u5bf9\u5e94 nanobot ``provider_retry_mode``
  - ``ThinkingStyle`` enum — 10+ \u98ce\u683c\uff08minimal/detailed/step_by_step/budget_aware/code_first/...)\uff0cbuild_thinking_extra_body \u51fd\u6570\u8d70 vendor

\u8bbe\u8ba1\u539f\u5219\uff1a

  - **\u5411\u540e\u517c\u5bb9** — \u65e7 Provider \u4ec5\u7ee7\u627f ``BaseLLMProvider`` \u5e76\u4e0d\u52a8\uff1b\u65b0\u63d0\u4f9b ABC + dataclass + enums \u7ed9 future provider \u4f7f\u7528
  - **\u4e0d\u8986\u76d6\u65e7 Provider** — \u539f ``LLMProvider`` Protocol \u4fdd\u7559\uff1b\u65b0 ABC \u4ee5 ``LLMProviderABC`` \u522b\u540d\u63d0\u4f9b
  - **\u53ef\u6eaf\u6e90** — ProviderConfig \u4ece dict \u8f6c\u6362\u4fdd\u7559 ``from_dict``\uff0cregistry \u63a5\u53e7\u4e0d\u53d8
  - **\u96f6\u4fb5\u5165\u7f3a\u7701** — ``apply_snapshot()`` \u9ed8\u8ba4 noop\uff0cBaseLLMProvider \u9ed8\u8ba4 thinking_style=MINIMAL
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from llmwikify.foundation.llm.streamable import StreamableLLMClient


# ─── Enums ──────────────────────────────────────────────────────


class RetryMode(str, Enum):
    """Provider-level retry strategy (borrowed from nanobot v0.2.1).

    Maps onto nanobot's ``provider_retry_mode`` env. Each mode tells
    the underlying ``StreamableLLMClient`` which errors to retry and
    how aggressively.
    """

    TRANSIENT = "transient"
    """Default: retry 429 / 5xx / connection errors with exponential
    backoff. Same errors only — no billing-related (insufficient_quota,
    payment_required) retry."""

    PERSISTENT = "persistent"
    """Like TRANSIENT but also retry billing errors after a long wait
    (``identical_error_limit=10`` in nanobot). For dev / cost-tolerant
    setups that want maximum resilience."""

    OFF = "off"
    """Disable all automatic retries. The caller decides what to do
    with each error."""

    AGGRESSIVE = "aggressive"
    """Retry everything including non-retryable 4xx (other than 429).
    Use only for tests / CI where you want to maximize call attempts.
    Production should stick with TRANSIENT."""


class ThinkingStyle(str, Enum):
    """Vendor of thinking_style settings (borrowed from nanobot v0.2.1).

    Each style maps to a ``build_thinking_extra_body`` override set
    used by the underlying LLM client. ``MINIMAL`` is the default and
    matches what most providers do out of the box; the other styles
    opt into richer / cheaper / more guided reasoning.

    Borrowed mapping (nanobot ``build_thinking_extra_body``):
      - minimal        → empty extras
      - detailed       → high reasoning_effort
      - step_by_step   → step markers in prompt
      - budget_aware   → token budget respected
      - code_first     → code-friendly reasoning
      - compact        → short / fast
      - exhaustive     → max reasoning_effort + low temperature
      - analytical     → chain-of-thought explicit
      - summary_first  → plan + summary
      - tool_first     → tool selection over prose
      - safe_first     → conservative / refuse-when-unsure
    """

    MINIMAL = "minimal"
    DETAILED = "detailed"
    STEP_BY_STEP = "step_by_step"
    BUDGET_AWARE = "budget_aware"
    CODE_FIRST = "code_first"
    COMPACT = "compact"
    EXHAUSTIVE = "exhaustive"
    ANALYTICAL = "analytical"
    SUMMARY_FIRST = "summary_first"
    TOOL_FIRST = "tool_first"
    SAFE_FIRST = "safe_first"

    @classmethod
    def default(cls) -> ThinkingStyle:
        """The default style when none is configured."""
        return cls.MINIMAL

    def extra_body(self) -> dict[str, Any]:
        """Return the ``extra_body`` fields this style implies.

        Mirrors nanobot v0.2.1 ``build_thinking_extra_body`` for the
        subset of styles most commonly needed. Styles that don't map
        cleanly to ``extra_body`` (e.g. ``step_by_step`` is a prompt
        injection) return empty dict; the provider's
        ``thinking_style_prompt()`` method handles those.
        """
        if self == ThinkingStyle.MINIMAL:
            return {}
        if self == ThinkingStyle.DETAILED:
            return {"reasoning_effort": "high"}
        if self == ThinkingStyle.EXHAUSTIVE:
            return {
                "reasoning_effort": "high",
                "temperature": 0.2,
            }
        if self == ThinkingStyle.BUDGET_AWARE:
            return {"reasoning_effort": "medium"}
        if self == ThinkingStyle.COMPACT:
            return {"reasoning_effort": "low"}
        # Styles that depend on prompt injection (returned empty;
        # provider's thinking_style_prompt() may add to messages).
        return {}


# ─── ProviderConfig ────────────────────────────────────────────


@dataclass
class ProviderConfig:
    """Typed provider configuration (replaces naked dicts).

    Borrowed from nanobot v0.2.1 ``provider_retry_mode`` /
    ``thinking_style`` / etc. but kept llmwikify-specific:

      - ``provider`` — the registry key (e.g. ``"minimax"``).
      - ``model`` — model name; provider's ``default_model()`` if empty.
      - ``api_key`` — may be ``"env:VAR_NAME"`` to read from env at runtime.
      - ``base_url`` — provider's ``default_base_url()`` if empty.
      - ``enabled`` — when ``False``, ``from_config()`` raises
        ``LLMNotConfiguredError`` (mirrors the existing
        ``create_llm()`` semantics).
      - ``retry_mode`` — see ``RetryMode``.
      - ``thinking_style`` — see ``ThinkingStyle``.
      - ``max_tokens`` — per-response token cap (None = provider default).
      - ``temperature`` — sampling temperature (None = provider default).
      - ``extra`` — free-form passthrough for provider-specific knobs
        (e.g. ``{"top_p": 0.9}``).

    Use ``ProviderConfig.from_dict`` to convert from the existing
    raw-config-dict shape (``{"llm": {...}}`` or ``{"provider": "..."}``)
    so existing config files keep working without migration.
    """

    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    enabled: bool = False
    retry_mode: RetryMode = RetryMode.TRANSIENT
    thinking_style: ThinkingStyle = ThinkingStyle.MINIMAL
    max_tokens: int | None = None
    temperature: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderConfig:
        """Convert a raw config dict into a ``ProviderConfig``.

        Accepts two common shapes:

          - ``{"provider": "...", "model": "...", "api_key": "..."}``
            (top-level)
          - ``{"llm": {"provider": "...", "model": "...", ...}}``
            (wrapped, mirrors ``create_llm()`` argument shape)

        Unknown keys land in ``extra`` so provider-specific knobs
        survive the round-trip.
        """
        if not isinstance(data, dict):
            return cls()
        inner = data.get("llm") if isinstance(data.get("llm"), dict) else data
        if not isinstance(inner, dict):
            inner = {}
        known = {
            "provider", "model", "api_key", "base_url", "enabled",
            "retry_mode", "thinking_style", "max_tokens", "temperature",
        }
        kwargs: dict[str, Any] = {
            k: v for k, v in inner.items() if k in known
        }
        # Coerce enum fields; tolerate bad values (fall back to default).
        if "retry_mode" in kwargs:
            try:
                kwargs["retry_mode"] = RetryMode(kwargs["retry_mode"])
            except ValueError:
                kwargs.pop("retry_mode")
        if "thinking_style" in kwargs:
            try:
                kwargs["thinking_style"] = ThinkingStyle(
                    kwargs["thinking_style"],
                )
            except ValueError:
                kwargs.pop("thinking_style")
        if "enabled" in kwargs:
            kwargs["enabled"] = bool(kwargs["enabled"])
        if "max_tokens" in kwargs and kwargs["max_tokens"] is not None:
            try:
                kwargs["max_tokens"] = int(kwargs["max_tokens"])
            except (TypeError, ValueError):
                kwargs.pop("max_tokens")
        if "temperature" in kwargs and kwargs["temperature"] is not None:
            try:
                kwargs["temperature"] = float(kwargs["temperature"])
            except (TypeError, ValueError):
                kwargs.pop("temperature")
        # Extra fields
        extras = {k: v for k, v in inner.items() if k not in known}
        if extras:
            kwargs["extra"] = extras
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Round-trip back to the raw shape. Useful for ``/api/health``
        and config persistence."""
        out: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "enabled": self.enabled,
            "retry_mode": self.retry_mode.value,
            "thinking_style": self.thinking_style.value,
        }
        if self.api_key:
            out["api_key"] = self.api_key
        if self.base_url:
            out["base_url"] = self.base_url
        if self.max_tokens is not None:
            out["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.extra:
            out.update(self.extra)
        return out

    def is_configured(self) -> bool:
        """True iff enabled + has provider + has API key (or env var set)."""
        if not self.enabled or not self.provider:
            return False
        if self.api_key.startswith("env:"):
            import os
            return bool(os.environ.get(self.api_key[4:], ""))
        return bool(self.api_key)


# ─── LLMProviderABC ────────────────────────────────────────────


class LLMProviderABC(ABC):
    """Abstract base class for LLM providers (Phase 16, optional).

    Compared to the existing ``LLMProvider`` Protocol in ``base.py``,
    the ABC adds:

      - ``apply_snapshot()`` — runtime hot-swap (model/api_key/...)
      - ``supported_retry_modes()`` — class-level capability check
      - ``thinking_style_prompt()`` — style-specific prompt injection

    Existing providers (``MiniMaxProvider`` / ``XiaomiProvider``)
    keep using ``BaseLLMProvider`` + the Protocol; this ABC is for
    **future** providers that want the full snapshot / style /
    retry surface.

    Borrowed from nanobot v0.2.1 ``providers/base.py`` design:
      - ABC + classmethod factory (mirrors nanobot ``from_config``)
      - ``apply_snapshot()`` for hot-swap (mirrors nanobot
        ``apply_snapshot``)
      - ``thinking_style_extra_body()`` for style overrides
        (mirrors nanobot ``build_thinking_extra_body``)
    """

    #: Class-level identifier. Default = ``cls.provider_name()``.
    name: ClassVar[str] = ""

    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier string (e.g. ``"minimax"``)."""

    @abstractmethod
    def default_model(self) -> str:
        """Return the default model name for this provider."""

    @abstractmethod
    def default_base_url(self) -> str:
        """Return the default base URL for this provider."""

    @abstractmethod
    def supported_models(self) -> list[str]:
        """Return list of supported model names for this provider."""

    @abstractmethod
    def from_config(
        self, config: dict[str, Any] | ProviderConfig,
    ) -> StreamableLLMClient:
        """Build a ``StreamableLLMClient`` from a config (dict or typed).

        Accepts either a raw dict (legacy compat) or a ``ProviderConfig``
        (typed, recommended). When a dict is passed, it's converted
        via ``ProviderConfig.from_dict`` internally.
        """

    # ── capability checks (class-level metadata) ─────────────

    def supported_retry_modes(self) -> list[RetryMode]:
        """Return the retry modes this provider supports.

        Default: ``[TRANSIENT]`` only (most providers don't want
        PERSISTENT to mask billing issues). Override to widen.
        """
        return [RetryMode.TRANSIENT]

    def supported_thinking_styles(self) -> list[ThinkingStyle]:
        """Return the thinking styles this provider supports.

        Default: all ``ThinkingStyle`` values (most providers can
        accept the prompt-level overrides even if they don't have
        native extended-thinking knobs). Override to narrow.
        """
        return list(ThinkingStyle)

    # ── runtime hot-swap (Phase 16) ──────────────────────────

    def apply_snapshot(self, snapshot: ProviderConfig | dict[str, Any]) -> None:  # noqa: B027
        """Hot-swap runtime config (model / api_key / base_url).

        Default implementation is a **noop** — the default provider
        builds the ``StreamableLLMClient`` once in ``from_config`` and
        doesn't hold mutable state. Providers that keep config on
        ``self`` for re-resolution should override.

        Note: this is intentionally not decorated ``@abstractmethod``
        so existing Protocol-based providers (``MiniMaxProvider``,
        ``XiaomiProvider``) can adopt the ABC without forcing an
        override. The ``# noqa: B027`` suppresses the ruff warning
        that would otherwise flag an empty ABC method.

        Borrowed from nanobot v0.2.1 ``apply_snapshot`` semantics:
        the provider updates its internal state without rebuilding
        the underlying HTTP client (to preserve connection pools).
        """
        # noop default

    # ── thinking style ───────────────────────────────────────

    def thinking_style_prompt(self, style: ThinkingStyle) -> str:
        """Return the prompt-level override for a thinking style.

        Default empty string (most styles are handled via
        ``ThinkingStyle.extra_body()``). Providers that need
        prompt injection (e.g. ``STEP_BY_STEP``) override.
        """
        return ""


__all__ = [
    "RetryMode",
    "ThinkingStyle",
    "ProviderConfig",
    "LLMProviderABC",
]
