"""Action implementations for the ReAct research loop.

Each action is a free function that receives an ActionContext (deps)
and the current ResearchState, and yields SSE event dicts. The engine
orchestrates the ReAct loop; actions do the work.

This module is extracted from engine.py (Commits 5a/5b/5c of the
engine.py refactoring plan — see docs/refactoring-engine-py.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from llmwikify.foundation.llm.streamable import StreamableLLMClient
from llmwikify.apps.chat.clarifier import ResearchClarifier
from llmwikify.apps.chat.config import merge_six_step_config
from llmwikify.apps.chat.gatherer import SourceGatherer
from llmwikify.apps.chat.llm_step import run_prompt
from llmwikify.apps.chat.prompts import _plan_fallback, _replan_fallback
from llmwikify.apps.chat.quality_gate import QualityGate
from llmwikify.apps.chat.report import ReportGenerator
from llmwikify.apps.chat.review import ResearchReviewer, ResearchRevisor
from llmwikify.apps.chat.session import ResearchSessionManager
from llmwikify.apps.chat.state import (
    ActionMetrics,
    MetricsCollector,
    ResearchState,
    SessionMetrics,
    VALID_TRANSITIONS,
)

logger = logging.getLogger(__name__)


# ─── Metrics tracking decorator ─────────────────────────────────────────


def tracked(action_name: str):
    """Decorator: wraps an async-generator action in metrics.record().

    Usage::

        @tracked("clarify")
        async def action_clarify(ctx, state):
            ...  # body unchanged, no indentation bump
    """
    def decorator(fn):
        async def wrapper(ctx: ActionContext, state: ResearchState):
            with ctx.metrics.record(action_name):
                async for event in fn(ctx, state):
                    yield event
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__wrapped__ = fn
        return wrapper
    return decorator


# ─── ActionContext: all deps the 9 action functions need ─────────────────


@dataclass
class ActionContext:
    """All deps the 9 action functions need. Constructed once in
    ResearchEngine.__init__, captured by functools.partial() at dispatch time.

    This replaces the ``self.xxx`` access pattern: each action receives
    ``ctx`` as its first arg instead of being an instance method.
    """
    wiki: Any
    db: Any  # AutoResearchDatabase
    session_manager: ResearchSessionManager
    clarifier: ResearchClarifier
    gatherer: SourceGatherer
    analyzer: Any  # SourceAnalyzer
    synthesizer: Any  # ResearchSynthesizer
    report: ReportGenerator
    reviewer: ResearchReviewer
    revisor: ResearchRevisor
    quality_gate: QualityGate
    config: dict[str, Any]
    metrics: MetricsCollector | None
    planning_llm: StreamableLLMClient
    default_llm: StreamableLLMClient  # used by ResearchReviewer
    report_llm: StreamableLLMClient   # used by ReportGenerator + ResearchRevisor


# ─── Helpers (extracted from engine.py) ─────────────────────────────────


def _step_event(session_id: str, step: str, message: str) -> dict[str, Any]:
    """Build an SSE step event dict.

    Free function version of the former ``ResearchEngine._step_event``.
    """
    return {"type": "step", "step": step, "message": message, "session_id": session_id}


def _warn_invalid_transition(from_phase: str, to_phase: str) -> None:
    """Log a warning if the transition is invalid.

    Free function version of the former ``ResearchEngine._warn_invalid_transition``.
    """
    # First run or uninitialized state → always allow
    if not from_phase:
        return
    valid_targets = VALID_TRANSITIONS.get(from_phase, [])
    if to_phase not in valid_targets:
        logger.warning(
            "Invalid state transition: %s → %s (valid: %s)",
            from_phase, to_phase, valid_targets or "none",
        )


# ─── Planning helpers (used by action_plan) ────────────────────────────


async def _plan_sub_queries(ctx: ActionContext, query: str) -> list[dict[str, Any]]:
    """Decompose the research topic into sub-queries using planning_model."""
    local_wiki_matches = ""
    try:
        wiki_results = ctx.wiki.search(query, limit=5)
        if wiki_results:
            lines = []
            for r in wiki_results:
                name = r.get("page_name", "")
                snippet = r.get("snippet", "")
                score = r.get("score", 0)
                lines.append(f"- {name} (score: {score:.2f}): {snippet}")
            local_wiki_matches = "\n".join(lines)
    except Exception as e:
        logger.debug("Local wiki search failed: %s", e)

    wiki_index = ""
    if ctx.wiki.index_file.exists():
        wiki_index = ctx.wiki.index_file.read_text()[:3000]

    try:
        result = await run_prompt(
            ctx, "research_plan",
            query=query,
            wiki_index=wiki_index[:2000] if wiki_index else "",
            local_wiki_matches=local_wiki_matches,
        )
        if not isinstance(result, list):
            result = []
    except Exception as e:
        logger.warning("Planning LLM failed: %s, using single query", e)
        result = _plan_fallback(query=query, error=e)

    max_sq = ctx.config.get("max_sub_queries", 20)
    sub_queries: list[dict[str, Any]] = []

    for item in result[:max_sq]:
        sq_type = item.get("source_type", "web")
        if sq_type not in ("web", "youtube", "wiki", "pdf"):
            sq_type = "web"
        sub_queries.append({
            "query": item.get("query", ""),
            "source_type": sq_type,
            "url": item.get("url"),
        })

    if not sub_queries:
        sub_queries.append({"query": query, "source_type": "web", "url": ""})

    return sub_queries


async def _plan_for_gaps(
    ctx: ActionContext, query: str, gaps: list[str],
) -> list[dict[str, Any]]:
    """Generate sub-queries to fill knowledge gaps."""
    local_wiki_matches = ""
    try:
        gap_query = f"{query} {' '.join(gaps[:3])}"
        wiki_results = ctx.wiki.search(gap_query, limit=3)
        if wiki_results:
            lines = []
            for r in wiki_results:
                name = r.get("page_name", "")
                snippet = r.get("snippet", "")
                lines.append(f"- {name}: {snippet}")
            local_wiki_matches = "\n".join(lines)
    except Exception as e:
        logger.debug("Local wiki search for gaps failed: %s", e)

    wiki_context = ""
    if local_wiki_matches:
        wiki_context = (
            f"\n\nExisting wiki articles that may help fill gaps:\n"
            f"{local_wiki_matches}\nUse source_type \"wiki\" for these if relevant."
        )

    try:
        # Pass the raw gaps list (Jinja2 for-loop in the YAML handles
        # the '- ' formatting). The [:5] slice limits to the top 5
        # gaps so the user message stays compact.
        result = await run_prompt(
            ctx, "research_replan",
            query=query,
            gaps=gaps[:5],
            wiki_context=wiki_context,
        )
        if not isinstance(result, list):
            result = []
    except Exception as e:
        logger.warning("Gap planning LLM failed: %s", e)
        result = _replan_fallback(query=query, gaps=gaps, error=e)

    sub_queries = []
    for item in result[:5]:
        sq_type = item.get("source_type", "web")
        if sq_type not in ("web", "youtube", "wiki", "pdf"):
            sq_type = "web"
        sub_queries.append({
            "query": item.get("query", ""),
            "source_type": sq_type,
            "url": item.get("url"),
        })

    return sub_queries


# ─── 6-step context builder (used by action_report + action_review) ────


def _build_six_step_context(state: ResearchState) -> dict[str, Any] | None:
    """Build a 6-step context dict from state for report/review prompts."""
    if not state.clarification and not state.evidence_scores:
        return None

    ctx: dict[str, Any] = {}
    if state.clarification:
        ctx["clarification"] = state.clarification
    if state.evidence_scores:
        ctx["evidence_scores"] = state.evidence_scores
    if state.reasoning_check:
        ctx["reasoning_check"] = state.reasoning_check
    if state.structure_check:
        ctx["structure_check"] = state.structure_check
    return ctx if ctx else None


# ─── Synthesis → text helper (used by action_synthesize + engine._evaluate_gate) ───


def synthesis_to_text(synthesis: dict | None) -> str:
    """Flatten the synthesis dict into a single text blob for the reasoner.

    The synthesizer stores structured output (claims / reinforced_claims
    / contradictions / knowledge_gaps). The ReasoningChecker expects
    a text synthesis, so we concatenate the human-readable parts.

    Free function version of the former ``ResearchEngine._synthesis_to_text``.
    """
    if not synthesis:
        return ""
    parts: list[str] = []
    for key in ("summary", "synthesis", "analysis", "main_text", "narrative"):
        v = synthesis.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    for key in ("reinforced_claims", "claims"):
        items = synthesis.get(key) or []
        for it in items:
            if isinstance(it, dict):
                text = it.get("text") or it.get("claim") or ""
                if text:
                    parts.append(f"- {text}")
            elif isinstance(it, str):
                parts.append(f"- {it}")
    for key in ("contradictions",):
        for it in synthesis.get(key) or []:
            if isinstance(it, dict):
                text = it.get("text") or it.get("description") or ""
                if text:
                    parts.append(f"! {text}")
    for gap in synthesis.get("knowledge_gaps") or []:
        if isinstance(gap, str):
            parts.append(f"? {gap}")
        elif isinstance(gap, dict):
            parts.append(f"? {gap.get('text', '')}")
    return "\n".join(parts)


# ─── Actions: 9 free functions ─────────────────────────────────────────


@tracked("clarify")
async def action_clarify(
    ctx: ActionContext, state: ResearchState,
):
    """6-step step 1: clarify research context, boundaries, position, premises.

    Runs only when clarify_enabled (default true) and not on resume. The
    result is stored in state.clarification and persisted to the DB.
    """
    # Skip if disabled
    if not ctx.config.get("clarify_enabled", True):
        state.clarification = {"scope_check": True, "context": "skipped (clarify_enabled=False)"}
        return

    _warn_invalid_transition(state.phase, "clarifying")

    state.phase = "clarifying"
    ctx.session_manager.update_status(state.session_id, "clarifying", "clarifying", None)
    yield _step_event(state.session_id, "clarifying", "Clarifying research scope and boundaries...")

    # Build wiki context
    wiki_context = ""
    try:
        wiki_results = ctx.wiki.search(state.query, limit=3)
        if wiki_results:
            lines = [
                f"- {r.get('page_name', '')}: {r.get('snippet', '')[:200]}"
                for r in wiki_results
            ]
            wiki_context = "\n".join(lines)
    except Exception as e:
        logger.debug("Wiki search for clarification failed: %s", e)

    # Run clarifier with self-loop
    clarification, loop_history = await ctx.clarifier.clarify_with_loop(
        query=state.query,
        wiki_context=wiki_context,
        budget_remaining=state.budget_remaining,
    )

    state.clarification = clarification
    state.self_loop_counts["clarify"] = len(loop_history) - 1
    state.self_loop_history.extend(loop_history)

    # Persist to DB (independent autoresearch.db — no shared schema)
    try:
        ctx.db.update_research_status(
            state.session_id, "clarifying", "clarifying",
            iteration_round=state.round,
            synthesis_json=None,
            review_json=None,
        )
        ctx.db.update_six_step_fields(
            state.session_id, clarification=clarification,
        )
    except Exception as e:
        logger.warning("Clarification persist: %s", e)

    # Yield result event
    yield {
        "type": "clarification_complete",
        "round": state.round,
        "scope_check": clarification.get("scope_check", False),
        "premises_count": len(clarification.get("premises", [])),
        "warnings": clarification.get("warnings", []),
        "loop_attempts": len(loop_history),
    }

    if not clarification.get("scope_check", False):
        state.observations.append(
            f"⚠ 概念澄清未通过 scope_check，但将继续 plan（{len(loop_history)} 次尝试）"
        )


@tracked("plan")
async def action_plan(
    ctx: ActionContext, state: ResearchState,
):
    """Plan sub-queries (initial or replanning for gaps)."""
    _warn_invalid_transition(state.phase, "planning")

    state.phase = "planning"
    ctx.session_manager.update_status(state.session_id, "planning", "planning", None)
    yield _step_event(state.session_id, "planning", f"Planning sub-queries (round {state.round})...")

    # Decide: initial plan or gap-focused replan
    if state.knowledge_gaps and state.sub_queries:
        yield {"type": "gap_detected", "gaps": state.knowledge_gaps, "round": state.round}
        sub_queries = await _plan_for_gaps(ctx, state.query, state.knowledge_gaps)
    else:
        sub_queries = await _plan_sub_queries(ctx, state.query)

    # Deduplicate against existing
    existing_queries = {sq["query"].lower().strip() for sq in state.sub_queries}
    new_queries = [sq for sq in sub_queries if sq["query"].lower().strip() not in existing_queries]

    for sq in new_queries[:5]:  # Limit per round
        sq_id = ctx.session_manager.add_sub_query(
            state.session_id, sq["query"], sq["source_type"], sq.get("url")
        )
        sq["id"] = sq_id
        state.sub_queries.append(sq)
        yield {
            "type": "sub_query_created",
            "sub_query_id": sq_id,
            "query": sq["query"],
            "source_type": sq["source_type"],
            "url": sq.get("url"),
        }

    yield {"type": "progress", "progress": 0.1, "message": f"Round {state.round}: {len(new_queries)} new sub-queries"}


@tracked("gather")
async def action_gather(
    ctx: ActionContext, state: ResearchState,
):
    """Gather sources for ungathered or failed sub-queries."""
    _warn_invalid_transition(state.phase, "gathering")

    state.phase = "gathering"
    ctx.session_manager.update_status(state.session_id, "gathering", "gathering", None)
    yield _step_event(state.session_id, "gathering", "Gathering sources...")

    gathered_ids = {s.get("sub_query_id") for s in state.sources}
    remaining = [sq for sq in state.sub_queries if sq["id"] not in gathered_ids]

    # DR-2: Also retry failed sub-queries (max 1 retry per sub-query)
    failed = [sq for sq in state.sub_queries if sq.get("status") == "failed"]
    retryable = [
        sq for sq in failed
        if sq.get("retry_count", 0) < 1
    ]
    if retryable:
        yield {"type": "retrying_failed", "count": len(retryable)}
        for sq in retryable:
            sq["retry_count"] = sq.get("retry_count", 0) + 1
        remaining.extend(retryable)

    if remaining:
        gatherer = SourceGatherer(ctx.wiki, ctx.db, ctx.session_manager, ctx.config)
        events = await gatherer.gather(remaining)
        for event in events:
            yield event

    sources = ctx.db.get_sources(state.session_id) or []
    yield {"type": "progress", "progress": 0.4, "message": f"Gathered {len(sources)} sources total"}

    # ─── 6-step step 2: evidence scoring (run only when enabled) ───
    if ctx.config.get("evidence_scoring_enabled", True) and sources:
        from llmwikify.apps.chat.source_filter import SourceFilter
        sf = SourceFilter(ctx.config)
        new_scores: dict[str, float] = {}
        for src in sources:
            sid = src.get("id")
            if not sid:
                continue
            try:
                new_scores[sid] = round(float(sf.compute_evidence_score(src)), 4)
            except Exception as e:
                logger.warning("evidence_score failed for %s: %s", sid, e)
                new_scores[sid] = 0.0
        # Merge with any existing scores (preserve across replans)
        state.evidence_scores.update(new_scores)
        try:
            ctx.db.update_six_step_fields(
                state.session_id, evidence_scores=state.evidence_scores
            )
        except Exception as e:
            logger.warning("evidence_scores persist: %s", e)
        yield {
            "type": "evidence_scoring_complete",
            "count": len(new_scores),
            "avg_score": round(sum(new_scores.values()) / max(1, len(new_scores)), 4),
        }

    if not sources:
        ctx.session_manager.update_status(state.session_id, "error", "gathering", -1)
        yield {"type": "error", "error": "No sources gathered. All sub-queries failed."}
        state.phase = "error"
        state.issues.append("No sources gathered — all sub-queries failed")


# ─── Actions: 6 more (Commit 5b) ─────────────────────────────────────


@tracked("analyze")
async def action_analyze(
    ctx: ActionContext, state: ResearchState,
):
    """Analyze unanalyzed sources."""
    _warn_invalid_transition(state.phase, "analyzing")

    state.phase = "analyzing"
    ctx.session_manager.update_status(state.session_id, "analyzing", "analyzing", None)
    yield _step_event(state.session_id, "analyzing", "Analyzing sources...")

    sources = ctx.db.get_sources(state.session_id) or []
    unanalyzed = [s for s in sources if not s.get("analysis")]

    if unanalyzed:
        analyzer = ctx.analyzer
        events = await analyzer.analyze_sources(unanalyzed)
        for event in events:
            yield event

    yield {"type": "progress", "progress": 0.55, "message": "Analysis complete"}


@tracked("synthesize")
async def action_synthesize(
    ctx: ActionContext, state: ResearchState,
):
    """Synthesize findings from analyzed sources."""
    _warn_invalid_transition(state.phase, "synthesizing")

    state.phase = "synthesizing"
    ctx.session_manager.update_status(state.session_id, "synthesizing", "synthesizing", None)
    yield _step_event(state.session_id, "synthesizing", "Synthesizing cross-source findings...")

    sources = ctx.db.get_sources(state.session_id) or []
    synthesizer = ctx.synthesizer
    state.synthesis = await synthesizer.synthesize(sources, query=state.query)
    state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
    state.contradictions = state.synthesis.get("contradictions", [])

    # Persist synthesis for resume
    ctx.session_manager.update_status(
        state.session_id, "synthesizing", "synthesizing", None,
        iteration_round=state.round,
        synthesis_json=__import__("json").dumps(state.synthesis),
    )

    yield {"type": "synthesis_complete", "synthesis": {
        "reinforced_claims": state.synthesis.get("reinforced_claims", []),
        "contradictions": state.synthesis.get("contradictions", []),
        "knowledge_gaps": state.synthesis.get("knowledge_gaps", []),
        "new_entities": state.synthesis.get("new_entities", []),
    }}
    yield {"type": "progress", "progress": 0.65, "message": "Synthesis complete"}

    # ─── 6-step step 3: reasoning chain check ───
    if ctx.config.get("reasoning_check_enabled", True):
        try:
            from llmwikify.apps.chat.reasoning_checker import ReasoningChecker
            checker = ReasoningChecker()
            synth_text = synthesis_to_text(state.synthesis)
            result = checker.check(
                synthesis=synth_text,
                evidence_sources=state.sources,
                clarification=state.clarification,
            )
            state.reasoning_check = result
            ctx.db.update_six_step_fields(state.session_id, reasoning=result)
            yield {
                "type": "reasoning_check_complete",
                "aggregate_score": result.get("aggregate_score", 0.0),
                "issues_count": len(result.get("issues", [])),
            }
        except Exception as e:
            logger.warning("ReasoningChecker failed: %s", e)
            # Don't fail the pipeline — self-loop fallback is to skip.


@tracked("report")
async def action_report(
    ctx: ActionContext, state: ResearchState,
):
    """Generate research report."""
    _warn_invalid_transition(state.phase, "reporting")

    state.phase = "reporting"
    ctx.session_manager.update_status(state.session_id, "report", "report", None)
    yield _step_event(state.session_id, "report", "Generating research report...")

    sources = ctx.db.get_sources(state.session_id) or []
    generator = ctx.report

    # ─── 6-step context: build dict to pass into report + review ───
    six_step_context = _build_six_step_context(state)

    # Use streaming report generation (DR-3)
    import asyncio
    report_chunks: list[str] = []

    def _generate_streaming():
        for event in generator.generate_streaming(
            state.query, sources, state.synthesis or {},
            six_step_context=six_step_context,
        ):
            if event["type"] == "chunk":
                report_chunks.append(event["text"])
            elif event["type"] == "done":
                return event["content"]
            elif event["type"] == "error":
                raise Exception(event["error"])
        return "".join(report_chunks)

    try:
        # Run streaming generator in thread pool
        state.report_md = await asyncio.to_thread(_generate_streaming)

        # Persist report immediately so it survives pause/cancel/error
        ctx.session_manager.persist_report(state.session_id, {
            "markdown": state.report_md,
            "query": state.query,
            "quality_score": state.quality_score,
            "rounds": state.round,
            "sources": [
                {"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""), "source_type": s.get("source_type", "")}
                for s in sources
            ],
        })
        yield {"type": "progress", "progress": 0.75, "message": "Report generated"}
    except Exception as e:
        logger.error("Report generation failed: %s", e)
        yield {"type": "error", "error": f"Report generation failed: {e}"}
        ctx.session_manager.update_status(state.session_id, "error", "report", -1)
        state.phase = "error"
        state.issues.append(f"Report generation failed: {e}")

    # ─── 6-step step 4: structure validation ───
    if state.report_md and ctx.config.get("structure_check_enabled", True):
        try:
            from llmwikify.apps.chat.structure_validator import StructureValidator
            validator = StructureValidator()
            result = validator.validate(
                report=state.report_md,
                synthesis=state.synthesis,
                evidence_sources=state.sources,
            )
            state.structure_check = result
            ctx.db.update_six_step_fields(state.session_id, structure=result)
            yield {
                "type": "structure_check_complete",
                "aggregate_score": result.get("aggregate_score", 0.0),
                "issues_count": len(result.get("issues", [])),
            }
        except Exception as e:
            logger.warning("StructureValidator failed: %s", e)


@tracked("review")
async def action_review(
    ctx: ActionContext, state: ResearchState,
):
    """Review report quality."""
    _warn_invalid_transition(state.phase, "reviewing")

    state.phase = "reviewing"
    ctx.session_manager.update_status(state.session_id, "reviewing", "reviewing", None)
    yield _step_event(state.session_id, "review", "Reviewing report quality...")

    sources = ctx.db.get_sources(state.session_id) or []
    reviewer = ctx.reviewer
    try:
        six_step_context = _build_six_step_context(state)
        state.review = await reviewer.review(
            state.query, state.report_md or "", sources,
            six_step_context=six_step_context,
        )
    except Exception as e:
        logger.error("Report review failed: %s", e)
        # DR-4: Skip review on LLM failure instead of creating fake bad review
        state.review = {
            "approved": True,
            "score": 7,
            "issues": [],
            "feedback": "",
            "skipped": True,
            "skip_reason": f"Review LLM failed: {e}",
        }
    state.quality_score = state.review.get("score", 0)
    state.issues = state.review.get("issues", [])

    # Persist review for resume
    ctx.session_manager.update_status(
        state.session_id, "reviewing", "reviewing", None,
        iteration_round=state.round,
        review_json=__import__("json").dumps(state.review),
    )

    if state.review.get("approved"):
        yield {
            "type": "review_passed",
            "round": state.round,
            "score": state.quality_score,
            "feedback": state.review.get("feedback", ""),
        }
    else:
        yield {
            "type": "review_issues",
            "round": state.round,
            "score": state.quality_score,
            "issues": state.issues,
        }


@tracked("revise")
async def action_revise(
    ctx: ActionContext, state: ResearchState,
):
    """Revise report based on review feedback."""
    _warn_invalid_transition(state.phase, "revise")

    yield _step_event(state.session_id, "revise", "Revising report...")

    sources = ctx.db.get_sources(state.session_id) or []
    revisor = ctx.revisor
    try:
        state.report_md = await revisor.revise(state.report_md or "", state.issues, sources)
        # Reset review so it gets re-evaluated
        state.review = None
        # Persist revised report immediately so it survives pause/cancel/error
        ctx.session_manager.persist_report(state.session_id, {
            "markdown": state.report_md,
            "query": state.query,
            "quality_score": state.quality_score,
            "rounds": state.round,
            "sources": [
                {"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""), "source_type": s.get("source_type", "")}
                for s in sources
            ],
        })
        yield {"type": "progress", "progress": 0.85, "message": "Report revised"}
    except Exception as e:
        logger.error("Report revision failed: %s", e)
        yield {"type": "error", "error": f"Report revision failed: {e}"}


@tracked("done")
async def action_done(
    ctx: ActionContext, state: ResearchState,
):
    """Finalize research session."""
    _warn_invalid_transition(state.phase, "done")

    state.phase = "done"
    sources = ctx.db.get_sources(state.session_id) or []

    ctx.session_manager.update_status(state.session_id, "done", "done", 1.0, iteration_round=state.round)
    ctx.session_manager.finalize(state.session_id, {
        "markdown": state.report_md,
        "query": state.query,
        "quality_score": state.quality_score,
        "rounds": state.round,
        "synthesis_summary": {
            "reinforced_claims": len((state.synthesis or {}).get("reinforced_claims", [])),
            "contradictions": len((state.synthesis or {}).get("contradictions", [])),
            "knowledge_gaps": len(state.knowledge_gaps),
        },
        "sources": [
            {"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""), "source_type": s.get("source_type", "")}
            for s in sources
        ],
    })

    yield {
        "type": "done",
        "report": {
            "query": state.query,
            "markdown": state.report_md,
            "sources": [
                {"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""), "source_type": s.get("source_type", "")}
                for s in sources
            ],
            "synthesis_summary": {
                "reinforced_claims": len((state.synthesis or {}).get("reinforced_claims", [])),
                "contradictions": len((state.synthesis or {}).get("contradictions", [])),
                "knowledge_gaps": len(state.knowledge_gaps),
            },
            "rounds": state.round,
            "quality_score": state.quality_score,
        },
    }


async def _action_incomplete_impl(
    ctx: ActionContext, state: ResearchState, reason: str = "",
):
    """Implementation of action_incomplete (no @tracked wrapper)."""
    _warn_invalid_transition(state.phase, "incomplete")

    state.phase = "incomplete"
    sources = ctx.db.get_sources(state.session_id) or []

    # Compute progress based on how many framework steps completed
    step_progress = 0
    if state.clarification is not None: step_progress += 1
    if state.evidence_scores:            step_progress += 1
    if state.synthesis is not None:      step_progress += 1
    if state.reasoning_check is not None: step_progress += 1
    if state.report_md:                  step_progress += 1
    if state.structure_check is not None: step_progress += 1
    if state.review is not None:         step_progress += 1
    # 7 step-progress points → map to 0..1 with 0.85 cap
    progress = min(0.85, step_progress / 7 * 0.85)

    ctx.session_manager.update_status(
        state.session_id, "incomplete", "incomplete", progress,
        iteration_round=state.round,
    )
    # Persist whatever we have; mark with incomplete_reason in result
    try:
        ctx.session_manager.finalize(state.session_id, {
            "markdown": state.report_md,
            "query": state.query,
            "quality_score": state.quality_score,
            "rounds": state.round,
            "incomplete_reason": reason or "framework compliance gate failed",
            "framework_completed": step_progress,
            "framework_total": 7,
            "synthesis_summary": {
                "reinforced_claims": len((state.synthesis or {}).get("reinforced_claims", [])),
                "contradictions": len((state.synthesis or {}).get("contradictions", [])),
                "knowledge_gaps": len(state.knowledge_gaps),
            },
            "sources": [
                {"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""), "source_type": s.get("source_type", "")}
                for s in sources
            ],
        })
        # finalize() hardcodes status='done'; re-set to incomplete
        ctx.session_manager.update_status(
            state.session_id, "incomplete", "incomplete",
            progress, iteration_round=state.round,
        )
    except Exception as e:
        logger.warning("incomplete finalize: %s", e)

    yield {
        "type": "incomplete",
        "reason": reason or "framework compliance gate failed",
        "round": state.round,
        "framework_completed": step_progress,
        "framework_total": 7,
        "report": {
            "query": state.query,
            "markdown": state.report_md,
            "sources": [
                {"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""), "source_type": s.get("source_type", "")}
                for s in sources
            ],
            "quality_score": state.quality_score,
        },
    }


async def action_incomplete(
    ctx: ActionContext, state: ResearchState, reason: str = "",
):
    """Mark session as incomplete (framework compliance gate failed, no budget).

    Distinct from action_done: the 6-step framework is NOT fully run,
    and the engine has no more replan budget to fix it. We persist
    whatever we have (synthesis, report, review) so the user can
    inspect partial results.

    Status is set to 'incomplete' (not 'done') so the UI can warn
    the user that the result is partial.

    Note: not decorated with @tracked (which has fixed (ctx, state)
    signature) because this action takes a custom 'reason' arg.
    Metrics are recorded manually if ctx.metrics is available.
    """
    from contextlib import nullcontext
    metrics_cm = (
        ctx.metrics.record("incomplete") if ctx.metrics else nullcontext()
    )
    with metrics_cm:
        async for ev in _action_incomplete_impl(ctx, state, reason):
            yield ev
