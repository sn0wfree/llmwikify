"""LAL error types — the single classification of LLM failures.

Part of the LLM Access Layer (LAL). See
``docs/designs/llm-access-layer.md`` for the full design.

All LLM-related errors raised by LAL-aware code MUST inherit from
``LLMError``. They carry an ``action`` field that the frontend
uses to decide what to show the user (toast + auto-navigate,
toast + button, log + ignore, etc.).

The four error types are layered:

  - ``LLMNotConfiguredError`` — no LLM is wired up. Action
    points the user to ``/llm-settings``.
  - ``LLMModelNotSupportedError`` — the requested model is
    not in the provider's supported list. Action shows a
    model picker.
  - ``LLMSpecMismatchError`` — a subagent actor requested a
    model that's not compatible with the inherited LLMSpec.
    Action points the user at the workflow YAML.
  - ``SubagentLLMError`` — an unexpected LLM failure inside a
    subagent process. Action tells the user to retry or check
    their provider.

These replace the historical mix of ``ValueError`` and
``RuntimeError`` with no ``action`` field, so the frontend had
to string-match to figure out what to show.
"""

from __future__ import annotations

from typing import Any


class LLMError(Exception):
    """Base class for all LAL errors.

    Subclasses MUST set ``action`` to one of the well-known
    action strings (see module docstring) and SHOULD set
    ``path`` to a UI path when the action is
    ``"go-to-llm-settings"`` (or similar).
    """

    action: str = ""
    path: str | None = None

    def __init__(
        self,
        message: str = "",
        *,
        action: str | None = None,
        path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        if action is not None:
            self.action = action
        if path is not None:
            self.path = path
        self.details: dict[str, Any] = details or {}


class LLMNotConfiguredError(LLMError):
    """Raised when the LLM stack has no usable configuration.

    Examples:
      - ``llm.enabled`` is False
      - ``api_key`` is missing or empty
      - ``provider`` is None

    Action: ``"go-to-llm-settings"`` — frontend should auto-
    navigate the user to the LLM settings page.
    """

    action = "go-to-llm-settings"
    path = "/llm-settings"

    def __init__(
        self,
        message: str = "LLM is not configured.",
        *,
        path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, path=path, details=details)


class LLMModelNotSupportedError(LLMError):
    """Raised when the requested model is not in the provider's list.

    Action: ``"select-supported-model"`` — frontend should show
    the list of supported models and prompt the user to pick
    one. The ``details`` dict carries ``provider`` and
    ``supported`` (list of model names) for rendering.
    """

    action = "select-supported-model"

    def __init__(
        self,
        message: str = "Model not supported by provider.",
        *,
        provider: str = "",
        model: str = "",
        supported: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "supported": list(supported or []),
        }
        if details:
            merged_details.update(details)
        super().__init__(message, details=merged_details)


class LLMSpecMismatchError(LLMError):
    """Raised when a subagent's actor.model conflicts with the LLMSpec.

    Action: ``"fix-workflow-yaml"`` — frontend should point the
    user at the offending workflow YAML file. ``details``
    carries the file path, actor name, and the bad model name.
    """

    action = "fix-workflow-yaml"

    def __init__(
        self,
        message: str = "actor.model is not compatible with the inherited LLMSpec.",
        *,
        actor: str = "",
        actor_model: str = "",
        spec_model: str = "",
        provider: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details: dict[str, Any] = {
            "actor": actor,
            "actor_model": actor_model,
            "spec_model": spec_model,
            "provider": provider,
        }
        if details:
            merged_details.update(details)
        super().__init__(message, details=merged_details)


class SubagentLLMError(LLMError):
    """Raised when a subagent's LLM call fails for any other reason.

    Action: ``"retry-or-check-provider"`` — frontend should show
    a retry button and a link to provider docs / status page.
    """

    action = "retry-or-check-provider"

    def __init__(
        self,
        message: str = "Subagent LLM call failed.",
        *,
        actor: str = "",
        original_error: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details: dict[str, Any] = {
            "actor": actor,
            "original_error": original_error,
        }
        if details:
            merged_details.update(details)
        super().__init__(message, details=merged_details)


__all__ = [
    "LLMError",
    "LLMNotConfiguredError",
    "LLMModelNotSupportedError",
    "LLMSpecMismatchError",
    "SubagentLLMError",
]
