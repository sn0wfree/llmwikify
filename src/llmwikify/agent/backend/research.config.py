"""Backward-compat shim: ``llmwikify.agent.backend.research.config`` →
``llmwikify.apps.research.config`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.research.config import *  # noqa: F401, F403
