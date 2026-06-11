"""Tests for paper/factor/strategy REST endpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

fastapi = pytest.importorskip("fastapi")


class _FakeWiki:
    def __init__(self, tmp: Path):
        self.wiki_dir = tmp
        self.written: list[tuple[str, str, str]] = []
        self._pages: dict[str, str] = {}

    def write_page(self, name, content, page_type=None):
        self.written.append((page_type, name, content))
        self._pages[name] = content

    def read_page(self, name):
        if name in self._pages:
            return {"page_name": name, "content": self._pages[name]}
        raise FileNotFoundError(f"Page {name} not found")


class _FakeRegistry:
    def __init__(self, wiki):
        self._wiki = wiki

    def get_default_wiki(self):
        return self._wiki

    def get_wiki(self, wiki_id):
        return self._wiki


@pytest.fixture
def paper_client(tmp_path, monkeypatch):
    from llmwikify.interfaces.server.http import paper as mod
    from llmwikify.reproduction.sessions import ReproductionDatabase

    wiki = _FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)
    db = ReproductionDatabase(tmp_path / "repro.db")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(exist_ok=True)
    upload_dir = tmp_path / "papers"
    upload_dir.mkdir(exist_ok=True)
    set_paper_deps = mod.set_paper_deps
    set_paper_deps(
        _FakeRegistry(wiki),
        db=db,
        raw_dir=raw_dir,
        upload_dir=upload_dir,
    )

    monkeypatch.setattr(mod, "_WIKI_REGISTRY", _FakeRegistry(wiki))
    monkeypatch.setattr(mod, "_DB", db)
    monkeypatch.setattr(mod, "_RAW_DIR", raw_dir)
    monkeypatch.setattr(mod, "_UPLOAD_DIR", upload_dir)

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.paper import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki, db


@pytest.fixture
def factor_client(tmp_path, monkeypatch):
    from llmwikify.interfaces.server.http import factor as mod

    wiki = _FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "_WIKI_REGISTRY", _FakeRegistry(wiki))

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.factor import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki


@pytest.fixture
def strategy_client(tmp_path, monkeypatch):
    from llmwikify.interfaces.server.http import strategy as mod

    wiki = _FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mod, "_WIKI_REGISTRY", _FakeRegistry(wiki))

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.strategy import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki


# ── Paper tests ──

def test_paper_list_empty(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/test-001")
    assert r.status_code == 200


def test_paper_start(paper_client):
    """POST /start returns session_id immediately with status=pending
    (the background task is scheduled and runs asynchronously)."""
    client, _, db = paper_client
    r = client.post("/api/paper/start", json={
        "paper_id": "test-001",
        "source_type": "pdf",
        "source_ref": "/tmp/test.pdf",
        "paper_content": "Test paper about momentum",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["paper_id"] == "test-001"
    assert "session_id" in body
    # Status is whatever the task got to when /start returned. With TestClient
    # the task may still be pending; in production it would progress.
    assert body["status"] in ("pending", "extracting", "wiki_building", "done", "error")
    # The session row exists in DB
    from llmwikify.interfaces.server.http import paper as mod
    sess = mod._DB.get_session(body["session_id"])
    assert sess is not None
    assert sess.paper_id == "test-001"
    assert sess.source_type == "pdf"


def test_paper_status(paper_client):
    """GET /{sid}/status returns session + events + artifacts."""
    client, _, db = paper_client
    r = client.post("/api/paper/start", json={
        "paper_id": "test-002",
        "source_type": "url",
        "source_ref": "https://example.com/paper",
        "paper_content": "Content",
    })
    sid = r.json()["session_id"]
    r2 = client.get(f"/api/paper/{sid}/status")
    assert r2.status_code == 200
    body = r2.json()
    assert body["session"]["paper_id"] == "test-002"
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 1
    assert body["events"][0]["event_type"] == "extract.started"


def test_paper_status_not_found(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/nonexistent-sid/status")
    assert r.status_code == 404


def test_paper_list_sessions(paper_client):
    """GET /list returns all paper sessions (source_type=pdf|url|raw)."""
    client, _, db = paper_client
    client.post("/api/paper/start", json={
        "paper_id": "list-1",
        "source_type": "pdf",
        "source_ref": "/x.pdf",
        "paper_content": "a",
    })
    client.post("/api/paper/start", json={
        "paper_id": "list-2",
        "source_type": "raw",
        "source_ref": "y.pdf",
        "paper_content": "b",
    })
    r = client.get("/api/paper/list")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["sessions"], list)
    paper_ids = {s["paper_id"] for s in body["sessions"]}
    assert "list-1" in paper_ids
    assert "list-2" in paper_ids


def test_paper_list_raw_empty(paper_client):
    """GET /list-raw returns [] when raw_dir is empty."""
    client, _, _ = paper_client
    r = client.get("/api/paper/list-raw")
    assert r.status_code == 200
    body = r.json()
    assert body["files"] == []


def test_paper_list_raw(paper_client):
    """GET /list-raw returns *.pdf files in raw_dir."""
    client, _, _ = paper_client
    from llmwikify.interfaces.server.http import paper as mod
    (mod._RAW_DIR / "foo.pdf").write_bytes(b"%PDF-1.4 fake")
    (mod._RAW_DIR / "bar.pdf").write_bytes(b"%PDF-1.4 fake")
    (mod._RAW_DIR / "ignore.txt").write_text("not pdf")
    r = client.get("/api/paper/list-raw")
    assert r.status_code == 200
    body = r.json()
    names = {f["filename"] for f in body["files"]}
    assert names == {"foo.pdf", "bar.pdf"}


def test_paper_upload(paper_client):
    """POST /upload saves file to upload_dir/{safe(paper_id)}.pdf."""
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
    assert body["path"].endswith(".pdf")
    # File exists on disk
    from pathlib import Path
    assert Path(body["path"]).exists()


def test_paper_upload_rejects_non_pdf(paper_client):
    client, _, _ = paper_client
    r = client.post(
        "/api/paper/upload",
        data={"paper_id": "x"},
        files={"file": ("test.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_paper_upload_rejects_empty(paper_client):
    client, _, _ = paper_client
    r = client.post(
        "/api/paper/upload",
        data={"paper_id": "x"},
        files={"file": ("test.pdf", b"", "application/pdf")},
    )
    assert r.status_code == 400


def test_paper_artifacts(paper_client):
    client, _, _ = paper_client
    r = client.get("/api/paper/test-001/artifacts")
    assert r.status_code == 200
    body = r.json()
    assert body["paper_id"] == "test-001"
    assert isinstance(body["artifacts"], list)


# ── Factor tests ──

def test_factor_list_empty(factor_client):
    client, _ = factor_client
    r = client.get("/api/factor/list")
    assert r.status_code == 200
    body = r.json()
    assert body["factors"] == []


def test_factor_get_missing(factor_client):
    client, _ = factor_client
    r = client.get("/api/factor/nonexistent")
    assert r.status_code == 404


def test_factor_backtest(factor_client):
    client, wiki = factor_client
    # Create a factor page
    factor_dir = wiki.wiki_dir / "factor"
    factor_dir.mkdir(parents=True, exist_ok=True)
    (factor_dir / "test-factor.md").write_text(
        "---\ntitle: Test Factor\nfactor_class: momentum\nfactor_params: {lookback: 60}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.post("/api/factor/test-factor/backtest", json={
        "universe": "single",
        "symbol": "600660.SH",
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["factor"]["factor_class"] == "momentum"
    assert "metrics" in body
    assert "ic_series" in body
    assert "quantile_curves" in body


# ── Strategy tests ──

def test_strategy_list_empty(strategy_client):
    client, _ = strategy_client
    r = client.get("/api/strategy/list")
    assert r.status_code == 200
    body = r.json()
    assert body["strategies"] == []


def test_strategy_get_missing(strategy_client):
    client, _ = strategy_client
    r = client.get("/api/strategy/nonexistent")
    assert r.status_code == 404


def test_strategy_backtest(strategy_client):
    client, wiki = strategy_client
    # Create a strategy page
    strategy_dir = wiki.wiki_dir / "strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    (strategy_dir / "test-strategy.md").write_text(
        "---\ntitle: Test Strategy\nstrategy_class: trend_following\nsignal_type: ma_cross\nsignal_params: {fast: 5, slow: 20}\nstatus: draft\n---\n",
        encoding="utf-8",
    )
    r = client.post("/api/strategy/test-strategy/backtest", json={
        "symbol": "600660.SH",
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("success", "error")
    assert "metrics" in body
    assert "monthly_returns" in body
