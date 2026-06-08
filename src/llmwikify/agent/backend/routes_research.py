"""Backward-compat shim: ``llmwikify.agent.backend.routes_research`` →
``llmwikify.interfaces.server.http.research`` (v0.32 Phase 9).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.interfaces.server.http.research import *  # noqa: F401, F403
