"""WebUI-side verification: proposals created by maintenance are visible
and approvable through the paths the WebUI actually uses.

The review UI reads ``WikiService.get_wiki_dream_proposals()`` →
``WikiDreamEditor.proposal_manager`` and approves through
``approve_wiki_dream_proposal()``. Maintenance (auto-ingest / gap filler /
enricher) writes through its own ``WikiDreamProposalManager`` instance.
These tests pin that the two sides meet — which is what the
cross-instance DB fix was for.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


def _db(tmp_path):
    from llmwikify.apps.wiki_db import WikiDatabase

    return WikiDatabase(tmp_path / "data")


def _editor(db, tmp_path):
    from llmwikify.apps.agent.wiki_dream_editor import WikiDreamEditor

    return WikiDreamEditor(
        wiki=SimpleNamespace(root=tmp_path),
        db=db,
        wiki_id="w1",
    )


def _enricher_manager(db):
    from llmwikify.apps.agent.wiki_dream_editor import WikiDreamProposalManager

    return WikiDreamProposalManager(db=db, wiki_id="w1")


# ── editor layer (what the WebUI reads through) ─────────────────────


def test_editor_sees_proposal_created_by_maintenance(tmp_path):
    """A proposal written by another manager must show up in the editor."""
    db = _db(tmp_path)
    maintenance = _enricher_manager(db)
    editor = _editor(db, tmp_path)

    created = maintenance.create_proposal(
        page_name="Monte Carlo Simulation",
        edit_type="create",
        content="# Monte Carlo Simulation\n\n(pending human review)",
        reason="enricher: page suggested by the new source has no page yet",
    )

    pending = editor.proposal_manager.get_pending_by_page()
    assert "Monte Carlo Simulation" in pending
    assert any(p["id"] == created["id"] for p in pending["Monte Carlo Simulation"])
    assert pending["Monte Carlo Simulation"][0]["reason"].startswith("enricher:")


def test_editor_approves_proposal_created_by_maintenance(tmp_path):
    """The WebUI's approve must work on a proposal it did not create."""
    db = _db(tmp_path)
    maintenance = _enricher_manager(db)
    editor = _editor(db, tmp_path)

    created = maintenance.create_proposal(
        page_name="P", edit_type="create", content="x", reason="r"
    )

    approved = editor.proposal_manager.approve(created["id"])
    assert approved is not None
    assert approved["status"] == "approved"
    # the writer sees the outcome too
    assert maintenance.get_proposal(created["id"])["status"] == "approved"


def test_editor_rejects_proposal_created_by_maintenance(tmp_path):
    db = _db(tmp_path)
    maintenance = _enricher_manager(db)
    editor = _editor(db, tmp_path)

    created = maintenance.create_proposal(
        page_name="P", edit_type="create", content="x", reason="r"
    )

    rejected = editor.proposal_manager.reject(created["id"])
    assert rejected is not None
    assert rejected["status"] == "rejected"
    # no longer pending
    assert all(
        p["id"] != created["id"]
        for items in editor.proposal_manager.get_pending_by_page().values()
        for p in items
    )


def test_editor_stats_count_db_rows(tmp_path):
    """Stats must reflect the shared database, not a local snapshot."""
    db = _db(tmp_path)
    maintenance = _enricher_manager(db)
    editor = _editor(db, tmp_path)

    for i in range(3):
        maintenance.create_proposal(
            page_name=f"P{i}", edit_type="create", content="x", reason="r"
        )

    stats = editor.proposal_manager.get_stats()
    assert stats.get("pending", 0) >= 3


# ── HTTP layer (routes → service) ───────────────────────────────────


class _ServiceStub:
    """Stands in for AgentService: records calls, returns canned data."""

    def __init__(self, proposals: dict[str, Any]) -> None:
        self.proposals = proposals
        self.approved: list[str] = []
        self.rejected: list[str] = []

    def get_wiki_dream_proposals(self, wiki_id: str | None = None) -> dict:
        return self.proposals

    def approve_wiki_dream_proposal(self, proposal_id: str) -> dict:
        self.approved.append(proposal_id)
        return {"id": proposal_id, "status": "approved"}

    def reject_wiki_dream_proposal(self, proposal_id: str) -> dict:
        self.rejected.append(proposal_id)
        return {"id": proposal_id, "status": "rejected"}

    def batch_approve_wiki_dream_proposals(self, ids: list[str]) -> dict:
        return {"approved": len(ids), "results": []}

    def get_wiki_dream_log(self, wiki_id: str | None = None, limit: int = 20) -> list:
        return []

    async def run_wiki_dream(self, wiki_id: str | None = None) -> dict:
        return {"pending_review": 0}

    async def apply_wiki_dream_proposals(
        self, wiki_id: str | None = None, proposal_ids: list[str] | None = None
    ) -> dict:
        return {"applied": 0, "errors": 0}


@pytest.fixture
def client(tmp_path):
    """FastAPI app with the dream routes wired to a stub service."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from llmwikify.interfaces.server.http.agent import _common

    app = FastAPI()
    from llmwikify.interfaces.server.http.agent import dream  # noqa: F401

    app.include_router(_common.router)

    stub = _ServiceStub(
        proposals={
            "proposals": {
                "Monte Carlo Simulation": [
                    {
                        "id": "prop-abc123",
                        "page_name": "Monte Carlo Simulation",
                        "edit_type": "create",
                        "content": "# Monte Carlo Simulation",
                        "reason": "enricher: page suggested by the new source",
                        "content_length": 25,
                        "status": "pending",
                        "created_at": "2026-11-03T00:00:00+00:00",
                        "reviewed_at": None,
                    }
                ]
            },
            "stats": {"pending": 1},
        }
    )

    # Restore the *previous* global, not None — another test may have
    # installed a service. try/finally so a setup failure (before the
    # yield) cannot leak the stub into the rest of the session.
    original = _common.AGENT_SERVICE
    try:
        _common.set_agent_service(stub)  # type: ignore[arg-type]
        with TestClient(app) as c:
            yield c, stub
    finally:
        _common.set_agent_service(original)  # type: ignore[arg-type]


def test_http_proposals_endpoint_returns_maintenance_proposal(client):
    """GET /agent/wiki-dream/proposals surfaces the proposal to the UI."""
    c, stub = client
    resp = c.get("/api/agent/wiki-dream/proposals")

    assert resp.status_code == 200
    body = resp.json()
    assert "Monte Carlo Simulation" in body["proposals"]
    item = body["proposals"]["Monte Carlo Simulation"][0]
    assert item["id"] == "prop-abc123"
    assert item["status"] == "pending"
    assert item["reason"].startswith("enricher:")


def test_http_approve_reaches_service(client):
    c, stub = client
    resp = c.post("/api/agent/wiki-dream/proposals/prop-abc123/approve")

    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert stub.approved == ["prop-abc123"]


def test_http_reject_reaches_service(client):
    c, stub = client
    resp = c.post("/api/agent/wiki-dream/proposals/prop-abc123/reject")

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert stub.rejected == ["prop-abc123"]


def test_http_batch_approve_reaches_service(client):
    c, stub = client
    resp = c.post(
        "/api/agent/wiki-dream/proposals/batch-approve",
        json={"ids": ["prop-abc123", "prop-def456"]},
    )

    assert resp.status_code == 200
    assert resp.json()["approved"] == 2
