"""Wiki core business logic."""

import json
import re
import os
import shutil
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
        
        # Query sink directory (pending updates for query pages)
        self.sink_dir = self.root / 'sink'
        
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
        
        if not self.sink_dir.exists():
            self.sink_dir.mkdir(parents=True, exist_ok=True)
            created.append("sink/")
        else:
            skipped.append("sink/")
        
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
- Use `[[wikilink]]` syntax for cross-references between wiki pages
- Link to entities, concepts, and related topics
- Update links when creating or modifying pages
- Section links: `[[Page Name#Section]]`
- Display text: `[[Page Name|Custom Display]]`

### Source Citations
- Cite raw sources in wiki pages using standard markdown links (NOT wikilinks)
- Raw files are NOT wiki pages — never use `[[raw/filename]]` syntax
- Two approaches — choose based on context:
  - **Page-level**: Add `## Sources` section at page end listing all sources
    ```markdown
    ## Sources
    - [Source: Article Title](raw/slugified-title.md)
    - [Source: research-paper.pdf](raw/research-paper.pdf)
    ```
  - **Inline**: Add citations after key claims `[Source](raw/filename)`
- Format: `[Source: Title](raw/filename)` — use relative paths from wiki root
- When ingesting a new source, cite it in every wiki page you create or update

### Page Structure
- Start with `# Title` (matching page name)
- Use `## Section` headers for organization
- Add `[[wikilinks]]` to related pages
- Keep pages focused on one topic

### index.md
- Auto-updated on each page write
- Lists all pages with one-line summaries
- Do NOT edit manually

### index.md vs build_index
- **index.md**: Content catalog — human-readable, LLM query entry point. Lists all pages with one-line summaries. Updated automatically on write.
- **build_index**: Technical operation — rebuilds SQLite FTS5 full-text index and exports `reference_index.json` (bidirectional link graph). Used by `wiki_search` under the hood.
- Query flow: Read `index.md` first for overview → Use `wiki_search` to drill down → Use `wiki_read_page` for full content

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
1. Search wiki using `wiki_search` to find relevant pages
2. Read relevant pages using `wiki_read_page` for full context
   - If results show `has_sink: true`, also read the sink file: `wiki_read_page("sink/{{Topic}}.sink.md")`
3. Synthesize answer with citations to wiki pages and raw sources
4. **Save the answer back to the wiki** using `wiki_synthesize`:
   - Provide the original query and your answer content
   - Include `source_pages` (wiki pages you referenced)
   - Include `raw_sources` (raw source files, e.g., `raw/article.md`)
   - The tool auto-creates a `Query: {{topic}}` page with a structured Sources section
   - The tool auto-logs to log.md (disable with `auto_log=False`)
5. If a similar query page exists:
   - Your answer will be saved to the sink (status: "sunk")
   - Read the existing page first: `wiki_read_page("Query: {{topic}}")`
   - Read pending sink entries: `wiki_read_page("sink/Query: {{topic}}.sink.md")`
   - Synthesize a comprehensive answer combining both, then use `update_existing=True`
6. Query answers compound in the knowledge base — they become persistent wiki pages just like ingested sources

### Query Sink
- When a similar query page exists, new answers go to `sink/` instead of creating duplicates
- Sink files: `sink/Query: Topic.sink.md` — one per formal query page
- Format: chronological entries with timestamp, query, answer, and sources
- Each sink file links to its formal page via frontmatter (`formal_page`)
- Formal pages link to their sink via frontmatter (`sink_path`, `sink_entries`)
- During lint: use `wiki_sink_status` to find sinks with pending entries
- Read sinks with `wiki_read_page("sink/Query: Topic.sink.md")`
- After merging, clear sinks with `wiki_write_page("sink/Query: Topic.sink.md", content)`

### Query Page Naming
- Auto-generated: `Query: {{Topic}}` (first 50 chars of query, title-cased)
- If a similar query page exists, a date suffix is added: `Query: {{Topic}} (2026-04-10)`
- Use `page_name` parameter to override the auto-generated name
- Use `update_existing=True` to revise an existing query page instead of creating a new one

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
        
        All source files are collected into raw/ for centralized management.
        - URL/YouTube: extracted text is saved to raw/
        - Local files outside raw/: copied to raw/
        - Local files already in raw/: no copy needed
        """
        result = extract(source, wiki_root=self.root)
        
        if result.source_type == "error":
            return {"error": result.metadata.get("error", "Unknown extraction error")}
        
        if not result.text:
            return {"error": "No content extracted"}
        
        # Collect source file into raw/
        saved_to_raw = False
        already_exists = False
        hint = ""
        source_name = ""
        
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        
        if result.source_type in ("url", "youtube"):
            # URL/YouTube: save extracted text to raw/
            safe_name = self._slugify(result.title) + ".md"
            saved_path = self.raw_dir / safe_name
            
            if saved_path.exists():
                already_exists = True
                source_name = safe_name
                hint = f"Source already exists in raw/{safe_name}"
            else:
                saved_path.write_text(result.text)
                saved_to_raw = True
                source_name = safe_name
                hint = f"Extracted text saved to raw/{safe_name}"
        else:
            # Local file: check if already in raw/
            original_path = Path(source).resolve()
            try:
                original_path.relative_to(self.raw_dir.resolve())
                # File is already inside raw/
                source_name = str(original_path.relative_to(self.raw_dir))
                saved_to_raw = False
                hint = f"Source is already in raw/{source_name}"
            except ValueError:
                # File is outside raw/, copy it in
                safe_name = self._slugify(result.title or original_path.stem) + original_path.suffix
                saved_path = self.raw_dir / safe_name
                
                if saved_path.exists():
                    already_exists = True
                    source_name = safe_name
                    hint = f"Source already exists in raw/{safe_name}"
                else:
                    # Cross-platform copy: read bytes and write (no permission issues)
                    saved_path.write_bytes(original_path.read_bytes())
                    saved_to_raw = True
                    source_name = safe_name
                    hint = f"Source copied to raw/{safe_name} from {original_path}"
        
        # Read current index for LLM context
        index_content = ""
        if self.index_file.exists():
            index_content = self.index_file.read_text()
        
        # Log the ingest
        log_detail = f"Source ({result.source_type}): {result.title}"
        if saved_to_raw:
            log_detail += f" → raw/{source_name}"
        self.append_log("ingest", log_detail)
        
        # Compute file metadata for LLM context
        raw_file = self.raw_dir / source_name
        file_size = 0
        word_count = 0
        has_images = False
        image_count = 0
        
        if raw_file.exists():
            file_size = raw_file.stat().st_size
            word_count = len(result.text.split()) if result.text else 0
            # Detect image references in markdown
            image_refs = re.findall(r'!\[.*?\]\((.*?)\)', result.text or '')
            image_count = len(image_refs)
            has_images = image_count > 0
        
        return {
            "source_name": source_name,
            "source_raw_path": f"raw/{source_name}",
            "source_type": result.source_type,
            "file_type": self._detect_file_type(source_name),
            "file_size": file_size,
            "word_count": word_count,
            "has_images": has_images,
            "image_count": image_count,
            "text_extracted": bool(result.text),
            "title": result.title,
            "content_preview": (result.text or "")[:200],
            "content": result.text,
            "content_length": len(result.text),
            "metadata": result.metadata,
            "saved_to_raw": saved_to_raw,
            "already_exists": already_exists,
            "hint": hint,
            "current_index": index_content,
            "message": "Source ingested. Read the file to extract key takeaways.",
            "instructions": (
                "You have received a new source document. Please:\n"
                "1. Read and understand the content\n"
                "2. See wiki.md (at the project root) for wiki conventions and workflows\n"
                "3. Create/update relevant wiki pages using wiki_write_page\n"
                "4. Update index.md with the new page listing\n"
                "5. Add [[wikilinks]] between related pages\n"
                "6. Cite the source in wiki pages using standard markdown (NOT wikilinks):\n"
                "   - Page-level: add '## Sources' section with [Source: Title](raw/filename)\n"
                "   - Inline: cite after key claims like [Source](raw/filename)\n"
                "   - Choose the approach that best fits the context\n"
                "7. Log what you did using wiki_log"
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
        """Read a wiki page with sink status attached."""
        if page_name.startswith('sink/'):
            sink_file = self.root / page_name
            if not sink_file.exists():
                return {"error": f"Sink file not found: {page_name}"}
            # Remove .sink.md suffix properly
            raw_name = sink_file.name  # e.g., "Query: Gold Mining.sink.md"
            if raw_name.endswith('.sink.md'):
                page_name_from_file = raw_name[:-len('.sink.md')]
            else:
                page_name_from_file = sink_file.stem.replace('.sink', '')

            return {
                "page_name": page_name_from_file,
                "content": sink_file.read_text(),
                "file": str(sink_file),
                "is_sink": True,
            }
        
        page_path = self.wiki_dir / f"{page_name}.md"
        
        if not page_path.exists():
            return {"error": f"Page not found: {page_name}"}
        
        result = {
            "page_name": page_name,
            "content": page_path.read_text(),
            "file": str(page_path),
            "is_sink": False,
        }
        
        sink_info = self._get_sink_info_for_page(page_name)
        result['has_sink'] = sink_info['has_sink']
        result['sink_entries'] = sink_info['sink_entries']
        
        return result
    
    def search(self, query: str, limit: int = 10) -> list:
        """Full-text search with sink status attached."""
        results = self.index.search(query, limit)
        
        for result in results:
            sink_info = self._get_sink_info_for_page(result['page_name'])
            result['has_sink'] = sink_info['has_sink']
            result['sink_entries'] = sink_info['sink_entries']
        
        return results
    
    def _detect_dated_claims(self) -> List[dict]:
        """Find year mentions in pages that predate latest raw source by 3+ years.
        
        Returns critical hints (max 3) for LLM to evaluate.
        """
        hints = []
        now = datetime.now(timezone.utc)
        current_year = now.year
        
        # Find latest year mentioned in raw sources
        latest_source_year = 0
        if self.raw_dir.exists():
            for src in self.raw_dir.glob("*"):
                content = src.read_text(errors="ignore")
                years = re.findall(r'\b(20\d{2})\b', content)
                if years:
                    latest_source_year = max(latest_source_year, max(int(y) for y in years))
        
        if latest_source_year == 0:
            return hints
        
        # Scan wiki pages for dated claims
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            if page_name.startswith("sink/") or page_name.startswith("Query:"):
                continue
            
            content = page.read_text()
            years_in_page = re.findall(r'\b(20\d{2})\b', content)
            
            for year_str in years_in_page:
                year = int(year_str)
                # Check if year is between 2018 and current_year-3
                if 2018 <= year <= current_year - 3:
                    if latest_source_year - year >= 3:
                        hints.append({
                            "type": "dated_claim",
                            "page": page_name,
                            "file": str(page),
                            "claim_year": year,
                            "latest_source_year": latest_source_year,
                            "gap_years": latest_source_year - year,
                            "observation": (
                                f"'{page_name}' references {year}, but the latest raw source is from {latest_source_year}. "
                                f"The gap is {latest_source_year - year} years. "
                                f"Content may be outdated."
                            ),
                        })
                        break  # One hint per page
            
            if len(hints) >= 3:
                break
        
        return hints[:3]
    
    def _detect_query_page_overlap(self) -> List[dict]:
        """Find Query: pages with >=85% keyword Jaccard overlap.
        
        Returns informational hints (max 2) for LLM to evaluate.
        """
        hints = []
        stop_words = {"what", "is", "the", "a", "an", "how", "do", "does", "why",
                       "can", "could", "would", "should", "will", "did", "are", "was",
                       "were", "be", "been", "being", "have", "has", "had", "of", "to",
                       "in", "for", "on", "with", "at", "by", "from", "and", "or", "not",
                       "but", "if", "then", "than", "so", "as", "about", "compare"}
        
        if not self.wiki_dir.exists():
            return hints
        
        query_pages = []
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if not page_name.startswith("Query:"):
                continue
            
            keywords = set(
                w.lower().strip(".,;:!?\"'()[]{}")
                for w in page_name.replace("Query:", "").split()
                if w.lower() not in stop_words and len(w) > 2
            )
            
            if keywords:
                query_pages.append({
                    "page_name": page_name,
                    "keywords": keywords,
                    "file": str(page),
                })
        
        # Compare all pairs
        seen_pairs = set()
        for i in range(len(query_pages)):
            for j in range(i + 1, len(query_pages)):
                p1 = query_pages[i]
                p2 = query_pages[j]
                
                union = len(p1["keywords"] | p2["keywords"])
                if union == 0:
                    continue
                
                overlap = len(p1["keywords"] & p2["keywords"])
                jaccard = overlap / union
                
                if jaccard >= 0.85:
                    pair_key = tuple(sorted([p1["page_name"], p2["page_name"]]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        hints.append({
                            "type": "topic_overlap",
                            "page_a": p1["page_name"],
                            "page_b": p2["page_name"],
                            "jaccard_score": round(jaccard, 3),
                            "shared_keywords": sorted(p1["keywords"] & p2["keywords"]),
                            "observation": (
                                f"'{p1['page_name']}' and '{p2['page_name']}' share {len(p1['keywords'] & p2['keywords'])} keywords "
                                f"(Jaccard: {jaccard:.0%}). They may cover overlapping topics."
                            ),
                        })
            
            if len(hints) >= 2:
                break
        
        return hints[:2]
    
    def _detect_missing_cross_refs(self) -> List[dict]:
        """Find concepts mentioned in 2+ pages but not wikilinked.
        
        Returns informational hints (max 3) for LLM to evaluate.
        """
        hints = []
        
        if not self.wiki_dir.exists():
            return hints
        
        # Collect all existing wiki page names as potential concepts
        existing_pages = set()
        for page in self.wiki_dir.glob("*.md"):
            existing_pages.add(page.stem)
        
        # Track concept mentions: concept -> list of pages that mention it without linking
        concept_mentions: Dict[str, List[str]] = {}
        
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            
            content = page.read_text()
            
            # Find existing wikilinks in this page
            wikilinks = set()
            for link in re.findall(r'\[\[(.*?)\]\]', content):
                target = link.split('|')[0].split('#')[0].strip()
                wikilinks.add(target)
            
            # Check if other page names are mentioned in text (case-insensitive)
            for candidate in existing_pages:
                if candidate == page_name:
                    continue
                if candidate in wikilinks:
                    continue  # Already linked
                
                # Check if candidate name appears in content (word boundary match)
                # Split candidate into words and check if they appear together
                pattern = r'\b' + re.escape(candidate) + r'\b'
                if re.search(pattern, content, re.IGNORECASE):
                    if candidate not in concept_mentions:
                        concept_mentions[candidate] = []
                    concept_mentions[candidate].append(page_name)
        
        # Filter to concepts mentioned in 2+ pages
        for concept, pages in sorted(concept_mentions.items(), key=lambda x: -len(x[1])):
            if len(pages) >= 2:
                hints.append({
                    "type": "missing_cross_ref",
                    "concept": concept,
                    "mentioning_pages": pages[:5],  # Max 5 pages listed
                    "mention_count": len(pages),
                    "observation": (
                        f"'{concept}' is mentioned in {len(pages)} pages ({', '.join(pages[:3])}"
                        f"{'...' if len(pages) > 3 else ''}) but not linked. "
                        f"Consider adding [[{concept}]] wikilinks."
                    ),
                })
            
            if len(hints) >= 3:
                break
        
        return hints[:3]
    
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
        
        sink_status = self.sink_status()
        sink_warnings = []
        
        if isinstance(sink_status, dict) and 'sinks' in sink_status:
            for sink in sink_status['sinks']:
                if sink.get('urgency') in ('stale', 'aging'):
                    sink_warnings.append({
                        "type": "stale_sink",
                        "page_name": sink['page_name'],
                        "entry_count": sink['entry_count'],
                        "days_old": sink.get('days_since_last_entry', 0),
                        "urgency": sink['urgency'],
                        "suggestion": f"Review and merge {sink['entry_count']} pending entries",
                    })
        
        # Generate hints (clue-based, non-mandatory)
        critical_hints = self._detect_dated_claims()
        informational_hints = []
        informational_hints.extend(self._detect_query_page_overlap())
        informational_hints.extend(self._detect_missing_cross_refs())
        
        # Enforce limits: critical max 3, informational max 5
        critical_hints = critical_hints[:3]
        informational_hints = informational_hints[:5]
        
        return {
            "total_pages": len(list(self.wiki_dir.glob("*.md"))),
            "issue_count": len(issues),
            "issues": issues,
            "hints": {
                "critical": critical_hints,
                "informational": informational_hints,
            },
            "sink_status": sink_status,
            "sink_warnings": sink_warnings,
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
    def _detect_file_type(filename: str) -> str:
        """Detect file type from extension."""
        ext = Path(filename).suffix.lower()
        type_map = {
            '.md': 'markdown',
            '.markdown': 'markdown',
            '.pdf': 'pdf',
            '.txt': 'text',
            '.html': 'html',
            '.htm': 'html',
            '.csv': 'csv',
            '.json': 'json',
            '.xml': 'xml',
            '.docx': 'docx',
            '.doc': 'doc',
        }
        return type_map.get(ext, 'unknown')
    
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
        """Update index.md with current wiki contents and sink status."""
        pages = []
        
        for page in sorted(self.wiki_dir.glob("*.md")):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            
            content = page.read_text()
            first_line = content.split('\n')[0].lstrip('# ').strip()
            
            sink_info = self._get_sink_info_for_page(page_name)
            sink_marker = ""
            if sink_info['has_sink']:
                sink_marker = f" 📥 {sink_info['sink_entries']} pending updates"
            
            pages.append(f"- [[{page_name}]] - {first_line}{sink_marker}")
        
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
    
    def synthesize_query(
        self,
        query: str,
        answer: str,
        source_pages: Optional[List[str]] = None,
        raw_sources: Optional[List[str]] = None,
        page_name: Optional[str] = None,
        auto_link: bool = True,
        auto_log: bool = True,
        merge_or_replace: str = "sink",
    ) -> dict:
        """Save a query answer as a new wiki page.
        
        Implements the Query compounding cycle: answers filed back into the wiki
        as persistent pages, just like ingested sources.
        
        Args:
            query: Original question that was asked.
            answer: LLM-generated answer content (markdown).
            source_pages: Wiki pages referenced to generate this answer.
            raw_sources: Raw source files referenced (e.g., 'raw/article.md').
            page_name: Custom page name. Auto-generated as 'Query: {topic}' if omitted.
            auto_link: Automatically add source_pages as [[wikilinks]] in Sources section.
            auto_log: Automatically append to log.md.
            merge_or_replace: Strategy when similar page exists:
                "sink" (default) — append to sink buffer for later review
                "merge" — read old content, consolidate, replace formal page
                "replace" — overwrite the formal page entirely
        
        Returns:
            Dict with status, page_name, page_path, sources info, hint about duplicates.
        """
        source_pages = source_pages or []
        raw_sources = raw_sources or []
        
        similar_page = self._find_similar_query_page(query)
        hint = ""
        
        if similar_page and merge_or_replace in ("merge", "replace"):
            similar_name = similar_page['page_name']
            page_name = similar_name
            page_path = self.wiki_dir / f"{page_name}.md"
            
            if auto_link:
                answer = self._append_sources_section(
                    answer, query, source_pages, raw_sources
                )
            
            page_path.write_text(answer)
            
            rel_path = str(page_path.relative_to(self.wiki_dir))
            self.index.upsert_page(page_name, answer, rel_path)
            self._update_index_file()
            
            status = "merged" if merge_or_replace == "merge" else "replaced"
            message = f"Merged answer into: {page_name}" if merge_or_replace == "merge" else f"Replaced existing query page: {page_name}"
            
        elif similar_page:
            similar_name = similar_page['page_name']
            sink_path = self._append_to_sink(
                similar_name, query, answer, source_pages, raw_sources
            )
            
            hint = {
                "type": "similar_page_exists",
                "page_name": similar_name,
                "preview": similar_page['preview'][:100],
                "word_count": similar_page['word_count'],
                "created": similar_page['created'],
                "score": similar_page['score'],
                "action_taken": "appended_to_sink",
                "sink_path": sink_path,
                "observation": (
                    f"A page on this topic exists: '{similar_name}' ({similar_page['word_count']} words). "
                    f"Preview: '{similar_page['preview'][:100]}'. "
                    f"Your answer has been saved to the sink buffer. "
                    f"When ready to integrate, read both and synthesize a comprehensive update."
                ),
                "options": [
                    f"Read the existing page: wiki_read_page('{similar_name}')",
                    f"Read pending entries: wiki_read_page('sink/{similar_name}.sink.md')",
                    f"Merge and replace: wiki_synthesize(..., merge_or_replace='replace')",
                    "Or let the sink accumulate for later review during lint",
                ],
            }
            
            page_name = similar_name
            page_path = self.root / sink_path
            
            status = "sunk"
            message = f"Appended to sink for: {similar_name}"
            
        else:
            # Create new page
            page_name = page_name or self._generate_query_page_name(query)
            page_path = self.wiki_dir / f"{page_name}.md"
            
            # Handle name collision with non-query pages
            counter = 1
            while page_path.exists():
                base = page_name
                page_name = f"{base} ({counter})"
                page_path = self.wiki_dir / f"{page_name}.md"
                counter += 1
            
            self._create_query_page(page_path, page_name, answer, query, source_pages, raw_sources, auto_link)
            status = "created"
            message = f"Created query page: {page_name}"
        
        # Auto-log
        logged = False
        if auto_log:
            if status == "sunk":
                log_detail = f"{query} → [sink] (pending merge into {similar_page['page_name']})"
            elif status in ("merged", "replaced"):
                log_detail = f"{query} → [[{page_name}]] ({status})"
            else:
                log_detail = f"{query} → [[{page_name}]]"
            self.append_log("query", log_detail)
            logged = True
        
        hint_str = hint if isinstance(hint, str) else json.dumps(hint, indent=2)
        
        return {
            "status": status,
            "page_name": page_name,
            "page_path": str(page_path.relative_to(self.root)),
            "source_pages": source_pages,
            "raw_sources": raw_sources,
            "logged": logged,
            "hint": hint_str,
            "message": message,
        }
    
    def _generate_query_page_name(self, query: str) -> str:
        """Generate a page name from a query string.
        
        Extracts topic (first 50 chars, slugified) and prefixes with 'Query: '.
        """
        topic = query.strip()[:50].strip()
        # Capitalize first letter of each word for readability
        topic = topic.title()
        # Remove trailing punctuation
        topic = topic.rstrip(".,;:!?")
        return f"Query: {topic}"
    
    def _find_similar_query_page(self, query: str) -> Optional[dict]:
        """Find an existing query page with similar topic.
        
        Searches for pages starting with 'Query: ' that share significant
        keywords with the given query.
        
        Returns:
            Dict with page_name, preview, key_topics, word_count, created, score.
            None if no similar page found.
        """
        if not self.wiki_dir.exists():
            return None
        
        stop_words = {"what", "is", "the", "a", "an", "how", "do", "does", "why",
                       "can", "could", "would", "should", "will", "did", "are", "was",
                       "were", "be", "been", "being", "have", "has", "had", "of", "to",
                       "in", "for", "on", "with", "at", "by", "from", "and", "or", "not",
                       "but", "if", "then", "than", "so", "as", "about", "compare",
                       "what's", "how's", "tell", "me", "explain"}
        keywords = set(
            w.lower().strip(".,;:!?\"'()[]{}")
            for w in query.split()
            if w.lower() not in stop_words and len(w) > 2
        )
        
        if not keywords:
            return None
        
        best_match = None
        best_score = 0
        
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            
            if not page_name.startswith("Query:"):
                continue
            
            page_keywords = set(
                w.lower().strip(".,;:!?\"'()[]{}")
                for w in page_name.replace("Query:", "").split()
                if w.lower() not in stop_words and len(w) > 2
            )
            
            if not page_keywords:
                continue
            
            overlap = len(keywords & page_keywords)
            union = len(keywords | page_keywords)
            score = overlap / union if union > 0 else 0
            
            try:
                content = page.read_text()
                content_keywords = set(
                    w.lower() for w in re.findall(r'\b\w{4,}\b', content)
                    if w.lower() not in stop_words
                )
                content_overlap = len(keywords & content_keywords)
                content_score = content_overlap / len(keywords) if keywords else 0
                score = max(score, content_score * 0.8)
            except Exception:
                pass
            
            if score > best_score and score >= 0.3:
                best_score = score
                
                preview = content.split('\n')[-1] if '\n' in content else content
                for line in content.split('\n'):
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#') and not stripped.startswith('---'):
                        preview = stripped[:200]
                        break
                
                key_topics = list(page_keywords)[:5]
                word_count = len(content.split())
                
                try:
                    created = datetime.fromtimestamp(
                        page.stat().st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                except Exception:
                    created = "unknown"
                
                best_match = {
                    "page_name": page_name,
                    "preview": preview,
                    "key_topics": key_topics,
                    "word_count": word_count,
                    "created": created,
                    "score": round(score, 3),
                }
        
        return best_match
    
    def _create_query_page(
        self,
        page_path: Path,
        page_name: str,
        answer: str,
        query: str,
        source_pages: List[str],
        raw_sources: List[str],
        auto_link: bool,
    ) -> None:
        """Create a new query page with sources section."""
        content = answer
        
        if auto_link and (source_pages or raw_sources):
            content = self._append_sources_section(content, query, source_pages, raw_sources)
        
        page_path.write_text(content)
        
        # Index the page
        rel_path = str(page_path.relative_to(self.wiki_dir))
        self.index.upsert_page(page_name, content, rel_path)
        self._update_index_file()
    
    def _append_sources_section(
        self,
        answer: str,
        query: str,
        source_pages: List[str],
        raw_sources: List[str],
    ) -> str:
        """Append structured Sources section to answer content."""
        sources_section = "\n\n---\n\n## Sources\n\n"
        
        # Query metadata
        sources_section += f"### Query\n"
        sources_section += f"- **Question**: {query}\n"
        sources_section += f"- **Generated**: {self._now()}\n"
        
        # Wiki pages
        if source_pages:
            sources_section += "\n### Wiki Pages Referenced\n"
            for page in source_pages:
                sources_section += f"- [[{page}]]\n"
        
        # Raw sources
        if raw_sources:
            sources_section += "\n### Raw Sources\n"
            for raw_path in raw_sources:
                # Extract filename for display
                filename = Path(raw_path).name
                sources_section += f"- [Source: {filename}]({raw_path})\n"
        
        return answer + sources_section
    
    def _get_sink_info_for_page(self, page_name: str) -> dict:
        """Get sink status for a wiki page.
        
        Returns dict with has_sink (bool) and sink_entries (int).
        """
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            return {"has_sink": False, "sink_entries": 0}
        
        try:
            content = sink_file.read_text()
            entries = len(re.findall(r'^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]', content, re.MULTILINE))
            return {"has_sink": True, "sink_entries": entries}
        except Exception:
            return {"has_sink": False, "sink_entries": 0}
    
    def _find_or_create_sink_file(self, page_name: str) -> Path:
        """Find or create a sink file for the given page name."""
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        
        if not sink_file.exists():
            content = (
                f"---\n"
                f"formal_page: \"{page_name}\"\n"
                f"formal_path: wiki/{page_name}.md\n"
                f"created: {self._now()}\n"
                f"---\n\n"
                f"# Query Sink: {page_name.replace('Query: ', '')}\n\n"
                f"> Pending entries for [[{page_name}]] — review during lint\n\n"
            )
            sink_file.write_text(content)
            
            formal_path = self.wiki_dir / f"{page_name}.md"
            if formal_path.exists():
                self._update_page_sink_meta(formal_path, sink_file)
        
        return sink_file
    
    def _update_page_sink_meta(self, page_path: Path, sink_file: Path) -> None:
        """Update a wiki page's frontmatter with sink metadata."""
        try:
            content = page_path.read_text()
            
            if content.startswith('---'):
                fm_end = content.find('---', 3)
                if fm_end > 0:
                    fm_end += 3
                    frontmatter = content[3:fm_end].strip()
                    body = content[fm_end:]
                    
                    lines = frontmatter.split('\n')
                    new_lines = []
                    has_sink_path = False
                    for line in lines:
                        if line.startswith('sink_path:'):
                            new_lines.append(f'sink_path: {str(sink_file.relative_to(self.root))}')
                            has_sink_path = True
                        elif line.startswith('sink_entries:') or line.startswith('last_merged:'):
                            continue
                        else:
                            new_lines.append(line)
                    
                    if not has_sink_path:
                        new_lines.append(f'sink_path: {str(sink_file.relative_to(self.root))}')
                    
                    new_frontmatter = '\n'.join(new_lines)
                    page_path.write_text(f'---\n{new_frontmatter}\n---{body}')
            else:
                sink_path = str(sink_file.relative_to(self.root))
                new_content = (
                    f"---\n"
                    f"sink_path: {sink_path}\n"
                    f"sink_entries: 0\n"
                    f"---\n\n"
                    f"{content}"
                )
                page_path.write_text(new_content)
        except Exception:
            pass
    
    def _generate_sink_suggestions(
        self,
        query: str,
        answer: str,
        source_pages: List[str],
        raw_sources: List[str],
        page_name: str,
    ) -> List[str]:
        """Generate optimization suggestions for a sink entry.
        
        Returns list of suggestion strings.
        """
        suggestions = []
        suggestions.extend(self._detect_content_gaps(answer, page_name))
        suggestions.extend(self._suggest_source_improvements(source_pages, raw_sources, page_name))
        suggestions.extend(self._analyze_query_patterns(query, page_name))
        suggestions.extend(self._suggest_knowledge_growth(answer, page_name))
        return suggestions
    
    def _extract_topics(self, text: str) -> set:
        """Extract key topics from text using keyword extraction."""
        stop_words = {"this", "that", "these", "those", "with", "from", "have", "been",
                       "were", "will", "also", "each", "which", "their", "there", "about",
                       "through", "during", "before", "after", "above", "below", "between",
                       "into", "through", "against", "among", "within", "without"}
        words = set(
            w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', text)
            if w.lower() not in stop_words
        )
        return words
    
    def _detect_content_gaps(self, answer: str, page_name: str) -> List[str]:
        """Compare new answer with existing content to detect gaps."""
        suggestions = []
        
        formal_path = self.wiki_dir / f"{page_name}.md"
        if not formal_path.exists():
            return suggestions
        
        formal_content = formal_path.read_text()
        formal_topics = self._extract_topics(formal_content)
        answer_topics = self._extract_topics(answer)
        
        missing = formal_topics - answer_topics
        if len(missing) >= 2:
            suggestions.append(
                f"Content Gap: Previous answer covered {', '.join(sorted(missing)[:3])}, "
                f"but this answer does not."
            )
        
        new = answer_topics - formal_topics
        if len(new) >= 2:
            suggestions.append(
                f"New Coverage: This answer adds {', '.join(sorted(new)[:3])} "
                f"not in the formal page."
            )
        
        return suggestions
    
    def _suggest_source_improvements(
        self,
        source_pages: List[str],
        raw_sources: List[str],
        page_name: str,
    ) -> List[str]:
        """Analyze source citation quality."""
        suggestions = []
        
        formal_path = self.wiki_dir / f"{page_name}.md"
        formal_sources_wiki: set = set()
        formal_sources_raw: set = set()
        
        if formal_path.exists():
            content = formal_path.read_text()
            formal_sources_wiki = set(re.findall(r'\[\[(.*?)\]\]', content))
            formal_sources_raw = set(re.findall(r'\[Source:[^\]]*\]\((raw/[^\)]+)\)', content))
        
        if not source_pages and not raw_sources:
            suggestions.append(
                "No Sources: This answer does not cite any sources. "
                "Adding references improves credibility and traceability."
            )
        
        missing_wiki = formal_sources_wiki - set(source_pages)
        if len(missing_wiki) >= 2:
            suggestions.append(
                f"Missing Sources: Previous answer cited {', '.join(sorted(missing_wiki)[:2])}."
            )
        
        new_raw = set(raw_sources) - formal_sources_raw
        if new_raw:
            suggestions.append(
                f"New Sources: References {', '.join(sorted(new_raw)[:2])} not in formal page."
            )
        
        return suggestions
    
    def _query_similarity(self, q1: str, q2: str) -> float:
        """Simple query similarity using word overlap."""
        stop = {"what", "is", "the", "a", "an", "how", "do", "does", "why", "can", "tell", "me",
                 "about", "explain", "describe", "compare"}
        words1 = set(w.lower() for w in q1.split() if w.lower() not in stop and len(w) > 2)
        words2 = set(w.lower() for w in q2.split() if w.lower() not in stop and len(w) > 2)
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)
    
    def _analyze_query_patterns(self, query: str, page_name: str) -> List[str]:
        """Analyze query patterns for this topic."""
        suggestions = []
        
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            return suggestions
        
        content = sink_file.read_text()
        entries = re.findall(r'## \[\d{4}-\d{2}-\d{2}[^]]*\] Query: (.+?)\n', content)
        
        similar_count = 0
        for old_query in entries:
            if self._query_similarity(query, old_query) > 0.7:
                similar_count += 1
        
        if similar_count >= 2:
            suggestions.append(
                f"Repeated Question: This question (or variations) has been asked "
                f"{similar_count + 1} times. Consider adding a FAQ section."
            )
        
        if len(query.split()) > 8 and len(entries) > 0:
            avg_length = sum(len(q.split()) for q in entries) / len(entries)
            if len(query.split()) > avg_length * 1.5:
                suggestions.append(
                    "Increasing Complexity: Queries are becoming more detailed. "
                    "Consider creating sub-topic pages."
                )
        
        return suggestions
    
    def _suggest_knowledge_growth(self, answer: str, page_name: str) -> List[str]:
        """Suggest knowledge growth opportunities."""
        suggestions = []
        
        formal_path = self.wiki_dir / f"{page_name}.md"
        if formal_path.exists():
            formal_content = formal_path.read_text()
            formal_words = set(
                w.lower() for w in re.findall(r'\b[A-Z][a-z]{3,}\b', formal_content)
            )
            answer_words = set(
                w.lower() for w in re.findall(r'\b[A-Z][a-z]{3,}\b', answer)
            )
            
            common = {"this", "that", "with", "from", "have", "been", "were", "will", "also", "each"}
            new_concepts = answer_words - formal_words - common
            
            if len(new_concepts) >= 3:
                suggestions.append(
                    f"New Concepts: Mentions {', '.join(sorted(new_concepts)[:3])} "
                    f"not in formal page. Consider if any deserve their own page."
                )
        
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if sink_file.exists():
            negation_words = re.findall(r'\b(not|never|no longer|however|contrary|contradicts?)\b', answer, re.IGNORECASE)
            if negation_words:
                suggestions.append(
                    "Possible Contradiction: This answer contains negation words. "
                    "Review against previous entries before merging."
                )
        
        return suggestions
    
    def _check_sink_duplicate(self, sink_file: Path, new_answer: str) -> Optional[str]:
        """Check if new answer is too similar to existing sink entries."""
        if not sink_file.exists():
            return None
        
        content = sink_file.read_text()
        entries = re.findall(
            r'## \[\d{4}-\d{2}-\d{2}[^]]*\] Query: .+?\n\n(.+?)(?:\n###|\n>|\n---\n\n## \[|$)',
            content, re.DOTALL
        )
        
        new_answer_clean = new_answer.strip()
        for entry in entries:
            entry_clean = entry.strip()
            if not entry_clean:
                continue
            similarity = self._query_similarity(new_answer_clean[:200], entry_clean[:200])
            if similarity > 0.7:
                return f"High similarity ({similarity:.0%}) with a previous sink entry. Consider using merge_or_replace='replace' to consolidate."
        
        return None
    
    def _append_to_sink(
        self,
        page_name: str,
        query: str,
        answer: str,
        source_pages: List[str],
        raw_sources: List[str],
    ) -> str:
        """Append a query answer to the appropriate sink file.
        
        Returns the path to the sink file relative to root.
        """
        sink_file = self._find_or_create_sink_file(page_name)
        
        # Generate suggestions and check for duplicates
        suggestions = self._generate_sink_suggestions(query, answer, source_pages, raw_sources, page_name)
        dup_warning = self._check_sink_duplicate(sink_file, answer)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        entry = f"---\n\n## [{timestamp}] Query: {query}\n\n{answer}\n"
        
        if dup_warning:
            entry += f"\n> ⚠️ {dup_warning}\n"
        
        if suggestions:
            entry += "\n### 💡 Suggestions for Improvement\n"
            for s in suggestions:
                entry += f"- {s}\n"
        
        if source_pages or raw_sources:
            entry += "\n### Sources\n"
            for page in source_pages:
                entry += f"- [[{page}]]\n"
            for raw_path in raw_sources:
                filename = Path(raw_path).name
                entry += f"- [Source: {filename}]({raw_path})\n"
        
        existing = sink_file.read_text()
        sink_file.write_text(existing + entry)
        
        self._update_page_sink_meta(self.wiki_dir / f"{page_name}.md", sink_file)
        
        self._update_index_file()
        
        return str(sink_file.relative_to(self.root))
    
    def read_sink(self, page_name: str) -> dict:
        """Read all pending entries from a query sink file.
        
        Args:
            page_name: The formal page name (e.g., 'Query: Gold Mining').
        
        Returns:
            Dict with status, entries list, or error.
        """
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        
        if not sink_file.exists():
            return {"status": "empty", "page_name": page_name, "entries": [], "message": "No sink file found"}
        
        content = sink_file.read_text()
        
        entries = []
        parts = re.split(r'^---\n\n## \[', content, flags=re.MULTILINE)
        
        for part in parts[1:]:
            match = re.match(r'(\d{4}-\d{2}-\d{2}[^]]*)\] Query: (.+?)\n\n(.+)', part, re.DOTALL)
            if match:
                timestamp = match.group(1).strip()
                query = match.group(2).strip()
                answer = match.group(3).strip()
                entries.append({
                    "timestamp": timestamp,
                    "query": query,
                    "answer": answer,
                })
        
        return {
            "status": "ok",
            "page_name": page_name,
            "file": str(sink_file.relative_to(self.root)),
            "entries": entries,
            "total_entries": len(entries),
        }
    
    def clear_sink(self, page_name: str) -> dict:
        """Clear processed entries from a query sink file.
        
        Args:
            page_name: The formal page name.
        
        Returns:
            Dict with status.
        """
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        
        if not sink_file.exists():
            return {"status": "empty", "message": "No sink file found"}
        
        sink_file.write_text(
            f"---\n"
            f"formal_page: \"{page_name}\"\n"
            f"formal_path: wiki/{page_name}.md\n"
            f"---\n\n"
            f"# Query Sink: {page_name.replace('Query: ', '')}\n\n"
            f"> All entries processed. Sink cleared on {self._now()}\n"
        )
        
        formal_path = self.wiki_dir / f"{page_name}.md"
        if formal_path.exists():
            try:
                content = formal_path.read_text()
                if content.startswith('---'):
                    fm_end = content.find('---', 3)
                    if fm_end > 0:
                        fm_end += 3
                        frontmatter = content[3:fm_end].strip()
                        body = content[fm_end:]
                        
                        lines = frontmatter.split('\n')
                        new_lines = []
                        has_last_merged = False
                        for line in lines:
                            if line.startswith('sink_entries:'):
                                new_lines.append('sink_entries: 0')
                            elif line.startswith('last_merged:'):
                                new_lines.append(f'last_merged: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}')
                                has_last_merged = True
                            else:
                                new_lines.append(line)
                        
                        if not has_last_merged:
                            new_lines.append(f'last_merged: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}')
                        
                        formal_path.write_text(f'---\n{chr(10).join(new_lines)}\n---{body}')
            except Exception:
                pass
        
        self._update_index_file()
        
        return {"status": "cleared", "page_name": page_name}
    
    def sink_status(self) -> dict:
        """Overview of all query sinks with entry counts and urgency.
        
        Returns:
            Dict with total_entries, total_sinks, urgent_count, sinks list.
            Each sink entry includes: page_name, file, entry_count, oldest_entry,
            newest_entry, days_since_last_entry, urgency (ok/attention/aging/stale).
        """
        if not self.sink_dir.exists():
            return {"total_entries": 0, "total_sinks": 0, "urgent_count": 0, "sinks": [], "message": "No sink directory"}
        
        sinks = []
        total_entries = 0
        now = datetime.now(timezone.utc)
        
        for sink_file in sorted(self.sink_dir.glob("*.sink.md")):
            page_name = sink_file.stem.replace('.sink', '')
            content = sink_file.read_text()
            entries = len(re.findall(r'^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]', content, re.MULTILINE))
            
            dates = re.findall(r'^## \[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\]', content, re.MULTILINE)
            oldest = min(dates) if dates else None
            newest = max(dates) if dates else None
            
            days_old = 0
            urgency = "ok"
            if newest:
                try:
                    newest_dt = datetime.strptime(newest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    days_old = (now - newest_dt).days
                except Exception:
                    pass
                
                if days_old > 30:
                    urgency = "stale"
                elif days_old > 14:
                    urgency = "aging"
                elif days_old > 7:
                    urgency = "attention"
            
            sinks.append({
                "page_name": page_name,
                "file": str(sink_file.relative_to(self.root)),
                "entry_count": entries,
                "oldest_entry": oldest,
                "newest_entry": newest,
                "days_since_last_entry": days_old,
                "urgency": urgency,
            })
            total_entries += entries
        
        sinks.sort(key=lambda x: x['entry_count'], reverse=True)
        urgent_count = sum(1 for s in sinks if s['urgency'] != 'ok')
        
        return {
            "total_entries": total_entries,
            "total_sinks": len(sinks),
            "urgent_count": urgent_count,
            "sinks": sinks,
        }
    
    def close(self):
        """Close database connections."""
        if self._index:
            self._index.close()
