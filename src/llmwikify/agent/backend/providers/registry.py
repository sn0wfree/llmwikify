"""Backward-compat shim: ``llmwikify.agent.backend.providers.registry`` →
``llmwikify.apps.chat.providers.registry`` (v0.32 Phase 4).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.providers.registry import *  # noqa: F401, F403
