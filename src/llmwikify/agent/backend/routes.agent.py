"""Backward-compat shim: ``llmwikify.agent.backend.routes.agent`` →
``llmwikify.apps.agent.routes.agent`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.agent.routes.agent import *  # noqa: F401, F403
