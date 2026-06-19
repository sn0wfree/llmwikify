"""Tests for PermissionRepository (chat_permissions table)."""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.db import PermissionRepository


@pytest.fixture
def repo(tmp_path: Path) -> PermissionRepository:
    r = PermissionRepository(tmp_path / "test.db")
    r._init_schema()
    return r


class TestSave:
    def test_returns_uuid_hex(self, repo: PermissionRepository) -> None:
        pid = repo.save_permission("echo", "once")
        assert isinstance(pid, str)
        assert len(pid) == 32

    def test_saves_minimal_args(self, repo: PermissionRepository) -> None:
        pid = repo.save_permission("echo", "once")
        assert pid is not None
        # Verify by querying via has_always_permission (would be False for 'once')
        assert repo.has_always_permission("echo") is False

    def test_saves_with_pattern(self, repo: PermissionRepository) -> None:
        pid = repo.save_permission(
            "echo", "always", pattern="echo(.*)",
        )
        assert pid is not None

    def test_saves_with_session(self, repo: PermissionRepository) -> None:
        pid = repo.save_permission(
            "echo", "always", session_id="sess-1",
        )
        assert pid is not None


class TestHasAlways:
    def test_no_permission_returns_false(
        self, repo: PermissionRepository,
    ) -> None:
        assert repo.has_always_permission("never-used") is False

    def test_once_permission_returns_false(
        self, repo: PermissionRepository,
    ) -> None:
        repo.save_permission("echo", "once")
        assert repo.has_always_permission("echo") is False

    def test_always_permission_returns_true(
        self, repo: PermissionRepository,
    ) -> None:
        repo.save_permission("echo", "always")
        assert repo.has_always_permission("echo") is True

    def test_session_bound_always_matches(
        self, repo: PermissionRepository,
    ) -> None:
        repo.save_permission(
            "echo", "always", session_id="sess-1",
        )
        # Same session matches
        assert repo.has_always_permission("echo", "sess-1") is True
        # Different session does NOT match (session-bound)
        assert repo.has_always_permission("echo", "sess-2") is False

    def test_global_always_matches_any_session(
        self, repo: PermissionRepository,
    ) -> None:
        repo.save_permission("echo", "always", session_id=None)
        assert repo.has_always_permission("echo", "any-session") is True
        assert repo.has_always_permission("echo") is True

    def test_empty_session_id_treated_as_global(
        self, repo: PermissionRepository,
    ) -> None:
        repo.save_permission("echo", "always", session_id="")
        assert repo.has_always_permission("echo", "any") is True

    def test_other_tool_does_not_match(
        self, repo: PermissionRepository,
    ) -> None:
        repo.save_permission("echo", "always")
        assert repo.has_always_permission("other-tool") is False
