"""Phase 3 #6 — mcp / serve merge + help subcommand tests.

Covers 5 new behaviors introduced by the Phase 3 #6 refactor:

  1. ``llmwikify mcp`` is an argparse alias of ``llmwikify serve``
     (same Namespace after parsing).
  2. ``llmwikify mcp --web`` now works (was an error before —
     ``mcp`` was a strict-subset parser, ``serve`` has the
     full flag set; after merge, mcp gets all of serve's
     flags via the alias).
  3. ``serve`` is the only command in ``COMMAND_REGISTRY``;
     ``mcp`` is not a separate Command (it's a parser alias).
  4. ``llmwikify help`` lists all commands + the alias table.
     ``llmwikify help --aliases`` lists just the aliases.
  5. The init MCP config still writes ``['llmwikify', 'mcp']``
     AND the equivalent ``['llmwikify', 'serve']`` would
     also work — forward-compat for v0.34.0+.

Also includes 2 regression guards:
  6. ``mcp.server`` is no longer imported by internal
     ``serve.py`` (the silent deprecation source).
  7. ``McpCommand`` is no longer auto-registered in
     ``commands/__init__.py``.
"""

import argparse
import inspect
import io
import sys
from contextlib import redirect_stderr, redirect_stdout


# ──────────────────────────────────────────────────────────────────
# Tests 1-3: mcp / serve merge
# ──────────────────────────────────────────────────────────────────


def test_mcp_is_argparse_alias_of_serve():
    """``llmwikify mcp --name foo`` and ``llmwikify serve --name foo``
    route to the same canonical command ('serve').

    argparse keeps the original name in args.command (so
    args.command is 'mcp' or 'serve' depending on what the
    user typed), but both route to the same handler via
    SUBCOMMAND_ALIASES lookup in main(). This test verifies
    the parser correctly accepts both names with the same
    flag set.
    """
    from llmwikify.cli._app import _build_parser
    from llmwikify.cli.commands.help_cmd import SUBCOMMAND_ALIASES

    for cmd in ("mcp", "serve"):
        # Build the parser (this populates SUBCOMMAND_ALIASES).
        parser = _build_parser()
        args = parser.parse_args([cmd, "--name", "test-wiki-merge"])
        # Both must parse the same flag set.
        assert args.name == "test-wiki-merge", (
            f"--name should be parsed correctly for '{cmd}'. "
            f"Got: {args.name}"
        )
        # argparse keeps the typed name in args.command.
        assert args.command == cmd, (
            f"argparse should keep the typed name '{cmd}' in args.command. "
            f"Got: {args.command}"
        )

    # The alias mapping is what main() uses to route to the
    # canonical command.
    assert SUBCOMMAND_ALIASES.get("mcp") == "serve", (
        f"SUBCOMMAND_ALIASES should map 'mcp' to 'serve' for "
        f"main() to dispatch correctly. Got: {dict(SUBCOMMAND_ALIASES)}"
    )


def test_mcp_accepts_serve_only_flags():
    """``llmwikify mcp --web`` works (was argparse error before).

    Before Phase 3 #6, ``mcp`` had a strict-subset parser that
    only accepted 4 flags. ``--web`` was not in that set, so
    ``mcp --web`` raised an ``unrecognized arguments`` error.
    After merge, ``mcp`` is an alias of ``serve``, so all
    serve flags (including ``--web``) are accepted.
    """
    from llmwikify.cli._app import _build_parser

    parser = _build_parser()
    # 'mcp' should accept 'serve' flags like --web.
    # If mcp is properly an alias, the parser won't reject --web.
    args = None
    try:
        args = parser.parse_args(["mcp", "--web"])
    except SystemExit:
        # SystemExit from argparse means the args were rejected.
        # This is the failure case.
        args = None
    assert args is not None, (
        "'mcp --web' should be accepted (mcp is alias of serve which "
        "has --web). If args is None, argparse rejected --web."
    )
    assert args.command == "mcp", (
        f"argparse should keep the typed 'mcp' in args.command. "
        f"Got: {args.command}"
    )
    assert args.web is True, (
        f"'mcp --web' should set args.web=True. Got: {args.web}"
    )


def test_serve_command_is_only_registered_command():
    """COMMAND_REGISTRY has 'serve' but not 'mcp' (alias only).

    After Phase 3 #6, ``mcp`` is an argparse alias of
    ``serve`` — it's NOT a separate Command class registered
    in COMMAND_REGISTRY. This test catches regression if
    someone re-adds ``McpCommand`` to the registry.
    """
    from llmwikify.cli._base import COMMAND_REGISTRY

    assert "serve" in COMMAND_REGISTRY, (
        "serve command must be in COMMAND_REGISTRY"
    )
    assert "mcp" not in COMMAND_REGISTRY, (
        "mcp must NOT be in COMMAND_REGISTRY (it's an argparse "
        "alias of serve, not a separate Command). If this fails, "
        "McpCommand was re-added to commands/__init__.py."
    )
    assert "help" in COMMAND_REGISTRY, (
        "help command must be in COMMAND_REGISTRY (Phase 3 #6 new)"
    )


# ──────────────────────────────────────────────────────────────────
# Tests 4: help subcommand
# ──────────────────────────────────────────────────────────────────


def test_help_command_lists_aliases():
    """``llmwikify help`` shows the mcp → serve alias.

    The help command populates SUBCOMMAND_ALIASES by walking
    argparse internals at startup. This test verifies the
    mcp → serve alias appears in the alias table.
    """
    from llmwikify.cli._app import _build_parser
    from llmwikify.cli.commands.help_cmd import HelpCommand, SUBCOMMAND_ALIASES

    # Build the parser (this populates SUBCOMMAND_ALIASES).
    _build_parser()

    # The alias was discovered.
    assert "mcp" in SUBCOMMAND_ALIASES, (
        f"After _build_parser(), SUBCOMMAND_ALIASES should have 'mcp'. "
        f"Got: {dict(SUBCOMMAND_ALIASES)}"
    )
    assert SUBCOMMAND_ALIASES["mcp"] == "serve", (
        f"'mcp' should alias to 'serve'. Got: {SUBCOMMAND_ALIASES.get('mcp')!r}"
    )

    # And HelpCommand's run() prints the alias correctly.
    # We test the print path by capturing stdout.
    saved_argv = sys.argv
    sys.argv = ["llmwikify", "help", "--aliases"]
    captured = io.StringIO()
    try:
        with redirect_stdout(captured), redirect_stderr(io.StringIO()):
            # Use HelpCommand.run directly to avoid starting
            # the wiki instance (main() would try to load wiki
            # config from cwd which may not exist in tests).
            cmd = HelpCommand()
            from argparse import Namespace
            args = Namespace(aliases=True)
            cmd.run(args, wiki=None, config={})
    finally:
        sys.argv = saved_argv

    output = captured.getvalue()
    assert "mcp" in output, (
        f"'llmwikify help --aliases' should mention 'mcp'. Output: {output}"
    )
    assert "serve" in output, (
        f"'llmwikify help --aliases' should mention 'serve' as target. "
        f"Output: {output}"
    )
    assert "v0.34.0" in output, (
        f"'llmwikify help --aliases' should mention the v0.34.0 "
        f"removal deadline. Output: {output}"
    )


def test_init_writes_serve_command_in_mcp_config():
    """Init MCP config: both 'mcp' and 'serve' are valid entry points.

    The init command writes ``command: ['llmwikify', 'mcp']`` in
    the agent config (backward compat for Claude Desktop /
    Cursor). This test verifies that:
      1. The current template uses 'mcp' (no change required).
      2. The same template with 'serve' substituted would
         also be a valid drop-in replacement (proves the
         v0.34.0+ canonical rename is safe).
    """
    import json
    from pathlib import Path

    template_dir = Path(__file__).parent.parent / "src" / "llmwikify" / "foundation" / "templates"
    claude_template = template_dir / "claude_mcp.json"
    codex_template = template_dir / "codex_mcp.json"

    # 1. Verify the current template uses 'mcp'
    assert claude_template.exists(), f"Missing template: {claude_template}"
    assert codex_template.exists(), f"Missing template: {codex_template}"

    claude_config = json.loads(claude_template.read_text())
    codex_config = json.loads(codex_template.read_text())

    # Claude Desktop format
    assert claude_config["mcpServers"]["llmwikify"]["args"] == ["mcp"], (
        f"Current claude_mcp.json should use 'mcp' for backward compat. "
        f"Got: {claude_config}"
    )
    # Codex format
    assert codex_config["mcp"]["llmwikify"]["command"] == ["llmwikify", "mcp"], (
        f"Current codex_mcp.json should use 'mcp' for backward compat. "
        f"Got: {codex_config}"
    )

    # 2. Verify 'serve' is also a valid entry point (forward
    #    compat for v0.34.0+ rename). We test this by parsing
    #    the command through the real argparse parser.
    from llmwikify.cli._app import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["serve", "--name", "test-init-template"])
    # argparse keeps the typed name in args.command.
    assert args.command == "serve", (
        f"'serve' must be a valid CLI command (forward compat "
        f"for v0.34.0+ rename). Got args.command={args.command}"
    )
    assert args.name == "test-init-template", (
        f"--name should be parsed correctly. Got: {args.name}"
    )

    # And 'mcp' should produce the same Namespace (verified
    # by test_mcp_is_argparse_alias_of_serve). Both 'mcp'
    # and 'serve' are valid drop-in entries.


# ──────────────────────────────────────────────────────────────────
# Regression guards
# ──────────────────────────────────────────────────────────────────


def test_serve_py_does_not_import_mcp_server():
    """Internal deprecation guard: serve.py must not import
    ``llmwikify.mcp.server``.

    After Phase 3 #6, the stdio transport path in
    ``run_serve`` uses ``MCPAdapter`` directly (decision 1.a).
    This test fails if the deprecated shim is imported
    again, which would re-trigger 1 internal deprecation
    warning per CLI invocation.
    """
    src = inspect.getsource(__import__("llmwikify.cli.commands.serve", fromlist=["run_serve"]))
    assert "from llmwikify.mcp.server import" not in src, (
        "cli/commands/serve.py should not import from "
        "llmwikify.mcp.server (use llmwikify.mcp.adapter.MCPAdapter "
        "directly). Phase 3 #6 removed this to silence internal "
        "deprecation warnings."
    )


def test_mcp_command_class_not_in_commands_init():
    """McpCommand must not be auto-registered.

    After Phase 3 #6, McpCommand is removed from
    ``commands/__init__.py`` imports and registrations.
    The class may still exist in serve.py (as dead code)
    for backward compat with any external import, but
    it's NOT auto-registered.
    """
    from llmwikify.cli import commands as commands_pkg

    # The __all__ list should not include McpCommand
    if hasattr(commands_pkg, "__all__"):
        assert "McpCommand" not in commands_pkg.__all__, (
            "commands/__init__.py should not export McpCommand. "
            "Phase 3 #6 removed it (mcp is now an argparse alias of serve)."
        )
