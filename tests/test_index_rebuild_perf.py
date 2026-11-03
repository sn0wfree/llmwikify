"""Tests for the index.md rebuild optimisation (batch queries + summary cache).

The index rebuild used to run three SQL queries and one file read per
page. On a 1400-page wiki that dominated every ``write_page`` call.
These tests pin the behaviour that matters: the produced index must be
identical to the per-page version, and the cache must not go stale.
"""

from __future__ import annotations

import shutil
import tempfile
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


def _seed(wiki, count: int) -> None:
    """Write pages straight to disk — write_page would rebuild the index."""
    concepts = wiki.root / "wiki" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (concepts / f"Page {i}.md").write_text(
            f"# Page {i}\n\n## Summary\n\nSummary for page {i}.\n\n" + ("x" * 2000),
            encoding="utf-8",
        )
    wiki.build_index()


# ── batch query helpers ────────────────────────────────────────────


def test_batch_count_helpers_match_per_page_counts(wiki_root: Path):
    """The batch helpers must agree with the per-page queries."""
    wiki = _wiki(wiki_root)
    _seed(wiki, 5)
    wiki.write_page("concepts/Alpha", "# Alpha\n\nSee [[Page 1]].\n")
    wiki.write_page("concepts/Beta", "# Beta\n\nSee [[Alpha]].\n")

    names = [wiki._page_display_name(p) for p in wiki._wiki_pages()]

    inbound_all = wiki.index.count_inbound_all()
    outbound_all = wiki.index.count_outbound_all()
    words_all = wiki.index.word_counts_all()

    for name in names:
        assert inbound_all.get(name, 0) == len(wiki.index.get_inbound_links(name))
        assert outbound_all.get(name, 0) == len(wiki.index.get_outbound_links(name))

    row = wiki.index.conn.execute(
        "SELECT word_count FROM pages WHERE page_name = ?", ("concepts/Alpha",)
    ).fetchone()
    assert words_all.get("concepts/Alpha") == row["word_count"]


def test_batch_count_helpers_are_parameterless(wiki_root: Path):
    """They take no page list, so no SQLite variable limit applies."""
    import inspect

    from llmwikify.kernel.storage.index import WikiIndex

    for name in ("count_inbound_all", "count_outbound_all", "word_counts_all"):
        sig = inspect.signature(getattr(WikiIndex, name))
        assert list(sig.parameters) == ["self"], f"{name} should take no arguments"


# ── summary cache ───────────────────────────────────────────────────


def test_summary_cache_recomputes_only_changed_pages(wiki_root: Path):
    """Changing one page must not invalidate every other page's summary."""
    wiki = _wiki(wiki_root)
    _seed(wiki, 3)

    wiki._update_index_file()
    cache = wiki.__dict__["_summary_cache"]
    assert len(cache) == 3

    page = wiki.root / "wiki" / "concepts" / "Page 1.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "Summary for page 1.", "A brand new summary."
        ),
        encoding="utf-8",
    )

    wiki._update_index_file()
    assert cache["concepts/Page 1"][2] == "A brand new summary."
    assert cache["concepts/Page 0"][2] == "Summary for page 0."


def test_summary_cache_is_per_instance(wiki_root: Path, tmp_path: Path):
    """Two wikis must not share summaries."""
    other_root = tmp_path / "other"
    (other_root / "raw").mkdir(parents=True)
    (other_root / "wiki").mkdir(parents=True)

    first = _wiki(wiki_root)
    _seed(first, 2)
    first._update_index_file()

    second = _wiki(other_root)
    _seed(second, 2)
    second._update_index_file()

    assert "_summary_cache" not in second.__dict__ or (
        second.__dict__["_summary_cache"] != first.__dict__["_summary_cache"]
    )


def test_index_content_matches_per_page_computation(wiki_root: Path):
    """The optimised rebuild must produce the same index as the old one."""
    wiki = _wiki(wiki_root)
    wiki.write_page("concepts/Alpha", "# Alpha\n\n## Summary\n\nFirst.\n")
    wiki.write_page("concepts/Beta", "# Beta\n\n## Summary\n\nSecond.\n")
    wiki.write_page("entities/Gamma", "# Gamma\n\n## Summary\n\nThird.\n")
    wiki.write_page("sources/Delta", "# Delta\n\n## Summary\n\nFourth.\n")
    wiki.write_page("concepts/Epsilon", "# Epsilon\n\nSee [[Alpha]] and [[Beta]].\n")

    legacy = _legacy_index_content(wiki)
    wiki._update_index_file()
    optimized = (wiki.root / "wiki" / "index.md").read_text(encoding="utf-8")

    assert _strip_ts(legacy) == _strip_ts(optimized)


def _strip_ts(text: str) -> str:
    import re

    return re.sub(r"Last updated: .*", "Last updated: <ts>", text)


def _legacy_index_content(wiki) -> str:
    """Per-page version of the index, as it was before the optimisation."""
    dir_labels = {
        "sources": "Sources",
        "concepts": "Concepts",
        "entities": "Entities",
        "comparisons": "Comparisons",
        "synthesis": "Synthesis",
        "claims": "Claims",
    }
    groups: dict[str, list[str]] = {}
    type_counts: dict[str, int] = {}

    for page in sorted(wiki._backend.list_page_paths()):
        page_path = page.relative_to(wiki.wiki_dir)
        if page_path.parts[0] == ".sink":
            continue
        if page.name in ("index.md", "log.md"):
            continue
        page_name = str(page_path.with_suffix(""))
        subdir = page_path.parts[0] if len(page_path.parts) > 1 else ""
        label = (
            dir_labels.get(subdir, subdir.capitalize())
            if len(page_path.parts) > 1
            else "Overview"
        )
        groups.setdefault(label, [])
        type_counts[label] = type_counts.get(label, 0) + 1

        summary = wiki._extract_page_summary(page)
        stats_extra = ""
        row = wiki.index.conn.execute(
            "SELECT word_count FROM pages WHERE page_name = ?", (page_name,)
        ).fetchone()
        if row and row["word_count"]:
            wc = row["word_count"]
            wc_str = f"{wc / 1000:.1f}k" if wc >= 1000 else str(wc)
            stats_extra = f" | 📝 {wc_str} words"
        in_count = len(wiki.index.get_inbound_links(page_name))
        out_count = len(wiki.index.get_outbound_links(page_name))
        if in_count > 0 or out_count > 0:
            link_str = f"🔗 {out_count} out"
            if in_count > 0:
                link_str += f" | {in_count} in"
            stats_extra = f" | {link_str}" + stats_extra
        entry = f"- [[{page_name}]] - {summary}"
        if stats_extra:
            entry += f"\n  {stats_extra}".lstrip()
        groups[label].append(entry)

    total = sum(type_counts.values())
    type_summary = " | ".join(
        f"{label}: {count}" for label, count in type_counts.items() if count > 0
    )
    out = (
        f"# Wiki Index\n\n"
        f"Last updated: {wiki._now()}\n\n"
        f"Total pages: {total}"
        + (f" — {type_summary}" if type_summary else "")
        + "\n\n---\n\n"
    )
    section_order = [
        "Sources",
        "Concepts",
        "Entities",
        "Comparisons",
        "Synthesis",
        "Claims",
        "Overview",
    ]
    remaining = [k for k in groups if k not in section_order]
    for label in section_order + sorted(remaining):
        if label not in groups or not groups[label]:
            continue
        out += f"## {label} ({len(groups[label])})\n\n"
        out += "\n\n".join(groups[label]) + "\n\n"
    return out


# ── performance guard ───────────────────────────────────────────────


def test_rebuild_stays_fast_on_a_large_wiki(wiki_root: Path):
    """Guard the optimisation: a 600-page wiki must rebuild in well under
    the time the per-page version needed."""
    import time

    wiki = _wiki(wiki_root)
    _seed(wiki, 600)

    t0 = time.monotonic()
    wiki._update_index_file()
    cold = time.monotonic() - t0

    t0 = time.monotonic()
    wiki._update_index_file()
    warm = time.monotonic() - t0

    assert cold < 2.0, f"cold rebuild took {cold:.2f}s"
    assert warm < 1.0, f"warm rebuild took {warm:.2f}s"
    assert warm <= cold + 0.05, "the summary cache did not help"
