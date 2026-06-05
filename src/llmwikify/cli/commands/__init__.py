"""Per-command classes for the CLI (Phase 1 #2 / C2+).

Each module in this package defines a single ``Command`` subclass
plus a free function ``run_<name>(wiki, args) -> int`` that
contains the actual logic. The function is the canonical
implementation; the class is the registry-friendly wrapper.

This subpackage uses auto-discovery: importing
``llmwikify.cli.commands`` runs the imports below, which in
turn register each command in ``COMMAND_REGISTRY``.

The WikiCLI class in ``llmwikify.cli.commands`` calls these
functions directly from its public methods (so the existing
``cli.method(args)`` test contract is preserved).
"""

from __future__ import annotations

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

__all__ = [
    # Init
    "InitCommand",
    "run_init",
    # Ingest
    "IngestCommand",
    "run_ingest",
    # Status
    "StatusCommand",
    "run_status",
    # Log
    "LogCommand",
    "run_log",
    # Sink status
    "SinkStatusCommand",
    "run_sink_status",
    # Write page
    "WritePageCommand",
    "run_write_page",
    # Read page
    "ReadPageCommand",
    "run_read_page",
    # Search
    "SearchCommand",
    "run_search",
    # Build index
    "BuildIndexCommand",
    "run_build_index",
    # Fix wikilinks
    "FixWikilinksCommand",
    "run_fix_wikilinks",
]
