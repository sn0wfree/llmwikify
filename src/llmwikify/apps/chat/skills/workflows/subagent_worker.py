"""Subagent worker — the code that actually runs inside the subprocess.

This is invoked by ``subagent_runner._child_main``. It is deliberately
small: load the request, build the message list, drive an LLM call,
return the parsed result.

The ``AgentDriver`` abstraction lets us swap the actual LLM call for
a mock in tests. Production deployments use ``LlmClientDriver`` which
wraps the existing ``llmwikify.foundation.llm.LLMClient``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from llmwikify.apps.chat.skills.workflows.subagent_runner import (
    SubagentRequest,
    SubagentResult,
)

logger = logging.getLogger(__name__)


# ─── Public: entry point ────────────────────────────────────────


def run_subagent(request: SubagentRequest) -> SubagentResult:
    """Build messages, drive the LLM, return a structured result.

    Returns a ``SubagentResult`` with ``status='ok'`` and a parsed
    JSON ``output`` when the LLM produces a parseable JSON object.
    Falls back to ``output={'raw_text': ...}`` when the model emits
    prose instead of JSON (the LLM is told JSON-only, but we don't
    trust that contract).
    """
    start = time.monotonic()
    driver = _build_driver(request)
    system_prompt = _build_system_prompt(request)
    user_prompt = _build_user_prompt(request)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        raw_text, tokens = driver.complete(
            messages=messages,
            model=request.actor_model,
        )
    except Exception as e:
        return SubagentResult(
            status="error",
            output={},
            tokens_used=0,
            duration_seconds=time.monotonic() - start,
            error=f"driver.complete failed: {type(e).__name__}: {e}",
        )
    output = _try_parse_json(raw_text)
    return SubagentResult(
        status="ok",
        output=output,
        tokens_used=int(tokens),
        duration_seconds=time.monotonic() - start,
        error=None,
    )


# ─── Prompt construction ───────────────────────────────────────


def _build_system_prompt(request: SubagentRequest) -> str:
    parts: list[str] = [request.actor_prompt_text]
    parts.append("")
    parts.append(
        "You are running as an isolated subagent. Your context is fresh; "
        "you cannot see other subagents' conversations. Return your "
        "findings as a single JSON object (not prose, not markdown) so "
        "the orchestrator can route it to the next phase."
    )
    if request.actor_permission_mode == "acceptEdits":
        parts.append(
            "You have acceptEdits mode: file writes do not need approval."
        )
    if request.worktree_path:
        parts.append(
            f"You are running in an isolated git worktree at "
            f"{request.worktree_path}. Do not touch files outside it."
        )
    if request.budget:
        budget_lines = [f"  - {k}: {v}" for k, v in request.budget.items()]
        parts.append("Budget for this run:")
        parts.extend(budget_lines)
    return "\n".join(parts)


def _build_user_prompt(request: SubagentRequest) -> str:
    parts = ["Inputs:"]
    parts.append(json.dumps(request.inputs, indent=2, ensure_ascii=False))
    parts.append("")
    parts.append(
        "Return ONLY a JSON object. No prose, no markdown fences, "
        "no commentary before or after."
    )
    return "\n".join(parts)


# ─── JSON extraction ────────────────────────────────────────────


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FIRST_OBJECT_RE = re.compile(r"(\{.*\})", re.DOTALL)


def _try_parse_json(text: str) -> dict[str, Any]:
    """Best-effort extract a JSON object from a model response.

    Models occasionally wrap JSON in markdown fences or preface it
    with prose. We try a few shapes in order of strictness.
    """
    candidate = text.strip()
    # 1. Exact parse
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # 2. Fenced ```json {...} ```
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    # 3. First balanced {...}
    m = _FIRST_OBJECT_RE.search(text)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"raw_text": text}


# ─── Driver abstraction ─────────────────────────────────────────


class AgentDriver(ABC):
    """Pluggable backend for the actual LLM call.

    Subclass and override ``complete`` to integrate with a real
    provider. ``MockDriver`` in this module is for tests.
    """

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> tuple[str, int]:
        """Return (response_text, tokens_used)."""


class LlmClientDriver(AgentDriver):
    """Production driver that delegates to ``LLMClient``."""

    def __init__(self) -> None:
        # Lazy import so tests that use MockDriver don't pull in the
        # whole foundation.llm stack.
        from llmwikify.foundation.llm_client import LLMClient

        self._client_factory = LLMClient

    def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> tuple[str, int]:
        # Honor inherit → keep the parent's model
        resolved_model = model if model != "inherit" else None
        client = self._client_factory() if resolved_model is None else self._client_factory(model=resolved_model)
        result = client.chat(messages=messages)
        # ``LLMClient.chat`` returns either a dict with ``content``+``usage``,
        # or a string. Normalize.
        if isinstance(result, dict):
            text = result.get("content") or result.get("text") or ""
            usage = result.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0))
        else:
            text = str(result)
            tokens = 0
        return text, tokens


class MockDriver(AgentDriver):
    """Deterministic driver for tests and CI.

    Looks at the system prompt to decide what to return:

    - if it contains ``"return a plan with phases"``, return a small
      plan dict with 2 phases;
    - if it contains ``"verifier"`` (case-insensitive), return a
      verdict that accepts everything;
    - if it contains ``"synthesizer"``, return a stub final report;
    - otherwise, return a generic echo of the input.

    The mock also records every call into ``self.calls`` so tests
    can assert on the actual prompt shape.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> tuple[str, int]:
        self.calls.append({"model": model, "messages": messages})
        sys_prompt = next(
            (m["content"] for m in messages if m.get("role") == "system"),
            "",
        )
        user_prompt = next(
            (m["content"] for m in messages if m.get("role") == "user"),
            "",
        )
        if "return a plan with phases" in sys_prompt.lower():
            payload = {
                "phases": [
                    {"id": "p1", "title": "Explore the topic",
                     "sub_questions": ["what is X?", "who is affected by X?"],
                     "expected_sources": ["web", "code"],
                     "stop_condition": "two sources found"},
                    {"id": "p2", "title": "Find concrete examples",
                     "sub_questions": ["list 3 examples of X"],
                     "expected_sources": ["web"],
                     "stop_condition": "at least 3 examples"},
                ],
                "synthesis_criteria": [
                    "claim is supported by at least one source",
                    "examples are concrete, not generic",
                ],
            }
        elif "verifier" in sys_prompt.lower():
            payload = {
                "verdicts": [
                    {"claim": "claim A", "verdict": "accept", "reason": "cited",
                     "confidence": 0.9},
                    {"claim": "claim B", "verdict": "downgrade",
                     "reason": "single source", "confidence": 0.5},
                ],
                "summary": {"accepted": 1, "downgraded": 1, "rejected": 0,
                            "overall": "partial"},
            }
        elif "synthesizer" in sys_prompt.lower():
            payload = {
                "page_path": "/tmp/wiki/research/mock-report.md",
                "criteria_met": ["claim is supported by at least one source"],
                "criteria_unmet": ["examples are concrete, not generic"],
                "open_questions": ["need more examples"],
            }
        else:
            payload = {"echo": user_prompt[:200], "model": model}
        # Tokens used is a rough heuristic for tests
        tokens = sum(len(m.get("content", "")) for m in messages) // 4
        return json.dumps(payload), max(tokens, 1)


# ─── Driver selection (env-driven) ─────────────────────────────


def _build_driver(request: SubagentRequest) -> AgentDriver:
    """Pick a driver for this subagent.

    The default is the real ``LlmClientDriver``. Tests set
    ``LLMWIKIFY_SUBAGENT_DRIVER=mock`` (or any name registered in
    ``_DRIVERS``) to substitute.
    """
    choice = os.environ.get("LLMWIKIFY_SUBAGENT_DRIVER", "llm").lower()
    if choice in ("mock", "test"):
        return MockDriver()
    if choice in ("llm", "real", "default"):
        return LlmClientDriver()
    # Unknown → fall back to mock (safer than crashing)
    logger.warning("unknown LLMWIKIFY_SUBAGENT_DRIVER=%r; using MockDriver", choice)
    return MockDriver()


__all__ = [
    "run_subagent",
    "AgentDriver",
    "LlmClientDriver",
    "MockDriver",
    "_try_parse_json",
]
