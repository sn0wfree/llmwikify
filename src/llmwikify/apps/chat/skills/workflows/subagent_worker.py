"""Subagent worker — the code that actually runs inside the subprocess.

This is invoked by ``subagent_runner._child_main``. It is deliberately
small: load the request, build the message list, drive an LLM call,
return the parsed result.

The ``AgentDriver`` abstraction lets us swap the actual LLM call for
a mock in tests. Production deployments use ``LlmClientDriver`` which
wraps the existing ``llmwikify.foundation.llm.LLMClient``.

Tool loop (v0.41)
-----------------

When the actor declares ``actor_tools`` in YAML, the worker translates
them into OpenAI-format ``tools`` and runs a ReAct loop:

    response → if tool_calls → execute handlers → feed results back
              → re-call LLM → repeat until no tool_calls or MAX_TOOL_ITER

Supported tools:

    WebSearch — public web search (delegates to apps.research.web_search)
    WebFetch  — fetch a URL and extract readable text
    Read      — read a file (limited to the actor's worktree)
    Grep      — ripgrep in worktree
    Glob      — pathlib.rglob in worktree

The ``MockDriver`` is unaware of tools — tests assert on the final
``messages`` list to verify tool-loop behaviour. ``LlmClientDriver``
owns the loop.
"""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import os
import re
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.skills.workflows.subagent_runner import (
    SubagentRequest,
    SubagentResult,
)

logger = logging.getLogger(__name__)


# Maximum ReAct iterations before forcing a final answer.
_MAX_TOOL_ITER = 5

# Cap on file content returned to the LLM by Read.
_READ_MAX_CHARS = 50_000

# Cap on Grep output lines.
_GREP_MAX_LINES = 50

# Cap on Glob result count.
_GLOB_MAX_FILES = 100


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

        actor_tools = tuple(request.actor_tools) if request else ()
        tools_def, handlers = _build_subagent_tools(actor_tools, request)

        if not tools_def:
            # Fast path — no tool loop needed.
            result = client.chat(messages=messages)
            return _normalize_chat_result(result)

        return self._complete_with_tools(client, messages, tools_def, handlers)

    def _complete_with_tools(
        self,
        client: Any,
        messages: list[dict[str, Any]],
        tools_def: list[dict[str, Any]],
        handlers: dict[str, Any],
    ) -> tuple[str, int]:
        """Run a ReAct-style tool loop.

        Each iteration:
          1. Call ``client.chat_with_tools`` with the current messages.
          2. If the response contains ``tool_calls``, execute each one,
             append the assistant message with ``tool_calls`` and one
             ``role=tool`` message per result, then loop.
          3. Otherwise return the assistant ``content`` and accumulated
             token usage.

        Bounded by ``_MAX_TOOL_ITER`` to prevent runaway loops. On
        hitting the cap we log a warning and return whatever content
        the last iteration produced.
        """
        total_tokens = 0
        content = ""
        for _ in range(_MAX_TOOL_ITER):
            try:
                result = client.chat_with_tools(messages, tools=tools_def)
            except Exception as e:
                logger.error("subagent tool loop: chat_with_tools failed: %s", e)
                # Fall back to plain chat to recover.
                result = client.chat(messages=messages)
                content, total_tokens = _normalize_chat_result(result)
                return content, total_tokens

            content, tokens_inc = _extract_content_and_tokens(result)
            total_tokens += tokens_inc
            tool_calls = _extract_tool_calls(result)

            if not tool_calls:
                return content, total_tokens

            # Append the assistant message with tool_calls (OpenAI schema).
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": tc.get("args", ""),
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # Execute each tool and append a tool-role message.
            for tc in tool_calls:
                output = _dispatch_tool_call(tc, handlers)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(output, ensure_ascii=False),
                })

        logger.warning(
            "subagent tool loop hit MAX_TOOL_ITER=%d; returning last content",
            _MAX_TOOL_ITER,
        )
        return content, total_tokens

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
    "_TOOL_SPECS",
    "_TOOL_HANDLERS",
    "_build_subagent_tools",
    "_dispatch_tool_call",
]


# ─── Tool loop support (v0.41) ──────────────────────────────────


# OpenAI-format tool definitions keyed by YAML actor name.
# Each value is the spec passed to ``chat_with_tools(tools=...)``.
_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "WebSearch": {
        "type": "function",
        "function": {
            "name": "WebSearch",
            "description": (
                "Search the public web for the given query. Returns "
                "titles, URLs, and snippets via the configured provider "
                "chain (MiniMax / SearXNG / Tavily / DuckDuckGo)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (required).",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Max results to return (1-20, default 5).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
            },
        },
    },
    "WebFetch": {
        "type": "function",
        "function": {
            "name": "WebFetch",
            "description": (
                "Fetch a single URL via HTTP GET and return its title "
                "plus extracted readable text (HTML stripped, scripts "
                "and styles removed)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "HTTP(S) URL to fetch (required).",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters of text to return (default 2000).",
                        "default": 2000,
                        "minimum": 1,
                        "maximum": 50000,
                    },
                },
                "required": ["url"],
            },
        },
    },
    "Read": {
        "type": "function",
        "function": {
            "name": "Read",
            "description": (
                "Read a file from the worktree. Path is relative to the "
                "worktree root. Content is truncated to 50k characters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to worktree root.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    "Grep": {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": (
                "Search for a regex pattern in files within the worktree "
                "using ripgrep. Returns matching lines with file paths "
                "and line numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern (required).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Search root, relative to worktree (default '.').",
                        "default": ".",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max matching lines to return (default 50).",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    "Glob": {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": (
                "Find files matching a glob pattern within the worktree. "
                "Returns relative paths (capped at 100 files)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g. '**/*.py').",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
}


def _handle_web_search(
    query: str,
    num_results: int = 5,
    *,
    worktree_path: str | None = None,
) -> dict[str, Any]:
    """WebSearch handler — delegates to apps.research.web_search."""
    import asyncio

    try:
        from llmwikify.apps.research.web_search import WebSearch
    except Exception as e:  # noqa: BLE001
        return {"error": f"WebSearch import failed: {e!r}"}

    request = _current_request()
    config = _build_web_search_config(request)
    try:
        searcher = WebSearch(config)
        results = asyncio.run(searcher.search(query, num_results=num_results))
    except Exception as e:  # noqa: BLE001
        logger.warning("web_search tool failed for query=%r: %s", query[:60], e)
        return {"error": f"web_search failed: {e!r}"}

    return {
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ],
        "count": len(results),
    }


def _handle_web_fetch(
    url: str,
    max_chars: int = 2000,
    *,
    worktree_path: str | None = None,
) -> dict[str, Any]:
    """WebFetch handler — calls fetch_url_sync (httpx-based)."""
    try:
        from llmwikify.apps.chat.skills.actions.web_fetch_action import fetch_url_sync
    except Exception as e:  # noqa: BLE001
        return {"error": f"web_fetch import failed: {e!r}"}

    try:
        return fetch_url_sync(url, max_chars=max_chars)
    except Exception as e:  # noqa: BLE001
        return {"error": f"web_fetch failed: {e!r}", "url": url}


def _handle_read(
    path: str,
    *,
    worktree_path: str | None = None,
) -> dict[str, Any]:
    """Read a file from the worktree. Refuses paths outside worktree."""
    if not worktree_path:
        return {"error": "Read: no worktree_path in request"}

    try:
        worktree_root = Path(worktree_path).resolve()
        target = (worktree_root / path).resolve()
        if not str(target).startswith(str(worktree_root) + os.sep) and target != worktree_root:
            return {"error": f"path outside worktree: {path}"}
        if not target.exists():
            return {"error": f"file not found: {path}"}
        if not target.is_file():
            return {"error": f"not a regular file: {path}"}
        content = target.read_text(errors="replace")[:_READ_MAX_CHARS]
        return {
            "content": content,
            "length": min(len(content), _READ_MAX_CHARS),
            "truncated": len(content) >= _READ_MAX_CHARS,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"Read failed: {e!r}"}


def _handle_grep(
    pattern: str,
    path: str = ".",
    max_results: int = 50,
    *,
    worktree_path: str | None = None,
) -> dict[str, Any]:
    """Ripgrep wrapper scoped to the worktree."""
    if not worktree_path:
        return {"error": "Grep: no worktree_path in request"}

    try:
        worktree_root = Path(worktree_path).resolve()
        target = (worktree_root / path).resolve()
        if not str(target).startswith(str(worktree_root) + os.sep) and target != worktree_root:
            return {"error": f"path outside worktree: {path}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"path resolve failed: {e!r}"}

    try:
        out = subprocess.run(
            ["rg", "--no-heading", "-n", "--", pattern, str(target)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return {"error": "ripgrep (rg) not installed"}
    except subprocess.TimeoutExpired:
        return {"error": "Grep timed out after 15s"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Grep failed: {e!r}"}

    all_lines = out.stdout.splitlines()
    truncated = len(all_lines) > max_results
    lines = all_lines[:max_results]
    # Strip worktree_root prefix to keep paths relative.
    rel = [
        line.replace(str(worktree_root) + os.sep, "", 1)
        for line in lines
    ]
    return {
        "matches": "\n".join(rel),
        "match_count": len(rel),
        "truncated": truncated,
    }


def _handle_glob(
    pattern: str,
    *,
    worktree_path: str | None = None,
) -> dict[str, Any]:
    """Glob wrapper scoped to the worktree."""
    if not worktree_path:
        return {"error": "Glob: no worktree_path in request"}

    try:
        worktree_root = Path(worktree_path).resolve()
        # Path traversal guard: refuse patterns that escape the worktree
        # before running the glob (defence in depth).
        if ".." in pattern.split("/"):
            return {"error": f"path outside worktree: {pattern}"}
        candidates = worktree_root.glob(pattern)
        # Filter to paths actually inside the worktree (covers any
        # symlink / absolute path tricks that bypass the simple
        # textual check).
        files = sorted(
            p for p in candidates
            if p.is_file()
            and str(p.resolve()).startswith(str(worktree_root) + os.sep)
        )[:_GLOB_MAX_FILES]
        return {
            "files": [
                str(p.relative_to(worktree_root))
                for p in files
            ],
            "count": len(files),
            "truncated": len(files) >= _GLOB_MAX_FILES,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"Glob failed: {e!r}"}


# Handler dispatch (mirror _TOOL_SPECS keys).
_TOOL_HANDLERS: dict[str, Any] = {
    "WebSearch": _handle_web_search,
    "WebFetch": _handle_web_fetch,
    "Read": _handle_read,
    "Grep": _handle_grep,
    "Glob": _handle_glob,
}


def _build_subagent_tools(
    actor_tools: tuple[str, ...] | list[str],
    request: SubagentRequest | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Translate ``actor_tools`` into ``(tools_def, handlers)``.

    Unknown tools are silently skipped (logged at debug level). The
    handlers are partials with ``worktree_path`` pre-bound from the
    request so each call site doesn't need to thread it through.
    """
    if not actor_tools:
        return [], {}

    worktree_path = getattr(request, "worktree_path", None)
    tools_def: list[dict[str, Any]] = []
    handlers: dict[str, Any] = {}
    for name in actor_tools:
        spec = _TOOL_SPECS.get(name)
        handler = _TOOL_HANDLERS.get(name)
        if not spec:
            logger.debug("actor declared unknown tool %r; skipping", name)
            continue
        tools_def.append(spec)
        if handler is not None:
            handlers[name] = functools.partial(handler, worktree_path=worktree_path)
    return tools_def, handlers


def _dispatch_tool_call(tc: dict[str, Any], handlers: dict[str, Any]) -> dict[str, Any]:
    """Execute a single tool call and return a dict result.

    Args JSON is parsed if it's a string. Errors are caught and
    returned as ``{"error": "..."}`` so the LLM loop continues.
    """
    name = tc.get("name", "")
    raw_args = tc.get("args", {})

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except (TypeError, ValueError) as e:
            return {"error": f"invalid tool args JSON: {e!r}", "raw": raw_args[:200]}
    else:
        args = dict(raw_args or {})

    handler = handlers.get(name)
    if handler is None:
        return {
            "error": f"unknown tool: {name!r}",
            "available": sorted(handlers.keys()),
        }

    try:
        result = handler(**args)
    except TypeError as e:
        # Wrong arg shape from the LLM.
        return {"error": f"tool {name} got bad args: {e!r}"}
    except Exception as e:  # noqa: BLE001
        logger.warning("tool %s raised: %s", name, e)
        return {"error": f"tool {name} raised: {type(e).__name__}: {e}"}

    if not isinstance(result, dict):
        return {"value": result}
    return result


def _build_web_search_config(request: SubagentRequest | None) -> dict[str, Any]:
    """Derive a WebSearch config from the request's LLMSpec.

    Reuses the LLM's API key for MiniMax search (Token Plan serves
    both endpoints on the same key). Other providers are picked up
    from explicit ``web_search.*`` keys if the orchestrator injects
    them via a future config field; for now we only have the LLM
    spec to work with.
    """
    config: dict[str, Any] = {"search_provider": "auto"}
    if request is None or getattr(request, "llm", None) is None:
        return config

    spec = request.llm
    if getattr(spec, "api_key", None):
        config["minimax_api_key"] = spec.api_key
    host = getattr(spec, "base_url", "") or ""
    # Strip /v1 suffix for the search endpoint.
    host = host.rstrip("/").removesuffix("/v1")
    if host:
        config["minimax_api_host"] = host
    return config


def _normalize_chat_result(result: Any) -> tuple[str, int]:
    """Normalize a non-tool chat result to ``(content, tokens)``."""
    if isinstance(result, dict):
        text = result.get("content") or result.get("text") or ""
        usage = result.get("usage") or {}
        tokens = int(usage.get("total_tokens", 0))
        return str(text), tokens
    return str(result), 0


def _extract_content_and_tokens(result: Any) -> tuple[str, int]:
    """Pull content and token usage from a tool-aware chat result."""
    if isinstance(result, dict):
        text = result.get("content") or ""
        usage = result.get("usage") or {}
        tokens = int(usage.get("total_tokens", 0))
        return str(text), tokens
    return str(result), 0


def _extract_tool_calls(result: Any) -> list[dict[str, Any]]:
    """Pull the ``tool_calls`` list from a chat result, or ``[]``."""
    if not isinstance(result, dict):
        return []
    tcs = result.get("tool_calls")
    if not tcs:
        return []
    return list(tcs)
