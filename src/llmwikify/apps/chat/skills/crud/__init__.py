"""CRUD skills — Phase 12: thin wrappers for memory/notify/scheduler/dream.

Per ``v0.32-execution-plan.md`` Phase 12: these skills are
thin wrappers around the existing ``apps/agent/``
implementations (memory, notifications, scheduler,
dream_editor).

Each CRUD skill delegates to the existing implementation
via ``ctx.config['<manager_key>']``. The skill layer adds
JSON Schema validation and SkillResult normalization
without reimplementing the business logic.

Skills:

  1. ``memory_skill`` — conversation + knowledge sink CRUD
  2. ``notify_skill`` — notification CRUD
  3. ``scheduler_skill`` — scheduled task CRUD
  4. ``dream_skill`` — dream proposal CRUD

Design ref: ``v0.32-skill-restructure.md`` §3.1 (#28-#31)
"""

from llmwikify.apps.chat.skills.crud.dream_skill import DreamSkill, dream_skill
from llmwikify.apps.chat.skills.crud.goal_skill import GoalSkill, goal_skill
from llmwikify.apps.chat.skills.crud.memory_skill import MemorySkill, memory_skill
from llmwikify.apps.chat.skills.crud.notify_skill import NotifySkill, notify_skill
from llmwikify.apps.chat.skills.crud.scheduler_skill import (
    SchedulerSkill,
    scheduler_skill,
)

__all__ = [
    "MemorySkill", "memory_skill",
    "NotifySkill", "notify_skill",
    "SchedulerSkill", "scheduler_skill",
    "DreamSkill", "dream_skill",
    "GoalSkill", "goal_skill",
]
