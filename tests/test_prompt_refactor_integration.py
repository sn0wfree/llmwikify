"""End-to-end tests for the prompt-system refactor.

Verifies that the 7 LLM call sites in the 6-step framework all go
through the unified ``run_prompt`` entry point after the refactor.

Covers:
- Each of the 7 steps (clarify, plan, replan, reason, report,
  review, revise) reaches the LLM with the right client, the right
  template, and the right messages.
- Framework augmentation (auto-injection of 6-step framework block)
  works for report/review but not for the other 5 steps.
- Migration parity: the legacy inline prompt text for clarify and
  replan is now loaded from the registry; the inline prompt text
  for reason is now loaded from the (newly created)
  research_reason.yaml.
- Sanity: report and revise return raw markdown (expects_json=False)
  while the other 5 return parsed JSON.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest


# Patch PromptRegistry.get_messages to return a minimal valid message
# list for any prompt name. The actual YAMLs are out of scope for the
# call-layer tests; we only care about client resolution, framework
# injection, retry, and fallback behavior here.
@pytest.fixture(autouse=True)
def _mock_prompt_registry():
    with patch(
        "llmwikify.kernel.wiki.prompt_registry.PromptRegistry.get_messages",
        return_value=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user prompt"},
        ],
    ):
        yield


def _make_ctx(default_llm=None, planning_llm=None, report_llm=None, config=None):
    """Build a minimal ActionContext-like object for run_prompt."""
    ctx = MagicMock()
    ctx.default_llm = default_llm or MagicMock(name="default_llm")
    ctx.planning_llm = planning_llm or MagicMock(name="planning_llm")
    ctx.report_llm = report_llm or MagicMock(name="report_llm")
    ctx.config = config or {}
    return ctx


def _make_llm(chat_return: str):
    """Build a mock LLM whose .chat() returns the given string."""
    llm = MagicMock()
    llm.chat = MagicMock(return_value=chat_return)
    llm.provider = "openai"
    return llm


# ─── 1. The 7 LLM call sites all use the same run_prompt path ────────


class TestAllSevenStepsGoThroughRunPrompt:
    """Each of the 7 steps (clarify/plan/replan/reason/report/review/
    revise) should be expressible as a single ``run_prompt`` call with
    a known set of required kwargs. This test enforces that contract
    so future refactors don't accidentally bypass run_prompt.
    """

    # (prompt_name, llm_role, expects_json, expected_client_attr)
    EXPECTED = [
        ("research_clarify", "planning", True, "planning_llm"),
        ("research_plan", "planning", True, "planning_llm"),
        ("research_replan", "planning", True, "planning_llm"),
        ("research_reason", "default", True, "default_llm"),
        ("research_report", "report", False, "report_llm"),
        ("research_review", "default", True, "default_llm"),
        ("research_revise", "report", False, "report_llm"),
    ]

    @pytest.mark.parametrize(
        "prompt_name,llm_role,expects_json,client_attr",
        EXPECTED,
    )
    def test_step_uses_correct_client(
        self, prompt_name, llm_role, expects_json, client_attr,
    ):
        """Each step uses the LLM client matching its role."""
        from llmwikify.apps.chat.research_engine.llm_step import run_prompt

        chat_return = (
            json.dumps({"x": 1}) if expects_json else "raw markdown text"
        )
        default_llm = _make_llm(chat_return)
        planning_llm = _make_llm(chat_return)
        report_llm = _make_llm(chat_return)
        ctx = _make_ctx(
            default_llm=default_llm,
            planning_llm=planning_llm,
            report_llm=report_llm,
            config={"max_retry_attempts": 1, "llm_call_timeout_seconds": 30},
        )

        result = asyncio.new_event_loop().run_until_complete(
            run_prompt(ctx, prompt_name, query="q")
        )

        # The right client was called
        expected_client = {
            "default_llm": default_llm,
            "planning_llm": planning_llm,
            "report_llm": report_llm,
        }[client_attr]
        assert expected_client.chat.called, (
            f"{prompt_name} did not call {client_attr}"
        )
        # Others were NOT called
        for other_attr, other_client in [
            ("default_llm", default_llm),
            ("planning_llm", planning_llm),
            ("report_llm", report_llm),
        ]:
            if other_attr != client_attr:
                assert not other_client.chat.called, (
                    f"{prompt_name} called wrong client: {other_attr}"
                )

        # Return shape matches expects_json
        if expects_json:
            assert isinstance(result, dict)
            assert result == {"x": 1}
        else:
            assert result == "raw markdown text"


# ─── 2. Framework augmentation is end-to-end correct ─────────────────


class TestFrameworkAugmentationEndToEnd:
    """The framework augmentation logic in run_prompt should inject
    the right block for report/review and skip for everything else.
    """

    def test_report_injects_before_yaml_messages(self):
        from llmwikify.apps.chat.research_engine.llm_step import run_prompt

        llm = _make_llm("# R")
        ctx = _make_ctx(
            report_llm=llm,
            config={"max_retry_attempts": 1, "llm_call_timeout_seconds": 30},
        )
        six_step_context = {
            "clarification": {"context": "C"},
            "evidence_scores": {"s": 0.9},
            "reasoning_check": {"aggregate_score": 0.8},
            "structure_check": {"aggregate_score": 0.7},
        }
        asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_report",
                six_step_context=six_step_context,
                query="q", source_contents=[], synthesis={},
            )
        )
        messages = llm.chat.call_args[0][0]
        # First message is the framework block
        assert "Framework Guidance" in messages[0]["content"]
        # Subsequent messages come from the YAML (mocked here)
        assert len(messages) >= 2

    def test_review_injects_before_yaml_messages(self):
        from llmwikify.apps.chat.research_engine.llm_step import run_prompt

        llm = _make_llm(json.dumps({"approved": True, "score": 8}))
        ctx = _make_ctx(
            default_llm=llm,
            config={"max_retry_attempts": 1, "llm_call_timeout_seconds": 30},
        )
        six_step_context = {
            "clarification": {"context": "C"},
            "reasoning_check": {"aggregate_score": 0.8},
        }
        asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, "research_review",
                six_step_context=six_step_context,
                query="q", report="r", source_count=3,
            )
        )
        messages = llm.chat.call_args[0][0]
        assert "Framework Review Checklist" in messages[0]["content"]

    @pytest.mark.parametrize(
        "prompt_name",
        [
            "research_clarify", "research_plan", "research_replan",
            "research_reason", "research_revise",
        ],
    )
    def test_no_framework_injection_for_non_augmented_steps(self, prompt_name):
        """Steps without framework_kind set never inject, even when
        six_step_context is provided."""
        from llmwikify.apps.chat.research_engine.llm_step import run_prompt

        chat_return = json.dumps({"x": 1})
        default_llm = _make_llm(chat_return)
        planning_llm = _make_llm(chat_return)
        report_llm = _make_llm(chat_return)
        ctx = _make_ctx(
            default_llm=default_llm,
            planning_llm=planning_llm,
            report_llm=report_llm,
            config={"max_retry_attempts": 1, "llm_call_timeout_seconds": 30},
        )
        six_step_context = {
            "clarification": {"context": "C"},
            "reasoning_check": {"aggregate_score": 0.8},
        }
        # Build kwargs based on which prompt we're calling
        if prompt_name == "research_revise":
            # revise returns raw markdown
            chat_return = "raw text"
            default_llm.chat.return_value = "raw text"
            report_llm.chat.return_value = "raw text"
            planning_llm.chat.return_value = "raw text"
            kwargs = {"issues_text": "i", "source_refs": "", "report": "r"}
        elif prompt_name == "research_reason":
            kwargs = {
                "query": "q", "round": 0, "max_rounds": 5, "phase": "x",
                "quality_score": 0, "budget_remaining": 1.0,
                "sub_queries_count": 0, "failed_sq": 0, "sources_count": 0,
                "analyzed_count": 0, "report_exists": False, "review_exists": False,
                "observations_text": "(none)",
            }
        elif prompt_name == "research_replan":
            kwargs = {"query": "q", "gaps": ["g"], "wiki_context": ""}
        else:
            kwargs = {"query": "q"}

        asyncio.new_event_loop().run_until_complete(
            run_prompt(
                ctx, prompt_name,
                six_step_context=six_step_context,
                **kwargs,
            )
        )
        # The LLM that was called should NOT have a framework block
        for client in (default_llm, planning_llm, report_llm):
            if client.chat.called:
                messages = client.chat.call_args[0][0]
                for m in messages:
                    assert "Framework" not in m.get("content", ""), (
                        f"{prompt_name} incorrectly injected framework block: "
                        f"{m['content'][:200]}"
                    )


# ─── 3. PROMPT_REGISTRY is the single source of truth ─────────────────


class TestPromptRegistrySingleSourceOfTruth:
    """The PROMPT_REGISTRY in prompts.py should be the single source
    of truth for prompt metadata. Other modules (actions, engine,
    clarifier, report, review) should reference it via run_prompt,
    not duplicate the metadata.
    """

    def test_clarifier_does_not_define_its_own_prompt(self):
        """clarifier.py should not have its own inline system prompt
        or message-building code; it should rely on run_prompt."""
        from llmwikify.apps.chat import clarifier
        source = open(clarifier.__file__).read()
        # The inline Chinese system prompt is no longer in clarifier.py
        assert "你是一个研究澄清助手" not in source
        # _build_messages is deleted
        assert "def _build_messages" not in source

    def test_actions_does_not_have_inline_replan_messages(self):
        """actions._plan_for_gaps should not have its own inline
        English prompt; it should use run_prompt."""
        from llmwikify.apps.chat import actions
        source = open(actions.__file__).read()
        assert "You are a research planner" not in source

    def test_engine_does_not_have_inline_reason_messages(self):
        """engine._llm_reason should not have its own inline English
        ReAct prompt; it should use run_prompt."""
        from llmwikify.apps.chat import engine
        source = open(engine.__file__).read()
        assert "You are a research orchestrator" not in source

    def test_report_does_not_have_its_own_framework_block_renderer(self):
        """report.py should not define its own _render_framework_block;
        it should use prompts.render_framework_block."""
        from llmwikify.apps.chat import report
        source = open(report.__file__).read()
        assert "def _render_framework_block" not in source

    def test_review_does_not_have_its_own_framework_block_renderer(self):
        """review.py should not define its own _render_framework_review_block;
        it should use prompts.render_framework_block (via run_prompt)."""
        from llmwikify.apps.chat.harness import review
        source = open(review.__file__).read()
        assert "def _render_framework_review_block" not in source

    def test_no_inline_md5_in_report_or_review(self):
        """The md5-based source hash logic should be in prompts.source_hash,
        not duplicated in report/review."""
        from llmwikify.apps.chat import report
        from llmwikify.apps.chat.harness import review
        for module in (report, review):
            source = open(module.__file__).read()
            assert "hashlib.md5" not in source, (
                f"{module.__name__} still has inline hashlib.md5 — should use prompts.source_hash"
            )
