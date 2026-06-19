"""ResearchDelegate — wraps ResearchDatabase's 27 chat-domain methods.

The research domain (autoresearch_*, research_steps, six-step fields,
event_log writes, etc.) lives in ``apps.research.db.ResearchDatabase``.

For backward compatibility, ChatDatabase exposes 27 thin 1-line
delegates (``self._research.create_research_session(...)``). This
class is the extracted wrapper that holds the same 27 delegates so
ChatDatabase can simply do ``self._research_delegate.create_research_session(...)``.

All 27 methods are pure 1-line forwarders — no logic, no schema.
The real implementation is in ``apps/research/db.py``.

Methods (27):
    create_research_session, get_research_session, list_research_sessions,
    update_research_status, update_research_progress, persist_report,
    finalize_research, delete_research,
    save_sub_query, update_sub_query, get_sub_queries,
    save_source, update_source_analysis, get_sources,
    rate_source, get_source_count,
    update_six_step_fields, get_six_step_fields,
    append_events, get_events,
    save_step, get_step, list_steps, delete_steps, update_step_status,
    save_research_state, load_research_state

DEPRECATED: New code should use ``apps.research.db.ResearchDatabase``
directly. These delegates are kept for back-compat with 91 production
callers identified in the 2026-06-19 audit.
"""
from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.db_base import get_app_db_path

logger = logging.getLogger(__name__)


class ResearchDelegate:
    """Thin wrapper around ResearchDatabase's chat-domain methods.

    Holds a lazy ``ResearchDatabase`` instance. All methods are
    1-line forwarders.
    """

    def __init__(self, data_dir):
        self._data_dir = data_dir

    @property
    def _research(self):
        """Lazy ResearchDatabase instance."""
        if not hasattr(self, "_research_db"):
            from llmwikify.apps.research.db import ResearchDatabase
            self._research_db = ResearchDatabase(self._data_dir)
        return self._research_db

    # ─── Sessions ──────────────────────────────────────────────

    def create_research_session(self, wiki_id: str, query: str) -> str:
        return self._research.create_research_session(wiki_id, query)

    def get_research_session(self, session_id: str) -> dict | None:
        return self._research.get_research_session(session_id)

    def list_research_sessions(
        self, wiki_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        return self._research.list_research_sessions(wiki_id, limit)

    def update_research_status(
        self, session_id: str, status: str,
        step: str | None = None, iteration_round: int | None = None,
        synthesis_json: str | None = None,
        review_json: str | None = None,
    ) -> None:
        return self._research.update_research_status(
            session_id, status, step, iteration_round,
            synthesis_json, review_json,
        )

    def update_research_progress(
        self, session_id: str, progress: float,
    ) -> None:
        return self._research.update_research_progress(session_id, progress)

    def persist_report(
        self, session_id: str, result: str | None = None,
    ) -> None:
        return self._research.persist_report(session_id, result)

    def finalize_research(
        self, session_id: str, result: str | None = None,
        wiki_page_name: str | None = None,
    ) -> None:
        return self._research.finalize_research(
            session_id, result, wiki_page_name,
        )

    def delete_research(self, session_id: str) -> bool:
        return self._research.delete_research(session_id)

    # ─── Sub-queries ──────────────────────────────────────────

    def save_sub_query(
        self, session_id: str, query: str, source_type: str,
        url: str | None = None,
    ) -> str:
        return self._research.save_sub_query(
            session_id, query, source_type, url,
        )

    def update_sub_query(
        self, sq_id: str, status: str,
        result: dict | None = None, error: str | None = None,
    ) -> None:
        return self._research.update_sub_query(
            sq_id, status, result, error,
        )

    def get_sub_queries(self, session_id: str) -> list[dict]:
        return self._research.get_sub_queries(session_id)

    # ─── Sources ──────────────────────────────────────────────

    def save_source(
        self, session_id: str, sub_query_id: str, source_type: str,
        url: str, title: str, content_length: int,
        content_preview: str | None = None, content: str | None = None,
    ) -> str:
        return self._research.save_source(
            session_id, sub_query_id, source_type, url, title,
            content_length, content_preview, content,
        )

    def update_source_analysis(self, source_id: str, analysis: dict) -> None:
        return self._research.update_source_analysis(source_id, analysis)

    def get_sources(self, session_id: str) -> list[dict]:
        return self._research.get_sources(session_id)

    def rate_source(self, source_id: str, rating: int) -> None:
        return self._research.rate_source(source_id, rating)

    def get_source_count(self, session_id: str) -> int:
        return self._research.get_source_count(session_id)

    # ─── 6-step framework fields ──────────────────────────────

    def update_six_step_fields(
        self, session_id: str,
        clarification: dict | None = None,
        reasoning: dict | None = None,
        structure: dict | None = None,
        self_loop_counts: dict | None = None,
        self_loop_history: list | None = None,
        evidence_scores: dict | None = None,
    ) -> None:
        return self._research.update_six_step_fields(
            session_id, clarification, reasoning, structure,
            self_loop_counts, self_loop_history, evidence_scores,
        )

    def get_six_step_fields(self, session_id: str) -> dict[str, Any]:
        return self._research.get_six_step_fields(session_id)

    # ─── Event log persistence ───────────────────────────────

    def append_events(self, session_id: str, events: list[dict]) -> int:
        return self._research.append_events(session_id, events)

    def get_events(self, session_id: str) -> list[dict]:
        return self._research.get_events(session_id)

    # ─── research_steps ──────────────────────────────────────

    def save_step(
        self, session_id: str, step_num: int, action: str,
        status: str = "pending", thought: str | None = None,
        result: Any = None, duration_ms: int = 0,
    ) -> None:
        return self._research.save_step(
            session_id, step_num, action, status,
            thought, result, duration_ms,
        )

    def get_step(self, session_id: str, step_num: int) -> dict | None:
        return self._research.get_step(session_id, step_num)

    def list_steps(self, session_id: str) -> list[dict]:
        return self._research.list_steps(session_id)

    def delete_steps(self, session_id: str) -> int:
        return self._research.delete_steps(session_id)

    def update_step_status(
        self, session_id: str, step_num: int, status: str,
    ) -> None:
        return self._research.update_step_status(
            session_id, step_num, status,
        )

    def save_research_state(
        self, session_id: str, step_num: int, state: dict,
    ) -> str:
        return self._research.save_research_state(
            session_id, step_num, state,
        )

    def load_research_state(
        self, session_id: str, step_num: int,
    ) -> dict | None:
        return self._research.load_research_state(session_id, step_num)


__all__ = ["ResearchDelegate"]
