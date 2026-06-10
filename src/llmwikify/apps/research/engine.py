"""Research Engine — ReAct loop orchestrator with adaptive reasoning.

Replaces the fixed 7-stage sequential flow with an adaptive ReAct
(Reason → Act → Observe → loop) agent that dynamically decides what
to do next based on intermediate results.

This engine now delegates its ReAct core to ``ReActEngine`` via
``_build_react_config()`` (mirroring the pattern in
``apps/chat/engine.py::ResearchEngine``). The domain actions
(``_action_plan``, ``_action_gather``, etc.) and supporting
methods (``_reason``, ``_observe``, ``_evaluate_gate``, ...) are
preserved here and wired into ``SkillAction`` handlers.
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
from ..chat.db import ChatDatabase
from ..chat.providers.registry import create_llm
from llmwikify.apps.chat.agent.react_engine import (
    ReActConfig,
    ReActEngine,
    SkillAction,
    SkillContext,
    SkillResult,
)
from llmwikify.apps.chat.agent.research_bridge import translate_react_events
from .actions import (
    ActionContext,
    action_plan,
    action_gather,
    action_analyze,
    action_synthesize,
    action_report,
    action_review,
    action_revise,
    action_done,
    step_event,
)
from .config import merge_research_config
from .session import ResearchSessionManager
from .quality_gate import QualityGate

logger = logging.getLogger(__name__)

# ─── State Transition Table (DR-14) ──────────────────────────────────────
# Explicit valid transitions: from_phase → list of allowed to_phases
VALID_TRANSITIONS: dict[str | None, list[str]] = {
    None:           ["plan"],
    "planning":     ["gather"],
    "gathering":    ["analyze", "plan"],
    "analyzing":    ["synthesizing", "plan"],
    "synthesizing": ["reporting", "plan"],
    "reporting":    ["reviewing"],
    "reviewing":    ["revise", "done"],
    "revise":       ["reviewing", "done"],
    "error":        ["done"],
    "done":         [],
}


# ─── Metrics Collection (DR-13) ──────────────────────────────────────────

@dataclass
class ActionMetrics:
    """Metrics for a single action execution."""
    action: str
    start_time: float
    end_time: float = 0.0
    duration_ms: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0

    def finish(self) -> None:
        """Mark action as finished and compute duration."""
        self.end_time = time.monotonic()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)


@dataclass
class SessionMetrics:
    """Metrics for an entire research session."""
    session_id: str
    start_time: float = 0.0
    end_time: float = 0.0
    total_duration_ms: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    actions: list[ActionMetrics] = field(default_factory=list)

    def start(self) -> None:
        """Mark session as started."""
        self.start_time = time.monotonic()

    def finish(self) -> None:
        """Mark session as finished and compute totals."""
        self.end_time = time.monotonic()
        self.total_duration_ms = int((self.end_time - self.start_time) * 1000)
        self.total_tokens = sum(a.tokens_used for a in self.actions)
        self.total_cost_usd = sum(a.cost_usd for a in self.actions)

    def add_action(self, action: ActionMetrics) -> None:
        """Add an action metric."""
        self.actions.append(action)

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [f"Session {self.session_id} completed in {self.total_duration_ms/1000:.1f}s"]
        for a in self.actions:
            token_str = f"{a.tokens_used:,} tokens" if a.tokens_used > 0 else "0 tokens"
            cost_str = f"${a.cost_usd:.3f}" if a.cost_usd > 0 else "$0.00"
            lines.append(f"├── {a.action}: {a.duration_ms/1000:.1f}s, {token_str}, {cost_str}")
        lines.append(f"└── Total: {self.total_duration_ms/1000:.1f}s, {self.total_tokens:,} tokens, ${self.total_cost_usd:.3f}")
        return "\n".join(lines)


@dataclass
class ResearchState:
    """Mutable state for the ReAct research loop."""

    session_id: str = ""
    query: str = ""

    # Round tracking
    round: int = 0
    max_rounds: int = 5
    phase: str = ""  # planning | gathering | analyzing | synthesizing | reporting | reviewing | done

    # Data accumulators
    sub_queries: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    report_md: str | None = None
    review: dict[str, Any] | None = None

    # Quality tracking
    quality_score: int = 0
    knowledge_gaps: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    # Budget
    total_llm_calls: int = 0
    total_sources: int = 0
    total_sub_queries: int = 0
    budget_remaining: float = 1.0

    # Control signals
    cancelled: bool = False
    paused: bool = False

    # Interpreted observations (generated by _observe)
    observations: list[str] = field(default_factory=list)


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
        db: ChatDatabase,
        llm_client: StreamableLLMClient,
        config: dict[str, Any] | None = None,
    ):
        self.wiki = wiki
        self.db = db
        self.config = merge_research_config(config)
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

        # ActionContext (deps for action functions)
        self._action_ctx = ActionContext(
            wiki=self.wiki,
            db=self.db,
            session_manager=self.session_manager,
            config=self.config,
            planning_llm=self._planning_llm,
            report_llm=self._report_llm,
            default_llm=self._default_llm,
            quality_gate=self._quality_gate,
        )

        # Metrics (DR-13)
        self._metrics: SessionMetrics | None = None

    def _resolve_model(self, config_key: str) -> StreamableLLMClient | None:
        model_cfg = self.config.get(config_key)
        if not model_cfg:
            return None
        try:
            return create_llm(model_cfg)
        except Exception as e:
            logger.warning("Failed to resolve %s: %s, using default LLM", config_key, e)
            return None

    def _validate_transition(self, from_phase: str, to_phase: str) -> bool:
        """Validate state transition is allowed.
        
        Args:
            from_phase: Current phase
            to_phase: Target phase
            
        Returns:
            True if transition is valid, False otherwise
        """
        valid_targets = VALID_TRANSITIONS.get(from_phase, [])
        if to_phase not in valid_targets:
            logger.warning(
                "Invalid state transition: %s → %s (valid: %s)",
                from_phase, to_phase, valid_targets or "none"
            )
            return False
        return True

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
        self._action_ctx.metrics = self._metrics

        # Build action dispatch table (action_name → action function).
        self._action_dispatch = {
            "plan":       partial(action_plan, self._action_ctx),
            "gather":     partial(action_gather, self._action_ctx),
            "analyze":    partial(action_analyze, self._action_ctx),
            "synthesize": partial(action_synthesize, self._action_ctx),
            "report":     partial(action_report, self._action_ctx),
            "review":     partial(action_review, self._action_ctx),
            "revise":     partial(action_revise, self._action_ctx),
            "done":       partial(action_done, self._action_ctx),
        }

        # Build initial state
        state = ResearchState(
            session_id=session_id,
            query=query,
            max_rounds=self._max_react_rounds,
        )
        if resume:
            self._load_resume_state(state)

        # Build ReActConfig wired to ResearchEngine's domain logic
        config = self._build_react_config(state)
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
                action_done_handler=partial(action_done, self._action_ctx),
            ):
                yield event
        except TimeoutError:
            self.session_manager.update_status(session_id, "timeout", "timeout", -1)
            yield {"type": "error", "error": f"Research timed out after {self._timeout_seconds}s"}
        except Exception as e:
            logger.error("ReAct loop error for session %s: %s", session_id, e, exc_info=True)
            self.session_manager.update_status(session_id, "error", state.phase or "unknown", -1)
            yield {"type": "error", "error": str(e)}
        finally:
            # Finalize metrics and log summary
            if self._metrics:
                self._metrics.finish()
                logger.info("Research metrics:\n%s", self._metrics.summary())

    def _build_react_config(self, state: ResearchState) -> ReActConfig:
        """Build a ReActConfig wired to ResearchEngine's domain logic."""
        engine_ref = self

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

        # Reason callback: budget + control signals + delegate to _reason
        async def reason(state, ctx, emit):
            # Update budget
            elapsed = time.monotonic() - engine_ref._start_time
            state.budget_remaining = max(0, 1 - elapsed / engine_ref._timeout_seconds)

            # Check control signals
            engine_ref._check_control_signals(state)

            # Ask reasoner for next action
            action = await engine_ref._reason(state)
            thought = getattr(state, "_last_thought", "")

            return {"action": action, "thought": thought}

        # Observe callback: delegates to _observe + quality gate
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
                or getattr(s, "cancelled", False)
                or getattr(s, "paused", False)
            )

        # on_after_act: metrics tracking
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
        import json as json_mod

        analyzed_count = sum(1 for s in state.sources if s.get("analysis"))
        failed_sq = sum(1 for sq in state.sub_queries if sq.get("status") == "failed")

        # Build observation context from interpreted observations
        obs_text = "\n".join(f"  - {o}" for o in state.observations) if state.observations else "  (none)"

        messages = [
            {"role": "system", "content": (
                "You are a research orchestrator using ReAct reasoning.\n"
                "Based on the current state, provide your reasoning and decide the next action.\n\n"
                "Return a JSON object with:\n"
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

        def _call():
            return self._default_llm.chat(messages, max_tokens=200, temperature=0.1)

        raw = await asyncio.to_thread(_call)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json_mod.loads(raw)
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
        """Evaluate quality gate based on current phase."""
        gate = self._quality_gate
        if state.phase == "gathering":
            return gate.check_after_gathering(state.sources, state.sub_queries)
        elif state.phase == "analyzing":
            return gate.check_after_analysis(state.sources)
        elif state.phase == "synthesizing":
            return gate.check_after_synthesis(state.synthesis)
        elif state.phase == "reporting":
            return gate.check_before_report(state.synthesis, state.sources)
        return None

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

        logger.info("Resuming session %s from %s (round %d)", state.session_id, current_step, state.round)

    # ─── Utilities ─────────────────────────────────────────────────────

    def _step_event(self, step: str, message: str) -> dict[str, Any]:
        """Build a step-started event. Thin wrapper around actions.step_event."""
        return step_event(self.session_manager.session_id, step, message)
