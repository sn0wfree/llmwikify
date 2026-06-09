"""Backward-compat shim: ``llmwikify.agent.backend.service`` →
``llmwikify.apps.chat.agent.agent_service``
(Updated for v0.34.0: old apps.agent.core.service removed).

Update your imports. This shim will be removed in v0.35.0.
"""
from llmwikify.apps.chat.agent.agent_service import AgentService  # noqa: F401
