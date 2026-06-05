"""Output helpers for CLI commands.

Phase 1 #2 / C1 — centralize the print patterns and emoji
constants currently scattered across ``cli/commands.py``.

The existing codebase uses these patterns:

  print(f"✅ {result['message']}")              # success
  print(f"⚠️  Wiki already initialized at ...")  # warning
  print(f"❌ {result['error']}")                 # error
  print(f"📊 {len(results)} results")            # info

  if result['status'] == 'already_exists':      # status check
  if result['status'] == 'mcp_config_added':

  print(f"\n{json.dumps(output, ...)}")          # JSON to stdout

This module provides:
- Emoji constants (so commands don't use string literals)
- ``print_success``, ``print_warning``, ``print_error`` helpers
- ``check_status`` helper for the common status-dispatch pattern
- ``print_json`` for the agent-friendly JSON output path

In C1 these are added but not yet called by any command. C2
and C3 will migrate commands to use them.
"""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn


# Emoji constants — kept as module-level strings so they can be
# referenced without re-declaring the unicode literal at every
# callsite. Using string constants (not f-string interpolations of
# literals) also makes static linting easier.

ICON_SUCCESS = "✅"
ICON_WARNING = "⚠️ "
ICON_ERROR = "❌"
ICON_INFO = "📊"
ICON_SEARCH = "🔍"
ICON_BRAIN = "🧠"
ICON_CLIPBOARD = "📋"
ICON_BULB = "💡"
ICON_PENDING = "⏳"


def print_success(message: str, file: Any = None) -> None:
    """Print a success message with ✅ prefix.

    Args:
        message: The text to print (without the emoji prefix)
        file: Stream to write to (default: stdout)
    """
    print(f"{ICON_SUCCESS} {message}", file=file)


def print_warning(message: str, file: Any = None) -> None:
    """Print a warning message with ⚠️ prefix."""
    print(f"{ICON_WARNING} {message}", file=file)


def print_error(message: str, file: Any = None) -> None:
    """Print an error message with ❌ prefix."""
    print(f"{ICON_ERROR} {message}", file=file)


def print_info(message: str, file: Any = None) -> None:
    """Print an info message with 📊 prefix."""
    print(f"{ICON_INFO} {message}", file=file)


def print_json(payload: Any, file: Any = None) -> None:
    """Print a JSON payload to stdout (or a custom stream).

    Used for the agent-friendly JSON output path (e.g. ``ingest``
    without ``--self-create``). The leading newline matches the
    existing convention in ``cli/commands.py:162``.
    """
    print(f"\n{json.dumps(payload, ensure_ascii=False, indent=2)}", file=file)


# Status check helper ------------------------------------------------------

# Known status values from the result['status'] field across the
# codebase. Centralized here so adding a new status value is a
# one-line change.

KNOWN_STATUSES: frozenset[str] = frozenset({
    "ok",
    "already_exists",
    "mcp_config_added",
    "created",
    "skipped",
    "error",
    "pending",
    "done",
})


def is_known_status(status: str) -> bool:
    """Return True if ``status`` is a recognized value.

    This is a soft check — new status values can be added without
    changing this list. It exists primarily for documentation
    purposes and to give future static checks (lint rules) a
    single source of truth.
    """
    return status in KNOWN_STATUSES


# Exit codes ---------------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2  # argparse-style: invalid usage


def exit_with_error(message: str, code: int = EXIT_ERROR) -> NoReturn:
    """Print an error message and exit with the given code.

    Used by ``main()`` after catching ``CommandError`` or for
    unrecoverable argparse errors.
    """
    print_error(message)
    raise SystemExit(code)


def stderr_print(message: str) -> None:
    """Print to stderr.

    The existing CLI uses ``file=sys.stderr`` for ingest progress
    messages, batch progress, etc. This helper centralizes that
    pattern.
    """
    print(message, file=sys.stderr)
