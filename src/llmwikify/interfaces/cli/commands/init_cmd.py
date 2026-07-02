"""``init`` command — initialize a wiki at a given root."""

from __future__ import annotations

import os
import sys
from typing import Any

from .._base import Command
from .._output import ICON_SUCCESS, ICON_WARNING, print_success, print_warning


def _maybe_prompt_llm_setup() -> int:
    """After wiki init, prompt the user to set up LLM config if not present.

    Returns:
        0 on skip, 1 on error.
    """
    from .init_llm_cmd import (
        CONFIG_PATH, create_llm_config, auto_detect_provider, resolve_api_key,
        _PROVIDER_ENV_KEY, _DEFAULT_MODELS,
    )

    if CONFIG_PATH.exists():
        return 0

    if not sys.stdin.isatty():
        return 0

    print()
    print("💡 LLM features (analyze-source, synthesize, chat) need ~/.llmwikify/llmwikify.json")
    print("   No LLM config detected. Set one up now? [y/N]: ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if answer not in ("y", "yes"):
        print("  Skipped. Run later: llmwikify init-llm")
        return 0

    print()
    detected = auto_detect_provider()
    detected_env = _PROVIDER_ENV_KEY.get(detected, "API_KEY") if detected else None
    default = detected or "openai"
    if detected:
        print(f"  Detected {detected_env or 'API key'} in env vars. Provider: {default}")
    else:
        print("  Provider [openai/anthropic/minimax/xiaomi] [openai]: ", end="", flush=True)
        try:
            provider_input = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if provider_input:
            default = provider_input
        if not detected_env or default != detected:
            detected_env = _PROVIDER_ENV_KEY.get(default)
            if detected_env and not os.environ.get(detected_env):
                print(f"  API key for {default} (or set {detected_env} first): ", end="", flush=True)
                try:
                    api_key = input().strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 0
                if not api_key:
                    print("  No key provided. Skipping.")
                    return 0
                # Use create_llm_config with explicit key
                return create_llm_config(
                    provider=default,
                    model=_DEFAULT_MODELS.get(default, "gpt-4o"),
                    api_key=api_key,
                )

    return create_llm_config(
        provider=default,
        model=_DEFAULT_MODELS.get(default, "gpt-4o"),
    )


def run_init(wiki: Any, wiki_root: Any, args: Any) -> int:
    """Initialize a wiki at ``wiki_root``.

    Args:
        wiki: A Wiki instance (or any object with ``init(overwrite, agent, force, merge)``).
        wiki_root: The wiki root path (used only for display in the
            "already exists" message; wiki.init() reads from
            its own internal root).
        args: Parsed argparse Namespace with ``overwrite``, ``agent``,
            ``force``, ``merge``, ``llm``, ``llm_provider``, ``llm_model``,
            ``llm_api_key``, ``llm_base_url``, ``llm_overwrite``, ``no_llm_prompt``.

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
        print("    1. Drop sources into raw/")
        print("    2. Run: llmwikify ingest <filename>")
        print("    3. Or use an AI agent: llmwikify init --agent <opencode|claude|codex>")

    # --- LLM setup (P3) ---
    if getattr(args, "llm", False):
        from .init_llm_cmd import create_llm_config
        rc = create_llm_config(
            provider=getattr(args, "llm_provider", None),
            model=getattr(args, "llm_model", None),
            api_key=getattr(args, "llm_api_key", None),
            base_url=getattr(args, "llm_base_url", None),
            overwrite=getattr(args, "llm_overwrite", False),
        )
        if rc != 0:
            return rc
    elif not getattr(args, "no_llm_prompt", False):
        _maybe_prompt_llm_setup()

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
        # LLM setup (P3)
        p.add_argument(
            "--llm", action="store_true",
            help="Also set up global LLM config (~/.llmwikify/llmwikify.json)",
        )
        p.add_argument(
            "--llm-provider", dest="llm_provider",
            choices=["openai", "anthropic", "minimax", "xiaomi"],
            help="LLM provider (default: auto-detect from env)",
        )
        p.add_argument(
            "--llm-model", dest="llm_model",
            help="Model name (default: provider-specific)",
        )
        p.add_argument(
            "--llm-api-key", dest="llm_api_key",
            help="API key (default: from env var)",
        )
        p.add_argument(
            "--llm-base-url", dest="llm_base_url",
            help="Custom API base URL",
        )
        p.add_argument(
            "--llm-overwrite", dest="llm_overwrite", action="store_true",
            help="Overwrite existing LLM config",
        )
        p.add_argument(
            "--no-llm-prompt", dest="no_llm_prompt", action="store_true",
            help="Skip interactive LLM setup prompt (for non-tty/CI)",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        # The init command needs wiki_root for display, not just the wiki.
        # Wiki holds its own root internally, but we need it in run_init
        # for the "already initialized" message. The wiki's root is
        # the simplest way to get it.
        return run_init(wiki, wiki.root, args)
