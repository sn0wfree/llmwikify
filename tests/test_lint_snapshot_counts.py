"""Counting benchmark of the lint page snapshot (P4-b, design §8.2).

The gate of the snapshot plan is a *count*, not a wall clock: the cold
lint path (151 pages, 14 source summary pages, 8 raw files) must read
every page once.

This file owns the counting baseline:

* the **cold** caliber -- the page contents trigger no rule at all, so
  every consumer walks the whole wiki (the upper bound);
* the **hot** caliber -- the page contents trigger the rules, so every
  rule breaks as soon as it has ``max_results`` issues;
* the three counters ``Path.read_text`` / ``Path.rglob`` / ``Path.stat``
  -- the last one is the price of the snapshot: it measures the size of
  every page before reading it (design §14 R-7);
* both paths in the same test -- the legacy path (no snapshot) and the
  snapshot path -- so the file carries its own before/after.

The fixture is the one of ``tests/test_lint_snapshot.py``
(``_build_cold_wiki``); it is shared, not duplicated, so that the two
files can not drift apart.

Run (the numbers are printed for the benchmarker)::

    D:\\tools\\python312\\python.exe -m pytest tests/test_lint_snapshot_counts.py -q -s --rootdir=D:\\Github\\llmwikify
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from test_lint_snapshot import _build_cold_wiki

from llmwikify.kernel.wiki.snapshot import WikiPageSource

# -- the gate (cold caliber) --------------------------------------------

# The cold caliber is the upper bound: no rule triggers, so every
# consumer walks every page.
#
# The evolution of the cold path (design §0.2):
#
# * 929 / 9 — before P4-b-2: the scan read every page and every rule
#   read every page again.
# * 476 / 6 — after P4-b-2: the analyzer shares ONE page snapshot with
#   the scan and the rules.
# * 311 / 4 — after P4-b-3a: dated_claim / knowledge_gap consume the
#   snapshot.
# * 311 / 2 — after P4-b-3b: topic_overlap / redundancy take their
#   page names from the snapshot. This is the end point of the
#   snapshot plan: the 311 reads are 151 (the snapshot itself) + 151
#   (the raw reads of ``status.py``, design §14 R-3) + 8 (the raw
#   files of dated_claim) + 1 (wiki.md), and the 2 rglobs are the
#   enumeration of the snapshot and the raw directory of dated_claim.
#
# 174 / 3 (the original target of the orchestrator) is only reachable
# when ``status.py`` is released: its 151 raw reads of
# ``_should_exclude_orphan`` must read the snapshot too (design §14
# R-3).
COLD_READ_TEXT_MAX = 311
COLD_RGLOB_MAX = 2

# The legacy path (no snapshot) must stay where it was: it is the
# "before" of the refactoring.
LEGACY_READ_TEXT = 929
LEGACY_RGLOB = 9

# The snapshot measures the size of every page before it reads it
# (design §6.3): one ``stat`` per page (151 for the cold fixture).
SNAPSHOT_STAT_PER_PAGE = 151


class _Counters:
    """Filesystem counters: ``Path.read_text`` / ``Path.rglob`` / ``Path.stat``.

    ``Path.stat`` counts the existence checks as well: in Python 3.12
    ``Path.exists()`` is implemented with ``Path.stat()``, so the
    counter is "metadata IO", not only the size probe of the snapshot.
    The difference between the two paths is the interesting number.
    """

    def __init__(self) -> None:
        self.read_text = 0
        self.rglob = 0
        self.stat = 0

    def install(self, monkeypatch) -> None:
        """Count the three filesystem calls."""
        counters = self
        original_read_text = Path.read_text
        original_rglob = Path.rglob
        original_stat = Path.stat

        def counting_read_text(path, *args, **kwargs):
            counters.read_text += 1
            return original_read_text(path, *args, **kwargs)

        def counting_rglob(path, *args, **kwargs):
            counters.rglob += 1
            return original_rglob(path, *args, **kwargs)

        def counting_stat(path, *args, **kwargs):
            counters.stat += 1
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", counting_read_text)
        monkeypatch.setattr(Path, "rglob", counting_rglob)
        monkeypatch.setattr(Path, "stat", counting_stat)

    def as_dict(self) -> dict[str, int]:
        """The counters as a plain dict."""
        return {
            "read_text": self.read_text,
            "rglob": self.rglob,
            "stat": self.stat,
        }


# -- the fixtures --------------------------------------------------------


def _hot_body(name: str) -> str:
    """A page body that makes the rules report."""
    return (
        f"# {name}\n\n"
        "## Sources\n\n"
        "[Source](https://example.invalid/r1) "
        "[Source 2](https://example.invalid/r2)\n\n"
        "The first assertion line is definitely long enough to count as "
        "an unsourced claim about the organisation.\n\n"
        "The second assertion line is definitely long enough to count as "
        "an unsourced claim about the organisation.\n\n"
        "The third assertion line is definitely long enough to count as "
        "an unsourced claim about the organisation.\n\n"
        "Kubernetes adoption is growing everywhere.\n\n"
        "The organisation reported growth in 2015 during the period.\n"
    )


def _hot_source_body(name: str) -> str:
    """A source summary page without a wikilink -> an isolated source."""
    return f"# {name}\n\nA summary of the raw file {name} without a reference.\n"


def _build_hot_wiki(root: Path):
    """The cold fixture with page contents that trigger the rules.

    The shape is the cold one (151 pages, 14 source summary pages, 8
    raw files) -- only the content differs: the pages carry the markers
    the rules look for, so every rule stops as soon as it has
    ``max_results`` issues.
    """
    wiki = _build_cold_wiki(root)
    sources_dir = wiki.wiki_dir / "sources"
    for page in wiki._wiki_pages():
        if page.is_relative_to(sources_dir):
            page.write_text(_hot_source_body(page.stem), encoding="utf-8")
        else:
            page.write_text(_hot_body(page.stem), encoding="utf-8")
    return wiki


# -- the measurement -----------------------------------------------------


def _measure(monkeypatch, wiki, with_snapshot: bool) -> dict[str, int]:
    """Count the filesystem calls of one lint run.

    The caliber is the one of the gate: ``_scan_all_pages`` plus
    ``_run_all_rules``. ``_build_lint_context`` is not part of it (it
    is outside the gate, design §14 R-1).
    """
    counters = _Counters()
    with monkeypatch.context() as patch:
        counters.install(patch)
        analyzer = wiki._analyzer
        if with_snapshot:
            snapshot = WikiPageSource(wiki).snapshot()
            analyzer._scan_all_pages(snapshot)
            analyzer._run_all_rules(snapshot)
        else:
            analyzer._scan_all_pages()
            analyzer._run_all_rules()
    return counters.as_dict()


def _measure_cold(monkeypatch, root: Path, with_snapshot: bool) -> dict[str, int]:
    """Measure the cold caliber on a fresh wiki.

    A fresh wiki per measurement: the relation engine reads ``wiki.md``
    once per instance and the rules keep state, so the two paths must
    not share a wiki.
    """
    wiki = _build_cold_wiki(root)
    try:
        return _measure(monkeypatch, wiki, with_snapshot)
    finally:
        wiki.close()


def _measure_hot(monkeypatch, root: Path, with_snapshot: bool) -> dict[str, int]:
    """Measure the hot caliber on a fresh wiki."""
    wiki = _build_hot_wiki(root)
    try:
        return _measure(monkeypatch, wiki, with_snapshot)
    finally:
        wiki.close()


def _report(label: str, counters: dict[str, int]) -> None:
    """Print the counters of one measurement (``-s``)."""
    print(
        f"\n[{label}] read_text={counters['read_text']} "
        f"rglob={counters['rglob']} stat={counters['stat']}"
    )


# -- the gate ------------------------------------------------------------


def test_cold_lint_counts_use_one_snapshot(tmp_path, monkeypatch):
    """The cold gate: 311 reads / 2 rglobs for the snapshot path.

    The analyzer builds the snapshot once and hands it to the scan and
    to the rules; the pages are read once instead of once per rule.
    The two remaining rglobs are the enumeration of the snapshot and
    the raw directory of the ``dated_claim`` rule.

    The legacy path (no snapshot) is measured in the same test: it is
    the "before" of the refactoring and must not move.

    R-7 (one ``stat`` per page) is gated in
    ``test_snapshot_stats_every_page`` — the *relative* stat count
    vs the legacy path is not a valid gate: the snapshot path also
    *saves* the ``Path.exists()`` stats of the consumers, so
    ``snapshot.stat - legacy.stat`` can be well below 151 even when
    every page is measured.
    """
    legacy = _measure_cold(monkeypatch, tmp_path / "cold_legacy", with_snapshot=False)
    snapshot = _measure_cold(monkeypatch, tmp_path / "cold_snapshot", with_snapshot=True)

    _report("cold lint, no snapshot", legacy)
    _report("cold lint", snapshot)

    assert snapshot["read_text"] <= COLD_READ_TEXT_MAX
    assert snapshot["rglob"] <= COLD_RGLOB_MAX
    assert legacy["read_text"] == LEGACY_READ_TEXT, "the legacy path must be untouched"
    assert legacy["rglob"] == LEGACY_RGLOB
    # R-7 absolute floor: the run must pay at least one metadata probe
    # per page (the snapshot's stat); the exact net vs legacy is not
    # asserted here (see the docstring).
    assert snapshot["stat"] >= SNAPSHOT_STAT_PER_PAGE


def test_snapshot_stats_every_page(tmp_path, monkeypatch):
    """R-7: the snapshot measures every page (``Path.stat``) before reading it.

    Measured on ``WikiPageSource.snapshot()`` alone so the count is
    not polluted by the consumers' ``Path.exists()`` calls (which
    Python 3.12 implements via ``stat``).
    """
    wiki = _build_cold_wiki(tmp_path / "stat_only")
    try:
        n_pages = len(list(wiki._wiki_pages()))
        assert n_pages == 151, "the cold fixture must stay 151 pages"

        counters = _Counters()
        with monkeypatch.context() as patch:
            counters.install(patch)
            snap = WikiPageSource(wiki).snapshot()
        _report("snapshot() only", counters.as_dict())

        assert len(snap.names) == n_pages
        assert counters.stat >= n_pages, (
            "the snapshot measures the size of every page before reading it "
            "(design §14 R-7)"
        )
        assert counters.read_text == n_pages, "one read per cached page"
    finally:
        wiki.close()


def test_hot_lint_counts(tmp_path, monkeypatch):
    """The hot caliber: the rules break as soon as they have enough.

    The snapshot path pays the same price as in the cold caliber (it
    reads every page once, up front), the legacy path reads less (the
    rules stop at ``max_results``). The numbers are printed for the
    benchmarker; the gate itself is the cold caliber.
    """
    legacy = _measure_hot(monkeypatch, tmp_path / "hot_legacy", with_snapshot=False)
    snapshot = _measure_hot(monkeypatch, tmp_path / "hot_snapshot", with_snapshot=True)

    _report("hot lint, no snapshot", legacy)
    _report("hot lint", snapshot)

    assert snapshot["read_text"] <= COLD_READ_TEXT_MAX
    assert snapshot["rglob"] <= COLD_RGLOB_MAX
    assert legacy["read_text"] <= LEGACY_READ_TEXT
    assert legacy["rglob"] == LEGACY_RGLOB, "the rglobs do not depend on the content"
    assert snapshot["stat"] >= SNAPSHOT_STAT_PER_PAGE
