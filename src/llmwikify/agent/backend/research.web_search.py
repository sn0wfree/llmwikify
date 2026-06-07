"""Backward-compat shim: ``llmwikify.agent.backend.research.web_search`` →
``llmwikify.apps.research.web_search`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.research.web_search import *  # noqa: F401, F403
