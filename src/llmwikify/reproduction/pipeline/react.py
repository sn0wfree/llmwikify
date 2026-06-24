"""Three-tier ReAct engine for pipeline failure recovery.

FailureClassifier → classify raw exceptions into actionable categories.
PipelineReAct     → reason / act / observe loop that decides retry vs abort.
StageFailure      → structured record of a single failure event.
Decision          → enum of ReAct outcomes.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Decision ──────────────────────────────────────────────────


class Decision(str, Enum):
    """Outcome of a ReAct iteration."""

    RETRY = "retry"
    SKIP = "skip"
    ABORT = "abort"
    FALLBACK = "fallback"


# ── StageFailure ──────────────────────────────────────────────


@dataclass
class StageFailure:
    """Structured record of a single stage failure."""

    stage_name: str
    error_kind: str
    message: str
    attempt: int = 1
    elapsed_sec: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)


# ── FailureClassifier ────────────────────────────────────────


class FailureClassifier:
    """Classify raw exceptions into actionable categories.

    Returns a ``(kind, suggestion)`` tuple suitable for the ReAct
    decision step.
    """

    @staticmethod
    def classify(error: Exception) -> tuple[str, str]:
        """Classify *error* and return ``(kind, suggestion)``."""
        err_str = str(error).lower()

        if "timeout" in err_str or "timed out" in err_str:
            return "timeout", "Increase timeout or simplify the stage."

        if "memory" in err_str or "oom" in err_str:
            return "resource_exhausted", "Reduce data volume or add memory."

        if "permission" in err_str or "access denied" in err_str:
            return "permission", "Check file permissions."

        if "connection" in err_str or "network" in err_str:
            return "network", "Retry later or check connectivity."

        if "notfound" in err_str or "no such file" in err_str:
            return "not_found", "Verify the path exists."

        return "unknown", "Review logs and retry."


# ── PipelineReAct ────────────────────────────────────────────


class PipelineReAct:
    """Three-tier ReAct loop: classify → decide → act.

    Args:
        classifier: Optional custom FailureClassifier.
        max_retries: Maximum number of retry attempts.
    """

    def __init__(
        self,
        classifier: FailureClassifier | None = None,
        max_retries: int = 3,
    ) -> None:
        self.classifier = classifier or FailureClassifier()
        self.max_retries = max_retries
        self.failures: list[StageFailure] = []

    def handle_failure(
        self,
        stage_name: str,
        error: Exception,
        attempt: int = 1,
        elapsed_sec: float = 0.0,
    ) -> Decision:
        """Classify the failure and decide whether to retry/skip/abort.

        Args:
            stage_name: Name of the failed stage.
            error: The caught exception.
            attempt: Current attempt number (1-indexed).
            elapsed_sec: Time elapsed in the failed stage.

        Returns:
            A Decision enum value.
        """
        kind, suggestion = self.classifier.classify(error)
        failure = StageFailure(
            stage_name=stage_name,
            error_kind=kind,
            message=str(error),
            attempt=attempt,
            elapsed_sec=elapsed_sec,
            context={"suggestion": suggestion},
        )
        self.failures.append(failure)
        logger.warning(
            "Stage %r failed (attempt %d/%d): [%s] %s",
            stage_name,
            attempt,
            self.max_retries,
            kind,
            str(error)[:120],
        )

        if attempt >= self.max_retries:
            if kind in ("timeout", "network"):
                return Decision.ABORT
            return Decision.SKIP

        if kind in ("timeout", "network", "resource_exhausted"):
            return Decision.RETRY
        if kind in ("permission", "not_found"):
            return Decision.SKIP
        return Decision.RETRY
