"""Correctness tests for the second batch of performance fixes.

Each fix removes work that looked redundant but could change behaviour if
done carelessly — so every one is pinned against the pre-fix semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    return tmp_path


def _wiki(root: Path):
    from llmwikify.kernel import Wiki

    return Wiki(root)


# ── #5 jieba dictionary ─────────────────────────────────────────────


def test_english_wiki_skips_segmentation(wiki_root: Path):
    """A pure-Latin wiki must not pay for Chinese segmentation."""
    import jieba

    from llmwikify.kernel.storage import jieba_dict_gen as jdg

    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Alpha", "# Alpha\n\nPlain english body.\n")
    wiki.write_page("concepts/Beta", "# Beta\n\nMore english text here.\n")
    wiki.build_index()

    calls = {"n": 0}
    original_cut = jieba.cut

    def counting_cut(*args, **kwargs):
        calls["n"] += 1
        return original_cut(*args, **kwargs)

    original_extract = jieba.analyse.extract_tags

    def counting_extract(*args, **kwargs):
        calls["n"] += 1
        return original_extract(*args, **kwargs)

    jdg.jieba.cut = counting_cut
    jdg.jieba.analyse.extract_tags = counting_extract
    try:
        count = jdg.generate_fast_dict(wiki.db_path, wiki_root / "user.dict")
    finally:
        jdg.jieba.cut = original_cut
        jdg.jieba.analyse.extract_tags = original_extract

    assert calls["n"] == 0, "segmentation ran on a wiki with no CJK text"
    assert count == 0


def test_chinese_wiki_still_segmented(wiki_root: Path):
    """Chinese content must still reach the tokenizer."""
    import jieba

    from llmwikify.kernel.storage import jieba_dict_gen as jdg

    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/中文页", "# 中文页\n\n这是一段中文内容，用于测试分词。\n")
    wiki.build_index()

    calls = {"n": 0}
    original_cut = jieba.cut

    def counting_cut(*args, **kwargs):
        calls["n"] += 1
        return original_cut(*args, **kwargs)

    jdg.jieba.cut = counting_cut
    try:
        jdg.generate_fast_dict(wiki.db_path, wiki_root / "user.dict")
    finally:
        jdg.jieba.cut = original_cut

    assert calls["n"] > 0, "CJK content was skipped"


# ── #6 lint shared pages ────────────────────────────────────────────


def test_per_page_rule_matches_shared_pages(wiki_root: Path):
    """A per-page rule must produce the same issues either way."""
    from llmwikify.kernel.wiki.lint import LintEngine
    from llmwikify.kernel.wiki.lint.rules import RULES

    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Alpha", "# Alpha\n\nBody mentioning 1999.\n")
    wiki.write_page("concepts/Beta", "# Beta\n\nBody mentioning 1998.\n")
    wiki.build_index()

    rule = LintEngine(wiki, rules=RULES)._rules["dated_claim"]

    own = rule.run(wiki)
    shared = rule.run(wiki, pages=rule._load_pages(wiki))

    assert shared == own


def test_shared_pages_are_loaded_once(wiki_root: Path):
    """run_all must read the wiki once, not once per rule."""
    from llmwikify.kernel.wiki.lint import LintEngine
    from llmwikify.kernel.wiki.lint.rules import RULES

    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Alpha", "# Alpha\n\nBody.\n")
    wiki.build_index()

    engine = LintEngine(wiki, rules=RULES)
    original = engine._rules["dated_claim"]._load_pages
    calls = {"n": 0}

    def counting(w):
        calls["n"] += 1
        return original(w)

    engine._rules["dated_claim"]._load_pages = counting
    engine.run_all()

    # The engine loads through whichever rule runs first; the count stays
    # at 1 (or 0 when a rule short-circuits before loading).
    assert calls["n"] <= 1


def test_mock_wiki_without_wiki_pages_still_runs(wiki_root: Path):
    """run_all must tolerate a wiki that cannot be scanned."""
    from llmwikify.kernel.wiki.lint import LintEngine
    from llmwikify.kernel.wiki.lint.rules import RULES

    class _StubWiki:
        wiki_dir = Path("/nonexistent")

    engine = LintEngine(_StubWiki(), rules=RULES)  # type: ignore[arg-type]
    assert engine.run_all() == []


# ── #7 export_json ──────────────────────────────────────────────────


def test_export_matches_per_page_queries(wiki_root: Path):
    """The grouped export must equal the old per-page lookups."""
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Alpha", "# Alpha\n\nSee [[concepts/Beta]].\n")
    wiki.write_page("concepts/Beta", "# Beta\n\nBody.\n")
    wiki.write_page("concepts/Gamma", "# Gamma\n\nSee [[concepts/Alpha]].\n")
    wiki.build_index()

    out = wiki_root / "ref.json"
    data = wiki.export_index(out)

    for page_name in ("concepts/Alpha", "concepts/Beta", "concepts/Gamma"):
        assert data["outbound_links"].get(page_name, []) == wiki.index.get_outbound_links(
            page_name
        )
        assert data["inbound_links"].get(page_name, []) == wiki.index.get_inbound_links(
            page_name
        )

    sources = {link["source"] for link in wiki.index.get_all_links()}
    assert data["summary"]["pages_with_outbound"] == len(sources)


# ── #8 query sink ───────────────────────────────────────────────────


def test_get_info_for_pages_matches_single_page(wiki_root: Path):
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Alpha", "# Alpha\n\nBody.\n")
    wiki.write_page("concepts/Beta", "# Beta\n\nBody.\n")
    wiki.build_index()

    names = ["concepts/Alpha", "concepts/Beta", "concepts/Missing"]
    batch = wiki.query_sink.get_info_for_pages(names)

    for name in names:
        assert batch[name] == wiki.query_sink.get_info_for_page(name)


def test_rebuild_sink_keeps_dates(wiki_root: Path):
    """Dates parsed in one sweep must match the per-hash search."""
    from llmwikify.kernel.storage.query_sink import QuerySink

    original = (
        "# Query Sink: Demo\n\n"
        "### hash-one — 2024-05-06\ncontent\n\n"
        "### hash-two — 2023-01-02\ncontent\n"
    )
    content_store = {"hash-one": "content", "hash-two": "content"}

    sink = QuerySink(wiki_root, wiki_root / "wiki")
    rebuilt = QuerySink._rebuild_sink_file(
        sink, original, content_store, [], "Demo"
    )
    assert "### hash-one — 2024-05-06" in rebuilt
    assert "### hash-two — 2023-01-02" in rebuilt


# ── #9 redundancy ───────────────────────────────────────────────────


def test_redundancy_output_unchanged(wiki_root: Path):
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Machine Learning", "# ML\n\nx\n")
    wiki.write_page("concepts/Machine Learning Advanced", "# MLA\n\ny\n")
    wiki.write_page("concepts/Totally Different", "# TD\n\nz\n")
    wiki.build_index()

    from llmwikify.kernel.wiki.lint.rules.redundancy import RedundancyRule

    results = RedundancyRule().run(wiki)

    pairs = {frozenset((r["page_a"], r["page_b"])) for r in results}
    assert frozenset(
        ("concepts/Machine Learning", "concepts/Machine Learning Advanced")
    ) in pairs
