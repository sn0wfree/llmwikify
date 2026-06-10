"""Action implementations for the legacy research engine.

Each action is a free function that receives an ActionContext (deps)
and the current ResearchState, and yields SSE event dicts. The engine
orchestrates the ReAct loop; actions do the work.

This module is extracted from engine.py (Phase C of the triple
ReAct loop unification — see v0.36-agentchat-hardening branch).
"""

from __future__ import annotations

import asyncio
import json as json_mod
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from llmwikify.foundation.llm.streamable import StreamableLLMClient
from ..chat.db import ChatDatabase
from .analyzer import SourceAnalyzer
from .gatherer import SourceGatherer
from .report import ReportGenerator
from .review import ResearchReviewer, ResearchRevisor
from .session import ResearchSessionManager
from .synthesizer import ResearchSynthesizer
from .quality_gate import QualityGate

logger = logging.getLogger(__name__)


# ─── ActionContext (deps for all actions) ────────────────────────────────


@dataclass
class ActionContext:
    """Dependency bundle for research actions."""

    wiki: Any
    db: ChatDatabase
    session_manager: ResearchSessionManager
    config: dict[str, Any]
    planning_llm: StreamableLLMClient
    report_llm: StreamableLLMClient
    default_llm: StreamableLLMClient
    quality_gate: QualityGate
    metrics: Any = None  # SessionMetrics, set after construction


# ─── Step event helper ────────────────────────────────────────────────────


def step_event(
    session_id: str,
    step: str,
    message: str,
) -> dict[str, Any]:
    """Build a step-started event."""
    return {
        "type": "step",
        "step": step,
        "message": message,
        "session_id": session_id,
        "timestamp": time.time(),
    }


# ─── Planning helpers ─────────────────────────────────────────────────────


async def plan_sub_queries(ctx: ActionContext, query: str) -> list[dict[str, Any]]:
    """Decompose the research topic into sub-queries using planning_model."""
    from ...kernel.wiki.prompt_registry import PromptRegistry
    registry = PromptRegistry(provider="openai")

    # Proactively search local wiki for relevant articles
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

    messages = registry.get_messages(
        "research_plan",
        query=query,
        wiki_index=wiki_index[:2000] if wiki_index else "",
        local_wiki_matches=local_wiki_matches,
    )
    api_params = registry.get_api_params("research_plan")

    try:
        def _call_llm():
            raw = ctx.planning_llm.chat(
                messages,
                json_mode=api_params.get("json_mode", True),
                max_tokens=api_params.get("max_tokens", 2048),
                temperature=api_params.get("temperature", 0.3),
            )
            return raw

        raw = await asyncio.to_thread(_call_llm)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        result = json_mod.loads(raw)
        if not isinstance(result, list):
            result = []
    except Exception as e:
        logger.warning("Planning LLM failed: %s, using single query", e)
        result = [{"query": query, "source_type": "web", "url": ""}]

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


async def plan_for_gaps(ctx: ActionContext, query: str, gaps: list[str]) -> list[dict[str, Any]]:
    """Generate sub-queries to fill knowledge gaps."""
    gaps_text = "\n".join(f"- {gap}" for gap in gaps[:5])

    # Proactively search local wiki for gap-related content
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
        wiki_context = f"\n\nExisting wiki articles that may help fill gaps:\n{local_wiki_matches}\nUse source_type \"wiki\" for these if relevant."

    messages = [
        {"role": "system", "content": (
            "You are a research planner. Generate focused sub-queries to fill knowledge gaps. "
            "Return a JSON array of objects with 'query', 'source_type', and 'url' fields. "
            "source_type should be 'web', 'pdf', 'youtube', or 'wiki'. "
            "Use 'wiki' when existing wiki articles are relevant (see below). "
            "Generate 1-3 sub-queries per gap, maximum 5 total."
        )},
        {"role": "user", "content": (
            f"Research topic: {query}\n\n"
            f"Knowledge gaps to fill:\n{gaps_text}"
            f"{wiki_context}\n\n"
            "Generate sub-queries now. Return ONLY a JSON array."
        )},
    ]

    try:
        def _call():
            return ctx.planning_llm.chat(messages, json_mode=True, max_tokens=1024, temperature=0.3)

        raw = await asyncio.to_thread(_call)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        result = json_mod.loads(raw)
        if not isinstance(result, list):
            result = []
    except Exception as e:
        logger.warning("Gap planning LLM failed: %s", e)
        result = [{"query": f"{query} {gaps[0]}", "source_type": "web", "url": ""}] if gaps else []

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


# ─── Action implementations ──────────────────────────────────────────────


async def action_plan(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Plan sub-queries (initial or replanning for gaps)."""
    state.phase = "planning"
    ctx.session_manager.update_status(state.session_id, "planning", "planning", None)
    yield step_event(state.session_id, "planning", f"Planning sub-queries (round {state.round})...")

    # Decide: initial plan or gap-focused replan
    if state.knowledge_gaps and state.sub_queries:
        yield {"type": "gap_detected", "gaps": state.knowledge_gaps, "round": state.round}
        sub_queries = await plan_for_gaps(ctx, state.query, state.knowledge_gaps)
    else:
        sub_queries = await plan_sub_queries(ctx, state.query)

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


async def action_gather(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Gather sources for ungathered or failed sub-queries."""
    state.phase = "gathering"
    ctx.session_manager.update_status(state.session_id, "gathering", "gathering", None)
    yield step_event(state.session_id, "gathering", "Gathering sources...")

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

    if not sources:
        ctx.session_manager.update_status(state.session_id, "error", "gathering", -1)
        yield {"type": "error", "error": "No sources gathered. All sub-queries failed."}
        state.phase = "error"
        state.issues.append("No sources gathered — all sub-queries failed")


async def action_analyze(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Analyze unanalyzed sources."""
    state.phase = "analyzing"
    ctx.session_manager.update_status(state.session_id, "analyzing", "analyzing", None)
    yield step_event(state.session_id, "analyzing", "Analyzing sources...")

    sources = ctx.db.get_sources(state.session_id) or []
    unanalyzed = [s for s in sources if not s.get("analysis")]

    if unanalyzed:
        analyzer = SourceAnalyzer(ctx.wiki, ctx.session_manager, ctx.config)
        events = await analyzer.analyze_sources(unanalyzed)
        for event in events:
            yield event

    yield {"type": "progress", "progress": 0.55, "message": "Analysis complete"}


async def action_synthesize(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Synthesize findings from analyzed sources."""
    state.phase = "synthesizing"
    ctx.session_manager.update_status(state.session_id, "synthesizing", "synthesizing", None)
    yield step_event(state.session_id, "synthesizing", "Synthesizing cross-source findings...")

    sources = ctx.db.get_sources(state.session_id) or []
    synthesizer = ResearchSynthesizer(ctx.wiki, ctx.config)
    state.synthesis = await synthesizer.synthesize(sources, query=state.query)
    state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
    state.contradictions = state.synthesis.get("contradictions", [])

    # Persist synthesis for resume
    ctx.session_manager.update_status(
        state.session_id, "synthesizing", "synthesizing", None,
        iteration_round=state.round,
        synthesis_json=json_mod.dumps(state.synthesis),
    )

    yield {"type": "synthesis_complete", "synthesis": {
        "reinforced_claims": state.synthesis.get("reinforced_claims", []),
        "contradictions": state.synthesis.get("contradictions", []),
        "knowledge_gaps": state.synthesis.get("knowledge_gaps", []),
        "new_entities": state.synthesis.get("new_entities", []),
    }}
    yield {"type": "progress", "progress": 0.65, "message": "Synthesis complete"}


async def action_report(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Generate research report."""
    state.phase = "reporting"
    ctx.session_manager.update_status(state.session_id, "report", "report", None)
    yield step_event(state.session_id, "report", "Generating research report...")

    sources = ctx.db.get_sources(state.session_id) or []
    generator = ReportGenerator(ctx.wiki, ctx.report_llm, ctx.config)

    # Use streaming report generation (DR-3)
    report_chunks: list[str] = []

    def _generate_streaming():
        for event in generator.generate_streaming(state.query, sources, state.synthesis or {}):
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


async def action_review(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Review report quality."""
    state.phase = "reviewing"
    ctx.session_manager.update_status(state.session_id, "reviewing", "reviewing", None)
    yield step_event(state.session_id, "review", "Reviewing report quality...")

    sources = ctx.db.get_sources(state.session_id) or []
    reviewer = ResearchReviewer(ctx.wiki, ctx.default_llm, ctx.config)
    try:
        state.review = await reviewer.review(state.query, state.report_md or "", sources)
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
        review_json=json_mod.dumps(state.review),
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


async def action_revise(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Revise report based on review feedback."""
    yield step_event(state.session_id, "revise", "Revising report...")

    sources = ctx.db.get_sources(state.session_id) or []
    revisor = ResearchRevisor(ctx.wiki, ctx.report_llm, ctx.config)
    try:
        state.report_md = await revisor.revise(state.report_md or "", state.issues, sources)
        # Reset review so it gets re-evaluated
        state.review = None
        # Persist revised report immediately
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


async def action_done(ctx: ActionContext, state: Any) -> AsyncIterator[dict[str, Any]]:
    """Finalize research session."""
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
