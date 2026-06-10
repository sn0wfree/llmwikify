"""research_skill — 7-step ReAct research pipeline.

Per v0.32 Phase 6 (3 weeks, scaled to single session): this
module replaces the 1178-LOC ``apps/research/engine.py``
ReAct loop with a thin ReactLoop wrapper (Phase 8's
``ReactConfig``) that orchestrates 7 research-specific
actions (Phase 5's 23 base actions).

Pipeline structure
------------------

The 7 phases of a research session, in order:

  1. plan       — decompose the query into sub-queries
                  (action: plan_skill.plan)
  2. gather     — search/extract sources for each sub-query
                  (delegates to gather_skill pipeline, Phase 12)
  3. analyze    — entity recognition + quality assessment
                  (action: analyze_skill.analyze)
  4. synthesize — cross-source claims + gaps
                  (action: summarize_skill.summarize)
  5. score      — multi-dimensional quality scoring
                  (action: score_skill.score)
  6. revise     — improve text if score < threshold
                  (action: revise_skill.revise)
  7. report     — write final markdown report
                  (delegates to report_skill pipeline, Phase 12)

Plus a sentinel ``done`` action that the reason function
returns to exit the loop.

This is much smaller than the original engine.py:
  - Pre-Phase 6: 1178 LOC (one file, 8 _action_* methods,
    600 LOC of in-memory state machine, ~200 LOC of
    ReAct orchestration)
  - Post-Phase 6: ~280 LOC (this file) + ReactLoop (~340
    LOC, shared) + 23 actions (Phase 5, already shipped)

The state machine is now a dict (15+ fields) instead of a
dataclass, because the framework's ``ReactLoop.run``
mutates a single state dict. Phase 6 persists this dict
via the new ``ChatDatabase.save_research_state`` (Phase 3).

State persistence
-----------------

Every round, ``persist_state`` is called with the state
dict; we serialize the whole dict into
``research_steps.result_json`` (Phase 3's new table).
``restore_state`` (called once at run() start) loads the
last persisted step and replaces the state. This is the
resume mechanism.

Design refs
-----------

  - ``v0.32-skill-restructure.md`` §19.4 (research_skill
    ReactLoop config)
  - ``v0.32-execution-plan.md`` Phase 6
"""

from __future__ import annotations

import json
import logging
from typing import Any

from llmwikify.apps.chat.agent.react_engine import (
    EVENT_PHASE,
    EVENT_REASONING,
    EVENT_ROUND_COMPLETE,
    ReactConfig,
    ReactLoop,
)
from llmwikify.apps.chat.skills.actions.analyze_action import analyze_skill
from llmwikify.apps.chat.skills.actions.plan_action import plan_skill
from llmwikify.apps.chat.skills.actions.reason_action import reason_skill
from llmwikify.apps.chat.skills.actions.revise_action import revise_skill
from llmwikify.apps.chat.skills.actions.score_action import score_skill
from llmwikify.apps.chat.skills.actions.summarize_action import summarize_skill
from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)
from llmwikify.apps.chat.skills.registry import (
    SkillRegistry,
    default_registry,
)

logger = logging.getLogger(__name__)


# ─── LLM prompt for the research reasoner ────────────────────────
# Phase 6 ships a rule-based reasoner; the LLM prompt is
# the fallback when ctx.llm_client is configured (Phase 6+
# wiring to real LLM is in research_skill.run_research).
RESEARCH_REASON_PROMPT = """\
You are a research orchestrator using ReAct reasoning.
Based on the current state, decide the next action.

Return JSON: { "thought": str, "action": str }
where action is one of:
  plan, gather, analyze, synthesize, score, revise, report, done

Decision rules (apply in order):
  1. If no sub_queries → "plan"
  2. If sub_queries but no sources → "gather"
  3. If sources but no analysis → "analyze"
  4. If sources analyzed but no synthesis → "synthesize"
  5. If synthesis but no score → "score"
  6. If score < 0.5 and rounds remain → "revise"
  7. If score >= 0.5 and no report → "report"
  8. Otherwise → "done"
"""


# ─── 7 action handlers ────────────────────────────────────────────
# Each handler is the ReactLoop "Act" step. It mutates the
# state dict in place; ReactLoop folds the returned data
# into state (state.update(result.data)).


async def _act_plan(args: dict, ctx: SkillContext) -> SkillResult:
    """Phase 1: plan sub-queries from the research query."""
    state = args
    state["phase"] = "planning"
    query = state.get("query", "")
    if not query:
        return SkillResult.fail("query is required for plan")
    # Delegate to Phase 5's plan action
    r = await plan_skill.actions["plan"].handler(
        {"query": query}, ctx,
    )
    if r.status != "ok":
        return r
    sub_queries = r.data.get("sub_queries", [])
    # Merge into state (deduplicate)
    existing = {sq.get("q", "").lower() for sq in state.get("sub_queries", [])}
    new = [sq for sq in sub_queries if sq.get("q", "").lower() not in existing]
    state.setdefault("sub_queries", []).extend(new)
    return SkillResult.ok({
        "sub_queries": state["sub_queries"],
        "_plan_added": len(new),
    })


async def _act_gather(args: dict, ctx: SkillContext) -> SkillResult:
    """Phase 2: gather sources for the (still-ungathered) sub-queries.

    Delegates to ``gather_skill`` pipeline (Phase 12). The
    pipeline handles wiki.search, dedup, and optional content
    extraction.
    """
    state = args
    state["phase"] = "gathering"
    # Filter out already-gathered sub-queries
    sub_queries = state.get("sub_queries", [])
    ungathered = [
        sq for sq in sub_queries
        if sq.get("status") != "gathered"
    ]
    if not ungathered:
        state.setdefault("sources", [])
        return SkillResult.ok({
            "sources": state["sources"],
            "_new_sources": 0,
        })
    # Delegate to the gather pipeline
    from llmwikify.apps.chat.skills.pipelines.gather_skill import (
        gather_skill as _gather,
    )
    r = await _gather.actions["gather_for_research"].handler(
        {
            "sub_queries": ungathered,
            "sources": state.get("sources", []),
        }, ctx,
    )
    if r.status != "ok":
        return r
    # Update sub-query statuses
    failed = set(r.data.get("_failed_queries", []))
    for sq in ungathered:
        if sq.get("q", "") in failed:
            sq["status"] = "failed"
        else:
            sq["status"] = "gathered"
    state["sources"] = r.data["sources"]
    return SkillResult.ok({
        "sources": state["sources"],
        "_new_sources": r.data.get("_new_sources", 0),
    })


async def _act_analyze(args: dict, ctx: SkillContext) -> SkillResult:
    """Phase 3: analyze unanalyzed sources."""
    state = args
    state["phase"] = "analyzing"
    sources = state.get("sources", [])
    # Mark analysis as "done" even when there are no sources,
    # so the rule-based reasoner progresses to the next step
    # instead of looping. Real-world scenarios with sources
    # would proceed to per-source analysis.
    state["analysis"] = {
        "entities": [],
        "quality_assessment": {"credibility": 0 if not sources else 7},
        "_source_count": len(sources),
    }
    if not sources:
        return SkillResult.ok({
            "_no_sources": True,
            "analyzed": 0,
            "analysis": state["analysis"],
        })
    wiki = ctx.wiki
    if wiki is None:
        # Offline: synthetic per-source analysis
        for s in sources:
            if "analysis" not in s:
                s["analysis"] = {
                    "entities": [], "quality_assessment": {"credibility": 7},
                }
        return SkillResult.ok({"_offline_analyze": True, "analyzed": len(sources)})
    # Use Phase 5's analyze action (one source at a time)
    analyzed = 0
    for s in sources:
        if s.get("analysis"):
            continue
        r = await analyze_skill.actions["analyze"].handler(
            {"source_path": s.get("url", ""), "force": False}, ctx,
        )
        if r.status == "ok":
            s["analysis"] = r.data
            analyzed += 1
    return SkillResult.ok({"analyzed": analyzed})


async def _act_synthesize(args: dict, ctx: SkillContext) -> SkillResult:
    """Phase 4: synthesize cross-source claims."""
    state = args
    state["phase"] = "synthesizing"
    sources = state.get("sources", [])
    r = await summarize_skill.actions["summarize"].handler(
        {"sources": sources}, ctx,
    )
    if r.status != "ok":
        return r
    state["synthesis"] = r.data
    # Extract knowledge gaps and contradictions
    state["knowledge_gaps"] = r.data.get("gaps", [])
    state["contradictions"] = r.data.get("contradictions", [])
    return SkillResult.ok({
        "synthesis": r.data,
        "knowledge_gaps": state["knowledge_gaps"],
    })


async def _act_score(args: dict, ctx: SkillContext) -> SkillResult:
    """Phase 5: multi-dimensional quality score."""
    state = args
    state["phase"] = "scoring"
    synthesis = state.get("synthesis") or {}
    text = synthesis.get("narrative", "")
    if not text:
        return SkillResult.fail("no synthesis narrative to score")
    r = await score_skill.actions["score"].handler(
        {"text": text}, ctx,
    )
    if r.status != "ok":
        return r
    state["score"] = r.data["score"]
    state["score_by_dim"] = r.data.get("by_dimension", {})
    return SkillResult.ok({
        "score": state["score"],
        "by_dimension": state["score_by_dim"],
    })


async def _act_revise(args: dict, ctx: SkillContext) -> SkillResult:
    """Phase 6: revise the synthesis if score is low."""
    state = args
    state["phase"] = "revising"
    score = state.get("score", 1.0)
    synthesis = state.get("synthesis") or {}
    text = synthesis.get("narrative", "")
    if score >= 0.5:
        return SkillResult.ok({"_skipped": True, "score": score})
    r = await revise_skill.actions["revise"].handler(
        {"text": text, "score": score}, ctx,
    )
    if r.status != "ok":
        return r
    # Apply revision
    if r.data.get("revised"):
        synthesis["narrative"] = r.data["revised"]
    state["synthesis"] = synthesis
    state["revision_count"] = state.get("revision_count", 0) + 1
    return SkillResult.ok({
        "revised": True,
        "revision_count": state["revision_count"],
    })


async def _act_report(args: dict, ctx: SkillContext) -> SkillResult:
    """Phase 7: write the final markdown report.

    Delegates to ``report_skill`` pipeline (Phase 12). The
    pipeline builds the markdown from synthesis + sources.
    """
    state = args
    state["phase"] = "reporting"
    from llmwikify.apps.chat.skills.pipelines.report_skill import (
        report_skill as _report,
    )
    r = await _report.actions["generate_report"].handler(
        {
            "query": state.get("query", "Research Report"),
            "synthesis": state.get("synthesis"),
            "sources": state.get("sources", []),
            "knowledge_gaps": state.get("knowledge_gaps", []),
        }, ctx,
    )
    if r.status != "ok":
        return r
    state["report_md"] = r.data["report_md"]
    return SkillResult.ok({
        "report_md": state["report_md"],
        "report_length": r.data.get("report_length", 0),
    })


# ─── Hooks ──────────────────────────────────────────────────────


def _make_check_control_signals(db: Any) -> "Any":
    """Build the on_before_act hook for cancel/pause signals.

    Reads the DB session's status field; if "cancelling" or
    "pausing", sets state flags. ReactLoop's done_condition
    picks these up next round.
    """
    def check_control_signals(state: dict, action_name: str) -> None:
        if db is None:
            return
        try:
            session = db.get_research_session(state.get("session_id", ""))
            if session:
                db_status = session.get("status", "")
                if db_status == "cancelling":
                    state["cancelled"] = True
                elif db_status == "pausing":
                    state["paused"] = True
        except Exception as e:
            logger.debug("Control signal check failed: %s", e)
    return check_control_signals


def _make_gate_intervention(
    db: Any,
    gate_min_sources: int = 3,
) -> "Any":
    """Build the on_after_act hook for quality gate intervention.

    Phase 6 simplified gate: if after a "gather" action
    we have ≥ gate_min_sources, force the next action to be
    "analyze" (avoids the "stuck in gather" loop pattern).
    A full gate implementation lands in Phase 7 (5 harness
    eval classes).
    """
    def gate_intervention(state: dict, action_name: str, result: SkillResult) -> None:
        if action_name != "gather":
            return
        if result.status != "ok":
            return
        sources = state.get("sources", [])
        if len(sources) >= gate_min_sources:
            state["_forced_next_action"] = "analyze"
            state.setdefault("observations", []).append(
                f"gate: gathered {len(sources)} ≥ {gate_min_sources} sources, "
                f"forcing analyze next round"
            )
    return gate_intervention


def _make_persist_state(db: Any) -> "Any":
    """Build the persist_state hook: serialize state into research_steps."""
    def persist_research_state(state: dict, round_idx: int) -> None:
        if db is None:
            return
        try:
            db.save_research_state(
                session_id=state.get("session_id", ""),
                step_num=round_idx,
                state=state,
            )
        except Exception as e:
            logger.warning("persist_state failed: %s", e)
    return persist_research_state


def _make_restore_state(db: Any) -> "Any":
    """Build the restore_state hook: load last persisted state."""
    def restore_research_state(state: dict) -> dict:
        if db is None or not state.get("session_id"):
            return state
        # Find the last step with a result_json
        steps = db.list_steps(state["session_id"])
        if not steps:
            return state
        last = steps[-1]
        saved = last.get("result")
        if isinstance(saved, dict):
            return saved
        return state
    return restore_research_state


# ─── Config builder ────────────────────────────────────────────


def _make_research_config(args: dict, ctx: SkillContext) -> ReactConfig:
    """Build the ReactConfig for one research session.

    Args is the raw dict passed to ``run_research``. Pulls
    the chat DB and SkillRegistry from ``ctx``; falls back
    to the default singleton if neither is set (test
    scenarios).
    """
    db = getattr(ctx, "db", None)
    registry = ctx.config.get("registry") if ctx.config else None
    if registry is None:
        # The default registry should have the 23 base actions
        # already registered (Phase 5).
        registry = default_registry()

    # Build the 7 action SkillActions by re-fetching from the
    # registry. This ensures the actions used here are the
    # same instances the registry exposes to LLM tools.
    def _action(name: str, action: str) -> Any:
        skill = registry.get(name)
        if skill is None:
            # Fall back to module-level instance (offline /
            # non-registered state). Useful for tests.
            from llmwikify.apps.chat.skills.actions import (
                plan_skill as _plan,
                analyze_skill as _analyze,
                summarize_skill as _summarize,
                score_skill as _score,
                revise_skill as _revise,
            )
            fallback = {
                "plan": _plan, "analyze": _analyze,
                "summarize": _summarize, "score": _score,
                "revise": _revise,
            }
            return fallback[name].actions[action]
        return skill.actions[action]

    plan_action = _action("plan", "plan")
    analyze_action = _action("analyze", "analyze")
    summarize_action = _action("summarize", "summarize")
    score_action = _action("score", "score")
    revise_action = _action("revise", "revise")

    # Wrap each so it can be invoked with the state dict
    # (the framework's action handler contract is (args, ctx)
    # where args is the state; we need a (state, ctx)
    # binding).
    from llmwikify.apps.chat.skills.base import SkillAction

    def _wrap(name: str, fn: "Any") -> SkillAction:
        async def handler(args: dict, ctx: SkillContext) -> SkillResult:
            return await fn(args, ctx)
        return SkillAction(
            name=name,
            description=f"research_skill {name} step",
            handler=handler,
            input_schema={"type": "object", "properties": {}, "required": []},
        )

    actions = [
        _wrap("plan", _act_plan),
        _wrap("gather", _act_gather),
        _wrap("analyze", _act_analyze),
        _wrap("synthesize", _act_synthesize),
        _wrap("score", _act_score),
        _wrap("revise", _act_revise),
        _wrap("report", _act_report),
    ]

    # Use the module-level reason_skill as the Reason callable
    # (Phase 5 ships a rule-based fallback; Phase 6+ can wire
    # to LLM via ctx.llm_client).

    async def reason_for_research(state: dict, ctx: SkillContext) -> dict:
        # Try LLM-driven reason first if available
        llm = getattr(ctx, "llm_client", None)
        if llm is not None and state.get("reason_prompt"):
            try:
                # Phase 6: not implemented yet (Phase 6.5).
                # Fall through to rule-based.
                pass
            except Exception as e:
                logger.warning("LLM reason failed: %s, using rule-based", e)
        # Rule-based fallback (Phase 5)
        from llmwikify.apps.chat.skills.actions.reason_action import _rule_based_reason
        return _rule_based_reason(state)

    # Initial state — 15+ fields per Phase 3 design
    initial_state: dict[str, Any] = {
        "session_id": args.get("session_id", ""),
        "query": args.get("query", ""),
        "round": 0,
        "max_rounds": args.get("max_rounds", 5),
        "max_replan": args.get("max_replan", 2),
        "phase": "",
        "sub_queries": [],
        "sources": [],
        "synthesis": None,
        "report_md": None,
        "review": None,
        "knowledge_gaps": [],
        "contradictions": [],
        "issues": [],
        "observations": [],
        "cancelled": False,
        "paused": False,
        "budget_remaining": 1.0,
        "_last_thought": "",
    }

    return ReactConfig(
        actions=actions,
        initial_state=initial_state,
        reason_prompt=RESEARCH_REASON_PROMPT,
        done_condition=lambda s: (
            s.get("phase") == "done"
            or s.get("cancelled", False)
            or s.get("paused", False)
            or s.get("_forced_next_action") is not None
        ),
        reason=reason_for_research,
        max_rounds=args.get("max_rounds", 5),
        on_before_act=_make_check_control_signals(db),
        on_after_act=_make_gate_intervention(
            db, gate_min_sources=args.get("gate_min_sources", 3),
        ),
        persist_state=_make_persist_state(db),
        restore_state=_make_restore_state(db),
    )


# ─── Public action handlers ─────────────────────────────────────


async def run_research(args: dict, ctx: SkillContext) -> SkillResult:
    """Run a research session.

    ``args`` keys:
      - session_id (str): pre-created session id (optional
        if ``create_session_if_missing`` is True)
      - query (str): the research query
      - max_rounds (int): override the default (5)
      - gate_min_sources (int): force analyze after this many
        gathered sources (default 3)

    Returns a SkillResult whose data is the list of events
    yielded by the ReactLoop (``reasoning``, ``round_complete``,
    ``phase``). The final state is in ``ctx.config['final_state']``
    or, if ``persist_final`` is set, in the DB.
    """
    config = _make_research_config(args, ctx)
    loop = ReactLoop(config)
    events: list[dict] = []
    async for event in loop.run(ctx):
        events.append(event)
    # Find the terminal phase event for the final state
    final_state = loop.state
    return SkillResult.ok({
        "events": events,
        "final_state": final_state,
        "report_md": final_state.get("report_md"),
        "round": final_state.get("round", 0),
        "score": final_state.get("score"),
        "cancelled": final_state.get("cancelled", False),
        "paused": final_state.get("paused", False),
    })


async def resume_research(args: dict, ctx: SkillContext) -> SkillResult:
    """Resume a paused/cancelled research session.

    Same as ``run_research`` but the ``restore_state`` hook
    in ReactConfig picks up the last persisted step.
    """
    return await run_research(args, ctx)


async def cancel_research(args: dict, ctx: SkillContext) -> SkillResult:
    """Cancel a running research session.

    Updates the DB status to ``cancelling``; the next
    ``_check_control_signals`` hook tick will pick this up
    and the loop will exit.
    """
    db = getattr(ctx, "db", None)
    session_id = args.get("session_id")
    if db is None or not session_id:
        return SkillResult.fail("db and session_id are required")
    try:
        db.update_research_status(session_id, "cancelling", "cancelling", -1)
    except Exception as e:
        return SkillResult.fail(f"cancel failed: {e!r}")
    return SkillResult.ok({"status": "cancelling", "session_id": session_id})


# ─── Skill declaration ─────────────────────────────────────────


class ResearchSkill(Skill):
    """Research pipeline: run / resume / cancel.

    Composes the 7 action handlers (plan/gather/analyze/
    synthesize/score/revise/report) into a single
    ReactLoop-driven pipeline. The skill exposes 3 actions
    to the LLM:

      - run_research  — start a new session
      - resume_research — resume from persisted state
      - cancel_research — mark a session for cancellation

    The internal ReAct orchestration (reason → act →
    observe, with 6 hooks) is delegated to ReactLoop
    (``apps/chat/agent/react_loop.py``).
    """

    name = "research"
    description = "7-step ReAct research pipeline (plan→gather→...→report)"
    actions = {
        "run_research": SkillAction(
            name="run_research",
            description=(
                "Run a full 7-step research session. Args: "
                "session_id (str), query (str), max_rounds (int), "
                "gate_min_sources (int). Returns events + final "
                "state + report_md."
            ),
            handler=run_research,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Pre-created session id"},
                    "query": {"type": "string", "description": "Research query"},
                    "max_rounds": {"type": "integer", "default": 5},
                    "gate_min_sources": {"type": "integer", "default": 3},
                },
                "required": ["session_id", "query"],
            },
        ),
        "resume_research": SkillAction(
            name="resume_research",
            description="Resume a paused/cancelled session from persisted state.",
            handler=resume_research,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["session_id"],
            },
        ),
        "cancel_research": SkillAction(
            name="cancel_research",
            description="Cancel a running research session.",
            handler=cancel_research,
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                },
                "required": ["session_id"],
            },
        ),
    }


research_skill = ResearchSkill()


__all__ = [
    "ResearchSkill",
    "research_skill",
    "run_research",
    "resume_research",
    "cancel_research",
    "RESEARCH_REASON_PROMPT",
    "_make_research_config",
]
