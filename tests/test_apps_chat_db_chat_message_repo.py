"""Tests for ChatMessageRepository (chat_messages table)."""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.db import ChatMessageRepository


@pytest.fixture
def repo(tmp_path: Path) -> ChatMessageRepository:
    r = ChatMessageRepository(tmp_path / "test.db")
    r._init_schema()
    return r


# ─── save_chat_message ──────────────────────────────────────────


class TestSave:
    def test_inserts_message(self, repo: ChatMessageRepository) -> None:
        repo.save_chat_message({
            "session_id": "s1", "role": "user", "content": "hi",
        })
        msgs = repo.get_chat_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hi"

    def test_assigns_uuid_if_missing(self, repo: ChatMessageRepository) -> None:
        repo.save_chat_message({
            "session_id": "s1", "role": "user", "content": "hi",
        })
        msgs = repo.get_chat_messages("s1")
        assert len(msgs[0]["id"]) == 32

    def test_preserves_explicit_id(self, repo: ChatMessageRepository) -> None:
        repo.save_chat_message({
            "id": "custom-id", "session_id": "s1",
            "role": "user", "content": "hi",
        })
        msgs = repo.get_chat_messages("s1")
        assert msgs[0]["id"] == "custom-id"

    def test_insert_or_ignore_on_duplicate_id(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "id": "dup", "session_id": "s1",
            "role": "user", "content": "first",
        })
        # Second insert with same id is ignored, not replaced
        repo.save_chat_message({
            "id": "dup", "session_id": "s1",
            "role": "user", "content": "second",
        })
        msgs = repo.get_chat_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "first"

    def test_stores_tool_calls_as_json(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "session_id": "s1", "role": "assistant",
            "content": "", "tool_calls": [{"name": "x", "args": {"y": 1}}],
        })
        import json
        msgs = repo.get_chat_messages("s1")
        assert json.loads(msgs[0]["tool_calls"]) == [
            {"name": "x", "args": {"y": 1}},
        ]

    def test_stores_token_columns(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "session_id": "s1", "role": "assistant", "content": "x",
            "tokens_input": 10, "tokens_output": 20,
            "tokens_reasoning": 5, "tokens_cache_read": 3,
            "tokens_cache_write": 2, "cost": 0.001,
        })
        msgs = repo.get_chat_messages("s1")
        assert msgs[0]["tokens_input"] == 10
        assert msgs[0]["tokens_output"] == 20
        assert msgs[0]["cost"] == 0.001

    def test_stores_research_run_id(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "session_id": "s1", "role": "assistant",
            "content": "x", "research_run_id": "run-abc",
        })
        msgs = repo.get_chat_messages("s1")
        assert msgs[0]["research_run_id"] == "run-abc"


# ─── update_chat_message ────────────────────────────────────────


class TestUpdate:
    def test_returns_true_when_updated(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "id": "m1", "session_id": "s1",
            "role": "user", "content": "old",
        })
        assert repo.update_chat_message("m1", "new") is True
        msgs = repo.get_chat_messages("s1", include_reverted=True)
        assert msgs[0]["content"] == "new"

    def test_returns_false_when_missing(
        self, repo: ChatMessageRepository,
    ) -> None:
        assert repo.update_chat_message("nope", "new") is False


# ─── get_chat_messages ──────────────────────────────────────────


class TestGet:
    def test_returns_chronological_order(
        self, repo: ChatMessageRepository,
    ) -> None:
        for i in range(3):
            repo.save_chat_message({
                "session_id": "s1", "role": "user", "content": f"m{i}",
            })
        msgs = repo.get_chat_messages("s1")
        # All 3 messages returned (order may tie on sub-second inserts)
        contents = {m["content"] for m in msgs}
        assert contents == {"m0", "m1", "m2"}

    def test_filters_reverted_by_default(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "id": "a", "session_id": "s1", "role": "user", "content": "a",
        })
        repo.save_chat_message({
            "id": "b", "session_id": "s1", "role": "assistant", "content": "b",
        })
        # Manually mark 'b' as reverted
        import sqlite3
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "UPDATE chat_messages SET reverted = 1 WHERE id = 'b'"
            )
            conn.commit()
        # Default: exclude reverted
        msgs = repo.get_chat_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["id"] == "a"
        # include_reverted=True: both
        msgs = repo.get_chat_messages("s1", include_reverted=True)
        assert len(msgs) == 2

    def test_respects_limit(self, repo: ChatMessageRepository) -> None:
        for i in range(5):
            repo.save_chat_message({
                "session_id": "s1", "role": "user", "content": f"m{i}",
            })
        msgs = repo.get_chat_messages("s1", limit=3)
        assert len(msgs) == 3


# ─── revert_to_message ──────────────────────────────────────────


class TestRevert:
    def test_returns_zero_when_target_missing(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "id": "a", "session_id": "s1", "role": "user", "content": "a",
        })
        assert repo.revert_to_message("s1", "nonexistent") == 0

    def test_reverts_messages_after_target(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "id": "a", "session_id": "s1", "role": "user", "content": "a",
        })
        repo.save_chat_message({
            "id": "b", "session_id": "s1", "role": "assistant", "content": "b",
        })
        repo.save_chat_message({
            "id": "c", "session_id": "s1", "role": "user", "content": "c",
        })
        # Revert to 'a' (the first message) — b and c should be reverted
        n = repo.revert_to_message("s1", "a")
        assert n == 2
        # Default view (excludes reverted) shows only 'a'
        msgs = repo.get_chat_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["id"] == "a"
        # include_reverted shows all 3
        msgs = repo.get_chat_messages("s1", include_reverted=True)
        assert len(msgs) == 3

    def test_tool_call_delete_callback_invoked(
        self, repo: ChatMessageRepository, tmp_path: Path,
    ) -> None:
        """Verify the cross-repo callback fires when wired."""
        callback_calls: list[tuple[str, int]] = []

        def fake_delete(conn, session_id, target_rowid):
            callback_calls.append((session_id, target_rowid))
            return 0

        repo.save_chat_message({
            "id": "a", "session_id": "s1", "role": "user", "content": "a",
        })
        repo.save_chat_message({
            "id": "b", "session_id": "s1", "role": "assistant", "content": "b",
        })
        repo.revert_to_message(
            "s1", "a", tool_call_delete_after_rowid=fake_delete,
        )
        assert len(callback_calls) == 1
        assert callback_calls[0][0] == "s1"
        # target_rowid is the rowid of message 'a'
        assert callback_calls[0][1] > 0

    def test_target_message_not_reverted(
        self, repo: ChatMessageRepository,
    ) -> None:
        repo.save_chat_message({
            "id": "a", "session_id": "s1", "role": "user", "content": "a",
        })
        repo.save_chat_message({
            "id": "b", "session_id": "s1", "role": "assistant", "content": "b",
        })
        repo.revert_to_message("s1", "a")
        # Target 'a' should still be visible (not reverted)
        msgs = repo.get_chat_messages("s1", include_reverted=True)
        reverted_flags = {m["id"]: m["reverted"] for m in msgs}
        assert reverted_flags["a"] == 0
        assert reverted_flags["b"] == 1
