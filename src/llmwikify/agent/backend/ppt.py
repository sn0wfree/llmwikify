"""Backward-compat shim: ``llmwikify.agent.backend.ppt`` →
``llmwikify.apps.ppt`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.ppt import *  # noqa: F401, F403
