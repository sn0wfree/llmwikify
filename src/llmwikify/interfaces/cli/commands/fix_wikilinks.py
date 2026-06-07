"""``fix_wikilinks`` command — fix broken wikilinks by adding directory prefix."""

from __future__ import annotations

from typing import Any

from .._base import Command
from .._output import ICON_SUCCESS, ICON_WARNING, print_warning


def run_fix_wikilinks(wiki: Any, args: Any) -> int:
    """Fix broken wikilinks in the wiki.

    Args:
        wiki: A Wiki instance (or any object with ``fix_wikilinks(dry_run)``).
        args: Parsed argparse Namespace with ``dry_run``.

    Returns:
        0 on success (no ambiguous), 1 if there are ambiguous links
        that need manual resolution.
    """
    dry_run = getattr(args, "dry_run", False)
    result = wiki.fix_wikilinks(dry_run=dry_run)

    mode = "DRY RUN" if dry_run else "FIXED"
    print(f"=== Wikilink Fix Summary ({mode}) ===")
    print(f"  Fixed:     {result['fixed']}")
    print(f"  Skipped:   {result['skipped']}")
    print(f"  Ambiguous: {result['ambiguous']}")

    if result["changes"]:
        print(f"\nChanges ({len(result['changes'])} total):")
        for c in result["changes"][:50]:
            if c["status"] == "fixed":
                print(f"  {ICON_SUCCESS} {c['page']}: {c['old']} → {c['new']}")
            elif c["status"] == "ambiguous":
                print_warning(
                    f"{c['page']}: [[{c['link']}]] matches "
                    f"{len(c['matches'])} pages: {', '.join(c['matches'])}"
                )

    if result["ambiguous"] > 0:
        print_warning(f"{result['ambiguous']} ambiguous link(s) require manual resolution.")
        return 1
    return 0


class FixWikilinksCommand(Command):
    """``fix_wikilinks`` command — fix broken wikilinks."""

    name = "fix-wikilinks"
    help = "Fix broken wikilinks by adding directory prefix"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--dry-run", "-n", action="store_true",
            help="Preview changes without modifying files",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_fix_wikilinks(wiki, args)
