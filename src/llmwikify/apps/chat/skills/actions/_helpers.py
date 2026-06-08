"""Common helpers for action wrappers.

Most of the 23 Phase 5 actions are thin wrappers around
existing wiki / engine / database methods. This module
provides shared utilities so each action file stays tiny.

Helpers:

  - ``wiki_from_ctx(ctx)`` — extract the Wiki instance from
    a SkillContext.
  - ``safe_call(fn, *args, **kwargs)`` — call a method,
    catch exceptions, return SkillResult.fail(...) on error.
  - ``load_registry_or_default(registry)`` — return the
    provided registry or the default singleton.

Why these helpers exist:

  - The ``wiki`` attribute is the most common ctx field
    used by actions; centralizing access makes the actions
    testable in isolation (pass a Wiki mock via ctx).
  - The error-handling pattern (try/except → SkillResult.fail)
    is repeated in every action. Wrapping it in a helper
    avoids 23 copies of the same boilerplate.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from llmwikify.apps.chat.skills.base import SkillContext, SkillResult
from llmwikify.apps.chat.skills.registry import (
    SkillRegistry,
    default_registry,
)

logger = logging.getLogger(__name__)


def wiki_from_ctx(ctx: SkillContext) -> Any:
    """Extract the Wiki instance from a SkillContext.

    Returns the ``ctx.wiki`` attribute as-is. Callers should
    be ready for it to be ``None`` (when the action is
    invoked outside a real wiki session, e.g. in tests).
    """
    return ctx.wiki


def safe_call(
    fn: Callable[..., Any],
    *args: Any,
    error_prefix: str = "Action failed",
    **kwargs: Any,
) -> SkillResult:
    """Call ``fn`` and convert any exception to SkillResult.fail.

    This is the standard error-translation pattern for action
    handlers: the LLM-facing tool result is always a
    SkillResult, never a raw exception traceback.
    """
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, SkillResult):
            return result
        if isinstance(result, dict):
            return SkillResult.ok(result)
        if result is None:
            return SkillResult.ok({})
        # Some wiki methods return raw strings (search
        # results, page content) — wrap them.
        return SkillResult.ok({"result": result})
    except Exception as e:
        logger.warning("%s: %s", error_prefix, e, exc_info=True)
        return SkillResult.fail(
            f"{error_prefix}: {e!r}",
        )


def load_registry_or_default(registry: SkillRegistry | None) -> SkillRegistry:
    """Return the provided registry, or the default singleton."""
    return registry if registry is not None else default_registry()


__all__ = [
    "wiki_from_ctx",
    "safe_call",
    "load_registry_or_default",
]
