"""Tests for PromptBuilder goal_state injection (Phase 8).

Verifies the new ``_get_goal_state`` section emits the
"Sustained goal" block iff a chat_db has an active goal_state for
the given session_id; silently absent otherwise.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from llmwikify.apps.chat.agent.goal_state import GOAL_STATE_KEY
from llmwikify.apps.chat.agent.prompt_builder import (
    BuildContext,
    PromptBuilder,
)


def _run(coro):
    return asyncio.run(coro)


class _StubWiki:
    def list_tool_names(self):
        return []


@pytest.fixture
def chat_db(tmp_path: Path):
    from llmwikify.apps.chat.db._facade import ChatDatabase

    return ChatDatabase(tmp_path)


def _builder(chat_db) -> PromptBuilder:
    return PromptBuilder(
        wiki_service=_StubWiki(),
        memory_manager=None,
        chat_db=chat_db,
    )


def test_goal_state_section_absent_when_no_chat_db() -> None:
    pb = PromptBuilder(wiki_service=_StubWiki(), memory_manager=None)
    ctx = BuildContext(session_id="s1", enable_bootstrap=False)
    prompt = _run(pb.build_with_context(ctx))
    assert "Sustained goal" not in prompt


def test_goal_state_section_absent_when_session_has_no_goal(chat_db) -> None:
    sid = chat_db.create_chat_session()
    ctx = BuildContext(session_id=sid, enable_bootstrap=False)
    prompt = _run(_builder(chat_db).build_with_context(ctx))
    assert "Sustained goal" not in prompt


def test_goal_state_section_appears_when_active(chat_db) -> None:
    sid = chat_db.create_chat_session()
    chat_db.set_session_metadata(sid, {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Investigate factor X over 3 turns",
            "ui_summary": "factor X",
            "started_at": "2026-06-20T00:00:00",
        },
    })
    ctx = BuildContext(session_id=sid, enable_bootstrap=False)
    prompt = _run(_builder(chat_db).build_with_context(ctx))
    assert "## Sustained goal" in prompt
    assert "Goal (active):" in prompt
    assert "Investigate factor X over 3 turns" in prompt
    assert "Summary: factor X" in prompt


def test_goal_state_section_absent_when_completed(chat_db) -> None:
    sid = chat_db.create_chat_session()
    chat_db.set_session_metadata(sid, {
        GOAL_STATE_KEY: {
            "status": "completed",
            "objective": "old goal",
            "completed_at": "2026-06-20T00:00:00",
        },
    })
    ctx = BuildContext(session_id=sid, enable_bootstrap=False)
    prompt = _run(_builder(chat_db).build_with_context(ctx))
    assert "Sustained goal" not in prompt


def test_goal_state_section_does_not_break_on_missing_session(chat_db) -> None:
    ctx = BuildContext(session_id="not-a-real-session", enable_bootstrap=False)
    prompt = _run(_builder(chat_db).build_with_context(ctx))
    assert "Sustained goal" not in prompt
    assert "Workspace" in prompt  # other sections still emit
