"""v0.32 skill framework — the foundational layer for Phase 1.

This package provides the **framework** into which 23 actions,
4 pipelines, and 5 skills are wired in later phases (Phase 5,
6, 12 of ``v0.32-execution-plan.md``).

What lives here in Phase 1
--------------------------

  - ``Skill``           - abstract base class
  - ``SkillAction``     - one named operation
  - ``SkillContext``    - per-call runtime context
  - ``SkillResult``     - return envelope
  - ``SkillManifest``   - LLM-facing description
  - ``SkillRegistry``   - process-wide skill store
  - ``SkillRuntime``    - executor (validate → dispatch → handle errors)
  - error hierarchy (``SkillError`` and 5 subclasses)

What does NOT live here yet
---------------------------

  - The 23 actions (``search``, ``extract``, ``read``, ...)
    are added in **Phase 5**.
  - The 4 pipelines (``gather``, ``ingest``, ``report``,
    ``research``) are added in **Phase 6**.
  - The 5 CRUD skills (``memory``, ``notify``,
    ``scheduler``, ``dream``, ``wiki_query``) are added in
    **Phase 12**.

This means in Phase 1 the registry is empty and the runtime
is exercised only by unit tests.

Public API
----------

    from llmwikify.apps.chat.skills import (
        # ABC + dataclasses
        Skill, SkillAction, SkillContext, SkillResult,
        SkillManifest,
        # Registry + Runtime
        SkillRegistry, SkillRuntime,
        default_registry, reset_default_registry,
        # Errors
        SkillError, SkillNotFoundError, ActionNotFoundError,
        SkillValidationError, SkillExecutionError,
        ConfirmationRequiredError,
    )

Design refs
-----------

  - ``docs/designs/principles/unix-philosophy.md`` — bottom
    skills are tools; top skills are workflows; simple CRUD
    stays a single skill.
  - ``docs/designs/principles/skill-taxonomy.md`` — action
    / pipeline / skill are 3 independent concepts, not a
    hierarchy.
  - ``docs/designs/v0.32-skill-restructure.md`` §3 — the
    full 27-skill + 2-alias inventory.
  - ``docs/designs/v0.32-execution-plan.md`` Phase 1 — this
    phase's deliverables.
"""

from __future__ import annotations

from llmwikify.apps.chat.skills.base import (
    AsyncHandler,
    ConfirmationPolicy,
    Handler,
    Skill,
    SkillAction,
    SkillContext,
    SkillManifest,
    SkillResult,
    SyncHandler,
)
from llmwikify.apps.chat.skills.errors import (
    ActionNotFoundError,
    ConfirmationRequiredError,
    SkillError,
    SkillExecutionError,
    SkillNotFoundError,
    SkillValidationError,
)
from llmwikify.apps.chat.skills.registry import (
    SkillRegistry,
    default_registry,
    reset_default_registry,
)
from llmwikify.apps.chat.skills.runtime import SkillRuntime

__all__ = [
    # Base ABC + dataclasses
    "Skill",
    "SkillAction",
    "SkillContext",
    "SkillResult",
    "SkillManifest",
    # Type aliases
    "Handler",
    "SyncHandler",
    "AsyncHandler",
    "ConfirmationPolicy",
    # Registry + Runtime
    "SkillRegistry",
    "default_registry",
    "reset_default_registry",
    "SkillRuntime",
    # Errors
    "SkillError",
    "SkillNotFoundError",
    "ActionNotFoundError",
    "SkillValidationError",
    "SkillExecutionError",
    "ConfirmationRequiredError",
]
