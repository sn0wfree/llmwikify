"""Tests for orchestrator.goal_active_predicate (O-2 extraction).

The function used to be a closure inside
``ChatOrchestrator._build_chat_runner_v2``. Extracting it as a
module-level pure function enables direct unit testing of the
goal-state semantics that the runner relies on for
``stop_reason="goal_abandoned"`` behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llmwikify.apps.chat.agent.orchestrator import goal_active_predicate


def _db_with(metadata: dict | None) -> SimpleNamespace:
    """Build a minimal DB stub with a single get_session_metadata call."""
    return SimpleNamespace(get_session_metadata=lambda sid: metadata)


class TestGoalActivePredicate:
    """Active-state detection: 4 status values + 3 missing-shape cases."""

    def test_active_goal_returns_true(self):
        db = _db_with({"goal_state": {"status": "active"}})
        assert goal_active_predicate(db, "s1") is True

    def test_completed_goal_returns_false(self):
        db = _db_with({"goal_state": {"status": "completed"}})
        assert goal_active_predicate(db, "s1") is False

    def test_abandoned_goal_returns_false(self):
        db = _db_with({"goal_state": {"status": "abandoned"}})
        assert goal_active_predicate(db, "s1") is False

    def test_unknown_status_returns_false(self):
        """Any non-'active' status (e.g. 'paused', 'failed') returns False."""
        db = _db_with({"goal_state": {"status": "paused"}})
        assert goal_active_predicate(db, "s1") is False


class TestMissingMetadata:
    """Sessions without a goal default to active (Phase 8 back-compat)."""

    def test_none_metadata_returns_true(self):
        db = _db_with(None)
        assert goal_active_predicate(db, "s1") is True

    def test_empty_metadata_returns_true(self):
        db = _db_with({})
        assert goal_active_predicate(db, "s1") is True

    def test_missing_goal_state_key_returns_true(self):
        db = _db_with({"other_key": "x"})
        assert goal_active_predicate(db, "s1") is True

    def test_non_dict_goal_state_returns_true(self):
        """A string goal_state is treated as missing (Phase 8 back-compat)."""
        db = _db_with({"goal_state": "active"})
        assert goal_active_predicate(db, "s1") is True

    def test_dict_goal_state_missing_status_returns_false(self):
        """Empty status string is not 'active', so returns False."""
        db = _db_with({"goal_state": {}})
        assert goal_active_predicate(db, "s1") is False

    def test_dict_goal_state_with_other_keys_returns_false(self):
        """status key is absent → default is falsy → not 'active'."""
        db = _db_with({"goal_state": {"owner": "alice"}})
        assert goal_active_predicate(db, "s1") is False


class TestDbShapeRobustness:
    """The predicate must not crash on unusual DB shapes."""

    def test_db_lacks_method_returns_true(self):
        db = SimpleNamespace()  # no get_session_metadata
        assert goal_active_predicate(db, "s1") is True

    def test_db_is_none_returns_true(self):
        """None db must be tolerated (e.g. test stub)."""
        assert goal_active_predicate(None, "s1") is True

    def test_db_raising_returns_true(self):
        class _RaisingDb:
            def get_session_metadata(self, sid):
                raise ConnectionError("db down")

        assert goal_active_predicate(_RaisingDb(), "s1") is True

    def test_db_returning_non_dict_returns_true(self):
        """If getter returns e.g. a list or str, treat as no goal."""
        db = SimpleNamespace(get_session_metadata=lambda sid: ["weird"])
        assert goal_active_predicate(db, "s1") is True


class TestSessionIdForwarding:
    """The session_id is forwarded verbatim to the DB layer."""

    def test_session_id_forwarded_to_getter(self):
        seen = []

        def _getter(sid):
            seen.append(sid)
            return {"goal_state": {"status": "active"}}

        db = SimpleNamespace(get_session_metadata=_getter)
        goal_active_predicate(db, "session-xyz")
        assert seen == ["session-xyz"]

    def test_session_id_forwarded_on_missing(self):
        seen = []

        def _getter(sid):
            seen.append(sid)
            return None

        db = SimpleNamespace(get_session_metadata=_getter)
        goal_active_predicate(db, "another-id")
        assert seen == ["another-id"]
