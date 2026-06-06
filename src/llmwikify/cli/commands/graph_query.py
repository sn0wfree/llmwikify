"""``graph_query`` command — query the knowledge graph."""

from __future__ import annotations

from typing import Any

from .._base import Command


def run_graph_query(wiki: Any, args: Any) -> int:
    """Query the knowledge graph (neighbors / path / stats / context).

    Args:
        wiki: A Wiki instance (or any object with ``get_relation_engine()``).
        args: Parsed argparse Namespace with ``subcommand`` and ``args``.

    Returns:
        0 on success, 1 on usage error.
    """
    engine = wiki.get_relation_engine()
    subcommand = args.subcommand
    cmd_args = args.args or []

    if subcommand == "neighbors":
        if not cmd_args:
            print("❌ Usage: llmwikify graph-query neighbors <concept>")
            return 1
        concept = cmd_args[0]
        relations = engine.get_neighbors(concept)
        if not relations:
            print(f"No relations found for: {concept}")
            return 0
        print(f"Relations for: {concept}\n")
        for r in relations:
            direction = "→" if r["source"] == concept else "←"
            other = r["target"] if r["source"] == concept else r["source"]
            print(f"  {direction} [{r['relation']}] {other} ({r['confidence']})")
        print(f"\nTotal: {len(relations)}")

    elif subcommand == "path":
        if len(cmd_args) < 2:
            print("❌ Usage: llmwikify graph-query path <A> <B>")
            return 1
        result = engine.get_path(cmd_args[0], cmd_args[1])
        if result is None:
            print(f"No path found between {cmd_args[0]} and {cmd_args[1]}")
            return 0
        print(f"Path: {' → '.join(result['path'])}")
        for e in result["edges"]:
            print(f"  {e['source']} -[{e['relation']}]-> {e['target']} ({e['confidence']})")

    elif subcommand == "stats":
        stats = engine.get_stats()
        print("=== Graph Statistics ===\n")
        print(f"Total relations: {stats['total_relations']}")
        print(f"Unique concepts: {stats['unique_concepts']}")
        print("\nBy confidence:")
        for level, count in stats["by_confidence"].items():
            print(f"  {level}: {count}")
        print("\nBy relation type:")
        for rel, count in stats["by_relation"].items():
            print(f"  {rel}: {count}")

    elif subcommand == "context":
        if not cmd_args:
            print("❌ Usage: llmwikify graph-query context <relation_id>")
            return 1
        rel_id = int(cmd_args[0])
        result = engine.get_context(rel_id)
        if result is None:
            print(f"Relation {rel_id} not found")
            return 1
        print(f"Relation #{rel_id}:")
        print(f"  {result['source']} -[{result['relation']}]-> {result['target']}")
        print(f"  Confidence: {result['confidence']}")
        if result.get("context"):
            print(f"  Context: {result['context']}")
        if result.get("source_file"):
            print(f"  Source file: {result['source_file']}")

    return 0


class GraphQueryCommand(Command):
    """``graph_query`` command — query the knowledge graph."""

    name = "graph-query"
    help = "Query the knowledge graph"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "subcommand", choices=["neighbors", "path", "stats", "context"],
            help="Query type",
        )
        p.add_argument("args", nargs="*", help="Arguments (concept name, path endpoints, relation id)")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_graph_query(wiki, args)
