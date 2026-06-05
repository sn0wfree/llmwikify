"""Command-line interface for llmwikify.

Phase 1 #2 / C2 — the per-command implementations live in
``llmwikify.cli.commands`` (a subpackage). The WikiCLI class
and main() function live in ``llmwikify.cli._app`` (renamed
from commands.py to avoid shadowing the subpackage).
"""

from ._app import WikiCLI, main

__all__ = ["WikiCLI", "main"]
