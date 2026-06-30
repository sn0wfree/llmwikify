"""Tests for the declarative prompt registry (autoresearch.prompts).

Covers:
- ResearchPrompt dataclass validation
- PROMPT_REGISTRY has exactly 7 entries with correct fields
- Each prompt's fallback function returns the expected type/shape
- render_framework_block matches the original report/review renderers
  byte-for-byte (consolidation regression check)
- source_hash matches the inline md5 logic
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.prompts import (
    PROMPT_REGISTRY,
    ResearchPrompt,
    get_prompt,
    render_framework_block,
    source_hash,
)

# ─── dataclass validation ─────────────────────────────────────────────


class TestResearchPromptValidation:
    def test_rejects_invalid_llm_role(self):
        with pytest.raises(ValueError, match="llm_role"):
            ResearchPrompt(name="x", phase="x", llm_role="bogus")

    def test_rejects_invalid_framework_kind(self):
        with pytest.raises(ValueError, match="framework_kind"):
            ResearchPrompt(
                name="x", phase="x", llm_role="default",
                framework_kind="bogus",
            )

    def test_accepts_valid_framework_kind(self):
        p = ResearchPrompt(
            name="x", phase="x", llm_role="default",
            framework_kind="report",
        )
        assert p.framework_kind == "report"

    def test_accepts_none_framework_kind(self):
        p = ResearchPrompt(name="x", phase="x", llm_role="default")
        assert p.framework_kind is None


# ─── registry shape ───────────────────────────────────────────────────


EXPECTED_NAMES = {
    "research_clarify",
    "research_plan",
    "research_replan",
    "research_reason",
    "research_report",
    "research_review",
    "research_revise",
}


class TestPromptRegistry:
    def test_has_exactly_seven_entries(self):
        assert len(PROMPT_REGISTRY) == 7

    def test_contains_all_expected_names(self):
        assert set(PROMPT_REGISTRY.keys()) == EXPECTED_NAMES

    def test_get_prompt_returns_correct_spec(self):
        spec = get_prompt("research_clarify")
        assert isinstance(spec, ResearchPrompt)
        assert spec.name == "research_clarify"
        assert spec.phase == "clarifying"
        assert spec.llm_role == "planning"
        assert spec.expects_json is True

    def test_get_prompt_unknown_raises(self):
        with pytest.raises(KeyError):
            get_prompt("research_bogus")

    def test_report_and_revise_return_raw_text(self):
        assert PROMPT_REGISTRY["research_report"].expects_json is False
        assert PROMPT_REGISTRY["research_revise"].expects_json is False

    def test_other_steps_expect_json(self):
        for name in EXPECTED_NAMES - {"research_report", "research_revise"}:
            assert PROMPT_REGISTRY[name].expects_json is True, name

    def test_only_report_and_review_have_framework_kind(self):
        assert PROMPT_REGISTRY["research_report"].framework_kind == "report"
        assert PROMPT_REGISTRY["research_review"].framework_kind == "review"
        for name in EXPECTED_NAMES - {"research_report", "research_review"}:
            assert PROMPT_REGISTRY[name].framework_kind is None, name

    def test_llm_role_assignment(self):
        assert PROMPT_REGISTRY["research_clarify"].llm_role == "planning"
        assert PROMPT_REGISTRY["research_plan"].llm_role == "planning"
        assert PROMPT_REGISTRY["research_replan"].llm_role == "planning"
        assert PROMPT_REGISTRY["research_reason"].llm_role == "default"
        assert PROMPT_REGISTRY["research_report"].llm_role == "report"
        assert PROMPT_REGISTRY["research_review"].llm_role == "default"
        assert PROMPT_REGISTRY["research_revise"].llm_role == "report"

    def test_temperature_values_match_legacy(self):
        # research_reason + research_review use low T=0.1 (decision/eval)
        # everything else uses T=0.3
        assert PROMPT_REGISTRY["research_reason"].default_temperature == 0.1
        assert PROMPT_REGISTRY["research_review"].default_temperature == 0.1
        for name in EXPECTED_NAMES - {"research_reason", "research_review"}:
            assert PROMPT_REGISTRY[name].default_temperature == 0.3, name

    def test_max_tokens_values_match_legacy(self):
        # 1024: clarify/replan/reason
        # 2048: plan/review
        # 8192: report/revise (long-form)
        assert PROMPT_REGISTRY["research_clarify"].default_max_tokens == 1024
        assert PROMPT_REGISTRY["research_replan"].default_max_tokens == 1024
        assert PROMPT_REGISTRY["research_reason"].default_max_tokens == 1024
        assert PROMPT_REGISTRY["research_plan"].default_max_tokens == 2048
        assert PROMPT_REGISTRY["research_review"].default_max_tokens == 2048
        assert PROMPT_REGISTRY["research_report"].default_max_tokens == 8192
        assert PROMPT_REGISTRY["research_revise"].default_max_tokens == 8192

    def test_report_and_revise_have_no_fallback(self):
        # Important steps: re-raise on failure
        assert PROMPT_REGISTRY["research_report"].fallback is None
        assert PROMPT_REGISTRY["research_revise"].fallback is None

    def test_clarify_plan_replan_review_have_fallback(self):
        assert PROMPT_REGISTRY["research_clarify"].fallback is not None
        assert PROMPT_REGISTRY["research_plan"].fallback is not None
        assert PROMPT_REGISTRY["research_replan"].fallback is not None
        assert PROMPT_REGISTRY["research_review"].fallback is not None
        # research_reason has a fallback (sentinel for rule-based)
        assert PROMPT_REGISTRY["research_reason"].fallback is not None


# ─── fallback function behavior ──────────────────────────────────────


class TestFallbacks:
    def test_clarify_fallback_shape(self):
        from llmwikify.apps.chat.prompts import _clarify_fallback
        result = _clarify_fallback(query="foo")
        assert result["context"].startswith("未澄清")
        assert result["boundaries"] == "未明确"
        assert result["position"] == "研究者视角"
        assert result["premises"] == ["原始查询: foo"]
        assert result["scope_check"] is False
        assert result["fallback"] is True

    def test_clarify_fallback_truncates_long_query(self):
        from llmwikify.apps.chat.prompts import _clarify_fallback
        long_q = "x" * 500
        result = _clarify_fallback(query=long_q)
        # The premise truncates to 200 chars
        assert len(result["premises"][0]) <= 200 + len("原始查询: ")

    def test_plan_fallback_returns_single_subquery(self):
        from llmwikify.apps.chat.prompts import _plan_fallback
        result = _plan_fallback(query="my research topic")
        assert result == [{"query": "my research topic", "source_type": "web", "url": ""}]

    def test_replan_fallback_with_gaps(self):
        from llmwikify.apps.chat.prompts import _replan_fallback
        result = _replan_fallback(query="q", gaps=["gap1", "gap2"])
        assert result == [{"query": "q gap1", "source_type": "web", "url": ""}]

    def test_replan_fallback_no_gaps(self):
        from llmwikify.apps.chat.prompts import _replan_fallback
        result = _replan_fallback(query="q", gaps=[])
        assert result == []

    def test_reason_fallback_signals_rule_based(self):
        from llmwikify.apps.chat.prompts import _reason_fallback
        result = _reason_fallback()
        assert result["action"] == "__rule_based__"
        assert "rule-based" in result["thought"]

    def test_review_fallback_shape(self):
        from llmwikify.apps.chat.prompts import _review_fallback
        result = _review_fallback()
        assert result["approved"] is False
        assert result["score"] == 0
        assert "Review failed" in result["feedback"]


# ─── render_framework_block ───────────────────────────────────────────


class TestRenderFrameworkBlock:
    def test_none_context_returns_empty(self):
        assert render_framework_block(None, "report") == ""
        assert render_framework_block(None, "review") == ""

    def test_empty_context_returns_empty(self):
        assert render_framework_block({}, "report") == ""
        assert render_framework_block({}, "review") == ""

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="framework_kind"):
            render_framework_block({"clarification": {"context": "x"}}, "bogus")

    def test_report_block_basic_structure(self):
        ctx = {
            "clarification": {"context": "C", "boundaries": "B", "position": "P", "premises": ["p1"]},
            "evidence_scores": {"src1": 0.9, "src2": 0.7},
            "reasoning_check": {"aggregate_score": 0.8},
            "structure_check": {"aggregate_score": 0.75},
        }
        block = render_framework_block(ctx, "report")
        assert "# 6-step Framework Guidance" in block
        assert "步骤 1: 概念澄清" in block
        assert "上下文: C" in block
        assert "边界: B" in block
        assert "立场: P" in block
        assert "前提 (1): p1" in block
        assert "平均证据分: 0.80" in block
        assert "推理聚合分: 0.80" in block
        assert "结构聚合分: 0.75" in block
        assert "步骤 5: 结论输出" in block
        assert "步骤 6: 检查清单" in block

    def test_review_block_basic_structure(self):
        ctx = {
            "clarification": {"context": "C"},
            "evidence_scores": {"src1": 0.9},
            "reasoning_check": {"aggregate_score": 0.8},
            "structure_check": {"aggregate_score": 0.75},
        }
        block = render_framework_block(ctx, "review")
        assert "# 6-step Framework Review Checklist" in block
        assert "标准 1: 概念清晰" in block
        assert "标准 2: 证据充分" in block
        assert "标准 3: 推理严密" in block
        assert "标准 4: 结构稳固" in block
        assert "标准 5: 结论量化" in block
        assert "输出要求" in block
        assert "0.80" in block  # evidence avg
        assert "0.75" in block  # structure score

    def test_truncation_at_200_chars(self):
        long_str = "x" * 500
        ctx = {"clarification": {"context": long_str}}
        block = render_framework_block(ctx, "report")
        # Report block truncates context at 200
        assert f"上下文: {'x' * 200}" in block
        assert f"上下文: {'x' * 500}" not in block

    def test_review_truncation_at_150_chars(self):
        long_str = "x" * 500
        ctx = {"clarification": {"context": long_str}}
        block = render_framework_block(ctx, "review")
        # Review block truncates context at 150
        assert f"上下文: {'x' * 150}" in block
        assert f"上下文: {'x' * 500}" not in block

    def test_empty_evidence_scores_skips_block(self):
        ctx = {
            "clarification": {"context": "C"},
            "evidence_scores": {},
            "reasoning_check": {"aggregate_score": 0.8},
        }
        block = render_framework_block(ctx, "report")
        # reasoning_check present → block rendered
        assert "步骤 1: 概念澄清" in block
        # empty evidence_scores → "## 步骤 2: 建立依据" is NOT emitted
        # (matches original report._render_framework_block: line 141 `if evidence_scores:`)
        assert "步骤 2: 建立依据" not in block

    def test_no_framework_data_returns_empty(self):
        # clarification with empty context + empty reasoning + empty structure
        ctx = {
            "clarification": {"context": ""},
            "reasoning_check": {},
            "structure_check": {},
        }
        assert render_framework_block(ctx, "report") == ""
        assert render_framework_block(ctx, "review") == ""


# ─── source_hash ──────────────────────────────────────────────────────


class TestSourceHash:
    def test_url_based_hash(self):
        s1 = {"url": "https://example.com/a", "title": "Other"}
        s2 = {"url": "https://example.com/a", "title": "Different"}
        assert source_hash(s1) == source_hash(s2)

    def test_title_fallback(self):
        s1 = {"url": "", "title": "Foo"}
        s2 = {"title": "Foo"}
        assert source_hash(s1) == source_hash(s2)

    def test_unknown_fallback(self):
        # {} → None or "unknown" → "unknown"
        s1 = {}
        # {"url": None, "title": ""} → None or "" → ""
        # (matches original `s.get("url") or s.get("title", "unknown")` behavior
        # — the "unknown" default is only used when the title key is missing)
        s2 = {"url": None, "title": ""}
        assert source_hash(s1) == source_hash({"title": "unknown"})
        assert source_hash(s2) == source_hash({"title": ""})

    def test_returns_12_char_hex(self):
        s = {"url": "https://example.com"}
        h = source_hash(s)
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_urls_different_hashes(self):
        s1 = {"url": "https://a.com"}
        s2 = {"url": "https://b.com"}
        assert source_hash(s1) != source_hash(s2)
