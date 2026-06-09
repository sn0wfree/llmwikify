"""``init`` command — initialize a wiki at a given root."""

from __future__ import annotations

from typing import Any

from .._base import Command
from .._output import ICON_SUCCESS, ICON_WARNING, print_success, print_warning


def run_init(wiki: Any, wiki_root: Any, args: Any) -> int:
    """Initialize a wiki at ``wiki_root``.

    Args:
        wiki: A Wiki instance (or any object with ``init(overwrite, agent, force, merge)``).
        wiki_root: The wiki root path (used only for display in the
            "already exists" message; wiki.init() reads from
            its own internal root).
        args: Parsed argparse Namespace with ``overwrite``, ``agent``,
            ``force``, ``merge``.

    Returns:
        0 on success or "already exists", 1 on invalid agent.
    """
    from llmwikify.kernel.wiki.wiki import VALID_AGENTS

    overwrite = getattr(args, "overwrite", False)
    agent = getattr(args, "agent", None)
    force = getattr(args, "force", False)
    merge = getattr(args, "merge", False)

    if agent and agent not in VALID_AGENTS:
        print(f"Error: Invalid agent type '{agent}'.")
        print(f"  Choose: {', '.join(VALID_AGENTS)}")
        print("  Example: llmwikify init --agent opencode")
        return 1

    result = wiki.init(overwrite=overwrite, agent=agent, force=force, merge=merge)

    if result["status"] == "already_exists":
        print_warning(f"Wiki already initialized at {wiki_root}")
        print(f"   Existing files: {', '.join(result['existing_files'])}")
        if agent:
            print("   Use --force to overwrite or --merge to regenerate MCP config.")
        else:
            print("   Use --overwrite to reinitialize.")
        return 0

    if result["status"] == "mcp_config_added":
        print_success(f"MCP config added to existing wiki at {wiki_root}")
        if result["created_files"]:
            print(f"   Added: {', '.join(result['created_files'])}")
        warnings = result.get("warnings", [])
        if warnings:
            for w in warnings:
                print_warning(f"{w}")
        return 0

    print_success(result["message"])
    print()

    if result["created_files"]:
        print(f"  Created: {', '.join(result['created_files'])}")
    if result["skipped_files"]:
        print(f"  Skipped: {', '.join(result['skipped_files'])}")

    warnings = result.get("warnings", [])
    if warnings:
        print()
        for w in warnings:
            print_warning(f"{w}")

    raw_stats = result.get("raw_stats", {})
    if raw_stats and raw_stats.get("total", 0) > 0:
        print()
        print("  Source analysis:")
        print(
            f"    {raw_stats['total']} files in "
            f"{len(raw_stats.get('categories', {}))} categories"
        )
        top_cats = sorted(
            raw_stats.get("categories", {}).items(), key=lambda x: -x[1]
        )[:5]
        print(f"    Top: {', '.join(f'{k} ({v})' for k, v in top_cats)}")

    print()
    print("  Next steps:")
    if agent:
        print("    1. Review wiki.md for page conventions")
        if agent == "opencode":
            print("    2. Run: opencode")
        elif agent == "claude":
            print("    2. Run: claude")
        elif agent == "codex":
            print("    2. Run: opencode (codex mode)")
        print("    3. Tell the agent: 'Start ingesting news from raw/'")
    else:
        print("    Run: llmwikify init --agent <opencode|claude|codex|generic> for full setup")

    return 0


class InitCommand(Command):
    """``init`` command — initialize a wiki."""

    name = "init"
    help = "Initialize wiki"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--overwrite", action="store_true",
            help="Recreate index.md and log.md if they exist",
        )
        p.add_argument(
            "--agent", type=str,
            choices=["opencode", "claude", "codex", "generic"],
            help="Generate agent-specific config files (required for MCP setup)",
        )
        p.add_argument(
            "--force", action="store_true",
            help="Overwrite existing files without prompting",
        )
        p.add_argument(
            "--merge", action="store_true",
            help="Merge into existing wiki.md instead of skipping",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        # The init command needs wiki_root for display, not just the wiki.
        # Wiki holds its own root internally, but we need it in run_init
        # for the "already initialized" message. The wiki's root is
        # the simplest way to get it.
        return run_init(wiki, wiki.root, args)
