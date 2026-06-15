"""``dynamic_workflow`` skill — the LLM-facing entry point for running
multi-agent workflows.

This is a normal v0.32 Skill with 4 actions:

  - ``list``    — show all built-in workflows
  - ``run``     — start a workflow by name
  - ``status``  — query a run's state
  - ``resume``  — resume a halted run

The LLM never has to know the YAML DSL or the executor's internals.
It just calls ``dynamic_workflow.run`` with ``{name, inputs}`` and
gets back a ``run_id``. It can then ``status`` to poll, or
``resume`` if a run was interrupted.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)
from llmwikify.apps.chat.skills.workflows.builtins import (
    get_builtin,
    iter_builtins,
    list_builtin_names,
)
from llmwikify.apps.chat.skills.workflows.executor import (
    WorkflowExecutor,
    WorkflowInputs,
)
from llmwikify.apps.chat.skills.workflows.run_store import RunStore

logger = logging.getLogger(__name__)


# ─── handlers (defined before the class so the class body can reference them) ──


def _handle_list(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    items = [
        {
            "name": w.name,
            "description": w.description,
            "actor_names": list(w.actor_names),
            "phase_count": w.phase_count,
        }
        for w in iter_builtins()
    ]
    return SkillResult.ok({"workflows": items})


def _handle_run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    name = args.get("name")
    if not name:
        return SkillResult.fail("missing required arg: name")
    builtin = get_builtin(name)
    if builtin is None:
        return SkillResult.fail(
            f"unknown workflow {name!r}; available: {list_builtin_names()}"
        )
    user_inputs = args.get("inputs", {}) or {}
    declared = builtin.spec.inputs
    missing = [r for r in declared.required if r not in user_inputs]
    if missing:
        return SkillResult.fail(
            f"workflow {name!r}: missing required inputs {missing!r}; "
            f"declared properties: {list(declared.properties.keys())}"
        )
    base_dir = builtin.path.parent
    executor = WorkflowExecutor(
        spec=builtin.spec,
        inputs=WorkflowInputs(data=user_inputs),
        base_dir=base_dir,
        session_id=getattr(ctx, "session_id", "") or "",
        on_progress=_progress_logger,
        llm_spec=getattr(ctx, "llm_spec", None),
    )
    logger.info("starting workflow run_id=%s name=%s", executor.run_id, name)
    result = executor.run()
    return SkillResult.ok(result.to_dict())


def _handle_status(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    """Compact status check. Returns per-phase statuses only.

    Set ``include_details=true`` to also get the full per-phase
    outputs (used by tests / debugging; the LLM almost never
    needs this — use the autoresearch status tool for that).
    """
    run_id = args.get("run_id")
    if not run_id:
        return SkillResult.fail("missing required arg: run_id")
    include_details = bool(args.get("include_details", False))
    state = RunStore.default().load(run_id)
    if state is None:
        return SkillResult.fail(f"no run with id {run_id!r}")

    phases_summary: dict[str, dict[str, Any]] = {}
    for pid, info in (state.phases or {}).items():
        if not isinstance(info, dict):
            phases_summary[pid] = {"status": "unknown"}
            continue
        entry: dict[str, Any] = {"status": info.get("status", "pending")}
        if info.get("status") == "failed":
            output = info.get("output", {})
            if isinstance(output, dict) and "_error" in output:
                entry["error"] = str(output["_error"])[:300]
        phases_summary[pid] = entry

    response: dict[str, Any] = {
        "run_id": state.run_id,
        "workflow_name": state.workflow_name,
        "status": state.status,
        "total_tokens_used": state.total_tokens_used,
        "total_agents_spawned": state.total_agents_spawned,
        "phases_summary": phases_summary,
        "started_at": state.started_at,
        "last_updated": state.last_updated,
    }
    if include_details:
        response["phases"] = state.phases
    return SkillResult.ok(response)


def _handle_resume(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    run_id = args.get("run_id")
    if not run_id:
        return SkillResult.fail("missing required arg: run_id")
    store = RunStore.default()
    state = store.load(run_id)
    if state is None:
        return SkillResult.fail(f"no run with id {run_id!r}")
    if state.source_path is None:
        return SkillResult.fail(
            f"run {run_id!r} has no source_path; cannot resume"
        )
    try:
        executor = WorkflowExecutor.from_run_id(
            run_id=run_id,
            base_dir=Path(state.source_path).parent,
            run_store=store,
            on_progress=_progress_logger,
        )
    except Exception as e:
        return SkillResult.fail(f"failed to load run for resume: {e}")
    result = executor.run()
    return SkillResult.ok(result.to_dict())


def _progress_logger(evt: Any) -> None:
    """Default progress listener: log structured events."""
    fields = {
        "event": evt.event,
        "phase_id": evt.phase_id,
        **dict(evt.payload),
    }
    line = f"workflow.progress: {fields}"
    if evt.event in ("phase_failed", "workflow_halted"):
        logger.warning(line)
    else:
        logger.info(line)


# ─── Skill declaration ────────────────────────────────────────


class DynamicWorkflowSkill(Skill):
    """Skill that lets the LLM run multi-agent workflows."""

    name = "dynamic_workflow"
    description = (
        "Run a multi-agent dynamic workflow. Built-in workflows include "
        "llmwikify-research (4-phase research with adversarial "
        "verification) and others. Use when the task is broad, "
        "needs cross-checked sources, or benefits from parallel "
        "investigators. Prefer simpler skills (wiki_query, "
        "research_skill) for single-fact or short tasks."
    )

    actions: dict[str, SkillAction] = {
        "list": SkillAction(
            name="list",
            description=(
                "List all available built-in workflows. Returns an array "
                "of {name, description, actor_names, phase_count}."
            ),
            handler=_handle_list,
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={
                "type": "object",
                "properties": {
                    "workflows": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
            },
            action_type="read",
            tags=["workflow", "discovery"],
        ),
        "run": SkillAction(
            name="run",
            description=(
                "Start a workflow by name. Returns {run_id, status} "
                "synchronously. To check progress, call status with the "
                "run_id. Workflows can take seconds to minutes."
            ),
            handler=_handle_run,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Workflow name (e.g. 'llmwikify-research').",
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Inputs to pass to the workflow.",
                    },
                },
                "required": ["name"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            action_type="write",
            requires_confirmation=True,
            tags=["workflow", "execution"],
        ),
        "status": SkillAction(
            name="status",
            description=(
                "Query the status of a workflow run. Returns "
                "{run_id, status, total_tokens_used, "
                "total_agents_spawned, phases_summary}. "
                "Pass include_details=true to also get the full "
                "per-phase outputs (used by tests / debugging)."
            ),
            handler=_handle_status,
            input_schema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "include_details": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, also include the full per-phase "
                            "outputs. Default is false (compact summary only)."
                        ),
                    },
                },
                "required": ["run_id"],
            },
            action_type="read",
            tags=["workflow", "query"],
        ),
        "resume": SkillAction(
            name="resume",
            description=(
                "Resume a previously halted or interrupted workflow "
                "run. Completed phases are skipped; remaining phases "
                "are re-run."
            ),
            handler=_handle_resume,
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
            action_type="write",
            requires_confirmation=True,
            tags=["workflow", "execution"],
        ),
    }


__all__ = ["DynamicWorkflowSkill"]
