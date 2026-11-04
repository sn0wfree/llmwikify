"""Tests for the O(N²) traversal fixes and the index build tuning.

Two hot paths walked the whole wiki tree once per link / per entity:
``fix_wikilinks`` (143 s on 1400 pages) and ``add_relations`` (18 s for
60 relations). They now build the lookup once. These tests pin both the
speed-up and — more importantly — that the results did not change.
"""

from __future__ import annotations

import os
import time
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


def _seed_pages(wiki, count: int, links_per_page: int = 4) -> None:
    """Write pages straight to disk (write_page would rebuild the index)."""
    concepts = wiki.root / "wiki" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        links = " ".join(
            f"[[Concept {j}]]" for j in range(i % 5, i % 5 + links_per_page)
        )
        (concepts / f"Page {i}.md").write_text(
            f"# Page {i}\n\n## Summary\n\nSummary {i}.\n\n{links}\n",
            encoding="utf-8",
        )


# ── #1 fix_wikilinks ───────────────────────────────────────────────


def test_stem_index_matches_per_name_rglob(wiki_root: Path):
    """The stem index must return exactly what ``rglob(f"{name}.md")`` would."""
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Foo", "# Foo\n\nx\n")
    wiki.write_page("entities/Foo", "# Foo\n\ny\n")
    wiki.write_page("sources/Bar", "# Bar\n\nz\n")

    index = wiki._page_stem_index()

    for name in ("Foo", "Bar", "Missing"):
        expected = list(wiki.wiki_dir.rglob(f"{name}.md"))
        got = index.get(os.path.normcase(name), [])
        assert sorted(got) == sorted(expected), name


def test_stem_index_uses_platform_case_rules(wiki_root: Path):
    """``rglob`` is case-insensitive on Windows and sensitive on POSIX;
    the index must follow the same rule."""
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Foo", "# Foo\n\nx\n")

    index = wiki._page_stem_index()
    expected = list(wiki.wiki_dir.rglob("foo.md"))
    got = index.get(os.path.normcase("foo"), [])

    assert len(got) == len(expected)
    assert (len(got) == 1) == (len(expected) == 1)


def test_fix_wikilinks_reports_ambiguous_targets(wiki_root: Path):
    """Two pages with the same stem must be reported as ambiguous."""
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Foo", "# Foo\n\nx\n")
    wiki.write_page("entities/Foo", "# Foo\n\ny\n")
    wiki.write_page("sources/Bar", "# Bar\n\nSee [[Foo]] here.\n")

    result = wiki.fix_wikilinks(dry_run=True)

    assert result["ambiguous"] == 1
    assert result["fixed"] == 0
    assert result["changes"][0]["status"] == "ambiguous"


def test_fix_wikilinks_fixes_unique_target(wiki_root: Path):
    """A bare link to a uniquely named page gets its directory prefix."""
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Foo", "# Foo\n\nx\n")
    wiki.write_page("sources/Bar", "# Bar\n\nSee [[Foo]] here.\n")

    result = wiki.fix_wikilinks(dry_run=True)

    assert result["fixed"] == 1
    assert result["changes"][0]["new"] == "[[concepts/Foo]]"


def test_fix_wikilinks_scales(wiki_root: Path):
    """Guard the fix: many pages with many bare links must stay fast."""
    wiki = _wiki(wiki_root)
    _seed_pages(wiki, 400, links_per_page=8)

    t0 = time.monotonic()
    wiki.fix_wikilinks(dry_run=True)
    elapsed = time.monotonic() - t0

    # Before the fix each link walked the tree: this took well over a
    # minute on 400 pages. The budget is generous (the fix takes ~0.3s
    # here) so a slow CI machine does not produce a false failure.
    assert elapsed < 30.0, f"fix_wikilinks took {elapsed:.1f}s"


# ── #2 add_relations ────────────────────────────────────────────────


def _relation_rows(wiki) -> list[tuple]:
    rows = wiki.index.conn.execute(
        "SELECT source, target, relation, confidence FROM relations "
        "ORDER BY source, target"
    ).fetchall()
    return [tuple(r) for r in rows]


def test_add_relations_matches_one_by_one(tmp_path: Path):
    """The batch path must produce exactly what adding one by one does."""
    from llmwikify.kernel.wiki.engines.relation import RelationEngine

    relations = [
        {"source": "Attention", "target": "Softmax", "relation": "uses"},
        {"source": "Attention", "target": "Softmax", "relation": "uses"},
        {"source": "Beta", "target": "Attention", "relation": "uses"},
    ]

    # one-by-one
    root_a = tmp_path / "a"
    (root_a / "raw").mkdir(parents=True)
    (root_a / "wiki").mkdir(parents=True)
    wiki_a = _wiki(root_a)
    engine_a = RelationEngine(wiki_a.index, wiki_root=wiki_a.root)
    for r in relations:
        engine_a.add_relation(
            source=r["source"],
            target=r["target"],
            relation=r["relation"],
        )

    # batch
    root_b = tmp_path / "b"
    (root_b / "raw").mkdir(parents=True)
    (root_b / "wiki").mkdir(parents=True)
    wiki_b = _wiki(root_b)
    engine_b = RelationEngine(wiki_b.index, wiki_root=wiki_b.root)
    engine_b.add_relations(relations)

    assert _relation_rows(wiki_b) == _relation_rows(wiki_a)


def test_resolve_entity_accepts_prefetched_pages(wiki_root: Path):
    """A caller-supplied page list must give the same answer as a fresh walk."""
    from llmwikify.kernel.wiki.engines.relation import RelationEngine

    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Alpha", "# Alpha\n\nx\n")
    engine = RelationEngine(wiki.index, wiki_root=wiki.root)

    fresh = engine.resolve_entity("Alpha")
    prefetched = engine.resolve_entity("Alpha", known_pages=engine._get_wiki_pages())

    assert fresh == prefetched


def test_add_relations_scales(wiki_root: Path):
    """Guard the fix: resolving many relations must not re-walk per entity."""
    from llmwikify.kernel.wiki.engines.relation import RelationEngine

    wiki = _wiki(wiki_root)
    _seed_pages(wiki, 300)
    engine = RelationEngine(wiki.index, wiki_root=wiki.root)

    relations = [
        {"source": f"Entity {i}", "target": f"Entity {i + 1}", "relation": "uses"}
        for i in range(60)
    ]

    t0 = time.monotonic()
    added = engine.add_relations(relations)
    elapsed = time.monotonic() - t0

    assert added == 60
    # Before the fix this took 18 s (each entity walked the tree twice);
    # the fix takes ~0.15 s here, so 10s leaves ample headroom while
    # still catching the quadratic regression.
    assert elapsed < 10.0, f"add_relations took {elapsed:.1f}s"


# ── #3 batch commit ─────────────────────────────────────────────────


def test_upsert_page_can_defer_commit(wiki_root: Path):
    """``commit=False`` must leave the write pending until the caller commits."""
    wiki = _wiki(wiki_root)

    wiki.index.upsert_page("concepts/A", "# A\n\nbody\n", "concepts/A.md", commit=False)
    pending = wiki.index.conn.execute(
        "SELECT COUNT(*) FROM pages WHERE page_name = ?", ("concepts/A",)
    ).fetchone()[0]
    # Same connection sees the pending row (it is not committed yet).
    assert pending == 1

    wiki.index._commit()
    assert wiki.index.get_page_count() == 1


def test_build_index_produces_usable_index(wiki_root: Path):
    """A batched build must leave the index complete and searchable."""
    wiki = _wiki(wiki_root)
    _seed_pages(wiki, 30)

    result = wiki.index.build_index_from_files(wiki.root / "wiki")

    assert result["total_pages"] == 30
    assert wiki.index.get_page_count() == 30
    hits = wiki.search("Page 7", 5)
    assert hits, "search found nothing after a batched build"


# ── #4 PRAGMA ───────────────────────────────────────────────────────


def test_index_connection_uses_wal(wiki_root: Path):
    """The index must not use the slowest journal/sync combination."""
    wiki = _wiki(wiki_root)
    conn = wiki.index.conn

    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

    assert journal.lower() == "wal"
    assert synchronous == 1  # NORMAL
