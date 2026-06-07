"""Backward-compat shim for ``llmwikify.server.create_unified_server``.

Per Batch B2 of the 4-layer refactor, ``server/`` moved to
``interfaces/server/``. The ``create_unified_server`` factory
function is now defined in ``llmwikify.interfaces.server``
(where ``WikiServer`` lives). External code that imported the
factory from the old ``llmwikify.server`` module should switch
to ``llmwikify.interfaces.server``.

This module preserves the old entry point until v0.33.0 and
emits a ``DeprecationWarning``.
"""
from __future__ import annotations

import warnings

from llmwikify.interfaces.server import (  # noqa: F401
    create_unified_server,
)

warnings.warn(
    "llmwikify.server.create_unified_server is moved to "
    "llmwikify.interfaces.server.create_unified_server in the "
    "4-layer refactor. Update your imports. This shim will be "
    "removed in v0.33.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["create_unified_server"]
