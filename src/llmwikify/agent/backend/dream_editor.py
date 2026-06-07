"""Backward-compat shim: ``llmwikify.agent.backend.dream_editor`` →
``llmwikify.apps.agent.dream_editor`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.dream_editor import *  # noqa: F401, F403
