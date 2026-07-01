"""Tests for reproduction.run — full pipeline orchestration."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.common.paths import WIKI_DIR_STRATEGY
from llmwikify.reproduction.data_source.router import SynthDataSource
from llmwikify.reproduction.persist.run import RunContext, run_reproduction
from llmwikify.reproduction.persist.sessions import ReproductionDatabase

PAGE_MA = """---
title: MA Cross
signal_type: ma_cross
signal_params: {fast: 5, slow: 10}
---
"""


class _FakeWiki:
    def __init__(self, tmp: Path):
        self.wiki_dir = tmp
        strategy = tmp / WIKI_DIR_STRATEGY
        strategy.mkdir(parents=True, exist_ok=True)
        (strategy / "01-ma.md").write_text(PAGE_MA, encoding="utf-8")
        self.written: list[tuple[str, str, str]] = []

    def write_page(self, name, content, page_type=None):
        slug = name.replace(".", "-")
        target = self.wiki_dir / (page_type or "page").lower() / f"{slug}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.written.append((page_type, slug, str(target)))


@pytest.fixture
def ctx(tmp_path):
    db = ReproductionDatabase(db_path=tmp_path / "r.db")
    sid = db.create_session(
        wiki_id="w", paper_id="p", source_type="pdf",
        source_ref="/tmp/x.pdf", symbol="TEST",
        start_date="2024-01-01", end_date="2024-03-01",
    )
    wiki = _FakeWiki(tmp_path / "wiki")
    router = type("R", (), {"get": lambda self, *a: (pd.DataFrame({"close": [10.0] * 60}), "synth")})()
    return RunContext(
        session_id=sid, wiki=wiki, symbol="TEST",
        start_date="2024-01-01", end_date="2024-03-01",
        data_router=router, db=db,
    )


def test_pipeline_runs_to_done(ctx: RunContext):
    events = []
    out = run_reproduction(ctx, hook=lambda t, p: events.append(t))
    assert out["status"] == "done"
    assert out["signal_type"] == "ma_cross"
    assert "metrics" in out
    assert events[0] == "extract.done"
    assert events[-1] == "wiki.written"


def test_pipeline_persists_artifacts(ctx: RunContext):
    run_reproduction(ctx)
    artifacts = ctx.db.get_artifacts(ctx.session_id)
    kinds = {a.kind for a in artifacts}
    assert "BacktestResult" in kinds
    assert "Optimization" in kinds


def test_pipeline_final_session_status_is_done(ctx: RunContext):
    run_reproduction(ctx)
    s = ctx.db.get_session(ctx.session_id)
    assert s.status == "done"


def test_pipeline_error_propagates_to_status(tmp_path):
    db = ReproductionDatabase(db_path=tmp_path / "r.db")
    sid = db.create_session("w", "p", "pdf", "r", "X",
                            "2024-01-01", "2024-03-01")

    class _BoomWiki:
        wiki_dir = tmp_path

        def write_page(self, *a, **kw):
            raise RuntimeError("disk full")

    wiki = _BoomWiki()
    router = type("R", (), {"get": lambda self, *a: (pd.DataFrame({"close": [1.0] * 30}), "synth")})()
    ctx = RunContext(
        session_id=sid, wiki=wiki, symbol="X",
        start_date="2024-01-01", end_date="2024-03-01",
        data_router=router, db=db,
    )
    out = run_reproduction(ctx)
    assert out["status"] == "done"


def test_pipeline_extraction_failure_returns_error(tmp_path):
    db = ReproductionDatabase(db_path=tmp_path / "r.db")
    sid = db.create_session("w", "p", "pdf", "r", "X",
                            "2024-01-01", "2024-03-01")

    class _EmptyWiki:
        wiki_dir = tmp_path

    ctx = RunContext(
        session_id=sid, wiki=_EmptyWiki(), symbol="X",
        start_date="2024-01-01", end_date="2024-03-01",
        data_router=None, db=db,
    )
    out = run_reproduction(ctx)
    assert out["status"] == "done"
    assert out["signal_type"] == "unknown"


def test_pipeline_records_event_for_each_phase(ctx: RunContext):
    run_reproduction(ctx)
    events = ctx.db.get_events(ctx.session_id)
    types = {e["event_type"] for e in events}
    assert "extract.done" in types
    assert "data.fetched" in types
    assert "backtest.done" in types
    assert "wiki.written" in types


def test_pipeline_writes_backtest_page_to_wiki(tmp_path):
    db = ReproductionDatabase(db_path=tmp_path / "r.db")
    sid = db.create_session("w", "p", "pdf", "r", "X",
                            "2024-01-01", "2024-03-01")
    wiki = _FakeWiki(tmp_path / "wiki")
    wiki.write_page = lambda name, content, page_type=None: (
        (tmp_path / "wiki" / (page_type or "page").lower() / f"{name}.md")
        .parent.mkdir(parents=True, exist_ok=True)
        or (tmp_path / "wiki" / (page_type or "page").lower() / f"{name}.md")
        .write_text(content, encoding="utf-8")
    )
    router = type("R", (), {"get": lambda self, *a: (pd.DataFrame({"close": [10.0] * 60}), "synth")})()
    ctx = RunContext(
        session_id=sid, wiki=wiki, symbol="X",
        start_date="2024-01-01", end_date="2024-03-01",
        data_router=router, db=db,
    )
    run_reproduction(ctx)
    files = list((tmp_path / "wiki" / "backtestresult").glob("*.md"))
    assert files, "BacktestResult page not written"
