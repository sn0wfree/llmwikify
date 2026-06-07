"""``wikis`` command — multi-wiki management (list / add / remove / scan)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .._base import Command
from .._output import print_error


def _wikis_list(config: dict, cli_config: Any) -> int:
    """List all registered wikis."""
    from llmwikify.foundation.config import get_wikis_config
    from llmwikify.core.wiki_registry import WikiRegistry

    wikis_config = get_wikis_config(config)
    registry = WikiRegistry(config)
    registry.initialize()

    wikis = registry.list_wikis()
    default_id = registry.get_default_wiki_id()

    if not wikis:
        print("No wikis registered.")
        print("\nTo add a wiki:")
        print("  llmwikify wikis add <wiki_id> --path /path/to/wiki")
        print("  llmwikify wikis scan .")
        return 0

    print(f"{'ID':<20} {'Name':<25} {'Type':<10} {'Pages':<10} {'Default':<10}")
    print("-" * 75)

    for wiki in wikis:
        is_default = "✓" if wiki.wiki_id == default_id else ""
        print(f"{wiki.wiki_id:<20} {wiki.name:<25} {wiki.wiki_type.value:<10} {wiki.page_count:<10} {is_default:<10}")

    registry.close()
    return 0


def _wikis_add(config: dict, args: Any) -> int:
    """Register a new wiki."""
    from llmwikify.core.wiki_registry import WikiRegistry

    wiki_id = args.wiki_id
    name = getattr(args, "name", None) or wiki_id.replace("-", " ").replace("_", " ").title()
    path = getattr(args, "path", None)
    url = getattr(args, "url", None)
    api_key = getattr(args, "api_key", None)

    registry = WikiRegistry(config)
    registry.initialize()

    if url:
        # Remote wiki
        instance = registry.register_remote(
            wiki_id=wiki_id,
            name=name,
            url=url,
            api_key=api_key,
        )
        print(f"✓ Registered remote wiki: {wiki_id}")
        print(f"  URL: {url}")
    elif path:
        # Local wiki
        root = Path(path).expanduser().resolve()
        if not root.exists():
            print_error(f"Path does not exist: {root}")
            registry.close()
            return 1

        instance = registry.register_wiki(
            wiki_id=wiki_id,
            name=name,
            root=root,
        )
        print(f"✓ Registered local wiki: {wiki_id}")
        print(f"  Path: {root}")
    else:
        print_error("Either --path or --url is required")
        registry.close()
        return 1

    print(f"  Name: {name}")
    registry.close()
    return 0


def _wikis_remove(config: dict, args: Any) -> int:
    """Unregister a wiki."""
    from llmwikify.core.wiki_registry import WikiRegistry

    wiki_id = args.wiki_id

    registry = WikiRegistry(config)
    registry.initialize()

    try:
        instance = registry.get_wiki_instance(wiki_id)
        registry.unregister_wiki(wiki_id)
        print(f"✓ Unregistered wiki: {wiki_id}")
        print(f"  Name: {instance.name}")
    except KeyError:
        print_error(f"Wiki not found: {wiki_id}")
        registry.close()
        return 1

    registry.close()
    return 0


def _wikis_scan(config: dict, args: Any) -> int:
    """Scan directories for wikis."""
    from llmwikify.core.wiki_registry import WikiRegistry

    paths = getattr(args, "paths", ["."])
    depth = getattr(args, "depth", 2)

    registry = WikiRegistry(config)
    registry.initialize()

    new_wikis = registry.scan_directories(paths, depth)

    if not new_wikis:
        print("No new wikis found.")
    else:
        print(f"Found {len(new_wikis)} new wiki(es):")
        for wiki in new_wikis:
            print(f"  • {wiki.wiki_id}: {wiki.name} ({wiki.root})")

    registry.close()
    return 0


def run_wikis(wiki: Any, config: dict, args: Any) -> int:
    """Multi-wiki management.

    Args:
        wiki: A Wiki instance (unused — wikis command uses config directly).
        config: The merged config dict.
        args: Parsed argparse Namespace with ``wikis_subcommand`` and
            its subcommand-specific args.

    Returns:
        0 on success, 1 on error.
    """
    subcommand = getattr(args, "wikis_subcommand", "list")

    if subcommand == "list":
        return _wikis_list(config, args)
    elif subcommand == "add":
        return _wikis_add(config, args)
    elif subcommand == "remove":
        return _wikis_remove(config, args)
    elif subcommand == "scan":
        return _wikis_scan(config, args)
    else:
        print(f"Unknown wikis subcommand: {subcommand}")
        return 1


class WikisCommand(Command):
    """``wikis`` command — multi-wiki management."""

    name = "wikis"
    help = "Multi-wiki management commands"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        wikis_parsers = subparsers.add_parser(self.name, help=self.help)
        wikis_sub = wikis_parsers.add_subparsers(
            dest="wikis_subcommand",
            help="Wikis subcommands: list, add, remove, scan",
        )
        wikis_sub.required = True

        # wikis list
        wikis_sub.add_parser("list", help="List all registered wikis")

        # wikis add
        p = wikis_sub.add_parser("add", help="Register a new wiki")
        p.add_argument("wiki_id", help="Unique wiki identifier")
        p.add_argument("--name", "-n", help="Display name")
        p.add_argument("--path", help="Root directory path (for local wikis)")
        p.add_argument("--url", help="Server URL (for remote wikis)")
        p.add_argument("--api-key", help="API key (for remote wikis)")

        # wikis remove
        p = wikis_sub.add_parser("remove", help="Unregister a wiki")
        p.add_argument("wiki_id", help="Wiki identifier to delete")

        # wikis scan
        p = wikis_sub.add_parser("scan", help="Scan directories for wikis")
        p.add_argument("paths", nargs="*", default=["."], help="Directories to scan")
        p.add_argument("--depth", type=int, default=2, help="Scan depth")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_wikis(wiki, config, args)
