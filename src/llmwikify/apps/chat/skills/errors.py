"""Error hierarchy for the v0.32 skill framework.

These exceptions are the only ones raised by the framework itself;
individual skills should raise ``SkillExecutionError`` for handler
failures and ``SkillValidationError`` for input-schema violations.

The split mirrors the dual nature of skill execution:

  - ``SkillValidationError``  - raised BEFORE the handler runs
    (e.g. unknown skill/action, bad args, schema mismatch).
    The framework catches these and converts them to a
    ``SkillResult(status="error", error=...)``.

  - ``SkillExecutionError``  - raised BY the handler or DURING
    its invocation (e.g. downstream LLM/network failure).
    The runtime catches these and converts them similarly.

A bare ``SkillError`` is exported for callers that want to
catch anything framework-emitted.
"""

from __future__ import annotations

from typing import Any


class SkillError(Exception):
    """Base class for all skill-framework errors."""


class SkillNotFoundError(SkillError):
    """Raised when a skill name is not in the registry."""

    def __init__(self, skill_name: str) -> None:
        super().__init__(f"Skill not found: {skill_name!r}")
        self.skill_name = skill_name


class ActionNotFoundError(SkillError):
    """Raised when an action name is not declared on a skill."""

    def __init__(self, skill_name: str, action_name: str) -> None:
        super().__init__(f"Action {action_name!r} not found on skill {skill_name!r}")
        self.skill_name = skill_name
        self.action_name = action_name


class SkillValidationError(SkillError):
    """Raised when args fail input-schema validation.

    Carries the raw validation message so the runtime can
    surface it to the LLM.
    """

    def __init__(
        self,
        message: str,
        *,
        skill_name: str = "",
        action_name: str = "",
        errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.skill_name = skill_name
        self.action_name = action_name
        self.errors = errors or []


class SkillExecutionError(SkillError):
    """Raised by a skill handler or by the runtime during execution.

    The runtime converts these to ``SkillResult(status="error")``
    so the LLM receives a structured failure rather than an
    unhandled traceback.
    """

    def __init__(
        self,
        message: str,
        *,
        skill_name: str = "",
        action_name: str = "",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.skill_name = skill_name
        self.action_name = action_name
        self.__cause__ = cause


class ConfirmationRequiredError(SkillError):
    """Raised when an action requires pre-execution confirmation.

    The runtime (or ChatBase tool-call bridge) catches this
    and creates a pending confirmation, returning a
    ``SkillResult(status="needs_confirmation", confirmation_id=...)``
    to the LLM.
    """

    def __init__(self, skill_name: str, action_name: str, args: dict) -> None:
        super().__init__(f"Action {skill_name}.{action_name} requires confirmation")
        self.skill_name = skill_name
        self.action_name = action_name
        # NOTE: must NOT use self.args here — ``Exception.args`` is
        # a special property that auto-tuplifies any assignment
        # (e.g. assigning a dict stores the keys). Call it
        # ``action_args`` to avoid that footgun.
        self.action_args = args


__all__ = [
    "SkillError",
    "SkillNotFoundError",
    "ActionNotFoundError",
    "SkillValidationError",
    "SkillExecutionError",
    "ConfirmationRequiredError",
]


def format_run_not_found(run_id: Any, workflow_name: str | None = None) -> str:
    """Produce a helpful error when a run_id doesn't match any stored run.

    run_id should be a 'wf_YYYY-MM-DDTHH-MM-SS_<8hex>' identifier
    returned by a *_run tool. If the LLM passed something else
    (e.g. user input starting with '/' or containing ':'), include
    a hint plus up to 3 most recent run_ids to help it recover.

    Regression: the bare "no run with id X" message was confusing
    for the LLM, which would sometimes pass the user's slash command
    input as a run_id (e.g. "study: 量化交易策略").
    """
    rid = str(run_id) if run_id else ""
    if not rid or not rid.startswith("wf_"):
        # Imported lazily: skills.workflows imports this module, so a
        # module-level import here would close a cycle.
        from llmwikify.apps.chat.skills.workflows.run_store import RunStore

        try:
            recent = RunStore.default().list_runs(
                workflow_name=workflow_name,
                limit=3,
            )
            recent_ids = [s.run_id for s in recent if s.run_id]
        except Exception:
            recent_ids = []
        hint = f" Recent run_ids: {recent_ids}." if recent_ids else ""
        return (
            f"no run with id {run_id!r} — run_id must be a 'wf_...' "
            f"identifier returned by the *_run tool, not user input."
            f"{hint}"
        )
    return (
        f"no run with id {run_id!r} — run_id must be a 'wf_...' "
        f"identifier returned by the *_run tool, not user input."
    )
