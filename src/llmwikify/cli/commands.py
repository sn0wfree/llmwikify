"""CLI commands for llmwikify."""

import argparse
import sys
import os
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
        agent = getattr(args, 'agent', 'claude')
        result = self.wiki.init(agent=agent)
        print(result)
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
  llmwikify init --agent claude           Initialize wiki
  llmwikify serve                         Start MCP server
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # init
    p = subparsers.add_parser('init', help='Initialize wiki')
    p.add_argument('--agent', '-a', default='claude', choices=['claude', 'codex', 'cursor', 'generic'])
    
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
    }
    
    try:
        return commands[args.command](args)
    finally:
        cli.wiki.close()
