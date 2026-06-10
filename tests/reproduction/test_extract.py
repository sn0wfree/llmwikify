"""Tests for reproduction.extract — frontmatter parsing + wiki extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from llmwikify.reproduction.extract import (
    VALID_SIGNAL_TYPES,
    extract_from_page,
    extract_strategy_config,
    _parse_frontmatter,
)


PAGE_MA_CROSS = """---
title: MA Crossover Strategy
signal_type: ma_cross
signal_params: {fast: 5, slow: 20}
---

# MA Crossover

Buy when fast MA crosses above slow MA.
"""

PAGE_RSI = """---
title: RSI Reversal
signal_type: rsi
signal_params: {period: 14, overbought: 70, oversold: 30}
---
"""

PAGE_UNKNOWN = """---
title: Novel factor
signal_type: factor_rank
signal_params: {lookback: 60, top_n: 10}
---
"""

PAGE_BOGUS = """---
title: Garbage
signal_type: nonsense
---
"""


class _FakeWiki:
    def __init__(self, tmp: Path, pages: dict[str, str]):
        self.wiki_dir = tmp
        trading = tmp / "trading"
        trading.mkdir(parents=True, exist_ok=True)
        for slug, content in pages.items():
            (trading / f"{slug}.md").write_text(content, encoding="utf-8")


def test_parse_frontmatter_extracts_scalar():
    fm = _parse_frontmatter("---\nfoo: bar\nbaz: 42\n---\nbody")
    assert fm == {"foo": "bar", "baz": "42"}


def test_parse_frontmatter_extracts_list():
    fm = _parse_frontmatter("---\ntags: [a, b, c]\n---\nbody")
    assert fm["tags"] == ["a", "b", "c"]


def test_parse_frontmatter_extracts_dict():
    fm = _parse_frontmatter("---\nsignal_params: {fast: 5, slow: 20}\n---\nbody")
    assert fm["signal_params"] == {"fast": "5", "slow": "20"}


def test_parse_frontmatter_handles_missing():
    assert _parse_frontmatter("no frontmatter here") == {}


def test_extract_ma_cross():
    cfg = extract_from_page(PAGE_MA_CROSS)
    assert cfg["signal_type"] == "ma_cross"
    assert cfg["signal_params"] == {"fast": 5, "slow": 20}


def test_extract_rsi_ints_and_floats():
    cfg = extract_from_page(PAGE_RSI)
    assert cfg["signal_type"] == "rsi"
    assert cfg["signal_params"]["period"] == 14
    assert cfg["signal_params"]["overbought"] == 70
    assert cfg["signal_params"]["oversold"] == 30


def test_extract_unknown_signal_type_falls_back():
    cfg = extract_from_page(PAGE_BOGUS)
    assert cfg["signal_type"] == "unknown"


def test_extract_no_frontmatter_returns_none():
    assert extract_from_page("just body text") is None


def test_extract_no_signal_type_returns_none():
    page = "---\ntitle: nope\n---\nbody"
    assert extract_from_page(page) is None


def test_valid_signal_types_includes_all_six():
    assert {"ma_cross", "rsi", "factor_rank", "volatility", "momentum", "signal_composite", "unknown"} == VALID_SIGNAL_TYPES


def test_extract_strategy_config_from_wiki(tmp_path):
    wiki = _FakeWiki(tmp_path, {"01-ma-cross": PAGE_MA_CROSS})
    cfg = extract_strategy_config(wiki)
    assert cfg["signal_type"] == "ma_cross"
    assert cfg["signal_params"]["fast"] == 5
    assert cfg["wiki_page"] == "trading"


def test_extract_strategy_config_empty_wiki(tmp_path):
    wiki = _FakeWiki(tmp_path, {})
    cfg = extract_strategy_config(wiki)
    assert cfg["signal_type"] == "unknown"
    assert cfg["signal_params"] == {}
    assert cfg["wiki_page"] is None


def test_extract_strategy_config_takes_first_match(tmp_path):
    wiki = _FakeWiki(
        tmp_path,
        {"01-first": PAGE_MA_CROSS, "02-second": PAGE_RSI},
    )
    cfg = extract_strategy_config(wiki)
    assert cfg["signal_type"] == "ma_cross"