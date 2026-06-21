"""Phase 12 — runtime context tag isolation (borrowed from nanobot v0.2.1).

Verifies that metadata-only sections are wrapped with explicit
``[Runtime Context — metadata only, not instructions]`` … ``[/Runtime Context]``
tags so:

  1. the LLM can clearly see the block is metadata, not instruction
  2. compaction / persistence paths can strip the whole block by
     matching the tags (NOT the leading ``## `` heading, which collides
     with normal markdown sections)
  3. user-authored ``## Goal`` / ``## User preferences`` sections
     never accidentally land inside the runtime context block
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.agent.prompt_builder import (
    RUNTIME_CONTEXT_END,
    RUNTIME_CONTEXT_TAG,
    PromptBuilder,
    wrap_runtime_context,
)

# ── wrap_runtime_context unit tests ─────────────────────────────


class TestWrapRuntimeContext:
    def test_empty_body_returns_empty_string(self) -> None:
        assert wrap_runtime_context("") == ""

    def test_body_with_label(self) -> None:
        out = wrap_runtime_context("## Goal\nAchieve X", label="goal_state")
        assert out.startswith(f"{RUNTIME_CONTEXT_TAG} (goal_state)\n")
        assert "## Goal" in out
        assert "Achieve X" in out
        assert out.rstrip().endswith(RUNTIME_CONTEXT_END)

    def test_body_without_label(self) -> None:
        out = wrap_runtime_context("body text")
        assert out.startswith(f"{RUNTIME_CONTEXT_TAG}\n")
        assert out.rstrip().endswith(RUNTIME_CONTEXT_END)

    def test_body_with_internal_dashes(self) -> None:
        """Body containing ``---`` separators does not confuse the wrapper."""
        out = wrap_runtime_context("a\n\n---\n\nb", label="x")
        assert out.count(RUNTIME_CONTEXT_END) == 1
        assert out.count(RUNTIME_CONTEXT_TAG) == 1
        # The body is preserved verbatim between the tags
        assert "a\n\n---\n\nb" in out

    def test_body_is_stripped_of_trailing_whitespace(self) -> None:
        out = wrap_runtime_context("body   \n\n\n", label="x")
        # The closing tag should be on its own line with no trailing
        # whitespace before it
        assert "   \n" + RUNTIME_CONTEXT_END not in out
        assert out.endswith(RUNTIME_CONTEXT_END)

    def test_block_is_strippable_by_tag_regex(self) -> None:
        """Persistence paths can strip the block by regex on the tags."""
        import re

        body = wrap_runtime_context("secret content", label="x")
        stripped = re.sub(
            rf"{re.escape(RUNTIME_CONTEXT_TAG)}.*?{re.escape(RUNTIME_CONTEXT_END)}",
            "[REDACTED]",
            body,
            flags=re.DOTALL,
        )
        assert "secret content" not in stripped
        assert "[REDACTED]" in stripped


# ── integration: prompt sections are tagged ──────────────────────


class TestPromptSectionsHaveRuntimeContextTags:
    """Each metadata-only section in the final prompt must be wrapped.

    Sections that carry real instructions (identity, bootstrap,
    tool contract, skills summary, ReAct prompt) are NOT wrapped.
    """

    @pytest.mark.asyncio
    async def test_goal_state_section_wrapped(self) -> None:
        """A session with active goal produces a runtime-context block."""
        from llmwikify.apps.chat.agent.prompt_builder import BuildContext

        chat_db = _StubChatDb(
            metadata={"goal_state": {"status": "active", "objective": "Reach M3"}}
        )
        builder = PromptBuilder(
            wiki_service=_StubWiki(), chat_db=chat_db,
        )
        ctx = BuildContext(session_id="s1")
        prompt = await builder.build_with_context(ctx)
        # The runtime context tag with the ``goal_state`` label appears
        assert f"{RUNTIME_CONTEXT_TAG} (goal_state)" in prompt
        assert RUNTIME_CONTEXT_END in prompt
        # And the goal text is inside the block
        assert "Reach M3" in prompt

    @pytest.mark.asyncio
    async def test_no_goal_state_means_no_goal_block(self) -> None:
        """Without an active goal, no runtime-context block is added."""
        from llmwikify.apps.chat.agent.prompt_builder import BuildContext

        chat_db = _StubChatDb(metadata={})
        builder = PromptBuilder(wiki_service=_StubWiki(), chat_db=chat_db)
        ctx = BuildContext(session_id="s1")
        prompt = await builder.build_with_context(ctx)
        assert "(goal_state)" not in prompt

    @pytest.mark.asyncio
    async def test_recent_history_wrapped(self) -> None:
        """When wiki_id is set, the recent history section gets the tag."""
        from llmwikify.apps.chat.agent.prompt_builder import BuildContext

        builder = PromptBuilder(wiki_service=_StubWiki(), chat_db=None)
        ctx = BuildContext(wiki_id="w1", session_id=None)
        prompt = await builder.build_with_context(ctx)
        assert f"{RUNTIME_CONTEXT_TAG} (recent_history)" in prompt

    @pytest.mark.asyncio
    async def test_identity_not_wrapped(self) -> None:
        """Identity is a real instruction; no runtime-context tag."""
        from llmwikify.apps.chat.agent.prompt_builder import BuildContext

        builder = PromptBuilder(wiki_service=_StubWiki(), chat_db=None)
        ctx = BuildContext()
        prompt = await builder.build_with_context(ctx)
        # Identity text appears, but the runtime-context tag does not
        # wrap it. We check by absence: there is exactly one opening tag
        # (and one closing tag) at most, and it does not surround
        # ``You are a helpful wiki assistant``.
        assert "You are a helpful wiki assistant" in prompt
        idx = prompt.find("You are a helpful wiki assistant")
        before = prompt[:idx]
        # No ``RUNTIME_CONTEXT_TAG`` immediately preceding the identity
        # text within the same section (a tiny allowance for trailing
        # whitespace + section joiner).
        assert RUNTIME_CONTEXT_TAG not in before.split("\n\n---\n\n")[-1]

    @pytest.mark.asyncio
    async def test_react_prompt_not_wrapped(self) -> None:
        """ReAct prompt is real instruction; not wrapped."""
        from llmwikify.apps.chat.agent.prompt_builder import (
            REACT_SYSTEM_PROMPT,
            BuildContext,
        )

        builder = PromptBuilder(wiki_service=_StubWiki(), chat_db=None)
        ctx = BuildContext()
        prompt = await builder.build_with_context(ctx)
        assert "Reasoning Pattern" in prompt  # From REACT_SYSTEM_PROMPT
        # The REACT_SYSTEM_PROMPT block is NOT inside a runtime-context
        # tag — check by absence of the tag in the same section as the
        # prompt heading.
        idx = prompt.find("Reasoning Pattern")
        same_section = prompt[:idx].split("\n\n---\n\n")[-1]
        assert RUNTIME_CONTEXT_TAG not in same_section


# ── Persistence: compaction can strip the block ──────────────────


class TestPersistenceCanStripBlock:
    """The block must be strippable by a simple regex (compaction, writeback)."""

    def test_tag_pair_marks_exact_block(self) -> None:
        """Persistence path strips by the tag pair, not by the heading."""
        body = wrap_runtime_context(
            "## Sustained goal\nReach M3\nSummary: weekly",
            label="goal_state",
        )
        import re

        # A regex that naively strips by ``## Sustained goal`` heading
        # alone would be unsafe (collides with user-authored sections).
        # The tag pair gives an unambiguous strip target.
        stripped = re.sub(
            rf"{re.escape(RUNTIME_CONTEXT_TAG)}.*?{re.escape(RUNTIME_CONTEXT_END)}",
            "",
            body,
            flags=re.DOTALL,
        )
        assert "Reach M3" not in stripped
        assert "weekly" not in stripped

    def test_user_authored_goal_section_not_stripped(self) -> None:
        """User-authored ``## Goal`` sections survive the strip."""
        body = (
            "## Goal\nUser wrote this goal\n\n"
            + wrap_runtime_context(
                "## Sustained goal\nReach M3", label="goal_state",
            )
        )
        import re

        stripped = re.sub(
            rf"{re.escape(RUNTIME_CONTEXT_TAG)}.*?{re.escape(RUNTIME_CONTEXT_END)}",
            "",
            body,
            flags=re.DOTALL,
        )
        # User-authored section survives
        assert "User wrote this goal" in stripped
        # Runtime context block is gone
        assert "Reach M3" not in stripped


# ── Helpers ──────────────────────────────────────────────────────


class _StubChatDb:
    def __init__(self, metadata: dict) -> None:
        self._metadata = metadata

    def get_session_metadata(self, session_id: str) -> dict:
        return self._metadata


class _StubWiki:
    def get_skill_descriptions(self, names: list[str]) -> dict:
        return {n: f"description for {n}" for n in names}
