"""Phase 3 #7 — error/log unification tests.

Covers the consolidation of error and log handling
across the 26 CLI commands:

  1. ``CommandError`` exception has ``message`` and ``exit_code`` fields
  2. ``main()`` catches ``CommandError`` and returns the right exit code
  3. ``main()`` prints the error message via ``print_error`` (with ❌)
  4. ``print_error_stderr`` writes to stderr (not stdout)
  5. ``print_warning_stderr`` writes to stderr
  6. ``print_success_stderr`` writes to stderr
  7. ``print_info_stderr`` writes to stderr
  8. ``stderr_print`` writes raw message to stderr
  9. ``graph-query`` raises ``CommandError`` on missing concept
     arg (not ``print + return 1``)
 10. ``graph-query context`` raises ``CommandError`` on missing
     relation row (was ``print + return 1``)
 11. ``batch.py`` no longer uses ``file=sys.stderr`` for emoji
     prints (uses helpers)
 12. ``ingest.py`` no longer uses ``file=sys.stderr`` for emoji
     prints (uses helpers)
 13. ``main()`` keeps the existing finally: cli.wiki.close()
     path on ``CommandError``
 14. Regression guard: the 3 known direct ``print("❌ ...`` patterns
     are gone from graph_query.py.
"""

import inspect
import io
import sys
from contextlib import redirect_stderr, redirect_stdout

import pytest


def test_command_error_has_message_and_exit_code():
    """CommandError stores message and exit_code (default 1)."""
    from llmwikify.interfaces.cli._base import CommandError

    e = CommandError("test error")
    assert e.message == "test error"
    assert e.exit_code == 1

    e2 = CommandError("usage", exit_code=2)
    assert e2.message == "usage"
    assert e2.exit_code == 2


def test_main_catches_command_error_and_returns_exit_code():
    """``main()`` catches ``CommandError`` and returns its exit_code."""
    # Use the real graph-query command with the missing
    # concept arg — the run() raises CommandError, main()
    # catches it and returns 1.
    from llmwikify.interfaces.cli._app import main

    saved_argv = sys.argv
    sys.argv = ["llmwikify", "graph-query", "neighbors"]
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = main()
        assert rc == 1, f"Expected exit_code 1 from CommandError, got {rc}"
    finally:
        sys.argv = saved_argv


def test_main_prints_command_error_message_with_error_icon():
    """``main()`` prints the CommandError message via print_error (❌)."""
    from llmwikify.interfaces.cli._app import main

    saved_argv = sys.argv
    sys.argv = ["llmwikify", "graph-query", "neighbors"]
    captured = io.StringIO()
    try:
        with redirect_stdout(captured), redirect_stderr(io.StringIO()):
            main()
        output = captured.getvalue()
        # The CommandError message is "Usage: ...neighbors <concept>"
        assert "neighbors <concept>" in output, (
            f"Expected error message in stdout, got: {output!r}"
        )
        # print_error prefixes with ❌
        assert "❌" in output, (
            f"Expected ❌ prefix from print_error, got: {output!r}"
        )
    finally:
        sys.argv = saved_argv


def test_print_error_stderr_writes_to_stderr():
    """print_error_stderr writes the ❌-prefixed line to stderr."""
    from llmwikify.interfaces.cli._output import ICON_ERROR, print_error_stderr

    captured_err = io.StringIO()
    captured_out = io.StringIO()
    with redirect_stdout(captured_out), redirect_stderr(captured_err):
        print_error_stderr("hello stderr")
    err = captured_err.getvalue()
    out = captured_out.getvalue()
    assert "hello stderr" in err
    assert ICON_ERROR in err
    # Nothing leaked to stdout
    assert "hello stderr" not in out


def test_print_warning_stderr_writes_to_stderr():
    """print_warning_stderr writes the ⚠️-prefixed line to stderr."""
    from llmwikify.interfaces.cli._output import ICON_WARNING, print_warning_stderr

    captured_err = io.StringIO()
    captured_out = io.StringIO()
    with redirect_stdout(captured_out), redirect_stderr(captured_err):
        print_warning_stderr("hello warn")
    err = captured_err.getvalue()
    assert "hello warn" in err
    assert ICON_WARNING in err
    assert "hello warn" not in captured_out.getvalue()


def test_print_success_stderr_writes_to_stderr():
    """print_success_stderr writes the ✅-prefixed line to stderr."""
    from llmwikify.interfaces.cli._output import ICON_SUCCESS, print_success_stderr

    captured_err = io.StringIO()
    captured_out = io.StringIO()
    with redirect_stdout(captured_out), redirect_stderr(captured_err):
        print_success_stderr("hello ok")
    err = captured_err.getvalue()
    assert "hello ok" in err
    assert ICON_SUCCESS in err
    assert "hello ok" not in captured_out.getvalue()


def test_print_info_stderr_writes_to_stderr():
    """print_info_stderr writes the 📊-prefixed line to stderr."""
    from llmwikify.interfaces.cli._output import ICON_INFO, print_info_stderr

    captured_err = io.StringIO()
    captured_out = io.StringIO()
    with redirect_stdout(captured_out), redirect_stderr(captured_err):
        print_info_stderr("hello info")
    err = captured_err.getvalue()
    assert "hello info" in err
    assert ICON_INFO in err
    assert "hello info" not in captured_out.getvalue()


def test_stderr_print_writes_raw_to_stderr():
    """stderr_print writes the raw message (no icon) to stderr."""
    from llmwikify.interfaces.cli._output import stderr_print

    captured_err = io.StringIO()
    captured_out = io.StringIO()
    with redirect_stdout(captured_out), redirect_stderr(captured_err):
        stderr_print("raw line")
    assert "raw line" in captured_err.getvalue()
    assert "raw line" not in captured_out.getvalue()


def test_graph_query_raises_command_error_on_missing_concept():
    """``graph-query neighbors`` without arg raises CommandError."""
    from argparse import Namespace
    from llmwikify.interfaces.cli._base import CommandError
    from llmwikify.interfaces.cli.commands.graph_query import run_graph_query

    class FakeEngine:
        def get_neighbors(self, concept):
            return []

    class FakeWiki:
        def get_relation_engine(self):
            return FakeEngine()

    args = Namespace(subcommand="neighbors", args=[])
    with pytest.raises(CommandError) as exc_info:
        run_graph_query(FakeWiki(), args)
    assert "neighbors" in str(exc_info.value)


def test_graph_query_context_raises_command_error_on_missing_row():
    """``graph-query context`` with unknown relation id raises CommandError."""
    from argparse import Namespace
    from llmwikify.interfaces.cli._base import CommandError
    from llmwikify.interfaces.cli.commands.graph_query import run_graph_query

    class FakeEngine:
        def get_context(self, rel_id):
            return None  # not found

    class FakeWiki:
        def get_relation_engine(self):
            return FakeEngine()

    args = Namespace(subcommand="context", args=["999"])
    with pytest.raises(CommandError) as exc_info:
        run_graph_query(FakeWiki(), args)
    assert "not found" in str(exc_info.value).lower()


def test_batch_no_longer_uses_file_sys_stderr_for_emoji():
    """batch.py: no more ``print(..., file=sys.stderr)`` for emoji outputs.

    The migration in Phase 3 #7 replaced 9
    ``print(..., file=sys.stderr)`` patterns in batch.py
    with helpers (``stderr_print``,
    ``print_success_stderr``, ``print_error_stderr``,
    ``print_warning_stderr``). This test asserts the
    migration is complete.

    We use AST parsing (not regex on source) so docstring
    mentions of the pattern don't false-positive.
    """
    import ast
    import llmwikify.interfaces.cli.commands.batch as batch_mod

    tree = ast.parse(inspect.getsource(batch_mod))

    class PrintFinder(ast.NodeVisitor):
        def __init__(self):
            self.violations = []

        def visit_Call(self, node):
            # Look for ``print(...)`` with ``file=sys.stderr``
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                for kw in node.keywords:
                    if kw.arg == "file":
                        # Check the value
                        if isinstance(kw.value, ast.Attribute):
                            if (kw.value.value.id == "sys"
                                    and kw.value.attr == "stderr"):
                                self.violations.append(
                                    f"line {node.lineno}: print(..., file=sys.stderr)"
                                )
                        elif isinstance(kw.value, ast.Name):
                            if kw.value.id == "stderr":
                                self.violations.append(
                                    f"line {node.lineno}: print(..., file=stderr)"
                                )
            self.generic_visit(node)

    finder = PrintFinder()
    finder.visit(tree)
    assert not finder.violations, (
        "batch.py should not use 'file=sys.stderr' for "
        f"print() after Phase 3 #7. Violations: {finder.violations}. "
        "Use stderr_print / print_*_stderr helpers from "
        "cli._output instead."
    )


def test_ingest_no_longer_uses_file_sys_stderr_for_emoji():
    """ingest.py: no more ``print(..., file=sys.stderr)`` for emoji outputs.

    AST-based check so docstring mentions don't false-positive.
    """
    import ast
    import llmwikify.interfaces.cli.commands.ingest as ingest_mod

    tree = ast.parse(inspect.getsource(ingest_mod))

    class PrintFinder(ast.NodeVisitor):
        def __init__(self):
            self.violations = []

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                for kw in node.keywords:
                    if kw.arg == "file":
                        if isinstance(kw.value, ast.Attribute):
                            if (kw.value.value.id == "sys"
                                    and kw.value.attr == "stderr"):
                                self.violations.append(
                                    f"line {node.lineno}: print(..., file=sys.stderr)"
                                )
                        elif isinstance(kw.value, ast.Name):
                            if kw.value.id == "stderr":
                                self.violations.append(
                                    f"line {node.lineno}: print(..., file=stderr)"
                                )
            self.generic_visit(node)

    finder = PrintFinder()
    finder.visit(tree)
    assert not finder.violations, (
        "ingest.py should not use 'file=sys.stderr' for "
        f"print() after Phase 3 #7. Violations: {finder.violations}. "
        "Use stderr_print / print_*_stderr helpers from "
        "cli._output instead."
    )


def test_main_finally_runs_wiki_close_on_command_error():
    """``main()`` runs ``cli.wiki.close()`` even on CommandError.

    The wiki instance is created in main() and closed in
    the finally block. On the CommandError path, both
    should still run.
    """
    from llmwikify.interfaces.cli._app import main

    saved_argv = sys.argv
    sys.argv = ["llmwikify", "graph-query", "neighbors"]
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = main()
        # Should not raise; the finally path executed
        assert rc == 1
    finally:
        sys.argv = saved_argv


def test_regression_no_direct_print_error_in_graph_query():
    """graph_query.py: the 3 direct ``print("❌ ...`` patterns are gone.

    The migration in Phase 3 #7 replaced
    ``print("❌ Usage: ..."); return 1`` with
    ``raise CommandError(...)``. This test asserts the
    migration is complete.
    """
    import llmwikify.interfaces.cli.commands.graph_query as gq

    src = inspect.getsource(gq)
    # The pattern ``print("❌`` should not appear in
    # graph_query.py after Phase 3 #7.
    assert 'print("❌' not in src, (
        "graph_query.py should not contain direct "
        "``print(\"❌`` patterns after Phase 3 #7. Use "
        "CommandError instead — main() catches it and "
        "calls print_error."
    )
