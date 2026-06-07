"""Agent Backend Package.

StreamableLLMClient is re-exported from its canonical home in
``llmwikify.foundation.llm.streamable``. The legacy import path
``llmwikify.agent.backend.adapters`` remains as a deprecation
shim (1 release cycle, removed in v0.33.0) per PLAN.md.
"""

from llmwikify.foundation.llm.streamable import StreamableLLMClient
from .db import AgentDatabase, get_agent_db_path
from .service import AgentContext, AgentService, ChatEvent

__all__ = [
    "StreamableLLMClient",
    "AgentDatabase",
    "get_agent_db_path",
    "AgentService",
    "AgentContext",
    "ChatEvent",
]