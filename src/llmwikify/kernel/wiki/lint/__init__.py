"""Lint rule base class and LintEngine aggregator.

Phase 1 #3 — extract the 8 ``_detect_X`` rule methods from
``WikiAnalyzer`` (929 LOC) into small, focused rule classes
under ``llmwikify.kernel.wiki.lint.rules``. ``LintEngine`` runs all
rules and aggregates their results, replacing the inline
detection logic in ``WikiAnalyzer.lint()``.

Design notes
------------

Each rule is a single class that:
- knows its ``name`` (used as the issue-type string)
- has a single ``run(wiki) -> list[dict]`` method
- returns 0+ hint dicts (empty list = no issues)

The ``LintEngine`` owns the rule registry and the wiki. It
exposes:
- ``LintEngine(wiki)``
- ``LintEngine.run_all()`` — run every rule, return aggregated list
- ``LintEngine.run_rule(name)`` — run a specific rule

``WikiAnalyzer`` becomes a thin orchestrator: it calls
``LintEngine`` to get rule results, then composes them with
its other concerns (LLM-based investigations, sink warnings,
broken-link and orphan detection, etc.).

The ``Rule`` base class is intentionally minimal — no abstract
``__init__``, no plugin discovery. New rules are added by
writing a new file in ``rules/`` and importing it in
``rules/__init__.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from ..snapshot import PageSnapshot

if TYPE_CHECKING:
    from ..wiki import Wiki


def _is_query_page(name: str) -> bool:
    """True when a display name belongs to a query page.

    Mirrors the inline predicate of ``Rule._iter_pages`` and
    ``CrossPageRule._load_pages`` verbatim. The check is platform
    dependent -- on Windows the path codec maps ``:`` to a full width
    ``：``, so the prefix never matches -- therefore it stays with the
    consumers: the snapshot keeps every page.
    """
    return name.startswith("Query:")


class Rule:
    """Base class for a per-page lint rule.

    Subclasses override:
    - ``name`` (str): the issue-type string this rule produces
    - ``detect(page_name, content, wiki, results)``: per-page detection logic

    Subclasses MAY override:
    - ``max_results`` (int): max issues to return (default 3)
    - ``_iter_pages(wiki)``: custom page iteration (default: skip Query: pages)
    - ``__doc__``: a short description of what the rule detects

    A rule that reads its pages in its own way (it overrides ``run()``
    or ``_iter_pages()``) must declare ``snapshot_mode = "custom"`` and
    own ``run_with_snapshot()`` as well. The declaration replaces a
    reflection check that used to decide this silently: a rule author
    who overrode ``run()`` without knowing about the reflection lost
    the page-snapshot optimisation without any error.
    """

    name: str = ""
    max_results: int = 3

    #: How the rule reads its pages.
    #:
    #: ``"template"`` — the generic per-page template; the rule only
    #: implements ``detect()`` and works against a page snapshot out of
    #: the box.
    #: ``"custom"`` — the rule implements its own ``run()``; it owns
    #: ``run_with_snapshot()`` as well.
    snapshot_mode: ClassVar[str] = "template"

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        """Run this rule against ``wiki`` and return any issues found.

        Template method: checks wiki_dir, iterates pages, calls detect().
        """
        if not wiki.wiki_dir.exists():
            return []
        results: list[dict[str, Any]] = []
        for page in self._iter_pages(wiki):
            page_name = wiki._page_display_name(page)
            content = wiki._backend.get_page(page_name) or ""
            self.detect(page_name, content, wiki, results)
            if len(results) >= self.max_results:
                break
        return results[: self.max_results]

    def run_with_snapshot(
        self, wiki: Wiki, snapshot: PageSnapshot | None = None
    ) -> list[dict[str, Any]]:
        """Run this rule against ``wiki``, taking the pages from a snapshot.

        ``snapshot is None`` runs the legacy path (``self.run(wiki)``),
        so every existing caller keeps its behaviour. With a snapshot
        the pages are read from the snapshot instead of from disk; a
        page that was left out of the snapshot (memory budget) is read
        back from its path, so the checked pages do not change.

        A rule with ``snapshot_mode = "custom"`` owns this method; the
        generic template below only applies to the template rules.
        """
        if snapshot is None:
            return self.run(wiki)
        if self.snapshot_mode != "template":
            # The rule reads its pages in its own way: only the rule
            # knows how to replay that.
            return self.run(wiki)
        if not wiki.wiki_dir.exists():
            return []
        results: list[dict[str, Any]] = []
        for name in snapshot.names:
            if _is_query_page(name):
                continue
            content = snapshot.content_of(name)
            if content is None:
                # Degraded page: it did not fit into the snapshot, read
                # it back from disk (same read as the legacy path).
                content = wiki._backend.get_page(name) or ""
            self.detect(name, content, wiki, results)
            if len(results) >= self.max_results:
                break
        return results[: self.max_results]

    def _iter_pages(self, wiki: Wiki):
        """Yield non-Query pages. Override for custom iteration."""
        for page in wiki._wiki_pages():
            if not wiki._page_display_name(page).startswith("Query:"):
                yield page

    def detect(
        self,
        page_name: str,
        content: str,
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        """Detect issues in a single page. Append to results."""
        raise NotImplementedError


class CrossPageRule(Rule):
    """Base class for rules that need all pages loaded first.

    Subclasses override:
    - ``detect_all(pages, wiki, results)``: cross-page analysis logic

    The ``pages`` dict is ``{page_name: content}`` for all non-Query pages.
    """

    def run(self, wiki: Wiki) -> list[dict[str, Any]]:
        """Run this rule against ``wiki`` and return any issues found.

        Template method: loads all pages, then calls detect_all().
        """
        if not wiki.wiki_dir.exists():
            return []
        pages = self._load_pages(wiki)
        results: list[dict[str, Any]] = []
        self.detect_all(pages, wiki, results)
        return results[: self.max_results]

    def run_with_snapshot(
        self, wiki: Wiki, snapshot: PageSnapshot | None = None
    ) -> list[dict[str, Any]]:
        """Run this rule against ``wiki``, taking the pages from a snapshot.

        ``snapshot is None`` runs the legacy path (``self.run(wiki)``),
        so every existing caller keeps its behaviour.
        """
        if snapshot is None:
            return self.run(wiki)
        if self.snapshot_mode != "template":
            # The rule overrides run(): the generic template must not
            # bypass it.
            return self.run(wiki)
        if not wiki._backend.dir_exists("wiki"):
            return []
        pages = self._pages_from_snapshot(wiki, snapshot)
        results: list[dict[str, Any]] = []
        self.detect_all(pages, wiki, results)
        return results[: self.max_results]

    def _load_pages(self, wiki: Wiki) -> dict[str, str]:
        """Load all non-Query pages into a dict (utf-8, lossy on bad bytes)."""
        pages: dict[str, str] = {}
        for page in wiki._wiki_pages():
            name = wiki._page_display_name(page)
            if not name.startswith("Query:"):
                pages[name] = wiki._backend.get_page(name) or ""
        return pages

    def _pages_from_snapshot(
        self, wiki: Wiki, snapshot: PageSnapshot
    ) -> dict[str, str]:
        """Snapshot -> ``{display_name: content}``, the shape of ``_load_pages``.

        The filter is the one of ``_load_pages``, verbatim: a display
        name that starts with ``Query:`` is skipped. A page that is not
        cached in the snapshot (memory budget) is read back from disk.
        """
        pages: dict[str, str] = {}
        for name in snapshot.names:
            if _is_query_page(name):
                continue
            content = snapshot.content_of(name)
            if content is None:
                content = wiki._backend.get_page(name) or ""
            pages[name] = content
        return pages

    def detect_all(
        self,
        pages: dict[str, str],
        wiki: Wiki,
        results: list[dict[str, Any]],
    ) -> None:
        """Detect issues across all pages. Append to results."""
        raise NotImplementedError


class LintEngine:
    """Runs all registered rules against a Wiki and aggregates results.

    Usage::

        engine = LintEngine(wiki)
        all_issues = engine.run_all()
        dated_issues = engine.run_rule("dated_claim")

    Rules are passed in at construction time (so the engine has
    no plugin-discovery magic). The default rule set is the
    8 rules extracted from WikiAnalyzer — see
    ``core.lint.rules.RULES``.
    """

    def __init__(self, wiki: Wiki, rules: list[Rule] | None = None) -> None:
        self.wiki = wiki
        self._rules: dict[str, Rule] = {}
        for rule in rules or []:
            if not rule.name:
                raise ValueError(f"rule {rule!r} has no name")
            if rule.name in self._rules:
                raise ValueError(f"duplicate rule name: {rule.name}")
            self._rules[rule.name] = rule

    @property
    def rule_names(self) -> list[str]:
        """Return the sorted list of registered rule names."""
        return sorted(self._rules.keys())

    def run_all(self, snapshot: PageSnapshot | None = None) -> list[dict[str, Any]]:
        """Run every registered rule, return aggregated issues.

        Rules run in name-sorted order (deterministic for tests).
        Cross-page rules share one ``{name: content}`` load so each
        does not re-read the whole wiki.

        With a snapshot the rules take their pages from it (the whole
        run reads every page once); without one the legacy path is
        taken unchanged.
        """
        import logging

        logger = logging.getLogger(__name__)

        all_issues: list[dict[str, Any]] = []
        shared_pages: dict[str, str] | None = None
        for name in self.rule_names:
            rule = self._rules[name]
            try:
                if snapshot is not None:
                    # The rules read their pages from the snapshot; the
                    # two cross page rules share it like they shared
                    # ``shared_pages`` before.
                    all_issues.extend(self._run_with_snapshot(rule, snapshot))
                elif isinstance(rule, CrossPageRule):
                    if shared_pages is None:
                        shared_pages = rule._load_pages(self.wiki)
                    results: list[dict[str, Any]] = []
                    rule.detect_all(shared_pages, self.wiki, results)
                    all_issues.extend(results[: rule.max_results])
                else:
                    all_issues.extend(rule.run(self.wiki))
            except Exception as e:
                logger.warning("lint rule %r failed: %s", name, e)
        return all_issues

    def run_rule(
        self, name: str, snapshot: PageSnapshot | None = None
    ) -> list[dict[str, Any]]:
        """Run a specific rule by name. Returns [] if the rule is unknown.

        Without a snapshot the legacy path is taken: a single rule must
        not pay for a full page snapshot.
        """
        if name not in self._rules:
            return []
        rule = self._rules[name]
        if snapshot is None:
            return rule.run(self.wiki)
        return self._run_with_snapshot(rule, snapshot)

    def _run_with_snapshot(
        self, rule: Rule, snapshot: PageSnapshot
    ) -> list[dict[str, Any]]:
        """Run one rule with the page snapshot of the current lint run.

        The rule takes its pages from the snapshot. A rule without the
        snapshot entry point (there is none today, but the engine does
        not rely on it) falls back to the legacy path, so the issues
        stay the same.
        """
        runner = getattr(rule, "run_with_snapshot", None)
        if runner is None:
            return rule.run(self.wiki)
        return runner(self.wiki, snapshot)
