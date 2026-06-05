"""Research concept clarifier.

The first of six steps in the structured reasoning framework. Locks down
the research context, boundaries, position, and premises before planning.
"""

from __future__ import annotations

import logging
from typing import Any

from llmwikify.autoresearch.llm_step import run_prompt
from llmwikify.autoresearch.prompts import _clarify_fallback

logger = logging.getLogger(__name__)


class _ClarifierCtx:
    """Minimal ctx-like object for run_prompt.

    ``run_prompt`` needs ``default_llm``, ``planning_llm``, ``report_llm``,
    and ``config``. The clarifier only has a single LLM client (the
    planning one) so the other two default to the same client.
    ``metrics`` is optional (None if the caller does not track them).
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


class ResearchClarifier:
    """Clarify a research query before planning.

    Output schema:
    {
        "context": "Research context (scope, time/space bounds)",
        "boundaries": "Boundary conditions (stakeholders, conventions)",
        "position": "Position (role/viewpoint)",
        "premises": "Premise assumptions list",
        "scope_check": "Whether scope is researchable (true/false)"
    }
    """

    def __init__(
        self, llm_client: Any, config: dict[str, Any] | None = None,
        metrics: Any = None,
    ):
        self.llm_client = llm_client
        self.config = config or {}
        self.metrics = metrics

    def _as_ctx(self) -> _ClarifierCtx:
        """Build a ctx-like object for ``run_prompt``."""
        return _ClarifierCtx(self.llm_client, self.config, metrics=self.metrics)

    async def clarify(self, query: str, wiki_context: str = "") -> dict[str, Any]:
        """Clarify the research query.

        Returns:
            Clarification dict with context, boundaries, position, premises,
            scope_check. Falls back to a minimal dict if LLM call fails.
        """
        try:
            result = await run_prompt(
                self._as_ctx(), "research_clarify",
                query=query, wiki_context=wiki_context,
            )
        except Exception as e:
            logger.warning("Clarifier LLM call failed: %s, using fallback", e)
            return _clarify_fallback(query=query, error=e)
        return self._normalize(result)

    async def clarify_with_loop(
        self,
        query: str,
        wiki_context: str = "",
        budget_remaining: float = 1.0,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Clarify with self-loop on scope_check=false.

        Returns:
            (clarification, loop_history). The history contains one entry
            per attempt with type/attempt/reason/scope_check fields.
        """
        max_retries = self.config.get("clarify_max_retries", 2)
        budget_ratio = self.config.get("self_loop_budget_ratio", 0.3)
        loop_history: list[dict[str, Any]] = []

        current_query = query
        current_context = wiki_context
        clarification = await self.clarify(current_query, current_context)
        loop_history.append({
            "type": "clarify",
            "attempt": 0,
            "scope_check": clarification.get("scope_check", False),
        })

        for attempt in range(1, max_retries + 1):
            # Stop if scope is researchable (genuine clarification succeeded)
            if clarification.get("scope_check", False):
                break
            # Stop if budget is exhausted
            if budget_remaining < budget_ratio:
                logger.warning(
                    "Clarify self-loop budget exhausted (%.0f%% < %.0f%%), using last result",
                    budget_remaining * 100, budget_ratio * 100,
                )
                break

            # If previous attempt was a fallback (LLM parse/exception), retry
            # with the ORIGINAL query — don't narrow using fallback data
            # (fallback has "未明确"/"研究者视角" placeholders that pollute
            # the refinement).
            if clarification.get("fallback"):
                logger.info(
                    "Clarify attempt %d: previous was fallback (%s), retrying with original query",
                    attempt, clarification.get("fallback_reason", "unknown"),
                )
                clarification = await self.clarify(query, wiki_context)
                loop_history.append({
                    "type": "clarify_retry_after_fallback",
                    "attempt": attempt,
                    "scope_check": clarification.get("scope_check", False),
                    "fallback": clarification.get("fallback", False),
                })
                continue

            # Normal path: refine query based on previous clarification and retry
            current_query = self._narrow_query(query, clarification)
            current_context = self._enrich_context(wiki_context, clarification)
            clarification = await self.clarify(current_query, current_context)
            loop_history.append({
                "type": "clarify_retry",
                "attempt": attempt,
                "scope_check": clarification.get("scope_check", False),
            })

        # Final warning if scope still not researchable
        if not clarification.get("scope_check", False) and len(loop_history) > 1:
            logger.warning(
                "Clarify self-loop exhausted after %d attempts, scope_check still false",
                len(loop_history),
            )
            clarification.setdefault("warnings", []).append(
                "澄清重试超限，使用最后一次结果"
            )

        return clarification, loop_history

    def _normalize(self, result: dict[str, Any]) -> dict[str, Any]:
        """Normalize the LLM response into a typed dict.

        Same shape as the legacy ``_parse_response`` (sans fallback
        handling, which is now in ``_clarify_fallback`` via run_prompt).
        """
        return {
            "context": result.get("context", ""),
            "boundaries": result.get("boundaries", ""),
            "position": result.get("position", ""),
            "premises": result.get("premises", []),
            "scope_check": bool(result.get("scope_check", True)),
        }

    def _narrow_query(self, original: str, prev_clarification: dict) -> str:
        """Narrow the query based on the previous clarification result.
        Prepends the context and boundaries to constrain the scope.
        """
        parts = [original]
        if prev_clarification.get("context"):
            parts.append(f"语境: {prev_clarification['context']}")
        if prev_clarification.get("boundaries"):
            parts.append(f"边界: {prev_clarification['boundaries']}")
        return "\n".join(parts)

    def _enrich_context(self, base: str, clarification: dict) -> str:
        """Enrich wiki context with clarification hints for the next attempt."""
        hints = []
        if clarification.get("context"):
            hints.append(f"上一次澄清的语境: {clarification['context']}")
        if clarification.get("boundaries"):
            hints.append(f"上一次澄清的边界: {clarification['boundaries']}")
        if hints:
            return base + "\n\n" + "\n".join(hints) if base else "\n".join(hints)
        return base
