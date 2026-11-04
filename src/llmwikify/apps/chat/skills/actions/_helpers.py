"""Common helpers for action wrappers.

Most of the 23 Phase 5 actions are thin wrappers around
existing wiki / engine / database methods. This module
provides shared utilities so each action file stays tiny.

Helpers:

  - ``wiki_from_ctx(ctx)`` — extract the Wiki instance from
    a SkillContext.
  - ``safe_call(fn, *args, **kwargs)`` — call a method,
    catch exceptions, return SkillResult.fail(...) on error.
  - ``safe_call_async(fn, *args, **kwargs)`` — same, but runs the
    callable in a worker thread so a blocking call cannot stall the
    event loop. Use it from every ``async`` handler.
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

import asyncio
import logging
from collections.abc import Callable
from typing import Any

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
        return _as_skill_result(result)
    except Exception as e:
        logger.warning("%s: %s", error_prefix, e, exc_info=True)
        return SkillResult.fail(
            f"{error_prefix}: {e!r}",
        )


def _as_skill_result(result: Any) -> SkillResult:
    """Convert a raw handler return value into a SkillResult."""
    if isinstance(result, SkillResult):
        return result
    if isinstance(result, dict):
        return SkillResult.ok(result)
    if result is None:
        # Void-success: wiki methods like write/delete return None on
        # success. Failures raise and are caught by safe_call. Log at
        # debug so an unexpected None (handler swallowing an error)
        # is at least observable.
        logger.debug("handler returned None; treating as void success")
        return SkillResult.ok({})
    # Some wiki methods return raw strings (search
    # results, page content) — wrap them.
    return SkillResult.ok({"result": result})


async def safe_call_async(
    fn: Callable[..., Any],
    *args: Any,
    error_prefix: str = "Action failed",
    timeout: float | None = None,
    **kwargs: Any,
) -> SkillResult:
    """Async counterpart of :func:`safe_call` for blocking handlers.

    The callable runs in a worker thread, so a slow call cannot stall
    the event loop. That matters for handlers reaching the LLM (one chat
    completion can take tens of seconds) and for ones that rebuild the
    wiki index (hundreds of milliseconds on a large wiki).

    Args:
        fn: The blocking callable.
        timeout: Optional ceiling in seconds. On expiry the action
            fails instead of hanging forever.
    """
    try:
        call = asyncio.to_thread(fn, *args, **kwargs)
        result = await (asyncio.wait_for(call, timeout) if timeout else call)
        return _as_skill_result(result)
    except asyncio.TimeoutError:
        logger.warning("%s: timed out after %ss", error_prefix, timeout)
        return SkillResult.fail(f"{error_prefix}: timed out after {timeout}s")
    except Exception as e:
        logger.warning("%s: %s", error_prefix, e, exc_info=True)
        return SkillResult.fail(f"{error_prefix}: {e!r}")


def load_registry_or_default(registry: SkillRegistry | None) -> SkillRegistry:
    """Return the provided registry, or the default singleton."""
    return registry if registry is not None else default_registry()


__all__ = [
    "wiki_from_ctx",
    "safe_call",
    "safe_call_async",
    "load_registry_or_default",
]
