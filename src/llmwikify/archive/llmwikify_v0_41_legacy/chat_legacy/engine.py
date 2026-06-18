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
from llmwikify.apps.chat.db import AutoResearchDatabase
from llmwikify.apps.chat.providers.registry import create_llm
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy import actions
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.actions import ActionContext
from llmwikify.apps.chat.agent.research_bridge import translate_react_events
from llmwikify.apps.chat.harness.source_analyzer import SourceAnalyzer
from llmwikify.apps.chat.config import merge_six_step_config
from llmwikify.apps.chat.gatherer import SourceGatherer
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.gates import ResearchGates
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.observer import ResearchObserver
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.reasoner import ResearchReasoner
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.resume import ResearchResumeLoader
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.llm_step import run_prompt
from llmwikify.apps.chat.state import (
    MetricsCollector,
    ResearchState,
)
from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.report import ReportGenerator
from llmwikify.apps.chat.harness.review import ResearchReviewer, ResearchRevisor
from llmwikify.apps.chat.session import ResearchSessionManager
from llmwikify.apps.chat.synthesizer import ResearchSynthesizer
from llmwikify.apps.chat.harness.quality_gate import QualityGate

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
        from llmwikify.apps.chat.clarifier import ResearchClarifier

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
            metrics=None,  # set in run() before ReActEngine.run()
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

        # Build initial state
        state = ResearchState(
            session_id=session_id,
            query=query,
            max_rounds=self._max_react_rounds,
        )
        if resume:
            self._load_resume_state(state)

        # Pre-loop: run clarify before the first plan
        if not resume and state.clarification is None:
            async for event in self._action_dispatch["clarify"](state):
                yield event

        # Build ReActConfig wired to ResearchEngine's domain logic
        config = self._build_react_config(state)
        from llmwikify.apps.chat.agent.research_runner import (
            ReActEngine,
            SkillContext,
        )

        engine = ReActEngine(config)

        try:
            async for event in translate_react_events(
                engine.run(SkillContext(
                    session_id=session_id,
                    wiki=self.wiki,
                    db=self.db,
                    llm_client=self._default_llm,
                    config=self.config,
                    metrics=self._metrics,
                )),
                state=state,
                session_id=session_id,
                timeout_seconds=self._timeout_seconds,
                update_status=self.session_manager.update_status,
            ):
                yield event
        except Exception as e:
            logger.error("ReAct loop error for session %s: %s", session_id, e, exc_info=True)
            self.session_manager.update_status(session_id, "error", state.phase or "unknown", -1)
            yield {"type": "error", "error": str(e)}
        finally:
            if self._metrics:
                self._metrics.finish()
                logger.info("Research metrics:\n%s", self._metrics.summary())

    def _build_react_config(self, state: ResearchState) -> ReActConfig:
        """Build a ReActConfig wired to ResearchEngine's domain logic."""
        from llmwikify.apps.chat.agent.research_runner import (
            ReActConfig,
            SkillAction,
            SkillResult,
        )

        engine_ref = self  # capture for closures

        # Build SkillAction wrappers for each action in the dispatch table
        def _make_action_handler(action_name: str):
            async def handler(args, ctx):
                dispatch = engine_ref._action_dispatch.get(action_name)
                if dispatch is None:
                    return SkillResult.fail(f"Unknown action: {action_name}")
                events = []
                async for ev in dispatch(state):
                    events.append(ev)
                return SkillResult.ok({"_events": events, "action": action_name})
            return handler

        action_names = [
            "plan", "gather", "analyze", "synthesize",
            "report", "review", "revise", "done",
        ]
        skill_actions = [
            SkillAction(
                name=name,
                description=f"Research action: {name}",
                handler=_make_action_handler(name),
                input_schema={"type": "object", "properties": {}, "required": []},
            )
            for name in action_names
        ]

        # Reason callback: wraps ResearchReasoner with compliance gate
        async def reason(state, ctx, emit):
            # Update budget
            elapsed = time.monotonic() - engine_ref._start_time
            state.budget_remaining = max(0, 1 - elapsed / engine_ref._timeout_seconds)

            # Check control signals
            engine_ref._check_control_signals(state)

            # Ask reasoner for next action
            action = await engine_ref._reason(state)
            thought = getattr(state, "_last_thought", "")

            # Framework compliance gate: intercept "done"
            if action == "done":
                if engine_ref.config.get("strict_exit", True):
                    non_compliant = engine_ref._check_quality_compliance(state)
                    gate_label = "Strict exit gate"
                else:
                    non_compliant = engine_ref._check_framework_compliance(state)
                    gate_label = "Framework compliance gate"
                if non_compliant is not None:
                    if engine_ref._can_replan(state):
                        logger.info(
                            "%s: %s → redirecting done→%s",
                            gate_label, non_compliant["reason"], non_compliant["missing"],
                        )
                        action = non_compliant["missing"]
                    else:
                        # No budget: mark incomplete and signal done
                        state.phase = "incomplete"
                        return {"action": "done", "thought": f"{gate_label} failed: {non_compliant['reason']}"}

            return {"action": action, "thought": thought}

        # Observe callback: delegates to ResearchObserver + quality gate
        async def observe(state, ctx):
            engine_ref._observe(state)
            # Quality gate check
            if engine_ref.config.get("gate_enabled", True):
                gate_result = engine_ref._evaluate_gate(state)
                if gate_result:
                    state.observations.append(
                        f"[质量门禁] {gate_result.gate_name}: {gate_result.summary}"
                    )
                    if not gate_result.passed:
                        state.observations.append(
                            f"⚠ 门禁未通过，建议: {gate_result.suggestion}"
                        )
            return {"observations": state.observations}

        # Done condition: check phase + special states
        def done_condition(s):
            phase = getattr(s, "phase", "") if hasattr(s, "phase") else s.get("phase", "")
            return (
                phase == "done"
                or phase == "incomplete"
                or getattr(s, "cancelled", False)
                or getattr(s, "paused", False)
            )

        # on_after_act: metrics tracking + gate intervention
        def on_after_act(state, action_name, result):
            if engine_ref._metrics:
                engine_ref._metrics.finish()

        return ReActConfig(
            actions=skill_actions,
            initial_state=state,
            reason=reason,
            done_condition=done_condition,
            max_rounds=self._max_react_rounds,
            timeout_seconds=self._timeout_seconds,
            observe=observe,
            on_after_act=on_after_act,
        )

    # ─── Backward-compat delegators ───────────────────────────────────────
    # These methods are kept for backward compat with existing tests
    # and any external code that may call them directly.

    async def _reason(self, state: ResearchState) -> str:
        """Decide next action based on current state."""
        return await self.reasoner.reason(state)

    def _rule_based_reason(self, state: ResearchState) -> str | None:
        """Deterministic decision rules as fallback."""
        return self.reasoner.rule_based(state)

    async def _llm_reason(self, state: ResearchState) -> str:
        """LLM-based reasoning via run_prompt."""
        return await self.reasoner._llm_reason(state)

    def _check_control_signals(self, state: ResearchState) -> None:
        """Check DB for cancel/pause signals from API layer."""
        self.gates.check_control_signals(state)

    def _check_framework_compliance(self, state: ResearchState) -> dict | None:
        """Return None if all 6-step framework fields are present."""
        return self.gates.check_framework_compliance(state)

    def _check_quality_compliance(self, state: ResearchState) -> dict | None:
        """Layered check: 6-step presence + quality thresholds."""
        return self.gates.check_quality_compliance(state)

    def _can_replan(self, state: ResearchState) -> bool:
        """Return True if the engine has budget for one more action."""
        return self.gates.can_replan(state)

    def _evaluate_gate(self, state: ResearchState):
        """Evaluate quality gate based on current phase."""
        return self.gates.evaluate_gate(state)

    @staticmethod
    def _synthesis_to_text(synthesis: dict | None) -> str:
        """Flatten synthesis dict to plain text for gate scoring."""
        return ResearchGates.synthesis_to_text(synthesis)

    async def _action_incomplete(
        self, state: ResearchState, reason: str,
    ):
        """Async-gen wrapper around actions.action_incomplete."""
        async for ev in actions.action_incomplete(self._action_ctx, state, reason):
            yield ev

    def _observe(self, state: ResearchState) -> None:
        """Refresh state from DB and generate interpreted observations."""
        self.observer.observe(state)

    def _load_resume_state(self, state: ResearchState) -> None:
        """Load existing session state for resume."""
        self.resume_loader.load(state)

