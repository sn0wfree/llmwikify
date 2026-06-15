"""Tests that the status tool returns compact responses by default.

Regression test for the "显示都乱了" bug where the status tool
returned ~53K tokens of duplicated / verbose data, garbling the
chat UI display and wasting LLM context.

The fix:
- Default response is now <2K bytes (~175 tokens).
- Per-phase outputs are NOT included by default.
- A new ``include_details`` flag is opt-in for getting the full
  final report (autoresearch) or full per-phase outputs (workflow).
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.skills.autoresearch_compound_skill import (
    _handle_status as ar_status,
)
from llmwikify.apps.chat.skills.workflows.skill import (
    _handle_status as wf_status,
)


# ─── Fixtures ───────────────────────────────────────────────────


def _make_fake_state(run_id: str = "wf_test_001") -> MagicMock:
    """Build a fake RunState with full outputs to verify the handler
    doesn't return them by default.
    """
    state = MagicMock()
    state.run_id = run_id
    state.workflow_name = "autoresearch-compound"
    state.status = "ok"
    state.total_tokens_used = 12345
    state.total_agents_spawned = 11
    state.started_at = 1700000000.0
    state.last_updated = 1700000500.0
    state.phases = {
        "clarify": {"status": "complete", "output": {"research_question": "X"}},
        "plan": {"status": "complete", "output": {"phases": [1, 2, 3]}},
        "gather_evidence": {
            "status": "complete",
            "output": {
                "findings": [{"id": f"f-{i}", "claim": "x" * 200} for i in range(34)],
                "instances": [
                    {"id": f"e-{i}", "evidence_items": [{}] * 10}
                    for i in range(6)
                ],
            },
        },
        "extract_findings": {"status": "complete", "output": {"findings": []}},
        "propose_wiki_updates": {
            "status": "complete",
            "output": {"wiki_update_proposals": [{}] * 3},
        },
        "synthesize": {
            "status": "complete",
            "output": {
                "answer": "A" * 2000,
                "final_report_markdown": "# Report\n" + ("x" * 5000),
                "evidence_items": [{}] * 44,
                "findings": [{}] * 19,
                "wiki_update_proposals": [{}] * 3,
                "graph_relations": [{}] * 18,
                "research_memory": {"reusable_facts": []},
                "quality": {"confidence": "high"},
            },
        },
        "evidence_0": {"status": "complete", "output": {"x": "y" * 1000}},
        "evidence_1": {"status": "complete", "output": {"x": "y" * 1000}},
        "evidence_2": {"status": "complete", "output": {"x": "y" * 1000}},
        "evidence_3": {"status": "complete", "output": {"x": "y" * 1000}},
        "evidence_4": {"status": "complete", "output": {"x": "y" * 1000}},
        "evidence_5": {"status": "complete", "output": {"x": "y" * 1000}},
    }
    return state


@pytest.fixture
def ctx() -> MagicMock:
    return MagicMock()


# ─── autoresearch_compound_skill status ─────────────────────────


def test_autoresearch_status_default_is_compact(
    monkeypatch: pytest.MonkeyPatch, ctx: MagicMock
) -> None:
    """Default status call returns <2K tokens."""
    from llmwikify.apps.chat.skills import autoresearch_compound_skill as mod

    monkeypatch.setattr(
        mod.RunStore, "default",
        lambda: MagicMock(load=MagicMock(return_value=_make_fake_state())),
    )
    result = ar_status({"run_id": "wf_test_001"}, ctx)
    assert result.status == "ok"
    data = result.data
    assert "phases" not in data, "phases should not be in default response"
    assert "proposal_bundle" not in data, "duplicate field should be removed"
    assert "phases_summary" in data
    assert "artifact_counts" in data
    response_json = json.dumps(data, ensure_ascii=False)
    assert len(response_json) < 2000, (
        f"Default response too large: {len(response_json)} bytes "
        f"(expected <2000). Display will be garbled."
    )
    assert len(data["phases_summary"]) == 12  # 6 main + 6 evidence


def test_autoresearch_status_include_details_returns_final_report(
    monkeypatch: pytest.MonkeyPatch, ctx: MagicMock
) -> None:
    """include_details=true adds the final report but not full phases."""
    from llmwikify.apps.chat.skills import autoresearch_compound_skill as mod

    monkeypatch.setattr(
        mod.RunStore, "default",
        lambda: MagicMock(load=MagicMock(return_value=_make_fake_state())),
    )
    result = ar_status(
        {"run_id": "wf_test_001", "include_details": True}, ctx
    )
    data = result.data
    assert "final_report" in data
    assert "phases" not in data
    assert "proposal_bundle" not in data
    assert "final_report_markdown" in data["final_report"]


def test_autoresearch_status_phase_summary_includes_errors(
    monkeypatch: pytest.MonkeyPatch, ctx: MagicMock
) -> None:
    """Failed phases appear in summary with truncated error string."""
    from llmwikify.apps.chat.skills import autoresearch_compound_skill as mod

    state = _make_fake_state()
    state.phases["synthesize"] = {
        "status": "failed",
        "output": {"_error": "X" * 1000},  # longer than 300 char limit
    }
    monkeypatch.setattr(
        mod.RunStore, "default",
        lambda: MagicMock(load=MagicMock(return_value=state)),
    )
    result = ar_status({"run_id": "wf_test_001"}, ctx)
    syn_summary = result.data["phases_summary"]["synthesize"]
    assert syn_summary["status"] == "failed"
    assert "error" in syn_summary
    assert len(syn_summary["error"]) <= 300


def test_autoresearch_status_missing_run_id_fails(ctx: MagicMock) -> None:
    """Status without run_id returns a clean error."""
    result = ar_status({}, ctx)
    assert result.status == "error"
    assert "run_id" in result.error


def test_autoresearch_status_unknown_run_id_fails(
    monkeypatch: pytest.MonkeyPatch, ctx: MagicMock
) -> None:
    """Status with non-existent run_id returns a clean error."""
    from llmwikify.apps.chat.skills import autoresearch_compound_skill as mod

    monkeypatch.setattr(
        mod.RunStore, "default",
        lambda: MagicMock(load=MagicMock(return_value=None)),
    )
    result = ar_status({"run_id": "wf_does_not_exist"}, ctx)
    assert result.status == "error"
    assert "wf_does_not_exist" in result.error


# ─── workflows/skill status ─────────────────────────────────────


def test_workflow_status_default_is_compact(
    monkeypatch: pytest.MonkeyPatch, ctx: MagicMock
) -> None:
    """Same compact behavior for the lower-level workflow status tool."""
    from llmwikify.apps.chat.skills.workflows import skill as mod

    monkeypatch.setattr(
        mod.RunStore, "default",
        lambda: MagicMock(load=MagicMock(return_value=_make_fake_state())),
    )
    result = wf_status({"run_id": "wf_test_001"}, ctx)
    data = result.data
    assert "phases_summary" in data
    assert "phases" not in data
    response_json = json.dumps(data, ensure_ascii=False)
    assert len(response_json) < 2000


def test_workflow_status_include_details_returns_phases(
    monkeypatch: pytest.MonkeyPatch, ctx: MagicMock
) -> None:
    """include_details=true returns the full phases data."""
    from llmwikify.apps.chat.skills.workflows import skill as mod

    monkeypatch.setattr(
        mod.RunStore, "default",
        lambda: MagicMock(load=MagicMock(return_value=_make_fake_state())),
    )
    result = wf_status(
        {"run_id": "wf_test_001", "include_details": True}, ctx
    )
    data = result.data
    assert "phases" in data
    assert len(data["phases"]) == 12
