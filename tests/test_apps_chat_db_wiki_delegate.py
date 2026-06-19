"""Tests for WikiDelegate (17 thin delegates to WikiDatabase).

Smoke-tests that the facade still works end-to-end. The real logic
lives in ``apps/wiki/db.py`` and has its own tests; here we just
verify the delegate forwards correctly.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from llmwikify.apps.chat.db import ChatDatabase


@pytest.fixture
def db(tmp_path: Path) -> ChatDatabase:
    return ChatDatabase(tmp_path)


# ─── Notifications (4) ─────────────────────────────────────────


class TestNotifications:
    def test_save_and_list(self, db: ChatDatabase) -> None:
        nid = str(uuid.uuid4())
        db.save_notification({
            "id": nid, "wiki_id": "w1", "title": "Test",
        })
        notifs = db.list_notifications("w1")
        assert len(notifs) == 1
        assert notifs[0]["id"] == nid

    def test_list_unread_only(self, db: ChatDatabase) -> None:
        db.save_notification({
            "id": "a", "wiki_id": "w", "read": False,
        })
        db.save_notification({
            "id": "b", "wiki_id": "w", "read": True,
        })
        unread = db.list_notifications("w", unread_only=True)
        assert len(unread) == 1
        assert unread[0]["id"] == "a"

    def test_mark_read(self, db: ChatDatabase) -> None:
        db.save_notification({
            "id": "a", "wiki_id": "w", "read": False,
        })
        db.mark_notification_read("a")
        unread = db.list_notifications("w", unread_only=True)
        assert unread == []

    def test_get_unread_count(self, db: ChatDatabase) -> None:
        db.save_notification({
            "id": "a", "wiki_id": "w", "read": False,
        })
        db.save_notification({
            "id": "b", "wiki_id": "w", "read": True,
        })
        count = db.get_unread_count("w")
        assert count == 1


# ─── Confirmations (6) ──────────────────────────────────────────


class TestConfirmations:
    def test_save_and_get(self, db: ChatDatabase) -> None:
        cid = str(uuid.uuid4())
        db.save_confirmation({
            "id": cid, "wiki_id": "w", "tool": "echo",
            "arguments": {"x": 1}, "status": "pending",
        })
        c = db.get_confirmation(cid)
        assert c is not None
        # Schema uses 'tool' column (not 'tool_name')
        assert c["tool"] == "echo"
        # arguments is JSON-encoded
        import json
        assert json.loads(c["arguments"]) == {"x": 1}

    def test_list_confirmations(self, db: ChatDatabase) -> None:
        db.save_confirmation({
            "id": "a", "wiki_id": "w", "tool": "echo",
            "arguments": {}, "status": "pending",
        })
        db.save_confirmation({
            "id": "b", "wiki_id": "w", "tool": "read",
            "arguments": {}, "status": "approved",
        })
        pending = db.get_confirmations("w", status="pending")
        assert len(pending) == 1
        assert pending[0]["id"] == "a"

    def test_update_status(self, db: ChatDatabase) -> None:
        db.save_confirmation({
            "id": "a", "wiki_id": "w", "tool": "echo",
            "arguments": {}, "status": "pending",
        })
        db.update_confirmation_status("a", "approved")
        c = db.get_confirmation("a")
        assert c["status"] == "approved"

    def test_update_arguments(self, db: ChatDatabase) -> None:
        db.save_confirmation({
            "id": "a", "wiki_id": "w", "tool": "echo",
            "arguments": {"x": 1}, "status": "pending",
        })
        db.update_confirmation_arguments("a", {"y": 2})
        c = db.get_confirmation("a")
        # arguments is JSON-encoded by the underlying DB
        import json
        assert json.loads(c["arguments"]) == {"y": 2}

    def test_delete_confirmation(self, db: ChatDatabase) -> None:
        db.save_confirmation({
            "id": "a", "wiki_id": "w", "tool": "echo",
            "arguments": {}, "status": "pending",
        })
        db.delete_confirmation("a")
        assert db.get_confirmation("a") is None

    def test_missing_returns_none(self, db: ChatDatabase) -> None:
        assert db.get_confirmation("nonexistent") is None


# ─── Ingest log (3) ─────────────────────────────────────────────


class TestIngestLog:
    def test_log_and_get(self, db: ChatDatabase) -> None:
        iid = str(uuid.uuid4())
        db.log_ingest({
            "id": iid, "wiki_id": "w",
            "tool": "pdf", "status": "ok",
            "result_summary": "ingested",
        })
        entries = db.get_ingest_log("w")
        assert len(entries) == 1
        assert entries[0]["id"] == iid

    def test_get_ingest_entry(self, db: ChatDatabase) -> None:
        iid = str(uuid.uuid4())
        db.log_ingest({
            "id": iid, "wiki_id": "w",
            "tool": "pdf", "status": "ok",
            "result_summary": "ingested",
        })
        entry = db.get_ingest_entry(iid)
        assert entry is not None
        assert entry["tool"] == "pdf"
        assert entry["result_summary"] == "ingested"

    def test_limit_respected(self, db: ChatDatabase) -> None:
        for i in range(5):
            db.log_ingest({
                "id": f"e{i}", "wiki_id": "w",
                "tool": "pdf", "status": "ok",
            })
        entries = db.get_ingest_log("w", limit=3)
        assert len(entries) == 3


# ─── Dream proposals (4) ────────────────────────────────────────


class TestDreamProposals:
    def test_save_and_get(self, db: ChatDatabase) -> None:
        pid = str(uuid.uuid4())
        db.save_dream_proposal({
            "id": pid, "wiki_id": "w", "title": "Dream 1",
            "status": "pending",
        })
        proposals = db.get_dream_proposals("w")
        assert len(proposals) == 1
        assert proposals[0]["id"] == pid

    def test_update_status(self, db: ChatDatabase) -> None:
        pid = str(uuid.uuid4())
        db.save_dream_proposal({
            "id": pid, "wiki_id": "w", "title": "x", "status": "pending",
        })
        db.update_dream_proposal_status(pid, "approved")
        proposals = db.get_dream_proposals("w")
        assert proposals[0]["status"] == "approved"

    def test_get_stats(self, db: ChatDatabase) -> None:
        stats = db.get_dream_proposal_stats("w")
        assert "total" in stats or "pending" in stats or stats == {}
