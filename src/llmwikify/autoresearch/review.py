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

    async def review(self, query: str, report: str, sources: list[dict[str, Any]],
                    six_step_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Review a research report for quality.

        When six_step_context is provided, the review prompt is enriched
        with the 5 framework checks (clarity, evidence, reasoning,
        structure, conclusion-quantification) and the LLM is asked to
        score against them. Returns:

            {"approved": bool, "feedback": str, "issues": list[str],
             "score": int, "framework_scores": dict[str, int]?}
        """
        from llmwikify.core.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")

        framework_block = self._render_framework_review_block(six_step_context)

        messages = registry.get_messages(
            "research_review",
            query=query,
            report=report,
            source_count=len(sources),
        )

        if framework_block:
            messages = [
                {"role": "system", "content": framework_block},
                *messages,
            ]

        api_params = registry.get_api_params("research_review")

        try:
            import asyncio
            import json as json_mod
            from llmwikify.autoresearch.retry_managers import retry_async

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

    def _render_framework_review_block(
        self, six_step_context: dict[str, Any] | None
    ) -> str:
        """Render the 5 framework review criteria as a system-prompt block.

        Used in step 6 (检查清单). The reviewer LLM is asked to score
        each criterion 0-10 and report issues per criterion.
        """
        if not six_step_context:
            return ""
        clarification = six_step_context.get("clarification") or {}
        reasoning = six_step_context.get("reasoning_check") or {}
        structure = six_step_context.get("structure_check") or {}
        evidence_scores = six_step_context.get("evidence_scores") or {}

        # Only emit block if framework was actually run
        if not (clarification.get("context") or reasoning or structure):
            return ""

        lines = ["# 6-step Framework Review Checklist\n"]
        lines.append("评审此报告时，请额外按以下 5 个 6 步框架标准评分 (0-10):\n")

        lines.append("## 标准 1: 概念清晰（步骤 1）")
        if clarification.get("context"):
            lines.append(f"- 报告应明确阐述上下文: {clarification['context'][:150]}")
        if clarification.get("boundaries"):
            lines.append(f"- 报告应明确边界: {clarification['boundaries'][:150]}")
        if clarification.get("position"):
            lines.append(f"- 报告应明确立场: {clarification['position'][:150]}")
        lines.append("- score_clarity: (0-10)")
        lines.append("")

        lines.append("## 标准 2: 证据充分（步骤 2）")
        if evidence_scores:
            avg_ev = (
                sum(evidence_scores.values()) / max(1, len(evidence_scores))
                if isinstance(evidence_scores, dict)
                else 0
            )
            lines.append(f"- 报告所用证据平均分: {avg_ev:.2f}")
        lines.append("- 至少 3 个不同来源 + 每个结论有引用")
        lines.append("- score_evidence: (0-10)")
        lines.append("")

        lines.append("## 标准 3: 推理严密（步骤 3）")
        if reasoning.get("aggregate_score") is not None:
            lines.append(f"- 推理链聚合分: {reasoning['aggregate_score']:.2f}")
        lines.append("- 因果连接词 + 假设标注 + 不确定性量化")
        lines.append("- score_reasoning: (0-10)")
        lines.append("")

        lines.append("## 标准 4: 结构稳固（步骤 4）")
        if structure.get("aggregate_score") is not None:
            lines.append(f"- 结构聚合分: {structure['aggregate_score']:.2f}")
        lines.append("- 层次支撑 + 章节完整 + 内部一致")
        lines.append("- score_structure: (0-10)")
        lines.append("")

        lines.append("## 标准 5: 结论量化（步骤 5）")
        lines.append("- 结论应可量化（数字 / 范围 / 概率）")
        lines.append("- 应标注置信度（可能 / likely / approximately）")
        lines.append("- score_conclusion: (0-10)")
        lines.append("")

        lines.append("## 输出要求")
        lines.append('在 issues 列表中按 "标准N: 反馈" 格式补充。')
        lines.append("在 score 中取 5 个标准分数的均值。")
        return "\n".join(lines)


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
        from llmwikify.core.prompt_registry import PromptRegistry
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
        from llmwikify.autoresearch.retry_managers import retry_async

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
