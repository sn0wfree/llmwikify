"""Quick Research engine for multi-source async research.

The legacy ResearchEngine / ResearchSessionManager were removed in
v0.36 (Phase 2.1 cleanup) — the production path is the 6-step
framework engine in ``apps/chat/``. This package now houses only
the shared helpers still used by the chat engine:

  - ``db.ResearchDatabase`` — the 4-table schema backing research
    sessions, sub-queries, sources, and the research_steps log.
  - ``base`` — ``BaseResearchConfig`` / ``BaseQualityGate`` /
    ``BaseResearchTaskManager`` / ``BaseGateResult`` mixed in by
    chat subclasses.
  - ``web_search.WebSearch`` — the unified web-search facade used
    by ``apps/chat/gatherer.py`` and the gather skill actions.
"""

from .db import ResearchDatabase

__all__ = ["ResearchDatabase"]
