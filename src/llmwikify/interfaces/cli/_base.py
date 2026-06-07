"""Command protocol and base classes for CLI commands.

Phase 1 #2 / C1 — establish the framework for splitting
``cli/commands.py`` (2200 LOC) into per-command files.

The current ``WikiCLI`` class holds 43 public methods and 22
private helpers, all in one file. This module defines the
``Command`` protocol that future per-command files will follow.

This commit is framework-only: no commands are migrated yet.
C2 will migrate the simplest ~10 commands as proof of concept;
C3 will migrate the remaining 16 + switch ``main()`` to use the
registry.

Design notes
------------

A ``Command`` is intentionally minimal: a name, a help string,
a parser setup, and a run method. There is no separate
``format`` step — formatting stays inline in ``run`` because
most commands have a single output mode (either print or
JSON-via-stdout). Splitting formatting out added complexity
without buying much for the 26-command surface.

``run()`` takes the parsed args, the Wiki instance, and the
config dict. Returning an ``int`` exit code is unchanged from
the current ``WikiCLI`` contract.

``setup_parser()`` receives the parent ``subparsers`` object and
is responsible for adding the parser for this command. This
matches the current pattern in ``commands.py``.
"""

from __future__ import annotations

from argparse import _SubParsersAction
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Command(Protocol):
    """Protocol for a single CLI command.

    A command is a unit of CLI behavior with:
    - a unique name (used in dispatch)
    - a help string (shown in ``llmwikify --help``)
    - a parser-setup method (adds arguments to subparsers)
    - a run method (executes the command, returns exit code)
    """

    name: str
    help: str

    def setup_parser(
        self,
        subparsers: _SubParsersAction[Any],
    ) -> None:
        """Add a parser for this command to ``subparsers``."""
        ...

    def run(self, args: Any, wiki_root: Path, config: dict[str, Any]) -> int:
        """Execute this command. Return the exit code (0 = success).

        ``wiki_root`` is the wiki's root directory; ``config`` is the
        merged config dict (loaded from .wiki-config.yaml or built-in
        defaults).
        """
        ...


# Registry holds all registered commands. Commands are added via
# the ``@register_command`` decorator (defined in cli.commands or
# in a future cli._registry module). The dict is module-level so
# commands can self-register on import.

COMMAND_REGISTRY: dict[str, Command] = {}


def register_command(cmd: Command) -> Command:
    """Register a command instance in the global registry.

    Usage::

        class StatusCommand:
            name = "status"
            help = "Show status"

            def setup_parser(self, subparsers): ...
            def run(self, args, wiki_root, config): ...

        register_command(StatusCommand())

    Returns the command unchanged so the decorator can be used
    inline::

        @register_command
        class StatusCommand: ...
    """
    if cmd.name in COMMAND_REGISTRY:
        raise ValueError(
            f"command name '{cmd.name}' is already registered "
            f"(by {type(COMMAND_REGISTRY[cmd.name]).__name__})"
        )
    COMMAND_REGISTRY[cmd.name] = cmd
    return cmd


def get_command(name: str) -> Command | None:
    """Look up a registered command by name. Returns None if absent."""
    return COMMAND_REGISTRY.get(name)


def registered_command_names() -> list[str]:
    """Return the list of registered command names (sorted)."""
    return sorted(COMMAND_REGISTRY.keys())


class CommandError(Exception):
    """Raised by a command's run() to signal a user-facing error.

    Catches and prints the message with an ❌ icon, returning
    exit code 1. The main() function uses this to centralize
    error handling once commands start raising it.

    In the current refactor (Phase 1 #2 C1), this exception is
    defined but not yet raised by any command — existing
    commands still use print() + return 1 directly. C2 and C3
    will migrate commands to raise CommandError for cleaner
    error handling.
    """

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
