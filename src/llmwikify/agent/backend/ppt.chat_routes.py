"""Backward-compat shim: ``llmwikify.agent.backend.ppt.chat_routes`` →
``llmwikify.apps.ppt.chat_routes`` (Batch B4 of the 4-layer refactor).

Update your imports. This shim will be removed in v0.33.0.
"""
from llmwikify.apps.ppt.chat_routes import *  # noqa: F401, F403
