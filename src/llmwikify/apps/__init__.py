"""L3 apps layer — application packages.

Per the 4-layer refactor (see
``docs/designs/refactor-4layer-architecture.md``), this package
contains the application-level code that orchestrates L2
kernel logic for end-user features. It depends on kernel (L2)
and foundation (L1) but MUST NOT import from interfaces (L4).

Subpackages:
    - agent: agent backend (db, service, tools, memory, ...).
      Replaces the deprecated ``llmwikify.agent`` package.
    - research: the research engine, evolved from
      ``llmwikify.agent.backend.research``.
    - chat: chat framework (skills, harness, memory, agent_service).
"""
from .agent import WikiAgent

__all__ = ["WikiAgent"]
