"""Backward-compat shim: ``llmwikify.agent.backend.notifications`` →
``llmwikify.apps.agent.notifications`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.notifications import *  # noqa: F401, F403
