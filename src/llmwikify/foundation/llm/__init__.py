"""LLM utilities — token estimation, budget checking, context window resolution.

No external dependencies required beyond tiktoken (optional, falls back to
heuristic estimation if not installed).

``LLMClient`` lives in ``base.py`` (canonical home since the dual-stack
merge). ``StreamableLLMClient`` is re-exported lazily via PEP 562 to keep
``import llmwikify.foundation.llm`` light. Use::

    from llmwikify.foundation.llm import StreamableLLMClient   # canonical
    from llmwikify.foundation.llm import LLMClient              # base class
    from llmwikify.foundation.llm import LLMSpec                # LAL spec
    from llmwikify.foundation.llm import resolve_chat_llm       # LAL resolver
"""

from .base import LLMClient
from .budget_decorator import check_token_budget
from .context_windows import (
    CONTEXT_WINDOWS,
    ask_llm_context_window,
    probe_provider_api,
    resolve_context_window,
)
from .resolver import (
    PROVIDER_ALIASES,
    apply_provider_alias,
    resolve_chat_llm,
    resolver_enabled,
)
from .spec import LLMSpec
from .token_budget import (
    TokenBudgetChecker,
    TokenBudgetConfig,
    TokenBudgetExceeded,
    TokenUsage,
)
from .token_estimator import count_messages, count_tokens


def __getattr__(name: str):
    """Lazy re-export of StreamableLLMClient (PEP 562).

    Keeps the heavy streamable module (retry/SSE machinery) out of the
    import path when callers only need ``LLMClient`` / LAL helpers.
    """
    if name == "StreamableLLMClient":
        from .streamable import StreamableLLMClient

        return StreamableLLMClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Clients
    "LLMClient",
    "StreamableLLMClient",  # lazy via __getattr__
    # LAL (LLM Access Layer)
    "LLMSpec",
    "resolve_chat_llm",
    "resolver_enabled",
    "apply_provider_alias",
    "PROVIDER_ALIASES",
    # Decorator
    "check_token_budget",
    # Context windows
    "CONTEXT_WINDOWS",
    "resolve_context_window",
    "probe_provider_api",
    "ask_llm_context_window",
    # Token estimation
    "count_tokens",
    "count_messages",
    # Budget checking
    "TokenBudgetChecker",
    "TokenBudgetConfig",
    "TokenBudgetExceeded",
    "TokenUsage",
]
