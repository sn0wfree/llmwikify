"""Backward-compat shim for the old ``llmwikify.web`` package.

The web interface was moved to ``llmwikify.interfaces.web`` as
part of the 4-layer refactor (Batch A2). This shim preserves
the old import path until v0.33.0 cleanup.

Prefer the new path for new code.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "llmwikify.web is moved to llmwikify.interfaces.web in the "
    "4-layer refactor. Update your imports.",
    DeprecationWarning,
    stacklevel=2,
)
