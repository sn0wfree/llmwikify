"""Backward-compat shim: ``llmwikify.agent.backend.providers.minimax`` →
``llmwikify.apps.agent.providers.minimax`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.providers.minimax import *  # noqa: F401, F403
