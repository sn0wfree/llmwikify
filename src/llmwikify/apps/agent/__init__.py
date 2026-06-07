"""L3 apps/agent package.

This is the L3 (apps) home for the agent backend — everything
that used to live in ``llmwikify.agent.backend`` plus the
standalone agent modules (``wiki_agent``, ``runner``,
``dream_editor``, ``hooks``). The 1:1 mirror layout matches
``agent/backend/`` for low cognitive overhead during the
migration.
"""
from .wiki_agent import WikiAgent

__all__ = ["WikiAgent"]
