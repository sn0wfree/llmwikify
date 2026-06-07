"""Backward-compat shim: ``llmwikify.agent.backend.runner`` →
``llmwikify.apps.agent.core.runner`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.core.runner import *  # noqa: F401, F403
