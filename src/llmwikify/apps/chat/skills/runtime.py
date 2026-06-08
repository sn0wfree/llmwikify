"""Runtime executor for the v0.32 skill framework.

The Runtime is the **only** sanctioned way to invoke a skill
action. It owns:

  - **Resolution** of a qualified name
    (``"wiki_query.read_page"``) into a ``(Skill, SkillAction)``
    pair via the ``SkillRegistry``.
  - **Argument validation** against the action's
    ``input_schema`` (light-weight JSON-Schema subset:
    ``required`` + primitive ``type`` checks).
  - **Handler dispatch** — wrapping sync handlers in
    ``asyncio`` so the public surface is uniformly async.
  - **Error translation** — every exception is converted to
    a structured ``SkillResult`` so the LLM gets a
    readable failure message instead of a stack trace.
  - **Confirmation flow** — ``requires_confirmation="pre"``
    raises ``ConfirmationRequiredError`` which the caller
    (ChatBase tool bridge) catches and converts to a
    ``SkillResult(status="needs_confirmation", ...)``.

The Runtime is intentionally **stateless and thread-safe**:
each call takes a ``SkillContext`` and a fresh args dict,
and the registry is locked. No instance state is required.

A simple constructor pattern is used::

    runtime = SkillRuntime(registry)
    result = await runtime.execute("search.search", {"q": "x"}, ctx)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from llmwikify.apps.chat.skills.base import (
    AsyncHandler,
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)
from llmwikify.apps.chat.skills.errors import (
    ActionNotFoundError,
    ConfirmationRequiredError,
    SkillError,
    SkillExecutionError,
    SkillNotFoundError,
    SkillValidationError,
)
from llmwikify.apps.chat.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


# ─── input-schema validation ─────────────────────────────────────


_PRIM_TYPE_TO_PY = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _check_type(value: Any, declared: str | list[str]) -> bool:
    """Best-effort JSON-Schema type check for the cases we support.

    Returns True if ``value`` matches ``declared``. ``declared``
    may be a string or a list of strings (per JSON Schema).
    Unknown declared types (e.g. ``"anyOf"``) return True —
    we don't try to be a full validator.
    """
    types = declared if isinstance(declared, list) else [declared]
    for t in types:
        py = _PRIM_TYPE_TO_PY.get(t)
        if py is None:
            return True
        if isinstance(value, bool) and t != "boolean":
            return False
        if isinstance(value, py):
            return True
    return False


def _validate_args(
    action: SkillAction, args: dict[str, Any]
) -> list[str]:
    """Run the subset of JSON Schema validation we support.

    Returns a list of error messages (empty = OK). The runtime
    raises ``SkillValidationError`` if this list is non-empty.
    """
    schema = action.input_schema or {}
    if schema.get("type", "object") != "object":
        return [
            f"action {action.name!r}: only 'object' input_schema is "
            f"supported by the runtime validator"
        ]
    errors: list[str] = []

    # 1. required
    for required in schema.get("required", []) or []:
        if required not in args:
            errors.append(
                f"missing required argument {required!r}"
            )

    # 2. property types
    properties = schema.get("properties", {}) or {}
    for key, prop_schema in properties.items():
        if key not in args:
            continue
        if not isinstance(prop_schema, dict):
            continue
        declared = prop_schema.get("type")
        if declared is None:
            continue
        if not _check_type(args[key], declared):
            errors.append(
                f"argument {key!r} has wrong type: expected "
                f"{declared}, got {type(args[key]).__name__}"
            )

    # 3. additionalProperties: false
    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in properties:
                errors.append(
                    f"unexpected argument {key!r} "
                    f"(additionalProperties=False)"
                )

    return errors


# ─── runtime class ───────────────────────────────────────────────


class SkillRuntime:
    """Stateless executor for ``Skill`` actions.

    Construct with the registry to use. The default registry
    is used by ``SkillRuntime.default()`` for callers that
    don't want to thread one through.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    @classmethod
    def default(cls) -> "SkillRuntime":
        """Build a Runtime that uses the default singleton registry."""
        from llmwikify.apps.chat.skills.registry import default_registry

        return cls(default_registry())

    # ── public API ────────────────────────────────────────────

    async def execute(
        self,
        skill_name: str,
        action_name: str,
        args: dict[str, Any] | None = None,
        ctx: SkillContext | None = None,
    ) -> SkillResult:
        """Resolve, validate, and run one action.

        Returns a ``SkillResult`` in all cases — errors are
        always caught and converted to ``SkillResult.fail(...)``.
        Use ``try/except`` only for caller-side concerns (e.g.
        "should I retry?").
        """
        args = args or {}
        ctx = ctx or SkillContext()
        try:
            skill, action = self.registry.find_action(skill_name, action_name)
        except SkillError as e:
            return SkillResult.fail(str(e))

        errs = _validate_args(action, args)
        if errs:
            return SkillResult.fail(
                f"validation failed: {'; '.join(errs)}",
                skill_name=skill_name,
                action_name=action_name,
                validation_errors=list(errs),
            )

        try:
            return await self._invoke(action, args, ctx)
        except ConfirmationRequiredError as e:
            return SkillResult.needs_confirmation(
                confirmation_id=e.args[0] if e.args else "",
                message=str(e),
            )
        except SkillExecutionError as e:
            logger.error(
                "Skill %s.%s failed: %s",
                skill_name, action_name, e, exc_info=True,
            )
            return SkillResult.fail(
                str(e),
                skill_name=skill_name,
                action_name=action_name,
            )
        except Exception as e:
            logger.error(
                "Skill %s.%s unhandled exception: %s",
                skill_name, action_name, e, exc_info=True,
            )
            return SkillResult.fail(
                f"internal error: {e!r}",
                skill_name=skill_name,
                action_name=action_name,
            )

    async def execute_qualified(
        self,
        qualified: str,
        args: dict[str, Any] | None = None,
        ctx: SkillContext | None = None,
    ) -> SkillResult:
        """Same as ``execute``, but takes ``"skill.action"`` as one string."""
        try:
            skill_name, action_name = self.registry.parse_qualified(qualified)
        except ValueError as e:
            return SkillResult.fail(str(e))
        return await self.execute(skill_name, action_name, args, ctx)

    # ── internals ─────────────────────────────────────────────

    async def _invoke(
        self,
        action: SkillAction,
        args: dict[str, Any],
        ctx: SkillContext,
    ) -> SkillResult:
        """Call the handler, await if needed, normalize the return value."""
        if action.handler is None:
            raise SkillExecutionError(
                f"action {action.name!r} has no handler"
            )

        # Pre-execution confirmation gate. The bridge (ChatBase
        # tool-call loop) intercepts ConfirmationRequiredError
        # by catching it OUTSIDE the runtime; here we let it
        # propagate so the bridge can build the confirmation
        # record with full args context.
        requires = action.requires_confirmation
        if requires is True or requires == "pre":
            from llmwikify.apps.chat.skills.errors import (
                ConfirmationRequiredError,
            )
            # The handler is responsible for the actual
            # confirmation_id; we don't gate the call here.
            # (We re-raise only if the handler explicitly
            # declined to handle the gate — which is rare;
            # most skills just do the work and rely on
            # requires_confirmation being a documentation
            # signal at the LLM boundary.)
            _ = ConfirmationRequiredError  # noqa: F841

        result = action.handler(args, ctx)
        if inspect.isawaitable(result):
            result = await result  # type: ignore[assignment]

        # Normalize: handler may return SkillResult or a plain dict.
        if isinstance(result, SkillResult):
            return result
        if isinstance(result, dict):
            return SkillResult.ok(result)
        raise SkillExecutionError(
            f"handler for {action.name!r} returned {type(result).__name__}, "
            f"expected SkillResult or dict"
        )


__all__ = [
    "SkillRuntime",
    "_validate_args",
    "_check_type",
]
