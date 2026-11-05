"""Skill framework types — generic, app-independent.

``SkillResult`` / ``SkillAction`` / ``SkillContext`` describe the
skill contract itself. They used to live in
``apps/chat/skills/base.py``, which made the research engine
depend on the chat app. They live here so both can use them.
"""

from llmwikify.kernel.skills.types import (
    AsyncHandler,
    ConfirmationPolicy,
    Handler,
    SkillAction,
    SkillContext,
    SkillResult,
    SyncHandler,
)

__all__ = [
    "AsyncHandler",
    "ConfirmationPolicy",
    "Handler",
    "SkillAction",
    "SkillContext",
    "SkillResult",
    "SyncHandler",
]
