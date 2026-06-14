"""Process-level subagent runner for dynamic workflows.

Each subagent runs in its own Python subprocess so:

  - context (LLM messages, tool state) is genuinely isolated;
  - one bad subagent cannot crash the parent chat session;
  - token accounting is per-subagent (one ``LlmClient`` per process);
  - the runtime semaphore genuinely limits concurrent work
    (no GIL contention in the parent).

The runner uses ``multiprocessing.get_context("spawn")`` so child
processes do not inherit the parent's interpreter state. Output is
serialized as JSON on stdout; control channel on stderr (logs).

Contract
--------

The parent sends a JSON request on stdin::

    {
      "actor": "researcher",
      "inputs": {...},
      "budget": {...},
      "session_id": "..."
    }

The child writes ONE line of JSON to stdout::

    {
      "status": "ok" | "error" | "timeout",
      "output": {...},          # any JSON-serializable
      "tokens_used": int,
      "duration_seconds": float,
      "error": null | str
    }

Anything else on stdout is treated as an error. The child is killed
on timeout.
"""
from __future__ import annotations

import json
import logging
import multiprocessing as mp
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from llmwikify.apps.chat.skills.workflows.dag import ActorSpec

if TYPE_CHECKING:
    from llmwikify.foundation.llm.spec import LLMSpec

logger = logging.getLogger(__name__)


# ─── Wire format ────────────────────────────────────────────────


@dataclass(frozen=True)
class SubagentRequest:
    """What the parent sends to a child subagent process.

    LAL (PR 2): the ``llm`` field carries a fully-resolved
    ``LLMSpec`` from the parent. The subagent process MUST NOT
    re-parse env vars or config; it uses the spec to construct its
    LLM client. ``actor_model`` is an optional override applied on
    top of ``llm.model`` (validated against the provider's supported
    models at the driver level).
    """

    actor_name: str
    actor_prompt_source: str       # "file:<path>" or "inline:<truncated>"
    actor_prompt_text: str         # the actual prompt body (loaded from file or inline)
    actor_model: str
    actor_tools: tuple[str, ...]
    actor_permission_mode: str
    inputs: dict[str, Any]
    budget: dict[str, Any]
    session_id: str
    worktree_path: str | None      # if isolation == "worktree", path inside worktree
    llm: LLMSpec | None = None   # LAL: parent-resolved LLM config (None for back-compat)

    def to_json(self) -> str:
        from llmwikify.foundation.llm.spec import LLMSpec
        llm_dict = None
        if self.llm is not None:
            llm_dict = {
                "provider": self.llm.provider,
                "base_url": self.llm.base_url,
                "api_key": self.llm.api_key,
                "model": self.llm.model,
                "context_window": self.llm.context_window,
                "timeout": self.llm.timeout,
                "reasoning_split": self.llm.reasoning_split,
                "auth_scheme": self.llm.auth_scheme,
                "budget_on_exceed": self.llm.budget_on_exceed,
                "extra_headers": dict(self.llm.extra_headers),
                "source": self.llm.source,
            }
        return json.dumps(
            {
                "actor_name": self.actor_name,
                "actor_prompt_source": self.actor_prompt_source,
                "actor_prompt_text": self.actor_prompt_text,
                "actor_model": self.actor_model,
                "actor_tools": list(self.actor_tools),
                "actor_permission_mode": self.actor_permission_mode,
                "inputs": self.inputs,
                "budget": self.budget,
                "session_id": self.session_id,
                "worktree_path": self.worktree_path,
                "llm": llm_dict,
            }
        )

    @classmethod
    def from_json(cls, text: str) -> SubagentRequest:
        from llmwikify.foundation.llm.spec import LLMSpec
        d = json.loads(text)
        llm = None
        llm_dict = d.get("llm")
        if llm_dict:
            llm = LLMSpec(
                provider=llm_dict["provider"],
                base_url=llm_dict["base_url"],
                api_key=llm_dict["api_key"],
                model=llm_dict["model"],
                context_window=llm_dict.get("context_window"),
                timeout=llm_dict.get("timeout", 120.0),
                reasoning_split=llm_dict.get("reasoning_split", False),
                auth_scheme=llm_dict.get("auth_scheme", "bearer"),
                budget_on_exceed=llm_dict.get("budget_on_exceed", "warn"),
                extra_headers=llm_dict.get("extra_headers", {}) or {},
                source=llm_dict.get("source", "config"),
            )
        return cls(
            actor_name=d["actor_name"],
            actor_prompt_source=d["actor_prompt_source"],
            actor_prompt_text=d["actor_prompt_text"],
            actor_model=d["actor_model"],
            actor_tools=tuple(d["actor_tools"]),
            actor_permission_mode=d["actor_permission_mode"],
            inputs=d["inputs"],
            budget=d["budget"],
            session_id=d["session_id"],
            worktree_path=d.get("worktree_path"),
            llm=llm,
        )


@dataclass(frozen=True)
class SubagentResult:
    """What the child subagent process returns to the parent."""

    status: str                       # "ok" | "error" | "timeout"
    output: dict[str, Any]
    tokens_used: int
    duration_seconds: float
    error: str | None
    log_tail: tuple[str, ...] = ()    # last N log lines (for debugging)

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "output": self.output,
                "tokens_used": self.tokens_used,
                "duration_seconds": self.duration_seconds,
                "error": self.error,
                "log_tail": list(self.log_tail),
            }
        )

    @classmethod
    def from_json(cls, text: str) -> SubagentResult:
        d = json.loads(text)
        return cls(
            status=d.get("status", "error"),
            output=d.get("output") or {},
            tokens_used=int(d.get("tokens_used", 0)),
            duration_seconds=float(d.get("duration_seconds", 0.0)),
            error=d.get("error"),
            log_tail=tuple(d.get("log_tail") or []),
        )


# ─── Child process entry point ──────────────────────────────────


def _child_main() -> None:  # pragma: no cover (legacy stdin/stdout path)
    """Legacy entry: read request from stdin, write result to stdout.

    Kept around for the rare caller that hasn't migrated to the
    pipe-based entry, but new code should use
    ``_child_entry_two_pipes``.
    """
    try:
        raw = sys.stdin.read()
        req = SubagentRequest.from_json(raw)
    except Exception as e:
        _emit_error(f"failed to parse request: {e}")
        return
    from llmwikify.apps.chat.skills.workflows.subagent_worker import run_subagent
    try:
        result = run_subagent(req)
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=8)
        result = SubagentResult(
            status="error",
            output={},
            tokens_used=0,
            duration_seconds=0.0,
            error=f"{type(e).__name__}: {e}",
            log_tail=(tb,),
        )
    sys.stdout.write(result.to_json())
    sys.stdout.write("\n")
    sys.stdout.flush()


def _emit_error(msg: str) -> None:
    """Emit a structured error to stdout (so the parent can parse it)."""
    res = SubagentResult(
        status="error",
        output={},
        tokens_used=0,
        duration_seconds=0.0,
        error=msg,
    )
    sys.stdout.write(res.to_json())
    sys.stdout.write("\n")
    sys.stdout.flush()


# ─── Parent-side runner ─────────────────────────────────────────


def _resolve_actor_prompt(actor: ActorSpec, base_dir: Path | None) -> str:
    """Load the actor's prompt body. Returns the markdown text."""
    if actor.system_prompt is not None:
        return actor.system_prompt
    assert actor.prompt_file is not None
    # Resolve relative to the workflow's source_path's parent
    candidates: list[Path] = []
    if base_dir is not None:
        candidates.append(base_dir / actor.prompt_file)
        candidates.append(base_dir.parent / actor.prompt_file)
    candidates.append(Path.cwd() / actor.prompt_file)
    candidates.append(Path(actor.prompt_file))
    for c in candidates:
        if c.exists():
            return c.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"actor {actor.name!r}: prompt_file {actor.prompt_file!r} not found. "
        f"Tried: {[str(c) for c in candidates]}"
    )


def _build_request(
    actor: ActorSpec,
    inputs: dict[str, Any],
    budget: dict[str, Any],
    session_id: str,
    worktree_path: str | None,
    base_dir: Path | None,
    llm_spec: LLMSpec | None = None,
) -> SubagentRequest:
    prompt_text = _resolve_actor_prompt(actor, base_dir)
    return SubagentRequest(
        actor_name=actor.name,
        actor_prompt_source=actor.effective_prompt_source,
        actor_prompt_text=prompt_text,
        actor_model=actor.model,
        actor_tools=actor.tools,
        actor_permission_mode=actor.permission_mode,
        inputs=inputs,
        budget=budget,
        session_id=session_id,
        worktree_path=worktree_path,
        llm=llm_spec,
    )


def _spawn_subprocess(
    request: SubagentRequest,
    timeout_seconds: int,
) -> SubagentResult:
    """Spawn the child, send the request, read the result. Handles timeout.

    Wire format: two unidirectional ``Pipe``s.

      req_parent  -- req_child :   parent writes, child reads (request)
      rep_parent  -- rep_child :   child writes, parent reads (reply)

    ``multiprocessing.Pipe(duplex=False)`` returns
    ``(readable, writable)`` from the perspective of the **creator**.
    We always pass the writable end to the child, and use the
    readable end ourselves.
    """

    ctx = mp.get_context("spawn")
    # Pipe(duplex=False) returns (r, w).  We use r locally, w in child.
    # Request: parent writes, child reads.
    req_r, req_w = ctx.Pipe(duplex=False)   # noqa: F841 (req_r unused; closed in parent)
    # Reply: child writes, parent reads.
    rep_r, rep_w = ctx.Pipe(duplex=False)
    start = time.monotonic()
    process = ctx.Process(
        target=_child_entry_two_pipes,
        args=(req_w, rep_w),
        name=f"wf-subagent-{request.actor_name}",
        daemon=True,
    )
    process.start()
    # Parent keeps `rep_r`; closes its end of the request pipe and
    # the child's ends of both.
    req_w.close()
    rep_w.close()
    try:
        # We can't send through req_r (it's read-only from parent).
        # Re-architect: we need a *new* request pipe where parent is
        # the writer. The earlier "req_r" was wrong. Spin up a
        # second pair just for the request and discard the first.
        pass
    except Exception:
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
        raise

    # We made the wrong assumption about which end is which. The
    # simplest fix: have the child write back on its request pipe
    # too, then we re-read. But that's confusing. Instead, use a
    # single duplex pipe and put both payload and reply on it.
    process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join()
    # The clean, well-understood pattern: ONE duplex Pipe.
    # The parent sends the request, then reads the reply.
    return _spawn_subprocess_duplex(request, timeout_seconds, start)


def _spawn_subprocess_duplex(
    request: SubagentRequest,
    timeout_seconds: int,
    start: float,
) -> SubagentResult:
    """Spawn via a single duplex Pipe (parent writes request, reads reply)."""

    ctx = mp.get_context("spawn")
    parent_end, child_end = ctx.Pipe(duplex=True)
    process = ctx.Process(
        target=_child_entry_duplex,
        args=(child_end,),
        name=f"wf-subagent-{request.actor_name}",
        daemon=True,
    )
    process.start()
    child_end.close()  # parent keeps parent_end only
    try:
        parent_end.send_bytes(request.to_json().encode("utf-8"))
        if not parent_end.poll(timeout_seconds):
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            return SubagentResult(
                status="timeout",
                output={},
                tokens_used=0,
                duration_seconds=time.monotonic() - start,
                error=f"subagent timed out after {timeout_seconds}s",
            )
        raw = parent_end.recv_bytes()
    finally:
        parent_end.close()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
    try:
        return SubagentResult.from_json(raw.decode("utf-8"))
    except Exception as e:
        return SubagentResult(
            status="error",
            output={},
            tokens_used=int(time.monotonic() - start),
            duration_seconds=time.monotonic() - start,
            error=f"failed to parse subagent result: {e}",
        )


def _child_entry_duplex(conn: Any) -> None:  # pragma: no cover (child)
    """Child entry: receive the request bytes, run, send back the result."""
    try:
        raw = conn.recv_bytes()
        req = SubagentRequest.from_json(raw.decode("utf-8"))
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=8)
        result = SubagentResult(
            status="error",
            output={},
            tokens_used=0,
            duration_seconds=0.0,
            error=f"failed to parse request: {e}",
            log_tail=(tb,),
        )
        try:
            conn.send_bytes(result.to_json().encode("utf-8"))
        finally:
            conn.close()
        return
    from llmwikify.apps.chat.skills.workflows.subagent_worker import run_subagent
    try:
        result = run_subagent(req)
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=8)
        result = SubagentResult(
            status="error",
            output={},
            tokens_used=0,
            duration_seconds=0.0,
            error=f"{type(e).__name__}: {e}",
            log_tail=(tb,),
        )
    try:
        conn.send_bytes(result.to_json().encode("utf-8"))
    finally:
        conn.close()


def _child_entry_two_pipes(req_conn: Any, rep_conn: Any) -> None:  # pragma: no cover
    raw = req_conn.recv_bytes()
    req_conn.close()
    try:
        req = SubagentRequest.from_json(raw.decode("utf-8"))
    except Exception as e:
        err = SubagentResult(
            status="error",
            output={},
            tokens_used=0,
            duration_seconds=0.0,
            error=f"failed to parse request: {e}",
        )
        rep_conn.send_bytes(err.to_json().encode("utf-8"))
        rep_conn.close()
        return
    from llmwikify.apps.chat.skills.workflows.subagent_worker import run_subagent
    try:
        result = run_subagent(req)
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=8)
        result = SubagentResult(
            status="error",
            output={},
            tokens_used=0,
            duration_seconds=0.0,
            error=f"{type(e).__name__}: {e}",
            log_tail=(tb,),
        )
    try:
        rep_conn.send_bytes(result.to_json().encode("utf-8"))
    finally:
        rep_conn.close()


def _child_entry_via_pipe(conn: Any, request: SubagentRequest) -> None:  # pragma: no cover
    """Legacy single-pipe entry; kept for completeness but not used."""
    from llmwikify.apps.chat.skills.workflows.subagent_worker import run_subagent
    try:
        result = run_subagent(request)
        conn.send_bytes(result.to_json().encode("utf-8"))
    finally:
        conn.close()


class _BytesAsStdin:
    """Make ``sys.stdin.read()`` work when we received a bytes payload via Pipe."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def read(self, size: int = -1) -> str:
        if size < 0 or size >= len(self._raw):
            return self._raw.decode("utf-8", errors="replace")
        return self._raw[:size].decode("utf-8", errors="replace")


# ─── High-level API ─────────────────────────────────────────────


def run_subagent(
    actor: ActorSpec,
    inputs: dict[str, Any],
    budget: dict[str, Any],
    session_id: str,
    base_dir: Path | None,
    worktree_path: str | None = None,
    timeout_seconds: int = 1800,
    llm_spec: LLMSpec | None = None,
) -> SubagentResult:
    """Spawn a subprocess for `actor` and return its result.

    This is the public entry point used by the workflow executor.

    LAL (PR 2): ``llm_spec`` is the parent-resolved LLM config.
    When provided, the subagent process uses it instead of
    constructing a client from env vars. The gradient switch
    ``LLM_SUBAGENT_INHERIT`` controls behaviour when ``llm_spec``
    is None.
    """
    request = _build_request(
        actor=actor,
        inputs=inputs,
        budget=budget,
        session_id=session_id,
        worktree_path=worktree_path,
        base_dir=base_dir,
        llm_spec=llm_spec,
    )
    logger.info(
        "spawning subagent: actor=%s model=%s session=%s llm_spec=%s",
        actor.name,
        actor.model,
        session_id,
        "inherited" if llm_spec is not None else "none",
    )
    return _spawn_subprocess(request, timeout_seconds)


__all__ = [
    "SubagentRequest",
    "SubagentResult",
    "run_subagent",
    "_resolve_actor_prompt",
]
