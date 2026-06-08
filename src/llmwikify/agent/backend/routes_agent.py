"""Backward-compat shim: ``llmwikify.agent.backend.routes_agent`` →
``llmwikify.interfaces.server.http.chat_sse`` (v0.32 Phase 9).

Phase 9 moved the 3 REST route modules from
``apps/agent/routes/`` (L3) to ``interfaces/server/http/``
(L4 — their natural home). The ``agent.py`` route was
renamed to ``chat_sse.py`` (since the SSE stream is a
chat feature, not an agent feature).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.interfaces.server.http.chat_sse import *  # noqa: F401, F403
