"""``init-llm`` command — scaffold ~/.llmwikify/llmwikify.json from env vars."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import ICON_SUCCESS, ICON_WARNING, print_success, print_warning


# Provider detection from env vars
_ENV_PROVIDER_MAP = {
    "OPENAI_API_KEY": "openai",
    "ANTHROPIC_API_KEY": "anthropic",
    "MINIMAX_API_KEY": "minimax",
    "OPENAI_BASE_URL": "openai",  # custom endpoint
}

# Default models per provider
_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    "minimax": "minimax-M3",
    "xiaomi": "MiMo-7B-RL",
}

CONFIG_DIR = Path.home() / ".llmwikify"
CONFIG_PATH = CONFIG_DIR / "llmwikify.json"


def run_init_llm(wiki: Any, wiki_root: Any, args: Any) -> int:
    """Scaffold ~/.llmwikify/llmwikify.json with LLM config.

    Auto-detects provider from env vars if --provider not specified.

    Returns:
        0 on success, 1 on error.
    """
    provider = getattr(args, "provider", None)
    model = getattr(args, "model", None)
    api_key = getattr(args, "api_key", None)
    base_url = getattr(args, "base_url", None)
    overwrite = getattr(args, "overwrite", False)

    # Auto-detect provider from env vars
    if not provider:
        for env_var, prov in _ENV_PROVIDER_MAP.items():
            if os.environ.get(env_var):
                provider = prov
                break

    if not provider:
        print_warning("Cannot auto-detect provider. Use --provider or set OPENAI_API_KEY / ANTHROPIC_API_KEY / MINIMAX_API_KEY.")
        print("  Supported providers: openai, anthropic, minimax, xiaomi")
        print("  Example: llmwikify init-llm --provider openai --api-key sk-...")
        return 1

    # Auto-detect API key from env vars
    if not api_key:
        env_key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "minimax": "MINIMAX_API_KEY",
            "xiaomi": None,
        }
        env_var = env_key_map.get(provider)
        if env_var:
            api_key = os.environ.get(env_var)

    if not api_key:
        print_warning(f"No API key found. Set {env_var} or use --api-key.")
        return 1

    # Default model
    if not model:
        model = _DEFAULT_MODELS.get(provider, "gpt-4o")

    # Build config
    config: dict[str, Any] = {
        "llm": {
            "enabled": True,
            "provider": provider,
            "model": model,
            "api_key": api_key,
        }
    }

    if base_url:
        config["llm"]["base_url"] = base_url

    # Check if config already exists
    if CONFIG_PATH.exists() and not overwrite:
        print_warning(f"Config already exists at {CONFIG_PATH}")
        print("  Use --overwrite to replace it, or edit manually.")
        return 1

    # Write config
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print_success(f"LLM config written to {CONFIG_PATH}")
    print(f"  Provider: {provider}")
    print(f"  Model:    {model}")
    print(f"  Key:      ...{api_key[-8:]}")
    print()
    print("  LLM features now available: analyze-source, synthesize, chat, etc.")
    print("  Verify with: llmwikify doctor")
    return 0


class InitLlmCommand(Command):
    """Scaffold ~/.llmwikify/llmwikify.json from env vars or flags."""

    name = "init-llm"
    help = "Create global LLM config (~/.llmwikify/llmwikify.json)"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction
        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")

        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--provider",
            choices=["openai", "anthropic", "minimax", "xiaomi"],
            help="LLM provider (auto-detected from env vars)",
        )
        p.add_argument("--model", help="Model name (default: provider-specific)")
        p.add_argument("--api-key", dest="api_key", help="API key (default: from env var)")
        p.add_argument("--base-url", dest="base_url", help="Custom API base URL")
        p.add_argument("--overwrite", action="store_true", help="Overwrite existing config")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_init_llm(wiki, wiki.root if hasattr(wiki, 'root') else None, args)
