# DEPRECATED in v0.42+: archived to archive/llmwikify_v0_41_legacy/. Will be removed in v0.5.
# Replaced by apps/chat/agent/orchestrator.py::ChatOrchestrator's session resume path.
# Kept here for git history preservation and emergency rollback. Do not add new callers.
"""Research Resume Loader — hydrate state from DB on resume.

Phase 2 #5 / C3 — extracted from ResearchEngine (~565 LOC
after C2, now ~400 after C3) to ``resume.py``.

The Resume Loader encapsulates the 1 method that runs at
the start of a session to hydrate ``ResearchState`` from
the DB when ``resume=True`` is passed to ``engine.run()``:

  - ``load(state)`` — load session row from DB, restore
       round / max_rounds / quality_score / knowledge_gaps,
       rebuild sub_queries / sources, set phase from
       current_step, restore report / synthesis / review /
       clarification / reasoning / structure / evidence
       from their respective JSON columns.

The engine keeps a 1-line delegator
(``_load_resume_state(state)``) for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.engine import ResearchEngine
    from llmwikify.apps.chat.state import ResearchState

logger = logging.getLogger(__name__)

# Phases that mean "session is finished" — resume should NOT
# try to continue the loop from these.
_TERMINAL_PHASES = frozenset(("done", "error", "incomplete", "timeout"))


class ResearchResumeLoader:
    """Hydrate ``ResearchState`` from the DB on resume.

    Reads the session row, then walks each JSON column
    (synthesis_json / review_json / clarification_json /
    reasoning_json / structure_json / evidence_scores_json)
    and applies it to the live state object.
    """

    def __init__(self, engine: "ResearchEngine"):
        self._engine = engine
        # Cached for direct access.
        self._db = engine.db
        self._max_react_rounds = engine._max_react_rounds

    def load(self, state: "ResearchState") -> None:
        """Load existing session state for resume.

        If the session row is missing, returns silently
        (fresh session). Otherwise hydrates all relevant
        state fields from the row.
        """
        session = self._db.get_research_session(state.session_id)
        if not session:
            return

        # Reset round to 0 on resume so reasoner gets a fresh
        # budget cycle
        state.round = 0
        state.max_rounds = session.get("max_rounds", self._max_react_rounds)
        state.quality_score = session.get("quality_score", 0)

        # Load existing knowledge_gaps
        gaps_raw = session.get("knowledge_gaps")
        if gaps_raw:
            try:
                state.knowledge_gaps = json.loads(gaps_raw)
            except (json.JSONDecodeError, TypeError):
                state.knowledge_gaps = []

        # Load existing sub-queries and sources
        existing_sqs = self._db.get_sub_queries(state.session_id) or []
        state.sub_queries = [
            {
                "id": sq["id"],
                "query": sq["query"],
                "source_type": sq["source_type"],
                "url": sq.get("url"),
                "status": sq.get("status", "pending"),
            }
            for sq in existing_sqs
        ]
        state.sources = self._db.get_sources(state.session_id) or []

        # Determine phase from current_step
        current_step = session.get("current_step", "planning")
        if current_step in _TERMINAL_PHASES:
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

        # Restore self-loop metadata so the self-correction budget
        # is preserved across resume. Without this, a session that
        # already burned 2 of 3 clarify retries would get 3 fresh
        # retries on resume.
        self_loop_counts_raw = session.get("self_loop_counts_json")
        if self_loop_counts_raw:
            try:
                loaded = json.loads(self_loop_counts_raw)
                if isinstance(loaded, dict):
                    state.self_loop_counts = loaded
            except (json.JSONDecodeError, TypeError):
                pass
        self_loop_history_raw = session.get("self_loop_history_json")
        if self_loop_history_raw:
            try:
                loaded = json.loads(self_loop_history_raw)
                if isinstance(loaded, list):
                    state.self_loop_history = loaded
            except (json.JSONDecodeError, TypeError):
                pass

        logger.info(
            "Resuming session %s from %s (round %d)",
            state.session_id, current_step, state.round,
        )
