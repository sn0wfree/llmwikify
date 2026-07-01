"""``help`` command — list all available commands and aliases.

Phase 3 #6 — provides an easy way to discover subcommand
aliases (e.g., ``mcp`` → ``serve``). argparse does not
display aliases in the main ``--help`` output natively
(only Python 3.13+ does), so this command gives users
a fast way to see the full picture::

    $ llmwikify help                # all commands + aliases
    $ llmwikify help --aliases      # just aliases section
"""

from __future__ import annotations

from typing import Any

from .._base import COMMAND_REGISTRY, Command

# Subcommand aliases — populated by main() at startup.
# (Phase 3 #6: aliases registered on argparse subparsers
# are collected here so the ``help`` command can show them
# without re-walking argparse internals on every call.)
SUBCOMMAND_ALIASES: dict[str, str] = {}


class HelpCommand(Command):
    """``help`` command — list all commands and aliases."""

    name = "help"
    help = "List all available commands and aliases"

    def setup_parser(self, subparsers) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError(
                "setup_parser requires an argparse subparsers action"
            )
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--aliases", "-a", action="store_true",
            help="Show only subcommand aliases",
        )

    def run(self, args, wiki, config) -> int:
        if getattr(args, "aliases", False):
            return self._print_aliases_only()
        return self._print_full()

    def _print_full(self) -> int:
        """Show all commands, then aliases (if any)."""
        print("Available commands:")
        for name in sorted(COMMAND_REGISTRY):
            cmd = COMMAND_REGISTRY[name]
            print(f"  {name:20s}  {cmd.help}")

        if SUBCOMMAND_ALIASES:
            print()
            print("Subcommand aliases (backward compat, removed in v0.34.0):")
            for alias, target in sorted(SUBCOMMAND_ALIASES.items()):
                print(
                    f"  {alias:14s} \u2192 {target:14s}  "
                    f"(e.g., 'llmwikify {alias} --name foo')"
                )
        return 0

    def _print_aliases_only(self) -> int:
        """Show only the aliases section."""
        if not SUBCOMMAND_ALIASES:
            print("No subcommand aliases registered.")
            return 0

        print("Subcommand aliases (backward compat, removed in v0.34.0):")
        for alias, target in sorted(SUBCOMMAND_ALIASES.items()):
            print(
                f"  {alias:14s} \u2192 {target:14s}  "
                f"(e.g., 'llmwikify {alias} --name foo')"
            )
        return 0
