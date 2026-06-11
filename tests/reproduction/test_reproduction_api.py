"""Reproduction API tests — all 5 endpoints."""

from __future__ import annotations


def _start_repro(client, **overrides):
    """Helper to POST /api/reproduction/start with defaults."""
    payload = {
        "paper_id": "repro-001",
        "source_type": "pdf",
        "source_ref": "/tmp/test.pdf",
        "symbol": "TEST",
        "start_date": "2024-01-01",
        "end_date": "2024-03-01",
        **overrides,
    }
    return client.post("/api/reproduction/start", json=payload)


# ── POST /start ───────────────────────────────────────────────


def test_start_returns_session_id(repro_client):
    client, _, _ = repro_client
    r = _start_repro(client)
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert body["status"] in {"done", "error"}


def test_start_default_wiki_id(repro_client):
    """wiki_id resolves when omitted."""
    client, _, db = repro_client
    r = _start_repro(client)
    sid = r.json()["session_id"]
    sess = db.get_session(sid)
    assert sess is not None
    assert sess.wiki_id  # Not empty/None


# ── GET /list ─────────────────────────────────────────────────


def test_list_empty(repro_client):
    client, _, _ = repro_client
    r = client.get("/api/reproduction/list")
    assert r.status_code == 200
    assert r.json()["sessions"] == []


def test_list_with_sessions(repro_client):
    client, _, _ = repro_client
    _start_repro(client, paper_id="r1")
    _start_repro(client, paper_id="r2")
    r = client.get("/api/reproduction/list")
    assert r.status_code == 200
    assert len(r.json()["sessions"]) == 2


# ── GET /{sid} ────────────────────────────────────────────────


def test_get_session(repro_client):
    client, _, _ = repro_client
    r = _start_repro(client, paper_id="get-test")
    sid = r.json()["session_id"]
    r2 = client.get(f"/api/reproduction/{sid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["session"]["id"] == sid
    assert body["session"]["symbol"] == "TEST"
    assert isinstance(body["events"], list)


def test_get_not_found(repro_client):
    client, _, _ = repro_client
    r = client.get("/api/reproduction/does-not-exist")
    assert r.status_code == 404


# ── GET /{sid}/artifacts ──────────────────────────────────────


def test_artifacts_empty(repro_client):
    client, _, _ = repro_client
    r = _start_repro(client, paper_id="art-test")
    sid = r.json()["session_id"]
    r2 = client.get(f"/api/reproduction/{sid}/artifacts")
    assert r2.status_code == 200
    body = r2.json()
    assert body["session_id"] == sid
    assert isinstance(body["artifacts"], list)


# ── DELETE /{sid} ─────────────────────────────────────────────


def test_delete_session(repro_client):
    client, _, db = repro_client
    r = _start_repro(client, paper_id="del-test")
    sid = r.json()["session_id"]
    r2 = client.delete(f"/api/reproduction/{sid}")
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    # Verify gone
    r3 = client.get(f"/api/reproduction/{sid}")
    assert r3.status_code == 404


def test_delete_not_found(repro_client):
    client, _, _ = repro_client
    r = client.delete("/api/reproduction/nonexistent-sid")
    assert r.status_code == 404
