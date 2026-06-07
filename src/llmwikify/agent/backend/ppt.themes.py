"""Backward-compat shim: ``llmwikify.agent.backend.ppt.themes`` →
``llmwikify.apps.ppt.themes`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.ppt.themes import *  # noqa: F401, F403
