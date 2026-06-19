"""Research report review and revision."""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.apps.chat.prompts import _review_fallback
from llmwikify.apps.chat.prompts import source_hash as _source_hash
from llmwikify.apps.chat.research_engine.llm_step import run_prompt

logger = logging.getLogger(__name__)


class _ReviewerCtx:
    """Minimal ctx-like object for run_prompt.

    The reviewer only has a single LLM client (the default one) so
    the other two default to the same client. ``metrics`` is
    optional (None if the caller does not track them).
    """

    def __init__(
        self, llm_client: Any, config: dict[str, Any],
        metrics: Any = None,
    ):
        self.default_llm = llm_client
        self.planning_llm = llm_client
        self.report_llm = llm_client
        self.config = config
        self.metrics = metrics


class ResearchReviewer:
    """Evaluates research report quality and provides feedback."""

    def __init__(
        self, wiki: Any, llm_client: Any, config: dict[str, Any],
        metrics: Any = None,
    ):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config
        self.metrics = metrics
        self.min_score = config.get("quality_threshold", 7)

    def _as_ctx(self) -> _ReviewerCtx:
        """Build a ctx-like object for run_prompt."""
        return _ReviewerCtx(self.llm_client, self.config, metrics=self.metrics)

    async def review(self, query: str, report: str, sources: list[dict[str, Any]],
                    six_step_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Review a research report for quality.

        When six_step_context is provided, the review prompt is enriched
        with the 5 framework checks (clarity, evidence, reasoning,
        structure, conclusion-quantification) and the LLM is asked to
        score against them. Returns:

            {"approved": bool, "feedback": str, "issues": list[str],
             "score": int, "framework_scores": dict[str, int]?}

        Migrated to use ``run_prompt`` (commit 4 of the prompt-system
        refactor). On failure, returns the deterministic fallback via
        ``_review_fallback`` from ``prompts.py``.
        """
        try:
            result = await run_prompt(
                self._as_ctx(), "research_review",
                six_step_context=six_step_context,
                query=query,
                report=report,
                source_count=len(sources),
            )
        except Exception as e:
            logger.warning("Report review failed: %s", e)
            return _review_fallback(error=e)

        # Normalize the result with defaults
        result.setdefault("approved", result.get("score", 0) >= self.min_score)
        result.setdefault("feedback", "")
        result.setdefault("issues", [])
        result.setdefault("score", 0)
        return result


class ResearchRevisor:
    """Revises a research report based on reviewer feedback."""

    def __init__(
        self, wiki: Any, llm_client: Any, config: dict[str, Any],
        metrics: Any = None,
    ):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config
        self.metrics = metrics

    def _as_ctx(self) -> _ReviewerCtx:
        """Build a ctx-like object for run_prompt."""
        return _ReviewerCtx(self.llm_client, self.config, metrics=self.metrics)

    async def revise(
        self,
        report: str,
        issues: list[str],
        sources: list[dict[str, Any]],
    ) -> str:
        """Revise a report to address reviewer issues.

        Returns revised markdown report.

        Migrated to use ``run_prompt`` (commit 4 of the prompt-system
        refactor). No fallback — re-raises on failure (the engine
        catches and marks the session as 'error').
        """
        issues_text = "\n".join(f"- {issue}" for issue in issues)

        # Build source reference for revision (uses shared source_hash helper)
        source_refs: list[str] = []
        for s in sources:
            h = _source_hash(s)
            source_refs.append(
                f"[{h}] {s.get('source_type', '')}: {s.get('title', '')} — {s.get('url', '')}"
            )

        return await run_prompt(
            self._as_ctx(), "research_revise",
            issues_text=issues_text,
            source_refs="\n".join(source_refs),
            report=report,
        )
