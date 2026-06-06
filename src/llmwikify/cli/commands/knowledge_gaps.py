"""``knowledge_gaps`` command — detect knowledge gaps, outdated pages, redundancy."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command


def run_knowledge_gaps(wiki: Any, args: Any) -> int:
    """Detect knowledge gaps and outdated pages.

    Args:
        wiki: A Wiki instance (or any object with ``lint(generate_investigations=True)``).
        args: Parsed argparse Namespace with optional ``json``.

    Returns:
        0 on success.
    """
    as_json = getattr(args, "json", False)

    result = wiki.lint(generate_investigations=True)

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    investigations = result.get("investigations", {})

    print("=== Knowledge Gap Analysis ===\n")
    print(f"Total pages: {result['total_pages']}")
    print(f"Total issues: {result['issue_count']}")
    print()

    # Outdated pages
    outdated = investigations.get("outdated_pages", [])
    if outdated:
        print(f"📅 Potentially Outdated Pages ({len(outdated)})")
        for page in outdated:
            print(f"  • {page['page']} (latest: {page.get('latest_year_mentioned', 'unknown')})")
        print()
    else:
        print("✅ No outdated pages detected")
        print()

    # Knowledge gaps
    gaps = investigations.get("knowledge_gaps", [])
    if gaps:
        print(f"🔍 Knowledge Gaps ({len(gaps)})")
        for gap in gaps:
            print(f"  • {gap['observation']}")
        print()
    else:
        print("✅ No knowledge gaps detected")
        print()

    # Redundancy alerts
    redundancy = investigations.get("redundancy_alerts", [])
    if redundancy:
        print(f"⚠️ Redundancy Alerts ({len(redundancy)})")
        for alert in redundancy:
            print(f"  • {alert['observation']}")
        print()
    else:
        print("✅ No redundancy detected")
        print()

    # Contradictions
    contradictions = investigations.get("contradictions", [])
    if contradictions:
        print(f"❌ Contradictions ({len(contradictions)})")
        for contra in contradictions:
            print(f"  • {contra.get('observation', contra.get('type', 'unknown'))}")
        print()

    return 0


class KnowledgeGapsCommand(Command):
    """``knowledge_gaps`` command — detect knowledge gaps."""

    name = "knowledge-gaps"
    help = "Detect knowledge gaps, outdated pages, and redundancy"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("--json", action="store_true", help="Output as JSON")
        p.add_argument(
            "--include-suggestions", "-s", action="store_true",
            help="Include suggested sources to fill gaps",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_knowledge_gaps(wiki, args)
