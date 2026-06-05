"""Verify the 10 simple commands are extracted and accessible.

Phase 1 #2 / C2 — these tests validate the post-extraction state:

- Each of the 10 simple commands has a ``Command`` class in
  ``llmwikify.cli.commands.<name>``
- The free function ``run_<name>(wiki, args)`` exists in the
  same module
- The Command class has a unique ``name`` and a ``run()`` method
  that calls the function with the right arguments
- WikiCLI's public method still works (1-line delegate to the
  function) — backward compat is preserved
- The 10 new files are physically separate (not inlined back
  into _app.py)
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path


# The 10 migrated commands: (submodule_name, class_name, run_fn_name, wiki_cli_method)
MIGRATED_COMMANDS = [
    ("init_cmd", "InitCommand", "run_init", "init"),
    ("ingest", "IngestCommand", "run_ingest", "ingest"),
    ("status", "StatusCommand", "run_status", "status"),
    ("log_cmd", "LogCommand", "run_log", "log"),
    ("sink_status", "SinkStatusCommand", "run_sink_status", "sink_status"),
    ("write_page", "WritePageCommand", "run_write_page", "write_page"),
    ("read_page", "ReadPageCommand", "run_read_page", "read_page"),
    ("search", "SearchCommand", "run_search", "search"),
    ("build_index", "BuildIndexCommand", "run_build_index", "build_index"),
    ("fix_wikilinks", "FixWikilinksCommand", "run_fix_wikilinks", "fix_wikilinks"),
]


# ============================================================================
# Module structure
# ============================================================================


def test_commands_subpackage_exists():
    """llmwikify.cli.commands is a subpackage, not the old commands.py file."""
    from llmwikify.cli import commands

    # Subpackages have __path__ attribute
    assert hasattr(commands, "__path__"), "cli.commands should be a subpackage"
    assert commands.__file__ is not None


def test_commands_subpackage_exports_all_ten():
    """All 10 migrated commands are exported from cli.commands."""
    from llmwikify.cli import commands

    for _, class_name, run_fn_name, _ in MIGRATED_COMMANDS:
        assert hasattr(commands, class_name), f"missing {class_name} in cli.commands"
        assert hasattr(commands, run_fn_name), f"missing {run_fn_name} in cli.commands"


def test_each_command_module_is_a_separate_file():
    """Each command lives in its own .py file under cli/commands/."""
    commands_dir = Path("src/llmwikify/cli/commands")

    for submodule, _, _, _ in MIGRATED_COMMANDS:
        path = commands_dir / f"{submodule}.py"
        assert path.exists(), f"missing file: {path}"


# ============================================================================
# Command class shape
# ============================================================================


def test_each_command_class_has_name_and_run():
    """Each Command class has ``name`` (str) and a callable ``run()``."""
    from llmwikify.cli import commands

    for _, class_name, _, _ in MIGRATED_COMMANDS:
        cls = getattr(commands, class_name)
        assert isinstance(cls.name, str), f"{class_name}.name must be a string"
        assert callable(cls.run), f"{class_name}.run must be callable"


def test_command_names_are_unique():
    """No two migrated commands share the same ``name`` attribute."""
    from llmwikify.cli import commands

    names = []
    for _, class_name, _, _ in MIGRATED_COMMANDS:
        cls = getattr(commands, class_name)
        names.append(cls.name)

    assert len(names) == len(set(names)), f"duplicate command names: {names}"


def test_command_run_delegates_to_free_function():
    """Each Command.run() method delegates to the matching run_<name> function."""
    from llmwikify.cli import commands

    for _, class_name, run_fn_name, _ in MIGRATED_COMMANDS:
        cls = getattr(commands, class_name)
        run_fn = getattr(commands, run_fn_name)
        # The class source should reference the function by name
        src = inspect.getsource(cls)
        assert run_fn_name in src, (
            f"{class_name}.run() should delegate to {run_fn_name}()"
        )


# ============================================================================
# WikiCLI backward compatibility
# ============================================================================


def test_wiki_cli_delegates_migrated_methods():
    """WikiCLI's migrated methods are 1-line delegates to run_<name> functions."""
    from llmwikify.cli import WikiCLI

    for _, class_name, run_fn_name, method_name in MIGRATED_COMMANDS:
        method = getattr(WikiCLI, method_name)
        src = inspect.getsource(method)
        # The method body should be a single return statement
        # that calls the run_<name> function
        body = src.strip()
        assert body.startswith("def "), f"unexpected method source: {body[:80]}"
        # Look for a call to the function name
        assert run_fn_name in body, (
            f"WikiCLI.{method_name} should call {run_fn_name}"
        )


def test_wiki_cli_methods_not_duplicated_in_app_file():
    """The 10 migrated methods do NOT have their full bodies in _app.py.

    This is the structural guard against someone re-inlining
    the extracted code back into _app.py.
    """
    app_src = Path("src/llmwikify/cli/_app.py").read_text()
    for _, _, run_fn_name, method_name in MIGRATED_COMMANDS:
        # The function call site is OK — what we forbid is a second
        # full method body (e.g., `def method_name(self, args):` with
        # the original logic).
        # Pattern: "def method_name(self, args)" at start of line
        pattern = rf"^\s+def {method_name}\(self, args: Any\)"
        match = re.search(pattern, app_src, re.MULTILINE)
        if match:
            # Allow it only if it's the WikiCLI delegator (1-line)
            # — we can detect this by looking at how many lines
            # follow until the next def
            start = match.start()
            rest = app_src[start:]
            # Find the next def
            next_def = re.search(r"^\s+def ", rest[1:], re.MULTILINE)
            if next_def:
                method_body = rest[:next_def.start() + 1]
            else:
                method_body = rest
            # Count newlines — should be 4 (def + return + blank + 0)
            # for a 1-line delegator
            line_count = len(method_body.strip().splitlines())
            assert line_count <= 4, (
                f"WikiCLI.{method_name} in _app.py has {line_count} lines — "
                f"looks like a full implementation was re-inlined. Should be "
                f"a 1-line delegate to {run_fn_name}()."
            )


# ============================================================================
# The old file is gone
# ============================================================================


def test_old_commands_py_file_is_gone():
    """The original commands.py file was renamed to _app.py to avoid shadowing."""
    assert not Path("src/llmwikify/cli/commands.py").exists(), (
        "commands.py should have been renamed to _app.py"
    )
    assert Path("src/llmwikify/cli/_app.py").exists(), (
        "_app.py should exist as the new home for WikiCLI + main()"
    )


# ============================================================================
# Imports cleanliness
# ============================================================================


def test_app_file_imports_run_functions_from_commands_subpackage():
    """_app.py imports the 10 run_<name> functions from the new subpackage."""
    src = Path("src/llmwikify/cli/_app.py").read_text()
    for _, _, run_fn_name, _ in MIGRATED_COMMANDS:
        # There should be an import like:
        # from .commands.X import run_Y
        # or
        # from .commands import run_Y
        assert run_fn_name in src, (
            f"_app.py should reference {run_fn_name}"
        )


def test_cli_init_does_not_import_from_old_path():
    """cli/__init__.py imports from _app, not from commands (the subpackage)."""
    src = Path("src/llmwikify/cli/__init__.py").read_text()
    assert "from ._app import" in src, (
        "cli/__init__.py should import from ._app"
    )
    assert "from .commands import WikiCLI" not in src, (
        "cli/__init__.py must not import WikiCLI from the commands subpackage"
    )
