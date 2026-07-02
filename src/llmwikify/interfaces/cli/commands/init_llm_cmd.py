"""``init-llm`` command + shared LLM config creation logic.

Used by both ``init-llm`` (standalone) and ``init --llm`` (combined).
"""

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

# Env var for API key per provider
_PROVIDER_ENV_KEY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "xiaomi": None,
}

CONFIG_DIR = Path.home() / ".llmwikify"
CONFIG_PATH = CONFIG_DIR / "llmwikify.json"


def auto_detect_provider() -> str | None:
    """Auto-detect provider from env vars. Returns provider name or None."""
    for env_var, prov in _ENV_PROVIDER_MAP.items():
        if os.environ.get(env_var):
            return prov
    return None


def resolve_api_key(provider: str, explicit_key: str | None = None) -> str | None:
    """Resolve API key from explicit arg or env var."""
    if explicit_key:
        return explicit_key
    env_var = _PROVIDER_ENV_KEY.get(provider)
    if env_var:
        return os.environ.get(env_var)
    return None


def create_llm_config(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    overwrite: bool = False,
    quiet: bool = False,
) -> int:
    """Create ~/.llmwikify/llmwikify.json with LLM config.

    Args:
        provider: LLM provider name (auto-detected from env if None).
        model: Model name (default per provider if None).
        api_key: API key (auto-detected from env if None).
        base_url: Custom API base URL.
        overwrite: Replace existing config.
        quiet: Suppress informational output.

    Returns:
        0 on success, 1 on error.
    """
    if not provider:
        provider = auto_detect_provider()

    if not provider:
        if not quiet:
            print_warning("Cannot auto-detect provider. Use --provider or set OPENAI_API_KEY / ANTHROPIC_API_KEY / MINIMAX_API_KEY.")
            print("  Supported providers: openai, anthropic, minimax, xiaomi")
            print("  Example: llmwikify init-llm --provider openai --api-key sk-...")
        return 1

    if not api_key:
        api_key = resolve_api_key(provider)

    if not api_key:
        env_var = _PROVIDER_ENV_KEY.get(provider) or "API_KEY"
        if not quiet:
            print_warning(f"No API key found. Set {env_var} or use --api-key.")
        return 1

    if not model:
        model = _DEFAULT_MODELS.get(provider, "gpt-4o")

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

    if CONFIG_PATH.exists() and not overwrite:
        if not quiet:
            print_warning(f"Config already exists at {CONFIG_PATH}")
            print("  Use --overwrite to replace it, or edit manually.")
        return 1

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    if not quiet:
        print_success(f"LLM config written to {CONFIG_PATH}")
        print(f"  Provider: {provider}")
        print(f"  Model:    {model}")
        print(f"  Key:      ...{api_key[-8:]}")
        print()
        print("  LLM features now available: analyze-source, synthesize, chat, etc.")
        print("  Verify with: llmwikify doctor")

    return 0


def run_init_llm(wiki: Any, wiki_root: Any, args: Any) -> int:
    """CLI entry: scaffold ~/.llmwikify/llmwikify.json from env vars or flags."""
    return create_llm_config(
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        api_key=getattr(args, "api_key", None),
        base_url=getattr(args, "base_url", None),
        overwrite=getattr(args, "overwrite", False),
    )


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
