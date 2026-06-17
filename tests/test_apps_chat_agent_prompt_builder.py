"""Tests for PromptBuilder — 7-section composition + BuildContext.

Covers the 8-case matrix from docs/poc/phase-a-steps.md §4.6:
  1.  full BuildContext → all 7 sections present
  2.  missing AGENTS.md → bootstrap section omitted
  3.  memory placeholder filtered
  4.  always_skills injected into skills section
  5.  recent history over MAX_HISTORY_CHARS → truncated
  6.  one section raising → others still appear
  7.  build_minimal → only 3 sections
  8.  enable_bootstrap=False → bootstrap skipped
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from llmwikify.apps.chat.agent.prompt_builder import (
    BOOTSTRAP_FILES,
    BuildContext,
    PromptBuilder,
)


def _run(coro):
    return asyncio.run(coro)


class _StubWiki:
    def __init__(self, tool_names=None, skill_descs=None):
        self._tool_names = tool_names or []
        self._skill_descs = skill_descs or {}

    def list_tool_names(self):
        return list(self._tool_names)

    def get_skill_descriptions(self, names):
        return {n: self._skill_descs.get(n, "") for n in names}


class _StubMemory:
    def __init__(self, prefs=None, related=None):
        self._prefs = prefs or {}
        self._related = related or []

    class _Preferences:
        def __init__(self, outer):
            self._outer = outer

        async def aall(self, _user_id):
            return dict(self._outer._prefs)

    class _Index:
        def __init__(self, outer):
            self._outer = outer

        async def asearch(self, _msg, *, session_id, limit):
            return list(self._outer._related)[:limit]

    @property
    def preferences(self):
        return _StubMemory._Preferences(self)

    @property
    def index(self):
        return _StubMemory._Index(self)


def _make_builder(workspace=None, tool_names=None, prefs=None, related=None,
                  skill_descs=None):
    wiki = _StubWiki(tool_names=tool_names, skill_descs=skill_descs)
    memory = _StubMemory(prefs=prefs, related=related) if prefs is not None or related is not None else None
    return PromptBuilder(wiki_service=wiki, memory_manager=memory, workspace=workspace)


def test_full_context_emits_seven_sections(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# My Agent\nBe helpful.")
    (tmp_path / "SOUL.md").write_text("# Soul\nBe kind.")
    builder = _make_builder(
        workspace=tmp_path,
        tool_names=["read_file", "write_file"],
        prefs={"system_prompt": "Always respond in English."},
    )
    ctx = BuildContext(
        wiki_id="wiki-1",
        user_message="hi",
        session_id="s1",
        workspace=tmp_path,
        always_skills=["research"],
    )

    prompt = _run(builder.build_with_context(ctx))
    parts = prompt.split("\n\n---\n\n")
    assert len(parts) == 7
    assert "My Agent" in parts[1]
    assert "Soul" in parts[1]
    assert "read_file" in parts[2]
    assert "Always respond in English" in parts[3]
    assert "research" in parts[4]
    assert "ReAct" in parts[5] or "Reasoning" in parts[5]
    assert "wiki-1" in parts[6]


def test_missing_bootstrap_files_yield_empty_section(tmp_path: Path) -> None:
    builder = _make_builder(workspace=tmp_path, tool_names=[])
    ctx = BuildContext(workspace=tmp_path)

    prompt = _run(builder.build_with_context(ctx))
    assert "AGENTS.md" not in prompt
    assert "SOUL.md" not in prompt
    assert "## Active skills" not in prompt
    parts = prompt.split("\n\n---\n\n")
    assert len(parts) == 3


def test_bootstrap_files_absent_does_not_break(tmp_path: Path) -> None:
    builder = _make_builder(workspace=tmp_path)
    ctx = BuildContext(workspace=tmp_path, enable_bootstrap=True)
    prompt = _run(builder.build_with_context(ctx))
    assert "Workspace" in prompt


def test_enable_bootstrap_false_skips_section(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Should not appear")
    builder = _make_builder(workspace=tmp_path)
    ctx = BuildContext(workspace=tmp_path, enable_bootstrap=False)
    prompt = _run(builder.build_with_context(ctx))
    assert "Should not appear" not in prompt
    assert "## AGENTS.md" not in prompt


def test_skills_section_injects_descriptions() -> None:
    builder = _make_builder(
        tool_names=[],
        skill_descs={"research": "Run research workflows"},
    )
    ctx = BuildContext(always_skills=["research"])
    prompt = _run(builder.build_with_context(ctx))
    assert "## Active skills" in prompt
    assert "**research**: Run research workflows" in prompt


def test_skills_exclude_filters_named_skill() -> None:
    builder = _make_builder(skill_descs={"a": "Skill A", "b": "Skill B"})
    ctx = BuildContext(always_skills=["a", "b"], exclude_skills={"a"})
    prompt = _run(builder.build_with_context(ctx))
    assert "**a**" not in prompt
    assert "**b**: Skill B" in prompt


def test_history_truncated_to_max_chars() -> None:
    related = [{"source": f"s{i}", "content": "x" * 100} for i in range(20)]
    builder = _make_builder(related=related)
    ctx = BuildContext(
        wiki_id="w",
        user_message="query",
        session_id="s",
        max_history_chars=300,
    )
    prompt = _run(builder.build_with_context(ctx))
    parts = prompt.split("\n\n---\n\n")
    history_section = parts[-1]
    assert "…" in history_section
    assert len(history_section) <= 320


def test_section_failure_does_not_break_others(tmp_path: Path) -> None:
    class BrokenWiki(_StubWiki):
        def list_tool_names(self):
            raise RuntimeError("wiki broken")

    builder = PromptBuilder(wiki_service=BrokenWiki(), memory_manager=None,
                            workspace=tmp_path)
    ctx = BuildContext(workspace=tmp_path)
    prompt = _run(builder.build_with_context(ctx))
    assert "Workspace" in prompt
    assert "Reasoning Pattern" in prompt
    assert "wiki broken" not in prompt


def test_build_minimal_only_three_sections() -> None:
    builder = _make_builder(tool_names=["x"])
    ctx = BuildContext(always_skills=["s1"])
    prompt = _run(builder.build_minimal(ctx))
    parts = prompt.split("\n\n---\n\n")
    assert len(parts) == 3
    assert "Available tools" in parts[1]
    assert "ReAct" in parts[2] or "Reasoning" in parts[2]
    assert "## Active skills" not in prompt


def test_bootstrap_cache_hits_same_path(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# X")
    builder = _make_builder(workspace=tmp_path)
    ctx = BuildContext(workspace=tmp_path)
    _run(builder.build_with_context(ctx))
    _run(builder.build_with_context(ctx))
    cache = builder._bootstrap_cache
    assert len(cache) == 1


def test_bootstrap_cache_invalidates_on_mtime_change(tmp_path: Path) -> None:
    import os
    import time as time_mod

    path = tmp_path / "AGENTS.md"
    path.write_text("# Original")
    os.utime(path, (1000.0, 1000.0))
    builder = _make_builder(workspace=tmp_path)
    ctx = BuildContext(workspace=tmp_path)
    prompt1 = _run(builder.build_with_context(ctx))
    assert "Original" in prompt1
    time_mod.sleep(0.05)
    path.write_text("# Updated")
    os.utime(path, (2000.0, 2000.0))
    prompt2 = _run(builder.build_with_context(ctx))
    assert "Updated" in prompt2


def test_parse_wiki_prefix_static_method_unchanged() -> None:
    assert PromptBuilder.parse_wiki_prefix("hello") == (None, "hello")
    assert PromptBuilder.parse_wiki_prefix("@w1 hi") == ("w1", "hi")


def test_legacy_build_kwargs_still_work(tmp_path: Path) -> None:
    builder = _make_builder(workspace=tmp_path, tool_names=["x"])
    prompt = _run(builder.build(wiki_id="w", user_message="hi", session_id="s"))
    assert "w" in prompt
    assert "Workspace" in prompt


def test_workspace_unset_does_not_crash() -> None:
    builder = _make_builder(workspace=None, tool_names=[])
    ctx = BuildContext()
    prompt = _run(builder.build_with_context(ctx))
    assert "(unset)" in prompt


def test_bootstrap_files_constant() -> None:
    assert BOOTSTRAP_FILES == ("AGENTS.md", "SOUL.md", "USER.md")
