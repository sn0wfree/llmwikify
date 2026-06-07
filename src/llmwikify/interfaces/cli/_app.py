"""CLI commands for llmwikify.

Phase 1 #2 / C2 — this module is in the middle of being
decomposed. The 10 simple commands (init / ingest / status /
log / sink_status / write_page / read_page / search /
build_index / fix_wikilinks) now live in
``llmwikify.cli.commands.<name>`` and their logic is in
``run_<name>(wiki, args)`` free functions.

``WikiCLI`` keeps its public method API for backward
compatibility with the existing CLI tests. Each migrated
method is now a 1-line delegate to the new ``run_<name>``
function. The remaining 16 methods (lint, references, batch,
synthesize, watch, graph_*, wikis_*, qmd_*, db_*, serve, mcp,
analyze_source, etc.) will be migrated in C3.

The new command classes (StatusCommand, ReadPageCommand, etc.)
are auto-registered in ``COMMAND_REGISTRY`` when the
``llmwikify.cli.commands`` subpackage is imported. C3 will
switch ``main()`` to dispatch through the registry.

This file was previously named ``commands.py``; it had to be
renamed to ``_app.py`` because the new ``commands/``
subpackage now owns the name.
"""

import argparse
import glob as glob_module
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from ...core import Wiki
from .commands.analyze_source import run_analyze_source
from .commands.batch import run_batch
from .commands.build_index import run_build_index
from .commands.community_detect import run_community_detect
from .commands.db import run_db
from .commands.export_graph import run_export_graph
from .commands.fix_wikilinks import run_fix_wikilinks
from .commands.graph_analyze import run_graph_analyze
from .commands.graph_query import run_graph_query
from .commands.ingest import _ingest_smart_inline, run_ingest
from .commands.init_cmd import run_init
from .commands.knowledge_gaps import run_knowledge_gaps
from .commands.lint import run_lint
from .commands.log_cmd import run_log
from .commands.qmd import run_qmd
from .commands.read_page import run_read_page
from .commands.references import run_references
from .commands.report import run_report
from .commands.search import run_search
from .commands.serve import run_serve
from .commands.sink_status import run_sink_status
from .commands.status import run_status
from .commands.suggest_synthesis import run_suggest_synthesis
from .commands.synthesize import run_synthesize
from .commands.watch import run_watch
from .commands.wikis import run_wikis
from .commands.write_page import _get_content, run_write_page

logger = logging.getLogger(__name__)

class WikiCLI:
    """CLI command handler.

    Public methods preserve backward compatibility — each
    migrated method is a 1-line delegate to the new
    ``run_<name>`` function in ``llmwikify.cli.commands.<name>``.
    The Wiki instance is still created once in __init__ and
    reused across method calls (which is why the delegates
    pass ``self.wiki`` rather than re-creating it).
    """

    def __init__(self, wiki_root: Path, config: dict[str, Any] | None = None):
        self.wiki_root = wiki_root
        self.config = config or {}
        self.wiki = Wiki(wiki_root, config=self.config)

    def init(self, args: Any) -> int:
        """Initialize wiki. → ``cli.commands.init_cmd.run_init``."""
        return run_init(self.wiki, self.wiki_root, args)

    def ingest(self, args: Any) -> int:
        """Ingest a source file. → ``cli.commands.ingest.run_ingest``."""
        return run_ingest(self.wiki, args, _ingest_smart_fn=_ingest_smart_inline)

    def _ingest_smart(self, result: dict) -> int:
        """Smart-ingest helper. Preserved for backward compat with
        any external caller; delegates to the inline implementation.
        """
        return _ingest_smart_inline(self.wiki, result)

    def write_page(self, args: Any) -> int:
        """Write a wiki page. → ``cli.commands.write_page.run_write_page``."""
        return run_write_page(self.wiki, args)

    def read_page(self, args: Any) -> int:
        """Read a wiki page. → ``cli.commands.read_page.run_read_page``."""
        return run_read_page(self.wiki, args)

    def search(self, args: Any) -> int:
        """Search wiki. → ``cli.commands.search.run_search``."""
        return run_search(self.wiki, args)

    def status(self, args: Any) -> int:
        """Show status. → ``cli.commands.status.run_status``."""
        return run_status(self.wiki, args)

    def log(self, args: Any) -> int:
        """Record log entry. → ``cli.commands.log_cmd.run_log``."""
        return run_log(self.wiki, args)

    def sink_status(self, args: Any) -> int:
        """Show query sink buffer status. → ``cli.commands.sink_status.run_sink_status``."""
        return run_sink_status(self.wiki, args)

    def build_index(self, args: Any) -> int:
        """Build reference index. → ``cli.commands.build_index.run_build_index``."""
        return run_build_index(self.wiki, args)

    def _detect_old_index_format(self) -> bool:
        """Check if the index has old-format page_names.

        Backward-compat method (pre-existing tests use
        ``cli._detect_old_index_format()``). Delegates to
        the free function in
        ``cli.commands.build_index._detect_old_index_format``.
        """
        from .commands.build_index import _detect_old_index_format
        return _detect_old_index_format(self.wiki)

    def fix_wikilinks(self, args: Any) -> int:
        """Fix broken wikilinks. → ``cli.commands.fix_wikilinks.run_fix_wikilinks``."""
        return run_fix_wikilinks(self.wiki, args)

    def analyze_source(self, args: Any) -> int:

        """Delegated to ``cli.commands.analyze_source.run_analyze_source``."""

        return run_analyze_source(self.wiki, args)

    def lint(self, args: Any) -> int:

        """Delegated to ``cli.commands.lint.run_lint``."""

        return run_lint(self.wiki, args)

    def references(self, args: Any) -> int:

        """Delegated to ``cli.commands.references.run_references``."""

        return run_references(self.wiki, args)

    def batch(self, args: Any) -> int:

        """Delegated to ``cli.commands.batch.run_batch``."""

        return run_batch(self.wiki, args)

    def synthesize(self, args: Any) -> int:

        """Delegated to ``cli.commands.synthesize.run_synthesize``."""

        return run_synthesize(self.wiki, args)

    def watch(self, args: Any) -> int:
        """Delegated to ``cli.commands.watch.run_watch``."""
        return run_watch(self.wiki, self.wiki_root, args)

    def graph_query(self, args: Any) -> int:

        """Delegated to ``cli.commands.graph_query.run_graph_query``."""

        return run_graph_query(self.wiki, args)

    def export_graph(self, args: Any) -> int:

        """Delegated to ``cli.commands.export_graph.run_export_graph``."""

        return run_export_graph(self.wiki, args)

    def community_detect(self, args: Any) -> int:

        """Delegated to ``cli.commands.community_detect.run_community_detect``."""

        return run_community_detect(self.wiki, args)

    def report(self, args: Any) -> int:

        """Delegated to ``cli.commands.report.run_report``."""

        return run_report(self.wiki, args)

    def wikis(self, args: Any) -> int:

        """Delegated to ``cli.commands.wikis.run_wikis``."""

        return run_wikis(self.wiki, self.config, args)

    def suggest_synthesis(self, args: Any) -> int:

        """Delegated to ``cli.commands.suggest_synthesis.run_suggest_synthesis``."""

        return run_suggest_synthesis(self.wiki, args)

    def knowledge_gaps(self, args: Any) -> int:

        """Delegated to ``cli.commands.knowledge_gaps.run_knowledge_gaps``."""

        return run_knowledge_gaps(self.wiki, args)

    def graph_analyze(self, args: Any) -> int:

        """Delegated to ``cli.commands.graph_analyze.run_graph_analyze``."""

        return run_graph_analyze(self.wiki, args)

    def serve(self, args: Any) -> int:

        """Delegated to ``cli.commands.serve.run_serve``."""

        return run_serve(self.wiki, self.config, args)

    def qmd(self, args: Any) -> int:

        """Delegated to ``cli.commands.qmd.run_qmd``."""

        return run_qmd(self.wiki, args)

    def db(self, args: Any) -> int:

        """Delegated to ``cli.commands.db.run_db``."""

        return run_db(self.wiki, args)

def _build_parser():
    """Build the llmwikify top-level ArgumentParser.

    Phase 3 #6 — extracted from ``main()`` so tests can build
    a parser without starting the MCP server (which would
    conflict with pytest's event loop). The parser includes
    all command subparsers + the SUBCOMMAND_ALIASES scan
    that populates the help_cmd module's dict.
    """
    # Import the commands subpackage so all Command classes are
    # registered in COMMAND_REGISTRY before we iterate them.
    from . import commands as _commands  # noqa: F401  (registration side effect)
    from ._base import COMMAND_REGISTRY
    from .commands.help_cmd import SUBCOMMAND_ALIASES  # noqa: E402

    parser = argparse.ArgumentParser(
        prog="llmwikify",
        description="llmwikify CLI - LLM Wiki Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  llmwikify ingest document.pdf                       Show extraction summary + JSON for agent
  llmwikify ingest document.pdf --dry-run             Preview without changes
  llmwikify search "gold mining"                      Full-text search
  llmwikify references "Company"                      Show references
  llmwikify build-index                               Build reference index
  llmwikify build-index --export-only                 Export index without rebuilding
  llmwikify lint --format=brief                       Quick health suggestions
  llmwikify lint --format=recommendations             Missing and orphan pages
  llmwikify init                                      Initialize wiki
  llmwikify init --overwrite                          Reinitialize wiki
  llmwikify serve                                     Start MCP server (alias: mcp)
  llmwikify serve --transport http --port 8765        Start MCP server on HTTP port
  llmwikify serve --web                               Start unified server (MCP + WebUI) on :8765
  llmwikify serve --web --auth-token mysecret         Start unified server with API key auth
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    for cmd_name in sorted(COMMAND_REGISTRY):
        cmd = COMMAND_REGISTRY[cmd_name]
        cmd.setup_parser(subparsers)

    # Collect subcommand aliases for the ``help`` command.
    # argparse on Python 3.10 does not expose ``_aliases`` on
    # the subparser, but it does add each alias as a separate
    # key in ``action.choices`` pointing to the SAME subparser
    # object. We group by object identity, then identify
    # aliases as names that are NOT in COMMAND_REGISTRY.
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            groups: dict[int, list[str]] = {}
            for name, sub in action.choices.items():
                groups.setdefault(id(sub), []).append(name)
            for _sub_id, names in groups.items():
                if len(names) <= 1:
                    continue
                canonical = next(
                    (n for n in names if n in COMMAND_REGISTRY),
                    names[0],
                )
                for name in names:
                    if name == canonical:
                        continue
                    SUBCOMMAND_ALIASES[name] = canonical
            break

    return parser


def main() -> int:
    """Main CLI entry point.

    Phase 1 #2 / C3 — main() now uses the ``COMMAND_REGISTRY`` from
    ``llmwikify.cli._base`` to set up parsers and dispatch commands.
    Each ``Command`` subclass exposes its own ``setup_parser()`` and
    ``run()``, so main() is reduced to:

    1. Build the top-level parser + subparsers
    2. Iterate registered commands, calling ``cmd.setup_parser(subparsers)``
    3. Parse args
    4. Load wiki_root + config
    5. Dispatch via ``get_command(name).run(args, wiki_root, config)``

    This means adding a new command no longer requires touching
    main() — just register a new Command class and import it in
    ``llmwikify.cli.commands.__init__``.
    """
    # Import the commands subpackage so all Command classes are
    # registered in COMMAND_REGISTRY before main() iterates them.
    # The import is idempotent: subsequent calls are no-ops.
    from . import commands as _commands  # noqa: F401  (registration side effect)
    from ._base import COMMAND_REGISTRY, CommandError, get_command
    from ._config import load_cli_config
    from ._output import print_error

    # Build the parser (extracted to _build_parser() in Phase 3
    # #6 so tests can build it without starting the MCP server).
    parser = _build_parser()

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Load wiki_root and config via the shared helper from C1
    wiki_root, config = load_cli_config()

    # Create a WikiCLI just to hold the wiki instance lifecycle
    # (it's the same instance that the run() functions will use).
    # Note: we don't dispatch through WikiCLI's methods anymore —
    # the registry is the new dispatch path. WikiCLI is kept only
    # for backward compatibility with external code that does
    # ``from llmwikify.interfaces.cli import WikiCLI; cli = WikiCLI(...); cli.X(args)``.
    cli = WikiCLI(wiki_root, config=config)

    # Phase 3 #6 — resolve subcommand aliases before dispatch.
    # argparse keeps the original name in args.command (e.g.,
    # typing ``mcp`` leaves args.command == "mcp" even though
    # it's an alias of "serve"). We use SUBCOMMAND_ALIASES to
    # look up the canonical command name.
    from .commands.help_cmd import SUBCOMMAND_ALIASES  # noqa: E402
    canonical_command = SUBCOMMAND_ALIASES.get(args.command, args.command)

    cmd = get_command(canonical_command)
    if cmd is None:
        # Shouldn't happen — argparse already validated the command
        # name against the registered set — but guard anyway.
        parser.print_help()
        return 1

    try:
        # Pass the Wiki instance (not wiki_root) so commands that
        # expect a wiki (with methods like init/read_page/etc.) work.
        # The Command.run signature is ``run(self, args, wiki, config)``.
        return cmd.run(args, cli.wiki, config)
    except CommandError as e:
        # Phase 3 #7 — commands raise CommandError instead of
        # ``print(error); return 1``. ``main()`` centralizes
        # the error message + exit code so the command bodies
        # stay focused on the happy path.
        print_error(e.message)
        return e.exit_code
    finally:
        cli.wiki.close()
