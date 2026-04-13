"""CLI commands for llmwikify."""

import argparse
import json
import sys
import os
import re
import glob as glob_module
from pathlib import Path
from typing import Optional

from ..core import Wiki


class WikiCLI:
    """CLI command handler."""
    
    def __init__(self, wiki_root: Path, config: Optional[dict] = None):
        self.wiki_root = wiki_root
        self.config = config or {}
        self.wiki = Wiki(wiki_root, config=self.config)
    
    def init(self, args) -> int:
        """Initialize wiki."""
        from ..core.wiki import VALID_AGENTS
        
        overwrite = getattr(args, 'overwrite', False)
        agent = getattr(args, 'agent', None)
        force = getattr(args, 'force', False)
        merge = getattr(args, 'merge', False)
        
        if agent and agent not in VALID_AGENTS:
            print(f"Error: Invalid agent type '{agent}'.")
            print(f"  Choose: {', '.join(VALID_AGENTS)}")
            print(f"  Example: llmwikify init --agent opencode")
            return 1
        
        result = self.wiki.init(overwrite=overwrite, agent=agent, force=force, merge=merge)
        
        if result['status'] == 'already_exists':
            print(f"⚠️  Wiki already initialized at {self.wiki_root}")
            print(f"   Existing files: {', '.join(result['existing_files'])}")
            if agent:
                print(f"   Use --force to overwrite or --merge to regenerate agent config.")
            else:
                print(f"   Use --overwrite to reinitialize.")
            return 0
        
        if result['status'] == 'agent_config_added':
            print(f"✅ Agent config added to existing wiki at {self.wiki_root}")
            if result['created_files']:
                print(f"   Added: {', '.join(result['created_files'])}")
            warnings = result.get('warnings', [])
            if warnings:
                for w in warnings:
                    print(f"   ⚠️  {w}")
            return 0
        
        print(f"✅ {result['message']}")
        print()
        
        if result['created_files']:
            print(f"  Created: {', '.join(result['created_files'])}")
        if result['skipped_files']:
            print(f"  Skipped: {', '.join(result['skipped_files'])}")
        
        warnings = result.get('warnings', [])
        if warnings:
            print()
            for w in warnings:
                print(f"  ⚠️  {w}")
        
        raw_stats = result.get('raw_stats', {})
        if raw_stats and raw_stats.get('total', 0) > 0:
            print()
            print(f"  Source analysis:")
            print(f"    {raw_stats['total']} files in {len(raw_stats.get('categories', {}))} categories")
            top_cats = sorted(raw_stats.get('categories', {}).items(), key=lambda x: -x[1])[:5]
            print(f"    Top: {', '.join(f'{k} ({v})' for k, v in top_cats)}")
        
        print()
        print(f"  Next steps:")
        if agent:
            print(f"    1. Review wiki.md for page conventions")
            if agent == 'opencode':
                print(f"    2. Run: opencode")
            elif agent == 'claude':
                print(f"    2. Run: claude")
            elif agent == 'codex':
                print(f"    2. Run: opencode (codex mode)")
            print(f"    3. Tell the agent: 'Start ingesting news from raw/'")
        else:
            print(f"    Run: llmwikify init --agent <opencode|claude|codex|generic> for full setup")
        
        return 0
    
    def ingest(self, args) -> int:
        """Ingest a source file."""
        source = args.file
        result = self.wiki.ingest_source(source)
        
        if "error" in result:
            print(f"Error: {result['error']}")
            return 1
        
        # Display extraction summary to stderr (for human readability)
        print(f"Ingested: {result['title']} ({result['source_type']})", file=sys.stderr)
        print(f"Content length: {result['content_length']:,} chars", file=sys.stderr)
        
        if result.get('saved_to_raw'):
            print(f"Saved to raw: {result['source_name']}", file=sys.stderr)
        elif result.get('already_exists'):
            print(f"Already in raw: {result['source_name']}", file=sys.stderr)
        elif result.get('source_name'):
            print(f"Source: {result['source_raw_path']}", file=sys.stderr)
        
        if result['content_length'] > 8000:
            print(f"Note: Content truncated to 8,000 chars for LLM processing", file=sys.stderr)
        
        smart = getattr(args, 'smart', False)
        dry_run = getattr(args, 'dry_run', False)
        
        if dry_run:
            if smart:
                print("\n[DRY RUN] LLM smart mode requested.", file=sys.stderr)
                print("Remove --dry-run to execute LLM processing.", file=sys.stderr)
            else:
                print("\nNo pages created. Use --smart for LLM-assisted processing.", file=sys.stderr)
            return 0
        
        if smart:
            return self._ingest_smart(result)
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
                "message": "Read the content above, read wiki.md for conventions, then create/update wiki pages using write_page.",
            }
            print(f"\n{json.dumps(output, ensure_ascii=False, indent=2)}")
            return 0
    
    def _ingest_smart(self, result: dict) -> int:
        """Execute LLM smart processing on ingested content."""
        try:
            operations_result = self.wiki._llm_process_source(result)
        except ValueError as e:
            print(f"\nLLM not configured: {e}")
            print("Enable LLM in .wiki-config.yaml:")
            print("  llm:")
            print("    enabled: true")
            print("    api_key: your-key-here")
            print("    model: gpt-4o")
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
        execution = self.wiki.execute_operations(operations)
        
        for r in execution.get("results", []):
            status_icon = "ok" if r.get("status") == "done" else "!!"
            action = r.get("action", "")
            detail = r.get("page", r.get("operation", ""))
            print(f"  [{status_icon}] {action}: {detail}")
        
        # Write relations if extracted
        relations = operations_result.get("relations", [])
        if relations:
            print(f"\nExtracting {len(relations)} relations...")
            rel_result = self.wiki.write_relations(relations, source_file=result.get("source_name"))
            print(f"  Relations added: {rel_result.get('count', 0)}")
        
        print(f"\nCompleted: {execution['operations_executed']} operations")
        return 0
    
    def write_page(self, args) -> int:
        """Write a wiki page."""
        content = self._get_content(args)
        if not content:
            print("❌ Error: No content provided")
            return 1
        
        result = self.wiki.write_page(args.name, content)
        print(f"✅ {result}")
        return 0
    
    def read_page(self, args) -> int:
        """Read a wiki page."""
        result = self.wiki.read_page(args.name)
        
        if "error" in result:
            print(f"❌ {result['error']}")
            return 1
        
        print(result['content'])
        return 0
    
    def search(self, args) -> int:
        """Search wiki."""
        results = self.wiki.search(args.query, getattr(args, 'limit', 10))
        
        if not results:
            print(f"No results found for: {args.query}")
            return 0
        
        print(f"Search results for: {args.query}")
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['page_name']}")
            print(f"   Score: {r['score']}")
            print(f"   {r['snippet']}")
        
        return 0
    
    def lint(self, args) -> int:
        """Health check."""
        generate_inv = getattr(args, 'generate_investigations', False)
        fmt = getattr(args, 'format', 'full')
        result = self.wiki.lint(generate_investigations=generate_inv)

        if fmt == 'brief':
            return self._lint_brief(result)
        elif fmt == 'recommendations':
            return self._lint_recommendations(result)
        else:
            return self._lint_full(result)

    def _lint_full(self, result: dict) -> int:
        """Full health check output."""
        print(f"=== Wiki Health Check ===")
        print(f"Total pages: {result['total_pages']}")
        print(f"Issues found: {result['issue_count']}")

        if result['issues']:
            by_type = {}
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

            return 1
        else:
            print("\n✅ All healthy!")
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
    
    def status(self, args) -> int:
        """Show wiki status."""
        result = self.wiki.status()
        
        if not result.get('initialized'):
            print("❌ Wiki not initialized")
            return 1
        
        print("=== Wiki Status ===")
        print(f"📁 Root: {result['root']}")
        print(f"📄 Pages: {result['page_count']}")
        print(f"📦 Sources: {result['source_count']}")
        print(f"🔍 Indexed: {result.get('indexed_pages', 'N/A')}")
        print(f"🔗 Links: {result.get('total_links', 'N/A')}")
        
        return 0
    
    def log(self, args) -> int:
        """Record log entry."""
        result = self.wiki.append_log(args.operation, args.description)
        print(f"✅ {result}")
        return 0
    
    def build_index(self, args) -> int:
        """Build reference index."""
        no_export = getattr(args, 'no_export', False)
        output = getattr(args, 'output', None)
        export_only = getattr(args, 'export_only', False)
        output_path = Path(output) if output else None

        if export_only:
            print("=== Exporting Reference Index ===")
            result = self.wiki.export_index(output_path or self.wiki.ref_index_path)
            print(f"\n=== Export Complete ===")
            print(f"Pages: {result['total_pages']}")
            print(f"Links: {result['total_links']}")
            print(f"Output: {output_path or self.wiki.ref_index_path}")
            return 0

        print("=== Building Reference Index ===")
        print(f"Scanning: {self.wiki.wiki_dir}")
        print()

        result = self.wiki.build_index(auto_export=not no_export, output_path=output_path)

        print()
        print(f"=== Index Built ===")
        print(f"Total pages: {result['total_pages']}")
        print(f"Total links: {result['total_links']}")
        print(f"⏱️  Elapsed: {result.get('elapsed_seconds', 'N/A')}s")
        print(f"📈 Speed: {result.get('files_per_second', 'N/A')} files/sec")

        return 0
    
    def references(self, args) -> int:
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
                
                print(f"📥 Inbound ({len(inbound)})")
                if inbound:
                    for i, link in enumerate(inbound, 1):
                        section = link.get('section', '')
                        print(f"  {i}. {link['source']} → {section}")
                        if detail and link.get('context'):
                            print(f"     Context: \"{link['context']}\"")
                    print()
                else:
                    print("  (none)\n")
            
            if not outbound_only or inbound_only:
                print(f"📤 Outbound ({len(outbound)})")
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
            print(f"📥 Inbound ({len(inbound)})")
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
    
    def _show_reference_stats(self, args) -> int:
        """Show reference statistics."""
        top = getattr(args, 'top', 10)
        
        inbound_counts = {}
        outbound_counts = {}
        orphans = []
        
        for page in self.wiki.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self.wiki._index_page_name, self.wiki._log_page_name):
                continue
            
            inbound = self.wiki.index.get_inbound_links(page_name)
            outbound = self.wiki.index.get_outbound_links(page_name)
            
            inbound_counts[page_name] = len(inbound)
            outbound_counts[page_name] = len(outbound)
            
            if not inbound and not self.wiki._should_exclude_orphan(page_name, page):
                orphans.append(page_name)
        
        top_inbound = sorted(inbound_counts.items(), key=lambda x: -x[1])[:top]
        top_outbound = sorted(outbound_counts.items(), key=lambda x: -x[1])[:top]
        
        print("=== Reference Statistics ===\n")
        
        print(f"📈 Most Linked-To Pages (Top {top}):")
        for page, count in top_inbound:
            print(f"  {page}: {count} inbound")
        print()
        
        print(f"📊 Most Active Pages (Top {top}):")
        for page, count in top_outbound:
            print(f"  {page}: {count} outbound")
        print()
        
        if orphans:
            print(f"🟠 Orphan Pages ({len(orphans)}):")
            for page in orphans[:top]:
                print(f"  {page}")
        else:
            print("✅ No orphan pages")
        
        return 0
    
    def _show_broken_references(self, args) -> int:
        """Show broken references."""
        broken = []
        
        for page in self.wiki.wiki_dir.glob("*.md"):
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target in (self.wiki._index_page_name, self.wiki._log_page_name):
                    continue
                target_path = self.wiki.wiki_dir / f"{target}.md"
                if not target_path.exists():
                    broken.append({
                        "source": page.stem,
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
    
    def batch(self, args) -> int:
        """Batch ingest sources."""
        source_path = Path(args.source)
        limit = getattr(args, 'limit', 0)
        
        if source_path.is_dir():
            sources = list(source_path.glob("*"))
            sources = [s for s in sources if s.is_file()]
        else:
            # Glob pattern
            sources = [Path(p) for p in glob_module.glob(str(source_path))]
        
        if limit:
            sources = sources[:limit]
        
        if not sources:
            print("❌ No sources found")
            return 1
        
        print(f"=== Batch Ingest ===")
        print(f"Found {len(sources)} source(s)\n")
        
        success = 0
        failed = 0
        
        for i, source in enumerate(sources, 1):
            print(f"[{i}/{len(sources)}] Processing: {source.name}")
            result = self.wiki.ingest_source(str(source))
            
            if "error" in result:
                print(f"  ❌ Error: {result['error']}")
                failed += 1
            else:
                print(f"  ✅ {result['title']}")
                smart = getattr(args, 'smart', False)
                if smart:
                    try:
                        ops_result = self.wiki._llm_process_source(result)
                        ops = ops_result.get("operations", [])
                        if ops:
                            exec_result = self.wiki.execute_operations(ops)
                            print(f"    → {exec_result['operations_executed']} operations executed")
                    except (ConnectionError, TimeoutError, RuntimeError, OSError) as e:
                        print(f"    ⚠️ LLM processing skipped: {e}")
                success += 1
        
        print(f"\n=== Batch Complete ===")
        print(f"Success: {success}, Failed: {failed}")
        
        return 0 if failed == 0 else 1
    
    def sink_status(self, args) -> int:
        """Show query sink buffer status."""
        result = self.wiki.sink_status()
        
        print("=== Query Sink Status ===\n")
        
        if isinstance(result, dict) and result.get('sinks'):
            for sink_name, info in result['sinks'].items():
                count = info.get('count', 0)
                status = info.get('status', 'unknown')
                icon = "⏳" if status == "pending" else "✅"
                print(f"  {icon} {sink_name}: {count} entries ({status})")
        else:
            print("  No sink buffers found.")
        
        return 0
    
    def synthesize(self, args) -> int:
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
            page_name=args.page_name,
            merge_or_replace=args.merge,
        )
        
        if "error" in result:
            print(f"❌ {result['error']}")
            return 1
        
        print(f"✅ Synthesized: {result.get('page_name', args.query)}")
        return 0
    
    def watch(self, args) -> int:
        """Watch raw/ directory for new files."""
        from ..core.watcher import FileSystemWatcher, install_git_hook, uninstall_git_hook
        
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
        smart = getattr(args, 'smart', False)
        debounce = getattr(args, 'debounce', 2.0)
        dry_run = getattr(args, 'dry_run', False)
        
        print(f"=== File Watcher ===")
        print(f"Watching: {watch_dir}")
        print(f"Auto-ingest: {'Yes' if auto_ingest else 'No (notify only)'}")
        print(f"Smart mode: {'Yes' if smart else 'No'}")
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
            smart=smart,
            debounce=debounce,
        )
        
        def on_event(event_type, path):
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
    
    def graph_query(self, args) -> int:
        """Query the knowledge graph."""
        from ..core.relation_engine import RelationEngine
        
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
    
    def export_graph(self, args) -> int:
        """Export knowledge graph visualization."""
        from ..core.graph_export import build_graph, export_html, export_graphml, export_svg
        
        output = args.output
        fmt = args.format
        if not output:
            ext_map = {"html": ".html", "svg": ".svg", "graphml": ".graphml"}
            output = f"graph{ext_map.get(fmt, '.html')}"
        
        output_path = Path(output)
        
        print(f"=== Exporting Graph ===")
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
        except (ImportError, RuntimeError, OSError, ValueError) as e:
            print(f"❌ Export failed: {e}")
            return 1
        
        return 0
    
    def community_detect(self, args) -> int:
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
            print(f"=== Community Detection (Dry Run) ===")
            print(f"Algorithm: {args.algorithm}")
            print(f"Resolution: {args.resolution}")
            print(f"Nodes: {result['total_nodes']}")
            print(f"Edges: {result['total_edges']}")
            print(f"Communities: {result['num_communities']}")
            print(f"Modularity: {result['modularity']}")
            return 0
        
        print(f"=== Community Detection ===\n")
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
    
    def report(self, args) -> int:
        """Generate unexpected connections report."""
        from ..core.graph_export import generate_report, detect_communities, build_graph
        
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
    
    def serve(self, args) -> int:
        """Start MCP server. Used by both 'mcp' and 'serve' subcommands."""
        from ..mcp.server import serve_mcp
        
        # Get MCP configuration from wiki config
        mcp_config = self.config.get("mcp", {})
        
        # Override with CLI args if provided
        transport = getattr(args, 'transport', None)
        host = getattr(args, 'host', None)
        port = getattr(args, 'port', None)
        
        print(f"Starting MCP server...")
        print(f"  Transport: {transport or mcp_config.get('transport', 'stdio')}")
        if host:
            print(f"  Host: {host}")
        if port:
            print(f"  Port: {port}")
        print()
        
        try:
            serve_mcp(self.wiki, transport=transport, host=host, port=port, config=mcp_config)
        except KeyboardInterrupt:
            print("\nServer stopped")
        
        return 0
    
    def _get_content(self, args) -> Optional[str]:
        """Get content from file, argument, or stdin."""
        if getattr(args, 'file', None):
            try:
                with open(args.file, 'r') as f:
                    return f.read()
            except OSError as e:
                print(f"❌ Error reading file: {e}")
                return None
        elif getattr(args, 'content', None):
            return args.content
        else:
            return sys.stdin.read()


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='llmwikify',
        description='llmwikify CLI - LLM Wiki Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  llmwikify ingest document.pdf                  Show extraction summary
  llmwikify ingest document.pdf --smart          LLM-assisted page creation
  llmwikify ingest document.pdf --dry-run        Preview without changes
  llmwikify search "gold mining"                 Full-text search
  llmwikify references "Company"                 Show references
  llmwikify build-index                          Build reference index
  llmwikify build-index --export-only            Export index without rebuilding
  llmwikify lint --format=brief                  Quick health suggestions
  llmwikify lint --format=recommendations        Missing and orphan pages
  llmwikify init                                 Initialize wiki
  llmwikify init --overwrite                     Reinitialize wiki
  llmwikify mcp                                  Start MCP server for Agent interaction
  llmwikify serve                                Start self-hosted Agent (reserved)
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
    p.add_argument('--smart', '-s', action='store_true',
                   help='Use LLM to analyze content and create wiki pages (requires llm.enabled=true)')
    p.add_argument('--dry-run', '-n', action='store_true',
                   help='Show extraction summary without creating pages')
    
    # write_page
    p = subparsers.add_parser('write_page', help='Write page')
    p.add_argument('name', help='Page name')
    p.add_argument('--file', '-f', help='Read content from file')
    p.add_argument('--content', '-c', help='Content as string')
    
    # read_page
    p = subparsers.add_parser('read_page', help='Read page')
    p.add_argument('name', help='Page name')
    
    # search
    p = subparsers.add_parser('search', help='Full-text search')
    p.add_argument('query', help='Search query')
    p.add_argument('--limit', '-l', type=int, default=10)
    
    # lint
    p = subparsers.add_parser('lint', help='Health check')
    p.add_argument('--format', '-f', choices=['full', 'brief', 'recommendations'],
                   default='full', help='Output format (default: full)')
    p.add_argument('--generate-investigations', '-g', action='store_true',
                   help='Use LLM to generate investigation suggestions')
    
    # status
    subparsers.add_parser('status', help='Show status')
    
    # log
    p = subparsers.add_parser('log', help='Record log')
    p.add_argument('operation', help='Operation name')
    p.add_argument('description', help='Description')
    
    # build-index
    p = subparsers.add_parser('build-index', help='Build or export reference index')
    p.add_argument('--no-export', action='store_true', help='Skip JSON export')
    p.add_argument('--output', '-o', help='JSON output path')
    p.add_argument('--export-only', action='store_true', help='Export existing index without rebuilding')
    
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
    p.add_argument('--smart', '-s', action='store_true',
                   help='Use LLM to analyze content and create wiki pages')
    
    # sink-status
    subparsers.add_parser('sink-status', help='Show query sink buffer status')
    
    # synthesize
    p = subparsers.add_parser('synthesize', help='Save query answer as wiki page')
    p.add_argument('query', help='Original question')
    p.add_argument('--answer', '-a', help='Answer content (or read from stdin)')
    p.add_argument('--page-name', '-n', help='Custom page name')
    p.add_argument('--sources', '-s', nargs='*', help='Source pages to link')
    p.add_argument('--merge', choices=['sink', 'merge', 'replace'], default='sink',
                   help='Strategy when similar query exists')
    
    # watch
    p = subparsers.add_parser('watch', help='Watch raw/ directory for new files')
    p.add_argument('dir', nargs='?', default=None, help='Directory to watch (default: raw/)')
    p.add_argument('--auto-ingest', action='store_true',
                   help='Automatically ingest new files')
    p.add_argument('--smart', '-s', action='store_true',
                   help='Use LLM to process files (requires --auto-ingest)')
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
    p.add_argument('--confidence', choices=['EXTRACTED', 'INFERRED', 'AMBIGUOUS'],
                   default=None, help='Minimum confidence filter')
    
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
    
    # mcp - Start MCP server for Agent interaction
    p = subparsers.add_parser('mcp', help='Start MCP server for Agent interaction (stdio by default)')
    p.add_argument('--transport', '-t', choices=['stdio', 'http', 'sse'], help='Transport protocol')
    p.add_argument('--host', help='Host address')
    p.add_argument('--port', '-p', type=int, help='Port number')
    
    # serve - reserved for future self-hosted Agent mode
    p = subparsers.add_parser('serve', help='[Reserved] Start a self-hosted Agent with LLM API for knowledge base management')
    p.add_argument('--transport', '-t', choices=['stdio', 'http', 'sse'], help='Transport protocol')
    p.add_argument('--host', help='Host address')
    p.add_argument('--port', '-p', type=int, help='Port number')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    wiki_root = Path(os.environ.get('WIKI_ROOT', Path.cwd()))
    
    # Load configuration
    config = {}
    config_file = wiki_root / '.wiki-config.yaml'
    if config_file.exists():
        try:
            import yaml
            config = yaml.safe_load(config_file.read_text()) or {}
        except Exception:
            # YAML parse error or import error, use defaults
            pass
    
    cli = WikiCLI(wiki_root, config=config)
    
    commands = {
        'init': cli.init,
        'ingest': cli.ingest,
        'write_page': cli.write_page,
        'read_page': cli.read_page,
        'search': cli.search,
        'lint': cli.lint,
        'status': cli.status,
        'log': cli.log,
        'build-index': cli.build_index,
        'references': cli.references,
        'batch': cli.batch,
        'sink-status': cli.sink_status,
        'synthesize': cli.synthesize,
        'watch': cli.watch,
        'graph-query': cli.graph_query,
        'export-graph': cli.export_graph,
        'community-detect': cli.community_detect,
        'report': cli.report,
        'mcp': cli.serve,
        'serve': cli.serve,
    }
    
    try:
        return commands[args.command](args)
    finally:
        cli.wiki.close()
