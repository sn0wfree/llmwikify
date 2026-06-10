"""Tests for reproduction.router — data-source fallback chain."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llmwikify.reproduction.router import (
    AKShareDataSource,
    CachedClickHouseDataSource,
    ClickHouseDataSource,
    DataRouter,
    SynthDataSource,
)


class _FakeSource:
    """Programmable data source for fallback tests."""

    def __init__(self, name: str, df: pd.DataFrame | None, raises: bool = False):
        self.name = name
        self._df = df
        self._raises = raises
        self.calls = 0

    def get(self, symbol, start, end):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return self._df


def test_synth_returns_60_rows_with_ohlcv_schema():
    src = SynthDataSource(n_days=60, base_price=10.0)
    df = src.get("ANY", "2024-01-01", "2024-03-01")
    assert df is not None
    assert len(df) == 60
    assert set(["date", "open", "high", "low", "close", "volume"]).issubset(df.columns)


def test_synth_is_deterministic_per_symbol():
    src = SynthDataSource()
    a = src.get("AAA", "2024-01-01", "2024-02-28")
    b = src.get("AAA", "2024-01-01", "2024-02-28")
    assert a["close"].tolist() == b["close"].tolist()


def test_synth_differs_across_symbols():
    src = SynthDataSource()
    a = src.get("AAA", "2024-01-01", "2024-02-28")
    b = src.get("BBB", "2024-01-01", "2024-02-28")
    assert a["close"].tolist() != b["close"].tolist()


def test_akshare_returns_none_when_remote_disconnected(monkeypatch):
    """akshare is best-effort: any network failure must be swallowed."""
    import llmwikify.reproduction.router as r

    def boom(*a, **kw):
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(r, "ak", None, raising=False)
    monkeypatch.setattr("builtins.__import__", lambda name, *a, **kw: boom(name) if name == "akshare" else __import__(name, *a, **kw))
    src = AKShareDataSource()
    assert src.get("600660.SH", "2024-01-01", "2024-02-28") is None


def test_router_returns_first_non_none_source():
    df = pd.DataFrame({"close": [1, 2, 3]})
    a = _FakeSource("a", None)
    b = _FakeSource("b", df)
    c = _FakeSource("c", None)
    router = DataRouter(sources=[a, b, c])
    out, src_name = router.get("X", "2024-01-01", "2024-02-28")
    assert src_name == "b"
    assert out is df
    assert a.calls == 1
    assert b.calls == 1
    assert c.calls == 0


def test_router_skips_failing_source():
    df = pd.DataFrame({"close": [1]})
    a = _FakeSource("a", None, raises=True)
    b = _FakeSource("b", df)
    router = DataRouter(sources=[a, b])
    out, src_name = router.get("X", "2024-01-01", "2024-02-28")
    assert src_name == "b"


def test_router_skips_empty_dataframe():
    df = pd.DataFrame()
    b = _FakeSource("b", df)
    c = _FakeSource("c", pd.DataFrame({"close": [1]}))
    router = DataRouter(sources=[b, c])
    _, src_name = router.get("X", "2024-01-01", "2024-02-28")
    assert src_name == "c"


def test_router_falls_back_to_synth_when_all_fail():
    a = _FakeSource("a", None, raises=True)
    b = _FakeSource("b", None)
    router = DataRouter(sources=[a, b, SynthDataSource()])
    df, src_name = router.get("X", "2024-01-01", "2024-02-28")
    assert src_name == "synth"
    assert len(df) == 60


def test_default_chain_includes_cache_and_synth(monkeypatch):
    monkeypatch.setattr(DataRouter, "DEFAULT_CH_PASSWORD", "")
    router = DataRouter(use_cache=True)
    names = [s.name for s in router._sources]
    assert "cache+clickhouse" in names
    assert "synth" in names
    assert names[-1] == "synth"


def test_no_cache_chain_omits_cache_layer():
    router = DataRouter(use_cache=False, clickhouse_passwd="x")
    names = [s.name for s in router._sources]
    assert "cache+clickhouse" not in names
    assert names[-1] == "synth"


@pytest.mark.parametrize("src_cls", [ClickHouseDataSource, CachedClickHouseDataSource])
def test_clickhouse_handles_invalid_symbol_without_raising(src_cls):
    """Failed queries must return None, not raise — router depends on this."""
    if src_cls is CachedClickHouseDataSource:
        src = src_cls(ClickHouseDataSource(passwd="definitely-wrong"))
    else:
        src = src_cls(passwd="definitely-wrong")
    df = src.get("INVALID.SYMBOL", "2099-01-01", "2099-01-31")
    assert df is None or df.empty