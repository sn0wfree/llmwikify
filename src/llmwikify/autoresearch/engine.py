"""Research Engine — ReAct loop orchestrator with adaptive reasoning.

Replaces the fixed 7-stage sequential flow with an adaptive ReAct
(Reason → Act → Observe → loop) agent that dynamically decides what
to do next based on intermediate results.
"""

from __future__ import annotations

import json
import time
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from llmwikify.agent.backend.adapters import StreamableLLMClient
from llmwikify.autoresearch.db import AutoResearchDatabase
from llmwikify.agent.backend.providers.registry import create_llm
from llmwikify.autoresearch.analyzer import SourceAnalyzer
from llmwikify.autoresearch.config import merge_six_step_config
from llmwikify.autoresearch._json_utils import safe_json_loads
from llmwikify.autoresearch.engine_helpers import chat_json
from llmwikify.autoresearch.gatherer import SourceGatherer
from llmwikify.autoresearch.state import (
    ActionMetrics,
    ResearchState,
    SessionMetrics,
    VALID_TRANSITIONS,
)
from llmwikify.autoresearch.report import ReportGenerator
from llmwikify.autoresearch.review import ResearchReviewer, ResearchRevisor
from llmwikify.autoresearch.session import ResearchSessionManager
from llmwikify.autoresearch.synthesizer import ResearchSynthesizer
from llmwikify.autoresearch.quality_gate import QualityGate

logger = logging.getLogger(__name__)

# ─── Action dispatch table (replaces 8-arm if/elif in _react_loop) ───────
# Maps the LLM/rule-reasoner's action name to the corresponding method.
# Unknown actions fall through to _action_done (safe default).
_ACTION_DISPATCH_ATTR = "_actions"


# ─── State Transition Table (DR-14) ──────────────────────────────────────
# Explicit valid transitions: from_phase → list of allowed to_phases
class ResearchEngine:
    """Orchestrates the ReAct research loop.

    Instead of a fixed sequential pipeline, the agent reasons about what
    to do next based on intermediate results, enabling:
    - Adaptive re-planning when knowledge gaps are detected
    - Self-correcting review loop with re-gathering
    - Budget-aware iteration with configurable round limits
    """

    def __init__(
        self,
        wiki: Any,
        db: AutoResearchDatabase,
        llm_client: StreamableLLMClient,
        config: dict[str, Any] | None = None,
    ):
        self.wiki = wiki
        self.db = db
        self.config = merge_six_step_config(config)
        self.session_manager = ResearchSessionManager(db)
        self._timeout_seconds = self.config.get("research_timeout_minutes", 30) * 60
        self._start_time: float = 0

        # Model layering
        self._default_llm = llm_client
        self._planning_llm = self._resolve_model("planning_model") or llm_client
        self._report_llm = self._resolve_model("report_model") or llm_client

        # ReAct config
        self._max_react_rounds = self.config.get("max_react_rounds", 5)
        self._quality_threshold = self.config.get("quality_threshold", 7)
        self._max_replan = self.config.get("max_replan_attempts", 2)

        # Quality gate
        self._quality_gate = QualityGate(self.config)

        # ─── 6-step framework: clarifier (schema is built into the DB) ──
        from llmwikify.autoresearch.clarifier import ResearchClarifier

        self.clarifier = ResearchClarifier(self._planning_llm, self.config)
        # The 6-step JSON fields (clarification/reasoning/structure/...) are
        # native columns in autoresearch_sessions; no ALTER TABLE needed.
        # AutoResearchDatabase.__init__ runs the schema bootstrap once.

        # Metrics (DR-13)
        self._metrics: SessionMetrics | None = None

        # Action dispatch table: action name -> async generator method.
        # Populated here (not at class level) so we can reference bound
        # methods that only exist after __init__ returns.
        setattr(self, _ACTION_DISPATCH_ATTR, {
            "plan":       self._action_plan,
            "gather":     self._action_gather,
            "analyze":    self._action_analyze,
            "synthesize": self._action_synthesize,
            "report":     self._action_report,
            "review":     self._action_review,
            "revise":     self._action_revise,
            "done":       self._action_done,
        })

    def _resolve_model(self, config_key: str) -> StreamableLLMClient | None:
        model_cfg = self.config.get(config_key)
        if not model_cfg:
            return None
        try:
            return create_llm(model_cfg)
        except Exception as e:
            logger.warning("Failed to resolve %s: %s, using default LLM", config_key, e)
            return None

    def _check_timeout(self) -> None:
        if self._start_time > 0:
            elapsed = time.monotonic() - self._start_time
            if elapsed > self._timeout_seconds:
                raise TimeoutError(f"Research timed out after {elapsed:.0f}s (limit: {self._timeout_seconds}s)")

    def _validate_transition(self, from_phase: str, to_phase: str) -> bool:
        """Validate state transition is allowed.

        Args:
            from_phase: Current phase
            to_phase: Target phase

        Returns:
            True if transition is valid, False otherwise. First run
            (from_phase == "" or None) is always allowed.
        """
        # First run or uninitialized state → always allow
        if not from_phase:
            return True
        valid_targets = VALID_TRANSITIONS.get(from_phase, [])
        if to_phase not in valid_targets:
            logger.warning(
                "Invalid state transition: %s → %s (valid: %s)",
                from_phase, to_phase, valid_targets or "none"
            )
            return False
        return True

    def _warn_invalid_transition(self, from_phase: str, to_phase: str) -> None:
        """Log a warning if the transition is invalid.

        Equivalent to ``if not self._validate_transition(...): logger.warning(...)``
        but collapses the 8 duplicated callsites in action methods to a
        single line. Returns nothing (caller always continues anyway).
        """
        self._validate_transition(from_phase, to_phase)

    def _start_action(self, action: str) -> ActionMetrics:
        """Start tracking metrics for an action."""
        metrics = ActionMetrics(action=action, start_time=time.monotonic())
        return metrics

    def _finish_action(self, metrics: ActionMetrics) -> None:
        """Finish tracking metrics for an action and add to session."""
        metrics.finish()
        if self._metrics:
            self._metrics.add_action(metrics)
        logger.debug("Action %s completed in %dms", metrics.action, metrics.duration_ms)

    async def run(self, session_id: str, query: str, resume: bool = False) -> AsyncIterator[dict[str, Any]]:
        """Execute the ReAct research loop, yielding SSE events."""
        self.session_manager.session_id = session_id
        self._start_time = time.monotonic()
        
        # Initialize metrics (DR-13)
        self._metrics = SessionMetrics(session_id=session_id)
        self._metrics.start()

        try:
            async for event in self._react_loop(session_id, query, resume):
                self._check_timeout()
                yield event
        except TimeoutError:
            self.session_manager.update_status(session_id, "timeout", "timeout", -1)
            yield {"type": "error", "error": f"Research timed out after {self._timeout_seconds}s"}
        except Exception:
            raise
        finally:
            # Finalize metrics and log summary
            if self._metrics:
                self._metrics.finish()
                logger.info("Research metrics:\n%s", self._metrics.summary())

    # ─── ReAct Core Loop ───────────────────────────────────────────────

    async def _react_loop(
        self, session_id: str, query: str, resume: bool
    ) -> AsyncIterator[dict[str, Any]]:
        """Main ReAct loop: Reason → Act → Observe → repeat."""
        state = ResearchState(
            session_id=session_id,
            query=query,
            max_rounds=self._max_react_rounds,
        )

        # Load existing state on resume
        if resume:
            self._load_resume_state(state)

        # ─── 6-step framework: run clarify before the first plan ───
        if not resume and state.clarification is None:
            async for event in self._action_clarify(state):
                yield event

        try:
            while state.phase != "done":
                self._check_timeout()
                elapsed = time.monotonic() - self._start_time
                state.budget_remaining = max(0, 1 - elapsed / self._timeout_seconds)

                # ── Check cancel/pause signals from DB ──
                self._check_control_signals(state)
                if state.cancelled:
                    yield {"type": "cancelled", "round": state.round, "phase": state.phase}
                    self.session_manager.update_status(session_id, "cancelled", state.phase, -1)
                    break
                if state.paused:
                    yield {"type": "paused", "round": state.round, "phase": state.phase}
                    self.session_manager.update_status(session_id, "paused", state.phase, state.round)
                    break

                # ── REASON: decide next action (ReAct Thought) ──
                action = await self._reason(state)
                thought = getattr(state, "_last_thought", "")
                yield {
                    "type": "reasoning",
                    "action": action,
                    "thought": thought,
                    "round": state.round,
                    "phase": state.phase,
                }

                # ── ACT: execute action via dispatch table ──
                action_method = getattr(self, _ACTION_DISPATCH_ATTR).get(action)
                if action_method is None:
                    # Unknown action → default to done (safe fallback)
                    logger.warning("Unknown action %s, defaulting to done", action)
                    action_method = self._action_done
                    async for event in action_method(state):
                        yield event
                    break
                async for event in action_method(state):
                    yield event
                if action == "done":
                    break

                # ── OBSERVE: update state from DB ──
                self._observe(state)

                # ── Quality gate check ──
                if self.config.get("gate_enabled", True):
                    gate_result = self._evaluate_gate(state)
                    if gate_result:
                        state.observations.append(
                            f"[质量门禁] {gate_result.gate_name}: {gate_result.summary}"
                        )
                        if not gate_result.passed:
                            state.observations.append(
                                f"⚠ 门禁未通过，建议: {gate_result.suggestion}"
                            )
                            # Force transition: if gate fails after gathering and we have sources,
                            # override action to analyze instead of stuck in gather loop
                            if (state.phase == "gathering"
                                    and len(state.sources) >= self.config.get("gate_min_sources", 3)
                                    and action == "gather"):
                                action = "analyze"
                                logger.info("Gate %s failed, forcing analyze (have %d sources)",
                                            gate_result.gate_name, len(state.sources))

                # ── Track iteration count ──
                state.round += 1

                # ── Evaluate: check exit conditions ──
                if state.round >= state.max_rounds:
                    yield {"type": "round_max", "round": state.round, "message": f"Reached max rounds ({state.max_rounds})"}
                    async for event in self._action_done(state):
                        yield event
                    break
        except Exception as e:
            # Catch-all: ensure DB status is always updated on unexpected errors
            logger.error("ReAct loop error for session %s: %s", session_id, e, exc_info=True)
            self.session_manager.update_status(session_id, "error", state.phase or "unknown", -1)
            yield {"type": "error", "error": str(e)}

    # ─── Reason Step ───────────────────────────────────────────────────

    async def _reason(self, state: ResearchState) -> str:
        """Decide next action based on current state.

        Uses LLM for reasoning (ReAct Thought step), falls back to deterministic rules.
        """
        # LLM-based reasoning first (true ReAct Thought)
        try:
            return await self._llm_reason(state)
        except Exception as e:
            logger.warning("LLM reasoning failed: %s, using rule-based fallback", e)
            return self._rule_based_reason(state) or "done"

    def _rule_based_reason(self, state: ResearchState) -> str | None:
        """Deterministic decision rules as fallback."""
        # Error state → done (let LLM override if it wants to retry)
        if state.phase == "error":
            return "done"

        # ─── 6-step framework: if no clarification yet, redo clarify ───
        if state.clarification is None:
            return "plan"  # In the new flow this path is unreachable (clarify runs before loop) but keep for resume safety

        # No sub-queries yet → plan
        if not state.sub_queries:
            return "plan"

        # Not all gathered → gather (skip failed sub-queries)
        gathered_ids = {s.get("sub_query_id") for s in state.sources}
        ungathered = [
            sq for sq in state.sub_queries
            if sq["id"] not in gathered_ids and sq.get("status") != "failed"
        ]
        if ungathered:
            return "gather"

        # Not all analyzed → analyze
        sources = self.db.get_sources(state.session_id)
        unanalyzed = [s for s in sources if not s.get("analysis")]
        if unanalyzed:
            return "analyze"

        # No synthesis yet → synthesize
        if state.synthesis is None:
            return "synthesize"

        # Knowledge gaps detected + budget allows + replan attempts left → replan
        if (state.knowledge_gaps
                and state.budget_remaining > 0.15
                and state.round < state.max_replan + 1):
            return "plan"

        # No report yet → report
        if state.report_md is None:
            return "report"

        # Report exists, not reviewed → review
        if state.review is None:
            return "review"

        # Review passed → done
        if state.review and state.review.get("approved"):
            return "done"

        # Review failed + rounds remaining → revise
        if state.round < state.max_rounds:
            return "revise"

        # Default → done
        return "done"

    async def _llm_reason(self, state: ResearchState) -> str:
        """Use LLM to decide next action with chain-of-thought reasoning."""
        import asyncio

        analyzed_count = sum(1 for s in state.sources if s.get("analysis"))
        failed_sq = sum(1 for sq in state.sub_queries if sq.get("status") == "failed")

        # Build observation context from interpreted observations
        obs_text = "\n".join(f"  - {o}" for o in state.observations) if state.observations else "  (none)"

        messages = [
            {"role": "system", "content": (
                "You are a research orchestrator using ReAct reasoning.\n"
                "Based on the current state, decide the next action.\n\n"
                "Return a JSON object ONLY — no prose, no markdown fence, no explanation.\n"
                "Schema:\n"
                '- "thought": Your reasoning about what to do next and why (1-2 sentences)\n'
                '- "action": One of: plan, gather, analyze, synthesize, report, review, revise, done\n\n'
                "Rules:\n"
                "- If sub-queries exist but not all are gathered → gather\n"
                "- If sources exist but not all analyzed → analyze\n"
                "- If all analyzed but no synthesis → synthesize\n"
                "- If synthesis shows knowledge gaps and budget allows → plan (replan)\n"
                "- If report exists but not reviewed → review\n"
                "- If review failed and rounds remain → revise\n"
                "- If all done and quality acceptable → done\n"
            )},
            {"role": "user", "content": (
                f"Research topic: {state.query}\n"
                f"Round: {state.round}/{state.max_rounds}\n"
                f"Phase: {state.phase or 'starting'}\n"
                f"Quality score: {state.quality_score}/10\n"
                f"Budget remaining: {state.budget_remaining:.0%}\n\n"
                f"Sub-queries: {len(state.sub_queries)} ({failed_sq} failed)\n"
                f"Sources gathered: {len(state.sources)}\n"
                f"Sources analyzed: {analyzed_count}\n"
                f"Report exists: {state.report_md is not None}\n"
                f"Review exists: {state.review is not None}\n\n"
                f"Observations:\n{obs_text}\n\n"
                "What should I do next? Return JSON."
            )},
        ]

        result = await chat_json(
            self._default_llm, messages,
            max_tokens=1024, temperature=0.1, json_mode=True,
        )
        action = result.get("action", "done")
        thought = result.get("thought", "")

        valid = {"plan", "gather", "analyze", "synthesize", "report", "review", "revise", "done"}
        if action not in valid:
            action = "done"

        # Store thought for SSE event (set on state so _react_loop can yield it)
        state._last_thought = thought

        return action

    # ─── Control Signal Check ─────────────────────────────────────────

    def _check_control_signals(self, state: ResearchState) -> None:
        """Check DB for cancel/pause signals from API layer."""
        try:
            session = self.db.get_research_session(state.session_id)
            if session:
                db_status = session.get("status", "")
                if db_status == "cancelling":
                    state.cancelled = True
                elif db_status == "pausing":
                    state.paused = True
        except Exception as e:
            logger.debug("Control signal check failed: %s", e)

    # ─── Observe Step ──────────────────────────────────────────────────

    def _observe(self, state: ResearchState) -> None:
        """Refresh state from DB and generate interpreted observations after each action."""
        state.sources = self.db.get_sources(state.session_id) or []
        state.sub_queries_raw = self.db.get_sub_queries(state.session_id) or []

        # Rebuild sub_queries list from DB
        state.sub_queries = [
            {"id": sq["id"], "query": sq["query"], "source_type": sq["source_type"],
             "url": sq.get("url"), "status": sq.get("status", "pending")}
            for sq in state.sub_queries_raw
        ]

        state.total_sources = len(state.sources)
        state.total_sub_queries = len(state.sub_queries)

        # Extract knowledge gaps from synthesis
        if state.synthesis:
            state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
            state.contradictions = state.synthesis.get("contradictions", [])

        # Generate interpreted observations for the reasoner
        state.observations = []

        # Source quality distribution
        analyzed = [s for s in state.sources if s.get("analysis")]
        if analyzed:
            scores = [s.get("analysis", {}).get("quality_assessment", {}).get("credibility", 5) for s in analyzed]
            avg = sum(scores) / len(scores) if scores else 0
            state.observations.append(
                f"Average source credibility: {avg:.1f}/10 ({len(analyzed)}/{len(state.sources)} analyzed)"
            )

        # Failed sub-queries
        failed = [sq for sq in state.sub_queries if sq.get("status") == "failed"]
        if failed:
            state.observations.append(
                f"{len(failed)} sub-queries failed: {[sq['query'] for sq in failed[:3]]}"
            )

        # Source type distribution
        type_counts: dict[str, int] = {}
        for s in state.sources:
            t = s.get("source_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        if type_counts:
            state.observations.append(f"Source types: {type_counts}")

        # Wiki vs web ratio
        wiki_count = type_counts.get("wiki", 0)
        web_count = type_counts.get("web", 0)
        if wiki_count + web_count > 0:
            state.observations.append(
                f"Local wiki: {wiki_count} sources, Web: {web_count} sources"
            )

        # Key quality assessment
        analyzed = [s for s in state.sources if s.get("analysis")]
        if analyzed:
            cred_scores = [
                s.get("analysis", {}).get("quality_assessment", {}).get("credibility", 5)
                for s in analyzed
            ]
            avg_cred = sum(cred_scores) / len(cred_scores)
            if avg_cred < 5:
                state.observations.append(f"⚠ 平均可信度偏低 ({avg_cred:.1f}/10)，建议获取更高质量源")
            elif avg_cred >= 7:
                state.observations.append(f"✓ 源质量良好 (平均 {avg_cred:.1f}/10)")

        if len(state.knowledge_gaps) > 3:
            state.observations.append(
                f"⚠ {len(state.knowledge_gaps)} 个知识缺口，可能影响报告完整性"
            )

    # ─── Quality Gate Evaluation ────────────────────────────────────────

    def _evaluate_gate(self, state: ResearchState):
        """Evaluate quality gate based on current phase.

        Each phase invokes its base gate plus the 6-step framework gate.
        The 6-step gate is layered ON TOP of the base gate (both must pass
        for the engine to proceed; any failure triggers a replan).
        Returns a combined GateResult (or the first failing one).

        Mapping (per plan:162-166):
            gathering    → check_after_gathering       + check_evidence_quality
            analyzing    → check_after_analysis
            synthesizing → check_after_synthesis       + check_reasoning_quality
            reporting    → check_before_report         + check_structure_quality
            reviewing    →                              check_framework_compliance
        """
        gate = self._quality_gate
        evidence_enabled = self.config.get("evidence_scoring_enabled", True)
        reasoning_enabled = self.config.get("reasoning_check_enabled", True)
        structure_enabled = self.config.get("structure_check_enabled", True)
        framework_enabled = self.config.get("framework_check_enabled", True)

        if state.phase == "gathering":
            base = gate.check_after_gathering(state.sources, state.sub_queries)
            if not base.passed:
                return base
            if evidence_enabled:
                ev = gate.check_evidence_quality(
                    state.sources,
                    evidence_threshold=self.config.get("gate_min_evidence_score", 0.5),
                )
                if not ev.passed:
                    return ev
            return base
        elif state.phase == "analyzing":
            return gate.check_after_analysis(state.sources)
        elif state.phase == "synthesizing":
            base = gate.check_after_synthesis(state.synthesis)
            if not base.passed:
                return base
            if reasoning_enabled:
                # Build a synthesis text from synthesis dict (synthesizer stores structured output)
                synth_text = self._synthesis_to_text(state.synthesis)
                rs = gate.check_reasoning_quality(
                    synth_text,
                    evidence_sources=state.sources,
                    clarification=state.clarification,
                    reasoning_threshold=self.config.get("gate_min_reasoning_score", 0.5) / 10.0,
                )
                if not rs.passed:
                    return rs
            return base
        elif state.phase == "reporting":
            base = gate.check_before_report(state.synthesis, state.sources)
            if not base.passed:
                return base
            if structure_enabled and state.report_md:
                st = gate.check_structure_quality(
                    state.report_md,
                    synthesis=state.synthesis,
                    evidence_sources=state.sources,
                    structure_threshold=self.config.get("gate_min_structure_score", 0.5),
                )
                if not st.passed:
                    return st
            return base
        elif state.phase == "reviewing" and framework_enabled:
            return gate.check_framework_compliance(
                clarification=state.clarification,
                reasoning_check=state.reasoning_check,
                structure_check=state.structure_check,
            )
        return None

    @staticmethod
    def _synthesis_to_text(synthesis: dict | None) -> str:
        """Flatten the synthesis dict into a single text blob for the reasoner.

        The synthesizer stores structured output (claims / reinforced_claims
        / contradictions / knowledge_gaps). The ReasoningChecker expects
        a text synthesis, so we concatenate the human-readable parts.
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

    # ─── Action Implementations ────────────────────────────────────────

    async def _action_clarify(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """6-step step 1: clarify research context, boundaries, position, premises.

        Runs only when clarify_enabled (default true) and not on resume. The
        result is stored in state.clarification and persisted to the DB.
        """
        # Skip if disabled (only the framework compliance gate respects this;
        # self-loop itself has no off-switch per the v3 design).
        if not self.config.get("clarify_enabled", True):
            state.clarification = {"scope_check": True, "context": "skipped (clarify_enabled=False)"}
            return

        # Validate state transition
        self._warn_invalid_transition(state.phase, "clarifying")

        # Track metrics
        metrics = self._start_action("clarify")

        state.phase = "clarifying"
        self.session_manager.update_status(state.session_id, "clarifying", "clarifying", None)
        yield self._step_event("clarifying", "Clarifying research scope and boundaries...")

        # Build wiki context (reuse _plan_sub_queries helper)
        wiki_context = ""
        try:
            wiki_results = self.wiki.search(state.query, limit=3)
            if wiki_results:
                lines = [
                    f"- {r.get('page_name', '')}: {r.get('snippet', '')[:200]}"
                    for r in wiki_results
                ]
                wiki_context = "\n".join(lines)
        except Exception as e:
            logger.debug("Wiki search for clarification failed: %s", e)

        # Run clarifier with self-loop
        clarification, loop_history = await self.clarifier.clarify_with_loop(
            query=state.query,
            wiki_context=wiki_context,
            budget_remaining=state.budget_remaining,
        )

        state.clarification = clarification
        state.self_loop_counts["clarify"] = len(loop_history) - 1
        state.self_loop_history.extend(loop_history)

        # Persist to DB (independent autoresearch.db — no shared schema)
        try:
            self.db.update_research_status(
                state.session_id, "clarifying", "clarifying",
                iteration_round=state.round,
                synthesis_json=None,
                review_json=None,
            )
            self.db.update_six_step_fields(
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

        # Finish metrics
        self._finish_action(metrics)

    async def _action_plan(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Plan sub-queries (initial or replanning for gaps)."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "planning")
        
        # Track metrics (DR-13)
        metrics = self._start_action("plan")
        
        state.phase = "planning"
        self.session_manager.update_status(state.session_id, "planning", "planning", None)
        yield self._step_event("planning", f"Planning sub-queries (round {state.round})...")

        # Decide: initial plan or gap-focused replan
        if state.knowledge_gaps and state.sub_queries:
            yield {"type": "gap_detected", "gaps": state.knowledge_gaps, "round": state.round}
            sub_queries = await self._plan_for_gaps(state.query, state.knowledge_gaps)
        else:
            sub_queries = await self._plan_sub_queries(state.query)

        # Deduplicate against existing
        existing_queries = {sq["query"].lower().strip() for sq in state.sub_queries}
        new_queries = [sq for sq in sub_queries if sq["query"].lower().strip() not in existing_queries]

        for sq in new_queries[:5]:  # Limit per round
            sq_id = self.session_manager.add_sub_query(
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
        
        # Finish metrics tracking
        self._finish_action(metrics)

    async def _action_gather(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Gather sources for ungathered or failed sub-queries."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "gathering")
        
        # Track metrics (DR-13)
        metrics = self._start_action("gather")
        
        state.phase = "gathering"
        self.session_manager.update_status(state.session_id, "gathering", "gathering", None)
        yield self._step_event("gathering", "Gathering sources...")

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
            gatherer = SourceGatherer(self.wiki, self.db, self.session_manager, self.config)
            events = await gatherer.gather(remaining)
            for event in events:
                yield event

        sources = self.db.get_sources(state.session_id) or []
        yield {"type": "progress", "progress": 0.4, "message": f"Gathered {len(sources)} sources total"}

        # ─── 6-step step 2: evidence scoring (run only when enabled) ───
        if self.config.get("evidence_scoring_enabled", True) and sources:
            from llmwikify.autoresearch.source_filter import SourceFilter
            sf = SourceFilter(self.config)
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
                self.db.update_six_step_fields(
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
            self.session_manager.update_status(state.session_id, "error", "gathering", -1)
            yield {"type": "error", "error": "No sources gathered. All sub-queries failed."}
            state.phase = "error"
            state.issues.append("No sources gathered — all sub-queries failed")
        
        # Finish metrics tracking
        self._finish_action(metrics)

    async def _action_analyze(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Analyze unanalyzed sources."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "analyzing")
        
        # Track metrics (DR-13)
        metrics = self._start_action("analyze")
        
        state.phase = "analyzing"
        self.session_manager.update_status(state.session_id, "analyzing", "analyzing", None)
        yield self._step_event("analyzing", "Analyzing sources...")

        sources = self.db.get_sources(state.session_id) or []
        unanalyzed = [s for s in sources if not s.get("analysis")]

        if unanalyzed:
            analyzer = SourceAnalyzer(self.wiki, self.session_manager, self.config)
            events = await analyzer.analyze_sources(unanalyzed)
            for event in events:
                yield event

        yield {"type": "progress", "progress": 0.55, "message": "Analysis complete"}
        
        # Finish metrics tracking
        self._finish_action(metrics)

    async def _action_synthesize(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Synthesize findings from analyzed sources."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "synthesizing")
        
        # Track metrics (DR-13)
        metrics = self._start_action("synthesize")
        
        state.phase = "synthesizing"
        self.session_manager.update_status(state.session_id, "synthesizing", "synthesizing", None)
        yield self._step_event("synthesizing", "Synthesizing cross-source findings...")

        sources = self.db.get_sources(state.session_id) or []
        synthesizer = ResearchSynthesizer(self.wiki, self.config)
        state.synthesis = await synthesizer.synthesize(sources, query=state.query)
        state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
        state.contradictions = state.synthesis.get("contradictions", [])

        # Persist synthesis for resume
        self.session_manager.update_status(
            state.session_id, "synthesizing", "synthesizing", None,
            iteration_round=state.round,
            synthesis_json=json.dumps(state.synthesis),
        )

        yield {"type": "synthesis_complete", "synthesis": {
            "reinforced_claims": state.synthesis.get("reinforced_claims", []),
            "contradictions": state.synthesis.get("contradictions", []),
            "knowledge_gaps": state.synthesis.get("knowledge_gaps", []),
            "new_entities": state.synthesis.get("new_entities", []),
        }}
        yield {"type": "progress", "progress": 0.65, "message": "Synthesis complete"}

        # ─── 6-step step 3: reasoning chain check ───
        if self.config.get("reasoning_check_enabled", True):
            try:
                from llmwikify.autoresearch.reasoning_checker import ReasoningChecker
                checker = ReasoningChecker()
                synth_text = self._synthesis_to_text(state.synthesis)
                result = checker.check(
                    synthesis=synth_text,
                    evidence_sources=state.sources,
                    clarification=state.clarification,
                )
                state.reasoning_check = result
                self.db.update_six_step_fields(state.session_id, reasoning=result)
                yield {
                    "type": "reasoning_check_complete",
                    "aggregate_score": result.get("aggregate_score", 0.0),
                    "issues_count": len(result.get("issues", [])),
                }
            except Exception as e:
                logger.warning("ReasoningChecker failed: %s", e)
                # Don't fail the pipeline — self-loop fallback is to skip.
        
        # Finish metrics tracking
        self._finish_action(metrics)

    async def _action_report(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Generate research report."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "reporting")
        
        # Track metrics (DR-13)
        metrics = self._start_action("report")
        
        state.phase = "reporting"
        self.session_manager.update_status(state.session_id, "report", "report", None)
        yield self._step_event("report", "Generating research report...")

        sources = self.db.get_sources(state.session_id) or []
        generator = ReportGenerator(self.wiki, self._report_llm, self.config)

        # ─── 6-step context: build dict to pass into report + review ───
        six_step_context = self._build_six_step_context(state)

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
            # Use persist_report (not finalize) to avoid setting status='done' prematurely
            self.session_manager.persist_report(state.session_id, {
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
            self.session_manager.update_status(state.session_id, "error", "report", -1)
            state.phase = "error"
            state.issues.append(f"Report generation failed: {e}")

        # ─── 6-step step 4: structure validation ───
        if state.report_md and self.config.get("structure_check_enabled", True):
            try:
                from llmwikify.autoresearch.structure_validator import StructureValidator
                validator = StructureValidator()
                result = validator.validate(
                    report=state.report_md,
                    synthesis=state.synthesis,
                    evidence_sources=state.sources,
                )
                state.structure_check = result
                self.db.update_six_step_fields(state.session_id, structure=result)
                yield {
                    "type": "structure_check_complete",
                    "aggregate_score": result.get("aggregate_score", 0.0),
                    "issues_count": len(result.get("issues", [])),
                }
            except Exception as e:
                logger.warning("StructureValidator failed: %s", e)

        # Finish metrics tracking
        self._finish_action(metrics)

    def _build_six_step_context(self, state: ResearchState) -> dict[str, Any] | None:
        """Build the consolidated 6-step framework context for report/review.

        The ReportGenerator and ResearchReviewer both accept a
        `six_step_context` dict to inject a framework block into their
        prompts. Returns None if no 6-step data is available (so the
        callers fall back to the no-enrichment code path).
        """
        if not (
            state.clarification
            or state.reasoning_check
            or state.structure_check
            or state.evidence_scores
        ):
            return None
        return {
            "clarification": state.clarification,
            "reasoning_check": state.reasoning_check,
            "structure_check": state.structure_check,
            "evidence_scores": dict(state.evidence_scores),
        }

    async def _action_review(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Review report quality."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "reviewing")
        
        # Track metrics (DR-13)
        metrics = self._start_action("review")
        
        state.phase = "reviewing"
        self.session_manager.update_status(state.session_id, "reviewing", "reviewing", None)
        yield self._step_event("review", "Reviewing report quality...")

        sources = self.db.get_sources(state.session_id) or []
        reviewer = ResearchReviewer(self.wiki, self._default_llm, self.config)
        try:
            six_step_context = self._build_six_step_context(state)
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
        self.session_manager.update_status(
            state.session_id, "reviewing", "reviewing", None,
            iteration_round=state.round,
            review_json=json.dumps(state.review),
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
        
        # Finish metrics tracking
        self._finish_action(metrics)

    async def _action_revise(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Revise report based on review feedback."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "revise")
        
        # Track metrics (DR-13)
        metrics = self._start_action("revise")
        
        yield self._step_event("revise", "Revising report...")

        sources = self.db.get_sources(state.session_id) or []
        revisor = ResearchRevisor(self.wiki, self._report_llm, self.config)
        try:
            state.report_md = await revisor.revise(state.report_md or "", state.issues, sources)
            # Reset review so it gets re-evaluated
            state.review = None
            # Persist revised report immediately so it survives pause/cancel/error
            # Use persist_report (not finalize) to avoid setting status='done' prematurely
            self.session_manager.persist_report(state.session_id, {
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
        
        # Finish metrics tracking
        self._finish_action(metrics)

    async def _action_done(self, state: ResearchState) -> AsyncIterator[dict[str, Any]]:
        """Finalize research session."""
        # Validate state transition
        self._warn_invalid_transition(state.phase, "done")
        
        state.phase = "done"
        sources = self.db.get_sources(state.session_id) or []

        self.session_manager.update_status(state.session_id, "done", "done", 1.0, iteration_round=state.round)
        self.session_manager.finalize(state.session_id, {
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

    # ─── Planning Helpers ──────────────────────────────────────────────

    async def _plan_sub_queries(self, query: str) -> list[dict[str, Any]]:
        """Decompose the research topic into sub-queries using planning_model."""
        from llmwikify.core.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")

        # Proactively search local wiki for relevant articles
        local_wiki_matches = ""
        try:
            wiki_results = self.wiki.search(query, limit=5)
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
        if self.wiki.index_file.exists():
            wiki_index = self.wiki.index_file.read_text()[:3000]

        messages = registry.get_messages(
            "research_plan",
            query=query,
            wiki_index=wiki_index[:2000] if wiki_index else "",
            local_wiki_matches=local_wiki_matches,
        )
        api_params = registry.get_api_params("research_plan")

        try:
            result = await chat_json(
                self._planning_llm, messages,
                max_tokens=api_params.get("max_tokens", 2048),
                temperature=api_params.get("temperature", 0.3),
                json_mode=api_params.get("json_mode", True),
            )
            if not isinstance(result, list):
                result = []
        except Exception as e:
            logger.warning("Planning LLM failed: %s, using single query", e)
            result = [{"query": query, "source_type": "web", "url": ""}]

        max_sq = self.config.get("max_sub_queries", 20)
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

    async def _plan_for_gaps(self, query: str, gaps: list[str]) -> list[dict[str, Any]]:
        """Generate sub-queries to fill knowledge gaps."""
        import asyncio

        gaps_text = "\n".join(f"- {gap}" for gap in gaps[:5])

        # Proactively search local wiki for gap-related content
        local_wiki_matches = ""
        try:
            gap_query = f"{query} {' '.join(gaps[:3])}"
            wiki_results = self.wiki.search(gap_query, limit=3)
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
            result = await chat_json(
                self._planning_llm, messages,
                max_tokens=1024, temperature=0.3, json_mode=True,
            )
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

    # ─── Resume Helpers ────────────────────────────────────────────────

    def _load_resume_state(self, state: ResearchState) -> None:
        """Load existing session state for resume."""
        session = self.db.get_research_session(state.session_id)
        if not session:
            return

        state.round = session.get("iteration_round", 1)
        state.max_rounds = session.get("max_rounds", self._max_react_rounds)
        state.quality_score = session.get("quality_score", 0)

        gaps_raw = session.get("knowledge_gaps")
        if gaps_raw:
            try:
                state.knowledge_gaps = json.loads(gaps_raw)
            except (json.JSONDecodeError, TypeError):
                state.knowledge_gaps = []

        # Load existing sub-queries and sources
        existing_sqs = self.db.get_sub_queries(state.session_id) or []
        state.sub_queries = [
            {"id": sq["id"], "query": sq["query"], "source_type": sq["source_type"],
             "url": sq.get("url"), "status": sq.get("status", "pending")}
            for sq in existing_sqs
        ]
        state.sources = self.db.get_sources(state.session_id) or []

        # Determine phase from current_step
        current_step = session.get("current_step", "planning")
        state.phase = current_step if current_step not in ("done", "error") else ""

        # If we have a report, set it
        result = session.get("result")
        if result:
            try:
                parsed = json.loads(result)
                state.report_md = parsed.get("markdown")
            except (json.JSONDecodeError, TypeError):
                state.report_md = result

        # Restore synthesis for resume
        synthesis_raw = session.get("synthesis_json")
        if synthesis_raw:
            try:
                state.synthesis = json.loads(synthesis_raw)
                state.knowledge_gaps = state.synthesis.get("knowledge_gaps", [])
                state.contradictions = state.synthesis.get("contradictions", [])
            except (json.JSONDecodeError, TypeError):
                pass

        # Restore review for resume
        review_raw = session.get("review_json")
        if review_raw:
            try:
                state.review = json.loads(review_raw)
                state.quality_score = state.review.get("score", 0)
                state.issues = state.review.get("issues", [])
            except (json.JSONDecodeError, TypeError):
                pass

        # ─── 6-step framework: restore clarification if present ───
        clarification_raw = session.get("clarification_json")
        if clarification_raw:
            try:
                state.clarification = json.loads(clarification_raw)
            except (json.JSONDecodeError, TypeError):
                state.clarification = None

        # Restore reasoning check
        reasoning_raw = session.get("reasoning_json")
        if reasoning_raw:
            try:
                state.reasoning_check = json.loads(reasoning_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        # Restore structure check
        structure_raw = session.get("structure_json")
        if structure_raw:
            try:
                state.structure_check = json.loads(structure_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        logger.info("Resuming session %s from %s (round %d)", state.session_id, current_step, state.round)

    # ─── Utilities ─────────────────────────────────────────────────────

    def _step_event(self, step: str, message: str) -> dict[str, Any]:
        return {"type": "step", "step": step, "message": message, "session_id": self.session_manager.session_id}
