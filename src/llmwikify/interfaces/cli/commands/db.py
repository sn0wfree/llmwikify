"""``db`` command — database management (stats / list / clean / export)."""

from __future__ import annotations

import json
from typing import Any

from .._base import Command
from .._output import print_error, print_warning


def _db_stats(wiki: Any, args: Any) -> int:
    """Show database statistics."""
    from llmwikify.agent.backend.db import AgentDatabase, get_agent_db_path

    db_path = get_agent_db_path(wiki.root / ".llmwikify" / "agent")
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    db = AgentDatabase(db_path)
    stats = db.get_db_stats()

    print("📊 Database Statistics")
    print(f"   Path: {stats['db_path']}")
    print(f"   Size: {stats['size_mb']:.2f} MB")
    print()

    wiki_id = getattr(args, "wiki_id", None)
    if wiki_id:
        wiki_stats = db.get_wiki_stats(wiki_id)
        print(f"   Wiki: {wiki_stats['wiki_id']}")
        print(f"     Chat sessions: {wiki_stats['chat_sessions']}")
        print(f"     Research sessions: {wiki_stats['research_sessions']}")
        print(f"     Research sources: {wiki_stats['research_sources']}")
    else:
        print("   Tables:")
        for table, count in stats["tables"].items():
            print(f"     {table}: {count} rows")

    return 0


def _db_list(wiki: Any, args: Any) -> int:
    """List all wikis."""
    from llmwikify.agent.backend.db import AgentDatabase, get_agent_db_path

    db_path = get_agent_db_path(wiki.root / ".llmwikify" / "agent")
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    db = AgentDatabase(db_path)
    wikis = db.list_all_wikis()

    if not wikis:
        print("No wikis found in database.")
        return 0

    print("📋 Wikis in Database")
    print()
    for wiki_entry in wikis:
        print(f"  {wiki_entry['wiki_id']}")
        print(f"    Chat sessions: {wiki_entry['chat_sessions']}")
        print(f"    Research sessions: {wiki_entry['research_sessions']}")
        print(f"    Research sources: {wiki_entry['research_sources']}")
        print()

    return 0


def _db_clean(wiki: Any, args: Any) -> int:
    """Delete all data for a wiki."""
    from llmwikify.agent.backend.db import AgentDatabase, get_agent_db_path

    wiki_id = args.wiki_id
    force = getattr(args, "force", False)

    if not force:
        print_warning(f"This will delete all data for wiki '{wiki_id}'.")
        confirm = input("Type 'yes' to confirm: ")
        if confirm.lower() != "yes":
            print("Cancelled.")
            return 0

    db_path = get_agent_db_path(wiki.root / ".llmwikify" / "agent")
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    db = AgentDatabase(db_path)
    result = db.delete_wiki_data(wiki_id)

    print(f"✅ Deleted data for wiki '{wiki_id}':")
    print(f"   Chat sessions: {result['chat_sessions']}")
    print(f"   Research sessions: {result['research_sessions']}")
    print(f"   Tool calls: {result['tool_calls']}")
    print(f"   Ingest log: {result['ingest_log']}")

    return 0


def _db_export(wiki: Any, args: Any) -> int:
    """Export wiki data to JSON."""
    from llmwikify.agent.backend.db import AgentDatabase, get_agent_db_path

    wiki_id = args.wiki_id
    output = args.output

    db_path = get_agent_db_path(wiki.root / ".llmwikify" / "agent")
    if not db_path.exists():
        print_error("No agent database found.")
        return 1

    db = AgentDatabase(db_path)
    data = db.export_wiki_data(wiki_id)

    with open(output, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"✅ Exported data for wiki '{wiki_id}' to {output}")
    print(f"   Chat sessions: {len(data['chat_sessions'])}")
    print(f"   Chat messages: {len(data['chat_messages'])}")
    print(f"   Research sessions: {len(data['research_sessions'])}")
    print(f"   Research sources: {len(data['research_sources'])}")
    print(f"   Research sub-queries: {len(data['research_sub_queries'])}")
    print(f"   Tool calls: {len(data['tool_calls'])}")

    return 0


def run_db(wiki: Any, args: Any) -> int:
    """Database management dispatcher.

    Args:
        wiki: A Wiki instance (used for ``.root``).
        args: Parsed argparse Namespace with ``db_subcommand``.

    Returns:
        0 on success, 1 on error.
    """
    subcommand = getattr(args, "db_subcommand", "stats")

    if subcommand == "stats":
        return _db_stats(wiki, args)
    elif subcommand == "list":
        return _db_list(wiki, args)
    elif subcommand == "clean":
        return _db_clean(wiki, args)
    elif subcommand == "export":
        return _db_export(wiki, args)
    else:
        print(f"Unknown db subcommand: {subcommand}")
        return 1


class DbCommand(Command):
    """``db`` command — database management."""

    name = "db"
    help = "Database management commands"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        db_parsers = subparsers.add_parser(self.name, help=self.help)
        db_sub = db_parsers.add_subparsers(dest="db_subcommand", help="DB subcommands")

        # db stats
        p = db_sub.add_parser("stats", help="Show database statistics")
        p.add_argument("wiki_id", nargs="?", help="Wiki ID (optional, shows all if omitted)")

        # db list
        db_sub.add_parser("list", help="List all wikis")

        # db clean
        p = db_sub.add_parser("clean", help="Delete all data for a wiki")
        p.add_argument("wiki_id", help="Wiki ID to delete")
        p.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

        # db export
        p = db_sub.add_parser("export", help="Export wiki data to JSON")
        p.add_argument("wiki_id", help="Wiki ID to export")
        p.add_argument("output", help="Output file path")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_db(wiki, args)
