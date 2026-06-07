"""Backward-compat shim for the old ``llmwikify.autoresearch`` package.

Per Sprint C of the 4-layer refactor, the autoresearch
code moved to ``llmwikify.apps.chat``. This module preserves
the old import path until v0.33.0 and emits a
``DeprecationWarning`` so external users get a clear
migration signal.
"""
from __future__ import annotations

import warnings

from llmwikify.apps.chat import *  # noqa: F401, F403

warnings.warn(
    "llmwikify.autoresearch is moved to llmwikify.apps.chat in the "
    "4-layer refactor. Update your imports. This shim will be "
    "removed in v0.33.0.",
    DeprecationWarning,
    stacklevel=2,
)
