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
from functools import partial
from typing import Any

from llmwikify.llm.streamable import StreamableLLMClient
from llmwikify.autoresearch.db import AutoResearchDatabase
from llmwikify.agent.backend.providers.registry import create_llm
from llmwikify.autoresearch import actions
from llmwikify.autoresearch.actions import ActionContext
from llmwikify.autoresearch.analyzer import SourceAnalyzer
from llmwikify.autoresearch.config import merge_six_step_config
from llmwikify.autoresearch.gatherer import SourceGatherer
from llmwikify.autoresearch.reasoner import ResearchReasoner
from llmwikify.autoresearch.llm_step import run_prompt
from llmwikify.autoresearch.state import (
    MetricsCollector,
    ResearchState,
    VALID_TRANSITIONS,
)
from llmwikify.autoresearch.report import ReportGenerator
from llmwikify.autoresearch.review import ResearchReviewer, ResearchRevisor
from llmwikify.autoresearch.session import ResearchSessionManager
from llmwikify.autoresearch.synthesizer import ResearchSynthesizer
from llmwikify.autoresearch.quality_gate import QualityGate

logger = logging.getLogger(__name__)

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

        # Action-level components (used by action functions in actions.py)
        self.gatherer = SourceGatherer(self.wiki, self.db, self.session_manager, self.config)
        self.analyzer = SourceAnalyzer(self.wiki, self.session_manager, self.config)
        self.synthesizer = ResearchSynthesizer(self.wiki, self.config)
        self.report = ReportGenerator(self.wiki, self._report_llm, self.config)
        self.reviewer = ResearchReviewer(self.wiki, self._default_llm, self.config)
        self.revisor = ResearchRevisor(self.wiki, self._report_llm, self.config)

        # Metrics (DR-13)
        self._metrics: MetricsCollector | None = None

        # ─── ActionContext + dispatch table ──────────────────────────────
        # Constructed here so actions.py functions receive all deps via ctx.
        self._action_ctx = ActionContext(
            wiki=self.wiki,
            db=self.db,
            session_manager=self.session_manager,
            clarifier=self.clarifier,
            gatherer=self.gatherer,
            analyzer=self.analyzer,
            synthesizer=self.synthesizer,
            report=self.report,
            reviewer=self.reviewer,
            revisor=self.revisor,
            quality_gate=self._quality_gate,
            config=self.config,
            metrics=None,  # set in run() before _react_loop
            planning_llm=self._planning_llm,
            default_llm=self._default_llm,
            report_llm=self._report_llm,
        )
        # Dispatch table: action name -> partial(action_fn, ctx).
        # Set in run() once metrics are initialized (ctx.metrics is set there).
        self._action_dispatch: dict[str, Any] = {}

        # Phase 2 #5 / C1 — ReAct Thought step lives in its own
        # module. The reasoner needs the action context (for
        # ``run_prompt``), the database (for ``get_sources`` in
        # the rule-based fallback), the config, and the
        # ``_max_replan`` constant. Constructed after the
        # action context is built.
        self.reasoner = ResearchReasoner(self)

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

    async def run(self, session_id: str, query: str, resume: bool = False) -> AsyncIterator[dict[str, Any]]:
        """Execute the ReAct research loop, yielding SSE events."""
        self.session_manager.session_id = session_id
        self._start_time = time.monotonic()
        
        # Initialize metrics (DR-13) + build dispatch table
        self._metrics = MetricsCollector(session_id=session_id)
        self._metrics.start()
        self._action_ctx.metrics = self._metrics
        # Propagate to LLM-using submodules so run_prompt (called via
        # the clarifier/report/reviewer/revisor) also records metrics.
        self.clarifier.metrics = self._metrics
        self.report.metrics = self._metrics
        self.reviewer.metrics = self._metrics
        self.revisor.metrics = self._metrics
        self._action_dispatch = {
            "clarify":    partial(actions.action_clarify, self._action_ctx),
            "plan":       partial(actions.action_plan, self._action_ctx),
            "gather":     partial(actions.action_gather, self._action_ctx),
            "analyze":    partial(actions.action_analyze, self._action_ctx),
            "synthesize": partial(actions.action_synthesize, self._action_ctx),
            "report":     partial(actions.action_report, self._action_ctx),
            "review":     partial(actions.action_review, self._action_ctx),
            "revise":     partial(actions.action_revise, self._action_ctx),
            "done":       partial(actions.action_done, self._action_ctx),
        }

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
            async for event in self._action_dispatch["clarify"](state):
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

                # ── Framework compliance gate: block 'done' if any 6-step
                #    framework field is missing. Either redirect to the
                #    missing action (if budget allows) or mark incomplete.
                #    When strict_exit=True (default v6), also enforce quality
                #    thresholds (review approved, quality_score, gaps, sources).
                if action == "done":
                    if self.config.get("strict_exit", True):
                        non_compliant = self._check_quality_compliance(state)
                        redirect_type = "quality_redirect"
                        gate_label = "Strict exit gate"
                    else:
                        non_compliant = self._check_framework_compliance(state)
                        redirect_type = "framework_redirect"
                        gate_label = "Framework compliance gate"
                    if non_compliant is not None:
                        if self._can_replan(state):
                            logger.info(
                                "%s: %s → redirecting done→%s",
                                gate_label, non_compliant["reason"], non_compliant["missing"],
                            )
                            yield {
                                "type": redirect_type,
                                "from": "done",
                                "to": non_compliant["missing"],
                                "reason": non_compliant["reason"],
                                "round": state.round,
                            }
                            action = non_compliant["missing"]
                        else:
                            logger.warning(
                                "%s failed and no budget: %s",
                                gate_label, non_compliant["reason"],
                            )
                            async for ev in self._action_incomplete(
                                state, non_compliant["reason"],
                            ):
                                yield ev
                            break

                # ── ACT: execute action via dispatch table ──
                action_method = self._action_dispatch.get(action)
                if action_method is None:
                    # Unknown action → default to done (safe fallback)
                    logger.warning("Unknown action %s, defaulting to done", action)
                    action_method = self._action_dispatch["done"]
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
                    # Framework compliance gate: do not exit to 'done' if
                    # any 6-step field is missing — mark incomplete instead.
                    # When strict_exit=True, also block on quality thresholds.
                    if self.config.get("strict_exit", True):
                        non_compliant = self._check_quality_compliance(state)
                        gate_label = "Strict exit gate"
                    else:
                        non_compliant = self._check_framework_compliance(state)
                        gate_label = "Framework compliance gate"
                    if non_compliant is not None:
                        logger.warning(
                            "Max rounds reached, %s failed: %s",
                            gate_label, non_compliant["reason"],
                        )
                        yield {
                            "type": "round_max",
                            "round": state.round,
                            "message": (
                                f"Reached max rounds ({state.max_rounds}) "
                                f"with {gate_label} failing"
                            ),
                        }
                        async for ev in self._action_incomplete(
                            state, f"max_rounds: {non_compliant['reason']}",
                        ):
                            yield ev
                        break
                    yield {
                        "type": "round_max",
                        "round": state.round,
                        "message": f"Reached max rounds ({state.max_rounds})",
                    }
                    async for event in self._action_done(state):
                        yield event
                    break
        except Exception as e:
            # Catch-all: ensure DB status is always updated on unexpected errors
            logger.error("ReAct loop error for session %s: %s", session_id, e, exc_info=True)
            self.session_manager.update_status(session_id, "error", state.phase or "unknown", -1)
            yield {"type": "error", "error": str(e)}

    # ─── Reason Step (Phase 2 #5 / C1) ────────────────────────────────
    # The 3 reason methods are now thin 1-line delegates to
    # ``self.reasoner`` (see ``engine/reasoner.py``). The
    # methods stay on ResearchEngine for backward compat with
    # existing tests and any external code that may call them
    # via ``engine._reason(state)`` etc.

    async def _reason(self, state: ResearchState) -> str:
        """Decide next action based on current state.

        Delegates to ``self.reasoner.reason()`` (Phase 2 #5 / C1).
        Uses LLM for reasoning (ReAct Thought step), falls back
        to deterministic rules.
        """
        return await self.reasoner.reason(state)

    def _rule_based_reason(self, state: ResearchState) -> str | None:
        """Deterministic decision rules as fallback.

        Delegates to ``self.reasoner.rule_based()``.
        """
        return self.reasoner.rule_based(state)

    async def _llm_reason(self, state: ResearchState) -> str:
        """LLM-based reasoning via run_prompt.

        Delegates to ``self.reasoner._llm_reason()``.
        """
        return await self.reasoner._llm_reason(state)

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

    # ─── Framework Compliance Gate ────────────────────────────────────

    def _check_framework_compliance(self, state: ResearchState) -> dict | None:
        """Return None if all 6-step framework fields are present, else
        {missing: action_name, reason: human_readable}.

        Used to prevent the engine from marking a session 'done' when
        the 6-step framework (clarify→evidence→reasoning→structure→
        report→review) has skipped steps. The 'missing' field is the
        next action the engine should take to fix the gap.

        Maps to the 6 framework steps in the README:
        - 1. clarify       → state.clarification
        - 2. evidence      → state.evidence_scores (populated by gather)
        - 3. reasoning     → state.reasoning_check (populated by synthesize)
        - 4. structure     → state.structure_check (populated by report)
        - 5. report        → state.report_md
        - 6. review        → state.review
        """
        if state.clarification is None:
            return {"missing": "clarify", "reason": "step 1 (clarification) missing"}
        if not state.evidence_scores:
            return {"missing": "gather", "reason": "step 2 (evidence scoring) missing"}
        if state.synthesis is None:
            return {"missing": "synthesize", "reason": "step 5 (synthesis) missing"}
        if state.reasoning_check is None:
            # reasoning_check is part of synthesize action
            return {"missing": "synthesize", "reason": "step 3 (reasoning check) missing"}
        if state.report_md is None:
            return {"missing": "report", "reason": "step 5 (report) missing"}
        if state.structure_check is None:
            # structure_check is part of report action
            return {"missing": "report", "reason": "step 4 (structure check) missing"}
        if state.review is None:
            return {"missing": "review", "reason": "step 6 (review) missing"}
        return None

    def _check_quality_compliance(self, state: ResearchState) -> dict | None:
        """Layered check: 6-step presence + quality thresholds.

        Used by the strict_exit gate (v6) to prevent the engine from
        marking a session 'done' with low-quality output. Returns the
        first failing check as {missing: action_name, reason: str}.

        Layer 1 (delegates to _check_framework_compliance):
            - All 6 framework fields present.

        Layer 2 (quality thresholds):
            - state.review.approved == True
            - state.quality_score >= config.quality_threshold
            - len(state.knowledge_gaps) <= config.gate_max_knowledge_gaps
            - len(state.sources) >= config.gate_min_sources

        Returns None only when all checks pass.
        """
        # Layer 1: framework presence
        missing = self._check_framework_compliance(state)
        if missing is not None:
            return missing

        # Layer 2: quality thresholds
        review = state.review or {}
        if not review.get("approved"):
            return {
                "missing": "revise",
                "reason": f"review not approved (score={state.quality_score})",
            }

        threshold = self.config.get("quality_threshold", 7)
        if state.quality_score < threshold:
            return {
                "missing": "revise",
                "reason": f"quality_score={state.quality_score} < threshold={threshold}",
            }

        max_gaps = self.config.get("gate_max_knowledge_gaps", 3)
        if len(state.knowledge_gaps) > max_gaps:
            return {
                "missing": "synthesize",
                "reason": f"knowledge_gaps={len(state.knowledge_gaps)} > max={max_gaps}",
            }

        min_sources = self.config.get("gate_min_sources", 3)
        if len(state.sources) < min_sources:
            return {
                "missing": "gather",
                "reason": f"sources={len(state.sources)} < min={min_sources}",
            }

        return None

    def _can_replan(self, state: ResearchState) -> bool:
        """Return True if the engine has budget for one more action.

        Used by the framework compliance gate to decide between
        'redirect to missing action' vs 'mark incomplete'.
        """
        if state.budget_remaining <= 0.10:
            return False
        if state.round >= state.max_rounds:
            return False
        return True

    async def _action_incomplete(
        self, state: ResearchState, reason: str,
    ):
        """Async-gen wrapper around actions.action_incomplete.

        Lets the main loop yield incomplete events inline.
        """
        async for ev in actions.action_incomplete(self._action_ctx, state, reason):
            yield ev

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
        """Delegate to actions.synthesis_to_text (extracted in Commit 5b/5c).

        Kept as a static method on ResearchEngine for backward compat
        with code that calls engine._synthesis_to_text.
        """
        return actions.synthesis_to_text(synthesis)

    # ─── Resume Helpers ────────────────────────────────────────────────

    def _load_resume_state(self, state: ResearchState) -> None:
        """Load existing session state for resume."""
        session = self.db.get_research_session(state.session_id)
        if not session:
            return

        # Reset round to 0 on resume so reasoner gets a fresh budget cycle
        state.round = 0
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
        if current_step in ("done", "error", "incomplete", "timeout"):
            state.phase = ""
        else:
            state.phase = current_step

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

        # Restore evidence scores
        evidence_raw = session.get("evidence_scores_json")
        if evidence_raw:
            try:
                state.evidence_scores = json.loads(evidence_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        logger.info("Resuming session %s from %s (round %d)", state.session_id, current_step, state.round)

