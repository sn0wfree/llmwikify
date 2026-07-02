"""Research state, transitions, and metrics.

This module houses the data classes that describe the state of a
research session in flight, the state machine that governs valid
transitions, and the per-action / per-session metrics. These were
previously declared at the top of engine.py; moving them here lets
engine.py focus on orchestration.

Re-exports: The ``__init__.py`` re-exports ``ResearchState``,
``ActionMetrics``, ``SessionMetrics``, ``MetricsCollector``,
and ``VALID_TRANSITIONS`` so existing imports
(``from llmwikify.apps.chat import ResearchState``,
``from .engine import VALID_TRANSITIONS``) continue to work unchanged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ─── State machine ────────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[str | None, list[str]] = {
    None:           ["clarifying", "plan"],   # 6-step: clarify first
    "clarifying":   ["plan"],                 # 6-step new state
    "planning":     ["gather"],
    "gathering":    ["analyze", "plan"],
    "analyzing":    ["synthesizing", "plan"],
    "synthesizing": ["reporting", "plan"],
    "reporting":    ["reviewing"],
    "reviewing":    ["revise", "done"],
    "revise":       ["reviewing", "done"],
    "error":        ["done"],
    "done":         [],
}


# ─── Metrics Collection (DR-13) ──────────────────────────────────────────


@dataclass
class ActionMetrics:
    """Metrics for a single action execution."""
    action: str
    start_time: float
    end_time: float = 0.0
    duration_ms: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0

    def finish(self) -> None:
        """Mark action as finished and compute duration."""
        self.end_time = time.monotonic()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)


@dataclass
class LLMCallMetrics:
    """Metrics for a single LLM call (one ``run_prompt`` invocation).

    Populated by ``run_prompt`` (commit 7 of the prompt-system
    refactor). Each entry corresponds to one logical call to an
    underlying LLM, including any retries — so ``attempt_count``
    can be > 1 when transient failures were retried.

    Fields:
        prompt_name: Registry key, e.g. ``"research_clarify"``.
        llm_role: Which client was used — "default" | "planning"
            | "report".
        attempt_count: Number of underlying ``client.chat`` calls
            actually made (1 = succeeded on first try, 2+ = had
            transient retries that were resolved).
        latency_ms: Wall-clock time spent in run_prompt, including
            retries and framework augmentation. The LLM client's
            own latency is roughly a subset of this.
        chars_in: Approximate input size — sum of ``len(content)``
            for every message sent to the LLM (system + user +
            framework block). Cheap proxy for input tokens.
        chars_out: Approximate output size — ``len(str(result))``
            for the final LLM response (JSON-stringified for JSON
            outputs, raw for markdown). Cheap proxy for output
            tokens.
        fallback_used: True if the LLM call failed after retries
            and the caller invoked ``spec.fallback(**vars)`` (not
            recorded here directly; set by run_prompt when it
            re-raises and the caller catches).
        success: True if the LLM returned a parseable result on
            the final attempt. False if run_prompt re-raised.
        json_parsed: True if the response was parsed as JSON
            (only meaningful for ``expects_json=True`` prompts).
        error: Stringified exception on failure, "" on success.
    """
    prompt_name: str
    llm_role: str
    attempt_count: int = 1
    latency_ms: int = 0
    chars_in: int = 0
    chars_out: int = 0
    fallback_used: bool = False
    success: bool = True
    json_parsed: bool = True
    error: str = ""


@dataclass
class MetricsCollector:
    """Metrics for an entire research session.

    Aggregates per-action metrics and per-LLM-call metrics. Each
    action's metric collection is a ``with`` context manager block
    — no need to remember to call ``_finish_action`` at every
    return point. Each LLM call is recorded by ``run_prompt``
    directly via ``record_llm_call``.

    Back-compat: ``SessionMetrics = MetricsCollector`` (alias at module level).
    """
    session_id: str
    start_time: float = 0.0
    end_time: float = 0.0
    total_duration_ms: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    actions: list[ActionMetrics] = field(default_factory=list)
    llm_calls: list[LLMCallMetrics] = field(default_factory=list)

    def start(self) -> None:
        """Mark session as started."""
        self.start_time = time.monotonic()

    def finish(self) -> None:
        """Mark session as finished and compute totals."""
        self.end_time = time.monotonic()
        self.total_duration_ms = int((self.end_time - self.start_time) * 1000)
        self.total_tokens = sum(a.tokens_used for a in self.actions)
        self.total_cost_usd = sum(a.cost_usd for a in self.actions)

    def add_action(self, action: ActionMetrics) -> None:
        """Back-compat: manually append an action metric."""
        self.actions.append(action)

    def record_llm_call(self, metric: LLMCallMetrics) -> None:
        """Append one LLM call metric.

        Called by ``run_prompt`` (autoresearch.llm_step). Errors
        raised by this method are caught by the caller; metric
        recording is best-effort and never breaks the LLM call path.
        """
        self.llm_calls.append(metric)

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [f"Session {self.session_id} completed in {self.total_duration_ms/1000:.1f}s"]
        for a in self.actions:
            token_str = f"{a.tokens_used:,} tokens" if a.tokens_used > 0 else "0 tokens"
            cost_str = f"${a.cost_usd:.3f}" if a.cost_usd > 0 else "$0.00"
            lines.append(f"├── {a.action}: {a.duration_ms/1000:.1f}s, {token_str}, {cost_str}")
        if self.llm_calls:
            lines.append(f"├── LLM calls: {len(self.llm_calls)} total")
            for c in self.llm_calls:
                status = (
                    "fallback" if c.fallback_used
                    else ("ok" if c.success else f"err: {c.error[:30]}")
                )
                lines.append(
                    f"│   ├── {c.prompt_name} ({c.llm_role}): "
                    f"{c.latency_ms}ms, {c.attempt_count} attempt(s), "
                    f"{c.chars_in}→{c.chars_out} chars, {status}"
                )
            total_llm_ms = sum(c.latency_ms for c in self.llm_calls)
            total_attempts = sum(c.attempt_count for c in self.llm_calls)
            lines.append(
                f"│   └── Total: {total_llm_ms/1000:.1f}s, "
                f"{total_attempts} attempt(s)"
            )
        lines.append(f"└── Total: {self.total_duration_ms/1000:.1f}s, {self.total_tokens:,} tokens, ${self.total_cost_usd:.3f}")
        return "\n".join(lines)

    def record(self, action: str) -> Iterator[ActionMetrics]:
        """Context manager: start/finish tracking for one action.

        Usage::

            with ctx.metrics.record("plan"):
                # ... do work ...
                # ActionMetrics.finish() runs on exit (even on exception)
        """
        return _record_action_impl(self, action)


# Back-compat alias
SessionMetrics = MetricsCollector


# ─── Context manager helper for MetricsCollector.record() ───────────────


@contextmanager
def _record_action_impl(
    collector: MetricsCollector, action: str,
) -> Iterator[ActionMetrics]:
    """Context manager body: start/finish + append action metrics.

    Used by ``MetricsCollector.record()``. The ``with`` block ensures
    the metric is always recorded, even if the action raises.
    """
    m = ActionMetrics(action=action, start_time=time.monotonic())
    try:
        yield m
    finally:
        m.finish()
        collector.actions.append(m)
        logger.debug("Action %s completed in %dms", m.action, m.duration_ms)


# ─── Live research state ──────────────────────────────────────────────────


@dataclass
class ResearchState:
    """Mutable state for the ReAct research loop.

    The engine reads and mutates this object on every loop iteration.
    On resume, ``_load_resume_state`` hydrates it from the DB.

    The ``_engine`` field is a weak back-reference set by the engine
    after construction. It is excluded from ``__repr__`` and not part
    of the value-equality so the dataclass can be safely nested or
    compared without infinite recursion.
    """

    session_id: str = ""
    query: str = ""

    # Round tracking
    round: int = 0
    max_rounds: int = 5
    phase: str = ""  # planning | gathering | analyzing | synthesizing | reporting | reviewing | done

    # Data accumulators
    sub_queries: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    report_md: str | None = None
    review: dict[str, Any] | None = None

    # Quality tracking
    quality_score: int = 0
    knowledge_gaps: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    # Budget
    total_llm_calls: int = 0
    total_sources: int = 0
    total_sub_queries: int = 0
    budget_remaining: float = 1.0

    # Control signals
    cancelled: bool = False
    paused: bool = False

    # Interpreted observations (generated by _observe)
    observations: list[str] = field(default_factory=list)

    # ─── 6-step framework fields ──────────────────────────────────────
    clarification: dict[str, Any] | None = None
    reasoning_check: dict[str, Any] | None = None
    structure_check: dict[str, Any] | None = None
    evidence_scores: dict[str, float] = field(default_factory=dict)
    self_loop_counts: dict[str, int] = field(default_factory=dict)
    self_loop_history: list[dict[str, Any]] = field(default_factory=list)

    # Engine back-reference (set after construction by ResearchEngine).
    # Excluded from repr/eq to avoid circular references.
    _engine: Any = field(default=None, repr=False, compare=False)

    # Reasoner-internal: counts consecutive ``plan`` decisions to break
    # plan→plan self-loops. Reset to 0 on any non-plan action. Excluded
    # from repr/eq because it is observation state, not value state.
    _consecutive_plan: int = field(default=0, repr=False, compare=False)
