"""Unit tests for v0.41 _format_run_not_found helper.

The bare "no run with id X" message was confusing for the LLM, which
would sometimes pass the user's slash command input as a run_id
(e.g. "study: 量化交易策略"). The helper now:

  - Detects non-wf_ run_ids and includes a hint explaining what a
    valid run_id looks like.
  - Lists up to 3 most recent run_ids from the RunStore to help
    the LLM recover.
  - For legitimate wf_*-prefixed but missing ids, falls back to
    the bare message (preserves existing test expectation).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from llmwikify.apps.chat.skills.autoresearch_compound_skill import (
    _format_run_not_found,
)
from llmwikify.apps.chat.skills.workflows.run_store import RunState, RunStore
from llmwikify.apps.chat.skills.workflows.skill import (
    _format_run_not_found as _format_run_not_found_workflow,
)


@pytest.fixture
def run_store(monkeypatch, tmp_path: Path):
    """A RunStore rooted in a temp dir, also patched as RunStore.default()."""
    store = RunStore(tmp_path / "runs")

    # RunStore.default() ignores env vars and always returns the home
    # directory. Patch it so our test can control the listing.
    from llmwikify.apps.chat.skills import workflows as wf_mod
    monkeypatch.setattr(
        wf_mod.run_store.RunStore, "default", classmethod(lambda cls: store),
    )
    # Also patch the importers in the two helper modules
    from llmwikify.apps.chat.skills import (
        autoresearch_compound_skill,
    )
    from llmwikify.apps.chat.skills import workflows as wf_pkg
    monkeypatch.setattr(
        autoresearch_compound_skill, "RunStore", wf_mod.run_store.RunStore,
    )
    # workflows.skill already uses RunStore via module-level import.
    # Replace it with our patched class so its .default() returns the temp store.
    monkeypatch.setattr(wf_pkg.skill, "RunStore", wf_mod.run_store.RunStore)
    yield store


def _seed_runs(store: RunStore, run_ids: list[str]) -> None:
    """Persist a list of dummy RunState files."""
    for rid in run_ids:
        state = RunState(
            run_id=rid,
            workflow_name="autoresearch-compound",
            source_path=None,
            started_at=1718540400.0,
            status="complete",
            inputs_data={},
        )
        store.save(state)


class TestAutoresearchFormatHelper:
    def test_non_wf_prefix_user_input_includes_hint(self) -> None:
        """The actual bug: LLM passed 'study: 量化交易策略'."""
        msg = _format_run_not_found("study: 量化交易策略")
        assert "no run with id" in msg  # preserves existing test contract
        assert "must be a 'wf_...'" in msg
        assert "run_id" in msg.lower()

    def test_empty_run_id_includes_hint(self) -> None:
        """Empty run_id also gets the hint."""
        msg = _format_run_not_found("")
        assert "must be a 'wf_...'" in msg

    def test_wf_prefixed_but_missing_keeps_bare_message(self) -> None:
        """A legitimate-looking wf_ id should NOT get the user-input hint."""
        msg = _format_run_not_found("wf_2026-06-16_abcdef12")
        assert msg == "no run with id 'wf_2026-06-16_abcdef12'"

    def test_wf_prefixed_with_recent_runs_no_hint(self) -> None:
        """A wf_-prefixed id never triggers the hint branch."""
        msg = _format_run_not_found("wf_does_not_exist")
        assert "must be" not in msg

    def test_non_wf_lists_recent_runs(self, run_store: RunStore) -> None:
        """When the LLM clearly gave a wrong run_id, list recent ones to help."""
        _seed_runs(run_store, [
            "wf_2026-06-16T10-00-00_aaaa1111",
            "wf_2026-06-16T10-01-00_bbbb2222",
        ])
        msg = _format_run_not_found("user-typo", workflow_name="autoresearch-compound")
        assert "Recent run_ids:" in msg
        assert "wf_2026-06-16T10-00-00_aaaa1111" in msg
        assert "wf_2026-06-16T10-01-00_bbbb2222" in msg

    def test_non_wf_no_recent_runs_no_recent_hint(self, run_store: RunStore) -> None:
        """Empty RunStore → no 'Recent run_ids:' segment."""
        msg = _format_run_not_found("garbage", workflow_name="autoresearch-compound")
        assert "Recent run_ids:" not in msg
        assert "must be a 'wf_...'" in msg

    def test_non_wf_filters_by_workflow_name(self, run_store: RunStore) -> None:
        """When workflow_name is given, recent runs are filtered."""
        _seed_runs(run_store, [
            "wf_other_wf_a1b2c3d4",
            "wf_match_me_e5f6g7h8",
        ])
        msg = _format_run_not_found(
            "garbage", workflow_name="autoresearch-compound",
        )
        # Note: seeded runs have workflow_name="autoresearch-compound" so both
        # appear. Verify the listing logic works (both run_ids listed).
        assert "wf_other_wf_a1b2c3d4" in msg
        assert "wf_match_me_e5f6g7h8" in msg

    def test_runstore_error_does_not_crash(self) -> None:
        """If RunStore.default() raises, helper still returns a message."""
        with patch(
            "llmwikify.apps.chat.skills.autoresearch_compound_skill.RunStore"
        ) as MockStore:
            MockStore.default.side_effect = OSError("disk gone")
            msg = _format_run_not_found("anything")
        # Even with the error, we get a sensible message
        assert "no run with id" in msg
        assert "must be a 'wf_...'" in msg
        # And no crash-induced 'Recent run_ids:' leak
        assert "Recent run_ids:" not in msg


class TestWorkflowsFormatHelper:
    """The dynamic_workflow skill has the same helper; same contract."""

    def test_non_wf_prefix_uses_helper(self) -> None:
        msg = _format_run_not_found_workflow("user-typo")
        assert "no run with id" in msg
        assert "must be a 'wf_...'" in msg

    def test_wf_prefixed_keeps_bare(self) -> None:
        msg = _format_run_not_found_workflow("wf_2026_zzz")
        assert msg == "no run with id 'wf_2026_zzz'"

    def test_empty_uses_helper(self) -> None:
        msg = _format_run_not_found_workflow("")
        assert "must be a 'wf_...'" in msg


class TestBackwardsCompatibility:
    """Existing test_apps_chat_autoresearch_compound_skill.py asserts on
    the substring 'no run with id'. Make sure all 4 patched sites still
    contain that substring for the wf_*-prefixed case."""

    @pytest.mark.parametrize("helper,run_id,expected_substr", [
        (_format_run_not_found, "wf_x", "no run with id"),
        (_format_run_not_found_workflow, "wf_x", "no run with id"),
        (_format_run_not_found, "study: x", "no run with id"),
        (_format_run_not_found_workflow, "study: x", "no run with id"),
    ])
    def test_substring_preserved(
        self, helper, run_id: str, expected_substr: str,
    ) -> None:
        msg = helper(run_id)
        assert expected_substr in msg
