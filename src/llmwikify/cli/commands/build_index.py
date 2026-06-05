"""``build_index`` command — build or export the reference index."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import ICON_PENDING, print_warning

logger = logging.getLogger(__name__)


def run_build_index(wiki: Any, args: Any) -> int:
    """Build or export the reference index.

    Args:
        wiki: A Wiki instance.
        args: Parsed argparse Namespace with ``no_export``, ``output``,
            ``export_only``, ``force``.

    Returns:
        0 on success.
    """
    no_export = getattr(args, "no_export", False)
    output = getattr(args, "output", None)
    export_only = getattr(args, "export_only", False)
    force = getattr(args, "force", False)
    output_path = Path(output) if output else None

    if export_only:
        print("=== Exporting Reference Index ===")
        result = wiki.export_index(output_path or wiki.ref_index_path)
        print("\n=== Export Complete ===")
        print(f"Pages: {result['total_pages']}")
        print(f"Links: {result['total_links']}")
        print(f"Output: {output_path or wiki.ref_index_path}")
        return 0

    # Auto-detect and migrate old index format
    if _detect_old_index_format(wiki):
        if not force:
            print_warning("Old index format detected. Migrating to new format automatically.")
            print("    (Use --force to skip this message in the future)")
        print()

    print("=== Building Reference Index ===")
    print(f"Scanning: {wiki.wiki_dir}")
    print()

    result = wiki.build_index(auto_export=not no_export, output_path=output_path)

    print()
    print("=== Index Built ===")
    print(f"Total pages: {result['total_pages']}")
    print(f"Total links: {result['total_links']}")
    print(f"{ICON_PENDING} Elapsed: {result.get('elapsed_seconds', 'N/A')}s")
    print(f"Speed: {result.get('files_per_second', 'N/A')} files/sec")

    return 0


def _detect_old_index_format(wiki: Any) -> bool:
    """Check if index contains pages with old-format page_names.

    Old format: page_name is bare name (e.g., "Risk Parity") while
    file_path has directory prefix (e.g., "concepts/Risk Parity.md").
    New format: page_name == file_path[:-3] (e.g., both are "concepts/Risk Parity").
    """
    if not wiki.is_initialized():
        return False
    try:
        cursor = wiki.index.conn.execute("SELECT page_name, file_path FROM pages")
        for row in cursor.fetchall():
            name = row["page_name"]
            fpath = row["file_path"]
            # New format: page_name == file_path without .md
            if name != fpath[:-3]:
                return True
    except Exception as e:
        logger.warning("Index format check failed: %s", e)
    return False


class BuildIndexCommand(Command):
    """``build_index`` command — build or export the reference index."""

    name = "build-index"
    help = "Build or export reference index"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--no-export", action="store_true",
            help="Skip JSON export",
        )
        p.add_argument("--output", "-o", help="JSON output path")
        p.add_argument(
            "--export-only", action="store_true",
            help="Export existing index without rebuilding",
        )
        p.add_argument(
            "--force", action="store_true",
            help="Force rebuild even if old format detected",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_build_index(wiki, args)
