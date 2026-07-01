"""Tests for the reproduction REST endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from llmwikify.interfaces.server.http.reproduction import (
    router as repro_router,
)
from llmwikify.interfaces.server.http.reproduction import (
    set_repro_deps,
)
from llmwikify.reproduction.persist.sessions import ReproductionDatabase


class _FakeWiki:
    def __init__(self, tmp: Path):
        self.wiki_dir = tmp
        trading = tmp / "trading"
        trading.mkdir(parents=True, exist_ok=True)
        (trading / "01-ma.md").write_text(
            "---\nsignal_type: ma_cross\nsignal_params: {fast: 5, slow: 10}\n---\n",
            encoding="utf-8",
        )
        self.written: list[tuple[str, str]] = []

    def write_page(self, name, content, page_type=None):
        self.written.append((page_type, name))


class _FakeRegistry:
    def __init__(self, wiki):
        self._wiki = wiki

    def get_default_wiki(self):
        return self._wiki

    def get_wiki(self, wiki_id):
        return self._wiki


class _FakeRouter:
    def get(self, symbol, start, end):
        return pd.DataFrame({"close": [10.0] * 60}), "synth"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from llmwikify.interfaces.server.http import reproduction as mod

    db = ReproductionDatabase(db_path=tmp_path / "r.db")
    wiki = _FakeWiki(tmp_path / "wiki")
    set_repro_deps(db, _FakeRegistry(wiki))

    monkeypatch.setattr(mod, "_REPRO_DB", db)
    monkeypatch.setattr(mod, "_WIKI_REGISTRY", _FakeRegistry(wiki))

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(repro_router)
    monkeypatch.setattr(
        "llmwikify.reproduction.data_source.router.SynthDataSource.get",
        lambda self, s, st, e: pd.DataFrame({"close": [10.0] * 60}),
    )
    yield TestClient(app)


def test_start_returns_session_id(client):
    r = client.post(
        "/api/reproduction/start",
        json={
            "wiki_id": "default",
            "paper_id": "p1",
            "source_type": "pdf",
            "source_ref": "/tmp/x.pdf",
            "symbol": "TEST",
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert body["status"] in {"done", "error"}


def test_start_validates_date_format(client):
    r = client.post(
        "/api/reproduction/start",
        json={
            "wiki_id": "default",
            "paper_id": "p1",
            "source_type": "pdf",
            "source_ref": "/tmp/x.pdf",
            "symbol": "TEST",
            "start_date": "2024/01/01",
            "end_date": "2024-03-01",
        },
    )
    assert r.status_code == 422


def test_get_missing_returns_404(client):
    r = client.get("/api/reproduction/does-not-exist")
    assert r.status_code == 404


def test_get_existing_returns_session(client):
    r = client.post(
        "/api/reproduction/start",
        json={
            "wiki_id": "default",
            "paper_id": "p2",
            "source_type": "pdf",
            "source_ref": "/tmp/y.pdf",
            "symbol": "TEST",
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
        },
    )
    sid = r.json()["session_id"]
    r2 = client.get(f"/api/reproduction/{sid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["session"]["id"] == sid
    assert body["session"]["symbol"] == "TEST"


def test_list_artifacts(client):
    r = client.post(
        "/api/reproduction/start",
        json={
            "wiki_id": "default",
            "paper_id": "p3",
            "source_type": "pdf",
            "source_ref": "/tmp/z.pdf",
            "symbol": "TEST",
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
        },
    )
    sid = r.json()["session_id"]
    r2 = client.get(f"/api/reproduction/{sid}/artifacts")
    assert r2.status_code == 200
    body = r2.json()
    assert body["session_id"] == sid
    kinds = {a["kind"] for a in body["artifacts"]}
    assert "BacktestResult" in kinds
