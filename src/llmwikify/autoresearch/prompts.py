"""Declarative prompt registry for the 6-step framework.

The 6-step framework has 7 LLM call sites (clarify, plan, replan, reason,
report, review, revise). This module centralizes their declarations in
a single dataclass + dict so the actual LLM call layer (see
``llm_step.py``) can be a single thin wrapper.

Each ``ResearchPrompt`` declares:

  * name:           registry key used to look up the YAML template
  * phase:          the engine phase this step belongs to (for status
                    events, debug logs)
  * llm_role:       which LLM client to use — "planning" / "default" /
                    "report". The engine resolves the actual client at
                    call time.
  * expects_json:   if True, run_prompt() parses the LLM response as
                    JSON. If False, returns the raw string (used for
                    markdown report / revise outputs).
  * default_max_tokens / default_temperature: fallbacks if neither
                    caller config nor the YAML provides an override.
  * framework_kind: if set, run_prompt() auto-injects a framework
                    guidance block (system message) before the YAML
                    messages. Used by report ("report") and review
                    ("review"). None for steps that do not benefit from
                    framework augmentation.
  * fallback:       a callable returning the deterministic fallback
                    value when the LLM call fails after retries. The
                    callable receives the same kwargs passed to
                    ``run_prompt()`` so it can use them in the fallback
                    (e.g. plan uses the query string). If None, the
                    exception is re-raised.

Helpers exported:

  * ``render_framework_block(six_step_context, kind)`` — consolidates
    the two hand-rolled render functions that previously lived in
    ``report._render_framework_block`` and
    ``review._render_framework_review_block``. Returns the same text
    for the same inputs.

  * ``source_hash(source)`` — the md5-based hash used for inline
    ``[[Source:hash]]`` citations. Consolidates the duplicate md5 logic
    in ``report._build_source_map`` and ``review.revise``.

The prompt YAMLs themselves live in
``llmwikify/prompts/_defaults/research_*.yaml`` and are loaded by
``llmwikify.core.prompt_registry.PromptRegistry`` at call time. This
module is purely declarative; it never calls an LLM.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ─── 6-step framework context augmentation ────────────────────────────


def render_framework_block(
    six_step_context: dict[str, Any] | None,
    kind: str,
) -> str:
    """Render the 6-step framework context as a system-prompt block.

    Consolidates the two hand-rolled render functions that previously
    lived in ``report._render_framework_block`` and
    ``review._render_framework_review_block``. Returns the exact same
    text for the same inputs to preserve behavior.

    Args:
        six_step_context: The consolidated 6-step context dict
            (clarification, evidence_scores, reasoning_check,
            structure_check). If empty, returns "".
        kind: Either "report" or "review". The block content differs
            per consumer.

    Returns:
        A multi-line string suitable for use as a system message.
        Returns "" if framework was not actually run.
    """
    if not six_step_context:
        return ""
    clarification = six_step_context.get("clarification") or {}
    reasoning = six_step_context.get("reasoning_check") or {}
    structure = six_step_context.get("structure_check") or {}
    evidence_scores = six_step_context.get("evidence_scores") or {}

    # Skip if no framework data at all (matches both original
    # implementations)
    if not (clarification.get("context") or reasoning or structure):
        return ""

    if kind == "report":
        return _render_report_block(clarification, reasoning, structure, evidence_scores)
    if kind == "review":
        return _render_review_block(clarification, reasoning, structure, evidence_scores)
    raise ValueError(f"Unknown framework_kind: {kind!r} (expected 'report' or 'review')")


def _render_report_block(
    clarification: dict[str, Any],
    reasoning: dict[str, Any],
    structure: dict[str, Any],
    evidence_scores: Any,
) -> str:
    """Render the report-step framework block (verbatim from report.py:107-178)."""
    lines = ["# 6-step Framework Guidance (this report should reflect all 6 steps)\n"]

    if clarification.get("context"):
        lines.append("## 步骤 1: 概念澄清")
        lines.append(f"- 上下文: {clarification.get('context', '')[:200]}")
        if clarification.get("boundaries"):
            lines.append(f"- 边界: {clarification['boundaries'][:200]}")
        if clarification.get("position"):
            lines.append(f"- 立场: {clarification['position'][:200]}")
        premises = clarification.get("premises") or []
        if premises:
            lines.append(f"- 前提 ({len(premises)}): {'; '.join(str(p)[:80] for p in premises[:5])}")
        lines.append("")

    if evidence_scores:
        avg_ev = (
            sum(evidence_scores.values()) / max(1, len(evidence_scores))
            if isinstance(evidence_scores, dict)
            else 0
        )
        lines.append("## 步骤 2: 建立依据")
        lines.append(f"- 平均证据分: {avg_ev:.2f}")
        lines.append("")

    if reasoning.get("aggregate_score") is not None:
        lines.append("## 步骤 3: 推理严密")
        lines.append(f"- 推理聚合分: {reasoning['aggregate_score']:.2f}")
        per_dim = reasoning.get("scores") or {}
        for dim, score in list(per_dim.items())[:3]:
            lines.append(f"  - {dim}: {score:.2f}")
        lines.append("")

    if structure.get("aggregate_score") is not None:
        lines.append("## 步骤 4: 稳固结构")
        lines.append(f"- 结构聚合分: {structure['aggregate_score']:.2f}")
        per_layer = structure.get("scores") or {}
        for layer, score in per_layer.items():
            lines.append(f"  - {layer}: {score:.2f}")
        lines.append("")

    lines.append("## 步骤 5: 结论输出（你正在写）")
    lines.append("- 输出结构化 markdown 报告")
    lines.append("- 每个结论引用证据（[[Source:hash]] 格式）")
    lines.append("- 量化不确定性（可能/likely/approximately）")
    lines.append("")
    lines.append("## 步骤 6: 检查清单（评审阶段会执行）")
    lines.append("- 概念是否清晰？边界是否明确？")
    lines.append("- 证据是否充分？推理是否严密？")
    lines.append("- 结构是否稳固？结论是否量化？")
    return "\n".join(lines)


def _render_review_block(
    clarification: dict[str, Any],
    reasoning: dict[str, Any],
    structure: dict[str, Any],
    evidence_scores: Any,
) -> str:
    """Render the review-step framework block (verbatim from review.py:79-146)."""
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


# ─── source hash helper ───────────────────────────────────────────────


def source_hash(source: dict[str, Any]) -> str:
    """Compute the 12-char md5 hash used for inline citations.

    Consolidates the duplicate md5 logic in ``report._build_source_map``
    and ``review.revise``. Behavior is identical: hash the url if
    present, else the title, else "unknown". Truncate to 12 hex chars.

    Args:
        source: A source dict with optional "url" and "title" fields.

    Returns:
        12-character lowercase hex string.
    """
    key = source.get("url") or source.get("title", "unknown")
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ─── fallback functions ───────────────────────────────────────────────


def _clarify_fallback(
    query: str, error: Exception | None = None, **_kwargs: Any,
) -> dict[str, Any]:
    """Fallback for research_clarify (verbatim from clarifier._fallback:188-206)."""
    reason = str(error) if error else "LLM call failed"
    return {
        "context": f"未澄清（{reason}），使用原始查询作为语境",
        "boundaries": "未明确",
        "position": "研究者视角",
        "premises": [f"原始查询: {query[:200]}"],
        "scope_check": False,
        "fallback": True,
        "fallback_reason": reason,
    }


def _plan_fallback(
    query: str, error: Exception | None = None, **_kwargs: Any,
) -> list[dict[str, Any]]:
    """Fallback for research_plan (verbatim from actions._plan_sub_queries:161)."""
    return [{"query": query, "source_type": "web", "url": ""}]


def _replan_fallback(
    query: str,
    gaps: list[str] | None = None,
    error: Exception | None = None,
    **_kwargs: Any,
) -> list[dict[str, Any]]:
    """Fallback for research_replan (verbatim from actions._plan_for_gaps:238)."""
    if not gaps:
        return []
    return [{"query": f"{query} {gaps[0]}", "source_type": "web", "url": ""}]


def _review_fallback(
    error: Exception | None = None, **_kwargs: Any,
) -> dict[str, Any]:
    """Fallback for research_review (verbatim from review.py:77)."""
    reason = f"Review failed: {error}" if error else "Review failed: LLM call failed"
    return {
        "approved": False,
        "feedback": reason,
        "issues": ["Review LLM call failed"],
        "score": 0,
    }


def _reason_fallback(
    error: Exception | None = None, **_kwargs: Any,
) -> dict[str, str]:
    """Fallback for research_reason.

    The original ``_llm_reason`` falls back to a rule-based decision
    tree in the same code path, not to a static dict. We preserve that
    semantic by returning a sentinel that signals the caller to apply
    the rule-based fallback. The actual rule-based logic stays in
    ``engine.py:_rule_based_reason`` (unchanged in this refactor).
    """
    return {"thought": "LLM failed, applying rule-based fallback", "action": "__rule_based__"}


# ─── ResearchPrompt dataclass + registry ──────────────────────────────


@dataclass
class ResearchPrompt:
    """Declarative description of one LLM call site in the 6-step framework."""

    name: str
    phase: str
    llm_role: str
    expects_json: bool = True
    default_max_tokens: int = 2048
    default_temperature: float = 0.3
    framework_kind: str | None = None
    fallback: Callable[..., Any] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.llm_role not in ("default", "planning", "report"):
            raise ValueError(
                f"ResearchPrompt.llm_role must be default/planning/report, got {self.llm_role!r}"
            )
        if self.framework_kind is not None and self.framework_kind not in ("report", "review"):
            raise ValueError(
                f"ResearchPrompt.framework_kind must be report/review/None, got {self.framework_kind!r}"
            )


PROMPT_REGISTRY: dict[str, ResearchPrompt] = {
    "research_clarify": ResearchPrompt(
        name="research_clarify",
        phase="clarifying",
        llm_role="planning",
        expects_json=True,
        default_max_tokens=1024,
        default_temperature=0.3,
        fallback=_clarify_fallback,
        description="Step 1: lock down context, boundaries, position, premises",
    ),
    "research_plan": ResearchPrompt(
        name="research_plan",
        phase="planning",
        llm_role="planning",
        expects_json=True,
        default_max_tokens=2048,
        default_temperature=0.3,
        fallback=_plan_fallback,
        description="Step 2: decompose query into 3-10 sub-queries",
    ),
    "research_replan": ResearchPrompt(
        name="research_replan",
        phase="planning",
        llm_role="planning",
        expects_json=True,
        default_max_tokens=1024,
        default_temperature=0.3,
        fallback=_replan_fallback,
        description="Step 2b: fill knowledge gaps with 1-5 sub-queries",
    ),
    "research_reason": ResearchPrompt(
        name="research_reason",
        phase="reasoning",
        llm_role="default",
        expects_json=True,
        default_max_tokens=1024,
        default_temperature=0.1,
        fallback=_reason_fallback,
        description="ReAct: pick next action (plan/gather/analyze/.../done)",
    ),
    "research_report": ResearchPrompt(
        name="research_report",
        phase="reporting",
        llm_role="report",
        expects_json=False,
        default_max_tokens=8192,
        default_temperature=0.3,
        framework_kind="report",
        fallback=None,  # important step: re-raise on failure
        description="Step 5: generate markdown report (raw text, not JSON)",
    ),
    "research_review": ResearchPrompt(
        name="research_review",
        phase="reviewing",
        llm_role="default",
        expects_json=True,
        default_max_tokens=2048,
        default_temperature=0.1,
        framework_kind="review",
        fallback=_review_fallback,
        description="Step 6: score report 1-10 + per-criterion framework scores",
    ),
    "research_revise": ResearchPrompt(
        name="research_revise",
        phase="revising",
        llm_role="report",
        expects_json=False,
        default_max_tokens=8192,
        default_temperature=0.3,
        fallback=None,  # important step: re-raise on failure
        description="Step 6b: apply reviewer issues to report (raw markdown)",
    ),
}


def get_prompt(name: str) -> ResearchPrompt:
    """Look up a ResearchPrompt by name. Raises KeyError if not found."""
    return PROMPT_REGISTRY[name]
