"""``serve`` command — start MCP server (and optional Web UI).

Also wired up to the ``mcp`` alias by ``main()``.
"""

from __future__ import annotations

from typing import Any

from .._base import Command


def run_serve(wiki: Any, config: dict, args: Any) -> int:
    """Start the MCP server (and optionally the Web UI).

    Args:
        wiki: A Wiki instance (used for both single-wiki and registry modes).
        config: The merged config dict.
        args: Parsed argparse Namespace with ``name``, ``transport``,
            ``host``, ``mcp_port``/``port``, ``web``, ``auth_token``,
            ``multi_wiki``.

    Returns:
        0 on success (or after KeyboardInterrupt).
    """
    from llmwikify.config import get_wikis_config
    from llmwikify.server import WikiServer

    mcp_config = config.get("mcp", {})

    name = getattr(args, "name", None)
    transport = getattr(args, "transport", None)
    host = getattr(args, "host", None)
    mcp_port = getattr(args, "mcp_port", None) or getattr(args, "port", None)
    web = getattr(args, "web", False)
    auth_token = getattr(args, "auth_token", None)
    multi_wiki = getattr(args, "multi_wiki", False)

    service_name = name or mcp_config.get("name") or wiki.root.name
    port = mcp_port or mcp_config.get("port", 8765)
    final_host = host or mcp_config.get("host", "127.0.0.1")
    final_transport = transport or mcp_config.get("transport", "stdio")

    try:
        # Check if multi-wiki mode is enabled
        wikis_config = get_wikis_config(config)
        has_wikis_config = wikis_config.get("local") or wikis_config.get("remote")

        if multi_wiki or has_wikis_config:
            from llmwikify.core.wiki_registry import WikiRegistry
            registry = WikiRegistry(config)
            registry.initialize()

            if not registry.list_wikis():
                discovered = registry.scan_directories(["."], 3)
                if discovered:
                    print(f"  Discovered: {len(discovered)} wiki(s)")

            server = WikiServer(
                registry,
                api_key=auth_token,
                mcp_name=service_name,
                enable_mcp=True,
                enable_rest=True,
                enable_webui=web,
            )

            wiki_count = len(registry.list_wikis())
            print(f"Starting Multi-Wiki Server '{service_name}' on {final_host}:{port}")
            print(f"  Wikis: {wiki_count} registered")
            print(f"  Transport: http")
            print(f"  Auth: {'enabled' if auth_token else 'disabled'}")
            if web:
                print(f"  Web UI: http://{final_host}:{port}")
                print(f"  API Docs: http://{final_host}:{port}/docs")
            print()

            server.run(host=final_host, port=port)
        else:
            if web:
                server = WikiServer(
                    wiki,
                    api_key=auth_token,
                    mcp_name=service_name,
                    enable_mcp=True,
                    enable_rest=True,
                    enable_webui=True,
                )

                print(f"Starting Unified Server '{service_name}' on {final_host}:{port}")
                print("  Transport: http")
                print(f"  Auth: {'enabled' if auth_token else 'disabled'}")
                print(f"  Web UI: http://{final_host}:{port}")
                print(f"  API Docs: http://{final_host}:{port}/docs")
                print()

                server.run(host=final_host, port=port)
            else:
                print(f"Starting MCP server '{service_name}'...")
                print(f"  Transport: {final_transport}")
                if final_host != "127.0.0.1":
                    print(f"  Host: {final_host}")
                if port != 8765:
                    print(f"  Port: {port}")
                print()

                from llmwikify.mcp.server import serve_mcp
                serve_mcp(wiki, name=name, transport=transport, host=host, port=mcp_port, config=mcp_config)
    except KeyboardInterrupt:
        print("\nServer stopped")

    return 0


def setup_serve_or_mcp_parser(subparsers: Any) -> None:
    """Add both the ``serve`` and ``mcp`` subparsers.

    The original code defines two CLI commands (``mcp`` and ``serve``)
    that both point to the same handler. This helper adds both
    parsers in one place, since they share an implementation.
    """
    from argparse import _SubParsersAction

    if not isinstance(subparsers, _SubParsersAction):
        raise TypeError("setup_parser requires an argparse subparsers action")

    p = subparsers.add_parser("mcp", help="Start MCP server for Agent interaction (stdio by default)")
    p.add_argument("--transport", "-t", choices=["stdio", "http", "sse"], help="Transport protocol")
    p.add_argument("--host", help="Host address")
    p.add_argument("--port", "-p", type=int, help="Port number")
    p.add_argument("--name", "-n", help="Service name (defaults to directory name)")

    p = subparsers.add_parser("serve", help="Start MCP server with optional Web UI")
    p.add_argument("--transport", "-t", choices=["stdio", "http", "sse"], help="Transport protocol")
    p.add_argument("--host", help="Host address")
    p.add_argument("--mcp-port", type=int, help="MCP server port")
    p.add_argument("--port", "-p", type=int, help="[Deprecated] Use --mcp-port instead")
    p.add_argument("--name", "-n", help="Service name (defaults to directory name)")
    p.add_argument("--web", action="store_true", help="Start unified Web UI (single process)")
    p.add_argument("--auth-token", help="API Key for authentication")
    p.add_argument("--multi-wiki", action="store_true", help="Enable multi-wiki mode")


class ServeCommand(Command):
    """``serve`` command — start MCP server and optional Web UI."""

    name = "serve"
    help = "Start MCP server with optional Web UI"

    def setup_parser(self, subparsers: Any) -> None:
        setup_serve_or_mcp_parser(subparsers)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_serve(wiki, config, args)


class McpCommand(Command):
    """``mcp`` command — alias for ``serve``."""

    name = "mcp"
    help = "Start MCP server for Agent interaction (stdio by default)"

    def setup_parser(self, subparsers: Any) -> None:
        setup_serve_or_mcp_parser(subparsers)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_serve(wiki, config, args)
