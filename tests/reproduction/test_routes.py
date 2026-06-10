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

    wiki = _FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)
    set_paper_deps = mod.set_paper_deps
    set_paper_deps(_FakeRegistry(wiki))

    monkeypatch.setattr(mod, "_WIKI_REGISTRY", _FakeRegistry(wiki))

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.paper import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki


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
    client, _ = paper_client
    r = client.get("/api/paper/test-001")
    assert r.status_code == 200


def test_paper_start(paper_client):
    client, wiki = paper_client
    r = client.post("/api/paper/start", json={
        "paper_id": "test-001",
        "source_type": "pdf",
        "source_ref": "/tmp/test.pdf",
        "paper_content": "Test paper about momentum",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["paper_id"] == "test-001"
    assert body["status"] == "done"


def test_paper_artifacts(paper_client):
    client, wiki = paper_client
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
