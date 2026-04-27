"""Standalone Web UI server for llmwikify.

Thin wrapper around the unified server (MCP + REST API + WebUI).
Run with: python -m llmwikify.web.server --wiki-root ~/wiki --port 8765
"""

import argparse
from pathlib import Path


def main():
    """CLI entry point for standalone unified server."""
    parser = argparse.ArgumentParser(description="llmwikify Unified Server (MCP + REST API + WebUI)")
    parser.add_argument(
        "--wiki-root",
        required=True,
        help="Wiki root directory path"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Server port (default: 8765)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API Key for authentication"
    )

    args = parser.parse_args()

    from ..core import Wiki
    from ..server import WikiServer

    wiki_root = Path(args.wiki_root).resolve()
    wiki = Wiki(wiki_root)

    server = WikiServer(
        wiki,
        api_key=args.api_key,
        enable_mcp=True,
        enable_rest=True,
        enable_webui=True,
    )

    print(f"Starting Unified Server on http://{args.host}:{args.port}")
    print(f"  Wiki root: {wiki_root}")
    print(f"  Auth: {'enabled' if args.api_key else 'disabled'}")
    print(f"  API Docs: http://{args.host}:{args.port}/docs")

    server.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
