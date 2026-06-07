"""``batch`` command — batch ingest sources from a directory or glob."""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import (
    print_error,
    print_error_stderr,
    print_success_stderr,
    print_warning_stderr,
    stderr_print,
)


def run_batch(wiki: Any, args: Any) -> int:
    """Batch ingest sources from a directory or glob pattern.

    Args:
        wiki: A Wiki instance (or any object with ``ingest_source``,
            ``_llm_process_source``, ``execute_operations``).
        args: Parsed argparse Namespace with ``source``, ``limit``,
            ``self_create``, ``smart``, ``dry_run``.

    Returns:
        0 on success, 1 if any source failed.

    Phase 3 #7 — progress / status messages that used
    ``print(..., file=sys.stderr)`` are now routed through
    ``stderr_print`` / ``print_*_stderr`` helpers from
    ``cli._output``. The structured JSON result still
    goes to stdout so the agent-facing path stays clean.
    """
    import glob as glob_module

    source_path = Path(args.source)
    limit = getattr(args, "limit", 0)

    if source_path.is_dir():
        sources = list(source_path.rglob("*"))
        sources = [s for s in sources if s.is_file()]
    else:
        # Glob pattern
        sources = [Path(p) for p in glob_module.glob(str(source_path))]

    if limit:
        sources = sources[:limit]

    if not sources:
        print_error("No sources found")
        return 1

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
            stderr_print("\n[DRY RUN] LLM self-create mode requested.")
            stderr_print("Remove --dry-run to execute LLM processing.")
        else:
            stderr_print("\nNo pages will be created. Use --self-create for LLM-assisted processing.")
        batch_results = []
        for source in sources:
            batch_results.append({
                "source": str(source),
                "status": "dry_run",
                "title": source.stem,
            })
        output = {
            "batch_summary": {
                "total": len(sources),
                "success": len(sources),
                "failed": 0,
                "dry_run": True,
            },
            "results": batch_results,
        }
        print(f"\n{json.dumps(output, ensure_ascii=False, indent=2)}")
        return 0

    stderr_print("=== Batch Ingest ===")
    stderr_print(f"Found {len(sources)} source(s)\n")

    success = 0
    failed = 0
    batch_results = []

    for i, source in enumerate(sources, 1):
        stderr_print(f"[{i}/{len(sources)}] Processing: {source.name}")
        result = wiki.ingest_source(str(source))

        if "error" in result:
            print_error_stderr(f"Error: {result['error']}")
            failed += 1
            batch_results.append({
                "source": str(source),
                "status": "error",
                "error": result["error"],
            })
        else:
            print_success_stderr(result['title'])
            if self_create:
                try:
                    ops_result = wiki._llm_process_source(result)
                    ops = ops_result.get("operations", [])
                    if ops:
                        exec_result = wiki.execute_operations(ops)
                        stderr_print(f"    → {exec_result['operations_executed']} operations executed")
                        batch_results.append({
                            "source": str(source),
                            "status": "processed",
                            "title": result.get("title", ""),
                            "source_name": result.get("source_name", ""),
                            "operations_executed": exec_result.get("operations_executed", 0),
                        })
                    else:
                        stderr_print("    → No operations planned by LLM")
                        batch_results.append({
                            "source": str(source),
                            "status": "no_operations",
                            "title": result.get("title", ""),
                            "source_name": result.get("source_name", ""),
                        })
                except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
                    print_warning_stderr(f"LLM processing skipped: {e}")
                    batch_results.append({
                        "source": str(source),
                        "status": "llm_failed",
                        "title": result.get("title", ""),
                        "source_name": result.get("source_name", ""),
                        "error": str(e),
                    })
            else:
                batch_results.append({
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
                    "instructions": result.get("instructions", ""),
                    "status": "extracted",
                })
            success += 1

    if not self_create:
        output = {
            "batch_summary": {
                "total": len(sources),
                "success": success,
                "failed": failed,
            },
            "results": batch_results,
            "message": "Read the content above for each source, read wiki.md for conventions, then create/update wiki pages using write_page.",
        }
        print(f"\n{json.dumps(output, ensure_ascii=False, indent=2)}")

    stderr_print("\n=== Batch Complete ===")
    stderr_print(f"Success: {success}, Failed: {failed}")

    return 0 if failed == 0 else 1


class BatchCommand(Command):
    """``batch`` command — batch ingest sources."""

    name = "batch"
    help = "Batch ingest sources"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction

        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument("source", help="Directory or glob pattern")
        p.add_argument("--limit", "-l", type=int, default=0, help="Limit number of sources")
        p.add_argument("--self-create", "-s", action="store_true", help="CLI uses LLM API to automatically process content and create wiki pages")
        p.add_argument("--smart", action="store_true", help="[Deprecated] Alias for --self-create")
        p.add_argument("--dry-run", "-n", action="store_true", help="Preview extraction without creating pages")

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_batch(wiki, args)
