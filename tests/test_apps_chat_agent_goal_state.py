"""Tests for goal_state — Phase 8 sustained objective helpers."""

from __future__ import annotations

import json

from llmwikify.apps.chat.agent.goal_state import (
    GOAL_STATE_KEY,
    goal_state_raw,
    goal_state_runtime_lines,
    goal_state_summary,
    parse_goal_state,
    sustained_goal_active,
)


def test_parse_goal_state_returns_dict_unchanged() -> None:
    blob = {"status": "active", "objective": "x"}
    assert parse_goal_state(blob) == blob


def test_parse_goal_state_parses_json_string() -> None:
    blob = json.dumps({"status": "active", "objective": "y"})
    assert parse_goal_state(blob) == {"status": "active", "objective": "y"}


def test_parse_goal_state_returns_none_for_invalid_json() -> None:
    assert parse_goal_state("{not json") is None
    assert parse_goal_state(None) is None
    assert parse_goal_state(123) is None


def test_goal_state_raw_uses_goal_state_key() -> None:
    metadata = {GOAL_STATE_KEY: {"status": "active"}}
    assert goal_state_raw(metadata) == {"status": "active"}


def test_goal_state_raw_handles_none_metadata() -> None:
    assert goal_state_raw(None) is None
    assert goal_state_raw({}) is None


def test_sustained_goal_active_true_when_status_active() -> None:
    metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "x"}}
    assert sustained_goal_active(metadata) is True


def test_sustained_goal_active_false_when_completed() -> None:
    metadata = {GOAL_STATE_KEY: {"status": "completed", "objective": "x"}}
    assert sustained_goal_active(metadata) is False


def test_sustained_goal_active_false_when_no_metadata() -> None:
    assert sustained_goal_active(None) is False
    assert sustained_goal_active({}) is False


def test_runtime_lines_emits_objective_and_summary() -> None:
    metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Research X",
            "ui_summary": "X research",
        },
    }
    lines = goal_state_runtime_lines(metadata)
    assert lines == ["Goal (active):", "Research X", "Summary: X research"]


def test_runtime_lines_omits_summary_when_empty() -> None:
    metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Just an objective",
        },
    }
    assert goal_state_runtime_lines(metadata) == [
        "Goal (active):", "Just an objective",
    ]


def test_runtime_lines_truncates_long_objective() -> None:
    long_text = "x" * 5000
    metadata = {GOAL_STATE_KEY: {"status": "active", "objective": long_text}}
    lines = goal_state_runtime_lines(metadata)
    assert lines[0] == "Goal (active):"
    assert lines[1].endswith("… (truncated)")
    assert len(lines[1]) <= 4100


def test_runtime_lines_returns_empty_when_no_active_goal() -> None:
    assert goal_state_runtime_lines(None) == []
    assert goal_state_runtime_lines({}) == []
    assert goal_state_runtime_lines({GOAL_STATE_KEY: {"status": "completed"}}) == []


def test_runtime_lines_uses_placeholder_when_objective_blank() -> None:
    metadata = {GOAL_STATE_KEY: {"status": "active", "objective": ""}}
    assert goal_state_runtime_lines(metadata) == [
        "Goal: active (no objective text stored).",
    ]


def test_summary_active_returns_compact_dict() -> None:
    metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Research X",
            "ui_summary": "X",
            "started_at": "2026-06-20T00:00:00",
        },
    }
    out = goal_state_summary(metadata)
    assert out["active"] is True
    assert out["objective"] == "Research X"
    assert out["ui_summary"] == "X"
    assert out["started_at"] == "2026-06-20T00:00:00"


def test_summary_inactive_returns_active_false() -> None:
    assert goal_state_summary(None) == {"active": False}
    assert goal_state_summary({}) == {"active": False}
    assert goal_state_summary({GOAL_STATE_KEY: {"status": "completed"}}) == {
        "active": False,
    }


def test_summary_truncates_long_objective() -> None:
    metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "x" * 1000}}
    out = goal_state_summary(metadata)
    assert out["objective"].endswith("…")
    assert len(out["objective"]) <= 700
