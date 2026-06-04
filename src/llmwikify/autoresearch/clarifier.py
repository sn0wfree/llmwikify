"""Research concept clarifier.

The first of six steps in the structured reasoning framework. Locks down
the research context, boundaries, position, and premises before planning.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from llmwikify.autoresearch._json_utils import safe_json_loads

logger = logging.getLogger(__name__)


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

    def __init__(self, llm_client: Any, config: dict[str, Any] | None = None):
        self.llm_client = llm_client
        self.config = config or {}
        self.max_tokens = self.config.get("llm_call_timeout_seconds", 120)

    async def clarify(self, query: str, wiki_context: str = "") -> dict[str, Any]:
        """Clarify the research query.

        Returns:
            Clarification dict with context, boundaries, position, premises,
            scope_check. Falls back to a minimal dict if LLM call fails.
        """
        try:
            messages = self._build_messages(query, wiki_context)
            raw = await asyncio.to_thread(
                self.llm_client.chat,
                messages,
                json_mode=True,
                max_tokens=1024,
                temperature=0.3,
            )
            return self._parse_response(raw, query)
        except Exception as e:
            logger.warning("Clarifier LLM call failed: %s, using fallback", e)
            return self._fallback(query, reason=str(e))

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

    def _build_messages(self, query: str, wiki_context: str) -> list[dict[str, str]]:
        """Build the LLM messages for clarification."""
        wiki_block = ""
        if wiki_context:
            wiki_block = f"\n\nExisting wiki context:\n{wiki_context[:2000]}"

        return [
            {
                "role": "system",
                "content": (
                    "你是一个研究澄清助手。给定研究主题，你需要：\n\n"
                    "1. **语境**：明确在谈什么，适用范围、可改变范围、约定边界\n"
                    "2. **边界**：识别利益相关方、约定条件\n"
                    "3. **立场**：明确角色视角\n"
                    "4. **前提**：区分必要条件、前提假设\n\n"
                    "返回 JSON：\n"
                    "{\n"
                    '  "context": "研究语境描述",\n'
                    '  "boundaries": "边界条件",\n'
                    '  "position": "立场声明",\n'
                    '  "premises": "前提假设列表",\n'
                    '  "scope_check": true/false\n'
                    "}\n\n"
                    "scope_check=false 的情况：\n"
                    "- 范围太宽泛无法研究\n"
                    "- 前提假设不可靠\n"
                    "- 缺乏明确的研究边界\n"
                ),
            },
            {
                "role": "user",
                "content": f"研究主题：{query}{wiki_block}\n\n请进行概念澄清。",
            },
        ]

    def _parse_response(self, raw: str, query: str) -> dict[str, Any]:
        """Parse the LLM response, handling code-fence wrappers and trailing prose."""
        try:
            result = safe_json_loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Clarify JSON parse failed: %s", e)
            return self._fallback(query, reason=f"JSON parse error: {e}")

        # Normalize
        return {
            "context": result.get("context", ""),
            "boundaries": result.get("boundaries", ""),
            "position": result.get("position", ""),
            "premises": result.get("premises", []),
            "scope_check": bool(result.get("scope_check", True)),
        }

    def _fallback(self, query: str, reason: str = "") -> dict[str, Any]:
        """Deterministic fallback when LLM fails.

        Returns scope_check=False so that clarify_with_loop will retry
        on the next iteration. The previous scope_check=True behavior
        silently used the fallback after a single LLM failure, hiding
        transient errors from operators. Now a JSON-parse failure (or
        LLM call exception) is treated as a signal that the scope is
        unverified, which triggers a retry with the original query.
        """
        return {
            "context": f"未澄清（{reason}），使用原始查询作为语境",
            "boundaries": "未明确",
            "position": "研究者视角",
            "premises": [f"原始查询: {query[:200]}"],
            "scope_check": False,  # 🐛 fix: trigger retry loop on parse failure
            "fallback": True,
            "fallback_reason": reason,
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
