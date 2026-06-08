"""Backward-compat shim package: ``llmwikify.agent.backend.providers`` →
``llmwikify.apps.chat.providers`` (v0.32 Phase 4: providers
migrated from apps/agent/ to apps/chat/ to live alongside
ChatBase and the other LLM-consuming components).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.chat.providers import *  # noqa: F401, F403
