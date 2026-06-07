"""Backward-compat shim: ``llmwikify.agent.backend.research.engine`` →
``llmwikify.apps.research.engine`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.research.engine import *  # noqa: F401, F403
