"""Shared substrate for knowledge work — the common base of chat and research.

``apps/chat`` and ``apps/chat``'s sibling ``apps/research`` used to
import each other: the research pipeline was built on the chat agent
machinery, while the chat side pulled a handful of research modules
(web search, the research base classes, the research database). That
made the two sibling packages a **cycle**.

This package holds the parts both sides need, so the dependency runs
one way only:

    apps/chat ──┐
                ├──► apps/knowledge ──► (foundation / kernel)
    apps/research ─┘

What lives here

- ``web_search.py`` — the web-search facade (was ``apps/research/web_search.py``)
- ``base.py`` — shared base classes: research config, quality gate,
  task manager (was ``apps/research/base.py``)
- ``db.py`` — the research artifact store (was ``apps/research/db.py``)

The old paths still work: ``apps/research/{web_search,base,db}.py`` are
back-compat shims that expose the **same module objects** (via the
``sys.modules`` trick), so ``mock.patch`` on either path works.

``apps/research/agent.py`` moved the other way — the research agent is
research-specific, so it belongs with the research engine; the chat
package keeps a shim at ``apps/chat/research_agent.py``.
"""

from __future__ import annotations

from .base import (
    BaseGateResult,
    BaseQualityGate,
    BaseResearchConfig,
    BaseResearchTaskManager,
)
from .db import ResearchDatabase
from .web_search import WebSearch

__all__ = [
    "BaseGateResult",
    "BaseQualityGate",
    "BaseResearchConfig",
    "BaseResearchTaskManager",
    "ResearchDatabase",
    "WebSearch",
]
