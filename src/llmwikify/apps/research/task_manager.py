"""Background task manager for research engine.

Runs research engines as independent asyncio.Tasks, decoupled
from SSE connections. Events are buffered in per-session async
queues so SSE consumers can subscribe at any time.

Sprint C4: the 6 base methods were extracted to
:mod:`llmwikify.apps.research.base.BaseResearchTaskManager`.
This module is a thin subclass that does not add any extra
behavior — the 14 ``agent/backend/research.*.py`` shim files
that re-export :class:`ResearchTaskManager` continue to work
without changes.
"""

from __future__ import annotations

from .base import BaseResearchTaskManager


class ResearchTaskManager(BaseResearchTaskManager):
    """Quick-Research task manager.

    Inherits all behavior from :class:`BaseResearchTaskManager`.
    The 6-step framework subclass in ``apps/chat/task_manager.py``
    adds a DB-persisted ``EventBuffer`` by overriding the four
    ``_on_*`` hooks.
    """

    pass


# Global singleton
_task_manager: ResearchTaskManager | None = None


def get_task_manager() -> ResearchTaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = ResearchTaskManager()
    return _task_manager
