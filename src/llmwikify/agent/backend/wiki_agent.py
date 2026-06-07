"""Backward-compat shim: ``llmwikify.agent.backend.wiki_agent`` →
``llmwikify.apps.agent.wiki_agent`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.wiki_agent import *  # noqa: F401, F403
