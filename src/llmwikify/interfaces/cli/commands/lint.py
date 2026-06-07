"""``lint`` command — health check (full / brief / recommendations / json)."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command


def _lint_full(result: dict) -> int:
    """Full health check output."""
    print("=== Wiki Health Check ===")
    print(f"Total pages: {result['total_pages']}")
    print(f"Issues found: {result['issue_count']}")

    if result["issues"]:
        by_type: dict[str, int] = {}
        for issue in result["issues"]:
            t = issue.get("type") or issue.get("issue_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        print("\nBy type:")
        for t, count in sorted(by_type.items()):
            print(f"  {t}: {count}")

        print("\nFirst 20 issues:")
        for issue in result["issues"][:20]:
            issue_type = issue.get("type") or issue.get("issue_type", "unknown")
            page = issue.get("page", "unknown")
            message = issue.get("message", "")
            print(f"  ❌ [{issue_type}] {page}: {message}")

    # P1.2: Show investigations
    inv = result.get("investigations", {})
    if inv:
        print("\n=== Investigations ===")

        contradictions = inv.get("contradictions", [])
        if contradictions:
            print(f"\n❌ Contradictions ({len(contradictions)}):")
            for c in contradictions[:3]:
                print(f"  • {c.get('observation', c.get('type', 'unknown'))[:100]}")

        data_gaps = inv.get("data_gaps", [])
        if data_gaps:
            print(f"\n🔍 Data Gaps ({len(data_gaps)}):")
            for g in data_gaps[:3]:
                print(f"  • {g.get('observation', g.get('type', 'unknown'))[:100]}")

        outdated = inv.get("outdated_pages", [])
        if outdated:
            print(f"\n📅 Outdated Pages ({len(outdated)}):")
            for o in outdated[:3]:
                print(f"  • {o.get('observation', o.get('page', 'unknown'))[:100]}")

        gaps = inv.get("knowledge_gaps", [])
        if gaps:
            print(f"\n🔍 Knowledge Gaps ({len(gaps)}):")
            for g in gaps[:3]:
                print(f"  • {g.get('observation', g.get('type', 'unknown'))[:100]}")

        redundancy = inv.get("redundancy_alerts", [])
        if redundancy:
            print(f"\n⚠️ Redundancy ({len(redundancy)}):")
            for r in redundancy[:3]:
                print(f"  • {r.get('observation', r.get('type', 'unknown'))[:100]}")

    if result["issues"]:
        return 1
    else:
        print("\n✅ All healthy!")

    # Show auto-fix results
    auto_fix = result.get("auto_fix", {})
    if auto_fix:
        print("\n=== Auto-Fix Results ===")
        wl_fixed = auto_fix.get("wikilinks_fixed", 0)
        wl_skipped = auto_fix.get("wikilinks_skipped", 0)
        wl_ambig = auto_fix.get("wikilinks_ambiguous", 0)
        idx_updated = auto_fix.get("index_updated", False)
        print(f"  Wikilinks fixed: {wl_fixed}")
        if wl_skipped:
            print(f"  Wikilinks skipped: {wl_skipped}")
        if wl_ambig:
            print(f"  Ambiguous matches: {wl_ambig}")
        if idx_updated:
            print("  Index updated: ✅ (summaries refreshed, pages grouped)")

    return 0


def _lint_brief(result: dict) -> int:
    """Brief suggestions output (replaces old `hint` command)."""
    hints = []
    for hint_type in ("critical", "informational"):
        for h in result.get("hints", {}).get(hint_type, []):
            priority = "high" if hint_type == "critical" else "medium"
            hints.append({"priority": priority, "message": h.get("message", "")})

    for issue in result.get("issues", []):
        if issue.get("type") == "orphan_page":
            hints.append({
                "priority": "medium",
                "message": f"Orphan page: [[{issue.get('page', '')}]]",
            })
        elif issue.get("type") == "broken_link":
            hints.append({
                "priority": "high",
                "message": f"Broken link in {issue.get('page', '')} → [[{issue.get('link', '')}]]",
            })

    print("=== Wiki Suggestions ===\n")
    if hints:
        for hint in hints[:10]:
            priority_icon = {
                "high": "🔴",
                "medium": "🟡",
                "low": "🟢",
            }.get(hint["priority"], "•")
            print(f"{priority_icon} [{hint['priority'].upper()}] {hint['message']}\n")
    else:
        print("✅ Wiki looks healthy! No suggestions.\n")

    print(f"Summary: {len(hints)} suggestion(s)")
    return 0


def _lint_recommendations(result: dict) -> int:
    """Missing pages and orphan pages output (replaces old `recommend` command)."""
    # Extract missing pages from hints
    missing_pages = []
    for h in result.get("hints", {}).get("critical", []):
        if "referenced but" in h.get("message", ""):
            msg = h.get("message", "")
            parts = msg.split(": ")
            if len(parts) > 1:
                for name in parts[1].split(", "):
                    missing_pages.append({"page": name.strip()})

    # Extract orphan pages from issues
    orphan_pages = []
    for issue in result.get("issues", []):
        if issue.get("type") == "orphan_page":
            orphan_pages.append({"page": issue.get("page", "")})

    # Also check lint hints for missing cross-refs
    for h in result.get("hints", {}).get("informational", []):
        msg = h.get("message", "")
        if "missing" in msg.lower() and "page" in msg.lower():
            parts = msg.split(": ")
            if len(parts) > 1:
                for name in parts[1].split(", "):
                    name = name.strip()
                    if name and not any(m["page"] == name for m in missing_pages):
                        missing_pages.append({"page": name})

    print("=== Wiki Recommendations ===\n")

    if missing_pages:
        print(f"🔴 Missing Pages ({len(missing_pages)})\n")
        for rec in missing_pages[:10]:
            print(f"   • [[{rec['page']}]]")
        print()
    else:
        print("✅ No missing pages\n")

    if orphan_pages:
        print(f"🟠 Orphan Pages ({len(orphan_pages)})\n")
        for rec in orphan_pages[:10]:
            print(f"   • [[{rec['page']}]]")
        print()
    else:
        print("✅ No orphan pages\n")

    return 0


def run_lint(wiki: Any, args: Any) -> int:
    """Run a health check on the wiki.

    Args:
        wiki: A Wiki instance (or any object with ``lint(mode, limit, force, generate_investigations)``).
        args: Parsed argparse Namespace with ``format``, ``mode``, ``limit``,
            ``force``, ``generate_investigations``.

    Returns:
        0 on healthy, 1 on issues found (or format-specific codes).
    """
    generate_inv = getattr(args, "generate_investigations", False)
    fmt = getattr(args, "format", "full")
    mode = getattr(args, "mode", "check")
    limit = getattr(args, "limit", 10)
    force = getattr(args, "force", False)
    result = wiki.lint(
        mode=mode, limit=limit, force=force,
        generate_investigations=generate_inv,
    )

    if fmt == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    elif fmt == "brief":
        return _lint_brief(result)
    elif fmt == "recommendations":
        return _lint_recommendations(result)
    else:
        return _lint_full(result)


class LintCommand(Command):
    """``lint`` command — health check."""

    name = "lint"
    help = "Health check"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--format", "-f",
            choices=["full", "brief", "recommendations", "json"],
            default="full", help="Output format (default: full)",
        )
        p.add_argument(
            "--generate-investigations", "-g", action="store_true",
            help="Use LLM to generate investigation suggestions",
        )
        p.add_argument(
            "--mode", choices=["check", "fix"], default="check",
            help="Lint mode: check (default) or fix",
        )
        p.add_argument(
            "--limit", "-l", type=int, default=10,
            help="Max LLM-detected issues to return (default: 10)",
        )
        p.add_argument("--force", action="store_true", help="Force re-detection (ignore cache)")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_lint(wiki, args)
