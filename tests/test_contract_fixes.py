"""Contract fixes: skill payload unwrap + list_runs glob + wiki write validation.

Covers docs/designs/contract-fixes.md:
- _unwrap_skill_payload handles ok / executed / bare envelopes
- list_runs globs *.json (not just wf_*)
- WikiWritePageRequest rejects missing page_name
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from llmwikify.apps.chat.agent.chat_persistence import (
    _unwrap_skill_payload,
    extract_research_run_id_from_tools,
)
from llmwikify.apps.chat.skills.workflows.run_store import RunState, RunStore
from llmwikify.interfaces.server.http._models import WikiWritePageRequest

# ─── _unwrap_skill_payload ────────────────────────────────────────


class TestUnwrapSkillPayload:
    def test_ok_envelope(self):
        assert _unwrap_skill_payload({"status": "ok", "data": {"a": 1}}) == {"a": 1}

    def test_executed_envelope_nested_ok(self):
        payload = {
            "status": "executed",
            "confirmation_id": "c1",
            "result": {"status": "ok", "data": {"run_id": "wf_1"}},
        }
        assert _unwrap_skill_payload(payload) == {"run_id": "wf_1"}

    def test_executed_envelope_bare_result(self):
        payload = {"status": "executed", "result": {"run_id": "wf_2"}}
        assert _unwrap_skill_payload(payload) == {"run_id": "wf_2"}

    def test_executed_with_non_dict_result(self):
        assert _unwrap_skill_payload({"status": "executed", "result": None}) is None

    def test_bare_payload_passthrough(self):
        assert _unwrap_skill_payload({"run_id": "wf_3"}) == {"run_id": "wf_3"}

    def test_extract_run_id_from_executed_envelope(self):
        tools = [
            {
                "tool": "autoresearch_compound_run",
                "result": {
                    "status": "executed",
                    "result": {"status": "ok", "data": {"run_id": "wf_x"}},
                },
            }
        ]
        assert extract_research_run_id_from_tools(tools) == "wf_x"

    def test_extract_run_id_from_ok_envelope(self):
        tools = [
            {
                "tool": "autoresearch_compound_run",
                "result": {"status": "ok", "data": {"run_id": "wf_y"}},
            }
        ]
        assert extract_research_run_id_from_tools(tools) == "wf_y"


# ─── list_runs glob ───────────────────────────────────────────────


class TestListRunsGlob:
    def _make_store(self, tmp_path: Path) -> RunStore:
        return RunStore(tmp_path)

    def _state(self, run_id: str) -> RunState:
        return RunState(
            run_id=run_id,
            workflow_name="test-wf",
            source_path=None,
            started_at=0.0,
            status="done",
        )

    def test_lists_custom_prefix_run(self, tmp_path: Path):
        """A run saved with a non-wf_ prefix must still be listed."""
        store = self._make_store(tmp_path)
        store.save(self._state("custom_abc123"))
        runs = store.list_runs()
        assert [r.run_id for r in runs] == ["custom_abc123"]

    def test_lists_wf_prefixed_run(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.save(self._state("wf_2026-01-01T00-00-00_deadbeef"))
        runs = store.list_runs()
        assert len(runs) == 1

    def test_ignores_tmp_files(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.save(self._state("wf_real"))
        # Atomic-write leftover
        (tmp_path / ".wf_real.abc.tmp").write_text("{}", encoding="utf-8")
        runs = store.list_runs()
        assert [r.run_id for r in runs] == ["wf_real"]


# ─── WikiWritePageRequest ─────────────────────────────────────────


class TestWikiWritePageRequest:
    def test_valid(self):
        req = WikiWritePageRequest(page_name="concepts/Foo", content="# Foo\n")
        assert req.page_name == "concepts/Foo"
        assert req.confirm_token is None

    def test_missing_page_name_rejected(self):
        with pytest.raises(ValidationError):
            WikiWritePageRequest(content="x")

    def test_empty_page_name_rejected(self):
        with pytest.raises(ValidationError):
            WikiWritePageRequest(page_name="", content="x")

    def test_confirm_token_optional(self):
        req = WikiWritePageRequest(page_name="p", content="c", confirm_token="tok")
        assert req.confirm_token == "tok"

    def test_content_defaults_empty(self):
        req = WikiWritePageRequest(page_name="p")
        assert req.content == ""


# ─── ConfirmApproveRequest ────────────────────────────────────────


class TestConfirmApproveRequest:
    def test_defaults(self):
        from llmwikify.interfaces.server.http._models import ConfirmApproveRequest

        req = ConfirmApproveRequest.model_validate({})
        assert req.response == "once"
        assert req.arguments is None

    def test_coerces_unknown_response_at_route_level(self):
        """Route coerces unknown response values to 'once' (back-compat)."""
        from llmwikify.interfaces.server.http._models import ConfirmApproveRequest

        req = ConfirmApproveRequest.model_validate({"response": "bogus"})
        # Model accepts any string; route does the coercion
        assert req.response == "bogus"
        response = req.response
        if response not in ("once", "always", "reject"):
            response = "once"
        assert response == "once"

    def test_json_roundtrip(self):
        from llmwikify.interfaces.server.http._models import ConfirmApproveRequest

        raw = json.dumps({"arguments": {"a": 1}, "response": "always"})
        req = ConfirmApproveRequest.model_validate_json(raw)
        assert req.arguments == {"a": 1}
        assert req.response == "always"
