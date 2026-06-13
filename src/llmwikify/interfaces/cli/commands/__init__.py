"""Per-command classes for the CLI (Phase 1 #2 / C2+C3).

Each module in this package defines a single ``Command`` subclass
plus a free function ``run_<name>(...)`` that contains the
actual logic. The function is the canonical implementation; the
class is the registry-friendly wrapper.

This subpackage uses auto-discovery: importing
``llmwikify.cli.commands`` runs the imports below, which in
turn register each command in ``COMMAND_REGISTRY``.

The WikiCLI class in ``llmwikify.cli._app`` calls these
functions directly from its public methods (so the existing
``cli.method(args)`` test contract is preserved).
"""

from __future__ import annotations

from .._base import register_command

# C2 (10 simple commands)
from .init_cmd import InitCommand, run_init
from .ingest import IngestCommand, run_ingest
from .status import StatusCommand, run_status
from .log_cmd import LogCommand, run_log
from .sink_status import SinkStatusCommand, run_sink_status
from .write_page import WritePageCommand, run_write_page
from .read_page import ReadPageCommand, run_read_page
from .search import SearchCommand, run_search
from .build_index import BuildIndexCommand, run_build_index
from .fix_wikilinks import FixWikilinksCommand, run_fix_wikilinks

# C3 (16 complex commands)
from .analyze_source import AnalyzeSourceCommand, run_analyze_source
from .lint import LintCommand, run_lint
from .references import ReferencesCommand, run_references
from .batch import BatchCommand, run_batch
from .synthesize import SynthesizeCommand, run_synthesize
from .watch import WatchCommand, run_watch
from .graph_query import GraphQueryCommand, run_graph_query
from .export_graph import ExportGraphCommand, run_export_graph
from .community_detect import CommunityDetectCommand, run_community_detect
from .report import ReportCommand, run_report
from .wikis import WikisCommand, run_wikis
from .suggest_synthesis import SuggestSynthesisCommand, run_suggest_synthesis
from .knowledge_gaps import KnowledgeGapsCommand, run_knowledge_gaps
from .graph_analyze import GraphAnalyzeCommand, run_graph_analyze
from .serve import ServeCommand, run_serve
from .qmd import QmdCommand, run_qmd
from .db import DbCommand, run_db
from .quant_init_cmd import QuantInitCommand, run_quant_init

# Phase 3 #6 — new ``help`` subcommand for command + alias
# discovery. ``mcp`` is no longer a separate Command class —
# it's an argparse alias of ``serve`` (see serve.py).
from .help_cmd import HelpCommand

# Auto-register all 27 commands (10 C2 + 16 C3 + help = 28)
# Note: ``mcp`` is NOT in the registry — it's an argparse alias
# of ``serve`` (added via ``aliases=['mcp']`` in serve.py).
register_command(InitCommand())
register_command(IngestCommand())
register_command(StatusCommand())
register_command(LogCommand())
register_command(SinkStatusCommand())
register_command(WritePageCommand())
register_command(ReadPageCommand())
register_command(SearchCommand())
register_command(BuildIndexCommand())
register_command(FixWikilinksCommand())
register_command(AnalyzeSourceCommand())
register_command(LintCommand())
register_command(ReferencesCommand())
register_command(BatchCommand())
register_command(SynthesizeCommand())
register_command(WatchCommand())
register_command(GraphQueryCommand())
register_command(ExportGraphCommand())
register_command(CommunityDetectCommand())
register_command(ReportCommand())
register_command(WikisCommand())
register_command(SuggestSynthesisCommand())
register_command(KnowledgeGapsCommand())
register_command(GraphAnalyzeCommand())
register_command(ServeCommand())
register_command(QmdCommand())
register_command(DbCommand())
register_command(QuantInitCommand())
register_command(HelpCommand())

# C3 backward-compat re-exports — when ``commands.py`` was
# renamed to ``_app.py`` (Phase 1 #2 / C2-C3) to make room
# for the new ``commands/`` subpackage, two public symbols
# (``WikiCLI`` and ``main``) moved with it. Tests and
# downstream callers that did
# ``from llmwikify.interfaces.cli.commands import WikiCLI`` (or
# ``main``) broke because ``cli/commands/`` is now a
# subpackage, not a module.
#
# We use PEP 562 module-level ``__getattr__`` for the
# re-export because a top-level ``from .._app import
# WikiCLI, main`` would create a circular import: this
# subpackage is imported by ``_app.py`` (via
# ``from .commands.analyze_source import run_analyze_source``
# etc.), so it cannot import from ``_app`` at module init
# time. ``__getattr__`` defers the lookup until the symbol
# is actually accessed, breaking the cycle.
def __getattr__(name):
    """PEP 562 lazy re-export of ``WikiCLI`` and ``main`` from
    ``llmwikify.cli._app``.

    Allows legacy imports like
    ``from llmwikify.interfaces.cli.commands import WikiCLI`` (or
    ``main``) to keep working, even though those symbols
    canonically live in ``llmwikify.cli._app``. The lookup
    is deferred to avoid a circular import with ``_app``
    (which imports from this subpackage).
    """
    if name in ("WikiCLI", "main"):
        from .. import _app
        return getattr(_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # C2 simple commands
    "InitCommand", "run_init",
    "IngestCommand", "run_ingest",
    "StatusCommand", "run_status",
    "LogCommand", "run_log",
    "SinkStatusCommand", "run_sink_status",
    "WritePageCommand", "run_write_page",
    "ReadPageCommand", "run_read_page",
    "SearchCommand", "run_search",
    "BuildIndexCommand", "run_build_index",
    "FixWikilinksCommand", "run_fix_wikilinks",
    # C3 complex commands
    "AnalyzeSourceCommand", "run_analyze_source",
    "LintCommand", "run_lint",
    "ReferencesCommand", "run_references",
    "BatchCommand", "run_batch",
    "SynthesizeCommand", "run_synthesize",
    "WatchCommand", "run_watch",
    "GraphQueryCommand", "run_graph_query",
    "ExportGraphCommand", "run_export_graph",
    "CommunityDetectCommand", "run_community_detect",
    "ReportCommand", "run_report",
    "WikisCommand", "run_wikis",
    "SuggestSynthesisCommand", "run_suggest_synthesis",
    "KnowledgeGapsCommand", "run_knowledge_gaps",
    "GraphAnalyzeCommand", "run_graph_analyze",
    "ServeCommand", "run_serve",  # McpCommand removed in Phase 3 #6
    "QmdCommand", "run_qmd",
    "DbCommand", "run_db",
    "HelpCommand",  # Phase 3 #6
]
