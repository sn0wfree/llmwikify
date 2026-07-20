"""``migrate-config`` command — migrate old .wiki-config.yaml to v0.41+ layout.

v0.41 moves LLM / Research / MCP / Chat mutable config from per-wiki
``.wiki-config.yaml`` to the global ``~/.llmwikify/llmwikify.json``.

This command:
- Detects configs older than v0.41 (no ``version`` field or version < "0.41").
- Extracts the deprecated sections (``llm``, ``research_mutable``,
  ``chat_mutable``, ``mcp``, ``prompts``).
- Merges them into the global config (with conflict resolution).
- Backs up the original wiki config as ``.wiki-config.yaml.bak.<timestamp>``.
- Adds a ``version: "0.41"`` field to the updated wiki config.

Usage:
    llmwikify migrate-config                      # auto-migrate (default)
    llmwikify migrate-config --dry-run            # show plan without writing
    llmwikify migrate-config --strict             # fail on conflicts
    llmwikify migrate-config --auto-global        # always prefer global (no prompt)
    llmwikify migrate-config --auto-wiki          # always prefer wiki (no prompt)
    llmwikify migrate-config --wiki-root /path    # specific wiki directory
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .._base import Command

logger = logging.getLogger(__name__)


def _format_plan(result: Any) -> str:
    """Format a MigrationResult as a human-readable plan."""
    lines: list[str] = []
    lines.append(f"Wiki root: {result.wiki_root}")
    lines.append(f"Status:    {result.reason or ('migrated' if result.migrated else 'skipped')}")
    if result.backup_path:
        lines.append(f"Backup:    {result.backup_path}")
    if result.changes:
        lines.append(f"Changes ({len(result.changes)}):")
        for ch in result.changes:
            tag = " [conflict]" if ch.conflict else ""
            old = "<new>" if ch.old_value is object() else repr(ch.old_value)
            lines.append(f"  {ch.section}.{ch.key}: {old} → {ch.new_value!r}{tag}")
    if result.conflicts:
        lines.append(f"Conflicts ({len(result.conflicts)}):")
        for c in result.conflicts:
            lines.append(
                f"  {c.section}.{c.key}: global={c.global_value!r} "
                f"vs wiki={c.wiki_value!r}"
            )
    return "\n".join(lines)


def run_migrate_config(wiki: Any, wiki_root: Path, args: Any) -> int:
    """Run migrate-config command."""
    from llmwikify.foundation.migration import auto_migrate_wiki_config

    custom_root = getattr(args, "wiki_root", None)
    target_root = Path(custom_root).resolve() if custom_root else wiki_root

    dry_run = getattr(args, "dry_run", False)
    strict = getattr(args, "strict", False)
    auto_global = getattr(args, "auto_global", False)
    auto_wiki = getattr(args, "auto_wiki", False)

    if dry_run:
        auto_resolve = "dry_run"
    elif strict:
        auto_resolve = "strict"
    elif auto_wiki:
        auto_resolve = "wiki"
    elif auto_global:
        auto_resolve = "global"
    else:
        auto_resolve = "interactive"

    try:
        result = auto_migrate_wiki_config(target_root, auto_resolve=auto_resolve)
    except RuntimeError as exc:
        print(f"❌ Migration failed: {exc}")
        return 1
    except Exception as exc:
        logger.exception("[migrate] unexpected error")
        print(f"❌ Unexpected error during migration: {exc}")
        return 1

    print(_format_plan(result))

    if result.reason == "no_migratable_sections":
        print("\n✓ Nothing to migrate.")
        return 0
    if result.reason == "already_migrated":
        print("\n✓ Already on latest schema.")
        return 0
    if result.reason == "no_config":
        print("\n✓ No .wiki-config.yaml found.")
        return 0
    if result.reason == "parse_error":
        print("\n⚠️  Failed to parse .wiki-config.yaml. Fix manually.")
        return 1
    if result.reason == "dry_run":
        print("\n→ Dry run complete (no files changed).")
        return 0
    if result.migrated:
        print(f"\n✓ Migrated {len(result.changes)} fields.")
        print(f"  Backup saved at: {result.backup_path}")
        print("  Backup is permanent. Delete manually if no longer needed.")
        return 0
    return 1


class MigrateConfigCommand(Command):
    """Migrate old .wiki-config.yaml to v0.41+ layout."""

    name = "migrate-config"
    help = "Migrate old .wiki-config.yaml to v0.41+ layout"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction
        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--wiki-root", dest="wiki_root", default=None,
            help="Path to wiki directory (default: current wiki_root)",
        )
        p.add_argument(
            "--dry-run", dest="dry_run", action="store_true",
            help="Show the migration plan without writing any files",
        )
        p.add_argument(
            "--strict", dest="strict", action="store_true",
            help="Fail on conflicts instead of auto-resolving",
        )
        p.add_argument(
            "--auto-global", dest="auto_global", action="store_true",
            help="Always prefer existing global config values (no prompt)",
        )
        p.add_argument(
            "--auto-wiki", dest="auto_wiki", action="store_true",
            help="Always prefer wiki config values (no prompt)",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        custom_root = getattr(args, "wiki_root", None)
        if custom_root:
            from llmwikify.kernel import Wiki as _Wiki
            try:
                wiki_root = Path(custom_root).resolve()
                wiki = _Wiki(wiki_root, config=config)
            except (OSError, RuntimeError):
                pass
        return run_migrate_config(
            wiki, wiki.root if hasattr(wiki, "root") else Path.cwd(), args,
        )
