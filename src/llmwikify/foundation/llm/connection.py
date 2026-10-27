"""HTTP connection + retry / backoff machinery for OpenAI-compatible LLMs.

Split from ``streamable.py`` (dual-stack merge, 2026-10-23).
"""


from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

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
    def from_env(cls) -> RetryConfig:
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
                    name,
                    raw,
                    default,
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
                        name,
                        v,
                        default,
                    )
                    return default
                return v
            except ValueError:
                logger.warning(
                    "%s=%r is not a valid int; using default %d",
                    name,
                    raw,
                    default,
                )
                return default

        return cls(
            max_retries=_read_int("LLM_RETRY_MAX_RETRIES", _DEFAULT_MAX_RETRIES),
            backoff_base=_read_float("LLM_RETRY_BACKOFF_BASE", _DEFAULT_BACKOFF_BASE),
            backoff_factor=_read_float(
                "LLM_RETRY_BACKOFF_FACTOR", _DEFAULT_BACKOFF_FACTOR
            ),
            backoff_jitter=_read_float(
                "LLM_RETRY_BACKOFF_JITTER", _DEFAULT_BACKOFF_JITTER
            ),
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
    return config.backoff_base * (config.backoff_factor**attempt) + random.uniform(
        0.0, config.backoff_jitter
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
        self.by_retries[retries_needed] = self.by_retries.get(retries_needed, 0) + 1
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
        success=success,
        status_code=status_code,
        exc=exc,
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

    with httpx.Client(timeout=timeout_seconds) as client:
        last_exc: BaseException | None = None
        for attempt in range(config.max_retries + 1):
            attempts_used = attempt + 1
            try:
                resp = client.post(url, headers=headers, json=payload)
            except (
                httpx.ReadTimeout,
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.NetworkError,
            ) as e:
                if _is_retryable_request_exception(e) and attempt < config.max_retries:
                    wait = _compute_backoff(attempt, config)
                    logger.warning(
                        "LLM POST %s failed with %s (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        url,
                        type(e).__name__,
                        attempt + 1,
                        config.max_retries + 1,
                        wait,
                        e,
                    )
                    last_exc = e
                    time.sleep(wait)
                    continue
                _record_retry_outcome(
                    success=False,
                    status_code=None,
                    exc=e,
                    attempts_used=attempts_used,
                )
                raise
            except Exception as e:
                logger.warning("LLM POST %s unexpected error: %s", url, e)
                _record_retry_outcome(
                    success=False,
                    status_code=None,
                    exc=e,
                    attempts_used=attempts_used,
                )
                raise

            if _is_retryable_status(resp.status_code) and attempt < config.max_retries:
                retry_after = _extract_retry_after(resp, config.retry_after_max_seconds)
                wait = (
                    retry_after
                    if retry_after is not None
                    else _compute_backoff(attempt, config)
                )
                reason = "Retry-After" if retry_after is not None else "backoff"
                logger.warning(
                    "LLM POST %s returned %d (attempt %d/%d), "
                    "retrying in %.1fs (%s)",
                    url,
                    resp.status_code,
                    attempt + 1,
                    config.max_retries + 1,
                    wait,
                    reason,
                )
                resp.close()
                time.sleep(wait)
                continue

            _record_retry_outcome(
                success=200 <= resp.status_code < 300,
                status_code=resp.status_code,
                exc=None,
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
    import httpx

    if config is None:
        config = RetryConfig.from_env()

    last_exc: BaseException | None = None
    for attempt in range(config.max_retries + 1):
        attempts_used = attempt + 1
        try:
            resp = await client.request(method, url, headers=headers, json=payload)
        except (
            httpx.ReadTimeout,
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.NetworkError,
        ) as e:
            if _is_retryable_request_exception(e) and attempt < config.max_retries:
                wait = _compute_backoff(attempt, config)
                logger.warning(
                    "LLM %s %s failed with %s (attempt %d/%d), "
                    "retrying in %.1fs: %s",
                    method,
                    url,
                    type(e).__name__,
                    attempt + 1,
                    config.max_retries + 1,
                    wait,
                    e,
                )
                last_exc = e
                await asyncio.sleep(wait)
                continue
            _record_retry_outcome(
                success=False,
                status_code=None,
                exc=e,
                attempts_used=attempts_used,
            )
            raise
        except Exception as e:
            logger.warning("LLM %s %s unexpected error: %s", method, url, e)
            _record_retry_outcome(
                success=False,
                status_code=None,
                exc=e,
                attempts_used=attempts_used,
            )
            raise

        if _is_retryable_status(resp.status_code) and attempt < config.max_retries:
            retry_after = _extract_retry_after(resp, config.retry_after_max_seconds)
            wait = (
                retry_after
                if retry_after is not None
                else _compute_backoff(attempt, config)
            )
            reason = "Retry-After" if retry_after is not None else "backoff"
            logger.warning(
                "LLM %s %s returned %d (attempt %d/%d), " "retrying in %.1fs (%s)",
                method,
                url,
                resp.status_code,
                attempt + 1,
                config.max_retries + 1,
                wait,
                reason,
            )
            await resp.aclose()
            await asyncio.sleep(wait)
            continue

        _record_retry_outcome(
            success=200 <= resp.status_code < 300,
            status_code=resp.status_code,
            exc=None,
            attempts_used=attempts_used,
        )
        return resp

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("async retry loop exited without returning a response")


