"""Tests for ConfirmationManager (Phase 5 extraction)."""
from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.chat.agent.confirmation_manager import ConfirmationManager

# ── Stubs ───────────────────────────────────────────────────────


class _FakeRegistry:
    """Minimal tool registry that records calls and returns scripted results."""

    def __init__(
        self,
        pending: dict[str, list[dict]] | None = None,
        confirm_result: dict | None = None,
        reject_result: dict | None = None,
    ) -> None:
        self._pending = pending or {}
        self._confirm_result = confirm_result
        self._reject_result = reject_result
        self.confirm_calls: list[tuple[str, dict | None]] = []
        self.reject_calls: list[str] = []

    def get_pending_by_group(self) -> dict[str, list[dict]]:
        return self._pending

    def confirm_execution(self, cid: str, args: dict | None) -> dict:
        self.confirm_calls.append((cid, args))
        return self._confirm_result or {"status": "ok", "result": "executed"}

    def reject_execution(self, cid: str) -> dict:
        self.reject_calls.append(cid)
        return self._reject_result or {"status": "ok"}


def _make_mgr(
    registries: dict[tuple[str, str], _FakeRegistry] | None = None,
) -> tuple[ConfirmationManager, dict[tuple[str, str], _FakeRegistry]]:
    registries = registries if registries is not None else {}
    mgr = ConfirmationManager(registries)
    return mgr, registries


# ── is_unknown_confirmation ──────────────────────────────────────


class TestIsUnknownConfirmation:
    def test_returns_false_for_non_dict(self) -> None:
        assert ConfirmationManager.is_unknown_confirmation("error") is False
        assert ConfirmationManager.is_unknown_confirmation(None) is False

    def test_returns_false_for_dict_without_error_status(self) -> None:
        assert ConfirmationManager.is_unknown_confirmation(
            {"status": "ok"}
        ) is False

    def test_returns_false_for_unrelated_error(self) -> None:
        assert ConfirmationManager.is_unknown_confirmation(
            {"status": "error", "error": "Permission denied"}
        ) is False

    def test_returns_true_for_unknown_confirmation_id(self) -> None:
        assert ConfirmationManager.is_unknown_confirmation(
            {"status": "error", "error": "Unknown confirmation ID: c1"}
        ) is True

    def test_returns_true_for_invalid_confirmation_id(self) -> None:
        assert ConfirmationManager.is_unknown_confirmation(
            {"status": "error", "error": "Invalid confirmation ID: c1"}
        ) is True


# ── list_confirmations ───────────────────────────────────────────


class TestListConfirmations:
    def test_empty_registries_returns_empty(self) -> None:
        mgr, _ = _make_mgr()
        assert mgr.list_confirmations() == {}

    def test_groups_by_tool_group(self) -> None:
        reg = _FakeRegistry(
            pending={
                "read_file": [{"id": "c1"}],
                "exec": [{"id": "c2"}],
            },
        )
        mgr, _ = _make_mgr({("s1", "w1"): reg})
        result = mgr.list_confirmations()
        assert set(result.keys()) == {"read_file", "exec"}
        assert result["read_file"] == [{"id": "c1"}]
        assert result["exec"] == [{"id": "c2"}]

    def test_wiki_id_filter_excludes_other_wikis(self) -> None:
        reg1 = _FakeRegistry(pending={"g1": [{"id": "a"}]})
        reg2 = _FakeRegistry(pending={"g1": [{"id": "b"}]})
        mgr, _ = _make_mgr({("s1", "w1"): reg1, ("s2", "w2"): reg2})
        result = mgr.list_confirmations(wiki_id="w1")
        assert result == {"g1": [{"id": "a"}]}

    def test_aggregates_across_sessions_in_same_wiki(self) -> None:
        reg1 = _FakeRegistry(pending={"g": [{"id": "1"}]})
        reg2 = _FakeRegistry(pending={"g": [{"id": "2"}]})
        mgr, _ = _make_mgr({("s1", "w1"): reg1, ("s2", "w1"): reg2})
        result = mgr.list_confirmations(wiki_id="w1")
        assert sorted(item["id"] for item in result["g"]) == ["1", "2"]


# ── approve_confirmation ─────────────────────────────────────────


class TestApproveConfirmation:
    def test_returns_unknown_when_no_registries(self) -> None:
        mgr, _ = _make_mgr()
        result = asyncio.run(mgr.approve_confirmation("c1"))
        assert result["status"] == "error"
        assert "Invalid confirmation ID: c1" in result["error"]

    def test_routes_to_matching_registry(self) -> None:
        reg = _FakeRegistry(confirm_result={"status": "ok", "result": "done"})
        mgr, _ = _make_mgr({("s1", "w1"): reg})
        result = asyncio.run(mgr.approve_confirmation("c1", "w1", {"x": 1}))
        assert result == {"status": "ok", "result": "done"}
        assert reg.confirm_calls == [("c1", {"x": 1})]

    def test_skips_unknown_results(self) -> None:
        reg_unknown = _FakeRegistry(
            confirm_result={"status": "error", "error": "Unknown confirmation ID: c1"},
        )
        reg_match = _FakeRegistry(
            confirm_result={"status": "ok", "result": "found"},
        )
        mgr, _ = _make_mgr({("s1", "w1"): reg_unknown, ("s2", "w1"): reg_match})
        result = asyncio.run(mgr.approve_confirmation("c1", "w1"))
        assert result["status"] == "ok"

    def test_returns_unknown_when_all_registries_reject(self) -> None:
        reg = _FakeRegistry(
            confirm_result={"status": "error", "error": "Unknown confirmation ID: c1"},
        )
        mgr, _ = _make_mgr({("s1", "w1"): reg})
        result = asyncio.run(mgr.approve_confirmation("c1", "w1"))
        assert result["status"] == "error"


# ── reject_confirmation ──────────────────────────────────────────


class TestRejectConfirmation:
    def test_routes_to_first_matching_registry(self) -> None:
        reg = _FakeRegistry(reject_result={"status": "ok"})
        mgr, _ = _make_mgr({("s1", "w1"): reg})
        result = asyncio.run(mgr.reject_confirmation("c1", "w1"))
        assert result["status"] == "ok"
        assert reg.reject_calls == ["c1"]

    def test_returns_unknown_when_no_registries(self) -> None:
        mgr, _ = _make_mgr()
        result = asyncio.run(mgr.reject_confirmation("missing"))
        assert result["status"] == "error"


# ── batch_approve_confirmations ──────────────────────────────────


class TestBatchApprove:
    def test_returns_count_and_results(self) -> None:
        reg = _FakeRegistry(confirm_result={"status": "ok", "result": "x"})
        mgr, _ = _make_mgr({("s1", "w1"): reg})
        result = asyncio.run(mgr.batch_approve_confirmations(["c1", "c2", "c3"], "w1"))
        assert result["approved"] == 3
        assert len(result["results"]) == 3
        assert all(r["status"] == "ok" for r in result["results"])

    def test_empty_list_returns_empty(self) -> None:
        mgr, _ = _make_mgr()
        result = asyncio.run(mgr.batch_approve_confirmations([]))
        assert result == {"approved": 0, "results": []}


# ── Smoke / integration ──────────────────────────────────────────


def test_manager_holds_tool_registries_reference() -> None:
    """The manager does not copy the dict — same identity preserved."""
    regs: dict = {}
    mgr = ConfirmationManager(regs)
    regs[("s", "w")] = "added later"
    # Approval will try to call .confirm_execution on the string, which
    # raises AttributeError — proves the dict is shared, not copied.
    with pytest.raises(AttributeError):
        asyncio.run(mgr.approve_confirmation("c1", "w"))
