"""Shared fixtures for paper/factor/strategy/reproduction API tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

fastapi = pytest.importorskip("fastapi")


# ── Shared Mocks ──────────────────────────────────────────────


class FakeWiki:
    """In-memory wiki mock for API tests."""

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

    def list_pages(self):
        return list(self._pages.keys())

    def search(self, query, limit=10):
        return []


class FakeRegistry:
    """In-memory wiki registry mock."""

    def __init__(self, wiki: FakeWiki):
        self._wiki = wiki

    def get_default_wiki(self):
        return self._wiki

    def get_wiki(self, wiki_id):
        return self._wiki

    def get_default_wiki_id(self):
        return "test-wiki"


class FakeLLMClient:
    """Fake LLM client that returns pre-configured JSON."""

    def __init__(self, response: str = ""):
        self._response = response

    def chat(self, messages, **kwargs):
        return self._response


# ── Paper Fixtures ────────────────────────────────────────────


@pytest.fixture
def paper_client(tmp_path, monkeypatch):
    """Paper router with isolated DB, wiki, raw/upload dirs."""
    from llmwikify.interfaces.server.http import paper as mod
    from llmwikify.reproduction.persist.sessions import ReproductionDatabase

    wiki = FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)
    db = ReproductionDatabase(tmp_path / "repro.db")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(exist_ok=True)
    upload_dir = tmp_path / "papers"
    upload_dir.mkdir(exist_ok=True)

    mod.set_paper_deps(FakeRegistry(wiki), db=db, raw_dir=raw_dir, upload_dir=upload_dir)
    monkeypatch.setattr(mod, "_WIKI_REGISTRY", FakeRegistry(wiki))
    monkeypatch.setattr(mod, "_DB", db)
    monkeypatch.setattr(mod, "_RAW_DIR", raw_dir)
    monkeypatch.setattr(mod, "_UPLOAD_DIR", upload_dir)

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.paper import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki, db


# ── Reproduction Fixtures ────────────────────────────────────


@pytest.fixture
def repro_client(tmp_path, monkeypatch):
    """Reproduction router with isolated DB and wiki."""
    from llmwikify.interfaces.server.http import reproduction as mod
    from llmwikify.reproduction.persist.sessions import ReproductionDatabase

    db = ReproductionDatabase(db_path=tmp_path / "r.db")
    wiki = FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)

    mod.set_repro_deps(db, FakeRegistry(wiki))
    monkeypatch.setattr(mod, "_REPRO_DB", db)
    monkeypatch.setattr(mod, "_WIKI_REGISTRY", FakeRegistry(wiki))

    # Mock DataRouter so we don't hit real data sources
    monkeypatch.setattr(
        "llmwikify.reproduction.data_source.router.SynthDataSource.get",
        lambda self, s, st, e: (pd.DataFrame({"close": [10.0] * 60}), "synth"),
    )

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.reproduction import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki, db


# ── Factor Fixtures ───────────────────────────────────────────


@pytest.fixture
def factor_client(tmp_path, monkeypatch):
    """Factor router with isolated wiki."""
    from llmwikify.interfaces.server.http import factor as mod

    wiki = FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)

    mod.set_factor_deps(FakeRegistry(wiki))
    monkeypatch.setattr(mod, "_WIKI_REGISTRY", FakeRegistry(wiki))

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.factor import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki


# ── Strategy Fixtures ─────────────────────────────────────────


@pytest.fixture
def strategy_client(tmp_path, monkeypatch):
    """Strategy router with isolated wiki."""
    from llmwikify.interfaces.server.http import strategy as mod

    wiki = FakeWiki(tmp_path / "wiki")
    wiki.wiki_dir.mkdir(parents=True, exist_ok=True)

    mod.set_strategy_deps(FakeRegistry(wiki))
    monkeypatch.setattr(mod, "_WIKI_REGISTRY", FakeRegistry(wiki))

    from fastapi import FastAPI
    from llmwikify.interfaces.server.http.strategy import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    yield TestClient(app), wiki


# ── Pytest collection ignore ────────────────────────────────────
#
# test_e2e_paper.py is a script (``python tests/reproduction/test_e2e_paper.py``)
# that starts its own server. Pytest collecting it produces 8 errors.
# Exclude it from collection.

collect_ignore = ["test_e2e_paper.py"]
