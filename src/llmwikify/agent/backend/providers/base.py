"""Backward-compat shim: ``llmwikify.agent.backend.providers.base`` →
``llmwikify.apps.chat.providers.base`` (v0.32 Phase 4).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.providers.base import *  # noqa: F401, F403
