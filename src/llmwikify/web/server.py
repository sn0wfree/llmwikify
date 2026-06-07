"""Backward-compat shim for the old ``llmwikify.web.server`` path.

The web server entry point was moved to
``llmwikify.interfaces.web.server`` as part of the 4-layer
refactor (Batch A2). This shim preserves the old import path
until v0.33.0 cleanup.

Prefer the new path for new code.
"""
from __future__ import annotations

import warnings

from llmwikify.interfaces.web.server import main  # noqa: F401

warnings.warn(
    "llmwikify.web.server is moved to llmwikify.interfaces.web.server "
    "in the 4-layer refactor. Update your imports.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["main"]
