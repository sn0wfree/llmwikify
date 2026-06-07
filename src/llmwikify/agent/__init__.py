"""Backward-compat shim: ``llmwikify.agent`` → ``llmwikify.apps.agent``.

Per Batch B4 of the 4-layer refactor, the agent/ package moved
to apps/agent/ (L3 layer). This shim preserves the old import
path until v0.33.0.
"""

from __future__ import annotations

import warnings

from llmwikify.apps.agent import WikiAgent  # noqa: F401

warnings.warn(
    "llmwikify.agent is moved to llmwikify.apps.agent in the 4-layer "
    "refactor. Update your imports. This shim will be removed in v0.33.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["WikiAgent"]
