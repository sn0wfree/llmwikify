"""Contract tests for the lint page snapshot (P4-b-1, P4-b-2).

The snapshot is the *boundary* of the P4-b work: an immutable
``PageSnapshot`` plus a ``PageSource`` protocol, and a parallel
``run_with_snapshot`` entry point on the rule base classes.

P4-b-2 wires it into the production path: the analyzer builds ONE
snapshot per lint run and shares it with the scan, the rules and the
LLM context. The snapshot is built **lazily**, so a fully cached run
still reads nothing (that is the gain of P4-a).

What is pinned here (recon C15: the base class contract had almost no
test coverage at all):

* the snapshot is immutable and deeply read-only;
* the snapshot enumerates the pages through ``wiki._wiki_pages()`` and
  does **not** filter ``Query:`` pages -- which pages are skipped is
  platform dependent (recon C11);
* a snapshot that exceeds the memory budget *degrades*: the pages are
  not dropped but read back from disk, so the issues do not change;
* ``run_with_snapshot`` produces exactly the issues of ``run`` -- with
  and without a snapshot;
* the cold lint read counts are 311 reads / 2 rglobs (one snapshot for
  the whole run; 929 / 9 before P4-b-2, 476 / 6 after P4-b-2) -- the
  counting baseline itself lives in ``tests/test_lint_snapshot_counts.py``;
* a fully cached lint run builds no snapshot and reads no page.

P4-b-3a migrates the two rules that still walked the wiki on their own
(``dated_claim``, ``knowledge_gap``) to the snapshot. What is pinned
here:

* the migrated rules report exactly the same issues as before, issue by
  issue;
* they read no wiki page from disk any more (the source summary pages
  of the ``knowledge_gap`` rule come from the snapshot, under their
  display name ``sources/<name>``);
* the raw scan of the ``dated_claim`` rule is untouched -- the raw
  directory is not part of the snapshot;
* the residual risk R1 (a source summary page that is not valid UTF-8
  kills the ``knowledge_gap`` rule) is closed, in the legacy path and in
  the snapshot path alike.

P4-b-3b migrates the two rules that only need the page *names*
(``topic_overlap``, ``redundancy``). What is pinned here:

* the migrated rules report exactly the same issues as before, issue by
  issue -- ``redundancy`` down to the order of ``page_a`` / ``page_b``;
* they do not walk the wiki directory any more: their own ``rglob`` is
  gone (the cold path ends at 311 reads / 2 rglobs);
* ``topic_overlap`` takes the **file stem** from the snapshot
  (``snapshot.path_of(name).stem``), not the display name -- the two
  differ for a page like ``Query:foo.bar.md``;
* the platform contract of the ``Query:`` prefix is pinned: the rule
  matches the half width colon only, so on Windows (where the path
  codec writes the full width colon) it stays dead code.

P4-b-3c closes the findings of the review round 1. What is pinned here:

* the two paths of the ``knowledge_gap`` rule -- with and without a
  snapshot -- see exactly the same source pages, so the two public
  interfaces of the rule can not report different issues for the same
  wiki (a candidate that is missing in one path shifts the truncation
  window of ``max_results``);
* the rules get the same ``(page_name, content)`` pairs in both paths
  (design section 8.1 #2);
* one ``wiki.lint()`` run reads every page file at most twice -- the
  snapshot plus the raw read of ``status.py`` (design section 14 R-3);
* a duplicate display name keeps the first page and warns; the second
  one is silently dropped (design section 14 R-8).

Benchmark command::

    D:\\tools\\python312\\python.exe -m pytest tests/test_lint_snapshot.py -q -s --rootdir=D:\\Github\\llmwikify
"""

from __future__ import annotations

import dataclasses
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.kernel import Wiki
from llmwikify.kernel.wiki.engines.analyzer import WikiAnalyzer
from llmwikify.kernel.wiki.lint import LintEngine, Rule
from llmwikify.kernel.wiki.lint.rules import (
    RULES,
    DatedClaimsRule,
    KnowledgeGapsRule,
    MissingCrossRefsRule,
)
from llmwikify.kernel.wiki.snapshot import (
    SNAPSHOT_MAX_PAGE_BYTES,
    SNAPSHOT_MAX_TOTAL_BYTES,
    PageSnapshot,
    WikiPageSource,
)

# -- the cold benchmark fixture (recon C3) ------------------------------

COLD_REGULAR_PAGES = 126
COLD_QUERY_PAGES = 10
COLD_SOURCE_PAGES = 14
COLD_RAW_FILES = 8

# The query pages carry the full width colon that ``path_codec`` writes
# on Windows. With the ASCII colon (POSIX) the "Query:" filter of
# ``Rule._iter_pages`` / ``CrossPageRule._load_pages`` would drop 8 of
# the 10 query pages and the read count would differ per platform --
# the fixture keeps the count the same everywhere.
FULL_WIDTH_COLON = "："

# The counts measured by the recon (C3) for the cold lint path
# (``_scan_all_pages`` + the 8 rules): 151 pages, 14 source pages and
# 8 raw files.
#
# The evolution of the cold path (design section 0.2):
#
# * 929 / 9 — before P4-b-2: the scan read every page and every rule
#   read every page again (6.2 reads per page).
# * 476 / 6 — after P4-b-2: the analyzer shares ONE page snapshot with
#   the scan and the rules. The rules that still read the pages
#   themselves (dated_claim, knowledge_gap, topic_overlap, redundancy)
#   are migrated in P4-b-3.
# * 311 / 4 — after P4-b-3a: dated_claim / knowledge_gap consume the
#   snapshot (the source pages of the knowledge_gap rule live under
#   ``wiki/sources/`` and are therefore part of it).
# * 311 / 2 — after P4-b-3b: topic_overlap / redundancy take their
#   page names from the snapshot (their own rglob goes away). This is
#   the end point of the snapshot plan: the 311 reads are 151 (the
#   snapshot itself) + 151 (the raw reads of ``status.py``, design §14
#   R-3) + 8 (the raw files of dated_claim) + 1 (wiki.md), and the 2
#   rglobs are the enumeration of the snapshot and the raw directory of
#   dated_claim.
#
# 174 / 3 (the original target of the orchestrator) is only reachable
# when ``status.py`` is released: its 151 raw reads of
# ``_should_exclude_orphan`` must read the snapshot too (design §14
# R-3).
#
# The gate itself lives in ``tests/test_lint_snapshot_counts.py`` (the
# counting baseline of design §8.2): the constants are there, so that
# the two files can not drift apart.


def _cold_page_names() -> list[str]:
    """The page names of the cold fixture (recon fixture, verbatim)."""
    names = []
    for i in range(1, COLD_REGULAR_PAGES + 1):
        if i == 1:
            names.append("Topic Alpha")
        elif i == 2:
            names.append("Topic Alpha Extended")
        elif i == 3:
            names.append("Kubernetes")
        else:
            names.append(f"Topic {i:03d}")
    return names


def _cold_body(i: int, n_par: int) -> str:
    """Filler paragraphs: no year, no vague time word, no page name."""
    lines = []
    for k in range(n_par):
        lines.append(
            f"Paragraph {k} of document {i}: the organisation reported growth "
            f"in sector {k % 7} during period {k % 5} with {k + 3} units."
        )
    return "\n".join(lines)


def _build_cold_wiki(root: Path) -> Wiki:
    """Build the synthetic wiki of the recon (151 pages, 8 raw files)."""
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    wiki = Wiki(root)
    wiki.init()

    wd = root / "wiki"
    for idx, name in enumerate(_cold_page_names(), start=1):
        if idx % 13 == 0:
            sub = wd / "entities"
        elif idx % 7 == 0:
            sub = wd / "concepts"
        else:
            sub = wd
        sub.mkdir(parents=True, exist_ok=True)
        body = [
            f"# {name}",
            "",
            "## Sources",
            "",
            "[Source](https://example.invalid/r1) "
            "[Source 2](https://example.invalid/r2)",
            "",
            _cold_body(idx, 2 + (idx % 9)),
        ]
        (sub / f"{name}.md").write_text("\n".join(body) + "\n", encoding="utf-8")

    for i in range(1, COLD_QUERY_PAGES + 1):
        if i <= 8:
            sub = wd
            name = f"Query{FULL_WIDTH_COLON}topic {i:03d} overview"
        else:
            sub = wd / ("queries" if i == 9 else "archive")
            name = f"Query{FULL_WIDTH_COLON}kubernetes cluster deployment"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"{name}.md").write_text(
            f"# {name}\n\nQuery result body for {name}.\n", encoding="utf-8"
        )

    (wd / "sources").mkdir(parents=True, exist_ok=True)
    for i in range(1, COLD_SOURCE_PAGES + 1):
        (wd / "sources" / f"source-{i:03d}.md").write_text(
            f"# Source {i:03d}\n\nSummary of raw file {i:03d} "
            f"with a [[Topic 004]] reference.\n",
            encoding="utf-8",
        )

    for i in range(1, COLD_RAW_FILES + 1):
        (root / "raw" / f"topic-{i:03d}.md").write_text(
            f"# Raw {i:03d}\n\nSource material published in 2025 "
            f"about subject {i}.\n",
            encoding="utf-8",
        )
    return wiki


# -- the small fixture -------------------------------------------------

SMALL_PAGES = {
    "Alpha.md": (
        "# Alpha\n\n"
        "Alpha was founded in 2019 in Berlin.\n\n"
        "Kubernetes adoption is growing everywhere.\n"
    ),
    "Beta.md": (
        "# Beta\n\n"
        "See (raw/topic-001.md) for the 2019 figure.\n\n"
        "Kubernetes adoption is growing everywhere.\n"
    ),
    "Gamma.md": (
        "# Gamma\n\n"
        "The first assertion line is definitely long enough to count.\n\n"
        "The second assertion line is definitely long enough to count.\n\n"
        "The third assertion line is definitely long enough to count.\n\n"
        "Kubernetes adoption is growing everywhere.\n"
    ),
    "Delta.md": "# Delta\n\ndeployment limit: 100 units\n",
    "Epsilon.md": "# Epsilon\n\ndeployment limit: 250 units\n",
    "Kubernetes.md": "# Kubernetes\n\nShort note about the topic.\n",
    "Tiny.md": "x",
    "sources/source-001.md": ("# Source 001\n\nSummary with a [[Alpha]] reference.\n"),
}

# The rules that report an issue on the small fixture. The fixture is
# worthless without "teeth": a rule that stops reporting must fail here.
RULES_WITH_ISSUES = {
    "data_gap",
    "potentially_outdated",
    "dated_claim",
    "missing_cross_ref",
    "contradiction",
}


class _ProbeRule(Rule):
    """Records the ``(page_name, content)`` pairs it is given."""

    name = "probe"

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def detect(
        self,
        page_name: str,
        content: str,
        wiki: Wiki,
        results: list[dict],
    ) -> None:
        self.seen.append((page_name, content))


def _fresh_rules() -> list[Rule]:
    """Fresh rule instances -- ``RULES`` is a module level singleton."""
    return [type(rule)() for rule in RULES]


def _count_reads(rule: Rule, wiki: Wiki, with_snapshot: bool) -> int:
    """Count the ``Path.read_text`` calls made while the rule runs."""
    calls: list[Path] = []
    original = Path.read_text

    def counting(self, *args, **kwargs):
        calls.append(self)
        return original(self, *args, **kwargs)

    Path.read_text = counting
    try:
        if with_snapshot:
            rule.run_with_snapshot(wiki, None)
        else:
            rule.run(wiki)
    finally:
        Path.read_text = original
    return len(calls)


class _Counters:
    """Filesystem counters for the cold lint path."""

    def __init__(self) -> None:
        self.read_text = 0
        self.rglob = 0

    def install(self, monkeypatch) -> None:
        """Count ``Path.read_text`` / ``Path.rglob`` calls."""
        counters = self
        original_read_text = Path.read_text
        original_rglob = Path.rglob

        def counting_read_text(path, *args, **kwargs):
            counters.read_text += 1
            return original_read_text(path, *args, **kwargs)

        def counting_rglob(path, *args, **kwargs):
            counters.rglob += 1
            return original_rglob(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read_text)
        monkeypatch.setattr(Path, "rglob", counting_rglob)


@pytest.fixture
def small_wiki(tmp_path):
    """A small wiki that makes several rules report an issue."""
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()

    for name, content in SMALL_PAGES.items():
        page = root / "wiki" / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(content, encoding="utf-8")
    (root / "raw" / "topic-001.md").write_text(
        "# Raw 001\n\nSource material published in 2024.\n", encoding="utf-8"
    )

    yield wiki
    wiki.close()


@pytest.fixture
def snapshot(small_wiki):
    """The snapshot of the small wiki, without any budget limit."""
    return WikiPageSource(small_wiki).snapshot()


# -- the snapshot object ------------------------------------------------


def test_snapshot_is_frozen(snapshot):
    """A frozen dataclass: the fields cannot be replaced."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.names = ("other",)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.byte_size = 7  # type: ignore[misc]


def test_snapshot_mappings_are_read_only(snapshot):
    """The mappings are wrapped: the snapshot is deeply read-only."""
    name = snapshot.names[0]

    with pytest.raises(TypeError):
        snapshot.contents[name] = "tampered"  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.paths[name] = Path("nope")  # type: ignore[index]


def test_snapshot_enumerates_the_pages_of_the_wiki(small_wiki, snapshot):
    """The snapshot reuses ``wiki._wiki_pages()`` (recon C12)."""
    expected = [small_wiki._page_display_name(p) for p in small_wiki._wiki_pages()]

    assert list(snapshot.names) == expected
    assert len(set(snapshot.names)) == len(snapshot.names)


def test_snapshot_keys_are_unique(small_wiki, snapshot):
    """Design §8.1 #8: the display name is injective -> the keys are unique.

    ``_page_display_name`` is the relative path without ``.md``, so two
    different pages can not share a name (recon C13).
    """
    assert len(set(snapshot.names)) == len(snapshot.names)
    assert len(snapshot.names) == len(snapshot.paths)
    assert len(snapshot.contents) <= len(snapshot.names)


def test_duplicate_page_name_keeps_the_first_and_warns(small_wiki, monkeypatch, caplog):
    """A duplicate display name: the first page wins, the second is lost.

    The snapshot keeps the first page and warns (``snapshot.py``). The
    dropped page ends up in neither ``contents`` nor ``omitted``: it is
    silently lost, and ``total_pages`` (``len(snapshot.names)``) counts
    one page too few (design §14 R-8).

    A duplicate can not happen on a normal file system -- the display
    name is injective -- so the enumeration is patched to yield the
    same page twice.
    """
    page = small_wiki.wiki_dir / "Alpha.md"
    original_rglob = Path.rglob

    def patched_rglob(path, pattern):
        if path == small_wiki.wiki_dir and pattern == "*.md":
            found = list(original_rglob(path, pattern))
            found.append(page)
            return iter(found)
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", patched_rglob)

    with caplog.at_level(logging.WARNING):
        snapshot = WikiPageSource(small_wiki).snapshot()

    assert snapshot.names.count("Alpha") == 1, "the first page is kept"
    assert "Alpha" not in snapshot.omitted, "the dropped page is not degraded"
    warnings = [r.getMessage() for r in caplog.records]
    assert any("duplicate page name" in message for message in warnings), warnings

    enumerated = len(small_wiki._wiki_pages())
    assert len(snapshot.names) == enumerated - 1, "one page is lost"

    monkeypatch.setattr(WikiAnalyzer, "_llm_detect_gaps", lambda self, *a, **k: [])
    result = small_wiki.lint()
    assert result["total_pages"] == len(snapshot.names)
    assert result["total_pages"] == enumerated - 1


def test_snapshot_relative_names_match_the_existing_page_names(small_wiki, snapshot):
    """``relative_names`` has the format of ``_get_existing_page_names()``."""
    assert sorted(snapshot.relative_names) == sorted(
        small_wiki._get_existing_page_names()
    )
    for name, relative in zip(snapshot.names, snapshot.relative_names, strict=True):
        assert relative.endswith(".md")
        assert snapshot.path_of(name) == small_wiki.wiki_dir / relative


def test_snapshot_content_matches_the_file(small_wiki, snapshot):
    """The cached content is the content of the file."""
    name = "Alpha"

    assert snapshot.content_of(name) == (small_wiki.wiki_dir / "Alpha.md").read_text(
        encoding="utf-8"
    )
    assert snapshot.content_of("does not exist") is None


def test_snapshot_reads_pages_lossy(tmp_path):
    """A page that is not valid UTF-8 is read lossy, not dropped."""
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    wiki = Wiki(root)
    wiki.init()
    (root / "wiki" / "Broken Page.md").write_bytes(
        b"# Broken Page\n\nReadable text \xff with an invalid byte.\n"
    )

    try:
        broken = WikiPageSource(wiki).snapshot()
        content = broken.content_of("Broken Page")

        assert content is not None
        assert "Readable text" in content
        assert "" in content
        assert broken.degraded is False
    finally:
        wiki.close()


def test_snapshot_does_not_filter_query_pages(small_wiki):
    """The snapshot keeps every page -- the filter is the consumer's."""
    probe = PageSnapshot(
        names=("Query: alpha", "Alpha"),
        contents={"Query: alpha": "q", "Alpha": "a"},
        paths={
            "Query: alpha": small_wiki.wiki_dir / "Alpha.md",
            "Alpha": small_wiki.wiki_dir / "Alpha.md",
        },
        relative_names=("Query: alpha.md", "Alpha.md"),
    )

    assert "Query: alpha" in probe.names

    rule = _ProbeRule()
    rule.run_with_snapshot(small_wiki, probe)

    assert rule.seen == [("Alpha", "a")], "the rule skips the query page"


# -- the memory budget and the degradation ------------------------------


def test_snapshot_degrades_when_the_budget_is_exceeded(small_wiki):
    """Pages that do not fit into the budget are omitted, not dropped."""
    degraded = WikiPageSource(small_wiki, max_total_bytes=1).snapshot()

    assert degraded.degraded is True
    assert degraded.omitted
    for name in degraded.omitted:
        assert degraded.content_of(name) is None, name
    assert list(degraded.names) == [
        small_wiki._page_display_name(p) for p in small_wiki._wiki_pages()
    ], "the pages are still known, only their content is missing"


def test_snapshot_omits_only_the_oversized_pages(small_wiki):
    """A page above the per page limit is left out, the small one is not."""
    limited = WikiPageSource(small_wiki, max_page_bytes=8).snapshot()

    assert limited.degraded is True
    assert "Tiny" in limited.contents
    assert "Alpha" in limited.omitted
    assert limited.path_of("Alpha").exists()


def test_degraded_snapshot_keeps_the_issues(small_wiki):
    """The fallback read gives the same issues as the legacy path."""
    degraded = WikiPageSource(small_wiki, max_total_bytes=1).snapshot()
    assert degraded.degraded is True

    for rule in _fresh_rules():
        assert rule.run_with_snapshot(small_wiki, degraded) == rule.run(small_wiki)


def test_degraded_snapshot_logs_a_warning(small_wiki, caplog):
    """The degradation is observable."""
    with caplog.at_level(logging.WARNING):
        WikiPageSource(small_wiki, max_total_bytes=1).snapshot()

    warnings = [r.getMessage() for r in caplog.records]
    assert any("snapshot degraded" in message for message in warnings), warnings


def test_snapshot_budget_constants():
    """The budget is the one of the design (64 MiB / 1 MiB per page)."""
    assert SNAPSHOT_MAX_PAGE_BYTES == 1 * 1024 * 1024
    assert SNAPSHOT_MAX_TOTAL_BYTES == 64 * 1024 * 1024


# -- the parallel entry points ------------------------------------------


def test_small_fixture_has_teeth(small_wiki):
    """The fixture must make the rules report, otherwise the equality
    assertions below would be vacuous."""
    reported = {rule.name for rule in _fresh_rules() if rule.run(small_wiki)}

    assert reported == RULES_WITH_ISSUES


def test_run_with_snapshot_none_matches_run(small_wiki):
    """Without a snapshot the new entry point is the legacy path."""
    for rule in _fresh_rules():
        assert rule.run_with_snapshot(small_wiki, None) == rule.run(small_wiki)


def test_run_with_snapshot_none_reads_exactly_as_run(small_wiki):
    """Without a snapshot the new entry point does the same I/O."""
    for rule in _fresh_rules():
        legacy = _count_reads(rule, small_wiki, with_snapshot=False)
        parallel = _count_reads(rule, small_wiki, with_snapshot=True)

        assert parallel == legacy, rule.name


def test_run_with_snapshot_matches_run_for_every_rule(small_wiki, snapshot):
    """With a snapshot the issues are the issues of the legacy path."""
    for rule in _fresh_rules():
        assert rule.run_with_snapshot(small_wiki, snapshot) == rule.run(
            small_wiki
        ), rule.name


def test_detect_receives_same_page_name_and_content(small_wiki, snapshot):
    """Design §8.1 #2: the rules get the same ``(page_name, content)``.

    Comparing the *inputs* is stronger than comparing the produced
    issues: a rule could be fed a different content and still happen to
    report the same issues.
    """
    legacy = _ProbeRule()
    legacy.run(small_wiki)

    parallel = _ProbeRule()
    parallel.run_with_snapshot(small_wiki, snapshot)

    assert legacy.seen, "the probe must have seen the pages"
    assert parallel.seen == legacy.seen


def test_pages_from_snapshot_matches_load_pages(small_wiki, snapshot):
    """The cross page input is the input of ``_load_pages``."""
    rule = MissingCrossRefsRule()

    assert rule._pages_from_snapshot(snapshot) == rule._load_pages(small_wiki)


def test_pages_from_snapshot_uses_the_same_query_filter(small_wiki, snapshot):
    """``_pages_from_snapshot`` filters exactly like ``_load_pages``."""
    rule = MissingCrossRefsRule()
    legacy = rule._load_pages(small_wiki)

    probe = PageSnapshot(
        names=("Query: probe",) + snapshot.names,
        contents={"Query: probe": "q", **snapshot.contents},
        paths={
            "Query: probe": small_wiki.wiki_dir / "Alpha.md",
            **snapshot.paths,
        },
        relative_names=("Query: probe.md",) + snapshot.relative_names,
    )
    filtered = rule._pages_from_snapshot(probe)

    assert "Query: probe" not in filtered
    assert set(filtered) == set(legacy)


# -- the migration of the two rules (P4-b-3a) ---------------------------

# The rules that P4-b-3a moves onto the snapshot.
SNAPSHOT_RULES = ("dated_claim", "knowledge_gap")


def _rule_by_name(name: str) -> Rule:
    """A fresh instance of the rule with that name."""
    for rule in _fresh_rules():
        if rule.name == name:
            return rule
    raise AssertionError(f"unknown rule {name!r}")


@pytest.fixture
def snapshot_wiki(tmp_path):
    """A wiki on which *both* migrated rules report something.

    ``dated_claim`` needs a raw source with a newer year and a page with
    an old year; ``knowledge_gap`` needs a source summary page without
    wikilinks (an ``isolated_source`` gap).
    """
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()

    (root / "wiki" / "Alpha.md").write_text(
        "# Alpha\n\nAlpha was founded in 2019 in Berlin.\n", encoding="utf-8"
    )
    (root / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "sources" / "source-001.md").write_text(
        "# Source 001\n\nA summary without any cross reference.\n",
        encoding="utf-8",
    )
    (root / "raw" / "topic-001.md").write_text(
        "# Raw 001\n\nSource material published in 2024.\n", encoding="utf-8"
    )

    yield wiki
    wiki.close()


def _count_io(rule: Rule, wiki: Wiki, snapshot: PageSnapshot):
    """The ``read_text`` / ``rglob`` calls of ``run_with_snapshot``."""
    reads: list[Path] = []
    rglobs: list[Path] = []
    original_read_text = Path.read_text
    original_rglob = Path.rglob

    def counting_read_text(path, *args, **kwargs):
        reads.append(path)
        return original_read_text(path, *args, **kwargs)

    def counting_rglob(path, *args, **kwargs):
        rglobs.append(path)
        return original_rglob(path, *args, **kwargs)

    Path.read_text = counting_read_text
    Path.rglob = counting_rglob
    try:
        rule.run_with_snapshot(wiki, snapshot)
    finally:
        Path.read_text = original_read_text
        Path.rglob = original_rglob
    return reads, rglobs


def test_snapshot_rules_report_on_the_snapshot_wiki(snapshot_wiki):
    """The fixture must make both migrated rules report.

    Otherwise the equality assertions below would be vacuous.
    """
    for name in SNAPSHOT_RULES:
        assert _rule_by_name(name).run(snapshot_wiki), name


def test_snapshot_rules_are_equal_issue_by_issue(snapshot_wiki):
    """``run_with_snapshot`` == ``run``, issue by issue."""
    snapshot = WikiPageSource(snapshot_wiki).snapshot()

    for name in SNAPSHOT_RULES:
        legacy = _rule_by_name(name).run(snapshot_wiki)
        parallel = _rule_by_name(name).run_with_snapshot(snapshot_wiki, snapshot)

        assert len(parallel) == len(legacy), name
        for legacy_issue, parallel_issue in zip(legacy, parallel, strict=True):
            assert parallel_issue == legacy_issue, name


def test_snapshot_rules_without_a_snapshot_are_the_legacy_path(snapshot_wiki):
    """``run_with_snapshot(wiki, None)`` is the legacy path."""
    for name in SNAPSHOT_RULES:
        rule = _rule_by_name(name)
        assert rule.run_with_snapshot(snapshot_wiki, None) == rule.run(snapshot_wiki)


def test_snapshot_rules_read_no_wiki_page_again(snapshot_wiki):
    """With a snapshot the migrated rules read no wiki page from disk."""
    snapshot = WikiPageSource(snapshot_wiki).snapshot()
    wiki_dir = snapshot_wiki.wiki_dir

    for name in SNAPSHOT_RULES:
        rule = _rule_by_name(name)
        reads, rglobs = _count_io(rule, snapshot_wiki, snapshot)

        page_reads = [path for path in reads if path.is_relative_to(wiki_dir)]
        page_rglobs = [path for path in rglobs if path.is_relative_to(wiki_dir)]

        assert page_reads == [], (name, page_reads)
        assert page_rglobs == [], (name, page_rglobs)


def test_dated_claim_keeps_the_raw_scan(snapshot_wiki):
    """The raw directory is not part of the snapshot: it is still scanned."""
    snapshot = WikiPageSource(snapshot_wiki).snapshot()
    rule = DatedClaimsRule()

    reads, rglobs = _count_io(rule, snapshot_wiki, snapshot)

    assert [path for path in rglobs if path == snapshot_wiki.raw_dir], rglobs
    raw_reads = [path for path in reads if path.is_relative_to(snapshot_wiki.raw_dir)]
    assert raw_reads, reads


def test_dated_claim_keeps_the_early_return(tmp_path):
    """Without a year in the raw sources the rule returns nothing.

    The early return happens before any page is read, in both paths.
    """
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    wiki = Wiki(root)
    wiki.init()
    (root / "wiki" / "Alpha.md").write_text(
        "# Alpha\n\nAlpha was founded in 2019 in Berlin.\n", encoding="utf-8"
    )
    (root / "raw" / "topic-001.md").write_text(
        "# Raw 001\n\nNo year in this file.\n", encoding="utf-8"
    )

    try:
        snapshot = WikiPageSource(wiki).snapshot()

        legacy = DatedClaimsRule()
        assert legacy.run(wiki) == []
        assert not hasattr(legacy, "_latest_source_year")

        parallel = DatedClaimsRule()
        assert parallel.run_with_snapshot(wiki, snapshot) == []
        assert not hasattr(parallel, "_latest_source_year")
    finally:
        wiki.close()


def test_knowledge_gap_takes_the_source_pages_from_the_snapshot(snapshot_wiki):
    """The source page is found under its display name ``sources/<name>``."""
    snapshot = WikiPageSource(snapshot_wiki).snapshot()

    assert "sources/source-001" in snapshot.names
    assert snapshot.content_of("sources/source-001") is not None

    issues = KnowledgeGapsRule().run_with_snapshot(snapshot_wiki, snapshot)
    isolated = [issue for issue in issues if issue["type"] == "isolated_source"]

    assert [issue["page"] for issue in isolated] == ["sources/source-001"]


@pytest.fixture
def pathological_source_wiki(tmp_path):
    """A wiki with a source summary page named ``index.md``.

    ``_wiki_pages()`` excludes the stems ``index`` and ``log``; the
    enumeration of the source pages used to be its own
    ``sources_dir.rglob("*.md")``, which did not exclude them. A raw
    document named ``index.md`` produces exactly such a summary page
    (``_slugify`` -> ``index``).
    """
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki" / "sources").mkdir(parents=True)
    wiki = Wiki(root)
    wiki.init()

    (root / "wiki" / "sources" / "index.md").write_text(
        "# Index\n\nA source summary page without any cross reference.\n",
        encoding="utf-8",
    )
    for i in range(1, 4):
        (root / "wiki" / "sources" / f"source-{i:03d}.md").write_text(
            f"# Source {i:03d}\n\nA source summary page without a reference.\n",
            encoding="utf-8",
        )

    yield wiki
    wiki.close()


def test_knowledge_gap_paths_report_the_same_source_pages(pathological_source_wiki):
    """Both paths of the rule see the same source pages -- issue by issue.

    The candidate set of the two paths must be identical: the rule
    truncates at ``max_results`` *inside* the loop, so a candidate that
    is missing in one path shifts the truncation window and changes the
    reported issues. The legacy path is the one of
    ``wiki._detect_knowledge_gaps()`` (the chat skill), the snapshot
    path is the one of ``lint()``.
    """
    wiki = pathological_source_wiki
    snapshot = WikiPageSource(wiki).snapshot()

    legacy = KnowledgeGapsRule().run(wiki)
    parallel = KnowledgeGapsRule().run_with_snapshot(wiki, snapshot)

    assert legacy == parallel, "the two paths must report the same issues"
    assert legacy, "the fixture must make the rule report"

    pages = [issue["page"] for issue in legacy if issue["type"] == "isolated_source"]
    assert set(pages) == {
        "sources/source-001",
        "sources/source-002",
        "sources/source-003",
    }
    assert "sources/index" not in pages, "the excluded stem is not checked"


def test_degraded_snapshot_keeps_the_source_pages(snapshot_wiki):
    """Over budget: the source pages are read back from disk.

    The snapshot degrades, it does not filter: the issues stay the same.
    """
    degraded = WikiPageSource(snapshot_wiki, max_total_bytes=1).snapshot()
    assert degraded.degraded is True

    for name in SNAPSHOT_RULES:
        rule = _rule_by_name(name)
        assert rule.run_with_snapshot(snapshot_wiki, degraded) == rule.run(
            snapshot_wiki
        ), name


def test_knowledge_gap_survives_a_non_utf8_source_page(tmp_path):
    """R1: a source page that is not valid UTF-8 must not kill the rule.

    Design: ``p4-lint-snapshot.md`` §11 R1, closed by ``p4b-lint-snapshot.md``.
    """
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki" / "sources").mkdir(parents=True)
    wiki = Wiki(root)
    wiki.init()
    (root / "wiki" / "sources" / "Broken Source.md").write_bytes(
        b"# Broken Source\n\nReadable source \xff with an invalid byte.\n"
    )

    try:
        snapshot = WikiPageSource(wiki).snapshot()

        legacy = KnowledgeGapsRule().run(wiki)
        parallel = KnowledgeGapsRule().run_with_snapshot(wiki, snapshot)

        assert parallel == legacy
        assert [issue["page"] for issue in parallel] == ["sources/Broken Source"]
    finally:
        wiki.close()


# -- the migration of the two name rules (P4-b-3b) ----------------------

# The rules that P4-b-3b moves onto the snapshot: they only need the
# page names, not the page bodies.
NAME_RULES = ("topic_overlap", "redundancy")

# The query page names as POSIX writes them (half width colon). The
# keywords of the first two pages overlap by 10 of 11 -> a Jaccard of
# 0.909, above the threshold of 0.85. The third page carries a dot:
# its display name ("Query:foo.bar") and its file stem are different
# things, and only the stem may be used.
POSIX_QUERY_PAGES = (
    "Query: alpha bravo charlie delta echo foxtrot golf hotel india juliet",
    "Query: alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo",
    "Query:foo.bar",
)


def _inject_page_names(monkeypatch, wiki_dir: Path, pages: list[Path]) -> None:
    """Make the ``*.md`` enumeration of ``wiki_dir`` return ``pages``.

    On Windows a file name cannot contain ``:`` -- the path codec writes
    the full width colon instead -- so the legacy enumeration of
    ``topic_overlap`` never sees a query page there and the rule is
    dead code on that platform. Injecting the POSIX names makes both
    paths comparable on every platform.
    """
    original_rglob = Path.rglob

    def patched_rglob(path, pattern):
        if path == wiki_dir and pattern == "*.md":
            return iter(list(pages))
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", patched_rglob)


def _synthetic_snapshot(wiki_dir: Path, file_names: list[str]) -> PageSnapshot:
    """A snapshot of file names that do not exist on disk.

    The POSIX spelling of a query page cannot be written on Windows, so
    the platform contract of the ``Query:`` prefix is checked with such
    a snapshot. The display name is the file name without ``.md``.
    """
    paths = {name[:-3]: wiki_dir / name for name in file_names}
    return PageSnapshot(
        names=tuple(paths),
        contents={},
        paths=paths,
        relative_names=tuple(file_names),
    )


@pytest.fixture
def name_rules_wiki(tmp_path):
    """A wiki on which the ``redundancy`` rule reports.

    The rule compares the page names: two pages whose names contain one
    another are reported (``Kubernetes`` / ``Kubernetes Cluster`` and
    ``Prometheus`` / ``Prometheus Operator``).
    """
    root = tmp_path / "name_rules_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()

    for name in (
        "Kubernetes",
        "Kubernetes Cluster",
        "Prometheus",
        "Prometheus Operator",
    ):
        (root / "wiki" / f"{name}.md").write_text(
            f"# {name}\n\nA short note about the topic.\n", encoding="utf-8"
        )

    yield wiki
    wiki.close()


@pytest.fixture
def posix_query_wiki(small_wiki, monkeypatch):
    """The small wiki with POSIX style query pages.

    See ``_inject_page_names``: on Windows such a file name cannot be
    written at all.
    """
    pages = [small_wiki.wiki_dir / f"{name}.md" for name in POSIX_QUERY_PAGES]
    _inject_page_names(monkeypatch, small_wiki.wiki_dir, pages)

    return small_wiki


def test_name_rules_report_on_their_fixture(name_rules_wiki, posix_query_wiki):
    """The fixtures must make the rules report.

    Otherwise the equality assertions below would be vacuous.
    """
    redundancy = _rule_by_name("redundancy").run(name_rules_wiki)

    assert len(redundancy) == 2
    assert {frozenset((issue["page_a"], issue["page_b"])) for issue in redundancy} == {
        frozenset(("Kubernetes", "Kubernetes Cluster")),
        frozenset(("Prometheus", "Prometheus Operator")),
    }

    topic_overlap = _rule_by_name("topic_overlap").run(posix_query_wiki)

    assert len(topic_overlap) == 1
    assert topic_overlap[0]["page_a"] == POSIX_QUERY_PAGES[0]
    assert topic_overlap[0]["page_b"] == POSIX_QUERY_PAGES[1]


def test_redundancy_snapshot_path_matches_the_legacy_path(name_rules_wiki):
    """``run_with_snapshot`` == ``run``, issue by issue.

    The order of ``page_a`` / ``page_b`` is part of the comparison.
    """
    snapshot = WikiPageSource(name_rules_wiki).snapshot()

    legacy = _rule_by_name("redundancy").run(name_rules_wiki)
    parallel = _rule_by_name("redundancy").run_with_snapshot(name_rules_wiki, snapshot)

    assert len(legacy) == 2
    assert len(parallel) == len(legacy)
    for legacy_issue, parallel_issue in zip(legacy, parallel, strict=True):
        assert parallel_issue == legacy_issue


def test_topic_overlap_snapshot_path_matches_the_legacy_path(posix_query_wiki):
    """``run_with_snapshot`` == ``run``, issue by issue."""
    snapshot = WikiPageSource(posix_query_wiki).snapshot()
    rule = _rule_by_name("topic_overlap")

    legacy = rule.run(posix_query_wiki)
    parallel = rule.run_with_snapshot(posix_query_wiki, snapshot)

    assert len(legacy) == 1
    assert len(parallel) == len(legacy)
    for legacy_issue, parallel_issue in zip(legacy, parallel, strict=True):
        assert parallel_issue == legacy_issue


def test_name_rules_do_not_walk_the_wiki_with_a_snapshot(
    name_rules_wiki, posix_query_wiki
):
    """With a snapshot the two rules do not rglob the wiki directory."""
    cases = ((name_rules_wiki, "redundancy"), (posix_query_wiki, "topic_overlap"))

    for wiki, name in cases:
        snapshot = WikiPageSource(wiki).snapshot()
        rule = _rule_by_name(name)
        reads, rglobs = _count_io(rule, wiki, snapshot)

        wiki_reads = [path for path in reads if path.is_relative_to(wiki.wiki_dir)]
        wiki_rglobs = [path for path in rglobs if path.is_relative_to(wiki.wiki_dir)]

        assert wiki_rglobs == [], name
        assert wiki_reads == [], name


def test_name_rules_without_a_snapshot_are_the_legacy_path(
    name_rules_wiki, posix_query_wiki
):
    """``run_with_snapshot(wiki, None)`` is the legacy path."""
    cases = ((name_rules_wiki, "redundancy"), (posix_query_wiki, "topic_overlap"))

    for wiki, name in cases:
        rule = _rule_by_name(name)
        assert rule.run_with_snapshot(wiki, None) == rule.run(wiki), name


def test_topic_overlap_uses_the_file_stem_not_the_display_name(posix_query_wiki):
    """``Query:foo.bar.md`` is the page ``Query:foo.bar``, not ``Query:foo``.

    The display name is not a file name: ``Path("Query:foo.bar").stem``
    is ``Query:foo``. The rule has to take the stem from the path of
    the page on disk (``snapshot.path_of(name).stem``).
    """
    snapshot = WikiPageSource(posix_query_wiki).snapshot()
    rule = _rule_by_name("topic_overlap")

    query_pages = rule._query_pages_from_snapshot(snapshot)
    names = {page["page_name"] for page in query_pages}

    assert "Query:foo.bar" in names
    assert "Query:foo" not in names
    assert "foo" not in names

    dot_page = next(
        page for page in query_pages if page["page_name"] == "Query:foo.bar"
    )
    assert dot_page["file"] == str(snapshot.path_of("Query:foo.bar"))


def test_topic_overlap_matches_the_half_width_colon_only(posix_query_wiki):
    """The platform contract of the ``Query:`` prefix.

    The rule matches the **half width** colon only. On Windows the path
    codec writes the full width colon (``Query：foo.md``), so
    ``stem.startswith("Query:")`` is never true there and the rule stays
    dead code on that platform -- a behaviour that must not be "fixed".

    The test is platform independent: the file names are injected, so
    both spellings can be checked everywhere.
    """
    half = "Query: alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    half_more = f"{half} kilo"
    full = half.replace(":", "：")
    full_more = f"{full} kilo"

    snapshot = _synthetic_snapshot(
        posix_query_wiki.wiki_dir,
        [f"{name}.md" for name in (half, half_more, full, full_more)],
    )
    rule = _rule_by_name("topic_overlap")

    names = {page["page_name"] for page in rule._query_pages_from_snapshot(snapshot)}

    assert half in names, "the half width colon matches"
    assert full not in names, "the full width colon does not match"

    issues = rule.run_with_snapshot(posix_query_wiki, snapshot)

    assert len(issues) == 1, "only the half width pages are compared"
    assert issues[0]["page_a"] == half
    assert issues[0]["page_b"] == half_more


def test_topic_overlap_ignores_a_full_width_colon_file(tmp_path):
    """A real file name with the full width colon is not a query page.

    That is the state of the rule on Windows: the path codec writes the
    full width colon, the prefix never matches and the rule reports
    nothing there.
    """
    root = tmp_path / "wiki_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    wiki = Wiki(root)
    wiki.init()

    for name in (
        "Query：alpha bravo charlie delta echo foxtrot golf hotel india juliet",
        "Query：alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo",
    ):
        (root / "wiki" / f"{name}.md").write_text(
            "# Query\n\nThe body of the query page.\n", encoding="utf-8"
        )

    try:
        snapshot = WikiPageSource(wiki).snapshot()
        rule = _rule_by_name("topic_overlap")

        assert rule.run(wiki) == []
        assert rule.run_with_snapshot(wiki, snapshot) == []
    finally:
        wiki.close()


def test_degraded_snapshot_keeps_the_name_rules(name_rules_wiki):
    """Over budget: the pages are read back from disk, the issues stay.

    The snapshot degrades, it does not filter: the issues stay the same.
    """
    degraded = WikiPageSource(name_rules_wiki, max_total_bytes=1).snapshot()
    assert degraded.degraded is True

    rule = _rule_by_name("redundancy")

    assert rule.run_with_snapshot(name_rules_wiki, degraded) == rule.run(
        name_rules_wiki
    )


def test_degraded_snapshot_keeps_the_topic_overlap_issues(posix_query_wiki):
    """Over budget: the query pages are still the same ones."""
    degraded = WikiPageSource(posix_query_wiki, max_total_bytes=1).snapshot()
    assert degraded.degraded is True

    rule = _rule_by_name("topic_overlap")

    assert rule.run_with_snapshot(posix_query_wiki, degraded) == rule.run(
        posix_query_wiki
    )


# -- one lint run reads every page once (design §8.1 #13) ---------------


@pytest.fixture
def read_once_wiki(tmp_path):
    """A small wiki without source summary pages.

    The source summary pages have a third reader in a lint run
    (``_build_lint_context`` -> ``_build_source_summary_map``, design
    §14 R-1); the contract of test #13 is about the readers of the
    *pages*, so the fixture leaves them out.
    """
    root = tmp_path / "read_once_root"
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)

    wiki = Wiki(root)
    wiki.init()

    for name in ("Alpha", "Beta", "Gamma"):
        (root / "wiki" / f"{name}.md").write_text(
            f"# {name}\n\nA short note about the topic.\n", encoding="utf-8"
        )

    yield wiki
    wiki.close()


def test_each_page_read_at_most_once_during_lint(read_once_wiki, monkeypatch):
    """Design §8.1 #13: one lint run reads every page file once.

    This is the test that guards R-6 (the snapshot is the single truth
    of one run) and the whole point of the refactor: a page that is
    read twice means that some consumer bypassed the snapshot.

    The limit is **2** reads per page, not 1: ``status.py`` reads the
    page a second time (``_should_exclude_orphan``, design §14 R-3) --
    that file belongs to another writer and can not be touched in this
    task. When R-3 is fixed the limit drops to 1.

    The caliber is ``wiki.lint()`` -- the whole run, not just the scan
    and the rules.
    """
    wiki = read_once_wiki
    monkeypatch.setattr(WikiAnalyzer, "_llm_detect_gaps", lambda self, *a, **k: [])

    reads: dict[str, int] = {}
    original_read_text = Path.read_text

    def counting_read_text(path, *args, **kwargs):
        key = str(path)
        reads[key] = reads.get(key, 0) + 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    wiki.lint()

    wiki_pages = {str(page) for page in wiki._wiki_pages()}
    page_reads = {path: count for path, count in reads.items() if path in wiki_pages}
    violations = {path: count for path, count in page_reads.items() if count > 2}

    assert len(page_reads) == len(wiki_pages), "every page must have been read"
    assert violations == {}, violations


# -- the cold read counts (the gate) ------------------------------------
#
# The counting baseline moved to ``tests/test_lint_snapshot_counts.py``
# (design §8.2): the cold gate -- 311 reads / 2 rglobs for the snapshot
# path, 929 / 9 for the legacy path -- is asserted there, together with
# the hot caliber and the ``stat`` counter.


# -- the analyzer wiring (P4-b-2) ---------------------------------------


class _CountingPageSource:
    """A page source that counts how often the snapshot was built."""

    def __init__(self, wiki: Wiki) -> None:
        self._inner = WikiPageSource(wiki)
        self.builds = 0

    def snapshot(self) -> PageSnapshot:
        self.builds += 1
        return self._inner.snapshot()


def test_cold_lint_builds_the_snapshot_once(small_wiki, monkeypatch):
    """One lint run builds exactly one snapshot."""
    monkeypatch.setattr(WikiAnalyzer, "_llm_detect_gaps", lambda self, *a, **k: [])
    source = _CountingPageSource(small_wiki)
    analyzer = WikiAnalyzer(small_wiki, page_source=source)

    analyzer.lint()

    assert source.builds == 1


def test_fully_cached_lint_builds_no_snapshot(small_wiki, monkeypatch):
    """A fully cached run must not read a single page (P4-a's gain).

    The snapshot is built lazily: when the core cache *and* the LLM
    gaps cache hit, none of the three consumers runs and the snapshot
    must not be built at all.
    """
    monkeypatch.setattr(WikiAnalyzer, "_llm_detect_gaps", lambda self, *a, **k: [])
    source = _CountingPageSource(small_wiki)
    analyzer = WikiAnalyzer(small_wiki, page_source=source)

    analyzer.lint()  # warm: fills the "lint" and "lint_llm_gaps" caches
    assert source.builds == 1

    source.builds = 0
    counters = _Counters()
    counters.install(monkeypatch)

    result = analyzer.lint()  # both caches hit -> nothing to recompute

    print(
        f"\n[fully cached lint] read_text={counters.read_text} "
        f"snapshot builds={source.builds}"
    )

    assert result["cached"] is True, "the core cache must hit"
    assert source.builds == 0, "a fully cached run must not build a snapshot"
    assert counters.read_text == 0, "a fully cached run must not read a page"


def test_build_lint_context_is_identical_with_and_without_snapshot(
    small_wiki, snapshot
):
    """The LLM context text is character by character the same."""
    analyzer = small_wiki._analyzer

    without = analyzer._build_lint_context()
    with_snapshot = analyzer._build_lint_context(snapshot=snapshot)

    assert with_snapshot == without


def test_scan_all_pages_is_identical_with_and_without_snapshot(small_wiki, snapshot):
    """The scan reports the same links, orphans and broken links."""
    analyzer = small_wiki._analyzer

    legacy = analyzer._scan_all_pages()
    with_snapshot = analyzer._scan_all_pages(snapshot)

    assert with_snapshot == legacy


def test_run_all_with_snapshot_produces_the_same_issues(small_wiki, snapshot):
    """``run_all(snapshot)`` == ``run_all()`` — the rules keep their semantics."""
    engine = LintEngine(small_wiki, rules=_fresh_rules())

    assert engine.run_all(snapshot) == engine.run_all()


def test_run_rule_with_snapshot_produces_the_same_issues(small_wiki, snapshot):
    """``run_rule(name, snapshot)`` == ``run_rule(name)``."""
    engine = LintEngine(small_wiki, rules=_fresh_rules())

    for name in engine.rule_names:
        assert engine.run_rule(name, snapshot) == engine.run_rule(name), name


def test_run_rule_without_snapshot_builds_no_snapshot(small_wiki):
    """A single rule must not pay for a full page snapshot."""
    source = _CountingPageSource(small_wiki)
    analyzer = WikiAnalyzer(small_wiki, page_source=source)

    analyzer._run_rule("data_gap")

    assert source.builds == 0


def test_run_rule_without_snapshot_keeps_the_legacy_reads(small_wiki, monkeypatch):
    """Without a snapshot the rule still reads the pages itself."""
    counters = _Counters()
    counters.install(monkeypatch)

    engine = LintEngine(small_wiki, rules=_fresh_rules())
    engine.run_rule("data_gap")

    assert counters.read_text > 0, "the legacy path must still read the pages"
