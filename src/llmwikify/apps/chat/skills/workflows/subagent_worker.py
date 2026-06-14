"""Subagent worker — the code that actually runs inside the subprocess.

This is invoked by ``subagent_runner._child_main``. It is deliberately
small: load the request, build the message list, drive an LLM call,
return the parsed result.

The ``AgentDriver`` abstraction lets us swap the actual LLM call for
a mock in tests. Production deployments use ``LlmClientDriver`` which
wraps the existing ``llmwikify.foundation.llm.LLMClient``.
"""
from __future__ import annotations

import contextvars
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


# Context var so LlmClientDriver (called from within the
# run_subagent request) can access the current request without
# changing the AgentDriver.complete signature.
_request_ctx: contextvars.ContextVar[SubagentRequest | None] = (
    contextvars.ContextVar("subagent_request", default=None)
)


# ─── Public: entry point ────────────────────────────────────────


def run_subagent(request: SubagentRequest) -> SubagentResult:
    """Build messages, drive the LLM, return a structured result.

    Returns a ``SubagentResult`` with ``status='ok'`` and a parsed
    JSON ``output`` when the LLM produces a parseable JSON object.
    Falls back to ``output={'raw_text': ...}`` when the model emits
    prose instead of JSON (the LLM is told JSON-only, but we don't
    trust that contract).

    LAL: sets the ``_request_ctx`` contextvar so
    ``LlmClientDriver.complete`` can access the request (for the
    inherited ``LLMSpec``) without changing the driver interface.
    """
    start = time.monotonic()
    driver = _build_driver(request)
    system_prompt = _build_system_prompt(request)
    user_prompt = _build_user_prompt(request)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    token = _request_ctx.set(request)
    try:
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
    finally:
        _request_ctx.reset(token)
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
    """Production driver that delegates to ``LLMClient``.

    LAL (PR 2): the driver uses the request's ``LLMSpec`` to
    construct the client. It no longer reads env vars or
    config dicts. ``actor.model`` is treated as an optional
    override applied on top of the spec's model, with
    validation against the provider's supported models.

    Gradient switch ``LLM_SUBAGENT_INHERIT``:
      - ``true`` (default after wiring): require ``request.llm``
        to be set; raise if missing.
      - ``false``: fall back to env-based construction
        (``LLMClient.from_config({})``) for back-compat with
        workflows that don't yet inject the spec.
    """

    def __init__(self) -> None:
        # Lazy import so tests that use MockDriver don't pull in the
        # whole foundation.llm stack.
        from llmwikify.foundation.llm.provider_models import get_supported_models
        from llmwikify.foundation.llm.spec import LLMSpec
        from llmwikify.foundation.llm.streamable import StreamableLLMClient
        from llmwikify.foundation.llm_client import LLMClient

        self._client_factory = LLMClient
        self._streamable_factory = StreamableLLMClient
        self._spec_cls = LLMSpec
        self._get_supported_models = get_supported_models

    def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> tuple[str, int]:
        request = _current_request()
        client = self._build_client(request, model)
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

    def _build_client(self, request: SubagentRequest | None, model: str):
        """Build the LLM client honoring LAL contract.

        Resolution order:
          1. If ``request.llm`` is set: build from spec, applying
             ``model`` override (validated against supported models).
          2. Else if ``LLM_SUBAGENT_INHERIT=true``: raise.
          3. Else (gradient switch off): fall back to env-based
             ``LLMClient.from_config({})`` for back-compat.
        """
        from llmwikify.foundation.llm.resolver import resolver_enabled

        inherit_required = resolver_enabled_subagent()

        if request is not None and request.llm is not None:
            return self._build_from_spec(request.llm, model)

        if not inherit_required:
            # Back-compat: use env vars via from_config.
            return self._client_factory.from_config({})

        # LAL mode: must have inherited spec.
        raise RuntimeError(
            "subagent received no LLMSpec from parent and "
            "LLM_SUBAGENT_INHERIT is enabled; inject llm_spec from "
            "the executor/ChatOrchestrator before calling run_subagent"
        )

    def _build_from_spec(self, spec, model: str):
        """Build a client from a spec, applying the model override."""
        # Treat "inherit" as a no-op alias (back-compat for existing
        # YAMLs; PR 3 will reject it). Empty / None also means
        # "use spec.model".
        actor_model = (model or "").strip()
        if actor_model and actor_model != "inherit":
            supported = self._get_supported_models(spec.provider)
            if supported and actor_model not in supported:
                # Validation failure — we DO NOT silently fall back
                # to spec.model. Raise with a clear message.
                raise ValueError(
                    f"actor.model={actor_model!r} is not in the "
                    f"supported models list for provider "
                    f"{spec.provider!r}. Supported: {supported}"
                )
            spec = spec.with_model_override(actor_model)
        # Build client from (possibly overridden) spec.
        return self._streamable_factory.from_spec(spec)


def _current_request() -> SubagentRequest | None:
    """Return the SubagentRequest currently being processed, if any.

    Set by ``run_subagent`` via a contextvar so ``LlmClientDriver``
    can see the request without changing the ``AgentDriver.complete``
    signature. Returns ``None`` outside the subagent context
    (e.g. direct unit tests of the driver).
    """
    return _request_ctx.get()


def resolver_enabled_subagent() -> bool:
    """Return True if subagents must inherit an ``LLMSpec`` from parent.

    Set the env var ``LLM_SUBAGENT_INHERIT=false`` to fall back to
    the env-based ``LLMClient.from_config({})`` path. Default is
    ``true`` (require inherited spec).
    """
    import os
    val = os.environ.get("LLM_SUBAGENT_INHERIT", "true").strip().lower()
    return val not in ("false", "0", "no", "off", "")


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
