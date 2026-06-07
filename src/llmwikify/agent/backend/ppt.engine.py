"""Backward-compat shim: ``llmwikify.agent.backend.ppt.engine`` →
``llmwikify.apps.ppt.engine`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.ppt.engine import *  # noqa: F401, F403
