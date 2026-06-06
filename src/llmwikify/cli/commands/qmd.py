"""``qmd`` command — QMD hybrid search engine (status / search / install / embed / mcp)."""

from __future__ import annotations

import subprocess
from typing import Any

from .._base import Command
from .._output import print_error


def _qmd_status(wiki: Any, args: Any) -> int:
    """Display QMD status and recommendations."""
    status = wiki.qmd_status()

    print("📊 QMD Hybrid Search Status")
    print(f"   Pages in wiki: {status['page_count']}")
    print(f"   QMD threshold: {status.get('threshold', 1000)} pages")
    print(f"   Configured backend: {status.get('backend', 'fts5')}")
    print(f"   QMD available: {'✅ Yes' if status['available'] else '❌ No'}")
    print(f"   QMD recommended: {'✅ Yes' if status['recommended'] else 'ℹ️ No'}")

    if status.get("message"):
        print(f"\n💡 {status['message']}")

    return 0


def _qmd_search(wiki: Any, args: Any) -> int:
    """Search using QMD hybrid engine."""
    results = wiki.search(args.query, getattr(args, "limit", 10), backend="qmd")

    if not results:
        print("No results found from QMD.")
        print("Make sure QMD MCP server is running: `qmd mcp --http --port 8181`")
        return 1

    print(f"🔍 QMD Hybrid Search results for: {args.query}")
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['page_name']}")
        print(f"   Score: {r['score']:.4f}")
        print(f"   {r['snippet']}")

    return 0


def _qmd_install(wiki: Any, args: Any) -> int:
    """Display QMD installation instructions."""
    qmd = wiki.qmd
    if qmd:
        print(qmd.get_install_guide())
    else:
        from llmwikify.core.qmd_client import QmdClient
        client = QmdClient()
        print(client.get_install_guide())
    return 0


def _qmd_embed(wiki: Any, args: Any) -> int:
    """Trigger QMD embedding generation."""
    qmd = wiki.qmd
    if not qmd or not qmd.is_available():
        print_error("QMD server not available.")
        print("Start the server first: `qmd mcp --http --port 8181`")
        return 1

    print("🔄 Starting embedding generation...")
    print("(This may take several minutes on first run)")
    result = qmd.embed()
    print(f"\nResult: {result.get('status', 'unknown')}")
    return 0


def _qmd_mcp(wiki: Any, args: Any) -> int:
    """Start QMD MCP server (delegates to external qmd command)."""
    port = getattr(args, "port", 8181)
    host = getattr(args, "host", "127.0.0.1")

    cmd = ["qmd", "mcp", "--http", "--port", str(port), "--host", host]

    if getattr(args, "collection", None):
        cmd.extend(["--collection", args.collection])

    print(f"Starting QMD MCP server: {' '.join(cmd)}")
    print("Press Ctrl+C to stop")

    try:
        subprocess.run(cmd, cwd=wiki.root)
    except KeyboardInterrupt:
        print("\nServer stopped")
    except FileNotFoundError:
        print_error("'qmd' command not found. Install QMD first:")
        print("   npm install -g @tobilu/qmd")
        return 1

    return 0


def run_qmd(wiki: Any, args: Any) -> int:
    """QMD hybrid search engine dispatcher.

    Args:
        wiki: A Wiki instance (or any object with ``qmd_status()``,
            ``search(query, limit, backend=...)``, ``qmd``).
        args: Parsed argparse Namespace with ``qmd_subcommand``.

    Returns:
        0 on success, 1 on error.
    """
    subcommand = getattr(args, "qmd_subcommand", "status")

    if subcommand == "status":
        return _qmd_status(wiki, args)
    elif subcommand == "search":
        return _qmd_search(wiki, args)
    elif subcommand == "install":
        return _qmd_install(wiki, args)
    elif subcommand == "embed":
        return _qmd_embed(wiki, args)
    elif subcommand == "mcp":
        return _qmd_mcp(wiki, args)
    else:
        print(f"Unknown qmd subcommand: {subcommand}")
        return 1


class QmdCommand(Command):
    """``qmd`` command — QMD hybrid search engine."""

    name = "qmd"
    help = "QMD hybrid search engine commands"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        qmd_parsers = subparsers.add_parser(self.name, help=self.help)
        qmd_sub = qmd_parsers.add_subparsers(
            dest="qmd_subcommand",
            help="QMD subcommands: status, search, install, embed, mcp",
        )

        # qmd status
        qmd_sub.add_parser("status", help="Show QMD status and recommendations")

        # qmd search
        p = qmd_sub.add_parser("search", help="QMD hybrid search")
        p.add_argument("query", help="Search query")
        p.add_argument("--limit", "-l", type=int, default=10)

        # qmd install
        qmd_sub.add_parser("install", help="Show QMD installation guide")

        # qmd embed
        qmd_sub.add_parser("embed", help="Trigger QMD embedding generation")

        # qmd mcp
        p = qmd_sub.add_parser("mcp", help="Start QMD MCP server")
        p.add_argument("--port", "-p", type=int, default=8181, help="Port (default: 8181)")
        p.add_argument("--host", default="127.0.0.1", help="Bind address")
        p.add_argument("--collection", help="Collection name")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_qmd(wiki, args)
