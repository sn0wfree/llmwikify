"""Research session management with DB persistence."""

from __future__ import annotations

from typing import Any

from ..chat.db import ChatDatabase


class ResearchSessionManager:
    """Manages research session lifecycle and sub-query/source tracking."""

    def __init__(self, db: ChatDatabase):
        self.db = db
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value

    def create_session(self, query: str, wiki_id: str) -> str:
        session_id = self.db.create_research_session(wiki_id, query)
        self._session_id = session_id
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        session = self.db.get_research_session(session_id)
        if session:
            session["sub_queries"] = self.db.get_sub_queries(session_id)
            session["sources"] = self.db.get_sources(session_id)
        return session

    def update_status(
        self,
        session_id: str,
        status: str,
        step: str | None = None,
        progress: float | None = None,
        iteration_round: int | None = None,
        synthesis_json: str | None = None,
        review_json: str | None = None,
    ) -> None:
        self.db.update_research_status(
            session_id, status, step,
            iteration_round=iteration_round,
            synthesis_json=synthesis_json,
            review_json=review_json,
        )
        if progress is not None:
            self.db.update_research_progress(session_id, progress)

    def add_sub_query(self, session_id: str, query: str, source_type: str, url: str | None = None) -> str:
        return self.db.save_sub_query(session_id, query, source_type, url)

    def complete_sub_query(self, sub_query_id: str, result: dict) -> None:
        self.db.update_sub_query(sub_query_id, "done", result=result)

    def fail_sub_query(self, sub_query_id: str, error: str) -> None:
        self.db.update_sub_query(sub_query_id, "failed", error=error)

    def add_source(
        self,
        session_id: str,
        sub_query_id: str,
        source_type: str,
        url: str,
        title: str,
        content_length: int,
        content_preview: str | None = None,
        content: str | None = None,
    ) -> str:
        return self.db.save_source(session_id, sub_query_id, source_type, url, title, content_length, content_preview, content=content)

    def update_source_analysis(self, source_id: str, analysis: dict) -> None:
        self.db.update_source_analysis(source_id, analysis)

    def persist_report(self, session_id: str, result: dict | None = None) -> None:
        """Persist report data without changing status (safe to call mid-pipeline)."""
        import json
        result_json = json.dumps(result) if result else None
        self.db.persist_report(session_id, result_json)

    def finalize(self, session_id: str, result: dict | None = None, wiki_page_name: str | None = None) -> None:
        import json
        result_json = json.dumps(result) if result else None
        self.db.finalize_research(session_id, result_json, wiki_page_name)
