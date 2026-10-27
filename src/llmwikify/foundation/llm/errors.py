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

import json
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


# ─── 429 fine classification (borrowed from nanobot base.py) ───
#
# Some 429 responses are billing/quota failures that will NOT clear
# on retry — e.g. insufficient_quota, payment_required. Retrying
# these wastes tokens and triggers provider throttling.
#
# Distinguishing the two classes requires inspecting the response
# body. nanobot's Provider ABC carries this logic in
# ``_is_retryable_429_response``; we expose the same primitives
# here so the helpers can be invoked from any retry site (HTTP or
# SSE) and from any new provider-specific code path.
#
# Borrowed from nanobot v0.2.1 providers/base.py:374-394,
# simplified for the body-text-only case (we don't parse the full
# structured error envelope; that's the caller's job if they want
# finer control).

_NON_RETRYABLE_429_ERROR_TOKENS: frozenset[str] = frozenset(
    {
        "insufficient_quota",
        "quota_exceeded",
        "quota_exhausted",
        "billing_hard_limit_reached",
        "insufficient_balance",
        "credit_balance_too_low",
        "billing_not_active",
        "payment_required",
    }
)

_RETRYABLE_429_ERROR_TOKENS: frozenset[str] = frozenset(
    {
        "rate_limit_exceeded",
        "rate_limit_error",
        "too_many_requests",
        "request_limit_exceeded",
        "requests_limit_exceeded",
        "overloaded_error",
    }
)

_NON_RETRYABLE_429_TEXT_MARKERS: tuple[str, ...] = (
    "insufficient_quota",
    "insufficient quota",
    "quota exceeded",
    "quota exhausted",
    "billing hard limit",
    "billing_hard_limit_reached",
    "billing not active",
    "insufficient balance",
    "insufficient_balance",
    "credit balance too low",
    "payment required",
    "payment_required",
    "out of credits",
    "out of quota",
    "exceeded your current quota",
)

_RETRYABLE_429_TEXT_MARKERS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "retry after",
    "try again in",
    "temporarily unavailable",
    "overloaded",
    "concurrency limit",
    "速率限制",
)


def _normalize_error_token(value: Any) -> str | None:
    """Normalize an error token: strip + lowercase, or return None."""
    if value is None:
        return None
    token = str(value).strip().lower()
    return token or None


def _extract_error_type_code(payload: Any) -> tuple[str | None, str | None]:
    """Extract (type, code) from a dict or JSON string error payload.

    Returns (None, None) for non-dict input, unparseable JSON, or
    payloads without an ``error`` / ``type`` / ``code`` field.
    """
    data: dict[str, Any] | None = None
    if isinstance(payload, dict):
        data = payload
    elif isinstance(payload, str):
        text = payload.strip()
        if text:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                data = parsed
    if not isinstance(data, dict):
        return None, None
    type_value = data.get("type")
    code_value = data.get("code")
    error_obj = data.get("error")
    if isinstance(error_obj, dict):
        type_value = error_obj.get("type") or type_value
        code_value = error_obj.get("code") or code_value
    return _normalize_error_token(type_value), _normalize_error_token(code_value)


def _is_retryable_429_text(content: str | None) -> bool:
    """Classify a 429 response body as retryable or not.

    Returns True for rate-limit-style errors (worth waiting + retrying)
    and False for billing/quota failures (insufficient_quota,
    payment_required, etc.) that won't clear on retry.

    Unknown bodies default to True (wait + retry) — the safe choice
    is to retry once and surface the error rather than abandon early.
    """
    lowered = (content or "").lower()
    if any(marker in lowered for marker in _NON_RETRYABLE_429_TEXT_MARKERS):
        return False
    if any(marker in lowered for marker in _RETRYABLE_429_TEXT_MARKERS):
        return True
    # Unknown 429 → wait + retry (matches nanobot's default).
    return True


def is_arrearage_response(
    status_code: int | None,
    content: str | None,
) -> bool:
    """Detect API-key arrearage / quota / billing errors.

    These surface as HTTP 402 (Payment Required) or as billing
    semantic tokens in the error body. They will NOT clear on
    retry, so callers should treat them as terminal.

    Decision rules (matches tests/test_apps_chat_providers_borrow.py):

    * ``status_code == 402`` → always arrearage (Payment Required
      is reserved for billing by HTTP semantics).
    * Any 4xx/5xx status (including 401, 429, 500) with body
      containing a known billing marker → arrearage.
    * 429 with no billing marker → NOT arrearage (transient rate
      limit, retry).
    * Other status codes without billing markers → not arrearage.

    Issue: MiniMax sometimes returns 401 (not 402/429) for quota
    exhaustion, hence the marker-based fallback for non-402
    status codes. 402 is treated as the canonical arrearage
    status and doesn't need a body marker (per the
    ``test_402_is_arrearage`` contract).
    """
    if status_code == 402:
        return True
    if status_code is None:
        return False
    if 400 <= status_code < 600:
        lowered = (content or "").lower()
        return any(marker in lowered for marker in _NON_RETRYABLE_429_TEXT_MARKERS)
    return False



class LLMRequestError(RuntimeError):
    """Raised when the LLM provider returns a 4xx/5xx response.

    Unlike ``httpx.HTTPStatusError`` or ``requests.HTTPError`` (which
    only embed the status line and URL), this exception carries the
    provider's error body so the user can see *why* the call failed —
    e.g. MiniMax's ``{"error":{"message":"invalid params, messages
    is empty (2013)"}}`` instead of a bare ``400 Bad Request``.
    """

    def __init__(self, status_code: int, url: str, body: str) -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        # Truncate body to keep logs readable
        preview = body[:500] + ("…" if len(body) > 500 else "")
        # Issue: detect quota/billing errors and append a helpful hint
        if is_arrearage_response(status_code, body):
            preview += (
                "\n  💡 Quota/billing error detected. "
                "Check your provider dashboard for token balance."
            )
        super().__init__(f"LLM API returned {status_code} for {url}: {preview}")


def _format_http_error(
    status_code: int,
    url: str,
    body: bytes | str | None,
) -> LLMRequestError:
    """Build an ``LLMRequestError`` with a best-effort decoded body."""
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = repr(body[:200])
    else:
        text = body or ""
    # Try to extract the message from common OpenAI-compatible shapes
    # so the preview is more useful than the full JSON blob.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            err = parsed.get("error") or parsed.get("message")
            if isinstance(err, dict) and "message" in err:
                text = str(err["message"])
            elif isinstance(err, str):
                text = err
    except (json.JSONDecodeError, ValueError):
        pass
    return LLMRequestError(status_code, url, text)
