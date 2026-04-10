"""Wiki core business logic."""

import json
import re
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from .index import WikiIndex
from ..extractors import extract
from ..config import load_config, get_directory, get_file_path, get_db_path


class Wiki:
    """Main Wiki manager."""
    
    def __init__(self, root: Path, config: Optional[dict] = None):
        self.root = root.resolve()
        
        # Load configuration (external file or built-in defaults)
        self.config = config or load_config(self.root)
        
        # Set up directory structure from config
        self.raw_dir = get_directory(self.root, 'raw', self.config)
        self.wiki_dir = get_directory(self.root, 'wiki', self.config)
        
        # Set up file paths from config
        # index and log files are in the wiki directory
        index_name = get_file_path(self.root, 'index', self.config).name
        log_name = get_file_path(self.root, 'log', self.config).name
        self.index_file = self.wiki_dir / index_name
        self.log_file = self.wiki_dir / log_name
        self.wiki_md_file = self.root / 'wiki.md'
        self.db_path = get_db_path(self.root, self.config)
        
        # Special page names (from config, used for exclusion logic)
        self._index_page_name = self.index_file.stem
        self._log_page_name = self.log_file.stem
        
        # Reference index path
        ref_index_name = self.config.get('reference_index', {}).get('name', 'reference_index.json')
        self._ref_index_path: Optional[Path] = None
        self._ref_index_name = ref_index_name
        
        # Orphan detection configuration
        orphan_config = self.config.get('orphan_detection', {})
        self._default_exclude_patterns = orphan_config.get('default_exclude_patterns', [])
        self._user_exclude_patterns = orphan_config.get('exclude_patterns', [])
        self._exclude_frontmatter_keys = orphan_config.get('exclude_frontmatter', [])
        self._archive_dirs = orphan_config.get('archive_directories', [])
        
        # Performance settings
        perf_config = self.config.get('performance', {})
        self._batch_size = perf_config.get('batch_size', 100)
        
        self._index: Optional[WikiIndex] = None
    
    @property
    def ref_index_path(self) -> Path:
        """Path to reference index JSON."""
        if self._ref_index_path is None:
            self._ref_index_path = self.wiki_dir / self._ref_index_name
        return self._ref_index_path
    
    @property
    def index(self) -> WikiIndex:
        """Lazy-load WikiIndex."""
        if self._index is None:
            self._index = WikiIndex(self.db_path)
        return self._index
    
    def is_initialized(self) -> bool:
        """Check if wiki is initialized."""
        return (self.raw_dir.exists() and 
                self.wiki_dir.exists() and 
                self.db_path.exists())
    
    def init(self, overwrite: bool = False) -> dict:
        """Initialize wiki directory structure.
        
        Args:
            overwrite: If True, recreate index.md and log.md even if they exist.
                       Always skips wiki.md and config_example if they exist.
        
        Returns:
            Structured result with status, created_files, and message.
        """
        already_exists = self.is_initialized()
        
        if already_exists and not overwrite:
            existing = []
            if self.raw_dir.exists():
                existing.append("raw/")
            if self.wiki_dir.exists():
                existing.append("wiki/")
            if self.index_file.exists():
                existing.append("index.md")
            if self.log_file.exists():
                existing.append("log.md")
            return {
                "status": "already_exists",
                "created_files": [],
                "existing_files": existing,
                "skipped_files": [],
                "message": "Wiki already initialized. Use overwrite=true to reinitialize.",
            }
        
        created = []
        skipped = []
        
        # Create directories
        if not self.raw_dir.exists():
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            created.append("raw/")
        else:
            skipped.append("raw/")
        
        if not self.wiki_dir.exists():
            self.wiki_dir.mkdir(parents=True, exist_ok=True)
            created.append("wiki/")
        else:
            skipped.append("wiki/")
        
        # Initialize database (always safe to call)
        self.index.initialize()
        
        # Create index.md
        if not self.index_file.exists() or overwrite:
            self.index_file.write_text(self._generate_index_content())
            created.append("index.md")
        else:
            skipped.append("index.md")
        
        # Create log.md
        if not self.log_file.exists() or overwrite:
            self.log_file.write_text(self._generate_log_content())
            created.append("log.md")
        else:
            skipped.append("log.md")
        
        # Create config example (always skip if exists)
        config_example = self.root / self.config.get('files', {}).get('config_example', '.wiki-config.yaml.example')
        if not config_example.exists():
            config_example.write_text(self._generate_config_example())
            created.append(".wiki-config.yaml.example")
        else:
            skipped.append(".wiki-config.yaml.example")
        
        # Create wiki.md (always skip if exists)
        if not self.wiki_md_file.exists():
            self.wiki_md_file.write_text(self._generate_wiki_md())
            created.append("wiki.md")
        else:
            skipped.append("wiki.md")
        
        return {
            "status": "created",
            "created_files": created,
            "existing_files": [],
            "skipped_files": skipped,
            "message": f"Wiki initialized at {self.root}",
        }
    
    def _generate_index_content(self) -> str:
        """Generate initial index.md content."""
        return (
            "# Wiki Index\n\n"
            f"Generated by llmwikify v{self._get_version()}\n\n"
            "---\n\n"
            "## Pages\n\n"
            "*(No pages yet)*\n"
        )
    
    def _generate_log_content(self) -> str:
        """Generate initial log.md content."""
        return (
            "# Wiki Log\n\n"
            f"Initialized: {self._now()}\n\n"
            "---\n"
        )
    
    def _generate_config_example(self) -> str:
        """Generate .wiki-config.yaml.example content."""
        return (
            "# Wiki Configuration\n"
            "# See docs/CONFIG_GUIDE.md for details\n\n"
            "# Override default directories\n"
            "# directories:\n"
            "#   raw: raw\n"
            "#   wiki: wiki\n\n"
            "# Override database name\n"
            "# database:\n"
            "#   name: \".llmwikify.db\"\n\n"
            "# Orphan detection exclusions\n"
            "# orphan_detection:\n"
            "#   exclude_patterns:\n"
            "#     - '^\\d{4}-\\d{2}-\\d{2}$'  # Date pages\n"
            "#     - '^meeting-.*'             # Meeting notes\n"
            "#   exclude_frontmatter:\n"
            "#     - redirect_to\n"
            "#   archive_directories:\n"
            "#     - 'archive'\n"
            "#     - 'logs'\n\n"
            "# MCP server settings\n"
            "# mcp:\n"
            "#   host: 127.0.0.1\n"
            "#   port: 8765\n"
            "#   transport: stdio\n"
        )
    
    def _generate_wiki_md(self) -> str:
        """Generate wiki.md - LLM agent instructions for wiki maintenance."""
        return f"""# Wiki Schema

> This document tells the LLM how to maintain this wiki.
> Generated by llmwikify v{self._get_version()}

## Directory Structure

```
root/
├── raw/           # Immutable source documents (PDFs, URLs, exports)
├── wiki/          # LLM-maintained markdown pages
├── index.md       # Content catalog (auto-updated)
├── log.md         # Chronological activity log
├── wiki.md        # This file - conventions and workflows
└── .wiki-config.yaml  # User configuration
```

## Conventions

### Page Naming
- Use descriptive, meaningful names: `Topic Name`, `Entity Name`
- Avoid special characters; use hyphens for spaces if needed
- The LLM owns the wiki/ directory; humans own the raw/ directory

### Linking
- Use `[[wikilink]]` syntax for cross-references
- Link to entities, concepts, and related topics
- Update links when creating or modifying pages
- Section links: `[[Page Name#Section]]`
- Display text: `[[Page Name|Custom Display]]`

### Page Structure
- Start with `# Title` (matching page name)
- Use `## Section` headers for organization
- Add `[[wikilinks]]` to related pages
- Keep pages focused on one topic

### index.md
- Auto-updated on each page write
- Lists all pages with one-line summaries
- Do NOT edit manually

### log.md
- Append-only chronological record
- Format: `## [timestamp] operation | details`
- Append entry after each significant operation

## Workflows

### Ingest a Source
1. Read the source file from raw/
2. Extract key information and entities
3. Create new wiki pages or update existing ones
4. Add `[[wikilinks]]` to connect related pages
5. Update index.md (automatic on write)
6. Append to log.md: `## [timestamp] ingest | Source Name`

### Answer a Query
1. Search wiki using search functionality
2. Read relevant pages for context
3. Synthesize answer with citations to wiki pages
4. If answer provides new insights, create a new wiki page
5. Append to log.md: `## [timestamp] query | Question topic`

### Maintain Wiki Health
1. Run lint periodically to check for:
   - Broken links (links to non-existent pages)
   - Orphan pages (no inbound links)
2. Fix broken links by creating missing pages or removing links
3. Connect orphan pages by adding references from other pages
4. Run recommend to find missing pages that are frequently referenced
5. Append to log.md: `## [timestamp] lint | Results`

## Orphan Detection

Pages with no inbound links are flagged as orphans. Some pages may be excluded:
- Configure exclusions in `.wiki-config.yaml`
- Common exclusions: date pages, meeting notes, archive directories
- index.md and log.md are always excluded

## Best Practices

1. **Cross-reference heavily** - The value is in the connections
2. **Update existing pages** - Don't create duplicates
3. **Note contradictions** - Flag when new info conflicts with old
4. **Keep summaries current** - Update when facts change
5. **Use consistent terminology** - Same entity = same page name
6. **File answers back** - Good query responses become wiki pages

## Configuration

User configuration is in `.wiki-config.yaml`. Key settings:
- `orphan_detection.exclude_patterns` - Regex for pages to exclude
- `orphan_detection.exclude_frontmatter` - Frontmatter keys for exclusion
- `orphan_detection.archive_directories` - Directory names to exclude

Do NOT modify `.wiki-config.yaml` unless explicitly asked by the user.
"""
    
    def ingest_source(self, source: str) -> dict:
        """Ingest a source file and return extracted data for LLM processing.
        
        Does NOT automatically write wiki pages. Returns extracted content
        along with current wiki index so the LLM can decide which pages
        to create/update and how to cross-reference.
        
        For URL/YouTube sources, saves extracted text to raw/ for persistence.
        """
        result = extract(source, wiki_root=self.root)
        
        if result.source_type == "error":
            return {"error": result.metadata.get("error", "Unknown extraction error")}
        
        if not result.text:
            return {"error": "No content extracted"}
        
        # URL/YouTube: save to raw/ for persistence
        saved_to_raw = False
        already_exists = False
        source_name = Path(source).name if Path(source).exists() else source
        
        if result.source_type in ("url", "youtube"):
            safe_name = self._slugify(result.title) + ".md"
            saved_path = self.raw_dir / safe_name
            
            if saved_path.exists():
                already_exists = True
                source_name = safe_name
            else:
                self.raw_dir.mkdir(parents=True, exist_ok=True)
                saved_path.write_text(result.text)
                saved_to_raw = True
                source_name = safe_name
        
        # Read current index for LLM context
        index_content = ""
        if self.index_file.exists():
            index_content = self.index_file.read_text()
        
        # Log the ingest
        self.append_log("ingest", f"Source ({result.source_type}): {result.title}")
        
        return {
            "source_name": source_name,
            "source_type": result.source_type,
            "title": result.title,
            "content": result.text,
            "content_length": len(result.text),
            "metadata": result.metadata,
            "saved_to_raw": saved_to_raw,
            "already_exists": already_exists,
            "current_index": index_content,
            "instructions": (
                "You have received a new source document. Please:\n"
                "1. Read and understand the content\n"
                "2. See wiki.md (at the project root) for wiki conventions and workflows\n"
                "3. Create/update relevant wiki pages using wiki_write_page\n"
                "4. Update index.md with the new page listing\n"
                "5. Add [[wikilinks]] between related pages\n"
                "6. Log what you did using wiki_log"
            ),
        }
    
    def _llm_process_source(self, source_data: dict) -> dict:
        """Use LLM to analyze source content and generate wiki operations.
        
        Args:
            source_data: Dict from ingest_source() with content, title, etc.
        
        Returns:
            Dict with 'operations' list and 'status'.
        """
        from ..llm_client import LLMClient
        
        client = LLMClient.from_config(self.config)
        
        system_prompt = (
            "You are a wiki maintenance agent. You analyze source documents "
            "and create structured wiki pages.\n\n"
            "Rules:\n"
            "- Create focused pages (one topic per page)\n"
            "- Use [[wikilink]] syntax for cross-references\n"
            "- Keep pages concise and well-structured\n"
            "- Update existing pages when content overlaps\n"
            "- Add meaningful summaries and connections\n"
        )
        
        user_prompt = (
            f"Ingest this source:\n\n"
            f"Title: {source_data['title']}\n"
            f"Type: {source_data['source_type']}\n"
            f"Content:\n---\n{source_data['content'][:8000]}\n---\n\n"
            f"Current wiki index:\n---\n{source_data.get('current_index', '')}\n---\n\n"
            f"Return a JSON array of operations to perform. "
            f"Each operation is either 'write_page' or 'log':\n"
            f'[{{"action": "write_page", "page_name": "Page Name", "content": "# Page Name\\n\\n..."}}, '
            f'{{"action": "log", "operation": "ingest", "details": "..."}}]'
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        operations = client.chat_json(messages)
        
        if not isinstance(operations, list):
            raise ValueError(f"Expected list of operations, got {type(operations).__name__}")
        
        return {
            "status": "success",
            "operations": operations,
            "source_title": source_data["title"],
        }
    
    def execute_operations(self, operations: list) -> dict:
        """Execute a list of wiki operations from LLM processing.
        
        Args:
            operations: List of {action, ...} dicts from _llm_process_source().
        
        Returns:
            Dict with results of each operation.
        """
        results = []
        for op in operations:
            action = op.get("action", "")
            if action == "write_page":
                page_name = op.get("page_name", "")
                content = op.get("content", "")
                if page_name and content:
                    self.write_page(page_name, content)
                    results.append({"action": "write_page", "page": page_name, "status": "done"})
                else:
                    results.append({"action": "write_page", "status": "skipped", "reason": "missing page_name or content"})
            elif action == "log":
                operation = op.get("operation", "")
                details = op.get("details", "")
                if operation and details:
                    self.append_log(operation, details)
                    results.append({"action": "log", "operation": operation, "status": "done"})
                else:
                    results.append({"action": "log", "status": "skipped", "reason": "missing operation or details"})
            else:
                results.append({"action": action, "status": "unknown"})
        
        return {
            "status": "completed",
            "operations_executed": len(results),
            "results": results,
        }
    
    def write_page(self, page_name: str, content: str) -> str:
        """Write a wiki page."""
        page_path = self.wiki_dir / f"{page_name}.md"
        
        if page_path.exists():
            page_path.write_text(content)
            action = "Updated"
        else:
            page_path.write_text(content)
            action = "Created"
        
        # Update index
        rel_path = str(page_path.relative_to(self.wiki_dir))
        self.index.upsert_page(page_name, content, rel_path)
        
        # Auto-update index.md
        self._update_index_file()
        
        return f"{action} page: {page_name}"
    
    def read_page(self, page_name: str) -> dict:
        """Read a wiki page."""
        page_path = self.wiki_dir / f"{page_name}.md"
        
        if not page_path.exists():
            return {"error": f"Page not found: {page_name}"}
        
        return {
            "page_name": page_name,
            "content": page_path.read_text(),
            "file": str(page_path),
        }
    
    def search(self, query: str, limit: int = 10) -> list:
        """Full-text search."""
        return self.index.search(query, limit)
    
    def lint(self) -> dict:
        """Health check the wiki."""
        issues = []
        
        # Check for broken links
        for page in self.wiki_dir.glob("*.md"):
            content = page.read_text()
            # Simple link checking logic
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                target_path = self.wiki_dir / f"{target}.md"
                if not target_path.exists():
                    issues.append({
                        "type": "broken_link",
                        "page": page.stem,
                        "link": target,
                        "file": str(page),
                    })
        
        # Check for orphan pages
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            
            if self._should_exclude_orphan(page_name, page):
                continue
            
            inbound = self.index.get_inbound_links(page_name)
            if not inbound:
                issues.append({
                    "type": "orphan_page",
                    "page": page_name,
                    "file": str(page),
                })
        
        return {
            "total_pages": len(list(self.wiki_dir.glob("*.md"))),
            "issue_count": len(issues),
            "issues": issues,
        }
    
    def recommend(self) -> dict:
        """Generate smart recommendations."""
        missing_pages = []
        orphan_pages = []
        
        # Find missing pages (referenced but don't exist)
        link_counts = {}
        for page in self.wiki_dir.glob("*.md"):
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target not in (self._index_page_name, self._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1
        
        for target, count in link_counts.items():
            if count >= 2:  # Threshold for missing pages
                target_path = self.wiki_dir / f"{target}.md"
                if not target_path.exists():
                    missing_pages.append({
                        "page": target,
                        "reference_count": count,
                    })
        
        # Find orphan pages
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            
            if self._should_exclude_orphan(page_name, page):
                continue
            
            inbound = self.index.get_inbound_links(page_name)
            if not inbound:
                orphan_pages.append({"page": page_name})
        
        return {
            "missing_pages": missing_pages,
            "orphan_pages": orphan_pages,
            "summary": {
                "total_missing_pages": len(missing_pages),
                "total_orphans": len(orphan_pages),
            },
        }
    
    def status(self) -> dict:
        """Get wiki status."""
        return {
            "initialized": self.is_initialized(),
            "root": str(self.root),
            "page_count": len(list(self.wiki_dir.glob("*.md"))),
            "source_count": len(list(self.raw_dir.glob("*"))),
            "indexed_pages": self.index.get_page_count() if self.is_initialized() else "N/A",
            "total_links": self.index.get_link_count() if self.is_initialized() else "N/A",
        }
    
    def append_log(self, operation: str, details: str) -> str:
        """Append entry to wiki log."""
        entry = f"## [{self._now()}] {operation} | {details}\n"
        with open(self.log_file, 'a') as f:
            f.write(entry)
        return "Logged"
    
    def build_index(self, auto_export: bool = True, output_path: Optional[Path] = None) -> dict:
        """Build reference index."""
        result = self.index.build_index_from_files(self.wiki_dir, batch_size=self._batch_size)
        
        if auto_export:
            export_path = output_path or self.ref_index_path
            self.index.export_json(export_path)
            result["json_export"] = str(export_path)
        
        return result
    
    def export_index(self, output_path: Path) -> dict:
        """Export reference index to JSON."""
        return self.index.export_json(output_path)
    
    def get_inbound_links(self, page_name: str, include_context: bool = False) -> list:
        """Get pages that link to this page.
        
        Args:
            page_name: Target page name
            include_context: If True, read source files for context around links
        """
        links = self.index.get_inbound_links(page_name)
        
        if include_context:
            for link in links:
                link['context'] = self._get_link_context(
                    link['source'], link.get('section', '')
                )
        
        return links
    
    def get_outbound_links(self, page_name: str, include_context: bool = False) -> list:
        """Get pages that this page links to.
        
        Args:
            page_name: Source page name
            include_context: If True, read source files for context around links
        """
        links = self.index.get_outbound_links(page_name)
        
        if include_context:
            for link in links:
                link['context'] = self._get_link_context(
                    page_name, link.get('section', ''), link.get('target', '')
                )
        
        return links
    
    def _should_exclude_orphan(self, page_name: str, page_path: Path) -> bool:
        """Check if a page should be excluded from orphan detection."""
        page_name_lower = page_name.lower()
        
        # Check default patterns
        for pattern in self._default_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True
        
        # Check user-configured patterns
        for pattern in self._user_exclude_patterns:
            if re.match(pattern, page_name_lower):
                return True
        
        # Check frontmatter
        if page_path.exists():
            content = page_path.read_text()
            for key in self._exclude_frontmatter_keys:
                if f"{key}:" in content:
                    return True
        
        # Check if in archive directory
        try:
            rel_path = page_path.relative_to(self.wiki_dir)
            for part in rel_path.parts:
                if part.lower() in self._archive_dirs:
                    return True
        except ValueError:
            pass
        
        return False
    
    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to URL-friendly slug."""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        return text
    
    @staticmethod
    def _now() -> str:
        """Get current ISO timestamp."""
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    @staticmethod
    def _get_version() -> str:
        """Get llmwikify version."""
        try:
            from .. import __version__
            return __version__
        except ImportError:
            return "0.11.0"
    
    def _update_index_file(self) -> None:
        """Update index.md with current wiki contents."""
        pages = []
        
        for page in sorted(self.wiki_dir.glob("*.md")):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            
            content = page.read_text()
            first_line = content.split('\n')[0].lstrip('# ').strip()
            
            pages.append(f"- [[{page_name}]] - {first_line}")
        
        index_content = (
            f"# Wiki Index\n\n"
            f"Last updated: {self._now()}\n\n"
            f"Total pages: {len(pages)}\n\n"
            f"---\n\n"
            "## Pages\n\n"
        )
        
        if pages:
            index_content += '\n'.join(pages) + '\n'
        else:
            index_content += "*(No pages yet)*\n"
        
        self.index_file.write_text(index_content)
    
    def _get_link_context(self, source_page: str, section: str, target_page: str = "", context_chars: int = 80) -> str:
        """Extract context around a wikilink in source file.
        
        Args:
            source_page: Source page name
            section: Section header (e.g., '#Overview')
            target_page: Target page name (for outbound links)
            context_chars: Characters to show before/after link
        
        Returns:
            Context string or empty if not found
        """
        source_path = self.wiki_dir / f"{source_page}.md"
        if not source_path.exists():
            return ""
        
        try:
            content = source_path.read_text()
        except Exception:
            return ""
        
        # If section specified, find that section
        if section:
            section_name = section.lstrip('#')
            pattern = rf'^#+\s*{re.escape(section_name)}'
            match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
            if match:
                start = match.end()
                next_section = re.search(r'^#+\s+', content[start:], re.MULTILINE)
                if next_section:
                    content = content[start:start+next_section.start()]
                else:
                    content = content[start:]
        
        # Find the wikilink
        search_target = target_page if target_page else source_page
        link_pattern = r'\[\[' + re.escape(search_target) + r'(?:[^\]]*)?\]\]'
        match = re.search(link_pattern, content)
        
        if match:
            start = max(0, match.start() - context_chars)
            end = min(len(content), match.end() + context_chars)
            context = content[start:end].strip()
            # Replace newlines with spaces for display
            context = ' '.join(context.split())
            if start > 0:
                context = "..." + context
            if end < len(content):
                context = context + "..."
            return context
        
        return ""
    
    def hint(self) -> dict:
        """Generate smart suggestions for wiki improvement."""
        hints = []
        
        # Check for orphan pages
        orphan_count = 0
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            if self._should_exclude_orphan(page_name, page):
                continue
            inbound = self.index.get_inbound_links(page_name)
            if not inbound:
                orphan_count += 1
        
        if orphan_count > 0:
            hints.append({
                "type": "orphan",
                "priority": "medium",
                "message": f"You have {orphan_count} orphan page(s). Consider adding cross-references to connect them.",
            })
        
        # Check for missing pages
        link_counts = {}
        for page in self.wiki_dir.glob("*.md"):
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                if target not in (self._index_page_name, self._log_page_name):
                    link_counts[target] = link_counts.get(target, 0) + 1
        
        missing = []
        for target, count in link_counts.items():
            if count >= 2:
                target_path = self.wiki_dir / f"{target}.md"
                if not target_path.exists():
                    missing.append(target)
        
        if missing:
            hints.append({
                "type": "missing",
                "priority": "high",
                "message": f"Pages referenced but don't exist: {', '.join(missing[:5])}",
            })
        
        # Check wiki size
        page_count = len(list(self.wiki_dir.glob("*.md"))) - 2  # Exclude index and log
        if page_count < 5:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is small. Consider ingesting more sources to build knowledge.",
            })
        elif page_count < 20:
            hints.append({
                "type": "growth",
                "priority": "low",
                "message": "Wiki is growing well. Consider running lint to check health.",
            })
        
        # Check for broken links
        broken_count = 0
        for page in self.wiki_dir.glob("*.md"):
            content = page.read_text()
            links = re.findall(r'\[\[(.*?)\]\]', content)
            for link in links:
                target = link.split('|')[0].split('#')[0].strip()
                target_path = self.wiki_dir / f"{target}.md"
                if not target_path.exists():
                    broken_count += 1
        
        if broken_count > 0:
            hints.append({
                "type": "broken_links",
                "priority": "high",
                "message": f"Found {broken_count} broken link(s). Consider fixing or removing them.",
            })
        
        return {
            "hints": hints,
            "summary": {
                "total_hints": len(hints),
                "high_priority": sum(1 for h in hints if h['priority'] == 'high'),
            }
        }
    
    def read_schema(self) -> dict:
        """Read wiki.md (schema/conventions file).
        
        Returns:
            Dict with 'content', 'file', and a 'hint' reminding the LLM
            to save a copy before making changes.
        """
        if not self.wiki_md_file.exists():
            return {"error": "wiki.md not found. Run init() first."}
        
        return {
            "content": self.wiki_md_file.read_text(),
            "file": str(self.wiki_md_file),
            "hint": "Tip: Save a copy of the current content before making changes to wiki.md",
        }
    
    def update_schema(self, content: str) -> dict:
        """Update wiki.md with new conventions/workflows.
        
        Validates format but does not block writing. Returns warnings
        for issues and suggestions for post-update actions.
        
        Args:
            content: New wiki.md content.
        
        Returns:
            Dict with 'status', 'file', optional 'warnings' and 'suggestions'.
        """
        if not self.wiki_md_file.exists():
            return {"error": "wiki.md not found. Run init() first."}
        
        # Format validation (warnings only, does not block)
        warnings = []
        if not content.strip().startswith("#"):
            warnings.append("Missing title header (should start with #)")
        if len(content.strip()) < 50:
            warnings.append("Content seems too short for a schema file")
        
        self.wiki_md_file.write_text(content)
        
        result = {
            "status": "updated",
            "file": str(self.wiki_md_file),
            "suggestions": [
                "Review existing wiki pages to ensure compliance with new conventions",
                "Update pages that may conflict with new workflows or linking rules",
            ],
        }
        
        if warnings:
            result["warnings"] = warnings
        
        return result
    
    def close(self):
        """Close database connections."""
        if self._index:
            self._index.close()
