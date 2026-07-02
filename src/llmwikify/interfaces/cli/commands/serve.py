"""``serve`` command — start MCP server (and optional Web UI).

Also wired up to the ``mcp`` alias by ``main()``.

Phase 2a additions (decisions 12, 13, 14, 15):
  - Default host reads ``LLMWIKIFY_HOST`` env var, falling back to
    ``127.0.0.1``. This is the gate that decides "local trust" vs
    "auth enforced" mode.
  - When host is non-loopback and no auth.db exists, we call
    ``prompt_first_admin()`` to bootstrap the first admin interactively
    (TTY required; otherwise print hint and exit 1).
  - When host is loopback (local mode), WikiServer runs with
    ``local_mode=True`` and the middleware is a pass-through.
"""

from __future__ import annotations

import asyncio  # Phase 3 #6 — used by stdio/http/sse paths
import os  # Phase 2a: LLMWIKIFY_HOST env var
import sys  # Phase 2a: print to stderr
from typing import Any

from llmwikify.interfaces.mcp.adapter import MCPAdapter  # Phase 3 #6

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
    from llmwikify.foundation.config import get_wikis_config
    from llmwikify.interfaces.server import WikiServer

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
    # Phase 2a decision 13: host precedence is
    #   --host > LLMWIKIFY_HOST env > mcp.host config > 127.0.0.1
    from llmwikify.foundation.auth import env_host, is_local_default
    final_host = (
        host
        or os.environ.get("LLMWIKIFY_HOST")
        or mcp_config.get("host")
        or env_host()  # reads LLMWIKIFY_HOST again, with default
    )
    final_transport = transport or mcp_config.get("transport", "stdio")

    # Phase 2a: detect local vs public mode and bootstrap auth.db
    # if needed (decision 12, 14, 15).
    local_mode = is_local_default(final_host)
    if not local_mode:
        from llmwikify.foundation.auth import (
            UserRepository,
            auth_db_path,
            chmod_600,
            ensure_dir_700,
            local_token_path,
            prompt_first_admin,
        )
        repo = UserRepository(db_path=auth_db_path())
        if not repo.exists():
            try:
                result = prompt_first_admin()
            except Exception as exc:  # AuthError (no_tty, etc.)
                print(
                    f"\n[!] {type(exc).__name__}: {getattr(exc, 'detail', exc)}",
                    file=sys.stderr,
                )
                return 1
            # Persist the local_token so subsequent CLI commands
            # (auth token, etc.) have a baseline.
            token_path = local_token_path()
            ensure_dir_700(token_path.parent)
            token_path.write_text(result.token + "\n", encoding="utf-8")
            chmod_600(token_path)
            print()
            print("✓ First admin created:", result.user_email)
            print()
            print("Your PAT (paste this in the WebUI login page):")
            print(f"  {result.pat}")
            print()
            print(f"  WebUI: open http://{final_host}:{port}")
            print("  CLI:   export LLMWIKIFY_AUTH_TOKEN=\"<pat-above>\"")
            print()

    # Decide WikiServer's local_mode flag (decision 12).
    # We pass it to WikiServer, which uses it to mount JWTAuthMiddleware
    # in pass-through mode.
    server_local_mode = local_mode
    server_public_read = True  # default; can be overridden later

    try:
        # Check if multi-wiki mode is enabled
        wikis_config = get_wikis_config(config)
        has_wikis_config = wikis_config.get("local") or wikis_config.get("remote")

        if multi_wiki or has_wikis_config:
            from llmwikify.kernel.multi_wiki.registry import WikiRegistry
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
                public_read=server_public_read,
                local_mode=server_local_mode,
            )

            wiki_count = len(registry.list_wikis())
            print(f"Starting Multi-Wiki Server '{service_name}' on {final_host}:{port}")
            print(f"  Wikis: {wiki_count} registered")
            print("  Transport: http")
            # Phase 2a: clearer auth banner (decision 12 + 13)
            if server_local_mode:
                print(f"  Auth: DISABLED (local mode, host {final_host} is loopback)")
            else:
                print(f"  Auth: ENFORCED (host {final_host} is non-loopback)")
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
                    public_read=server_public_read,
                    local_mode=server_local_mode,
                )

                print(f"Starting Unified Server '{service_name}' on {final_host}:{port}")
                print("  Transport: http")
                if server_local_mode:
                    print(f"  Auth: DISABLED (local mode, host {final_host} is loopback)")
                else:
                    print(f"  Auth: ENFORCED (host {final_host} is non-loopback)")
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

                # Phase 3 #6 — use MCPAdapter directly instead of
                # the deprecated ``llmwikify.mcp.server.serve_mcp``
                # shim. This silences 1 internal DeprecationWarning
                # while keeping the same runtime behavior.
                # ``MCPAdapter`` and ``asyncio`` are imported at
                # module level (top of file) so tests can patch
                # ``llmwikify.cli.commands.serve.MCPAdapter`` to
                # verify the name= flow without starting the
                # actual MCP server.
                adapter = MCPAdapter(wiki, name=name, config=mcp_config)
                transport_final = final_transport
                host_final = final_host
                port_final = port
                if transport_final == "stdio":
                    asyncio.run(adapter.run_stdio())
                elif transport_final == "http":
                    asyncio.run(adapter.run_http(host_final, port_final))
                elif transport_final == "sse":
                    asyncio.run(adapter.run_sse(host_final, port_final))
                else:
                    raise ValueError(
                        f"Unsupported transport: {transport_final}. "
                        "Use 'stdio', 'http', or 'sse'."
                    )
    except KeyboardInterrupt:
        print("\nServer stopped")

    return 0


def setup_serve_parser(subparsers: Any) -> None:
    """Add the ``serve`` subparser (with ``mcp`` as argparse alias).

    Phase 3 #6 — ``mcp`` is an argparse alias of ``serve`` (full
    backward compat for ``llmwikify mcp ...`` invocations).
    The ``mcp`` alias will be removed in v0.34.0.
    """
    from argparse import _SubParsersAction

    if not isinstance(subparsers, _SubParsersAction):
        raise TypeError("setup_parser requires an argparse subparsers action")

    p = subparsers.add_parser(
        "serve",
        help="Start MCP server with optional Web UI (alias: mcp)",
        aliases=["mcp"],
    )
    p.add_argument("--transport", "-t", choices=["stdio", "http", "sse"], help="Transport protocol")
    p.add_argument(
        "--host",
        help=(
            "Host address. Default: $LLMWIKIFY_HOST env var, or 127.0.0.1. "
            "Loopback = local trust mode (no auth). Non-loopback = public mode (auth enforced; "
            "auto-prompts for first admin if ~/.llmwikify/auth.db is missing)."
        ),
    )
    p.add_argument("--mcp-port", type=int, help="MCP server port")
    p.add_argument("--port", "-p", type=int, help="[Deprecated] Use --mcp-port instead")
    p.add_argument("--name", "-n", help="Service name (defaults to directory name)")
    p.add_argument("--web", action="store_true", help="Start unified Web UI (single process)")
    p.add_argument(
        "--auth-token",
        help=(
            "API Key (legacy, decision 2 plan B: treated as JWT signing secret). "
            "Prefer running `llmwikify auth init` for first-time setup."
        ),
    )
    p.add_argument("--multi-wiki", action="store_true", help="Enable multi-wiki mode")


class ServeCommand(Command):
    """``serve`` command — start MCP server and optional Web UI.

    ``mcp`` is an argparse alias of ``serve`` (Phase 3 #6).
    Backward compat: ``llmwikify mcp`` still works for Claude
    Desktop / Cursor MCP integration that reference
    ``llmwikify mcp`` in their config.
    """

    name = "serve"
    help = "Start MCP server with optional Web UI (alias: mcp)"

    def setup_parser(self, subparsers: Any) -> None:
        setup_serve_parser(subparsers)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_serve(wiki, config, args)
