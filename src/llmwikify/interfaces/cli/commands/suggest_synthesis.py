"""``suggest_synthesis`` command — cross-source synthesis suggestions."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command
from .._output import print_error


def run_suggest_synthesis(wiki: Any, args: Any) -> int:
    """Analyze sources and generate cross-source synthesis suggestions.

    Args:
        wiki: A Wiki instance (or any object with ``suggest_synthesis(source_name)``).
        args: Parsed argparse Namespace with optional ``source`` and ``json``.

    Returns:
        0 on success, 1 on error.
    """
    source = getattr(args, "source", None)
    as_json = getattr(args, "json", False)

    result = wiki.suggest_synthesis(source_name=source)

    if "error" in result:
        print_error(result["error"])
        return 1

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("=== Cross-Source Synthesis Suggestions ===\n")
    print(f"Sources analyzed: {result['sources_analyzed']}")
    print(f"Total suggestions: {result['total_suggestions']}")
    print()

    for i, suggestion in enumerate(result["suggestions"], 1):
        print(f"--- Source {i}: {suggestion['source_name']} ---")

        if suggestion.get("reinforced_claims"):
            print(f"\n  ✅ Reinforced Claims ({len(suggestion['reinforced_claims'])})")
            for claim in suggestion["reinforced_claims"][:3]:
                print(f"    • {claim['claim'][:80]}... (confirmed by {claim['confirmed_by_count']} source(s))")

        if suggestion.get("new_contradictions"):
            print(f"\n  ⚠️ Potential Contradictions ({len(suggestion['new_contradictions'])})")
            for contra in suggestion["new_contradictions"][:3]:
                print(f"    • {contra.get('contradiction', contra.get('new_claim', 'unknown'))[:80]}...")

        if suggestion.get("knowledge_gaps"):
            print(f"\n  🔍 Knowledge Gaps ({len(suggestion['knowledge_gaps'])})")
            for gap in suggestion["knowledge_gaps"][:3]:
                print(f"    • {gap['gap'][:80]}...")

        if suggestion.get("suggested_updates"):
            print(f"\n  📝 Suggested Updates ({len(suggestion['suggested_updates'])})")
            for update in suggestion["suggested_updates"][:3]:
                print(f"    • {update['page']}: {update['reason'][:60]}...")

        if suggestion.get("new_entities"):
            print(f"\n  🆕 New Entities ({len(suggestion['new_entities'])})")
            for entity in suggestion["new_entities"][:3]:
                print(f"    • {entity['name']} ({entity['type']})")

        print()

    print(f"\n{result['summary']}")
    return 0


class SuggestSynthesisCommand(Command):
    """``suggest_synthesis`` command — cross-source synthesis suggestions."""

    name = "suggest-synthesis"
    help = "Analyze sources and generate cross-source synthesis suggestions"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("source", nargs="?", default=None, help="Specific source to analyze (default: all unanalyzed sources)")
        p.add_argument("--json", action="store_true", help="Output as JSON")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_suggest_synthesis(wiki, args)
