"""Backward-compat shim: ``llmwikify.agent.backend.memory`` →
``llmwikify.apps.agent.memory`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.memory import *  # noqa: F401, F403
