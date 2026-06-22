"""Tests for the research-routing guard (2026-06-22).

The system prompt used to nudge the LLM to invoke autoresearch
whenever a message contained the word 研究 / 调研 / research /
investigate / 深入, even without an explicit ``/study`` prefix.
That made ordinary chat messages like "调研一下 nanobot" route to
the Research workflow against the user's intent.

After the fix:
- ``autoresearch_compound_skill`` only registers ``/study`` as a
  trigger (no Chinese 研究：)
- The system prompt explicitly tells the LLM to **only** invoke
  skill tools for explicit slash commands; ordinary-sounding
  "research" messages go through the normal tool loop.

These tests guard against regressions on either axis.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from llmwikify.apps.chat.agent.prompt_builder import (
    BuildContext,
    PromptBuilder,
)

# ── Stubs (mirror tests/test_apps_chat_agent_prompt_builder.py) ──


class _StubWiki:
    def __init__(self, tool_names=None, skill_descs=None):
        self._tool_names = tool_names or []
        self._skill_descs = skill_descs or {}

    def list_tool_names(self):
        return list(self._tool_names)

    def get_skill_descriptions(self, names):
        return {n: self._skill_descs.get(n, "") for n in names}


def _run(coro):
    return asyncio.run(coro)


def _make_builder(tmp_path, tool_names=None):
    wiki = _StubWiki(tool_names=tool_names)
    return PromptBuilder(wiki_service=wiki, memory_manager=None, workspace=tmp_path)


# ── 1. autoresearch trigger must be /study only ───────────────────


class TestAutoresearchTriggerIsStudyOnly:
    def test_only_study_trigger_registered(self) -> None:
        """The autoresearch skill must register only ``/study`` —
        no Chinese 研究: trigger, no other implicit triggers."""
        from llmwikify.apps.chat.skills.autoresearch_compound_skill import (
            AutoResearchCompoundSkill,
        )

        run_action = AutoResearchCompoundSkill.actions.get("run")
        assert run_action is not None, "autoresearch.run action not found"
        assert run_action.triggers == ["/study"], (
            f"Expected triggers=['/study'], got {run_action.triggers}"
        )

    def test_no_chinese_research_trigger_anywhere(self) -> None:
        """Belt-and-suspenders: no autoresearch trigger should contain
        Chinese characters (研究 / 调研)."""
        from llmwikify.apps.chat.skills.autoresearch_compound_skill import (
            AutoResearchCompoundSkill,
        )

        for action_name, action in AutoResearchCompoundSkill.actions.items():
            for trigger in action.triggers:
                assert not re.search(r"[\u4e00-\u9fff]", trigger), (
                    f"Action '{action_name}' has Chinese trigger: {trigger!r}"
                )


# ── 2. system prompt must NOT nudge implicit research routing ────


class TestSystemPromptResearchGuard:
    def test_prompt_omits_old_chinese_trigger_nudge(self, tmp_path: Path) -> None:
        """The old prompt said: "or a Chinese trigger (e.g. 研究：...)".
        That phrasing must be gone — only ``/study`` (slash command)
        should be mentioned as a skill trigger example."""
        builder = _make_builder(tmp_path, tool_names=["read_file"])
        ctx = BuildContext(
            wiki_id="w",
            user_message="hi",
            session_id="s1",
            workspace=tmp_path,
        )
        prompt = _run(builder.build_with_context(ctx))
        # Old phrasing must be gone
        assert "研究：" not in prompt, (
            "Old system prompt still mentions 研究： trigger — re-check prompt_builder.py"
        )
        # /study must still be there (it's the canonical example)
        assert "/study" in prompt, (
            "System prompt should still reference /study as the canonical slash command"
        )

    def test_prompt_includes_explicit_no_implicit_routing_clause(
        self, tmp_path: Path,
    ) -> None:
        """The new prompt should explicitly tell the LLM not to
        invoke skill tools for ordinary questions mentioning
        研究/调研/research without an explicit /study prefix."""
        builder = _make_builder(tmp_path, tool_names=["read_file"])
        ctx = BuildContext(workspace=tmp_path)
        prompt = _run(builder.build_with_context(ctx))
        # The guard phrasing should be present
        assert "do NOT invoke skill tools" in prompt or "do not invoke skill tools" in prompt.lower(), (
            "System prompt should explicitly forbid implicit skill invocation"
        )
        # And it should call out the example keywords
        for keyword in ("研究", "调研", "research"):
            assert keyword in prompt, (
                f"System prompt should mention '{keyword}' as a keyword "
                f"NOT to use as a skill trigger"
            )


# ── 3. integration: full system prompt for a chat that mentions ────
# ──      "research" should not contain a "use skill tool" instruction ─


class TestResearchKeywordInUserMessageDoesNotChangePrompt:
    def test_prompt_same_for_research_and_hello(self, tmp_path: Path) -> None:
        """Whether the user says 'hello' or '调研 nanobot', the
        system prompt (which is what nudges the LLM to route) must
        be identical. The routing decision should be LLM-side based
        on the prompt, not based on a per-message key in the prompt."""
        builder = _make_builder(tmp_path, tool_names=["read_file"])
        ctx_hello = BuildContext(
            wiki_id="w", user_message="hello", session_id="s1",
            workspace=tmp_path,
        )
        ctx_research = BuildContext(
            wiki_id="w", user_message="调研 nanobot", session_id="s1",
            workspace=tmp_path,
        )
        prompt_hello = _run(builder.build_with_context(ctx_hello))
        prompt_research = _run(builder.build_with_context(ctx_research))
        # System prompt = everything before the "Current message" /
        # user message section; both should produce the same nudge
        # section. Easiest check: both contain the "do not invoke
        # skill tools" guard.
        for kw in ("do NOT invoke skill tools", "/study"):
            assert kw in prompt_hello
            assert kw in prompt_research


# ── 4. command router does not match Chinese 研究: as a research trigger ─


class TestCommandRouterDoesNotRouteResearch:
    """The orchestrator's command router (orchestrator.py + apps/chat/command_router.py)
    only handles slash commands. ``研究:nanobot`` must not match any
    registered handler, so it falls through to normal chat."""

    def test_router_returns_none_for_chinese_research(self) -> None:
        from llmwikify.apps.chat.command_router import (
            CommandContext,
            CommandRouter,
        )

        def _echo(args: str) -> str:
            return f"echo: {args}"

        router = CommandRouter()
        router.prefix("/title", _echo)
        # 研究：nanobot should not match any registered command
        ctx = CommandContext(text="研究：nanobot", raw="研究：nanobot")
        result = asyncio.run(router.dispatch(ctx))
        assert result == [], (
            f"研究：nanobot should not match any router command; got {result!r}"
        )
        # And 研究 alone (no colon) shouldn't either
        ctx2 = CommandContext(text="研究 nanobot", raw="研究 nanobot")
        result = asyncio.run(router.dispatch(ctx2))
        assert result == []
        # But /title should still work (returns the handler invocation)
        ctx3 = CommandContext(text="/title foo", raw="/title foo")
        result = asyncio.run(router.dispatch(ctx3))
        assert result, f"/title should return handler events, got {result!r}"

    def test_router_handles_study_via_skill_not_command(self) -> None:
        """``/study nanobot`` is NOT handled by CommandRouter — it
        falls through to the orchestrator's normal LLM loop, which
        then sees the autoresearch skill in the tool list and calls
        it. The router itself has no /study entry."""
        from llmwikify.apps.chat.command_router import (
            CommandContext,
            CommandRouter,
        )

        def _echo(args: str) -> str:
            return f"echo: {args}"

        router = CommandRouter()
        router.prefix("/title", _echo)
        # /study should not match any router command (the orchestrator
        # handles it via the skill tool, not via the command router)
        ctx = CommandContext(text="/study nanobot", raw="/study nanobot")
        result = asyncio.run(router.dispatch(ctx))
        assert result == [], (
            "/study should not be in CommandRouter — it's a skill "
            f"trigger, not a slash command. Got {result!r}"
        )
