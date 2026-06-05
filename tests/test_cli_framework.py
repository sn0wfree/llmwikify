"""Tests for the CLI command framework (Phase 1 #2 / C1).

C1 establishes the framework — ``_base.py`` (Command protocol +
registry), ``_output.py`` (print helpers + emoji constants),
``_config.py`` (config loading). No commands are migrated yet.

This test file validates the framework in isolation:
- Command protocol is runtime-checkable
- Registry registers/looks up commands by name
- Duplicate registration raises
- Print helpers emit the right emoji prefix
- Status check helper recognizes known statuses
- Config loading honors WIKI_ROOT env var and falls back to cwd
- Config loading returns empty dict when no .wiki-config.yaml
- Config loading logs a warning and returns empty dict on YAML error
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest


# ============================================================================
# _base.py — Command protocol and registry
# ============================================================================


class _DummyCommand:
    """Minimal command implementation for testing the protocol."""

    name = "dummy"
    help = "A dummy command for testing"

    def setup_parser(self, subparsers):  # pragma: no cover - not exercised
        pass

    def run(self, args, wiki_root, config):  # pragma: no cover - not exercised
        return 0


def test_command_protocol_is_runtime_checkable():
    """DummyCommand is recognized as a Command at runtime."""
    from llmwikify.cli._base import Command

    c = _DummyCommand()
    assert isinstance(c, Command)


def test_register_command_adds_to_registry():
    """register_command adds the command under its ``name`` attribute."""
    from llmwikify.cli._base import (
        COMMAND_REGISTRY,
        get_command,
        register_command,
    )

    initial_count = len(COMMAND_REGISTRY)
    c = _DummyCommand()
    register_command(c)
    try:
        assert "dummy" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["dummy"] is c
        assert get_command("dummy") is c
        assert len(COMMAND_REGISTRY) == initial_count + 1
    finally:
        COMMAND_REGISTRY.pop("dummy", None)


def test_register_command_duplicate_raises():
    """Registering the same name twice raises ValueError."""
    from llmwikify.cli._base import COMMAND_REGISTRY, register_command

    c1 = _DummyCommand()
    c2 = _DummyCommand()
    register_command(c1)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_command(c2)
    finally:
        COMMAND_REGISTRY.pop("dummy", None)


def test_register_command_decorator_form():
    """register_command works as a decorator (returns the class)."""
    from llmwikify.cli._base import COMMAND_REGISTRY, register_command

    @register_command
    class DecoratedCommand:
        name = "decorated"
        help = "decorated"

        def setup_parser(self, subparsers):
            pass

        def run(self, args, wiki_root, config):
            return 0

    try:
        assert "decorated" in COMMAND_REGISTRY
        # When used as a decorator on a class, the registry stores
        # the class itself (not an instance). Its __name__ is
        # "DecoratedCommand".
        assert COMMAND_REGISTRY["decorated"].__name__ == "DecoratedCommand"
    finally:
        COMMAND_REGISTRY.pop("decorated", None)


def test_get_command_returns_none_for_unknown():
    """get_command returns None for unregistered names (no exception)."""
    from llmwikify.cli._base import get_command

    assert get_command("definitely_not_registered_xyz") is None


def test_registered_command_names_is_sorted():
    """registered_command_names returns a sorted list."""
    from llmwikify.cli._base import COMMAND_REGISTRY, register_command, registered_command_names

    @register_command
    class CmdZ:
        name = "z_cmd"
        help = ""
        def setup_parser(self, sp): pass
        def run(self, *a, **kw): return 0

    @register_command
    class CmdA:
        name = "a_cmd"
        help = ""
        def setup_parser(self, sp): pass
        def run(self, *a, **kw): return 0

    try:
        names = registered_command_names()
        assert names == sorted(names)
        assert "a_cmd" in names
        assert "z_cmd" in names
    finally:
        COMMAND_REGISTRY.pop("z_cmd", None)
        COMMAND_REGISTRY.pop("a_cmd", None)


def test_command_error_carries_message_and_code():
    """CommandError exposes ``message`` and ``exit_code`` attributes."""
    from llmwikify.cli._base import CommandError

    e = CommandError("something went wrong", exit_code=42)
    assert e.message == "something went wrong"
    assert e.exit_code == 42
    assert str(e) == "something went wrong"


def test_command_error_default_exit_code_is_one():
    """CommandError defaults to exit code 1."""
    from llmwikify.cli._base import CommandError

    e = CommandError("oops")
    assert e.exit_code == 1


# ============================================================================
# _output.py — print helpers and emoji constants
# ============================================================================


def test_emoji_constants_are_correct():
    """Emoji constants match the strings used throughout the existing CLI."""
    from llmwikify.cli._output import (
        ICON_BRAIN,
        ICON_BULB,
        ICON_CLIPBOARD,
        ICON_ERROR,
        ICON_INFO,
        ICON_PENDING,
        ICON_SEARCH,
        ICON_SUCCESS,
        ICON_WARNING,
    )

    assert ICON_SUCCESS == "✅"
    assert ICON_WARNING == "⚠️ "
    assert ICON_ERROR == "❌"
    assert ICON_INFO == "📊"
    assert ICON_SEARCH == "🔍"
    assert ICON_BRAIN == "🧠"
    assert ICON_CLIPBOARD == "📋"
    assert ICON_BULB == "💡"
    assert ICON_PENDING == "⏳"


def test_print_success_emits_checkmark_prefix():
    """print_success prefixes the message with the success icon."""
    from llmwikify.cli._output import ICON_SUCCESS, print_success

    buf = io.StringIO()
    print_success("done", file=buf)
    assert buf.getvalue() == f"{ICON_SUCCESS} done\n"


def test_print_warning_emits_warning_prefix():
    """print_warning prefixes the message with the warning icon."""
    from llmwikify.cli._output import ICON_WARNING, print_warning

    buf = io.StringIO()
    print_warning("careful", file=buf)
    assert buf.getvalue() == f"{ICON_WARNING} careful\n"


def test_print_error_emits_error_prefix():
    """print_error prefixes the message with the error icon."""
    from llmwikify.cli._output import ICON_ERROR, print_error

    buf = io.StringIO()
    print_error("failed", file=buf)
    assert buf.getvalue() == f"{ICON_ERROR} failed\n"


def test_print_info_emits_info_prefix():
    """print_info prefixes the message with the info icon."""
    from llmwikify.cli._output import ICON_INFO, print_info

    buf = io.StringIO()
    print_info("5 results", file=buf)
    assert buf.getvalue() == f"{ICON_INFO} 5 results\n"


def test_print_json_emits_valid_json_on_stdout():
    """print_json writes a leading newline then pretty-printed JSON."""
    from llmwikify.cli._output import print_json

    buf = io.StringIO()
    print_json({"key": "value", "list": [1, 2]}, file=buf)
    output = buf.getvalue()
    assert output.startswith("\n")
    parsed = json.loads(output.lstrip())
    assert parsed == {"key": "value", "list": [1, 2]}


def test_print_json_handles_unicode():
    """print_json uses ensure_ascii=False (matches the existing CLI)."""
    from llmwikify.cli._output import print_json

    buf = io.StringIO()
    print_json({"name": "中文"}, file=buf)
    output = buf.getvalue()
    # The raw Chinese characters should appear (not \uXXXX escapes)
    assert "中文" in output


def test_known_statuses_contains_common_values():
    """is_known_status returns True for values used by the existing CLI."""
    from llmwikify.cli._output import is_known_status

    for status in ("ok", "already_exists", "mcp_config_added", "skipped", "error"):
        assert is_known_status(status), f"missing known status: {status}"


def test_is_known_status_returns_false_for_unknown():
    """is_known_status returns False for unrecognized status values."""
    from llmwikify.cli._output import is_known_status

    assert is_known_status("this_is_not_a_status") is False
    assert is_known_status("") is False


def test_exit_constants_have_expected_values():
    """Exit code constants match the conventional Unix exit codes."""
    from llmwikify.cli._output import EXIT_ERROR, EXIT_OK, EXIT_USAGE

    assert EXIT_OK == 0
    assert EXIT_ERROR == 1
    assert EXIT_USAGE == 2


def test_exit_with_error_raises_systemexit():
    """exit_with_error raises SystemExit with the given code."""
    from llmwikify.cli._output import exit_with_error

    with pytest.raises(SystemExit) as exc_info:
        exit_with_error("nope", code=42)
    assert exc_info.value.code == 42


def test_stderr_print_writes_to_stderr(capsys):
    """stderr_print writes to sys.stderr (matches existing CLI behavior)."""
    from llmwikify.cli._output import stderr_print

    stderr_print("to stderr")
    captured = capsys.readouterr()
    assert captured.err == "to stderr\n"
    assert captured.out == ""


# ============================================================================
# _config.py — config loading
# ============================================================================


def test_load_cli_config_returns_cwd_when_no_env(tmp_path, monkeypatch):
    """With no WIKI_ROOT and no argument, the cwd is used."""
    monkeypatch.delenv("WIKI_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    from llmwikify.cli._config import load_cli_config

    root, config = load_cli_config()
    assert root == tmp_path
    assert config == {}


def test_load_cli_config_honors_explicit_root(tmp_path):
    """Explicit wiki_root argument wins over env var and cwd."""
    explicit = tmp_path / "my_wiki"
    explicit.mkdir()

    from llmwikify.cli._config import load_cli_config

    root, config = load_cli_config(wiki_root=explicit)
    assert root == explicit
    assert config == {}


def test_load_cli_config_honors_wiki_root_env(tmp_path, monkeypatch):
    """WIKI_ROOT env var is used when wiki_root argument is None."""
    explicit = tmp_path / "env_wiki"
    explicit.mkdir()
    monkeypatch.setenv("WIKI_ROOT", str(explicit))

    from llmwikify.cli._config import load_cli_config

    root, _ = load_cli_config()
    assert root == explicit


def test_load_cli_config_loads_existing_yaml(tmp_path, monkeypatch):
    """An existing .wiki-config.yaml is parsed and returned."""
    monkeypatch.chdir(tmp_path)
    cfg_file = tmp_path / ".wiki-config.yaml"
    cfg_file.write_text("llm:\n  enabled: true\n  model: foo\n")

    from llmwikify.cli._config import load_cli_config

    root, config = load_cli_config()
    assert root == tmp_path
    assert config == {"llm": {"enabled": True, "model": "foo"}}


def test_load_cli_config_handles_invalid_yaml(tmp_path, monkeypatch, caplog):
    """Invalid YAML logs a warning and returns empty config dict."""
    import logging

    monkeypatch.chdir(tmp_path)
    cfg_file = tmp_path / ".wiki-config.yaml"
    cfg_file.write_text("this: is: not: valid: yaml: at: all: :::")

    from llmwikify.cli._config import load_cli_config

    with caplog.at_level(logging.WARNING):
        root, config = load_cli_config()
    assert root == tmp_path
    assert config == {}
    # A warning about the failed load was emitted
    assert any("Failed to load config" in r.message for r in caplog.records)


def test_load_cli_config_handles_empty_yaml(tmp_path, monkeypatch):
    """A YAML file that parses to None/empty returns empty dict (not None)."""
    monkeypatch.chdir(tmp_path)
    cfg_file = tmp_path / ".wiki-config.yaml"
    cfg_file.write_text("")  # Empty file → yaml.safe_load returns None

    from llmwikify.cli._config import load_cli_config

    _, config = load_cli_config()
    assert config == {}


# ============================================================================
# Module-level imports — make sure each module imports cleanly
# ============================================================================


def test_base_module_imports():
    """cli._base imports without side effects."""
    from llmwikify.cli import _base

    assert hasattr(_base, "Command")
    assert hasattr(_base, "COMMAND_REGISTRY")
    assert hasattr(_base, "register_command")
    assert hasattr(_base, "get_command")
    assert hasattr(_base, "registered_command_names")
    assert hasattr(_base, "CommandError")


def test_output_module_imports():
    """cli._output imports without side effects."""
    from llmwikify.cli import _output

    for name in (
        "ICON_SUCCESS",
        "ICON_WARNING",
        "ICON_ERROR",
        "print_success",
        "print_warning",
        "print_error",
        "print_json",
        "is_known_status",
        "EXIT_OK",
        "EXIT_ERROR",
        "exit_with_error",
        "stderr_print",
    ):
        assert hasattr(_output, name), f"missing export: {name}"


def test_config_module_imports():
    """cli._config imports without side effects."""
    from llmwikify.cli import _config

    assert hasattr(_config, "load_cli_config")
