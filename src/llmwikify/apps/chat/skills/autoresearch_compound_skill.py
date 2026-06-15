"""autoresearch_compound skill — Skill-first AutoResearch workflow facade."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)
from llmwikify.apps.chat.skills.workflows.builtins import get_builtin
from llmwikify.apps.chat.skills.workflows.executor import (
    WorkflowExecutor,
    WorkflowInputs,
)
from llmwikify.apps.chat.skills.workflows.run_store import RunState, RunStore

logger = logging.getLogger(__name__)

WORKFLOW_NAME = "autoresearch-compound"

PHASE_LABELS = {
    "clarify": "Clarify",
    "plan": "Plan",
    "gather_evidence": "Evidence",
    "extract_findings": "Findings",
    "propose_wiki_updates": "Wiki Proposals",
    "synthesize": "Synthesize",
}


def _timeline_from_state(state: Any) -> list[dict[str, Any]]:
    if state is None:
        return []
    timeline = []
    for phase_id, info in state.phases.items():
        timeline.append(
            {
                "phase_id": phase_id,
                "label": PHASE_LABELS.get(phase_id, phase_id),
                "status": info.get("status", "pending"),
            }
        )
    return timeline


def _artifact_counts_from_outputs(outputs: dict[str, Any]) -> dict[str, int]:
    final_report = outputs.get("final_report", {}) if isinstance(outputs, dict) else {}
    if not isinstance(final_report, dict):
        final_report = {}
    return {
        "evidence_items": len(final_report.get("evidence_items", []) or []),
        "findings": len(final_report.get("findings", []) or []),
        "wiki_update_proposals": len(final_report.get("wiki_update_proposals", []) or []),
        "graph_relations": len(final_report.get("graph_relations", []) or []),
        "research_memory_candidates": len(
            (final_report.get("research_memory", {}) or {}).get("reusable_facts", [])
            if isinstance(final_report.get("research_memory", {}), dict)
            else []
        ),
    }


def _handle_run(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    question = args.get("question") or args.get("topic")
    if not question:
        return SkillResult.fail("missing required arg: question")
    builtin = get_builtin(WORKFLOW_NAME)
    if builtin is None:
        return SkillResult.fail(f"workflow {WORKFLOW_NAME!r} is not available")
    inputs = {
        "question": question,
        "topic": args.get("topic", ""),
        "scope": args.get("scope", ""),
    }
    executor = WorkflowExecutor(
        spec=builtin.spec,
        inputs=WorkflowInputs(data=inputs),
        base_dir=builtin.path.parent,
        session_id=getattr(ctx, "session_id", "") or "",
        on_progress=_progress_logger,
        llm_spec=getattr(ctx, "llm_spec", None),
    )
    executor._persist_state()
    logger.info("starting autoresearch_compound run_id=%s", executor.run_id)

    def _run_background() -> None:
        try:
            executor.run()
        except Exception as e:
            logger.exception("autoresearch_compound background run failed: %s", e)
            store = RunStore.default()
            state = store.load(executor.run_id)
            if state is None:
                state = RunState(
                    run_id=executor.run_id,
                    workflow_name=WORKFLOW_NAME,
                    source_path=str(builtin.path),
                    started_at=time.time(),
                    status="failed",
                    inputs_data=inputs,
                    session_id=getattr(ctx, "session_id", "") or "",
                )
            state.status = "failed"
            state.phases.setdefault("_error", {})["output"] = {
                "error": f"{type(e).__name__}: {e}"
            }
            store.save(state)

    thread = threading.Thread(
        target=_run_background,
        name=f"autoresearch-{executor.run_id}",
        daemon=True,
    )
    thread.start()
    return SkillResult.ok(
        {
            "run_id": executor.run_id,
            "workflow_name": WORKFLOW_NAME,
            "status": "running",
            "proposal_only": True,
            "writes_wiki": False,
            "requires_human_approval_to_write_wiki": True,
            "timeline": _timeline_from_state(RunStore.default().load(executor.run_id)),
        }
    )


def _handle_status(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    """Compact status check. Full outputs are opt-in via include_details.

    Default response: ~700 bytes (~175 tokens). Includes per-phase
    status summaries and artifact counts so the LLM can decide
    whether the run is done and whether to fetch the full report.

    Set ``include_details=true`` to also get the synthesize phase's
    final report (markdown + answer + evidence + findings + proposals).
    The full per-phase outputs are NEVER returned here — fetch them
    via the workflow run store directly if needed.
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

    synthesize = (state.phases or {}).get("synthesize", {}) if state.phases else {}
    final_report = synthesize.get("output") if isinstance(synthesize, dict) else None

    response: dict[str, Any] = {
        "run_id": state.run_id,
        "workflow_name": state.workflow_name,
        "status": state.status,
        "total_tokens_used": state.total_tokens_used,
        "total_agents_spawned": state.total_agents_spawned,
        "phases_summary": phases_summary,
        "started_at": state.started_at,
        "last_updated": state.last_updated,
        "timeline": _timeline_from_state(state),
        "artifact_counts": _artifact_counts_from_outputs(
            {"final_report": final_report} if final_report else {}
        ),
        "proposal_only": True,
        "writes_wiki": False,
        "requires_human_approval_to_write_wiki": True,
    }
    if include_details and final_report is not None:
        response["final_report"] = final_report
    return SkillResult.ok(response)


def _progress_logger(evt: Any) -> None:
    fields = {
        "event": evt.event,
        "phase_id": evt.phase_id,
        **dict(evt.payload),
    }
    line = f"autoresearch_compound.progress: {fields}"
    if evt.event in ("phase_failed", "workflow_halted"):
        logger.warning(line)
    else:
        logger.info(line)


class AutoResearchCompoundSkill(Skill):
    name = "autoresearch_compound"
    description = (
        "Run Skill-first AutoResearch as a compounding wiki workflow. "
        "It researches a question and returns evidence items, findings, "
        "wiki update proposals, graph relations, research memory, and a "
        "final report draft. It does not write wiki pages; apply proposals "
        "only after human approval."
    )

    actions: dict[str, SkillAction] = {
        "run": SkillAction(
            name="run",
            description=(
                "Run AutoResearch Compound for a question. Returns a proposal "
                "bundle with evidence, findings, wiki update proposals, graph "
                "relations, memory candidates, and a final report draft. Does "
                "not write wiki pages."
            ),
            handler=_handle_run,
            input_schema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The research question to investigate.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Optional stable topic slug or title.",
                    },
                    "scope": {
                        "type": "string",
                        "description": "Optional constraints, audience, depth, or source boundaries.",
                    },
                },
                "required": ["question"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "status": {"type": "string"},
                    "timeline": {"type": "array"},
                    "proposal_only": {"type": "boolean"},
                    "writes_wiki": {"type": "boolean"},
                    "requires_human_approval_to_write_wiki": {"type": "boolean"},
                },
            },
            action_type="read",
            requires_confirmation=False,
            tags=["autoresearch", "workflow", "execution"],
            triggers=["/study", "研究："],
            trigger_param="question",
        ),
        "status": SkillAction(
            name="status",
            description=(
                "Query an AutoResearch Compound workflow run by run_id. "
                "Returns a compact summary (status, per-phase status, "
                "artifact counts). Pass include_details=true to also get "
                "the full final report from the synthesize phase."
            ),
            handler=_handle_status,
            input_schema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string", "description": "Run ID to query."},
                    "include_details": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, also include the synthesize phase's "
                            "full final report (markdown + answer + artifacts). "
                            "Default is false (compact summary only)."
                        ),
                    },
                },
                "required": ["run_id"],
            },
            action_type="read",
            tags=["autoresearch", "workflow", "query"],
        ),
    }


autoresearch_compound_skill = AutoResearchCompoundSkill()


__all__ = [
    "AutoResearchCompoundSkill",
    "WORKFLOW_NAME",
    "autoresearch_compound_skill",
]
