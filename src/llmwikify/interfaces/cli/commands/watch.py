"""``watch`` command — watch raw/ directory for new files."""

from __future__ import annotations

import time
import warnings
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import print_error


def run_watch(wiki: Any, wiki_root: Path, args: Any) -> int:
    """Watch a directory for new files (raw/ by default).

    Args:
        wiki: A Wiki instance (used for FileSystemWatcher construction).
        wiki_root: Wiki root path (used for git-hook install location
            and as the default watch dir parent).
        args: Parsed argparse Namespace with ``dir``, ``auto_ingest``,
            ``self_create``, ``smart``, ``debounce``, ``dry_run``,
            ``git_hook``, ``uninstall_hook``.

    Returns:
        0 on success, 1 on errors.
    """
    from llmwikify.core.watcher import (
        FileSystemWatcher,
        install_git_hook,
        uninstall_git_hook,
    )

    # Handle git hook operations
    if getattr(args, "uninstall_hook", False):
        if uninstall_git_hook(wiki_root):
            return 0
        return 1

    if getattr(args, "git_hook", False):
        if install_git_hook(wiki_root):
            return 0
        return 1

    # Determine watch directory
    watch_dir = Path(args.dir) if args.dir else wiki_root / "raw"
    if not watch_dir.exists():
        print_error(f"Watch directory does not exist: {watch_dir}")
        return 1

    auto_ingest = getattr(args, "auto_ingest", False)
    self_create = getattr(args, "self_create", False) or getattr(args, "smart", False)
    if getattr(args, "smart", False):
        warnings.warn(
            "--smart is deprecated, use --self-create instead",
            DeprecationWarning,
            stacklevel=2,
        )
    debounce = getattr(args, "debounce", 2.0)
    dry_run = getattr(args, "dry_run", False)

    print("=== File Watcher ===")
    print(f"Watching: {watch_dir}")
    print(f"Auto-ingest: {'Yes' if auto_ingest else 'No (notify only)'}")
    print(f"Debounce: {debounce}s")
    print(f"Dry run: {'Yes' if dry_run else 'No'}")
    print()
    print("Press Ctrl+C to stop.")
    print()

    if dry_run:
        print("[DRY RUN] Would start watcher. Remove --dry-run to actually watch.")
        return 0

    watcher = FileSystemWatcher(
        watch_dir=watch_dir,
        auto_ingest=auto_ingest and not dry_run,
        self_create=self_create,
        debounce=debounce,
    )

    def on_event(event_type: str, path: Path) -> None:
        icon = {"created": "📄", "modified": "✏️", "deleted": "🗑️", "moved": "📥"}.get(event_type, "❓")
        print(f"{icon} [{event_type}] {path.name}")

    try:
        watcher.start(on_event=on_event)
        while watcher.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nWatcher stopped.")
    finally:
        watcher.stop()
        print(f"Stats: {watcher.stats['events']} events, {watcher.stats['ingests']} ingests")

    return 0


class WatchCommand(Command):
    """``watch`` command — watch raw/ directory for new files."""

    name = "watch"
    help = "Watch raw/ directory for new files"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("dir", nargs="?", default=None, help="Directory to watch (default: raw/)")
        p.add_argument("--auto-ingest", action="store_true", help="Automatically ingest new files")
        p.add_argument("--self-create", "-s", action="store_true", help="CLI uses LLM API to process files (requires --auto-ingest)")
        p.add_argument("--smart", action="store_true", help="[Deprecated] Alias for --self-create")
        p.add_argument("--debounce", type=float, default=2.0, help="Debounce time in seconds (default: 2)")
        p.add_argument("--dry-run", "-n", action="store_true", help="Only print events, do not ingest")
        p.add_argument("--git-hook", action="store_true", help="Install git post-commit hook instead of watching")
        p.add_argument("--uninstall-hook", action="store_true", help="Uninstall git post-commit hook")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        # watch needs wiki_root for the git hook and default dir
        return run_watch(wiki, wiki.root, args)
