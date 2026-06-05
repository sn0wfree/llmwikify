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

from ..core import Wiki
from .commands.build_index import run_build_index
from .commands.fix_wikilinks import run_fix_wikilinks
from .commands.ingest import _ingest_smart_inline, run_ingest
from .commands.init_cmd import run_init
from .commands.log_cmd import run_log
from .commands.read_page import run_read_page
from .commands.search import run_search
from .commands.sink_status import run_sink_status
from .commands.status import run_status
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

    def fix_wikilinks(self, args: Any) -> int:
        """Fix broken wikilinks. → ``cli.commands.fix_wikilinks.run_fix_wikilinks``."""
        return run_fix_wikilinks(self.wiki, args)

    def _get_content(self, args: Any) -> str | None:
        """Internal helper used by write_page. Preserved for
        backward compat — delegates to the new location.
        """
        return _get_content(args)

    def analyze_source(self, args: Any) -> int:
        """Analyze source files and cache extraction results."""
        if getattr(args, 'all', False):
            # Batch analyze all sources
            sources = list(self.wiki.raw_dir.rglob("*")) if self.wiki.raw_dir.exists() else []
            sources = [f for f in sources if f.is_file()]

            if not sources:
                print("No source files found in raw/")
                return 0

            analyzed = 0
            failed = 0
            skipped = 0
            force = getattr(args, 'force', False)

            for i, f in enumerate(sources, 1):
                rel = str(f.relative_to(self.wiki.root))
                print(f"[{i}/{len(sources)}] Analyzing: {rel}...", end=" ")

                try:
                    result = self.wiki.analyze_source(rel, force=force)
                    status = result.get("status", "success")
                    if status == "skipped":
                        print(f"skipped ({result.get('reason', 'unknown')})")
                        skipped += 1
                    elif status == "error":
                        print(f"failed ({result.get('reason', 'unknown')})")
                        failed += 1
                    else:
                        entities = len(result.get("entities", []))
                        suggested = len(result.get("suggested_pages", []))
                        print(f"done (entities: {entities}, suggested: {suggested})")
                        analyzed += 1
                except Exception as e:
                    print(f"error: {e}")
                    failed += 1

            print(f"\nSummary: {analyzed} analyzed, {skipped} skipped, {failed} failed")
            return 0 if failed == 0 else 1
        else:
            # Single source
            source_path = args.source
            if not source_path:
                print("Error: specify a source path or use --all")
                return 1

            result = self.wiki.analyze_source(source_path, force=getattr(args, 'force', False) if hasattr(args, 'force') else False)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") not in ("error", "skipped") else 1

    def lint(self, args: Any) -> int:
        """Health check."""
        generate_inv = getattr(args, 'generate_investigations', False)
        fmt = getattr(args, 'format', 'full')
        mode = getattr(args, 'mode', 'check')
        limit = getattr(args, 'limit', 10)
        force = getattr(args, 'force', False)
        result = self.wiki.lint(
            mode=mode, limit=limit, force=force,
            generate_investigations=generate_inv,
        )

        if fmt == 'json':
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        elif fmt == 'brief':
            return self._lint_brief(result)
        elif fmt == 'recommendations':
            return self._lint_recommendations(result)
        else:
            return self._lint_full(result)

    def _lint_full(self, result: dict) -> int:
        """Full health check output."""
        print("=== Wiki Health Check ===")
        print(f"Total pages: {result['total_pages']}")
        print(f"Issues found: {result['issue_count']}")

        if result['issues']:
            by_type: dict[str, int] = {}
            for issue in result['issues']:
                t = issue.get('type') or issue.get('issue_type', 'unknown')
                by_type[t] = by_type.get(t, 0) + 1

            print("\nBy type:")
            for t, count in sorted(by_type.items()):
                print(f"  {t}: {count}")

            print("\nFirst 20 issues:")
            for issue in result['issues'][:20]:
                issue_type = issue.get('type') or issue.get('issue_type', 'unknown')
                page = issue.get('page', 'unknown')
                message = issue.get('message', '')
                print(f"  ❌ [{issue_type}] {page}: {message}")

        # P1.2: Show investigations
        inv = result.get('investigations', {})
        if inv:
            print("\n=== Investigations ===")

            contradictions = inv.get('contradictions', [])
            if contradictions:
                print(f"\n❌ Contradictions ({len(contradictions)}):")
                for c in contradictions[:3]:
                    print(f"  • {c.get('observation', c.get('type', 'unknown'))[:100]}")

            data_gaps = inv.get('data_gaps', [])
            if data_gaps:
                print(f"\n🔍 Data Gaps ({len(data_gaps)}):")
                for g in data_gaps[:3]:
                    print(f"  • {g.get('observation', g.get('type', 'unknown'))[:100]}")

            outdated = inv.get('outdated_pages', [])
            if outdated:
                print(f"\n📅 Outdated Pages ({len(outdated)}):")
                for o in outdated[:3]:
                    print(f"  • {o.get('observation', o.get('page', 'unknown'))[:100]}")

            gaps = inv.get('knowledge_gaps', [])
            if gaps:
                print(f"\n🔍 Knowledge Gaps ({len(gaps)}):")
                for g in gaps[:3]:
                    print(f"  • {g.get('observation', g.get('type', 'unknown'))[:100]}")

            redundancy = inv.get('redundancy_alerts', [])
            if redundancy:
                print(f"\n⚠️ Redundancy ({len(redundancy)}):")
                for r in redundancy[:3]:
                    print(f"  • {r.get('observation', r.get('type', 'unknown'))[:100]}")

        if result['issues']:
            return 1
        else:
            print("\n✅ All healthy!")

        # Show auto-fix results
        auto_fix = result.get('auto_fix', {})
        if auto_fix:
            print("\n=== Auto-Fix Results ===")
            wl_fixed = auto_fix.get('wikilinks_fixed', 0)
            wl_skipped = auto_fix.get('wikilinks_skipped', 0)
            wl_ambig = auto_fix.get('wikilinks_ambiguous', 0)
            idx_updated = auto_fix.get('index_updated', False)
            print(f"  Wikilinks fixed: {wl_fixed}")
            if wl_skipped:
                print(f"  Wikilinks skipped: {wl_skipped}")
            if wl_ambig:
                print(f"  Ambiguous matches: {wl_ambig}")
            if idx_updated:
                print("  Index updated: ✅ (summaries refreshed, pages grouped)")

        return 0

    def _lint_brief(self, result: dict) -> int:
        """Brief suggestions output (replaces old `hint` command)."""
        hints = []
        for hint_type in ('critical', 'informational'):
            for h in result.get('hints', {}).get(hint_type, []):
                priority = 'high' if hint_type == 'critical' else 'medium'
                hints.append({'priority': priority, 'message': h.get('message', '')})

        for issue in result.get('issues', []):
            if issue.get('type') == 'orphan_page':
                hints.append({
                    'priority': 'medium',
                    'message': f"Orphan page: [[{issue.get('page', '')}]]",
                })
            elif issue.get('type') == 'broken_link':
                hints.append({
                    'priority': 'high',
                    'message': f"Broken link in {issue.get('page', '')} → [[{issue.get('link', '')}]]",
                })

        print("=== Wiki Suggestions ===\n")
        if hints:
            for hint in hints[:10]:
                priority_icon = {
                    'high': '🔴',
                    'medium': '🟡',
                    'low': '🟢',
                }.get(hint['priority'], '•')
                print(f"{priority_icon} [{hint['priority'].upper()}] {hint['message']}\n")
        else:
            print("✅ Wiki looks healthy! No suggestions.\n")

        print(f"Summary: {len(hints)} suggestion(s)")
        return 0

    def _lint_recommendations(self, result: dict) -> int:
        """Missing pages and orphan pages output (replaces old `recommend` command)."""
        # Extract missing pages from hints
        missing_pages = []
        for h in result.get('hints', {}).get('critical', []):
            if 'referenced but' in h.get('message', ''):
                msg = h.get('message', '')
                parts = msg.split(': ')
                if len(parts) > 1:
                    for name in parts[1].split(', '):
                        missing_pages.append({'page': name.strip()})

        # Extract orphan pages from issues
        orphan_pages = []
        for issue in result.get('issues', []):
            if issue.get('type') == 'orphan_page':
                orphan_pages.append({'page': issue.get('page', '')})

        # Also check lint hints for missing cross-refs
        for h in result.get('hints', {}).get('informational', []):
            msg = h.get('message', '')
            if 'missing' in msg.lower() and 'page' in msg.lower():
                parts = msg.split(': ')
                if len(parts) > 1:
                    for name in parts[1].split(', '):
                        name = name.strip()
                        if name and not any(m['page'] == name for m in missing_pages):
                            missing_pages.append({'page': name})

        print("=== Wiki Recommendations ===\n")

        if missing_pages:
            print(f"🔴 Missing Pages ({len(missing_pages)})\n")
            for rec in missing_pages[:10]:
                print(f"   • [[{rec['page']}]]")
            print()
        else:
            print("✅ No missing pages\n")

        if orphan_pages:
            print(f"🟠 Orphan Pages ({len(orphan_pages)})\n")
            for rec in orphan_pages[:10]:
                print(f"   • [[{rec['page']}]]")
            print()
        else:
            print("✅ No orphan pages\n")

        return 0

    def references(self, args: Any) -> int:
        """Show page references."""
        page_name = args.page
        detail = getattr(args, 'detail', False)
        inbound_only = getattr(args, 'inbound', False)
        outbound_only = getattr(args, 'outbound', False)
        stats = getattr(args, 'stats', False)
        broken = getattr(args, 'broken', False)

        if stats:
            return self._show_reference_stats(args)

        if broken:
            return self._show_broken_references(args)

        print(f"=== References: {page_name} ===\n")

        if not inbound_only:
            outbound = self.wiki.get_outbound_links(page_name, include_context=detail)
            if not outbound_only:
                inbound = self.wiki.get_inbound_links(page_name, include_context=detail)

                print(f"Inbound ({len(inbound)})")
                if inbound:
                    for i, link in enumerate(inbound, 1):
                        section = link.get('section', '')
                        print(f"  {i}. {link['source']} → {section}")
                        if detail and link.get('context'):
                            print(f"     Context: \"{link['context']}\"")
                    print()
                else:
                    print("  (none)\n")

            print(f"Outbound ({len(outbound)})")
            if outbound:
                for i, link in enumerate(outbound, 1):
                    section = link.get('section', '')
                    display = link.get('display', '')
                    display_str = f' [as "{display}"]' if display and display != link.get('target', '') else ''
                    print(f"  {i}. {link['target']}{section}{display_str}")
                    if detail and link.get('context'):
                        print(f"     Context: \"{link['context']}\"")
                print()
            else:
                print("  (none)\n")
        else:
            inbound = self.wiki.get_inbound_links(page_name, include_context=detail)
            print(f"Inbound ({len(inbound)})")
            if inbound:
                for i, link in enumerate(inbound, 1):
                    section = link.get('section', '')
                    print(f"  {i}. {link['source']} → {section}")
                    if detail and link.get('context'):
                        print(f"     Context: \"{link['context']}\"")
                print()
            else:
                print("  (none)\n")

        if not detail:
            print("---\n💡 Use --detail for full context")

        return 0

    def _show_reference_stats(self, args: Any) -> int:
        """Show reference statistics."""
        top = getattr(args, 'top', 10)

        inbound_counts: dict[str, int] = {}
        outbound_counts: dict[str, int] = {}
        orphans: list[str] = []

        for page_path in self.wiki._wiki_pages():
            page_name = self.wiki._page_display_name(page_path)

            inbound = self.wiki.index.get_inbound_links(page_name)
            outbound = self.wiki.index.get_outbound_links(page_name)

            inbound_counts[page_name] = len(inbound)
            outbound_counts[page_name] = len(outbound)

            if not inbound and not self.wiki._should_exclude_orphan(page_name, page_path):
                orphans.append(page_name)

        top_inbound = sorted(inbound_counts.items(), key=lambda x: -x[1])[:top]
        top_outbound = sorted(outbound_counts.items(), key=lambda x: -x[1])[:top]

        print("=== Reference Statistics ===\n")

        print(f"📈 Most Linked-To Pages (Top {top}):")
        for page_name, count in top_inbound:
            print(f"  {page_name}: {count} inbound")
        print()

        print(f"📊 Most Active Pages (Top {top}):")
        for page_name, count in top_outbound:
            print(f"  {page_name}: {count} outbound")
        print()

        if orphans:
            print(f"🟠 Orphan Pages ({len(orphans)}):")
            for page_name in orphans[:top]:
                print(f"  {page_name}")
        else:
            print("✅ No orphan pages")

        return 0

    def _show_broken_references(self, args: Any) -> int:
        """Show broken references."""
        broken = []

        for page in self.wiki._wiki_pages():
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = self.wiki._parse_wikilink_target(link)
                if target in (self.wiki._index_page_name, self.wiki._log_page_name):
                    continue
                if self.wiki._resolve_wikilink_target(target) is None:
                    broken.append({
                        "source": self.wiki._page_display_name(page),
                        "target": target,
                        "file": str(page),
                    })

        print("=== Broken References ===\n")

        if broken:
            for ref in broken:
                print(f"  ❌ {ref['source']} → [[{ref['target']}]]")
            print(f"\nTotal: {len(broken)} broken link(s)")
        else:
            print("✅ No broken references")

        return 0

    def batch(self, args: Any) -> int:
        """Batch ingest sources."""
        source_path = Path(args.source)
        limit = getattr(args, 'limit', 0)

        if source_path.is_dir():
            sources = list(source_path.rglob("*"))
            sources = [s for s in sources if s.is_file()]
        else:
            # Glob pattern
            sources = [Path(p) for p in glob_module.glob(str(source_path))]

        if limit:
            sources = sources[:limit]

        if not sources:
            print("❌ No sources found")
            return 1

        self_create = getattr(args, 'self_create', False) or getattr(args, 'smart', False)
        if getattr(args, 'smart', False):
            import warnings
            warnings.warn("--smart is deprecated, use --self-create instead", DeprecationWarning, stacklevel=2)
        dry_run = getattr(args, 'dry_run', False)

        if dry_run:
            if self_create:
                print("\n[DRY RUN] LLM self-create mode requested.", file=sys.stderr)
                print("Remove --dry-run to execute LLM processing.", file=sys.stderr)
            else:
                print("\nNo pages will be created. Use --self-create for LLM-assisted processing.", file=sys.stderr)
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

        print("=== Batch Ingest ===", file=sys.stderr)
        print(f"Found {len(sources)} source(s)\n", file=sys.stderr)

        success = 0
        failed = 0
        batch_results = []

        for i, source in enumerate(sources, 1):
            print(f"[{i}/{len(sources)}] Processing: {source.name}", file=sys.stderr)
            result = self.wiki.ingest_source(str(source))

            if "error" in result:
                print(f"  ❌ Error: {result['error']}", file=sys.stderr)
                failed += 1
                batch_results.append({
                    "source": str(source),
                    "status": "error",
                    "error": result["error"],
                })
            else:
                print(f"  ✅ {result['title']}", file=sys.stderr)
                if self_create:
                    try:
                        ops_result = self.wiki._llm_process_source(result)
                        ops = ops_result.get("operations", [])
                        if ops:
                            exec_result = self.wiki.execute_operations(ops)
                            print(f"    → {exec_result['operations_executed']} operations executed", file=sys.stderr)
                            batch_results.append({
                                "source": str(source),
                                "status": "processed",
                                "title": result.get("title", ""),
                                "source_name": result.get("source_name", ""),
                                "operations_executed": exec_result.get("operations_executed", 0),
                            })
                        else:
                            print("    → No operations planned by LLM", file=sys.stderr)
                            batch_results.append({
                                "source": str(source),
                                "status": "no_operations",
                                "title": result.get("title", ""),
                                "source_name": result.get("source_name", ""),
                            })
                    except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
                        print(f"    ⚠️ LLM processing skipped: {e}", file=sys.stderr)
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

        print("\n=== Batch Complete ===", file=sys.stderr)
        print(f"Success: {success}, Failed: {failed}", file=sys.stderr)

        return 0 if failed == 0 else 1

    def synthesize(self, args: Any) -> int:
        """Save query answer as wiki page."""
        answer = args.answer
        if not answer:
            answer = sys.stdin.read()

        if not answer:
            print("❌ Error: No answer content provided")
            return 1

        result = self.wiki.synthesize_query(
            query=args.query,
            answer=answer,
            source_pages=args.sources or [],
            raw_sources=getattr(args, 'raw_sources', None) or [],
            page_name=args.page_name,
            auto_link=not getattr(args, 'no_auto_link', False),
            auto_log=not getattr(args, 'no_auto_log', False),
            mode=args.mode,
        )

        if "error" in result:
            print(f"❌ {result['error']}")
            return 1

        print(f"✅ Synthesized: {result.get('page_name', args.query)}")
        return 0

    def watch(self, args: Any) -> int:
        """Watch raw/ directory for new files."""
        from ..core.watcher import (
            FileSystemWatcher,
            install_git_hook,
            uninstall_git_hook,
        )

        # Handle git hook operations
        if getattr(args, 'uninstall_hook', False):
            if uninstall_git_hook(self.wiki_root):
                return 0
            return 1

        if getattr(args, 'git_hook', False):
            if install_git_hook(self.wiki_root):
                return 0
            return 1

        # Determine watch directory
        watch_dir = Path(args.dir) if args.dir else self.wiki_root / 'raw'
        if not watch_dir.exists():
            print(f"❌ Watch directory does not exist: {watch_dir}")
            return 1

        auto_ingest = getattr(args, 'auto_ingest', False)
        self_create = getattr(args, 'self_create', False) or getattr(args, 'smart', False)
        if getattr(args, 'smart', False):
            import warnings
            warnings.warn("--smart is deprecated, use --self-create instead", DeprecationWarning, stacklevel=2)
        debounce = getattr(args, 'debounce', 2.0)
        dry_run = getattr(args, 'dry_run', False)

        print("=== File Watcher ===")
        print(f"Watching: {watch_dir}")
        print(f"Auto-ingest: {'Yes' if auto_ingest else 'No (notify only)'}")
        print(f"Debounce: {debounce}s")
        print(f"Dry run: {'Yes' if dry_run else 'No'}")
        print()
        print("Press Ctrl+C to stop.")
        print()

        if dry_run:
            print("[DRY RUN] Would start watcher. Remove --dry-run to actually watch.")
            return 0

        watcher = FileSystemWatcher(
            watch_dir=watch_dir,
            auto_ingest=auto_ingest and not dry_run,
            self_create=self_create,
            debounce=debounce,
        )

        def on_event(event_type: str, path: Path) -> None:
            icon = {"created": "📄", "modified": "✏️", "deleted": "🗑️", "moved": "📥"}.get(event_type, "❓")
            print(f"{icon} [{event_type}] {path.name}")

        try:
            watcher.start(on_event=on_event)
            # Keep running
            import time
            while watcher.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nWatcher stopped.")
        finally:
            watcher.stop()
            print(f"Stats: {watcher.stats['events']} events, {watcher.stats['ingests']} ingests")

        return 0

    def graph_query(self, args: Any) -> int:
        """Query the knowledge graph."""

        engine = self.wiki.get_relation_engine()
        subcommand = args.subcommand
        cmd_args = args.args or []

        if subcommand == "neighbors":
            if not cmd_args:
                print("❌ Usage: llmwikify graph-query neighbors <concept>")
                return 1
            concept = cmd_args[0]
            relations = engine.get_neighbors(concept)
            if not relations:
                print(f"No relations found for: {concept}")
                return 0
            print(f"Relations for: {concept}\n")
            for r in relations:
                direction = "→" if r["source"] == concept else "←"
                other = r["target"] if r["source"] == concept else r["source"]
                print(f"  {direction} [{r['relation']}] {other} ({r['confidence']})")
            print(f"\nTotal: {len(relations)}")

        elif subcommand == "path":
            if len(cmd_args) < 2:
                print("❌ Usage: llmwikify graph-query path <A> <B>")
                return 1
            result = engine.get_path(cmd_args[0], cmd_args[1])
            if result is None:
                print(f"No path found between {cmd_args[0]} and {cmd_args[1]}")
                return 0
            print(f"Path: {' → '.join(result['path'])}")
            for e in result['edges']:
                print(f"  {e['source']} -[{e['relation']}]-> {e['target']} ({e['confidence']})")

        elif subcommand == "stats":
            stats = engine.get_stats()
            print("=== Graph Statistics ===\n")
            print(f"Total relations: {stats['total_relations']}")
            print(f"Unique concepts: {stats['unique_concepts']}")
            print("\nBy confidence:")
            for level, count in stats['by_confidence'].items():
                print(f"  {level}: {count}")
            print("\nBy relation type:")
            for rel, count in stats['by_relation'].items():
                print(f"  {rel}: {count}")

        elif subcommand == "context":
            if not cmd_args:
                print("❌ Usage: llmwikify graph-query context <relation_id>")
                return 1
            rel_id = int(cmd_args[0])
            result = engine.get_context(rel_id)
            if result is None:
                print(f"Relation {rel_id} not found")
                return 1
            print(f"Relation #{rel_id}:")
            print(f"  {result['source']} -[{result['relation']}]-> {result['target']}")
            print(f"  Confidence: {result['confidence']}")
            if result.get('context'):
                print(f"  Context: {result['context']}")
            if result.get('source_file'):
                print(f"  Source file: {result['source_file']}")

        return 0

    def export_graph(self, args: Any) -> int:
        """Export knowledge graph visualization."""
        from ..core.graph_export import (
            build_graph,
            export_graphml,
            export_html,
            export_svg,
        )

        output = args.output
        fmt = args.format
        if not output:
            ext_map = {"html": ".html", "svg": ".svg", "graphml": ".graphml"}
            output = f"graph{ext_map.get(fmt, '.html')}"

        output_path = Path(output)

        print("=== Exporting Graph ===")
        print(f"Format: {fmt}")
        print(f"Output: {output_path}")

        graph = build_graph(self.wiki.index)

        try:
            if fmt == "html":
                result = export_html(graph, None, output_path, min_degree=args.min_degree)
            elif fmt == "graphml":
                result = export_graphml(graph, output_path)
            elif fmt == "svg":
                result = export_svg(graph, output_path)
            else:
                print(f"❌ Unsupported format: {fmt}")
                return 1

            print(f"\n✅ Exported: {result['nodes']} nodes, {result['edges']} edges")
            print(f"   Output: {result['output']}")
        except ImportError as e:
            print(f"❌ Missing dependency: {e}")
            return 1
        except (RuntimeError, OSError, ValueError) as e:
            print(f"❌ Export failed: {e}")
            return 1

        return 0

    def community_detect(self, args: Any) -> int:
        """Detect knowledge communities."""
        from ..core.graph_export import detect_communities

        result = detect_communities(
            self.wiki.index,
            algorithm=args.algorithm,
            resolution=args.resolution,
        )

        if "warning" in result:
            print(f"⚠️  {result['warning']}")

        if args.json:
            import json
            # Convert community nodes to lists for JSON
            output = {
                "communities": {str(k): v for k, v in result.get("communities", {}).items()},
                "num_communities": result["num_communities"],
                "modularity": result["modularity"],
                "total_nodes": result["total_nodes"],
                "total_edges": result["total_edges"],
            }
            print(json.dumps(output, indent=2))
            return 0

        if args.dry_run:
            print("=== Community Detection (Dry Run) ===")
            print(f"Algorithm: {args.algorithm}")
            print(f"Resolution: {args.resolution}")
            print(f"Nodes: {result['total_nodes']}")
            print(f"Edges: {result['total_edges']}")
            print(f"Communities: {result['num_communities']}")
            print(f"Modularity: {result['modularity']}")
            return 0

        print("=== Community Detection ===\n")
        print(f"Algorithm: {args.algorithm}")
        print(f"Resolution: {args.resolution}")
        print(f"Total nodes: {result['total_nodes']}")
        print(f"Total edges: {result['total_edges']}")
        print(f"Communities: {result['num_communities']}")
        print(f"Modularity: {result['modularity']} (0-1, higher = clearer separation)")
        print()

        communities = result.get("communities", {})
        for cid, nodes in sorted(communities.items()):
            print(f"Community {cid} ({len(nodes)} nodes):")
            for node in sorted(nodes)[:10]:
                print(f"  - {node}")
            if len(nodes) > 10:
                print(f"  ... and {len(nodes) - 10} more")
            print()

        return 0

    def report(self, args: Any) -> int:
        """Generate unexpected connections report."""
        from ..core.graph_export import detect_communities, generate_report

        comm_result = detect_communities(self.wiki.index)
        communities = comm_result.get("communities", {})

        report_text = generate_report(self.wiki.index, communities, top_n=args.top)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(report_text)
            print(f"Report written to: {output_path}")
        else:
            print(report_text)

        return 0

    def wikis(self, args: Any) -> int:
        """Multi-wiki management commands."""
        subcommand = getattr(args, 'wikis_subcommand', 'list')

        if subcommand == 'list':
            return self._wikis_list(args)
        elif subcommand == 'add':
            return self._wikis_add(args)
        elif subcommand == 'remove':
            return self._wikis_remove(args)
        elif subcommand == 'scan':
            return self._wikis_scan(args)
        else:
            print(f"Unknown wikis subcommand: {subcommand}")
            return 1

    def _wikis_list(self, args: Any) -> int:
        """List all registered wikis."""
        from ..core.wiki_registry import WikiRegistry
        from ..config import get_wikis_config

        wikis_config = get_wikis_config(self.config)
        registry = WikiRegistry(self.config)
        registry.initialize()

        wikis = registry.list_wikis()
        default_id = registry.get_default_wiki_id()

        if not wikis:
            print("No wikis registered.")
            print("\nTo add a wiki:")
            print("  llmwikify wikis add <wiki_id> --path /path/to/wiki")
            print("  llmwikify wikis scan .")
            return 0

        print(f"{'ID':<20} {'Name':<25} {'Type':<10} {'Pages':<10} {'Default':<10}")
        print("-" * 75)

        for wiki in wikis:
            is_default = "✓" if wiki.wiki_id == default_id else ""
            print(f"{wiki.wiki_id:<20} {wiki.name:<25} {wiki.wiki_type.value:<10} {wiki.page_count:<10} {is_default:<10}")

        registry.close()
        return 0

    def _wikis_add(self, args: Any) -> int:
        """Register a new wiki."""
        from ..core.wiki_registry import WikiRegistry
        from pathlib import Path

        wiki_id = args.wiki_id
        name = getattr(args, 'name', None) or wiki_id.replace('-', ' ').replace('_', ' ').title()
        path = getattr(args, 'path', None)
        url = getattr(args, 'url', None)
        api_key = getattr(args, 'api_key', None)

        registry = WikiRegistry(self.config)
        registry.initialize()

        if url:
            # Remote wiki
            instance = registry.register_remote(
                wiki_id=wiki_id,
                name=name,
                url=url,
                api_key=api_key,
            )
            print(f"✓ Registered remote wiki: {wiki_id}")
            print(f"  URL: {url}")
        elif path:
            # Local wiki
            root = Path(path).expanduser().resolve()
            if not root.exists():
                print(f"❌ Path does not exist: {root}")
                registry.close()
                return 1

            instance = registry.register_wiki(
                wiki_id=wiki_id,
                name=name,
                root=root,
            )
            print(f"✓ Registered local wiki: {wiki_id}")
            print(f"  Path: {root}")
        else:
            print("❌ Either --path or --url is required")
            registry.close()
            return 1

        print(f"  Name: {name}")
        registry.close()
        return 0

    def _wikis_remove(self, args: Any) -> int:
        """Unregister a wiki."""
        from ..core.wiki_registry import WikiRegistry

        wiki_id = args.wiki_id

        registry = WikiRegistry(self.config)
        registry.initialize()

        try:
            instance = registry.get_wiki_instance(wiki_id)
            registry.unregister_wiki(wiki_id)
            print(f"✓ Unregistered wiki: {wiki_id}")
            print(f"  Name: {instance.name}")
        except KeyError:
            print(f"❌ Wiki not found: {wiki_id}")
            registry.close()
            return 1

        registry.close()
        return 0

    def _wikis_scan(self, args: Any) -> int:
        """Scan directories for wikis."""
        from ..core.wiki_registry import WikiRegistry

        paths = getattr(args, 'paths', ['.'])
        depth = getattr(args, 'depth', 2)

        registry = WikiRegistry(self.config)
        registry.initialize()

        new_wikis = registry.scan_directories(paths, depth)

        if not new_wikis:
            print("No new wikis found.")
        else:
            print(f"Found {len(new_wikis)} new wiki(es):")
            for wiki in new_wikis:
                print(f"  • {wiki.wiki_id}: {wiki.name} ({wiki.root})")

        registry.close()
        return 0

    def suggest_synthesis(self, args: Any) -> int:
        """Analyze sources and generate cross-source synthesis suggestions."""
        source = getattr(args, 'source', None)
        as_json = getattr(args, 'json', False)

        result = self.wiki.suggest_synthesis(source_name=source)

        if "error" in result:
            print(f"Error: {result['error']}")
            return 1

        if as_json:
            import json
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        print("=== Cross-Source Synthesis Suggestions ===\n")
        print(f"Sources analyzed: {result['sources_analyzed']}")
        print(f"Total suggestions: {result['total_suggestions']}")
        print()

        for i, suggestion in enumerate(result['suggestions'], 1):
            print(f"--- Source {i}: {suggestion['source_name']} ---")

            if suggestion.get('reinforced_claims'):
                print(f"\n  ✅ Reinforced Claims ({len(suggestion['reinforced_claims'])})")
                for claim in suggestion['reinforced_claims'][:3]:
                    print(f"    • {claim['claim'][:80]}... (confirmed by {claim['confirmed_by_count']} source(s))")

            if suggestion.get('new_contradictions'):
                print(f"\n  ⚠️ Potential Contradictions ({len(suggestion['new_contradictions'])})")
                for contra in suggestion['new_contradictions'][:3]:
                    print(f"    • {contra.get('contradiction', contra.get('new_claim', 'unknown'))[:80]}...")

            if suggestion.get('knowledge_gaps'):
                print(f"\n  🔍 Knowledge Gaps ({len(suggestion['knowledge_gaps'])})")
                for gap in suggestion['knowledge_gaps'][:3]:
                    print(f"    • {gap['gap'][:80]}...")

            if suggestion.get('suggested_updates'):
                print(f"\n  📝 Suggested Updates ({len(suggestion['suggested_updates'])})")
                for update in suggestion['suggested_updates'][:3]:
                    print(f"    • {update['page']}: {update['reason'][:60]}...")

            if suggestion.get('new_entities'):
                print(f"\n  🆕 New Entities ({len(suggestion['new_entities'])})")
                for entity in suggestion['new_entities'][:3]:
                    print(f"    • {entity['name']} ({entity['type']})")

            print()

        print(f"\n{result['summary']}")
        return 0

    def knowledge_gaps(self, args: Any) -> int:
        """Detect knowledge gaps, outdated pages, and redundancy."""
        as_json = getattr(args, 'json', False)

        result = self.wiki.lint(generate_investigations=True)

        if as_json:
            import json
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        investigations = result.get('investigations', {})

        print("=== Knowledge Gap Analysis ===\n")
        print(f"Total pages: {result['total_pages']}")
        print(f"Total issues: {result['issue_count']}")
        print()

        # Outdated pages
        outdated = investigations.get('outdated_pages', [])
        if outdated:
            print(f"📅 Potentially Outdated Pages ({len(outdated)})")
            for page in outdated:
                print(f"  • {page['page']} (latest: {page.get('latest_year_mentioned', 'unknown')})")
            print()
        else:
            print("✅ No outdated pages detected")
            print()

        # Knowledge gaps
        gaps = investigations.get('knowledge_gaps', [])
        if gaps:
            print(f"🔍 Knowledge Gaps ({len(gaps)})")
            for gap in gaps:
                print(f"  • {gap['observation']}")
            print()
        else:
            print("✅ No knowledge gaps detected")
            print()

        # Redundancy alerts
        redundancy = investigations.get('redundancy_alerts', [])
        if redundancy:
            print(f"⚠️ Redundancy Alerts ({len(redundancy)})")
            for alert in redundancy:
                print(f"  • {alert['observation']}")
            print()
        else:
            print("✅ No redundancy detected")
            print()

        # Contradictions
        contradictions = investigations.get('contradictions', [])
        if contradictions:
            print(f"❌ Contradictions ({len(contradictions)})")
            for contra in contradictions:
                print(f"  • {contra.get('observation', contra.get('type', 'unknown'))}")
            print()

        return 0

    def graph_analyze(self, args: Any) -> int:
        """Analyze knowledge graph structure."""
        as_json = getattr(args, 'json', False)
        detailed_report = getattr(args, 'report', False)

        if detailed_report:
            report = self.wiki.graph_suggested_pages_report()
            print(report)
            return 0

        result = self.wiki.graph_analyze()

        if as_json:
            import json
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if result.get("status") == "empty":
            print(result.get("message", "No graph data available"))
            return 0

        print("=== Knowledge Graph Analysis ===\n")

        # Stats
        stats = result.get("stats", {})
        print(f"Nodes: {stats.get('nodes', 0)}")
        print(f"Edges: {stats.get('edges', 0)}")
        print(f"Density: {stats.get('density', 0)}")
        print(f"Connected: {'Yes' if stats.get('is_connected') else 'No'}")

        # Centrality
        centrality = result.get("centrality", {})
        if centrality.get("pagerank"):
            print("\n=== Core Concepts (PageRank) ===")
            for item in centrality["pagerank"][:5]:
                print(f"  • {item['node']} (score: {item['score']})")

        if centrality.get("hubs"):
            print("\n=== Hub Nodes (high out-degree) ===")
            for item in centrality["hubs"][:5]:
                print(f"  • {item['node']} (out-degree: {item['out_degree']})")

        if centrality.get("authorities"):
            print("\n=== Authority Nodes (high in-degree) ===")
            for item in centrality["authorities"][:5]:
                print(f"  • {item['node']} (in-degree: {item['in_degree']})")

        # Communities
        communities = result.get("communities", {})
        if communities.get("communities"):
            print(f"\n=== Communities ({communities.get('num_communities', 0)}) ===")
            for comm in list(communities["communities"].values())[:5]:
                print(f"  • {comm['label']}: {comm['size']} nodes")

            if communities.get("bridges"):
                print("\n=== Bridge Nodes ===")
                for bridge in communities["bridges"][:5]:
                    print(f"  • {bridge['node']}: {bridge['observation']}")

        # Suggestions
        suggestions = result.get("suggestions", [])
        if suggestions:
            print(f"\n=== Suggested Pages ({len(suggestions)}) ===")
            for sugg in suggestions[:10]:
                priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sugg.get("priority"), "•")
                print(f"  {priority_icon} [{sugg.get('priority', 'info').upper()}] {sugg['observation']}")
                print(f"     → {sugg['suggestion']}")
        else:
            print("\n✅ No suggestions at this time")

        print()
        return 0

    def serve(self, args: Any) -> int:
        """Start MCP server and optionally Web UI. Used by both 'mcp' and 'serve' subcommands."""
        from ..server import WikiServer
        from ..config import get_wikis_config

        mcp_config = self.config.get("mcp", {})

        name = getattr(args, 'name', None)
        transport = getattr(args, 'transport', None)
        host = getattr(args, 'host', None)
        mcp_port = getattr(args, 'mcp_port', None) or getattr(args, 'port', None)
        web = getattr(args, 'web', False)
        auth_token = getattr(args, 'auth_token', None)
        multi_wiki = getattr(args, 'multi_wiki', False)

        service_name = name or mcp_config.get("name") or self.wiki.root.name
        port = mcp_port or mcp_config.get('port', 8765)
        final_host = host or mcp_config.get('host', '127.0.0.1')
        final_transport = transport or mcp_config.get('transport', 'stdio')

        try:
            # Check if multi-wiki mode is enabled
            wikis_config = get_wikis_config(self.config)
            has_wikis_config = wikis_config.get('local') or wikis_config.get('remote')

            if multi_wiki or has_wikis_config:
                # Multi-wiki mode
                from ..core.wiki_registry import WikiRegistry
                registry = WikiRegistry(self.config)
                registry.initialize()

                # Auto-discover wikis by scanning for .llmwikify.db files
                if not registry.list_wikis():
                    discovered = registry.scan_directories(["."], 3)
                    if discovered:
                        print(f"  Discovered: {len(discovered)} wiki(s)")

                server = WikiServer(
                    registry,
                    api_key=auth_token,
                    mcp_name=service_name,
                    enable_mcp=True,
                    enable_rest=True,
                    enable_webui=web,
                )

                wiki_count = len(registry.list_wikis())
                print(f"Starting Multi-Wiki Server '{service_name}' on {final_host}:{port}")
                print(f"  Wikis: {wiki_count} registered")
                print(f"  Transport: http")
                print(f"  Auth: {'enabled' if auth_token else 'disabled'}")
                if web:
                    print(f"  Web UI: http://{final_host}:{port}")
                    print(f"  API Docs: http://{final_host}:{port}/docs")
                print()

                server.run(host=final_host, port=port)
            else:
                # Single wiki mode (backward compatible)
                if web:
                    server = WikiServer(
                        self.wiki,
                        api_key=auth_token,
                        mcp_name=service_name,
                        enable_mcp=True,
                        enable_rest=True,
                        enable_webui=True,
                    )

                    print(f"Starting Unified Server '{service_name}' on {final_host}:{port}")
                    print("  Transport: http")
                    print(f"  Auth: {'enabled' if auth_token else 'disabled'}")
                    print(f"  Web UI: http://{final_host}:{port}")
                    print(f"  API Docs: http://{final_host}:{port}/docs")
                    print()

                    server.run(host=final_host, port=port)
                else:
                    print(f"Starting MCP server '{service_name}'...")
                    print(f"  Transport: {final_transport}")
                    if final_host != '127.0.0.1':
                        print(f"  Host: {final_host}")
                    if port != 8765:
                        print(f"  Port: {port}")
                    print()

                    # Use original serve_mcp for pure MCP mode (backward compatible)
                    from ..mcp.server import serve_mcp
                    serve_mcp(self.wiki, name=name, transport=transport, host=host, port=mcp_port, config=mcp_config)
        except KeyboardInterrupt:
            print("\nServer stopped")

        return 0

    def _get_content(self, args: Any) -> str | None:
        """Get content from file, argument, or stdin."""
        if getattr(args, 'file', None):
            try:
                with open(args.file) as f:
                    return f.read()
            except OSError as e:
                print(f"❌ Error reading file: {e}")
                return None
        elif getattr(args, 'content', None):
            return str(args.content)
        else:
            return sys.stdin.read()

    # ============================================================
    # QMD - Hybrid Search Engine Commands
    # ============================================================

    def qmd(self, args: Any) -> int:
        """QMD hybrid search commands (status, search, install, embed, start)."""
        subcommand = getattr(args, 'qmd_subcommand', 'status')

        if subcommand == 'status':
            return self._qmd_status(args)
        elif subcommand == 'search':
            return self._qmd_search(args)
        elif subcommand == 'install':
            return self._qmd_install(args)
        elif subcommand == 'embed':
            return self._qmd_embed(args)
        elif subcommand == 'mcp':
            return self._qmd_mcp(args)
        else:
            print(f"Unknown qmd subcommand: {subcommand}")
            return 1

    def _qmd_status(self, args: Any) -> int:
        """Display QMD status and recommendations."""
        status = self.wiki.qmd_status()

        print("📊 QMD Hybrid Search Status")
        print(f"   Pages in wiki: {status['page_count']}")
        print(f"   QMD threshold: {status.get('threshold', 1000)} pages")
        print(f"   Configured backend: {status.get('backend', 'fts5')}")
        print(f"   QMD available: {'✅ Yes' if status['available'] else '❌ No'}")
        print(f"   QMD recommended: {'✅ Yes' if status['recommended'] else 'ℹ️ No'}")

        if status.get('message'):
            print(f"\n💡 {status['message']}")

        return 0

    def _qmd_search(self, args: Any) -> int:
        """Search using QMD hybrid engine."""
        results = self.wiki.search(args.query, getattr(args, 'limit', 10), backend="qmd")

        if not results:
            print("No results found from QMD.")
            print("Make sure QMD MCP server is running: `qmd mcp --http --port 8181`")
            return 1

        print(f"🔍 QMD Hybrid Search results for: {args.query}")
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['page_name']}")
            print(f"   Score: {r['score']:.4f}")
            print(f"   {r['snippet']}")

        return 0

    def _qmd_install(self, args: Any) -> int:
        """Display QMD installation instructions."""
        qmd = self.wiki.qmd
        if qmd:
            print(qmd.get_install_guide())
        else:
            # Fallback if QmdIndex not loaded
            from ..core.qmd_client import QmdClient
            client = QmdClient()
            print(client.get_install_guide())
        return 0

    def _qmd_embed(self, args: Any) -> int:
        """Trigger QMD embedding generation."""
        qmd = self.wiki.qmd
        if not qmd or not qmd.is_available():
            print("❌ QMD server not available.")
            print("Start the server first: `qmd mcp --http --port 8181`")
            return 1

        print("🔄 Starting embedding generation...")
        print("(This may take several minutes on first run)")
        result = qmd.embed()
        print(f"\nResult: {result.get('status', 'unknown')}")
        return 0

    def _qmd_mcp(self, args: Any) -> int:
        """Start QMD MCP server (delegates to external qmd command)."""
        import subprocess

        port = getattr(args, 'port', 8181)
        host = getattr(args, 'host', '127.0.0.1')

        cmd = ['qmd', 'mcp', '--http', '--port', str(port), '--host', host]

        if getattr(args, 'collection', None):
            cmd.extend(['--collection', args.collection])

        print(f"Starting QMD MCP server: {' '.join(cmd)}")
        print("Press Ctrl+C to stop")

        try:
            subprocess.run(cmd, cwd=self.wiki.root)
        except KeyboardInterrupt:
            print("\nServer stopped")
        except FileNotFoundError:
            print("❌ 'qmd' command not found. Install QMD first:")
            print("   npm install -g @tobilu/qmd")
            return 1

        return 0

    def db(self, args: Any) -> int:
        """Database management commands (stats, list, clean, export)."""
        subcommand = getattr(args, 'db_subcommand', 'stats')

        if subcommand == 'stats':
            return self._db_stats(args)
        elif subcommand == 'list':
            return self._db_list(args)
        elif subcommand == 'clean':
            return self._db_clean(args)
        elif subcommand == 'export':
            return self._db_export(args)
        else:
            print(f"Unknown db subcommand: {subcommand}")
            return 1

    def _db_stats(self, args: Any) -> int:
        """Show database statistics."""
        from ..agent.backend.db import AgentDatabase, get_agent_db_path

        db_path = get_agent_db_path(self.wiki.root / '.llmwikify' / 'agent')
        if not db_path.exists():
            print("No agent database found.")
            return 1

        db = AgentDatabase(db_path)
        stats = db.get_db_stats()

        print("📊 Database Statistics")
        print(f"   Path: {stats['db_path']}")
        print(f"   Size: {stats['size_mb']:.2f} MB")
        print()

        wiki_id = getattr(args, 'wiki_id', None)
        if wiki_id:
            wiki_stats = db.get_wiki_stats(wiki_id)
            print(f"   Wiki: {wiki_stats['wiki_id']}")
            print(f"     Chat sessions: {wiki_stats['chat_sessions']}")
            print(f"     Research sessions: {wiki_stats['research_sessions']}")
            print(f"     Research sources: {wiki_stats['research_sources']}")
        else:
            print("   Tables:")
            for table, count in stats['tables'].items():
                print(f"     {table}: {count} rows")

        return 0

    def _db_list(self, args: Any) -> int:
        """List all wikis."""
        from ..agent.backend.db import AgentDatabase, get_agent_db_path

        db_path = get_agent_db_path(self.wiki.root / '.llmwikify' / 'agent')
        if not db_path.exists():
            print("No agent database found.")
            return 1

        db = AgentDatabase(db_path)
        wikis = db.list_all_wikis()

        if not wikis:
            print("No wikis found in database.")
            return 0

        print("📋 Wikis in Database")
        print()
        for wiki in wikis:
            print(f"  {wiki['wiki_id']}")
            print(f"    Chat sessions: {wiki['chat_sessions']}")
            print(f"    Research sessions: {wiki['research_sessions']}")
            print(f"    Research sources: {wiki['research_sources']}")
            print()

        return 0

    def _db_clean(self, args: Any) -> int:
        """Delete all data for a wiki."""
        from ..agent.backend.db import AgentDatabase, get_agent_db_path

        wiki_id = args.wiki_id
        force = getattr(args, 'force', False)

        if not force:
            print(f"⚠️  This will delete all data for wiki '{wiki_id}'.")
            confirm = input("Type 'yes' to confirm: ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return 0

        db_path = get_agent_db_path(self.wiki.root / '.llmwikify' / 'agent')
        if not db_path.exists():
            print("No agent database found.")
            return 1

        db = AgentDatabase(db_path)
        result = db.delete_wiki_data(wiki_id)

        print(f"✅ Deleted data for wiki '{wiki_id}':")
        print(f"   Chat sessions: {result['chat_sessions']}")
        print(f"   Research sessions: {result['research_sessions']}")
        print(f"   Tool calls: {result['tool_calls']}")
        print(f"   Ingest log: {result['ingest_log']}")

        return 0

    def _db_export(self, args: Any) -> int:
        """Export wiki data to JSON."""
        from ..agent.backend.db import AgentDatabase, get_agent_db_path

        wiki_id = args.wiki_id
        output = args.output

        db_path = get_agent_db_path(self.wiki.root / '.llmwikify' / 'agent')
        if not db_path.exists():
            print("No agent database found.")
            return 1

        db = AgentDatabase(db_path)
        data = db.export_wiki_data(wiki_id)

        with open(output, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        print(f"✅ Exported data for wiki '{wiki_id}' to {output}")
        print(f"   Chat sessions: {len(data['chat_sessions'])}")
        print(f"   Chat messages: {len(data['chat_messages'])}")
        print(f"   Research sessions: {len(data['research_sessions'])}")
        print(f"   Research sources: {len(data['research_sources'])}")
        print(f"   Research sub-queries: {len(data['research_sub_queries'])}")
        print(f"   Tool calls: {len(data['tool_calls'])}")

        return 0

def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='llmwikify',
        description='llmwikify CLI - LLM Wiki Management',
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
  llmwikify mcp                                       Start MCP server for Agent interaction
  llmwikify mcp --transport http --port 8765          Start MCP server on HTTP port
  llmwikify serve --web                               Start unified server (MCP + WebUI) on :8765
  llmwikify serve --web --auth-token mysecret         Start unified server with API key auth
"""
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # init
    p = subparsers.add_parser('init', help='Initialize wiki')
    p.add_argument('--overwrite', action='store_true', help='Recreate index.md and log.md if they exist')
    p.add_argument('--agent', type=str, choices=['opencode', 'claude', 'codex', 'generic'],
                   help='Generate agent-specific config files (required for MCP setup)')
    p.add_argument('--force', action='store_true', help='Overwrite existing files without prompting')
    p.add_argument('--merge', action='store_true', help='Merge into existing wiki.md instead of skipping')

    # ingest
    p = subparsers.add_parser('ingest', help='Ingest a source file')
    p.add_argument('file', type=str, help='File path or URL')
    p.add_argument('--self-create', '-s', action='store_true',
                   help='CLI uses LLM API to automatically analyze content and create wiki pages')
    p.add_argument('--smart', action='store_true', help='[Deprecated] Alias for --self-create')
    p.add_argument('--dry-run', '-n', action='store_true',
                   help='Show extraction summary without creating pages')

    # analyze-source
    p = subparsers.add_parser('analyze-source', help='Analyze source and cache extraction results')
    p.add_argument('source', nargs='?', help='Source path (e.g., raw/article.md)')
    p.add_argument('--all', '-a', action='store_true', help='Analyze all sources')
    p.add_argument('--force', '-f', action='store_true', help='Force re-analysis')

    # write_page
    p = subparsers.add_parser('write_page', help='Write page')
    p.add_argument('name', help='Page name')
    p.add_argument('--type', '-t', help='Page type from wiki.md Page Types table (e.g., concept, model, source)')
    p.add_argument('--file', '-f', help='Read content from file')
    p.add_argument('--content', '-c', help='Content as string')

    # read_page
    p = subparsers.add_parser('read_page', help='Read page')
    p.add_argument('name', help='Page name')
    p.add_argument('--type', '-t', help='Page type from wiki.md Page Types table')

    # search
    p = subparsers.add_parser('search', help='Full-text search')
    p.add_argument('query', help='Search query')
    p.add_argument('--limit', '-l', type=int, default=10)
    p.add_argument('--backend', '-b', choices=['fts5', 'qmd'], default='fts5',
                   help='Search backend: fts5 (default, fast) or qmd (hybrid semantic)')

    # lint
    p = subparsers.add_parser('lint', help='Health check')
    p.add_argument('--format', '-f', choices=['full', 'brief', 'recommendations', 'json'],
                   default='full', help='Output format (default: full)')
    p.add_argument('--generate-investigations', '-g', action='store_true',
                   help='Use LLM to generate investigation suggestions')
    p.add_argument('--mode', choices=['check', 'fix'], default='check',
                   help='Lint mode: check (default) or fix')
    p.add_argument('--limit', '-l', type=int, default=10,
                   help='Max LLM-detected issues to return (default: 10)')
    p.add_argument('--force', action='store_true',
                   help='Force re-detection (ignore cache)')

    # status
    subparsers.add_parser('status', help='Show status')

    # log
    p = subparsers.add_parser('log', help='Record log')
    p.add_argument('operation', nargs='?', help='Operation name (positional)')
    p.add_argument('description', nargs='?', help='Description (positional)')
    p.add_argument('--operation', '-o', dest='op_flag', help='Operation name (flag)')
    p.add_argument('--details', '-d', help='Description (flag)')

    # build-index
    p = subparsers.add_parser('build-index', help='Build or export reference index')
    p.add_argument('--no-export', action='store_true', help='Skip JSON export')
    p.add_argument('--output', '-o', help='JSON output path')
    p.add_argument('--export-only', action='store_true', help='Export existing index without rebuilding')
    p.add_argument('--force', action='store_true', help='Force rebuild even if old format detected')

    # fix-wikilinks
    p = subparsers.add_parser('fix-wikilinks', help='Fix broken wikilinks by adding directory prefix')
    p.add_argument('--dry-run', '-n', action='store_true',
                   help='Preview changes without modifying files')

    # references
    p = subparsers.add_parser('references', help='Show page references')
    p.add_argument('page', help='Page name')
    p.add_argument('--detail', '-d', action='store_true', help='Show full context')
    p.add_argument('--inbound', '-i', action='store_true', help='Show only inbound')
    p.add_argument('--outbound', '-o', action='store_true', help='Show only outbound')
    p.add_argument('--stats', '-s', action='store_true', help='Show reference statistics')
    p.add_argument('--broken', '-b', action='store_true', help='Show broken references')
    p.add_argument('--top', '-t', type=int, default=10, help='Top N for stats')

    # batch
    p = subparsers.add_parser('batch', help='Batch ingest sources')
    p.add_argument('source', help='Directory or glob pattern')
    p.add_argument('--limit', '-l', type=int, default=0, help='Limit number of sources')
    p.add_argument('--self-create', '-s', action='store_true',
                   help='CLI uses LLM API to automatically process content and create wiki pages')
    p.add_argument('--smart', action='store_true', help='[Deprecated] Alias for --self-create')
    p.add_argument('--dry-run', '-n', action='store_true',
                   help='Preview extraction without creating pages')

    # sink-status
    subparsers.add_parser('sink-status', help='Show query sink buffer status')

    # synthesize
    p = subparsers.add_parser('synthesize', help='Save query answer as wiki page')
    p.add_argument('query', help='Original question')
    p.add_argument('--answer', '-a', help='Answer content (or read from stdin)')
    p.add_argument('--page-name', '-n', help='Custom page name')
    p.add_argument('--sources', nargs='*', help='Source pages to link')
    p.add_argument('--raw-sources', nargs='*', help='Raw source files to cite')
    p.add_argument('--mode', choices=['sink', 'update'], default='sink',
                   help='Strategy when similar query exists')
    p.add_argument('--no-auto-link', action='store_true', help='Disable automatic wikilink insertion')
    p.add_argument('--no-auto-log', action='store_true', help='Disable automatic log entry')

    # watch
    p = subparsers.add_parser('watch', help='Watch raw/ directory for new files')
    p.add_argument('dir', nargs='?', default=None, help='Directory to watch (default: raw/)')
    p.add_argument('--auto-ingest', action='store_true',
                   help='Automatically ingest new files')
    p.add_argument('--self-create', '-s', action='store_true',
                   help='CLI uses LLM API to process files (requires --auto-ingest)')
    p.add_argument('--smart', action='store_true', help='[Deprecated] Alias for --self-create')
    p.add_argument('--debounce', type=float, default=2.0,
                   help='Debounce time in seconds (default: 2)')
    p.add_argument('--dry-run', '-n', action='store_true',
                   help='Only print events, do not ingest')
    p.add_argument('--git-hook', action='store_true',
                   help='Install git post-commit hook instead of watching')
    p.add_argument('--uninstall-hook', action='store_true',
                   help='Uninstall git post-commit hook')

    # graph-query
    p = subparsers.add_parser('graph-query', help='Query the knowledge graph')
    p.add_argument('subcommand', choices=['neighbors', 'path', 'stats', 'context'],
                   help='Query type')
    p.add_argument('args', nargs='*', help='Arguments (concept name, path endpoints, relation id)')

    # export-graph
    p = subparsers.add_parser('export-graph', help='Export knowledge graph visualization')
    p.add_argument('--format', choices=['html', 'svg', 'graphml'], default='html',
                   help='Output format (default: html)')
    p.add_argument('--output', '-o', default=None, help='Output file path')
    p.add_argument('--min-degree', type=int, default=0, help='Filter nodes below this degree')

    # community-detect
    p = subparsers.add_parser('community-detect', help='Detect knowledge communities')
    p.add_argument('--algorithm', choices=['leiden', 'louvain'], default='leiden',
                   help='Detection algorithm (default: leiden)')
    p.add_argument('--resolution', type=float, default=1.0,
                   help='Resolution parameter (default: 1.0)')
    p.add_argument('--json', action='store_true', help='Output as JSON')
    p.add_argument('--dry-run', '-n', action='store_true', help='Only print stats')

    # report
    p = subparsers.add_parser('report', help='Generate unexpected connections report')
    p.add_argument('--top', type=int, default=10, help='Number of top connections (default: 10)')
    p.add_argument('--output', '-o', default=None, help='Output file path')

    # suggest-synthesis (P1.1)
    p = subparsers.add_parser('suggest-synthesis', help='Analyze sources and generate cross-source synthesis suggestions')
    p.add_argument('source', nargs='?', default=None, help='Specific source to analyze (default: all unanalyzed sources)')
    p.add_argument('--json', action='store_true', help='Output as JSON')

    # knowledge-gaps (P1.2)
    p = subparsers.add_parser('knowledge-gaps', help='Detect knowledge gaps, outdated pages, and redundancy')
    p.add_argument('--json', action='store_true', help='Output as JSON')
    p.add_argument('--include-suggestions', '-s', action='store_true', help='Include suggested sources to fill gaps')

    # graph-analyze (P1.3)
    p = subparsers.add_parser('graph-analyze', help='Analyze knowledge graph structure (PageRank, communities, suggestions)')
    p.add_argument('--json', action='store_true', help='Output as JSON')
    p.add_argument('--report', action='store_true', help='Generate detailed suggested pages report')

    # wikis - Multi-wiki management
    wikis_parsers = subparsers.add_parser('wikis', help='Multi-wiki management commands')
    wikis_sub = wikis_parsers.add_subparsers(dest='wikis_subcommand',
                                              help='Wikis subcommands: list, add, remove, scan')
    wikis_sub.required = True

    # wikis list
    wikis_sub.add_parser('list', help='List all registered wikis')

    # wikis add
    p = wikis_sub.add_parser('add', help='Register a new wiki')
    p.add_argument('wiki_id', help='Unique wiki identifier')
    p.add_argument('--name', '-n', help='Display name')
    p.add_argument('--path', help='Root directory path (for local wikis)')
    p.add_argument('--url', help='Server URL (for remote wikis)')
    p.add_argument('--api-key', help='API key (for remote wikis)')

    # wikis remove
    p = wikis_sub.add_parser('remove', help='Unregister a wiki')
    p.add_argument('wiki_id', help='Wiki identifier to remove')

    # wikis scan
    p = wikis_sub.add_parser('scan', help='Scan directories for wikis')
    p.add_argument('paths', nargs='*', default=['.'], help='Directories to scan')
    p.add_argument('--depth', type=int, default=2, help='Scan depth')

    # mcp
    p = subparsers.add_parser('mcp', help='Start MCP server for Agent interaction (stdio by default)')
    p.add_argument('--transport', '-t', choices=['stdio', 'http', 'sse'], help='Transport protocol')
    p.add_argument('--host', help='Host address')
    p.add_argument('--port', '-p', type=int, help='Port number')
    p.add_argument('--name', '-n', help='Service name (defaults to directory name)')

    # serve
    p = subparsers.add_parser('serve', help='Start MCP server with optional Web UI')
    p.add_argument('--transport', '-t', choices=['stdio', 'http', 'sse'], help='Transport protocol')
    p.add_argument('--host', help='Host address')
    p.add_argument('--mcp-port', type=int, help='MCP server port')
    p.add_argument('--port', '-p', type=int, help='[Deprecated] Use --mcp-port instead')
    p.add_argument('--name', '-n', help='Service name (defaults to directory name)')
    p.add_argument('--web', action='store_true', help='Start unified Web UI (single process)')
    p.add_argument('--auth-token', help='API Key for authentication')
    p.add_argument('--multi-wiki', action='store_true', help='Enable multi-wiki mode')

    # qmd - QMD Hybrid Search Engine
    qmd_parsers = subparsers.add_parser('qmd', help='QMD hybrid search engine commands')
    qmd_sub = qmd_parsers.add_subparsers(dest='qmd_subcommand',
                                          help='QMD subcommands: status, search, install, embed, mcp')

    # qmd status
    p = qmd_sub.add_parser('status', help='Show QMD status and recommendations')

    # qmd search
    p = qmd_sub.add_parser('search', help='QMD hybrid search')
    p.add_argument('query', help='Search query')
    p.add_argument('--limit', '-l', type=int, default=10)

    # qmd install
    p = qmd_sub.add_parser('install', help='Show QMD installation guide')

    # qmd embed
    p = qmd_sub.add_parser('embed', help='Trigger QMD embedding generation')

    # qmd mcp
    p = qmd_sub.add_parser('mcp', help='Start QMD MCP server')
    p.add_argument('--port', '-p', type=int, default=8181, help='Port (default: 8181)')
    p.add_argument('--host', default='127.0.0.1', help='Bind address')
    p.add_argument('--collection', help='Collection name')

    # db - Database management
    db_parsers = subparsers.add_parser('db', help='Database management commands')
    db_sub = db_parsers.add_subparsers(dest='db_subcommand', help='DB subcommands')

    # db stats
    p = db_sub.add_parser('stats', help='Show database statistics')
    p.add_argument('wiki_id', nargs='?', help='Wiki ID (optional, shows all if omitted)')

    # db list
    p = db_sub.add_parser('list', help='List all wikis')

    # db clean
    p = db_sub.add_parser('clean', help='Delete all data for a wiki')
    p.add_argument('wiki_id', help='Wiki ID to delete')
    p.add_argument('--force', '-f', action='store_true', help='Skip confirmation')

    # db export
    p = db_sub.add_parser('export', help='Export wiki data to JSON')
    p.add_argument('wiki_id', help='Wiki ID to export')
    p.add_argument('output', help='Output file path')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    wiki_root = Path(os.environ.get('WIKI_ROOT', Path.cwd()))

    # Load configuration
    config: dict[str, Any] = {}
    config_file = wiki_root / '.wiki-config.yaml'
    if config_file.exists():
        try:
            import yaml
            config = yaml.safe_load(config_file.read_text()) or {}
        except Exception as e:
            logger.warning("Failed to load config from %s: %s", config_file, e)

    cli = WikiCLI(wiki_root, config=config)

    commands = {
        'init': cli.init,
        'ingest': cli.ingest,
        'analyze-source': cli.analyze_source,
        'write_page': cli.write_page,
        'read_page': cli.read_page,
        'search': cli.search,
        'lint': cli.lint,
        'status': cli.status,
        'log': cli.log,
        'build-index': cli.build_index,
        'fix-wikilinks': cli.fix_wikilinks,
        'references': cli.references,
        'batch': cli.batch,
        'sink-status': cli.sink_status,
        'synthesize': cli.synthesize,
        'watch': cli.watch,
        'graph-query': cli.graph_query,
        'export-graph': cli.export_graph,
        'community-detect': cli.community_detect,
        'report': cli.report,
        'suggest-synthesis': cli.suggest_synthesis,
        'knowledge-gaps': cli.knowledge_gaps,
        'graph-analyze': cli.graph_analyze,
        'mcp': cli.serve,
        'serve': cli.serve,
        'qmd': cli.qmd,
        'db': cli.db,
    }

    try:
        return commands[args.command](args)
    finally:
        cli.wiki.close()
