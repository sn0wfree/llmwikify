"""Research report review and revision."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ResearchReviewer:
    """Evaluates research report quality and provides feedback."""

    def __init__(self, wiki: Any, llm_client: Any, config: dict[str, Any]):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config
        self.min_score = config.get("quality_threshold", 7)

    async def review(self, query: str, report: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
        """Review a research report for quality.

        Returns:
            {"approved": bool, "feedback": str, "issues": list[str], "score": int}
        """
        from ...kernel.wiki.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")

        messages = registry.get_messages(
            "research_review",
            query=query,
            report=report,
            source_count=len(sources),
        )
        api_params = registry.get_api_params("research_review")

        try:
            import asyncio
            import json as json_mod
            from .retry import retry_async

            max_attempts = self.config.get("max_retry_attempts", 3)
            call_timeout = self.config.get("llm_call_timeout_seconds", 120)

            async def _call_review() -> dict:
                def _sync_call():
                    raw = self.llm_client.chat(
                        messages,
                        json_mode=api_params.get("json_mode", True),
                        max_tokens=api_params.get("max_tokens", 2048),
                        temperature=api_params.get("temperature", 0.1),
                    )
                    raw = raw.strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                        if raw.endswith("```"):
                            raw = raw[:-3]
                        raw = raw.strip()
                    return json_mod.loads(raw)
                return await asyncio.to_thread(_sync_call)

            result = await retry_async(_call_review, max_attempts=max_attempts, base_delay=2.0, call_timeout=call_timeout)
            result.setdefault("approved", result.get("score", 0) >= self.min_score)
            result.setdefault("feedback", "")
            result.setdefault("issues", [])
            result.setdefault("score", 0)
            return result
        except Exception as e:
            logger.warning("Report review failed: %s", e)
            return {"approved": False, "feedback": f"Review failed: {e}", "issues": ["Review LLM call failed"], "score": 0}


class ResearchRevisor:
    """Revises a research report based on reviewer feedback."""

    def __init__(self, wiki: Any, llm_client: Any, config: dict[str, Any]):
        self.wiki = wiki
        self.llm_client = llm_client
        self.config = config

    async def revise(
        self,
        report: str,
        issues: list[str],
        sources: list[dict[str, Any]],
    ) -> str:
        """Revise a report to address reviewer issues.

        Returns revised markdown report.
        """
        import hashlib
        from ...kernel.wiki.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")

        issues_text = "\n".join(f"- {issue}" for issue in issues)

        # Build source reference for revision
        source_refs: list[str] = []
        for s in sources:
            key = s.get("url") or s.get("title", "unknown")
            h = hashlib.md5(key.encode()).hexdigest()[:12]
            source_refs.append(f"[{h}] {s.get('source_type', '')}: {s.get('title', '')} — {s.get('url', '')}")

        messages = registry.get_messages(
            "research_revise",
            issues_text=issues_text,
            source_refs="\n".join(source_refs),
            report=report,
        )
        api_params = registry.get_api_params("research_revise")

        import asyncio
        from .retry import retry_async

        max_attempts = self.config.get("max_retry_attempts", 3)
        call_timeout = self.config.get("llm_call_timeout_seconds", 120)

        async def _call_revise() -> str:
            return await asyncio.to_thread(
                self.llm_client.chat, messages,
                max_tokens=api_params.get("max_tokens", 8192),
                temperature=api_params.get("temperature", 0.3),
            )

        revised = await retry_async(_call_revise, max_attempts=max_attempts, base_delay=2.0, call_timeout=call_timeout)
        return revised
