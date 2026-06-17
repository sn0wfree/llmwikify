"""Callback foundation: lifecycle hooks for the agent loop.

Exposes the AgentHook abstract base, the CompositeHook fan-out helper,
and AgentHookContext (mutable per-iteration state). Domain hooks (wiki,
dream, auto-ingest) live in ``integrations/`` and depend on app code
at runtime only.
"""

from llmwikify.foundation.callback.composite import (
    AgentHook,
    CompositeHook,
    NoOpHook,
)
from llmwikify.foundation.callback.context import AgentHookContext

__all__ = [
    "AgentHook",
    "AgentHookContext",
    "CompositeHook",
    "NoOpHook",
]
