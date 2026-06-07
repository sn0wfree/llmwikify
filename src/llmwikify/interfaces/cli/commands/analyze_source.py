"""``analyze_source`` command — analyze source files and cache extraction."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command
from .._output import print_error


def run_analyze_source(wiki: Any, args: Any) -> int:
    """Analyze a single source or all sources in raw/.

    Args:
        wiki: A Wiki instance (or any object with ``raw_dir``, ``root``,
            and ``analyze_source(source, force)``).
        args: Parsed argparse Namespace with optional ``source``,
            ``all``, ``force``.

    Returns:
        0 on success (with no failures), 1 on errors.
    """
    if getattr(args, "all", False):
        # Batch analyze all sources
        sources = list(wiki.raw_dir.rglob("*")) if wiki.raw_dir.exists() else []
        sources = [f for f in sources if f.is_file()]

        if not sources:
            print("No source files found in raw/")
            return 0

        analyzed = 0
        failed = 0
        skipped = 0
        force = getattr(args, "force", False)

        for i, f in enumerate(sources, 1):
            rel = str(f.relative_to(wiki.root))
            print(f"[{i}/{len(sources)}] Analyzing: {rel}...", end=" ")

            try:
                result = wiki.analyze_source(rel, force=force)
                status = result.get("status", "success")
                if status == "skipped":
                    print(f"skipped ({result.get('reason', 'unknown')})")
                    skipped += 1
                elif status == "error":
                    print(f"failed ({result.get('reason', 'unknown')})")
                    failed += 1
                else:
                    entities = len(result.get("entities", []))
                    suggested = len(result.get("suggested_pages", []))
                    print(f"done (entities: {entities}, suggested: {suggested})")
                    analyzed += 1
            except Exception as e:
                print(f"error: {e}")
                failed += 1

        print(f"\nSummary: {analyzed} analyzed, {skipped} skipped, {failed} failed")
        return 0 if failed == 0 else 1
    else:
        # Single source
        source_path = args.source
        if not source_path:
            print_error("specify a source path or use --all")
            return 1

        result = wiki.analyze_source(
            source_path, force=getattr(args, "force", False) if hasattr(args, "force") else False
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in ("error", "skipped") else 1


class AnalyzeSourceCommand(Command):
    """``analyze_source`` command — analyze source files."""

    name = "analyze-source"
    help = "Analyze source and cache extraction results"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("source", nargs="?", help="Source path (e.g., raw/article.md)")
        p.add_argument("--all", "-a", action="store_true", help="Analyze all sources")
        p.add_argument("--force", "-f", action="store_true", help="Force re-analysis")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_analyze_source(wiki, args)
