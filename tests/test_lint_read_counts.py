"""Counting benchmark for the lint read path (P4-a).

The gate metric is *counts* — directory scans, file reads, call counts —
never wall-clock: this machine's ``wiki/`` holds only 3 pages, so timings
are noise (see design §8).

Benchmark command::

    D:\\tools\\python312\\python.exe -m pytest tests/test_lint_read_counts.py -q -s --rootdir=D:\\Github\\llmwikify

Counters printed by the tests (``-s``):

* ``sources rglob`` — scans of ``wiki/sources/**`` performed while the
  Source summary page of a raw file is being resolved (was: one full
  directory scan per raw file).
* ``sources read``  — ``read_text`` calls on files under ``wiki/sources/``
  inside that same window.
* ``build context`` — ``WikiAnalyzer._build_lint_context()`` invocations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.kernel import Wiki
from llmwikify.kernel.storage.backend import is_path_excluded
from llmwikify.kernel.wiki.engines.analyzer import WikiAnalyzer
from llmwikify.kernel.wiki.mixins.io.source_analysis import WikiSourceAnalysisMixin

# 12 raw files have a slug-named summary page (fast path, 0 reads);
# 8 have none (slow path -> full scan of wiki/sources/).
SLUG_RAWS = 12
NOREF_RAWS = 8
# 12 slug pages + 2 pages that cite a raw file by "(raw/<name>)".
SOURCE_PAGES = SLUG_RAWS + 2


class _Counters:
    """Filesystem counters for the lint read path."""

    def __init__(self) -> None:
        self.sources_dir: Path | None = None
        self.build_context_calls = 0
        self.sources_rglob_calls = 0
        self.sources_read_calls = 0
        self.total_rglob_calls = 0
        self.total_read_calls = 0
        self._depth = 0

    # ── classification helpers ────────────────────────────────────
    def _is_sources_dir(self, path: Path) -> bool:
        """True when ``path`` is (or is inside) the sources directory."""
        if self.sources_dir is None:
            return False
        return path == self.sources_dir or self.sources_dir in path.parents

    def _is_sources_file(self, path: Path) -> bool:
        """True when ``path`` is a file inside the sources directory."""
        if self.sources_dir is None:
            return False
        return self.sources_dir in path.parents

    @property
    def _lookup_active(self) -> bool:
        """True while a Source summary page lookup is running."""
        return self._depth > 0

    def reset(self) -> None:
        self.build_context_calls = 0
        self.sources_rglob_calls = 0
        self.sources_read_calls = 0
        self.total_rglob_calls = 0
        self.total_read_calls = 0

    # ── monkeypatch installation ───────────────────────────────────
    def install_path_counters(self, monkeypatch) -> None:
        """Count ``Path.rglob`` / ``Path.read_text`` calls."""
        counters = self
        orig_rglob = Path.rglob
        orig_read_text = Path.read_text

        def counting_rglob(path, *args, **kwargs):
            counters.total_rglob_calls += 1
            if counters._lookup_active and counters._is_sources_dir(path):
                counters.sources_rglob_calls += 1
            return orig_rglob(path, *args, **kwargs)

        def counting_read_text(path, *args, **kwargs):
            counters.total_read_calls += 1
            if counters._lookup_active and counters._is_sources_file(path):
                counters.sources_read_calls += 1
            return orig_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "rglob", counting_rglob)
        monkeypatch.setattr(Path, "read_text", counting_read_text)

    def install_lookup_window(self, monkeypatch) -> None:
        """Only count filesystem work done *inside* a summary-page lookup."""
        counters = self

        def wrap(orig):
            def wrapper(self, *args, **kwargs):
                counters._depth += 1
                try:
                    return orig(self, *args, **kwargs)
                finally:
                    counters._depth -= 1

            return wrapper

        monkeypatch.setattr(
            WikiSourceAnalysisMixin,
            "_find_source_summary_page",
            wrap(WikiSourceAnalysisMixin._find_source_summary_page),
        )
        if hasattr(WikiSourceAnalysisMixin, "_build_source_summary_map"):
            monkeypatch.setattr(
                WikiSourceAnalysisMixin,
                "_build_source_summary_map",
                wrap(WikiSourceAnalysisMixin._build_source_summary_map),
            )

    def install_context_counter(self, monkeypatch) -> None:
        """Count ``_build_lint_context()`` invocations."""
        counters = self
        orig = WikiAnalyzer._build_lint_context

        def counting(self, *args, **kwargs):
            counters.build_context_calls += 1
            return orig(self, *args, **kwargs)

        monkeypatch.setattr(WikiAnalyzer, "_build_lint_context", counting)

    def install(self, monkeypatch) -> None:
        self.install_path_counters(monkeypatch)
        self.install_lookup_window(monkeypatch)
        self.install_context_counter(monkeypatch)

    def report(self, label: str) -> str:
        return (
            f"[{label}] sources rglob={self.sources_rglob_calls} "
            f"sources read={self.sources_read_calls} "
            f"build context={self.build_context_calls} "
            f"(all rglob={self.total_rglob_calls}, "
            f"all read_text={self.total_read_calls})"
        )


@pytest.fixture
def synthetic_wiki(tmp_path):
    """Wiki with 20 raw files and 14 Source summary pages."""
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()

    sources_dir = root / "wiki" / "sources"
    for i in range(1, SLUG_RAWS + 1):
        (root / "raw" / f"slug-{i:02d}.md").write_text(
            f"# Raw {i}\n\nRaw body {i}.\n", encoding="utf-8"
        )
        # slug fast path: sources/<slug>.md exists
        (sources_dir / f"slug-{i:02d}.md").write_text(
            f"# Source {i}\n\nSummary of raw/slug-{i:02d}.md.\n", encoding="utf-8"
        )
    for i in range(1, NOREF_RAWS + 1):
        # no sources/<slug>.md -> slow path (full scan of the sources dir)
        (root / "raw" / f"noref-{i:02d}.md").write_text(
            f"# Raw {i}\n\nRaw body {i}.\n", encoding="utf-8"
        )
    # two summary pages that cite a raw file by "(raw/<basename>)"
    (sources_dir / "ref-alpha.md").write_text(
        "# Ref Alpha\n\nCites (raw/noref-01.md).\n", encoding="utf-8"
    )
    (sources_dir / "ref-beta.md").write_text(
        "# Ref Beta\n\nCites (raw/noref-02.md).\n", encoding="utf-8"
    )
    (root / "wiki" / "Topic.md").write_text(
        "# Topic\n\nMentions [[Other Topic]].\n", encoding="utf-8"
    )

    yield wiki
    wiki.close()


def _legacy_find_source_summary_page(wiki, source_path):
    """The pre-P4 per-path lookup, kept here as the equivalence oracle.

    Hand-written copy of the algorithm that ``_build_source_summary_map``
    replaced (one full scan of ``wiki/sources/`` per raw file). It is *not*
    a call into the current implementation — it is the "before" side of the
    equivalence check.

    The page read is deliberately lossy (``errors="replace"``), mirroring
    ``source_analysis.py``'s current read, so the oracle and the new
    implementation agree even on source pages that are not valid UTF-8.
    """
    sources_dir = wiki.wiki_dir / "sources"
    if not sources_dir.exists():
        return None

    slug = wiki._slugify(Path(source_path).stem)
    candidate = sources_dir / f"{slug}.md"
    if candidate.exists():
        return candidate

    source_ref = f"(raw/{Path(source_path).name})"
    for page in sources_dir.rglob("*.md"):
        if is_path_excluded(page):
            continue
        content = page.read_text(encoding="utf-8", errors="replace")
        if source_ref in content or source_path in content:
            return page

    return None


def test_source_summary_map_matches_per_path_lookup(synthetic_wiki):
    """The one-pass map resolves every raw file exactly like the old scan."""
    raw_dir = synthetic_wiki.raw_dir
    paths = [f"raw/{p.name}" for p in sorted(raw_dir.iterdir()) if p.is_file()]

    expected = {
        path: _legacy_find_source_summary_page(synthetic_wiki, path) for path in paths
    }
    actual = synthetic_wiki._build_source_summary_map(paths)

    assert list(actual) == paths, "the map keeps the input order"
    assert actual == expected


def test_sources_directory_scanned_at_most_once(synthetic_wiki, monkeypatch):
    """Resolving every raw file must scan ``wiki/sources/`` at most once."""
    counters = _Counters()
    counters.sources_dir = synthetic_wiki.wiki_dir / "sources"
    counters.install(monkeypatch)

    context = synthetic_wiki._analyzer._build_lint_context()

    print("\n" + counters.report("context build"))

    assert counters.build_context_calls == 1
    assert counters.sources_rglob_calls == 1, (
        "wiki/sources must be scanned at most once per context build, got "
        f"{counters.sources_rglob_calls} scans"
    )
    assert counters.sources_read_calls <= SOURCE_PAGES, (
        "context build must not read more source pages than exist: "
        f"{counters.sources_read_calls} reads for {SOURCE_PAGES} pages"
    )
    # the resolved pages are the same ones the per-path lookup found
    assert context.count("[NOT ANALYZED]") == SLUG_RAWS + 2
    assert context.count("[NO SOURCE PAGE]") == NOREF_RAWS - 2


def test_context_markers_unchanged(synthetic_wiki):
    """The context text keeps the same per-raw-file markers."""
    context = synthetic_wiki._analyzer._build_lint_context()

    print(
        "\n[context markers] NOT ANALYZED="
        f"{context.count('[NOT ANALYZED]')} "
        f"NO SOURCE PAGE={context.count('[NO SOURCE PAGE]')}"
    )

    assert "=== SOURCE ANALYSIS (20 total) ===" in context
    # 12 slug hits + 2 content hits -> summary page found, but not analyzed
    assert context.count("[NOT ANALYZED]") == SLUG_RAWS + 2
    # 6 raw files without any summary page
    assert context.count("[NO SOURCE PAGE]") == NOREF_RAWS - 2
    assert "=== UNANALYZED SOURCES (20) ===" in context


def test_context_not_built_when_llm_gaps_cached(synthetic_wiki, monkeypatch):
    """A warm ``lint_llm_gaps`` cache must not rebuild the LLM context."""
    counters = _Counters()
    counters.sources_dir = synthetic_wiki.wiki_dir / "sources"
    counters.install(monkeypatch)
    # Keep the test hermetic: no LLM call, deterministic gaps.
    monkeypatch.setattr(WikiAnalyzer, "_llm_detect_gaps", lambda self, *a, **k: [])

    analyzer = synthetic_wiki._analyzer
    analyzer.lint()  # warm: fills the "lint" and "lint_llm_gaps" caches
    counters.reset()

    result = analyzer.lint()  # both caches hit -> nothing to recompute

    print("\n" + counters.report("cached lint"))

    assert result["cached"] is True, "core cache must hit on the second lint()"
    assert counters.build_context_calls == 0, (
        "the LLM context must not be built when lint_llm_gaps is cached, got "
        f"{counters.build_context_calls} builds"
    )


# ── edge layouts the equivalence oracle must agree on ──────────────


def _edge_wiki(tmp_path, name):
    """Create an initialized wiki whose layout the caller fills in."""
    root = tmp_path / name
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()
    return wiki


def _rel_paths(wiki, files):
    """Rel paths spelled exactly like ``_build_lint_context`` spells them."""
    return [str(f.relative_to(wiki.root)) for f in files]


def _resolve_with_counters(wiki, paths, monkeypatch):
    """Resolve ``paths`` with the new map while counting filesystem work.

    The oracle runs *before* the counters are installed, so the old
    algorithm's own scans and reads do not show up in the counters.
    """
    expected = {p: _legacy_find_source_summary_page(wiki, p) for p in paths}

    counters = _Counters()
    counters.sources_dir = wiki.wiki_dir / "sources"
    counters.install(monkeypatch)

    actual = wiki._build_source_summary_map(paths)
    return actual, expected, counters


def test_nested_raw_subdirs_resolve_like_per_path_lookup(tmp_path, monkeypatch):
    """Raw files nested in subdirectories resolve like the old scan."""
    wiki = _edge_wiki(tmp_path, "nested_root")
    sources_dir = wiki.wiki_dir / "sources"

    raw_files = [
        wiki.raw_dir / "top.md",
        wiki.raw_dir / "nested" / "deep.md",
        wiki.raw_dir / "nested" / "more" / "deeper.md",
    ]
    for path in raw_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n\nRaw body.\n", encoding="utf-8")

    # Only the nested file has a summary page, cited by its basename.
    (sources_dir / "summary-nested.md").write_text(
        "# Summary Nested\n\nCites (raw/deep.md).\n", encoding="utf-8"
    )

    paths = _rel_paths(wiki, raw_files)
    actual, expected, counters = _resolve_with_counters(wiki, paths, monkeypatch)

    assert list(actual) == paths, "the map keeps the input order"
    assert actual == expected, "nested raw paths resolve like the old scan"
    assert expected[paths[1]] is not None, "the nested file has a summary page"

    assert counters.sources_rglob_calls == 1, (
        "wiki/sources must still be scanned once, got "
        f"{counters.sources_rglob_calls} scans"
    )
    assert counters.sources_read_calls <= 1, (
        "the sources dir must be read once per scan, got "
        f"{counters.sources_read_calls} reads"
    )


def test_same_basename_in_different_dirs_resolves_like_per_path_lookup(
    tmp_path, monkeypatch
):
    """Two raw files sharing a basename resolve like the old scan."""
    wiki = _edge_wiki(tmp_path, "dup_root")
    sources_dir = wiki.wiki_dir / "sources"

    raw_files = [wiki.raw_dir / "alpha" / "dup.md", wiki.raw_dir / "beta" / "dup.md"]
    for path in raw_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# dup\n\nRaw body.\n", encoding="utf-8")

    # No wiki/sources/dup.md, so both raw files fall back to the content
    # match, which keys on the basename only.
    (sources_dir / "dup-summary.md").write_text(
        "# Dup Summary\n\nCites (raw/dup.md).\n", encoding="utf-8"
    )

    paths = _rel_paths(wiki, raw_files)
    actual, expected, counters = _resolve_with_counters(wiki, paths, monkeypatch)

    assert list(actual) == paths, "the map keeps the input order"
    assert actual == expected, "same-basename raw files resolve like the old scan"

    assert counters.sources_rglob_calls == 1, (
        "wiki/sources must still be scanned once, got "
        f"{counters.sources_rglob_calls} scans"
    )
    assert counters.sources_read_calls <= 1, (
        "the sources dir must be read once per scan, got "
        f"{counters.sources_read_calls} reads"
    )


def test_excluded_sources_dir_resolves_like_per_path_lookup(tmp_path, monkeypatch):
    """Pages under an excluded directory are skipped, exactly as before."""
    wiki = _edge_wiki(tmp_path, "excluded_root")
    sources_dir = wiki.wiki_dir / "sources"

    raw_files = [wiki.raw_dir / "target.md"]
    for path in raw_files:
        path.write_text("# target\n\nRaw body.\n", encoding="utf-8")

    excluded_page = sources_dir / ".ipynb_checkpoints" / "excluded.md"
    excluded_page.parent.mkdir(parents=True, exist_ok=True)
    excluded_page.write_text("# Excluded\n\nCites (raw/target.md).\n", encoding="utf-8")

    paths = _rel_paths(wiki, raw_files)
    actual, expected, counters = _resolve_with_counters(wiki, paths, monkeypatch)

    assert list(actual) == paths, "the map keeps the input order"
    assert actual == expected, "excluded pages are skipped like the old scan"
    assert expected[paths[0]] is None, "an excluded page is not a summary page"

    assert counters.sources_rglob_calls == 1, (
        "wiki/sources must still be scanned once, got "
        f"{counters.sources_rglob_calls} scans"
    )
    assert counters.sources_read_calls == 0, (
        "excluded pages must not even be read, got "
        f"{counters.sources_read_calls} reads"
    )
