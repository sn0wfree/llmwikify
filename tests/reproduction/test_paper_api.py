"""Paper API tests — all 8 endpoints."""

from __future__ import annotations

from pathlib import Path


def _start_paper(client, **overrides):
    """Helper to POST /api/paper/start with defaults."""
    payload = {
        "paper_id": "test-paper-001",
        "source_type": "pdf",
        "source_ref": "/tmp/test.pdf",
        "paper_content": "Test content about momentum strategy",
        **overrides,
    }
    return client.post("/api/paper/start", json=payload)


# ── POST /start ───────────────────────────────────────────────


def test_start_returns_session_id(paper_client):
    client, _, _ = paper_client
    r = _start_paper(client)
    assert r.status_code == 200
    body = r.json()
    assert body["paper_id"] == "test-paper-001"
    assert "session_id" in body
    assert body["status"] == "pending"


def test_start_default_wiki_id(paper_client):
    """When wiki_id is omitted, DB gets a resolved wiki_id (not NULL)."""
    client, _, db = paper_client
    r = _start_paper(client)
    sid = r.json()["session_id"]
    sess = db.get_session(sid)
    assert sess is not None
    assert sess.wiki_id  # Not empty/None


def test_start_explicit_wiki_id(paper_client):
    client, _, db = paper_client
    r = _start_paper(client, wiki_id="my-wiki")
    sid = r.json()["session_id"]
    sess = db.get_session(sid)
    assert sess.wiki_id == "my-wiki"


def test_start_invalid_source_type(paper_client):
    client, _, _ = paper_client
    r = _start_paper(client, source_type="csv")
    assert r.status_code == 422


# ── GET /list ─────────────────────────────────────────────────


def test_list_empty(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/list")
    assert r.status_code == 200
    assert r.json()["sessions"] == []


def test_list_with_sessions(paper_client):
    client, _, _ = paper_client
    _start_paper(client, paper_id="p1")
    _start_paper(client, paper_id="p2")
    _start_paper(client, paper_id="p3")
    r = client.get("/api/paper/list")
    assert r.status_code == 200
    assert len(r.json()["sessions"]) == 3


def test_list_filter_status(paper_client):
    client, _, db = paper_client
    # Background tasks run synchronously in TestClient, so sessions
    # end up as "done" (empty extraction → no LLM). Test filtering
    # by creating one session then manually changing its status.
    r1 = _start_paper(client, paper_id="session-a")
    sid_a = r1.json()["session_id"]
    r2 = _start_paper(client, paper_id="session-b")
    sid_b = r2.json()["session_id"]
    # Both are "done" now; change one to "error"
    db.update_status(sid_a, "error", error="test error")
    r = client.get("/api/paper/list?status=error")
    sessions = r.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["paper_id"] == "session-a"


# ── GET /list-raw ─────────────────────────────────────────────


def test_list_raw_empty(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/list-raw")
    assert r.status_code == 200
    assert r.json()["files"] == []


def test_list_raw(paper_client):
    client, wiki, _ = paper_client
    from llmwikify.interfaces.server.http import paper as mod
    (mod._RAW_DIR / "alpha.pdf").write_bytes(b"%PDF-1.4 fake")
    (mod._RAW_DIR / "beta.pdf").write_bytes(b"%PDF-1.4 fake")
    (mod._RAW_DIR / "ignore.txt").write_text("not pdf")
    r = client.get("/api/paper/list-raw")
    names = {f["filename"] for f in r.json()["files"]}
    assert names == {"alpha.pdf", "beta.pdf"}
    # Each file has path, size_bytes, mtime
    for f in r.json()["files"]:
        assert "path" in f
        assert "size_bytes" in f
        assert "mtime" in f


# ── POST /upload ──────────────────────────────────────────────


def test_upload_pdf(paper_client):
    client, _, _ = paper_client
    r = client.post(
        "/api/paper/upload",
        data={"paper_id": "upload-test"},
        files={"file": ("test.pdf", b"%PDF-1.4 content", "application/pdf")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["paper_id"] == "upload-test"
    assert body["size_bytes"] == len(b"%PDF-1.4 content")
    assert Path(body["path"]).exists()


def test_upload_rejects_non_pdf(paper_client):
    client, _, _ = paper_client
    r = client.post(
        "/api/paper/upload",
        data={"paper_id": "x"},
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_upload_rejects_empty(paper_client):
    client, _, _ = paper_client
    r = client.post(
        "/api/paper/upload",
        data={"paper_id": "x"},
        files={"file": ("test.pdf", b"", "application/pdf")},
    )
    assert r.status_code == 400


# ── GET /{sid}/status ────────────────────────────────────────


def test_status_returns_session_and_events(paper_client):
    client, _, _ = paper_client
    r = _start_paper(client, paper_id="status-test")
    sid = r.json()["session_id"]
    r2 = client.get(f"/api/paper/{sid}/status")
    assert r2.status_code == 200
    body = r2.json()
    assert body["session"]["paper_id"] == "status-test"
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 1
    assert body["events"][0]["event_type"] == "extract.started"
    assert isinstance(body["artifacts"], list)


def test_status_not_found(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/nonexistent-sid/status")
    assert r.status_code == 404


# ── GET /{paper_id} (legacy) ──────────────────────────────────


def test_legacy_paper_id(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/test-001")
    assert r.status_code == 200
    body = r.json()
    assert body["paper_id"] == "test-001"
    # logic_page may be None if not written yet
    assert "logic_page" in body


# ── GET /{paper_id}/artifacts (legacy) ────────────────────────


def test_legacy_artifacts(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/test-001/artifacts")
    assert r.status_code == 200
    body = r.json()
    assert body["paper_id"] == "test-001"
    assert isinstance(body["artifacts"], list)


# ── DELETE /{sid} ─────────────────────────────────────────────


def test_delete_session(paper_client):
    client, _, db = paper_client
    r = _start_paper(client, paper_id="to-delete")
    sid = r.json()["session_id"]
    # Delete
    r2 = client.delete(f"/api/paper/{sid}")
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    # Verify gone
    r3 = client.get(f"/api/paper/{sid}/status")
    assert r3.status_code == 404


def test_delete_not_found(paper_client):
    client, _, _ = paper_client
    r = client.delete("/api/paper/nonexistent-sid")
    assert r.status_code == 404
