"""Backward-compat shim: ``llmwikify.agent.backend.routes`` →
``llmwikify.interfaces.server.http`` (v0.32 Phase 9).

The 3 REST route modules (``chat_sse``, ``ppt``, ``research``)
were moved from ``apps/agent/routes/`` (L3) to
``interfaces/server/http/`` (L4). The package-level
re-exports are preserved by this shim.

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.interfaces.server.http import (  # noqa: F401
    chat_sse,
    ppt,
    research,
)
