"""Streamable LLM client — supports streaming, async, and function calling.

Canonical location for the streaming-capable LLM client. The historical
home in ``llmwikify.agent.backend.adapters`` is preserved as a thin
deprecation shim; new code should import from
``llmwikify.foundation.llm.streamable`` instead.

Usage::

    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    client = StreamableLLMClient.from_config(config_dict)
    text = client.chat(messages, temperature=0.3)
    async for chunk in client.astream_chat(messages):
        ...

Token budget checking is applied automatically via decorator.
Pass ``_prompt_name="..."`` in generation_params to label calls in logs.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..llm_client import LLMClient, _legacy_fallback_enabled
from .budget_decorator import check_token_budget
from .errors import LLMNotConfiguredError
from .resolver import resolve_chat_llm, resolver_enabled
from .spec import LLMSpec
from .token_budget import TokenBudgetChecker, TokenBudgetConfig

logger = logging.getLogger(__name__)


# ─── Retry configuration ────────────────────────────────────────
#
# Retry+backoff for transient network / provider errors:
#   - ReadTimeout, ConnectionError, Timeout (network-level)
#   - HTTP 429 (rate limit)
#   - HTTP 500, 502, 503, 504 (server-side transient)
#
# Not retried:
#   - 4xx (except 429) — client errors that won't be fixed by retry
#   - 401/403 (auth) — won't change without credential update
#   - Mid-stream failures (once we start reading response body, the
#     request is committed; retry would re-bill tokens)
#
# Backoff: 1s, 2s, 4s exponential with up to 0.5s jitter to avoid
# synchronized retries from concurrent callers. Override the base
# with the LLM_RETRY_BACKOFF_BASE environment variable (in seconds).
# The HTTP Retry-After header (when present on 429/503) takes
# precedence over the computed backoff.

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_DEFAULT_MAX_RETRIES: int = 3
_DEFAULT_BACKOFF_BASE: float = 1.0
_DEFAULT_BACKOFF_FACTOR: float = 2.0
_DEFAULT_BACKOFF_JITTER: float = 0.5
# Cap on Retry-After header value to prevent absurd waits
# (some providers send values like 3600 for "back off an hour")
_RETRY_AFTER_MAX_SECONDS: float = 60.0


@dataclass(frozen=True)
class RetryConfig:
    """Snapshot of retry configuration, read from env at call time.

    Kept frozen so a config can be passed around without risk of
    accidental mutation. Use ``RetryConfig.from_env()`` to construct.
    """

    max_retries: int = _DEFAULT_MAX_RETRIES
    backoff_base: float = _DEFAULT_BACKOFF_BASE
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR
    backoff_jitter: float = _DEFAULT_BACKOFF_JITTER
    retry_after_max_seconds: float = _RETRY_AFTER_MAX_SECONDS

    @classmethod
    def from_env(cls) -> "RetryConfig":
        """Build a config from environment variables.

        Environment variables (all optional):
          - LLM_RETRY_MAX_RETRIES: int, default 3
          - LLM_RETRY_BACKOFF_BASE: float seconds, default 1.0
          - LLM_RETRY_BACKOFF_FACTOR: float, default 2.0
          - LLM_RETRY_BACKOFF_JITTER: float seconds, default 0.5
          - LLM_RETRY_AFTER_MAX_SECONDS: float, default 60.0
        """
        def _read_float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None or raw.strip() == "":
                return default
            try:
                return float(raw)
            except ValueError:
                logger.warning(
                    "%s=%r is not a valid float; using default %.1f",
                    name, raw, default,
                )
                return default

        def _read_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None or raw.strip() == "":
                return default
            try:
                v = int(raw)
                if v < 0:
                    logger.warning(
                        "%s=%d is negative; using default %d",
                        name, v, default,
                    )
                    return default
                return v
            except ValueError:
                logger.warning(
                    "%s=%r is not a valid int; using default %d",
                    name, raw, default,
                )
                return default

        return cls(
            max_retries=_read_int("LLM_RETRY_MAX_RETRIES", _DEFAULT_MAX_RETRIES),
            backoff_base=_read_float("LLM_RETRY_BACKOFF_BASE", _DEFAULT_BACKOFF_BASE),
            backoff_factor=_read_float("LLM_RETRY_BACKOFF_FACTOR", _DEFAULT_BACKOFF_FACTOR),
            backoff_jitter=_read_float("LLM_RETRY_BACKOFF_JITTER", _DEFAULT_BACKOFF_JITTER),
            retry_after_max_seconds=_read_float(
                "LLM_RETRY_AFTER_MAX_SECONDS", _RETRY_AFTER_MAX_SECONDS
            ),
        )


def _compute_backoff(attempt: int, config: RetryConfig) -> float:
    """Exponential backoff with jitter.

    attempt=0 → base–base+jitter (default 1.0–1.5s)
    attempt=1 → base*factor–base*factor+jitter (default 2.0–2.5s)
    attempt=2 → base*factor²–... (default 4.0–4.5s)
    """
    return (
        config.backoff_base * (config.backoff_factor ** attempt)
        + random.uniform(0.0, config.backoff_jitter)
    )


def _is_retryable_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS_CODES


def _is_retryable_request_exception(exc: BaseException) -> bool:
    """Check if an httpx exception is worth retrying.

    ReadTimeout / ConnectError / NetworkError are transient network
    conditions that often resolve on retry (e.g. provider throttling
    during a burst). Other httpx exceptions (SSLError, etc.) are
    configuration / environment issues that retry won't fix.
    """
    import httpx

    return isinstance(
        exc,
        (
            httpx.ReadTimeout,
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.NetworkError,
        ),
    )


def _parse_retry_after(header_value: str, max_seconds: float) -> float | None:
    """Parse an HTTP Retry-After header value into seconds to wait.

    Per RFC 7231, Retry-After can be either:
      - A non-negative integer (seconds to wait)
      - An HTTP-date (we approximate as 0 since we don't have a clock
        skew budget for this)
    Returns None if the header is missing, empty, or unparseable.
    Caps the result at max_seconds to prevent absurd waits.
    """
    if not header_value:
        return None
    header_value = header_value.strip()
    # Try seconds (integer or float)
    try:
        seconds = float(header_value)
        if seconds < 0:
            return None
        return min(seconds, max_seconds)
    except ValueError:
        pass
    # HTTP-date: just return 0 (we honor the spirit by not retrying
    # sooner; parsing the date and computing wait would require a
    # clock skew budget we don't track).
    return 0.0


def _extract_retry_after(resp: Any, max_seconds: float) -> float | None:
    """Extract Retry-After header from a requests or httpx response."""
    try:
        # requests.Response: case-insensitive header access
        if hasattr(resp, "headers"):
            headers = resp.headers
            # requests uses a CaseInsensitiveDict; httpx uses a regular dict
            value = None
            if hasattr(headers, "get"):
                value = headers.get("Retry-After")
            if value is not None:
                return _parse_retry_after(value, max_seconds)
    except Exception:
        return None
    return None


# ─── Retry metrics ──────────────────────────────────────────────


@dataclass
class RetryMetrics:
    """Cumulative metrics for LLM retry behavior across the process.

    Thread-safe; counters are updated under a lock. Designed for
    lightweight in-process observability (no external stats system
    required). For longer-term monitoring, push to a metrics backend
    via a separate exporter.

    Fields:
        total_calls: total LLM POSTs attempted (including retries).
        calls_completed: total POSTs that returned (any status, after
            all retries exhausted or 1st-try success).
        success_first_try: calls that succeeded on attempt 0.
        success_after_retry: calls that needed 1+ retries to succeed.
        failed_after_retries: calls that failed on every attempt.
        total_retries: cumulative retry count across all calls.
        by_outcome: counts per outcome category ("ok", "client_error",
            "rate_limit", "server_error", "timeout", "connection").
        by_retries: histogram of {retry_count: calls_count}, where
            retry_count is the number of retries needed to reach
            success (0 for first-try success, max for final failure).
    """

    total_calls: int = 0
    calls_completed: int = 0
    success_first_try: int = 0
    success_after_retry: int = 0
    failed_after_retries: int = 0
    total_retries: int = 0
    by_outcome: dict[str, int] = field(default_factory=dict)
    by_retries: dict[int, int] = field(default_factory=dict)

    def record_call(
        self,
        *,
        outcome: str,
        attempts_used: int,
    ) -> None:
        """Record a completed LLM call.

        Args:
            outcome: one of "ok", "client_error" (4xx not retried),
                "rate_limit" (429, possibly retried), "server_error"
                (5xx, possibly retried), "timeout", "connection".
            attempts_used: total attempts including the final one
                (1 = no retries needed; max+1 = retries exhausted).
        """
        self.calls_completed += 1
        self.by_outcome[outcome] = self.by_outcome.get(outcome, 0) + 1
        retries_needed = max(attempts_used - 1, 0)
        self.by_retries[retries_needed] = (
            self.by_retries.get(retries_needed, 0) + 1
        )
        if outcome == "ok":
            if retries_needed == 0:
                self.success_first_try += 1
            else:
                self.success_after_retry += 1
                self.total_retries += retries_needed
        else:
            if retries_needed > 0:
                self.total_retries += retries_needed
            self.failed_after_retries += 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the metrics."""
        total = max(self.calls_completed, 1)
        return {
            "calls_completed": self.calls_completed,
            "total_retries": self.total_retries,
            "success_first_try": self.success_first_try,
            "success_after_retry": self.success_after_retry,
            "failed_after_retries": self.failed_after_retries,
            "success_rate": round(
                (self.success_first_try + self.success_after_retry) / total, 4
            ),
            "first_try_rate": round(self.success_first_try / total, 4),
            "by_outcome": dict(self.by_outcome),
            "by_retries": {str(k): v for k, v in sorted(self.by_retries.items())},
        }


# Process-wide metrics singleton, protected by a lock so concurrent
# threads can update safely.
_retry_metrics_lock = threading.Lock()
_retry_metrics = RetryMetrics()


def get_retry_metrics() -> RetryMetrics:
    """Return the process-wide RetryMetrics instance.

    Mutate via ``.record_call(...)``. To snapshot for logging,
    use ``.to_dict()``.
    """
    return _retry_metrics


def reset_retry_metrics() -> None:
    """Reset all retry counters to zero. Useful for tests."""
    global _retry_metrics
    with _retry_metrics_lock:
        _retry_metrics = RetryMetrics()


def _classify_outcome(
    *,
    success: bool,
    status_code: int | None,
    exc: BaseException | None,
) -> str:
    """Map a (success, status, exc) tuple to an outcome category."""
    if success:
        return "ok"
    if status_code is not None:
        if status_code == 429:
            return "rate_limit"
        if 500 <= status_code < 600:
            return "server_error"
        if 400 <= status_code < 500:
            return "client_error"
    if exc is not None:
        name = type(exc).__name__
        if "Timeout" in name:
            return "timeout"
        if "Connection" in name or "Network" in name:
            return "connection"
    return "unknown"


class LLMRequestError(RuntimeError):
    """Raised when the LLM provider returns a 4xx/5xx response.

    Unlike ``httpx.HTTPStatusError`` or ``requests.HTTPError`` (which
    only embed the status line and URL), this exception carries the
    provider's error body so the user can see *why* the call failed —
    e.g. MiniMax's ``{"error":{"message":"invalid params, messages
    is empty (2013)"}}`` instead of a bare ``400 Bad Request``.
    """

    def __init__(self, status_code: int, url: str, body: str):
        self.status_code = status_code
        self.url = url
        self.body = body
        # Truncate body to keep logs readable
        preview = body[:500] + ("…" if len(body) > 500 else "")
        super().__init__(
            f"LLM API returned {status_code} for {url}: {preview}"
        )


def _validate_request(
    messages: list[dict[str, Any]] | None,
    generation_params: dict[str, Any] | None = None,
) -> None:
    """Pre-flight validation for chat completion requests.

    Catches the most common provider-side rejections *before* they
    cost a network round-trip:

      - Empty ``messages`` (MiniMax error 2013)
      - ``top_p`` outside the OpenAI-compatible (0, 1] range
      - ``temperature`` outside [0, 2] (Anthropic-compatible ceiling)

    Provider-specific quirks (e.g. MiniMax reasoning_split + tools
    combinations) are not validated here — they will surface as
    ``LLMRequestError`` with the full body, which is informative
    enough to diagnose.
    """
    if not messages:
        raise ValueError(
            "messages must be a non-empty list of role/content dicts; "
            "got empty list. Add at least one system or user message "
            "before calling the LLM."
        )
    params = generation_params or {}
    if "top_p" in params:
        top_p = params["top_p"]
        if not isinstance(top_p, (int, float)) or not (0.0 < top_p <= 1.0):
            raise ValueError(
                f"top_p must be a number in (0, 1]; got {top_p!r}"
            )
    if "temperature" in params:
        temp = params["temperature"]
        if not isinstance(temp, (int, float)) or not (0.0 <= temp <= 2.0):
            raise ValueError(
                f"temperature must be a number in [0, 2]; got {temp!r}"
            )


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


# ─── Retry-aware HTTP helpers ──────────────────────────────────


def _record_retry_outcome(
    *,
    success: bool,
    status_code: int | None,
    exc: BaseException | None,
    attempts_used: int,
) -> None:
    """Record retry outcome to the process-wide RetryMetrics singleton."""
    outcome = _classify_outcome(
        success=success, status_code=status_code, exc=exc,
    )
    with _retry_metrics_lock:
        _retry_metrics.record_call(
            outcome=outcome,
            attempts_used=attempts_used,
        )


def _post_with_retry_sync(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    config: RetryConfig | None = None,
) -> Any:
    """POST with exponential-backoff retry on transient failures.

    Uses ``httpx.Client`` for the HTTP call. Returns the final
    ``httpx.Response`` (caller is responsible for closing it).
    The response is never retryable-status (429/5xx); if the final
    attempt returns such a status, the response is returned and the
    caller decides what to do (typically raise via
    ``_format_http_error``).

    Network exceptions (ReadTimeout / ConnectError / ConnectTimeout /
    NetworkError) are retried up to ``config.max_retries`` times.
    After exhaustion, the last exception is re-raised.

    Honors the ``Retry-After`` HTTP response header (when present on
    429/503 responses) over the computed exponential backoff, capped
    at ``config.retry_after_max_seconds``.
    """
    import httpx

    if config is None:
        config = RetryConfig.from_env()

    last_exc: BaseException | None = None
    for attempt in range(config.max_retries + 1):
        attempts_used = attempt + 1
        try:
            resp = httpx.Client(timeout=timeout_seconds).post(
                url, headers=headers, json=payload,
            )
        except Exception as e:
            if _is_retryable_request_exception(e) and attempt < config.max_retries:
                wait = _compute_backoff(attempt, config)
                logger.warning(
                    "LLM POST %s failed with %s (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    url, type(e).__name__, attempt + 1,
                    config.max_retries + 1, wait, e,
                )
                last_exc = e
                time.sleep(wait)
                continue
            _record_retry_outcome(
                success=False, status_code=None, exc=e,
                attempts_used=attempts_used,
            )
            raise

        if _is_retryable_status(resp.status_code) and attempt < config.max_retries:
            retry_after = _extract_retry_after(resp, config.retry_after_max_seconds)
            wait = retry_after if retry_after is not None else _compute_backoff(attempt, config)
            reason = "Retry-After" if retry_after is not None else "backoff"
            logger.warning(
                "LLM POST %s returned %d (attempt %d/%d), "
                "retrying in %.1fs (%s)",
                url, resp.status_code, attempt + 1,
                config.max_retries + 1, wait, reason,
            )
            resp.close()
            time.sleep(wait)
            continue

        _record_retry_outcome(
            success=200 <= resp.status_code < 300,
            status_code=resp.status_code, exc=None,
            attempts_used=attempts_used,
        )
        return resp

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry loop exited without returning a response")


async def _post_with_retry_async(
    client: Any,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    config: RetryConfig | None = None,
) -> Any:
    """Async POST with exponential-backoff retry on transient failures.

    Takes an already-constructed ``httpx.AsyncClient`` and reuses it
    across retries. Returns the final ``httpx.Response``.

    Network exceptions (httpx.ReadTimeout / ConnectError / etc.) and
    retryable HTTP statuses (429/5xx) trigger backoff + retry. Honors
    the ``Retry-After`` response header over the computed backoff,
    capped at ``config.retry_after_max_seconds``.

    Records outcome to the process-wide ``RetryMetrics`` instance.
    """
    if config is None:
        config = RetryConfig.from_env()

    last_exc: BaseException | None = None
    for attempt in range(config.max_retries + 1):
        attempts_used = attempt + 1
        try:
            resp = await client.request(method, url, headers=headers, json=payload)
        except Exception as e:
            if _is_retryable_request_exception(e) and attempt < config.max_retries:
                wait = _compute_backoff(attempt, config)
                logger.warning(
                    "LLM %s %s failed with %s (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    method, url, type(e).__name__, attempt + 1,
                    config.max_retries + 1, wait, e,
                )
                last_exc = e
                time.sleep(wait)
                continue
            _record_retry_outcome(
                success=False, status_code=None, exc=e,
                attempts_used=attempts_used,
            )
            raise

        if _is_retryable_status(resp.status_code) and attempt < config.max_retries:
            retry_after = _extract_retry_after(resp, config.retry_after_max_seconds)
            wait = retry_after if retry_after is not None else _compute_backoff(attempt, config)
            reason = "Retry-After" if retry_after is not None else "backoff"
            logger.warning(
                "LLM %s %s returned %d (attempt %d/%d), "
                "retrying in %.1fs (%s)",
                method, url, resp.status_code, attempt + 1,
                config.max_retries + 1, wait, reason,
            )
            await resp.aclose()
            time.sleep(wait)
            continue

        _record_retry_outcome(
            success=200 <= resp.status_code < 300,
            status_code=resp.status_code, exc=None,
            attempts_used=attempts_used,
        )
        return resp

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("async retry loop exited without returning a response")


class StreamableLLMClient(LLMClient):
    """LLM client with streaming and function calling support.

    Extends basic LLMClient with:
    - stream_chat(): SSE-compatible streaming
    - chat_with_tools(): Function calling support
    - astream_chat(): Async streaming
    - achat(): Async non-streaming
    - reasoning_split mode (chain-of-thought separation)
    - Configurable auth header (bearer / api-key)

    Token budget checking is applied automatically via decorator.
    Pass ``_prompt_name="..."`` in generation_params to label calls in logs.

    .. note::

        This class extends :class:`LLMClient` purely for type hierarchy
        (``isinstance(client, LLMClient) == True``). It does **not** call
        ``super().__init__()`` because its ``__init__`` signature is a
        strict superset of ``LLMClient.__init__`` (adds ``reasoning_split``
        and ``auth_header``) AND its ``base_url`` normalization strips a
        trailing ``/v1`` segment that LLMClient's does not.

        As a result, code that takes an ``LLMClient`` argument will accept
        a ``StreamableLLMClient`` instance, but the converse is not true:
        an LLMClient-only consumer cannot call ``stream_chat`` etc.
    """

    def __init__(
        self,
        provider: str | None = None,
        base_url: str = "",
        api_key: str = "",
        model: str | None = None,
        reasoning_split: bool = False,
        auth_header: str = "bearer",
        context_window: int | None = None,
        budget_on_exceed: str = "warn",
        request_timeout_seconds: float = 120,
    ):
        # LAL (PR 4): default provider/model are None. When neither
        # is supplied, raise LLMNotConfiguredError unless the
        # historical fallback kill-switch is on.
        if not _legacy_fallback_enabled():
            if provider is None:
                raise LLMNotConfiguredError(
                    "StreamableLLMClient() requires a provider; pass "
                    "provider=... or use StreamableLLMClient.from_spec()."
                )
            if model is None:
                raise LLMNotConfiguredError(
                    "StreamableLLMClient() requires a model; pass "
                    "model=... or use StreamableLLMClient.from_spec()."
                )
        else:
            provider = provider or "openai"
            model = model or "gpt-4o"
        self.provider = provider
        raw_base = base_url if base_url else self._default_base_url(provider)
        self.base_url = raw_base.rstrip("/").removesuffix("/v1")
        self.api_key = api_key
        self.model = model
        self.reasoning_split = reasoning_split
        self.auth_header = auth_header  # "bearer" or "api-key"
        self.request_timeout_seconds = request_timeout_seconds

        self._budget_checker = TokenBudgetChecker(
            TokenBudgetConfig(
                model=model,
                context_window=context_window,
                base_url=self.base_url,
                api_key=api_key,
                on_exceed=budget_on_exceed,
            )
        )

    @staticmethod
    def _default_base_url(provider: str) -> str:
        defaults = {
            "openai": "https://api.openai.com",
            "ollama": "http://localhost:11434/v1",
            "lmstudio": "http://localhost:1234/v1",
            "minimax": "https://api.minimaxi.com/v1",
            "xiaomi": "https://token-plan-cn.xiaomimimo.com",
        }
        return defaults.get(provider, "https://api.openai.com")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> StreamableLLMClient:
        """Build a client from the ``llm.*`` section of a wiki config.

        This is a pure config-to-constructor translation; it does
        NOT consult the LLM provider registry (that lives at
        L3 in ``llmwikify.apps.chat.providers.registry``).
        Callers that need the registry's provider discovery
        should call ``apps.chat.providers.registry.create_llm``
        directly.

        LAL: delegates to ``resolve_chat_llm`` (the single resolver
        entry point) when ``LLM_USE_RESOLVER`` is not set to
        ``"false"``. The legacy inline path is preserved as a
        kill-switch fallback for resolver regressions.
        """
        if resolver_enabled():
            spec = resolve_chat_llm(config)
            return cls.from_spec(spec)
        llm_cfg = config.get("llm", config)
        return cls(
            provider=llm_cfg.get("provider", "openai"),
            base_url=llm_cfg.get("base_url", ""),
            api_key=llm_cfg.get("api_key", ""),
            model=llm_cfg.get("model", "gpt-4o"),
            context_window=llm_cfg.get("context_window"),
            budget_on_exceed=llm_cfg.get("budget_on_exceed", "warn"),
            request_timeout_seconds=llm_cfg.get("timeout", 120),
        )

    @classmethod
    def from_spec(cls, spec: LLMSpec) -> StreamableLLMClient:
        """Build a client from a fully-resolved ``LLMSpec``.

        This is the canonical construction path for code that has
        already resolved LLM configuration via
        ``resolve_chat_llm``. Unlike ``from_config`` it does NOT
        re-parse env vars or config dicts — it trusts the spec.
        """
        return cls(
            provider=spec.provider,
            base_url=spec.base_url,
            api_key=spec.api_key,
            model=spec.model,
            context_window=spec.context_window,
            reasoning_split=spec.reasoning_split,
            auth_header=spec.auth_scheme,
            request_timeout_seconds=spec.timeout,
            budget_on_exceed=spec.budget_on_exceed,
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Synchronous non-streaming chat completion (canonical LAL name).

        LAL: this is the canonical sync entry point. It is currently
        a thin alias for ``chat``; the name is preferred in new code
        so that the LAL contract is uniform across providers.
        """
        return self.chat(messages, json_mode=json_mode, **generation_params)

    def _chat_url(self) -> str:
        """Build chat completions URL, avoiding double /v1/v1/."""
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _build_headers(self) -> dict[str, str]:
        """Build HTTP headers with appropriate auth scheme."""
        headers = {"Content-Type": "application/json"}
        if self.auth_header == "api-key":
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @check_token_budget(lambda self: self._budget_checker)
    def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Chat completion — internally uses streaming to avoid timeout."""
        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        import httpx

        config = RetryConfig.from_env()
        last_exc: BaseException | None = None

        for attempt in range(config.max_retries + 1):
            attempts_used = attempt + 1
            try:
                resp = httpx.Client(
                    timeout=httpx.Timeout(connect=30, read=300, write=30),
                ).stream("POST", url, headers=headers, json=payload).__enter__()
            except Exception as e:
                if _is_retryable_request_exception(e) and attempt < config.max_retries:
                    wait = _compute_backoff(attempt, config)
                    logger.warning(
                        "LLM chat %s failed with %s (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        url, type(e).__name__, attempt + 1,
                        config.max_retries + 1, wait, e,
                    )
                    last_exc = e
                    time.sleep(wait)
                    continue
                _record_retry_outcome(
                    success=False, status_code=None, exc=e,
                    attempts_used=attempts_used,
                )
                raise

            if _is_retryable_status(resp.status_code) and attempt < config.max_retries:
                retry_after = _extract_retry_after(resp, config.retry_after_max_seconds)
                wait = retry_after if retry_after is not None else _compute_backoff(attempt, config)
                reason = "Retry-After" if retry_after is not None else "backoff"
                logger.warning(
                    "LLM chat %s returned %d (attempt %d/%d), "
                    "retrying in %.1fs (%s)",
                    url, resp.status_code, attempt + 1,
                    config.max_retries + 1, wait, reason,
                )
                resp.close()
                time.sleep(wait)
                continue

            _record_retry_outcome(
                success=200 <= resp.status_code < 300,
                status_code=resp.status_code, exc=None,
                attempts_used=attempts_used,
            )
            break
        else:
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("chat retry loop exited unexpectedly")

        try:
            if resp.status_code >= 400:
                body = resp.read()
                raise _format_http_error(resp.status_code, url, body)
            accumulated = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    return accumulated
                try:
                    chunk = json.loads(line)
                except Exception:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if "content" in delta and delta["content"]:
                    accumulated += delta["content"]
                finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
                if finish in ("stop", "length"):
                    return accumulated
            return accumulated
        finally:
            resp.close()

    @check_token_budget(lambda self: self._budget_checker)
    def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ) -> dict[str, Any]:
        """Chat with function calling support.

        Returns:
            {"content": str, "tool_calls": [{"name": str, "args": dict}] | None}
        """
        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        resp = _post_with_retry_sync(
            url,
            headers,
            payload,
            timeout_seconds=self.request_timeout_seconds,
        )
        try:
            if resp.status_code >= 400:
                raise _format_http_error(resp.status_code, url, resp.content)
            data = resp.json()
            message = data["choices"][0]["message"]

            result: dict[str, Any] = {"content": message.get("content", "")}
            if "tool_calls" in message and message["tool_calls"]:
                result["tool_calls"] = [
                    {
                        "name": tc["function"]["name"],
                        "args": tc["function"]["arguments"],
                    }
                    for tc in message["tool_calls"]
                ]
            return result
        finally:
            resp.close()

    @check_token_budget(lambda self: self._budget_checker)
    def stream_chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ):
        """Streaming chat completion (yield chunks) — sync version using httpx.

        Yields:
            dict: {"type": "content", "text": str} or
                  {"type": "tool_call", "tool": str, "args": dict} or
                  {"type": "done", "content": str}

        Retry+backoff is applied to the initial connection. Mid-stream
        failures are NOT retried (the request has been billed and the
        caller is consuming the body).
        """
        import httpx

        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        config = RetryConfig.from_env()
        last_exc: BaseException | None = None

        for attempt in range(config.max_retries + 1):
            attempts_used = attempt + 1
            try:
                resp = httpx.Client(
                    timeout=httpx.Timeout(connect=30, read=300, write=30),
                ).stream("POST", url, headers=headers, json=payload).__enter__()
            except Exception as e:
                if _is_retryable_request_exception(e) and attempt < config.max_retries:
                    wait = _compute_backoff(attempt, config)
                    logger.warning(
                        "LLM stream %s failed with %s (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        url, type(e).__name__, attempt + 1,
                        config.max_retries + 1, wait, e,
                    )
                    last_exc = e
                    time.sleep(wait)
                    continue
                _record_retry_outcome(
                    success=False, status_code=None, exc=e,
                    attempts_used=attempts_used,
                )
                raise

            if _is_retryable_status(resp.status_code) and attempt < config.max_retries:
                retry_after = _extract_retry_after(resp, config.retry_after_max_seconds)
                wait = retry_after if retry_after is not None else _compute_backoff(attempt, config)
                reason = "Retry-After" if retry_after is not None else "backoff"
                logger.warning(
                    "LLM stream %s returned %d (attempt %d/%d), "
                    "retrying in %.1fs (%s)",
                    url, resp.status_code, attempt + 1,
                    config.max_retries + 1, wait, reason,
                )
                resp.close()
                time.sleep(wait)
                continue

            _record_retry_outcome(
                success=200 <= resp.status_code < 300,
                status_code=resp.status_code, exc=None,
                attempts_used=attempts_used,
            )
            break
        else:
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("stream retry loop exited unexpectedly")

        try:
            if resp.status_code >= 400:
                body = resp.read()
                raise _format_http_error(resp.status_code, url, body)
            accumulated = ""
            tool_call_buffer: dict[int, dict] = {}
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    yield {"type": "done", "content": accumulated}
                    return
                try:
                    chunk = json.loads(line)
                except Exception:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if "reasoning_content" in delta and delta["reasoning_content"]:
                    yield {"type": "thinking", "text": delta["reasoning_content"]}
                if "content" in delta and delta["content"]:
                    accumulated += delta["content"]
                    yield {"type": "content", "text": delta["content"]}

                if "tool_calls" in delta:
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        if idx not in tool_call_buffer:
                            tool_call_buffer[idx] = {
                                "id": tc.get("id", ""),
                                "name": "",
                                "args_parts": [],
                            }
                        entry = tool_call_buffer[idx]
                        if "id" in tc and tc["id"]:
                            entry["id"] = tc["id"]
                        func = tc.get("function", {})
                        if "name" in func and func["name"]:
                            entry["name"] = func["name"]
                        if "arguments" in func and func["arguments"]:
                            entry["args_parts"].append(func["arguments"])

                finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
                if finish in ("stop", "tool_calls", "length"):
                    for entry in tool_call_buffer.values():
                        yield {
                            "type": "tool_call",
                            "tool": entry["name"],
                            "args": "".join(entry["args_parts"]),
                        }
                    tool_call_buffer.clear()
                    yield {
                        "type": "done",
                        "content": accumulated,
                        "finish_reason": finish,
                    }
                    return
        finally:
            resp.close()

    @check_token_budget(lambda self: self._budget_checker)
    async def astream_chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        **generation_params: Any,
    ):
        """Async streaming chat completion using httpx.

        Yields:
            dict: {"type": "content", "text": str} or
                  {"type": "tool_call", "tool": str, "args": dict} or
                  {"type": "done", "content": str}

        Retry+backoff is applied to the initial connection. Mid-stream
        failures are NOT retried (the request has been billed and the
        caller is consuming the body).
        """
        import httpx

        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=300, write=30)) as client:
            config = RetryConfig.from_env()
            last_exc: BaseException | None = None

            for attempt in range(config.max_retries + 1):
                attempts_used = attempt + 1
                try:
                    stream_ctx = client.stream("POST", url, headers=headers, json=payload)
                    resp = await stream_ctx.__aenter__()
                except Exception as e:
                    if _is_retryable_request_exception(e) and attempt < config.max_retries:
                        wait = _compute_backoff(attempt, config)
                        logger.warning(
                            "LLM astream %s failed with %s (attempt %d/%d), "
                            "retrying in %.1fs: %s",
                            url, type(e).__name__, attempt + 1,
                            config.max_retries + 1, wait, e,
                        )
                        last_exc = e
                        time.sleep(wait)
                        continue
                    _record_retry_outcome(
                        success=False, status_code=None, exc=e,
                        attempts_used=attempts_used,
                    )
                    raise

                if _is_retryable_status(resp.status_code) and attempt < config.max_retries:
                    retry_after = _extract_retry_after(resp, config.retry_after_max_seconds)
                    wait = retry_after if retry_after is not None else _compute_backoff(attempt, config)
                    reason = "Retry-After" if retry_after is not None else "backoff"
                    logger.warning(
                        "LLM astream %s returned %d (attempt %d/%d), "
                        "retrying in %.1fs (%s)",
                        url, resp.status_code, attempt + 1,
                        config.max_retries + 1, wait, reason,
                    )
                    await stream_ctx.__aexit__(None, None, None)
                    time.sleep(wait)
                    continue

                _record_retry_outcome(
                    success=200 <= resp.status_code < 300,
                    status_code=resp.status_code, exc=None,
                    attempts_used=attempts_used,
                )
                break
            else:
                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("astream retry loop exited unexpectedly")

            try:
                if resp.status_code >= 400:
                    # Drain the body so we can include the API's
                    # diagnostic in the raised error.
                    body = await resp.aread()
                    raise _format_http_error(resp.status_code, url, body)
                accumulated = ""
                tool_call_buffer: dict[int, dict] = {}
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if line == "[DONE]":
                        yield {"type": "done", "content": accumulated}
                        return
                    try:
                        import json as _json
                        chunk = _json.loads(line)
                    except Exception:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    # Handle reasoning_content (MiniMax reasoning_split mode).
                    # Chain-of-thought is yielded as a "thinking" event but is
                    # NOT mixed into the final "content" — downstream consumers
                    # that wait for the final string should get only the answer.
                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        yield {"type": "thinking", "text": delta["reasoning_content"]}
                    # Handle regular content (only this goes into accumulated)
                    if "content" in delta and delta["content"]:
                        accumulated += delta["content"]
                        yield {"type": "content", "text": delta["content"]}

                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_call_buffer:
                                tool_call_buffer[idx] = {
                                    "id": tc.get("id", ""),
                                    "name": "",
                                    "args_parts": [],
                                }
                            entry = tool_call_buffer[idx]
                            if "id" in tc and tc["id"]:
                                entry["id"] = tc["id"]
                            func = tc.get("function", {})
                            if "name" in func and func["name"]:
                                entry["name"] = func["name"]
                            if "arguments" in func and func["arguments"]:
                                entry["args_parts"].append(func["arguments"])

                    finish = chunk.get("choices", [{}])[0].get("finish_reason", "")
                    # "length" must also emit "done" — otherwise callers waiting
                    # for the done event would hang when the model hits
                    # max_tokens mid-stream.
                    if finish in ("stop", "tool_calls", "length"):
                        for entry in tool_call_buffer.values():
                            yield {
                                "type": "tool_call",
                                "tool": entry["name"],
                                "args": "".join(entry["args_parts"]),
                            }
                        tool_call_buffer.clear()
                        yield {
                            "type": "done",
                            "content": accumulated,
                            "finish_reason": finish,
                        }
                        return
            finally:
                await stream_ctx.__aexit__(None, None, None)

    @check_token_budget(lambda self: self._budget_checker)
    async def achat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **generation_params: Any,
    ) -> str:
        """Async non-streaming chat completion using httpx."""
        import httpx

        _validate_request(messages, generation_params)

        url = self._chat_url()
        headers = self._build_headers()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_split:
            payload["reasoning_split"] = True
        for key in ("temperature", "max_tokens", "top_p"):
            if key in generation_params:
                payload[key] = generation_params[key]

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=300, write=30)) as client:
            resp = await _post_with_retry_async(
                client,
                "POST",
                url,
                headers,
                payload,
            )
            try:
                if resp.status_code >= 400:
                    raise _format_http_error(resp.status_code, url, resp.content)
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            finally:
                await resp.aclose()
