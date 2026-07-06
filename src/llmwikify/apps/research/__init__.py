"""Research engine for llmwikify v0.40.

Replaces the legacy split between ``apps.research`` (DB helpers only) and
``apps.chat.research_engine`` (engine/actions/gates/etc). v0.40 collapses
both into a single ``apps.research`` package so the public surface is:

  - ``ResearchDatabase`` (db.py) — 4-table schema backing sessions,
    sub-queries, sources, and the research_steps log.
  - ``ResearchEngine`` / ``ResearchSessionManager`` (engine.py) — adaptive
    ReAct orchestrator. Note: due to a circular import (engine imports
    chat.config which imports chat.__init__ which imports
    chat.research_engine), this module is NOT eagerly imported here —
    callers must use ``from llmwikify.apps.research.engine import
    ResearchEngine`` directly.
  - ``WebSearch`` (web_search.py) — unified web-search facade.
  - ``BaseResearchConfig`` / ``BaseQualityGate`` (base.py) — abstract
    base classes for chat subclasses.

To avoid eager import cycles, only the leaf-level (non-cyclic) modules
are exposed at the package top level. Submodules with chat dependencies
(``engine``, ``actions``, ``gates``, ``llm_step``, ``observer``,
``reasoner``, ``report``, ``resume``, ``routes``) remain accessible via
their explicit submodule path.
"""

from .db import ResearchDatabase
from .web_search import WebSearch

__all__ = ["ResearchDatabase", "WebSearch"]