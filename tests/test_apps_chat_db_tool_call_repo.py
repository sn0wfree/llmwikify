"""Tests for ToolCallRepository (tool_calls table)."""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.db import ToolCallRepository


@pytest.fixture
def repo(tmp_path: Path) -> ToolCallRepository:
    r = ToolCallRepository(tmp_path / "test.db")
    r._init_schema()
    return r


class TestLog:
    def test_returns_uuid_hex(self, repo: ToolCallRepository) -> None:
        call_id = repo.log_tool_call("s1", "echo", {"x": 1})
        assert isinstance(call_id, str)
        assert len(call_id) == 32

    def test_inserts_with_status_pending(
        self, repo: ToolCallRepository,
    ) -> None:
        call_id = repo.log_tool_call("s1", "echo", {"x": 1})
        calls = repo.get_tool_calls("s1")
        assert len(calls) == 1
        assert calls[0]["id"] == call_id
        assert calls[0]["tool_name"] == "echo"
        assert calls[0]["status"] == "pending"

    def test_serializes_arguments_as_json(
        self, repo: ToolCallRepository,
    ) -> None:
        repo.log_tool_call("s1", "echo", {"x": 1, "y": [1, 2]})
        import json
        calls = repo.get_tool_calls("s1")
        assert json.loads(calls[0]["arguments"]) == {"x": 1, "y": [1, 2]}

    def test_handles_unicode_arguments(
        self, repo: ToolCallRepository,
    ) -> None:
        repo.log_tool_call("s1", "echo", {"text": "中文"})
        calls = repo.get_tool_calls("s1")
        import json
        assert json.loads(calls[0]["arguments"]) == {"text": "中文"}

    def test_stores_started_at(self, repo: ToolCallRepository) -> None:
        repo.log_tool_call(
            "s1", "echo", {}, started_at="2026-01-01 00:00:00",
        )
        calls = repo.get_tool_calls("s1")
        assert calls[0]["started_at"] == "2026-01-01 00:00:00"

    def test_custom_status(self, repo: ToolCallRepository) -> None:
        repo.log_tool_call("s1", "echo", {}, status="running")
        calls = repo.get_tool_calls("s1")
        assert calls[0]["status"] == "running"


class TestUpdate:
    def test_updates_result_status(self, repo: ToolCallRepository) -> None:
        call_id = repo.log_tool_call("s1", "echo", {"x": 1})
        repo.update_tool_call(call_id, {"output": "ok"}, "success")
        calls = repo.get_tool_calls("s1")
        import json
        assert json.loads(calls[0]["result"]) == {"output": "ok"}
        assert calls[0]["status"] == "success"

    def test_accepts_string_result(self, repo: ToolCallRepository) -> None:
        call_id = repo.log_tool_call("s1", "echo", {})
        repo.update_tool_call(call_id, "raw string result", "success")
        calls = repo.get_tool_calls("s1")
        assert calls[0]["result"] == "raw string result"

    def test_stores_finished_at(self, repo: ToolCallRepository) -> None:
        call_id = repo.log_tool_call("s1", "echo", {})
        repo.update_tool_call(
            call_id, "ok", "success",
            finished_at="2026-01-01 00:01:00",
        )
        calls = repo.get_tool_calls("s1")
        assert calls[0]["finished_at"] == "2026-01-01 00:01:00"


class TestGet:
    def test_empty_returns_empty_list(
        self, repo: ToolCallRepository,
    ) -> None:
        assert repo.get_tool_calls("s1") == []

    def test_filters_by_session(self, repo: ToolCallRepository) -> None:
        repo.log_tool_call("s1", "a", {})
        repo.log_tool_call("s1", "b", {})
        repo.log_tool_call("s2", "c", {})
        s1_calls = repo.get_tool_calls("s1")
        assert len(s1_calls) == 2
        assert all(c["session_id"] == "s1" for c in s1_calls)
        s2_calls = repo.get_tool_calls("s2")
        assert len(s2_calls) == 1


class TestDeleteAfterRowid:
    """Cross-repo callback for ChatMessageRepository.revert_to_message."""

    def test_deletes_calls_with_higher_rowid(
        self, repo: ToolCallRepository,
    ) -> None:
        a = repo.log_tool_call("s1", "a", {})
        repo.log_tool_call("s1", "b", {})
        repo.log_tool_call("s1", "c", {})
        # Get rowid of 'a' (the cut point)
        import sqlite3
        with sqlite3.connect(repo.db_path) as conn:
            target_rowid = conn.execute(
                "SELECT rowid FROM tool_calls WHERE id = ?", (a,),
            ).fetchone()[0]
            n = repo.delete_after_rowid(conn, "s1", target_rowid)
        # 'b' and 'c' are deleted (2 rows)
        assert n == 2
        # Only 'a' remains
        remaining = repo.get_tool_calls("s1")
        assert len(remaining) == 1
        assert remaining[0]["id"] == a

    def test_no_matches_returns_zero(
        self, repo: ToolCallRepository,
    ) -> None:
        repo.log_tool_call("s1", "a", {})
        import sqlite3
        with sqlite3.connect(repo.db_path) as conn:
            n = repo.delete_after_rowid(conn, "s1", 9999)
        assert n == 0
