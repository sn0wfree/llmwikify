"""DEPRECATED compatibility shim — use ``llmwikify.foundation.llm.base``.

The ``LLMClient`` class, client memo, and legacy-fallback switch moved
to ``foundation/llm/base.py`` (dual-stack merge, 2026-10-23).
This module only re-exports them so existing imports keep working:

    from llmwikify.foundation.llm_client import LLMClient  # still works

Removal planned: next minor after kernel callers migrate
(analyzer / source_analysis / gap_filler / llm mixin).
See docs/designs/foundation-llm-merge-streamable-split.md.
"""

from .llm.base import (  # noqa: F401
    LLMClient,
    _client_memo_key,
    _legacy_fallback_enabled,
    clear_llm_client_memo,
)

__all__ = [
    "LLMClient",
    "clear_llm_client_memo",
    "_legacy_fallback_enabled",
    "_client_memo_key",
]
