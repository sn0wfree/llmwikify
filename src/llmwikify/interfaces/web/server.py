"""Standalone Web UI server for llmwikify.

Thin wrapper around the unified server (MCP + REST API + WebUI).
Run with: python -m llmwikify.web.server --wiki-root ~/wiki --port 8765
"""

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


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
    parser.add_argument(
        "--force-skip-dream",
        action="store_true",
        help=(
            "If llm.enabled=true but the LLM provider fails to initialize "
            "(missing api_key, unknown provider, etc.), start the server "
            "anyway with dream_scheduler + auto_compact disabled. "
            "Default: exit with error and a fix-it hint."
        ),
    )

    args = parser.parse_args()

    # TODO(4layer-B3): once ``core/`` moves to ``kernel/``, update
    # the Wiki import to ``from llmwikify.kernel.wiki import Wiki``.
    from llmwikify.interfaces.server import WikiServer
    from llmwikify.kernel import Wiki

    # Phase 7+ (2026-07-08): wire the default LLM provider so Phase 6
    # DreamScheduler + Phase 9 AutoCompact can actually start. Same
    # semantics as ``llmwikify serve`` (see interfaces/cli/commands/serve.py).
    provider = None
    try:
        from llmwikify.apps.chat.providers.registry import get_default_provider
        provider = get_default_provider()
        if provider is not None:
            logger.info(
                "web: LLM provider wired (model=%s)",
                getattr(provider, "model", "?"),
            )
    except RuntimeError as exc:
        if args.force_skip_dream:
            logger.warning(
                "web: --force-skip-dream set; ignoring provider error: %s",
                exc,
            )
            provider = None
        else:
            print(
                f"\n[!] LLM provider initialization failed:\n    {exc}\n",
                file=sys.stderr,
            )
            print(
                "    To start the server anyway, pass --force-skip-dream "
                "(dream/auto_compact will be disabled).\n"
                "    Otherwise, fix llm.enabled / provider / api_key in "
                "~/.llmwikify/llmwikify.json.\n",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc

    wiki_root = Path(args.wiki_root).resolve()
    wiki = Wiki(wiki_root)

    server = WikiServer(
        wiki,
        api_key=args.api_key,
        enable_mcp=True,
        enable_rest=True,
        enable_webui=True,
        provider=provider,
    )

    print(f"Starting Unified Server on http://{args.host}:{args.port}")
    print(f"  Wiki root: {wiki_root}")
    print(f"  Auth: {'enabled' if args.api_key else 'disabled'}")
    print(f"  API Docs: http://{args.host}:{args.port}/docs")

    server.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
