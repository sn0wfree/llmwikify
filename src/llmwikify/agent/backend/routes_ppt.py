"""Backward-compat shim: ``llmwikify.agent.backend.routes_ppt`` →
``llmwikify.interfaces.server.http.ppt`` (v0.32 Phase 9).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.interfaces.server.http.ppt import *  # noqa: F401, F403
