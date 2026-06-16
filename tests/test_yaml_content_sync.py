"""Tests verifying that research_clarify and research_replan YAMLs
match the legacy inline prompt content (commit 9 of the prompt-system
refactor).

Before this commit, the inline Chinese clarify prompt and the inline
English replan prompt were the actual prompts being sent to the LLM.
The existing YAMLs had different (English) content that was dead code.

After this commit:
- research_clarify.yaml contains the Chinese system prompt that was
  inline in clarifier.py:_build_messages (commit 5ae899b version).
- research_replan.yaml contains the English system prompt that was
  inline in actions.py:_plan_for_gaps (commit 6819113^ version).
- The same Jinja2 user template structure is preserved.

This means the prompts being sent to the LLM are byte-equivalent (or
near-equivalent after Jinja2 whitespace normalization) to the legacy
inline versions, so behavior is preserved.

This is a deliberate behavior change vs the previous (commit 8) state
where the YAMLs were drift-version. The user explicitly approved this
synchronization in the planning session: "明确是行为变化，不是纯结构
化重构".
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from llmwikify.archive.llmwikify_v0_41_legacy.chat_legacy.llm_step import run_prompt


# ─── research_clarify.yaml matches legacy Chinese inline content ─────


class TestResearchClarifyYAMLContent:
    """The clarify YAML's system + user templates should render to the
    same content as the legacy inline _build_messages() (commit 5ae899b).
    """

    @pytest.fixture
    def rendered_messages(self):
        """Run run_prompt with the real YAMLs and capture the messages
        sent to the LLM."""
        llm = MagicMock()
        llm.chat = MagicMock(return_value=json.dumps({
            "context": "C", "scope_check": True,
        }))
        llm.provider = "openai"
        ctx = MagicMock()
        ctx.default_llm = llm
        ctx.planning_llm = llm
        ctx.report_llm = llm
        ctx.metrics = None
        ctx.config = {
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        }

        async def _run(query, wiki_context=""):
            await run_prompt(
                ctx, "research_clarify",
                query=query, wiki_context=wiki_context,
            )
            return llm.chat.call_args[0][0]

        return _run

    def test_system_prompt_is_chinese(self, rendered_messages):
        """Legacy was Chinese. YAML should also be Chinese."""
        async def _go():
            msgs = await rendered_messages("AI safety")
            assert msgs[0]["role"] == "system"
            return msgs[0]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        # The legacy prompt had these Chinese phrases
        assert "你是一个研究澄清助手" in content
        assert "语境" in content
        assert "边界" in content
        assert "立场" in content
        assert "前提" in content

    def test_system_prompt_contains_json_schema(self, rendered_messages):
        """The legacy prompt had an explicit JSON schema example."""
        async def _go():
            msgs = await rendered_messages("X")
            return msgs[0]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert '"context"' in content
        assert '"boundaries"' in content
        assert '"position"' in content
        assert '"premises"' in content
        assert '"scope_check"' in content

    def test_system_prompt_contains_scope_check_false_conditions(self, rendered_messages):
        """The legacy prompt listed when scope_check should be false."""
        async def _go():
            msgs = await rendered_messages("X")
            return msgs[0]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "scope_check=false" in content
        # The three conditions
        assert "范围太宽泛无法研究" in content
        assert "前提假设不可靠" in content
        assert "缺乏明确的研究边界" in content

    def test_user_message_contains_query(self, rendered_messages):
        """The user message should start with '研究主题：{query}'."""
        async def _go():
            msgs = await rendered_messages("AI safety")
            return msgs[1]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "研究主题：AI safety" in content

    def test_user_message_ends_with_concept_clarify_request(self, rendered_messages):
        """The legacy user message ended with '请进行概念澄清。'"""
        async def _go():
            msgs = await rendered_messages("X")
            return msgs[1]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert content.rstrip().endswith("请进行概念澄清。")

    def test_user_message_includes_wiki_context(self, rendered_messages):
        """When wiki_context is provided, it should be included."""
        async def _go():
            msgs = await rendered_messages("X", wiki_context="wiki text here")
            return msgs[1]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "Existing wiki context:" in content
        assert "wiki text here" in content

    def test_user_message_omits_wiki_block_when_empty(self, rendered_messages):
        """When wiki_context is empty, no 'Existing wiki context' line."""
        async def _go():
            msgs = await rendered_messages("X", wiki_context="")
            return msgs[1]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "Existing wiki context" not in content


# ─── research_replan.yaml matches legacy English inline content ──────


class TestResearchReplanYAMLContent:
    """The replan YAML's system + user templates should render to the
    same content as the legacy inline messages in actions.py:_plan_for_gaps
    (commit 6819113^).
    """

    @pytest.fixture
    def rendered_messages(self):
        """Run run_prompt with the real YAMLs and capture the messages."""
        llm = MagicMock()
        llm.chat = MagicMock(return_value=json.dumps([
            {"query": "q1", "source_type": "web", "url": ""},
        ]))
        llm.provider = "openai"
        ctx = MagicMock()
        ctx.default_llm = llm
        ctx.planning_llm = llm
        ctx.report_llm = llm
        ctx.metrics = None
        ctx.config = {
            "max_retry_attempts": 1, "llm_call_timeout_seconds": 30,
        }

        async def _run(query, gaps, wiki_context=""):
            await run_prompt(
                ctx, "research_replan",
                query=query,
                gaps=gaps,
                wiki_context=wiki_context,
            )
            return llm.chat.call_args[0][0]

        return _run

    def test_system_prompt_contains_required_rules(self, rendered_messages):
        """Legacy prompt specified JSON array shape, source_types, and limits."""
        async def _go():
            msgs = await rendered_messages("X", ["gap1"])
            return msgs[0]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "You are a research planner" in content
        # Source types mentioned
        for t in ("web", "pdf", "youtube", "wiki"):
            assert t in content
        # Limit mentioned
        assert "1-3 sub-queries per gap" in content
        assert "maximum 5 total" in content
        # JSON shape
        assert "query" in content and "source_type" in content and "url" in content

    def test_user_message_has_required_sections(self, rendered_messages):
        """Legacy user message had 3 sections: research topic, gaps,
        instructions."""
        async def _go():
            msgs = await rendered_messages(
                "quantum computing", ["entanglement", "decoherence"],
            )
            return msgs[1]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "Research topic: quantum computing" in content
        assert "Knowledge gaps to fill:" in content
        assert "entanglement" in content
        assert "decoherence" in content
        assert content.rstrip().endswith(
            "Generate sub-queries now. Return ONLY a JSON array."
        )

    def test_user_message_includes_wiki_context(self, rendered_messages):
        """When wiki_context is provided, the wiki block is appended
        to the gaps section (legacy behavior — the wiki_context kwarg
        already includes the 'Existing wiki articles...' header)."""
        async def _go():
            msgs = await rendered_messages(
                "X", ["gap1"],
                wiki_context="\n\nExisting wiki articles that may help fill gaps:\n- Bell inequality\nUse source_type \"wiki\" for these if relevant.",
            )
            return msgs[1]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "Existing wiki articles" in content
        assert "Bell inequality" in content

    def test_user_message_omits_wiki_when_empty(self, rendered_messages):
        """When wiki_context is empty, no wiki block."""
        async def _go():
            msgs = await rendered_messages("X", ["gap1"], wiki_context="")
            return msgs[1]["content"]
        content = asyncio.new_event_loop().run_until_complete(_go())
        assert "Existing wiki articles" not in content


# ─── Sanity: the YAMLs are the only place these prompts live ─────────


class TestNoInlinePromptResidue:
    """Static checks: no inline prompt text remains in the codebase.
    After commit 9, all 6 step prompts live in YAML files only.
    """

    def test_clarifier_no_chinese_inline_prompt(self):
        from llmwikify.apps.chat import clarifier
        source = open(clarifier.__file__).read()
        # The legacy Chinese prompt text should not be in the source
        assert "你是一个研究澄清助手" not in source
        # And the message builder should not exist
        assert "def _build_messages" not in source

    def test_actions_no_english_replan_prompt(self):
        from llmwikify.apps.chat import actions
        source = open(actions.__file__).read()
        # Legacy English replan system prompt
        assert "You are a research planner. Generate focused sub-queries" not in source

    def test_engine_no_reason_prompt(self):
        from llmwikify.apps.chat import engine
        source = open(engine.__file__).read()
        # Legacy English reason prompt
        assert "You are a research orchestrator using ReAct reasoning" not in source

    def test_all_six_prompts_resolve_to_yaml(self):
        """All 6 step prompts (clarify, plan, replan, reason, report,
        review, revise) should resolve via PromptRegistry without
        FileNotFoundError."""
        from llmwikify.kernel.wiki.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")
        for name in (
            "research_clarify", "research_plan", "research_replan",
            "research_reason", "research_report", "research_review",
            "research_revise",
        ):
            msgs = registry.get_messages(name, query="x")
            assert isinstance(msgs, list)
            assert len(msgs) >= 1
            for m in msgs:
                assert "role" in m
                assert "content" in m
