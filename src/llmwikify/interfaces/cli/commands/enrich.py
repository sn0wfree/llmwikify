"""``enrich`` command — parse a document, write its pages, then enrich the wiki.

One command runs the whole Track A + Track C chain:

    ingest_source → _llm_process_source → execute_operations → enrich

The last step is what makes this different from ``ingest --self-create``:
after the new pages are written, the knowledge base around them is
repaired — pages that mention the new concepts in plain text get a
wikilink, and a concept without a page of its own becomes a proposal.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from llmwikify.apps.agent.maintenance.config import EnricherConfig
from llmwikify.apps.agent.maintenance.enricher import KnowledgeEnricher

from .._base import Command
from .._output import print_error, stderr_print


def run_enrich(wiki: Any, args: Any) -> int:
    """Parse a document and enrich the knowledge base around it.

    Args:
        wiki: A Wiki instance.
        args: Parsed argparse Namespace with ``file`` and optional
            ``json``, ``dry_run``, ``no_propose``.

    Returns:
        0 on success, 1 on error.
    """
    source = getattr(args, "file", None)
    if not source:
        print_error("Error: no source file given")
        return 1

    result = wiki.ingest_source(source)
    if "error" in result:
        print_error(f"Error: {result['error']}")
        return 1

    stderr_print(f"Ingested: {result.get('title', '')} ({result.get('source_type', '')})")
    if result.get("saved_to_raw"):
        stderr_print(f"Saved to raw: {result.get('source_name', '')}")

    if getattr(args, "dry_run", False):
        stderr_print("\n[DRY RUN] No pages written, nothing enriched.")
        return 0

    try:
        ops_result = wiki._llm_process_source(result)
    except ValueError as exc:
        print_error(f"LLM not configured: {exc}")
        return 1
    except (ConnectionError, TimeoutError, RuntimeError, OSError) as exc:
        print_error(f"LLM processing failed: {exc}")
        return 1

    operations = ops_result.get("operations", [])
    execution = wiki.execute_operations(operations)

    stderr_print(f"Pages written: {execution.get('operations_executed', 0)}")

    relations = ops_result.get("relations", [])
    if relations:
        try:
            rel_result = wiki.write_relations(
                relations, source_file=result.get("source_name")
            )
            stderr_print(f"Relations added: {rel_result.get('count', 0)}")
        except Exception as exc:
            stderr_print(f"Relations failed: {exc}")

    config = EnricherConfig()
    if getattr(args, "no_propose", False):
        config.propose_missing_pages = False

    enricher = KnowledgeEnricher(
        wiki=wiki,
        wiki_id=getattr(wiki, "root", None) and str(wiki.root) or "cli",
        config=config,
        llm_semaphore=asyncio.Semaphore(1),
    )
    enrich_result = asyncio.run(
        enricher.enrich(llm_result=ops_result, exec_result=execution)
    )

    stderr_print(
        f"Enriched: {enrich_result.links_added} link(s), "
        f"{enrich_result.proposals_created} proposal(s), "
        f"{enrich_result.errors} error(s)"
    )

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "source": result.get("source_name", ""),
                    "operations_executed": execution.get("operations_executed", 0),
                    "enrich": enrich_result.as_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


class EnrichCommand(Command):
    """``enrich`` command — parse a document and enrich the knowledge base."""

    name = "enrich"
    help = "Parse a document, write its pages, then enrich the knowledge base"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("file", type=str, help="File path or URL to parse")
        p.add_argument(
            "--dry-run",
            "-n",
            action="store_true",
            help="Only extract the document; write nothing",
        )
        p.add_argument(
            "--no-propose",
            action="store_true",
            help="Do not queue proposals for concepts without a page",
        )
        p.add_argument("--json", action="store_true", help="Output as JSON")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_enrich(wiki, args)
