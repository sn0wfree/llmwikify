"""``ingest`` command — ingest a source file into a wiki.

This is one of the larger "simple" commands. It has 3 modes:
1. Dry-run: print summary, don't process
2. Self-create: call LLM to process the content
3. Default: emit a JSON payload for the agent to decide what to do

The original code lived in WikiCLI.ingest() and WikiCLI._ingest_smart()
in commands.py. The body is preserved here byte-for-byte.
"""

from __future__ import annotations

import json
import sys
import warnings
from typing import Any

from .._base import Command


def run_ingest(wiki: Any, args: Any, _ingest_smart_fn: Any = None) -> int:
    """Ingest a source file.

    Args:
        wiki: A Wiki instance.
        args: Parsed argparse Namespace with ``file``, ``self_create``,
            ``smart``, ``dry_run``.
        _ingest_smart_fn: Optional callback for the self-create
            path. Defaults to the inline implementation below.

    Returns:
        0 on success (or dry-run), 1 on error.
    """
    smart_fn = _ingest_smart_fn or _ingest_smart_inline
    source = args.file
    result = wiki.ingest_source(source)

    if "error" in result:
        print(f"Error: {result['error']}")
        return 1

    # Display extraction summary to stderr (for human readability)
    print(f"Ingested: {result['title']} ({result['source_type']})", file=sys.stderr)
    print(f"Content length: {result['content_length']:,} chars", file=sys.stderr)

    if result.get("saved_to_raw"):
        print(f"Saved to raw: {result['source_name']}", file=sys.stderr)
    elif result.get("already_exists"):
        print(f"Already in raw: {result['source_name']}", file=sys.stderr)
    elif result.get("source_name"):
        print(f"Source: {result['source_raw_path']}", file=sys.stderr)

    if result["content_length"] > 8000:
        print(
            "Note: Content truncated to 8,000 chars for LLM processing",
            file=sys.stderr,
        )

    self_create = getattr(args, "self_create", False) or getattr(args, "smart", False)
    if getattr(args, "smart", False):
        warnings.warn(
            "--smart is deprecated, use --self-create instead",
            DeprecationWarning,
            stacklevel=2,
        )
    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        if self_create:
            print("\n[DRY RUN] LLM self-create mode requested.", file=sys.stderr)
            print("Remove --dry-run to execute LLM processing.", file=sys.stderr)
        else:
            print(
                "\nNo pages created. Use --self-create for LLM-assisted processing.",
                file=sys.stderr,
            )
        return 0

    if self_create:
        return smart_fn(wiki, result)
    else:
        # Output full structured result as JSON (same as MCP wiki_ingest response)
        # so agent can parse and decide which pages to create
        output = {
            "source_name": result.get("source_name", ""),
            "source_raw_path": result.get("source_raw_path", ""),
            "source_type": result.get("source_type", ""),
            "file_type": result.get("file_type", ""),
            "title": result.get("title", ""),
            "content": result.get("content", ""),
            "content_length": result.get("content_length", 0),
            "content_preview": result.get("content_preview", ""),
            "word_count": result.get("word_count", 0),
            "file_size": result.get("file_size", 0),
            "has_images": result.get("has_images", False),
            "image_count": result.get("image_count", 0),
            "saved_to_raw": result.get("saved_to_raw", False),
            "already_exists": result.get("already_exists", False),
            "hint": result.get("hint", ""),
            "current_index": result.get("current_index", ""),
            "instructions": result.get("instructions", ""),
            "message": (
                "Read the content above, read wiki.md for conventions, "
                "then create/update wiki pages using write_page."
            ),
        }
        print(f"\n{json.dumps(output, ensure_ascii=False, indent=2)}")
        return 0


def _ingest_smart_inline(wiki: Any, result: dict) -> int:
    """Execute LLM smart processing on ingested content (default impl)."""
    try:
        operations_result = wiki._llm_process_source(result)
    except ValueError as e:
        print(f"\nLLM not configured: {e}")
        return 1
    except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
        print(f"\nLLM processing failed: {e}")
        return 1

    operations = operations_result.get("operations", [])
    print(f"\nLLM Plan ({len(operations)} operations):")

    for i, op in enumerate(operations, 1):
        action = op.get("action", "unknown")
        if action == "write_page":
            print(f"  {i}. write_page: {op.get('page_name', 'unnamed')}")
        elif action == "log":
            print(f"  {i}. log: {op.get('operation', '')} | {op.get('details', '')}")
        else:
            print(f"  {i}. {action}")

    # Execute operations
    print("\nExecuting...")
    execution = wiki.execute_operations(operations)

    for r in execution.get("results", []):
        status_icon = "ok" if r.get("status") == "done" else "!!"
        action = r.get("action", "")
        detail = r.get("page", r.get("operation", ""))
        print(f"  [{status_icon}] {action}: {detail}")

    # Write relations if extracted
    relations = operations_result.get("relations", [])
    if relations:
        print(f"\nExtracting {len(relations)} relations...")
        rel_result = wiki.write_relations(
            relations, source_file=result.get("source_name")
        )
        print(f"  Relations added: {rel_result.get('count', 0)}")

    print(f"\nCompleted: {execution['operations_executed']} operations")
    return 0


class IngestCommand(Command):
    """``ingest`` command — ingest a source file."""

    name = "ingest"
    help = "Ingest a source file"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("file", type=str, help="File path or URL")
        p.add_argument(
            "--self-create", "-s", action="store_true",
            help="CLI uses LLM API to automatically analyze content and create wiki pages",
        )
        p.add_argument(
            "--smart", action="store_true",
            help="[Deprecated] Alias for --self-create",
        )
        p.add_argument(
            "--dry-run", "-n", action="store_true",
            help="Show extraction summary without creating pages",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_ingest(wiki, args)
