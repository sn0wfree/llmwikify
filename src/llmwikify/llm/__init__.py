"""LLM utilities — token estimation, budget checking, context window resolution.

No external dependencies required beyond tiktoken (optional, falls back to
heuristic estimation if not installed).
"""

from .context_windows import (
    CONTEXT_WINDOWS,
    ask_llm_context_window,
    probe_provider_api,
    resolve_context_window,
)
from .token_budget import (
    TokenBudgetChecker,
    TokenBudgetConfig,
    TokenBudgetExceeded,
    TokenUsage,
)
from .token_estimator import count_messages, count_tokens

__all__ = [
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
