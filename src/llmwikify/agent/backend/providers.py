"""Backward-compat shim: ``llmwikify.agent.backend.providers`` →
``llmwikify.apps.agent.providers`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.providers import *  # noqa: F401, F403
