"""CLI commands for llmwikify."""

import argparse
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
        overwrite = getattr(args, 'overwrite', False)
        result = self.wiki.init(overwrite=overwrite)
        
        if result['status'] == 'already_exists':
            print(f"⚠️  Wiki already initialized at {self.root}")
            print(f"   Existing files: {', '.join(result['existing_files'])}")
            print(f"   Use --overwrite to reinitialize.")
            return 0
        else:
            print(f"✅ {result['message']}")
            print(f"   Created: {', '.join(result['created_files'])}")
            if result['skipped_files']:
                print(f"   Skipped: {', '.join(result['skipped_files'])}")
            return 0
    
    def ingest(self, args) -> int:
        """Ingest a source file."""
        source = args.file
        result = self.wiki.ingest_source(source)
        
        if "error" in result:
            print(f"❌ Error: {result['error']}")
            return 1
        
        print(f"✅ Ingested: {source}")
        print(f"   Title: {result['title']}")
        print(f"   Type: {result['source_type']}")
        print(f"   Length: {result['content_length']} chars")
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
        result = self.wiki.lint()
        
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
        output_path = Path(output) if output else None
        
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
    
    def recommend(self, args) -> int:
        """Generate recommendations."""
        result = self.wiki.recommend()
        
        print("=== Wiki Recommendations ===\n")
        
        if result['missing_pages']:
            print(f"🔴 Missing Pages ({len(result['missing_pages'])})\n")
            for rec in result['missing_pages'][:10]:
                print(f"   • [[{rec['page']}]] (referenced {rec['reference_count']} times)")
            print()
        else:
            print("✅ No missing pages\n")
        
        if result['orphan_pages']:
            print(f"🟠 Orphan Pages ({len(result['orphan_pages'])})\n")
            for rec in result['orphan_pages'][:10]:
                print(f"   • [[{rec['page']}]]")
            print()
        else:
            print("✅ No orphan pages\n")
        
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
                success += 1
        
        print(f"\n=== Batch Complete ===")
        print(f"Success: {success}, Failed: {failed}")
        
        return 0 if failed == 0 else 1
    
    def hint(self, args) -> int:
        """Show smart suggestions."""
        result = self.wiki.hint()
        
        print("=== Wiki Suggestions ===\n")
        
        if result['hints']:
            for hint in result['hints']:
                priority_icon = {
                    'high': '🔴',
                    'medium': '🟡',
                    'low': '🟢',
                }.get(hint['priority'], '•')
                
                print(f"{priority_icon} [{hint['priority'].upper()}] {hint['message']}\n")
        else:
            print("✅ Wiki looks healthy! No suggestions.\n")
        
        print(f"Summary: {result['summary']['total_hints']} hint(s), {result['summary']['high_priority']} high priority")
        
        return 0
    
    def export_index(self, args) -> int:
        """Export reference index to JSON."""
        output = getattr(args, 'output', 'reference_index.json')
        output_path = Path(output)
        
        print(f"=== Exporting Index ===")
        print(f"Output: {output_path}")
        
        result = self.wiki.export_index(output_path)
        
        print(f"\n=== Export Complete ===")
        print(f"Pages: {result['total_pages']}")
        print(f"Links: {result['total_links']}")
        
        return 0
    
    def serve(self, args) -> int:
        """Start MCP server."""
        from ..mcp.server import MCPServer
        from ..config import get_mcp_config
        
        # Get MCP configuration
        mcp_config = get_mcp_config(self.config)
        
        # Create MCP server
        server = MCPServer(self.wiki, config=mcp_config)
        
        # Override with CLI args if provided
        transport = getattr(args, 'transport', None)
        host = getattr(args, 'host', None)
        port = getattr(args, 'port', None)
        
        print(f"Starting MCP server...")
        print(f"  Transport: {transport or mcp_config['transport']}")
        if host:
            print(f"  Host: {host}")
        if port:
            print(f"  Port: {port}")
        print()
        
        try:
            server.serve(transport=transport, host=host, port=port)
        except KeyboardInterrupt:
            print("\nServer stopped")
        
        return 0
    
    def _get_content(self, args) -> Optional[str]:
        """Get content from file, argument, or stdin."""
        if getattr(args, 'file', None):
            try:
                with open(args.file, 'r') as f:
                    return f.read()
            except Exception as e:
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
  llmwikify ingest document.pdf           Ingest a PDF file
  llmwikify search "gold mining"          Full-text search
  llmwikify references "Company"          Show references
  llmwikify build-index                   Build reference index
  llmwikify recommend                     Get smart recommendations
  llmwikify init                          Initialize wiki
  llmwikify init --overwrite              Reinitialize wiki
  llmwikify serve                         Start MCP server
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # init
    p = subparsers.add_parser('init', help='Initialize wiki')
    p.add_argument('--overwrite', action='store_true', help='Recreate index.md and log.md if they exist')
    
    # ingest
    p = subparsers.add_parser('ingest', help='Ingest PDF/URL/YouTube')
    p.add_argument('file', type=str, help='File path or URL')
    
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
    subparsers.add_parser('lint', help='Health check')
    
    # status
    subparsers.add_parser('status', help='Show status')
    
    # log
    p = subparsers.add_parser('log', help='Record log')
    p.add_argument('operation', help='Operation name')
    p.add_argument('description', help='Description')
    
    # build-index
    p = subparsers.add_parser('build-index', help='Build reference index')
    p.add_argument('--no-export', action='store_true')
    p.add_argument('--output', '-o')
    
    # recommend
    subparsers.add_parser('recommend', help='Generate recommendations')
    
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
    
    # hint
    subparsers.add_parser('hint', help='Show smart suggestions')
    
    # export-index
    p = subparsers.add_parser('export-index', help='Export reference index to JSON')
    p.add_argument('--output', '-o', default='reference_index.json', help='Output file')
    
    # serve
    p = subparsers.add_parser('serve', help='Start MCP server')
    p.add_argument('--transport', '-t', choices=['stdio', 'http', 'sse'], help='Transport protocol')
    p.add_argument('--host', help='Host address')
    p.add_argument('--port', '-p', type=int, help='Port number')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    wiki_root = Path(os.environ.get('WIKI_ROOT', '/home/ll/mining_news'))
    
    # Load configuration
    config = {}
    config_file = wiki_root / '.wiki-config.yaml'
    if config_file.exists():
        try:
            import yaml
            config = yaml.safe_load(config_file.read_text()) or {}
        except Exception:
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
        'recommend': cli.recommend,
        'references': cli.references,
        'batch': cli.batch,
        'hint': cli.hint,
        'export-index': cli.export_index,
        'serve': cli.serve,
    }
    
    try:
        return commands[args.command](args)
    finally:
        cli.wiki.close()
