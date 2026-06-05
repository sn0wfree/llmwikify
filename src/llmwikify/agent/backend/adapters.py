"""DEPRECATED shim for StreamableLLMClient.

This module is preserved for backward compatibility and will be
removed in v0.33.0 (1 release cycle per PLAN.md / Phase 1 #1).

The canonical home for :class:`StreamableLLMClient` is now
``llmwikify.llm.streamable``. Update imports to::

    from llmwikify.llm.streamable import StreamableLLMClient
"""

from __future__ import annotations

import warnings

from llmwikify.llm.streamable import StreamableLLMClient

warnings.warn(
    "llmwikify.agent.backend.adapters is deprecated. "
    "Import StreamableLLMClient from llmwikify.llm.streamable instead. "
    "This shim will be removed in v0.33.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["StreamableLLMClient"]
