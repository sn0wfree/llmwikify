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

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..wiki import Wiki


class Rule:
    """Base class for a lint rule.

    Subclasses override:
    - ``name`` (str): the issue-type string this rule produces
    - ``run(wiki) -> list[dict]``: the detection logic

    Subclasses MAY override:
    - ``__doc__``: a short description of what the rule detects
    """

    name: str = ""

    def run(self, wiki: "Wiki") -> list[dict[str, Any]]:
        """Run this rule against ``wiki`` and return any issues found.

        Returns:
            A list of issue dicts. Each dict is a free-form structure
            consumed by the LLM/CLI for display. Common keys:
            ``type`` (str), ``page`` (str), ``file`` (str),
            ``observation`` (str, human-readable).
        """
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

    def __init__(self, wiki: "Wiki", rules: list[Rule] | None = None) -> None:
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

    def run_all(self) -> list[dict[str, Any]]:
        """Run every registered rule, return aggregated issues.

        Rules run in name-sorted order (deterministic for tests).
        Each rule's returned list is concatenated. If a rule
        raises, the error is logged and the rule is skipped
        (so one buggy rule doesn't crash the entire lint).
        """
        import logging

        logger = logging.getLogger(__name__)

        all_issues: list[dict[str, Any]] = []
        for name in self.rule_names:
            try:
                all_issues.extend(self._rules[name].run(self.wiki))
            except Exception as e:
                logger.warning("lint rule %r failed: %s", name, e)
        return all_issues

    def run_rule(self, name: str) -> list[dict[str, Any]]:
        """Run a specific rule by name. Returns [] if the rule is unknown."""
        if name not in self._rules:
            return []
        return self._rules[name].run(self.wiki)
