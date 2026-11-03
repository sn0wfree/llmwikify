"""Research engine for llmwikify v0.40.

The 6-step research pipeline (clarify → plan → gather → analyze →
synthesize → review) lives here. It is built on the chat agent
machinery (``apps.chat``), so the dependency runs **research → chat** —
one way only.

The parts that the chat side also needs (the web-search facade, the
shared research base classes, the research artifact store) live in
``llmwikify.apps.knowledge``, below both packages, so that
``apps.chat`` never has to import ``apps.research``.

Public surface:

  - ``ResearchEngine`` / ``ResearchSessionManager`` (``engine.py``) —
    adaptive ReAct orchestrator. Note: due to a circular import (engine
    imports chat.config which imports chat.__init__), this module is
    NOT eagerly imported here — callers must use
    ``from llmwikify.apps.research.engine import ResearchEngine``
    directly. Also accessible via the PEP 562 lazy attribute on
    ``apps.chat`` (``from llmwikify.apps.chat import ResearchEngine``).
  - ``ResearchAgent`` (``agent.py``) — the chat-style wrapper around the
    engine. It moved here from ``apps.chat.research_agent`` (which keeps
    a back-compat shim).
  - ``WebSearch`` / ``ResearchDatabase`` — re-exported from
    ``llmwikify.apps.knowledge``; the old paths
    ``apps.research.web_search`` / ``apps.research.db`` remain as
    back-compat shims.

To avoid eager import cycles, only the leaf-level (non-cyclic) modules
are exposed at the package top level. Submodules with chat dependencies
(``engine``, ``actions``, ``gates``, ``llm_step``, ``observer``,
``reasoner``, ``report``, ``resume``, ``routes``) remain accessible via
their explicit submodule path.
"""

from llmwikify.apps.knowledge.db import ResearchDatabase
from llmwikify.apps.knowledge.web_search import WebSearch

__all__ = ["ResearchDatabase", "WebSearch"]
