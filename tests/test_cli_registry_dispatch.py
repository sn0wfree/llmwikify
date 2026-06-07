"""Verify main() uses the registry for both parser setup AND dispatch.

Phase 1 #2 / C3 — the second half of the refactor: main() no longer
maintains a hand-written argparse block of ~260 lines + a 27-entry
dispatch dict. It now iterates ``COMMAND_REGISTRY`` to set up parsers
and look up the right ``Command.run()`` to invoke.

These tests validate the new dispatch path:
- All 26 commands (10 C2 + 16 C3) are in ``COMMAND_REGISTRY``
- ``main()``'s body references the registry, not a hand-written
  command dict
- The hand-written parser setup for each command is gone (replaced
  by per-Command ``setup_parser()`` calls)
- ``main()`` uses ``get_command(args.command).run(args, wiki_root,
  config)`` for dispatch
- The ``load_cli_config`` helper from C1 is used (not inlined config
  loading)
"""

from __future__ import annotations

import inspect
import re


ALL_26_COMMANDS = [
    # C2 (10 simple)
    "init", "ingest", "status", "log", "sink-status",
    "write_page", "read_page", "search", "build-index", "fix-wikilinks",
    # C3 (16 complex — note: serve and mcp share, so 16 entries)
    "analyze-source", "lint", "references", "batch", "synthesize",
    "watch", "graph-query", "export-graph", "community-detect", "report",
    "wikis", "suggest-synthesis", "knowledge-gaps", "graph-analyze",
    "serve", "qmd", "db",
]


# ============================================================================
# Registry coverage
# ============================================================================


def test_all_26_commands_in_registry():
    """Every CLI command has a corresponding entry in COMMAND_REGISTRY."""
    from llmwikify.interfaces.cli._base import COMMAND_REGISTRY

    for cmd_name in ALL_26_COMMANDS:
        assert cmd_name in COMMAND_REGISTRY, (
            f"command '{cmd_name}' is not in COMMAND_REGISTRY. "
            f"Available: {sorted(COMMAND_REGISTRY.keys())}"
        )


def test_registry_size_matches_command_count():
    """The registry should have at least 26 entries (mcp is an alias of serve)."""
    from llmwikify.interfaces.cli._base import COMMAND_REGISTRY

    # mcp is a separate Command that delegates to the same handler,
    # so it's a separate entry. We expect 27 entries (26 + mcp).
    assert len(COMMAND_REGISTRY) >= 26, (
        f"expected ≥26 commands, got {len(COMMAND_REGISTRY)}"
    )


def test_each_registry_command_has_setup_parser():
    """Each registered command has a callable setup_parser."""
    from llmwikify.interfaces.cli._base import COMMAND_REGISTRY

    for name, cmd in COMMAND_REGISTRY.items():
        assert callable(cmd.setup_parser), (
            f"command '{name}' has no setup_parser method"
        )


def test_each_registry_command_has_run():
    """Each registered command has a callable run."""
    from llmwikify.interfaces.cli._base import COMMAND_REGISTRY

    for name, cmd in COMMAND_REGISTRY.items():
        assert callable(cmd.run), (
            f"command '{name}' has no run method"
        )


# ============================================================================
# main() body uses registry
# ============================================================================


def test_main_references_command_registry():
    """main() imports/uses COMMAND_REGISTRY (not a hand-written dict)."""
    from llmwikify.interfaces.cli import _app

    src = inspect.getsource(_app.main)
    assert "COMMAND_REGISTRY" in src, (
        "main() should reference COMMAND_REGISTRY for parser setup"
    )
    assert "get_command" in src, (
        "main() should look up the command via get_command()"
    )


def test_main_does_not_contain_handwritten_command_dict():
    """main() no longer maintains a 27-entry ``commands = {…}`` dict."""
    from llmwikify.interfaces.cli import _app

    src = inspect.getsource(_app.main)
    # The old dict was: ``commands = {\n        'init': cli.init,``
    assert not re.search(r"^\s*commands\s*=\s*\{", src, re.MULTILINE), (
        "main() should not have a hand-written commands = {…} dict"
    )


def test_main_uses_load_cli_config_helper():
    """main() delegates config loading to ``cli._config.load_cli_config``."""
    from llmwikify.interfaces.cli import _app

    src = inspect.getsource(_app.main)
    assert "load_cli_config" in src, (
        "main() should use load_cli_config (C1 helper) for config loading"
    )


def test_main_does_not_inline_yaml_loading():
    """main() no longer inlines ``yaml.safe_load(config_file.read_text())``."""
    from llmwikify.interfaces.cli import _app

    src = inspect.getsource(_app.main)
    assert "yaml.safe_load" not in src, (
        "main() should not inline YAML loading — use load_cli_config"
    )
    assert ".wiki-config.yaml" not in src, (
        "main() should not reference .wiki-config.yaml directly"
    )


def test_main_iterates_registry_to_setup_parsers():
    """main() calls setup_parser for each registered command."""
    from llmwikify.interfaces.cli import _app

    # Phase 3 #6 — the sorted(COMMAND_REGISTRY) iteration moved
    # from main() to _build_parser() (the helper that builds the
    # argparse parser, extracted in Phase 3 #6 so tests can
    # build the parser without starting the MCP server). Both
    # the parser construction AND the subparsers iteration
    # patterns are tested here.
    src = inspect.getsource(_app._build_parser)
    assert "cmd.setup_parser(subparsers)" in src, (
        "_build_parser() should call cmd.setup_parser(subparsers) "
        "for each command"
    )
    assert "sorted(COMMAND_REGISTRY)" in src, (
        "_build_parser() should iterate sorted(COMMAND_REGISTRY) "
        "for determinism"
    )


def test_main_dispatches_via_registry_run():
    """main() dispatches via ``cmd.run(args, wiki_root, config)``."""
    from llmwikify.interfaces.cli import _app

    src = inspect.getsource(_app.main)
    assert "cmd.run(args" in src, (
        "main() should dispatch via cmd.run(args, wiki_root, config)"
    )


# ============================================================================
# main() size sanity check
# ============================================================================


def test_main_body_is_much_shorter_than_before():
    """main() should be much shorter than the original 350+ line hand-written version.

    After C3, main() should be ~80-120 lines (parser + epilog + dispatch).
    If it grows back toward 300+, the registry was bypassed.
    """
    from llmwikify.interfaces.cli import _app

    src_lines = inspect.getsource(_app.main).splitlines()
    line_count = len(src_lines)
    assert line_count < 200, (
        f"main() has {line_count} lines — should be much smaller after "
        f"the registry refactor (target: <200). If it's back over 300, "
        f"the hand-written parser setup was re-introduced."
    )


# ============================================================================
# Hand-written parser blocks are gone
# ============================================================================


def test_no_handwritten_subparsers_add_parser_calls_in_main():
    """main() should not have hand-written ``subparsers.add_parser('init', ...)`` etc."""
    from llmwikify.interfaces.cli import _app

    src = inspect.getsource(_app.main)
    # The old code had lines like:
    #     p = subparsers.add_parser('init', help='Initialize wiki')
    #     p.add_argument('--overwrite', ...)
    # The new code uses cmd.setup_parser() which is called once per cmd.
    # After C3, main() should have only ONE subparsers.add_subparsers call,
    # not 26+ add_parser calls.
    add_parser_count = len(re.findall(r"add_parser\(", src))
    assert add_parser_count <= 2, (
        f"main() has {add_parser_count} add_parser() calls — should be 1 "
        f"(just subparsers.add_subparsers). Hand-written parser setup was "
        f"re-introduced."
    )


# ============================================================================
# Backward compat with WikiCLI
# ============================================================================


def test_wiki_cli_still_has_all_public_methods():
    """WikiCLI still has the 26 public methods (backward compat for tests)."""
    from llmwikify.interfaces.cli import WikiCLI

    for cmd_name in ALL_26_COMMANDS:
        # Convert command name → method name (snake_case)
        method_name = cmd_name.replace("-", "_")
        assert hasattr(WikiCLI, method_name), (
            f"WikiCLI.{method_name} is missing — backward compat broken"
        )


def test_wiki_cli_methods_are_one_line_delegates():
    """Each WikiCLI public method is a 1-line delegate to run_<name>."""
    from llmwikify.interfaces.cli import WikiCLI

    for cmd_name in ALL_26_COMMANDS:
        method_name = cmd_name.replace("-", "_")
        method = getattr(WikiCLI, method_name)
        src = inspect.getsource(method)
        body_lines = [line for line in src.splitlines() if line.strip() and not line.strip().startswith("def ") and not line.strip().startswith('"""')]
        # 1-line delegate = 1 effective line
        assert len(body_lines) <= 1, (
            f"WikiCLI.{method_name} is not a 1-line delegate "
            f"({len(body_lines)} body lines)"
        )
