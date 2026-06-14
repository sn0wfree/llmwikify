"""LLM utilities — token estimation, budget checking, context window resolution.

No external dependencies required beyond tiktoken (optional, falls back to
heuristic estimation if not installed).

Re-exports of ``LLMClient`` and ``StreamableLLMClient`` are available
via PEP 562 lazy module ``__getattr__`` (defined at the bottom of this
file), which defers the import to break the cycle with the legacy
``llmwikify.foundation.llm_client`` module. Use::

    from llmwikify.foundation.llm import StreamableLLMClient   # canonical
    from llmwikify.foundation.llm import LLMClient              # base class (lazy)
    from llmwikify.foundation.llm import LLMSpec                # LAL spec
    from llmwikify.foundation.llm import resolve_chat_llm       # LAL resolver
"""

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
    """Lazy re-export of LLMClient and StreamableLLMClient (PEP 562).

    Triggered by ``from llmwikify.foundation.llm import X`` when X is not in
    this module's namespace. Avoids the eager-import cycle:

      llm_client.py → llm.budget_decorator → llm/__init__.py
        → streamable.py → llm_client.LLMClient   ← still loading!
    """
    if name == "LLMClient":
        from ..llm_client import LLMClient
        return LLMClient
    if name == "StreamableLLMClient":
        from .streamable import StreamableLLMClient
        return StreamableLLMClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Clients (lazy re-exports via __getattr__)
    "LLMClient",
    "StreamableLLMClient",
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
