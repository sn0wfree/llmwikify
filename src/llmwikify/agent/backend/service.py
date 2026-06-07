"""Backward-compat shim: ``llmwikify.agent.backend.service`` →
``llmwikify.apps.agent.core.service`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.core.service import *  # noqa: F401, F403
