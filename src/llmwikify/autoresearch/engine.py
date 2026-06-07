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

from llmwikify.foundation.llm.streamable import StreamableLLMClient
from llmwikify.autoresearch.db import AutoResearchDatabase
from llmwikify.agent.backend.providers.registry import create_llm
from llmwikify.autoresearch import actions
from llmwikify.autoresearch.actions import ActionContext
from llmwikify.autoresearch.analyzer import SourceAnalyzer
from llmwikify.autoresearch.config import merge_six_step_config
from llmwikify.autoresearch.gatherer import SourceGatherer
from llmwikify.autoresearch.gates import ResearchGates
from llmwikify.autoresearch.observer import ResearchObserver
from llmwikify.autoresearch.reasoner import ResearchReasoner
from llmwikify.autoresearch.resume import ResearchResumeLoader
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

        # Phase 2 #5 / C2 — framework & quality compliance
        # gates live in their own module. The gates need the
        # database (for control signals), the config, and
        # the quality gate. Constructed last so it can
        # reference ``self._quality_gate``.
        self.gates = ResearchGates(self)

        # Phase 2 #5 / C3 — ReAct Observe step and Resume
        # loader live in their own modules. Both need the
        # database (for ``get_sources`` / ``get_sub_queries`` /
        # ``get_research_session``). The resume loader also
        # needs ``_max_react_rounds`` for the default
        # ``max_rounds`` fallback.
        self.observer = ResearchObserver(self)
        self.resume_loader = ResearchResumeLoader(self)

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

    # ─── Gates (Phase 2 #5 / C2) ─────────────────────────────────────────
    # The 5 gate methods (control signals / framework compliance /
    # quality compliance / can_replan / evaluate_gate) plus the
    # synthesis_to_text helper are now thin 1-line delegators to
    # ``self.gates`` (see ``gates.py``). The methods stay on
    # ResearchEngine for backward compat with existing tests
    # and any external code that may call them via
    # ``engine._check_*()`` etc.

    def _check_control_signals(self, state: ResearchState) -> None:
        """Check DB for cancel/pause signals from API layer.

        Delegates to ``self.gates.check_control_signals()``.
        """
        self.gates.check_control_signals(state)

    def _check_framework_compliance(self, state: ResearchState) -> dict | None:
        """Return None if all 6-step framework fields are present, else
        {missing: action_name, reason: human_readable}.

        Delegates to ``self.gates.check_framework_compliance()``.
        """
        return self.gates.check_framework_compliance(state)

    def _check_quality_compliance(self, state: ResearchState) -> dict | None:
        """Layered check: 6-step presence + quality thresholds.

        Delegates to ``self.gates.check_quality_compliance()``.
        """
        return self.gates.check_quality_compliance(state)

    def _can_replan(self, state: ResearchState) -> bool:
        """Return True if the engine has budget for one more action.

        Delegates to ``self.gates.can_replan()``.
        """
        return self.gates.can_replan(state)

    def _evaluate_gate(self, state: ResearchState):
        """Evaluate quality gate based on current phase.

        Delegates to ``self.gates.evaluate_gate()``.
        """
        return self.gates.evaluate_gate(state)

    @staticmethod
    def _synthesis_to_text(synthesis: dict | None) -> str:
        """Flatten synthesis dict to plain text for gate scoring.

        Delegates to ``ResearchGates.synthesis_to_text()``
        (Phase 2 #5 / C2). Kept as a static method on
        ResearchEngine for backward compat with code that
        calls engine._synthesis_to_text.
        """
        return ResearchGates.synthesis_to_text(synthesis)

    async def _action_incomplete(
        self, state: ResearchState, reason: str,
    ):
        """Async-gen wrapper around actions.action_incomplete.

        Lets the main loop yield incomplete events inline.
        """
        async for ev in actions.action_incomplete(self._action_ctx, state, reason):
            yield ev

    # ─── Observe Step (Phase 2 #5 / C3) ────────────────────────────────
    # The 1 observe method is now a 1-line delegator to
    # ``self.observer`` (see ``observer.py``). The method
    # stays on ResearchEngine for backward compat with
    # existing tests and any external code that may call
    # ``engine._observe(state)`` directly.

    def _observe(self, state: ResearchState) -> None:
        """Refresh state from DB and generate interpreted observations.

        Delegates to ``self.observer.observe()``
        (Phase 2 #5 / C3).
        """
        self.observer.observe(state)

    # ─── Resume Helpers (Phase 2 #5 / C3) ──────────────────────────────
    # The 1 resume-state loader method is now a 1-line
    # delegator to ``self.resume_loader`` (see ``resume.py``).
    # The method stays on ResearchEngine for backward compat
    # with existing tests and any external code that may call
    # ``engine._load_resume_state(state)`` directly.

    def _load_resume_state(self, state: ResearchState) -> None:
        """Load existing session state for resume.

        Delegates to ``self.resume_loader.load()``
        (Phase 2 #5 / C3).
        """
        self.resume_loader.load(state)

