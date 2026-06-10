"""Workflow executor — runs a validated WorkflowSpec to completion.

Responsibilities:

  1. Resolve ``$`` references in each phase's ``inputs`` against
     (a) the user-provided ``inputs`` and (b) the outputs of
     previously-completed phases.
  2. Materialize fan-out instances once the upstream phase
     completes (we don't expand the graph at load time).
  3. Schedule ready phases under a concurrency semaphore.
  4. Persist progress to ``~/.llmwikify/workflows/runs/{run_id}.json``
     so a crashed run can be resumed.
  5. Enforce budget / wallclock / per-phase-timeout limits.
  6. Emit progress events (subscribe via ``ProgressListener``).

Design notes
------------

  - The executor is a **single-process async coordinator**. The
    actual LLM work happens in subprocesses spawned by
    ``subagent_runner``. This is the *concurrency boundary* — the
    semaphore limits how many subprocesses run at once.
  - For v1 we use ``concurrent.futures.ThreadPoolExecutor`` to
    schedule subprocess spawns. Each spawned future blocks on its
    child process; the parent thread is free to schedule more
    phases as their dependencies clear.
  - Fan-out: the upstream phase's output is expected to contain a
    list. We look at the fan_out's ``from_ref`` and expand one
    instance per element. Instances share the same actor; their ids
    are ``<id_prefix><index>``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.skills.workflows.dag import (
    Dag,
    PhaseSpec,
    WorkflowSpec,
    build_dag,
)
from llmwikify.apps.chat.skills.workflows.run_store import RunState, RunStore
from llmwikify.apps.chat.skills.workflows.subagent_runner import (
    SubagentResult,
    run_subagent,
)

logger = logging.getLogger(__name__)


# ─── Public types ──────────────────────────────────────────────


@dataclass
class WorkflowInputs:
    """User-provided inputs that satisfy the workflow's ``inputs`` schema."""

    data: Mapping[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass
class WorkflowRunResult:
    """Final result of a workflow run."""

    run_id: str
    status: str                          # "ok" | "partial" | "failed" | "halted"
    outputs: dict[str, Any]              # phase_id → final output
    total_tokens_used: int
    total_agents_spawned: int
    duration_seconds: float
    phase_summaries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "outputs": self.outputs,
            "total_tokens_used": self.total_tokens_used,
            "total_agents_spawned": self.total_agents_spawned,
            "duration_seconds": self.duration_seconds,
            "phase_summaries": self.phase_summaries,
        }


ProgressListener = Callable[["WorkflowProgressEvent"], None]


@dataclass
class WorkflowProgressEvent:
    """Emitted at every interesting state transition."""

    run_id: str
    event: str                            # "phase_started" | "phase_complete" | "phase_failed" | "workflow_complete" | "workflow_halted"
    phase_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ─── $-reference resolution ────────────────────────────────────


_DOLLAR_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")


def resolve_dollar_refs(
    value: Any,
    *,
    inputs: WorkflowInputs,
    outputs: Mapping[str, Any],
    item: Any = None,
) -> Any:
    """Recursively substitute ``$ref`` placeholders in a value tree.

    Supported roots:
      - ``$inputs.X``         → ``inputs.data['X']``
      - ``$phase_id.X.Y``     → ``outputs['phase_id']['X']['Y']``
      - ``$item`` / ``$item.X`` → the current fan-out item
      - ``$env.X``            → ``os.environ['X']``
    """
    import os

    if isinstance(value, str):
        if not value.startswith("$"):
            return value

        def _lookup(path: str) -> Any:
            if path == "item":
                return item
            if path == "env":
                # $env without further path is invalid; only $env.X is
                raise KeyError("$env requires a subkey (e.g. $env.HOME)")
            if path == "inputs":
                raise KeyError("$inputs requires a subkey (e.g. $inputs.X)")
            root, *rest = path.split(".", 1)
            if root == "item":
                cur: Any = item
                for r in rest:
                    if not isinstance(cur, Mapping):
                        raise KeyError(f"$item.{rest[0]!r} not navigable")
                    cur = cur[r]  # type: ignore[index]
                return cur
            if root == "env":
                if not rest:
                    raise KeyError("$env requires a subkey")
                return os.environ[rest[0]]
            if root == "inputs":
                if not rest:
                    raise KeyError("$inputs requires a subkey")
                return inputs.get(rest[0], _MISSING)
            if root in outputs:
                cur = outputs[root]
                for r in rest:
                    if not isinstance(cur, Mapping):
                        raise KeyError(f"$ref path {path!r} not navigable at {r!r}")
                    cur = cur[r]  # type: ignore[index]
                return cur
            # Unknown root: surface the placeholder, do not raise.
            # The executor's _execute_phase will catch the literal
            # ``$nonexistent.thing`` and report a clean error.
            raise _UnresolvableRef(path)

        def _replace(match: re.Match[str]) -> str:
            path = match.group(1)
            try:
                resolved = _lookup(path)
            except (KeyError, _UnresolvableRef):
                # Leave the placeholder; the executor will surface a
                # clearer error if the phase fails.
                return match.group(0)
            return json.dumps(resolved, ensure_ascii=False) if not isinstance(resolved, str) else resolved

        # Special case: entire string is a single $ref → return the value directly
        if value.startswith("$") and _DOLLAR_RE.fullmatch(value):
            path = value[1:]
            try:
                return _lookup(path)
            except (KeyError, _UnresolvableRef):
                return value  # keep the placeholder for the executor to report
        # Otherwise: substitute inside the string and re-parse if it
        # was meant to be JSON. For v1 we keep it simple: substitute
        # and let the LLM interpret any remaining text.
        return _DOLLAR_RE.sub(_replace, value)
    if isinstance(value, Mapping):
        return {k: resolve_dollar_refs(v, inputs=inputs, outputs=outputs, item=item) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_dollar_refs(v, inputs=inputs, outputs=outputs, item=item) for v in value]
    return value


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


class _UnresolvableRef(Exception):
    """Internal signal: a $-reference points to nothing in inputs/outputs/item.

    The resolver catches this and returns the original placeholder
    string so the executor can surface a clean error per phase
    instead of a stack trace.
    """

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


# ─── Executor ──────────────────────────────────────────────────


class WorkflowExecutor:
    """Drives a WorkflowSpec to completion.

    Lifecycle:

        executor = WorkflowExecutor(spec, inputs, base_dir=...)
        result = executor.run()

    Or, to resume a previous run:

        executor = WorkflowExecutor.from_run_id(run_id, base_dir=...)
        result = executor.run()

    Listeners (for UI / logging) can be added with ``add_listener``.
    """

    def __init__(
        self,
        spec: WorkflowSpec,
        inputs: WorkflowInputs,
        base_dir: Path | None,
        *,
        run_id: str | None = None,
        session_id: str = "",
        run_store: RunStore | None = None,
        on_progress: ProgressListener | None = None,
    ) -> None:
        self.spec = spec
        self.dag = build_dag(spec)
        self.inputs = inputs
        self.base_dir = base_dir
        self.run_id = run_id or self._new_run_id()
        self.session_id = session_id
        self.run_store = run_store or RunStore.default()
        self._listeners: list[ProgressListener] = []
        if on_progress is not None:
            self._listeners.append(on_progress)
        # Runtime state
        self._outputs: dict[str, Any] = {}
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._skipped: set[str] = set()
        self._total_tokens = 0
        self._total_agents = 0
        self._started_at = time.monotonic()
        # Plan: phases-by-id is a mutable dict that grows when fan-outs materialize
        self._live_phases: dict[str, PhaseSpec] = dict(self.dag.phases_by_id)
        # Persistent state — load if resuming
        self._restore_state()

    @classmethod
    def from_run_id(
        cls,
        run_id: str,
        base_dir: Path | None,
        *,
        run_store: RunStore | None = None,
        on_progress: ProgressListener | None = None,
    ) -> "WorkflowExecutor":
        store = run_store or RunStore.default()
        state = store.load(run_id)
        if state is None:
            raise FileNotFoundError(f"no run with id {run_id!r}")
        # Re-parse the spec from its source
        if state.source_path is None:
            raise FileNotFoundError(
                f"run {run_id!r} has no source_path; cannot resume"
            )
        from llmwikify.apps.chat.skills.workflows.dag import load_workflow

        spec = load_workflow(Path(state.source_path))
        inputs = WorkflowInputs(data=state.inputs_data)
        return cls(
            spec=spec,
            inputs=inputs,
            base_dir=base_dir,
            run_id=run_id,
            session_id=state.session_id,
            run_store=store,
            on_progress=on_progress,
        )

    # ── listeners ────────────────────────────────────────────

    def add_listener(self, listener: ProgressListener) -> None:
        self._listeners.append(listener)

    def _emit(self, event: str, phase_id: str | None = None, **payload: Any) -> None:
        evt = WorkflowProgressEvent(
            run_id=self.run_id,
            event=event,
            phase_id=phase_id,
            payload=payload,
        )
        for listener in self._listeners:
            try:
                listener(evt)
            except Exception as e:  # pragma: no cover
                logger.warning("progress listener raised: %s", e, exc_info=True)
        # Persist
        self._persist_state()

    # ── run ──────────────────────────────────────────────────

    def run(self) -> WorkflowRunResult:
        """Drive the DAG to completion (or halt)."""
        # Pre-flight: budget check
        if self.spec.budget.max_total_tokens is not None and \
                self._total_tokens > self.spec.budget.max_total_tokens:
            return self._halt("budget_preflight_exceeded")

        # Build the schedule. We iterate until no more ready phases
        # can be dispatched, or we hit a terminal condition.
        max_workers = self.spec.budget.max_concurrent_agents
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="wf") as pool:
            inflight: dict[Future[SubagentResult], str] = {}

            while True:
                self._materialize_fanouts()
                ready = self.dag.ready_phases(self._completed | self._skipped | self._failed)
                # Also include any newly materialized fan-out instances
                # whose templates aren't in completed/skipped/failed.
                for phase_id, phase in self._live_phases.items():
                    if phase_id in (self._completed | self._skipped | self._failed):
                        continue
                    if all(n in (self._completed | self._skipped) for n in phase.needs):
                        if phase not in ready:
                            ready.append(phase)

                # Filter out those already in flight
                inflight_phase_ids = set(inflight.values())
                ready = [p for p in ready if p.id not in inflight_phase_ids]

                # Check skip_if
                ready = [p for p in ready if not self._should_skip(p)]

                # Dispatch
                for phase in ready:
                    fut = pool.submit(self._execute_phase, phase)
                    inflight[fut] = phase.id

                if not inflight:
                    # Nothing in flight and nothing ready → done
                    break

                # Wait for at least one to complete (or fail)
                done, _ = _wait_any(inflight, timeout=1.0)
                for fut in done:
                    phase_id = inflight.pop(fut)
                    try:
                        result = fut.result()
                    except Exception as e:  # pragma: no cover
                        logger.error("phase %s raised: %s", phase_id, e, exc_info=True)
                        self._mark_failed(phase_id, str(e))
                        continue
                    self._record_phase_result(phase_id, result)

                # Budget / wallclock enforcement
                elapsed = time.monotonic() - self._started_at
                if elapsed > self.spec.limits.max_wallclock_seconds:
                    self._persist_state()
                    return self._halt("wallclock_exceeded")
                if (
                    self.spec.budget.max_total_tokens is not None
                    and self._total_tokens > self.spec.budget.max_total_tokens
                ):
                    if self.spec.budget.on_exceed == "halt":
                        self._persist_state()
                        return self._halt("budget_exceeded")

        # Final state classification
        return self._finalize()

    # ── internals ────────────────────────────────────────────

    def _execute_phase(self, phase: PhaseSpec) -> SubagentResult:
        actor = self.spec.actors.get(phase.actor)
        if actor is None:
            # Should have been caught at validation; defensive.
            return SubagentResult(
                status="error",
                output={},
                tokens_used=0,
                duration_seconds=0.0,
                error=f"unknown actor {phase.actor!r}",
            )
        self._emit("phase_started", phase_id=phase.id, actor=phase.actor)
        # Resolve inputs
        try:
            resolved_inputs = resolve_dollar_refs(
                dict(phase.inputs),
                inputs=self.inputs,
                outputs=self._outputs,
            )
        except Exception as e:
            return SubagentResult(
                status="error",
                output={},
                tokens_used=0,
                duration_seconds=0.0,
                error=f"failed to resolve $refs: {e}",
            )
        # Build per-phase budget
        per_phase_budget = {
            "max_phase_timeout_seconds": phase.timeout_seconds
            or self.spec.limits.max_phase_timeout_seconds,
        }
        attempts = max(phase.retry_attempts, 0) + 1
        last_result: SubagentResult | None = None
        for attempt in range(attempts):
            result = run_subagent(
                actor=actor,
                inputs=resolved_inputs,
                budget=per_phase_budget,
                session_id=self.session_id or self.run_id,
                base_dir=self.base_dir,
                worktree_path=None,  # TODO: worktree handling in v1.1
                timeout_seconds=per_phase_budget["max_phase_timeout_seconds"],
            )
            self._total_tokens += result.tokens_used
            self._total_agents += 1
            if result.status == "ok":
                return result
            last_result = result
            if attempt + 1 < attempts:
                time.sleep(phase.retry_backoff_seconds * (2 ** attempt))
        assert last_result is not None
        return last_result

    def _should_skip(self, phase: PhaseSpec) -> bool:
        """Evaluate ``skip_if`` expression. Whitelisted ops only."""
        if not phase.skip_if:
            return False
        expr = phase.skip_if.strip()
        # Only handle ``len($X) <op> N`` for now
        m = re.match(r"len\(\$([\w.]+)\)\s*(<|<=|>|>=|==|!=)\s*(\d+)$", expr)
        if m:
            path, op, n_str = m.group(1), m.group(2), m.group(3)
            n = int(n_str)
            try:
                val = resolve_dollar_refs(
                    f"${path}",
                    inputs=self.inputs,
                    outputs=self._outputs,
                )
            except KeyError:
                val = None
            actual = len(val) if val is not None else 0
            return _eval_int_compare(actual, op, n)
        logger.warning("phase %r: unparseable skip_if=%r; not skipping", phase.id, expr)
        return False

    def _materialize_fanouts(self) -> None:
        """For each fan-out template whose upstream is complete, expand
        instances and add them to ``_live_phases``.

        Also maintains an *aggregate* output keyed by the template's
        phase id, so downstream phases can reference it via
        ``$template_id`` and get a flat list of all instance outputs.
        """
        for phase_id, phase in list(self._live_phases.items()):
            if phase.fan_out is None:
                continue
            if phase_id in (self._completed | self._skipped | self._failed):
                continue
            if not all(n in (self._completed | self._skipped) for n in phase.needs):
                continue
            # Already materialized?
            existing = [
                pid for pid in self._live_phases
                if pid.startswith(phase.fan_out.id_prefix)
                and pid != phase_id
            ]
            if existing:
                continue
            # Resolve the upstream list
            try:
                upstream_value = resolve_dollar_refs(
                    phase.fan_out.from_ref,
                    inputs=self.inputs,
                    outputs=self._outputs,
                )
            except KeyError as e:
                logger.error("fan_out %r: cannot resolve %s: %s",
                             phase_id, phase.fan_out.from_ref, e)
                self._mark_failed(phase_id, f"fan_out upstream ref: {e}")
                continue
            if not isinstance(upstream_value, list):
                self._mark_failed(
                    phase_id,
                    f"fan_out.from={phase.fan_out.from_ref!r} resolved to "
                    f"{type(upstream_value).__name__}, not list",
                )
                continue
            # Materialize N instances
            for index, item in enumerate(upstream_value):
                instance_id = f"{phase.fan_out.id_prefix}{index}"
                instance_inputs = {
                    k: v for k, v in phase.fan_out.per_item_inputs.items()
                }
                # Replace $item with the current item
                instance_inputs = resolve_dollar_refs(
                    instance_inputs,
                    inputs=self.inputs,
                    outputs=self._outputs,
                    item=item,
                )
                instance = PhaseSpec(
                    id=instance_id,
                    actor=phase.fan_out.per_item_actor,
                    needs=phase.needs,
                    inputs=instance_inputs,
                    outputs=None,
                    fan_out=None,
                    count=None,
                    parallel=True,
                    timeout_seconds=phase.timeout_seconds,
                    retry_attempts=phase.retry_attempts,
                    retry_backoff_seconds=phase.retry_backoff_seconds,
                )
                self._live_phases[instance_id] = instance
            # Aggregate key so downstream $template_id.X resolves.
            # The aggregate shape is documented as a flat list of
            # instance outputs:
            #   { "findings": [<flat of all instance.findings>],
            #     "instances": [<raw output of each instance>] }
            # For v1 we only synthesize the well-known keys
            # ("findings", "filtered_findings") so the canned
            # llmwikify-research workflow runs end-to-end.
            self._refresh_fanout_aggregate(phase_id, phase.fan_out.id_prefix)
            self._completed.add(phase_id)
            self._emit("phase_complete", phase_id=phase_id, spawned=len(upstream_value))

    def _refresh_fanout_aggregate(self, template_id: str, id_prefix: str) -> None:
        """Recompute and store the aggregate output for a fan-out template.

        Looks at every phase whose id starts with ``id_prefix`` and
        whose status is complete; flattens known list-typed fields
        into a single output dict keyed by the template id.
        """
        instance_outputs: list[dict[str, Any]] = []
        for pid in sorted(self._live_phases.keys()):
            if not pid.startswith(id_prefix) or pid == template_id:
                continue
            if pid in self._completed and isinstance(self._outputs.get(pid), dict):
                instance_outputs.append(self._outputs[pid])
        findings: list[Any] = []
        filtered: list[Any] = []
        for inst in instance_outputs:
            f = inst.get("findings")
            if isinstance(f, list):
                findings.extend(f)
            ff = inst.get("filtered_findings")
            if isinstance(ff, list):
                filtered.extend(ff)
        self._outputs[template_id] = {
            "findings": findings,
            "filtered_findings": filtered,
            "instances": instance_outputs,
            "instance_count": len(instance_outputs),
        }

    def _record_phase_result(self, phase_id: str, result: SubagentResult) -> None:
        if result.status == "ok":
            self._outputs[phase_id] = result.output
            # If the phase declared an `outputs:` name, mirror the
            # result under that alias too so downstream $-refs work.
            phase = self._live_phases.get(phase_id)
            if phase is not None and phase.outputs is not None:
                self._outputs[phase.outputs] = result.output
            self._completed.add(phase_id)
            self._emit(
                "phase_complete",
                phase_id=phase_id,
                tokens=result.tokens_used,
                duration=result.duration_seconds,
            )
            # If this was a fan-out instance, refresh its template's
            # aggregate so any downstream $template_id.X ref sees
            # the fresh value.
            for template_id, phase in list(self._live_phases.items()):
                if phase.fan_out is None:
                    continue
                if phase_id.startswith(phase.fan_out.id_prefix):
                    self._refresh_fanout_aggregate(template_id, phase.fan_out.id_prefix)
                    break
        else:
            self._mark_failed(phase_id, result.error or "unknown error")

    def _mark_failed(self, phase_id: str, error: str) -> None:
        self._failed.add(phase_id)
        self._outputs[phase_id] = {"_error": error}
        self._emit("phase_failed", phase_id=phase_id, error=error)
        logger.error("phase %s failed: %s", phase_id, error)

    def _halt(self, reason: str) -> WorkflowRunResult:
        self._emit("workflow_halted", reason=reason)
        return WorkflowRunResult(
            run_id=self.run_id,
            status="halted",
            outputs=dict(self._outputs),
            total_tokens_used=self._total_tokens,
            total_agents_spawned=self._total_agents,
            duration_seconds=time.monotonic() - self._started_at,
            phase_summaries=self._phase_summaries(),
        )

    def _finalize(self) -> WorkflowRunResult:
        if not self._failed:
            status = "ok"
        elif self._completed:
            status = "partial"
        else:
            status = "failed"
        result = WorkflowRunResult(
            run_id=self.run_id,
            status=status,
            outputs=dict(self._outputs),
            total_tokens_used=self._total_tokens,
            total_agents_spawned=self._total_agents,
            duration_seconds=time.monotonic() - self._started_at,
            phase_summaries=self._phase_summaries(),
        )
        self._emit("workflow_complete", status=status)
        # Persist final state so the status action sees the right value.
        state = RunState(
            run_id=self.run_id,
            workflow_name=self.spec.name,
            source_path=str(self.spec.source_path) if self.spec.source_path else None,
            started_at=self._started_at,
            status=status,
            inputs_data=dict(self.inputs.data),
            session_id=self.session_id,
            phases={
                pid: {
                    "status": (
                        "complete" if pid in self._completed
                        else "failed" if pid in self._failed
                        else "skipped" if pid in self._skipped
                        else "pending"
                    ),
                    "output": self._outputs.get(pid, {}),
                }
                for pid in self._live_phases
            },
            total_tokens_used=self._total_tokens,
            total_agents_spawned=self._total_agents,
        )
        try:
            self.run_store.save(state)
        except Exception as e:  # pragma: no cover
            logger.warning("failed to persist final run state: %s", e)
        return result

    def _phase_summaries(self) -> list[dict[str, Any]]:
        out = []
        for phase_id in self.dag.topological_order:
            out.append(
                {
                    "phase_id": phase_id,
                    "status": (
                        "complete" if phase_id in self._completed
                        else "failed" if phase_id in self._failed
                        else "skipped" if phase_id in self._skipped
                        else "pending"
                    ),
                }
            )
        # Plus materialized fan-out instances
        for pid in self._live_phases:
            if pid in self.dag.phases_by_id:
                continue
            out.append(
                {
                    "phase_id": pid,
                    "status": (
                        "complete" if pid in self._completed
                        else "failed" if pid in self._failed
                        else "skipped" if pid in self._skipped
                        else "pending"
                    ),
                }
            )
        return out

    # ── persistence ──────────────────────────────────────────

    def _new_run_id(self) -> str:
        ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
        return f"wf_{ts}_{uuid.uuid4().hex[:8]}"

    def _persist_state(self) -> None:
        state = RunState(
            run_id=self.run_id,
            workflow_name=self.spec.name,
            source_path=str(self.spec.source_path) if self.spec.source_path else None,
            started_at=self._started_at,
            status="running",
            inputs_data=dict(self.inputs.data),
            session_id=self.session_id,
            phases={
                pid: {
                    "status": (
                        "complete" if pid in self._completed
                        else "failed" if pid in self._failed
                        else "skipped" if pid in self._skipped
                        else "pending"
                    ),
                    "output": self._outputs.get(pid, {}),
                }
                for pid in self._live_phases
            },
            total_tokens_used=self._total_tokens,
            total_agents_spawned=self._total_agents,
        )
        try:
            self.run_store.save(state)
        except Exception as e:  # pragma: no cover
            logger.warning("failed to persist run state: %s", e)

    def _restore_state(self) -> None:
        state = self.run_store.load(self.run_id)
        if state is None:
            return
        # Restore outputs of completed phases so $-refs can resolve on resume
        for pid, info in state.phases.items():
            if info.get("status") == "complete":
                self._completed.add(pid)
                if "output" in info:
                    self._outputs[pid] = info["output"]
        # Token + agent counters are *resumed* from the persisted
        # state so the final result's totals reflect cumulative
        # work, not just this run's incremental work.
        self._total_tokens = state.total_tokens_used
        self._total_agents = state.total_agents_spawned
        # If a fan-out template was previously marked complete, its
        # instances were already materialized. Reconstruct the
        # ``_live_phases`` entries for them so we don't re-spawn.
        for phase_id, phase in list(self._live_phases.items()):
            if phase.fan_out is None:
                continue
            if phase_id not in self._completed:
                continue
            prefix = phase.fan_out.id_prefix
            # Any instance id we find that begins with the prefix
            # is a previously-materialized instance.
            for pid in state.phases.keys():
                if pid.startswith(prefix) and pid != phase_id:
                    self._live_phases[pid] = PhaseSpec(
                        id=pid,
                        actor=phase.fan_out.per_item_actor,
                        needs=phase.needs,
                        inputs={},  # inputs are not stored; re-resolved at runtime
                        outputs=None,
                        fan_out=None,
                        count=None,
                        parallel=True,
                        timeout_seconds=phase.timeout_seconds,
                        retry_attempts=phase.retry_attempts,
                        retry_backoff_seconds=phase.retry_backoff_seconds,
                    )


# ─── Small helpers ──────────────────────────────────────────────


def _eval_int_compare(actual: int, op: str, expected: int) -> bool:
    if op == "<":
        return actual < expected
    if op == "<=":
        return actual <= expected
    if op == ">":
        return actual > expected
    if op == ">=":
        return actual >= expected
    if op == "==":
        return actual == expected
    if op == "!=":
        return actual != expected
    return False


def _wait_any(
    inflight: dict[Future[Any], str],
    timeout: float,
) -> tuple[set[Future[Any]], set[Future[Any]]]:
    """Wait for at least one future in `inflight` to complete, up to `timeout`."""
    if not inflight:
        return set(), set()
    futures = list(inflight.keys())
    done, not_done = _wait_first(futures, timeout)
    return done, not_done


def _wait_first(
    futures: list[Future[Any]],
    timeout: float,
) -> tuple[set[Future[Any]], set[Future[Any]]]:
    """Cross-version wait for first future to complete."""
    try:
        from concurrent.futures import wait, FIRST_COMPLETED
        done, not_done = wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
        return set(done), set(not_done)
    except ImportError:  # pragma: no cover
        # Python 3.7 fallback (very unlikely on supported versions)
        done: set[Future[Any]] = set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not done:
            for f in futures:
                if f.done():
                    done.add(f)
            if not done:
                time.sleep(0.05)
        not_done = set(futures) - done
        return done, not_done


__all__ = [
    "WorkflowExecutor",
    "WorkflowInputs",
    "WorkflowRunResult",
    "WorkflowProgressEvent",
    "ProgressListener",
    "resolve_dollar_refs",
]
