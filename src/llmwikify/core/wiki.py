"""Wiki core business logic."""

import json
import re
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from .index import WikiIndex
from .query_sink import QuerySink
from ..extractors import extract
from ..config import load_config, get_directory, get_db_path


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
        self.sink_dir = self.wiki_dir / '.sink'

        # Internal files (hardcoded — not user-configurable)
        self.index_file = self.wiki_dir / 'index.md'
        self.log_file = self.wiki_dir / 'log.md'
        self.wiki_md_file = self.root / 'wiki.md'
        self.db_path = get_db_path(self.root, self.config)

        # Special page names (from filenames, used for exclusion logic)
        self._index_page_name = 'index'
        self._log_page_name = 'log'
        
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
        self._query_sink: Optional[QuerySink] = None

        # Prompt custom directory (optional, from config)
        prompts_config = self.config.get("prompts", {})
        custom_dir = prompts_config.get("custom_dir")
        self._prompt_custom_dir: Optional[Path] = None
        if custom_dir:
            self._prompt_custom_dir = (self.root / custom_dir).resolve()
    
    def _get_prompt_registry(self) -> "PromptRegistry":
        """Create a PromptRegistry instance with current provider and custom dir."""
        from .prompt_registry import PromptRegistry
        provider = self.config.get("llm", {}).get("provider", "openai")
        return PromptRegistry(provider=provider, custom_dir=self._prompt_custom_dir)
    
    def _get_index_summary(self) -> str:
        """Return a condensed wiki index (max 500 chars)."""
        if not self.index_file.exists():
            return "(no index)"
        content = self.index_file.read_text()
        if len(content) <= 500:
            return content
        return content[:497] + "..."
    
    def _get_recent_log(self, limit: int = 3) -> str:
        """Return recent log entries."""
        if not self.log_file.exists():
            return "(no log)"
        lines = self.log_file.read_text().strip().split("\n")
        return "\n".join(lines[-limit:])
    
    def _get_page_count(self) -> int:
        """Return number of wiki pages."""
        if not self.wiki_dir.exists():
            return 0
        return len([p for p in self.wiki_dir.glob("*.md") 
                    if p.stem not in (self._index_page_name, self._log_page_name)])
    
    def _get_existing_page_names(self) -> List[str]:
        """Return list of existing wiki page names."""
        if not self.wiki_dir.exists():
            return []
        return [p.stem for p in self.wiki_dir.glob("*.md")
                if p.stem not in (self._index_page_name, self._log_page_name)]
    
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

    @property
    def query_sink(self) -> QuerySink:
        """Lazy-load QuerySink."""
        if self._query_sink is None:
            self._query_sink = QuerySink(self.root, self.wiki_dir)
        return self._query_sink

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
            created.append("wiki/.sink/")
        else:
            skipped.append("wiki/.sink/")
        
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
        config_example = self.root / '.wiki-config.yaml.example'
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
        registry = self._get_prompt_registry()
        return registry.render_document("wiki_schema", version=self._get_version())
    
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
            "instructions": self._get_prompt_registry().render_text("ingest_instructions"),
        }
    
    def _llm_process_source(self, source_data: dict) -> dict:
        """Process source with LLM using chained mode: analyze_source → generate_wiki_ops."""
        from ..llm_client import LLMClient

        client = LLMClient.from_config(self.config)
        registry = self._get_prompt_registry()

        max_content_chars = registry.get_params("analyze_source").get("max_content_chars", 8000)
        content = source_data["content"][:max_content_chars]
        content_truncated = len(source_data["content"]) > max_content_chars

        analysis_messages = registry.get_messages(
            "analyze_source",
            title=source_data["title"],
            source_type=source_data["source_type"],
            content=content,
            current_index=source_data.get("current_index", ""),
            max_content_chars=max_content_chars,
            content_truncated=content_truncated,
        )
        analysis_params = registry.get_api_params("analyze_source")

        analysis = self._call_llm_with_retry("analyze_source", analysis_messages, analysis_params)

        errors = registry.validate_output("analyze_source", analysis)
        if errors:
            raise ValueError(f"Analysis validation failed: {'; '.join(errors)}")

        template = registry._load_template("generate_wiki_ops")
        dynamic_context = {}
        if template.context_injection:
            dynamic_context = registry.inject_context(template.context_injection, wiki=self)

        ops_messages = registry.get_messages(
            "generate_wiki_ops",
            **dynamic_context,
            analysis_json=json.dumps(analysis, indent=2),
            current_index=source_data.get("current_index", ""),
        )
        ops_params = registry.get_api_params("generate_wiki_ops")

        operations = self._call_llm_with_retry("generate_wiki_ops", ops_messages, ops_params)

        errors = registry.validate_output("generate_wiki_ops", operations)
        if errors:
            raise ValueError(f"Operations validation failed: {'; '.join(errors)}")

        if not isinstance(operations, list):
            raise ValueError(f"Expected list of operations, got {type(operations).__name__}")

        return {
            "status": "success",
            "operations": operations,
            "analysis": analysis,
            "source_title": source_data["title"],
            "mode": "chained",
        }
    
    def _call_llm_with_retry(
        self,
        prompt_name: str,
        messages: List[Dict[str, str]],
        params: dict,
    ) -> Any:
        """Call LLM with retry on validation failure."""
        from ..llm_client import LLMClient
        
        client = LLMClient.from_config(self.config)
        registry = self._get_prompt_registry()
        retry_config = registry.get_retry_config(prompt_name)
        max_attempts = retry_config.get("max_attempts", 1)
        
        last_errors: List[str] = []
        for attempt in range(1, max_attempts + 1):
            try:
                result = client.chat_json(messages, **params)
                
                errors = registry.validate_output(prompt_name, result)
                if not errors:
                    return result
                
                last_errors = errors
                if attempt < max_attempts:
                    error_text = "\n".join(f"- {e}" for e in errors)
                    retry_prompt = (
                        f"Your previous response had errors:\n{error_text}\n\n"
                        f"Please fix and return a corrected response."
                    )
                    messages = [
                        messages[0],
                        {"role": "user", "content": retry_prompt},
                    ]
            
            except (ConnectionError, ValueError) as e:
                last_errors = [str(e)]
                if attempt >= max_attempts:
                    raise
        
        raise ValueError(
            f"LLM failed after {max_attempts} attempts for '{prompt_name}': "
            f"{'; '.join(last_errors)}"
        )
    
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
    
    def write_relations(self, relations: list, source_file: Optional[str] = None) -> dict:
        """Write extracted relations to the database.
        
        Args:
            relations: List of {source, target, relation, confidence, context} dicts.
            source_file: Original source file name.
        
        Returns:
            Dict with count of relations added.
        """
        if not relations:
            return {"status": "skipped", "count": 0}
        
        from .relation_engine import RelationEngine
        
        engine = RelationEngine(self.index)
        
        # Enrich with source_file if not present
        for r in relations:
            if "source_file" not in r and source_file:
                r["source_file"] = source_file
        
        count = engine.add_relations(relations)
        
        return {
            "status": "completed",
            "count": count,
            "source_file": source_file,
        }
    
    def get_relation_engine(self) -> "RelationEngine":
        """Get the relation engine instance."""
        from .relation_engine import RelationEngine
        return RelationEngine(self.index)
    
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
        # Backward compat: translate old 'sink/' path to new '.sink/' location
        if page_name.startswith('sink/'):
            page_name = page_name.replace('sink/', '.sink/', 1)
        
        if page_name.startswith('.sink/') or page_name.startswith('wiki/.sink/'):
            # Extract filename from path (handle both '.sink/X.sink.md' and 'wiki/.sink/X.sink.md')
            sink_name = page_name.rsplit('/', 1)[-1]
            sink_file = self.sink_dir / sink_name
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

        sink_info = self.query_sink.get_info_for_page(page_name)
        result['has_sink'] = sink_info['has_sink']
        result['sink_entries'] = sink_info['sink_entries']

        return result
    
    def search(self, query: str, limit: int = 10) -> list:
        """Full-text search with sink status attached."""
        results = self.index.search(query, limit)

        for result in results:
            sink_info = self.query_sink.get_info_for_page(result['page_name'])
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
            if page_name.startswith("Query:"):
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
    
    def _detect_potential_contradictions(self) -> List[dict]:
        """Scan wiki pages for potential contradictions.
        
        Returns observational hints (max 3) for LLM to evaluate.
        Detection strategies:
        - value_conflict: Same entity has different values (e.g., revenue: $10M vs $15M)
        - year_conflict: Same event has different years
        - negation_pattern: One page asserts X, another asserts not X
        """
        contradictions = []
        seen_pairs = set()
        
        if not self.wiki_dir.exists():
            return contradictions
        
        # Collect all pages content
        pages_content = {}
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            pages_content[page_name] = page.read_text()
        
        # Strategy 1: Extract key-value pairs and find conflicts
        entity_facts: Dict[str, Dict[str, List[tuple]]] = {}
        for page_name, content in pages_content.items():
            # Match simple key: value patterns (one per line)
            for line in content.split('\n'):
                line = line.strip().lstrip('- ').strip()
                if ':' in line and not line.startswith('#') and not line.startswith('http'):
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        if len(key) >= 2 and len(key) <= 30 and len(value) >= 2 and len(value) <= 50:
                            if key not in entity_facts:
                                entity_facts[key] = {}
                            if page_name not in entity_facts[key]:
                                entity_facts[key][page_name] = []
                            entity_facts[key][page_name].append(value)
        
        # Find conflicting values across pages
        for attr, page_values in entity_facts.items():
            if len(page_values) < 2:
                continue
            all_values = []
            for page_name, values in page_values.items():
                for v in values:
                    all_values.append((page_name, v))
            
            # Check if values differ significantly
            unique_values = set(v.lower() for _, v in all_values)
            if len(unique_values) >= 2:
                pair_key = tuple(sorted([p for p, _ in all_values]))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    values_str = ", ".join(f"{p}={v}" for p, v in all_values[:3])
                    contradictions.append({
                        "type": "value_conflict",
                        "attribute": attr,
                        "pages": [{"page": p, "value": v} for p, v in all_values[:4]],
                        "observation": f"Pages reference different values for '{attr}': {values_str}",
                    })
            
            if len(contradictions) >= 3:
                break
        
        # Strategy 2: Year conflicts (e.g., "launched in 2020" vs "launched in 2022")
        year_claims: Dict[str, List[dict]] = {}
        year_pattern = re.compile(
            r'([^\n]{3,30}?)\s+(?:launched|founded|started|established|created|born|died|closed|shutdown|ended)\s+(?:in\s+)?(20\d{2}|19\d{2})',
            re.IGNORECASE
        )
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                for match in year_pattern.finditer(line):
                    entity = match.group(1).strip()
                    year = match.group(2)
                    if entity and len(entity) <= 30:
                        if entity not in year_claims:
                            year_claims[entity] = []
                        year_claims[entity].append({"page": page_name, "year": year})
        
        for entity, claims in year_claims.items():
            years = set(c["year"] for c in claims)
            if len(years) >= 2:
                claims_str = ", ".join(f"{c['page']}={c['year']}" for c in claims[:3])
                contradictions.append({
                    "type": "year_conflict",
                    "entity": entity,
                    "claims": claims,
                    "observation": f"'{entity}' has conflicting year claims: {claims_str}",
                })
            
            if len(contradictions) >= 3:
                break
        
        # Strategy 3: Negation patterns (X is Y vs X is not Y)
        negation_claims: Dict[str, List[dict]] = {}
        for page_name, content in pages_content.items():
            for line in content.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Find assertions with and without negation
                assertion_pattern = re.compile(
                    r'([\w\s]{3,25}?)\s+(?:is|are|was|were)\s+(?:not\s+|no\s+longer\s+)?([\w\s]{3,30}?)(?:\.|,|;|$)',
                    re.IGNORECASE
                )
                for match in assertion_pattern.finditer(line):
                    subject = match.group(1).strip()
                    predicate = match.group(2).strip()
                    full_match = match.group(0).lower()
                    is_negated = bool(re.search(r'\b(?:is|are|was|were)\s+(?:not|no longer)', full_match))
                    
                    key = subject.lower()
                    if key not in negation_claims:
                        negation_claims[key] = []
                    negation_claims[key].append({
                        "page": page_name,
                        "predicate": predicate,
                        "negated": is_negated,
                    })
        
        for subject, claims in negation_claims.items():
            has_positive = any(not c["negated"] for c in claims)
            has_negative = any(c["negated"] for c in claims)
            if has_positive and has_negative:
                contradictions.append({
                    "type": "negation_pattern",
                    "subject": subject,
                    "claims": claims,
                    "observation": (
                        f"'{subject}' has both affirmative and negative claims across pages"
                    ),
                })
            
            if len(contradictions) >= 3:
                break
        
        return contradictions[:3]
    
    def _detect_data_gaps(self) -> List[dict]:
        """Detect potential data gaps in wiki pages.
        
        Returns observational hints (max 3) for LLM to evaluate.
        Detection strategies:
        - unsourced_claim: Page has assertions but no ## Sources section
        - vague_temporal: Page uses vague time references (recently, soon, etc.)
        - incomplete_entity: Page mentions entity but lacks key attributes
        """
        gaps = []
        
        if not self.wiki_dir.exists():
            return gaps
        
        for page in self.wiki_dir.glob("*.md"):
            page_name = page.stem
            if page_name in (self._index_page_name, self._log_page_name):
                continue
            if page_name.startswith("Query:"):
                continue
            
            content = page.read_text()
            
            # Strategy 1: Unsourced claims - page has assertions but no sources section
            has_sources_section = bool(re.search(r'^#{1,3}\s+Sources', content, re.MULTILINE | re.IGNORECASE))
            has_inline_citations = bool(re.search(r'\[Source[^\]]*\]\(', content))
            
            # Check for assertion-like content (non-empty, non-header lines)
            lines = content.split('\n')
            assertion_lines = [
                line.strip() for line in lines
                if line.strip()
                and not line.startswith('#')
                and not line.startswith('---')
                and not line.startswith('[')
                and len(line.strip()) > 20
            ]
            
            if len(assertion_lines) >= 3 and not has_sources_section and not has_inline_citations:
                gaps.append({
                    "type": "unsourced_claims",
                    "page": page_name,
                    "assertion_count": len(assertion_lines),
                    "observation": (
                        f"'{page_name}' contains {len(assertion_lines)} assertion(s) "
                        f"without cited sources"
                    ),
                })
            
            if len(gaps) >= 3:
                break
            
            # Strategy 2: Vague temporal references
            vague_time_words = re.findall(
                r'\b(recently|soon|upcoming|former|previous|last year|next year|in the past|currently|nowadays|these days)\b',
                content, re.IGNORECASE
            )
            if vague_time_words:
                gaps.append({
                    "type": "vague_temporal",
                    "page": page_name,
                    "vague_references": list(set(w.lower() for w in vague_time_words))[:5],
                    "observation": (
                        f"'{page_name}' uses vague temporal references: "
                        f"{', '.join(set(w.lower() for w in vague_time_words[:3]))}"
                    ),
                })
            
            if len(gaps) >= 3:
                break
            
            # Strategy 3: Incomplete entity - mentions entities without details
            # Look for entity names mentioned but no follow-up details
            entity_mentions = re.findall(r'\[\[([^\]|#]+)\]\]', content)
            for mentioned in entity_mentions:
                mentioned_clean = mentioned.strip()
                if not mentioned_clean:
                    continue
                # Check if there's a dedicated page for this entity
                mentioned_path = self.wiki_dir / f"{mentioned_clean}.md"
                if not mentioned_path.exists():
                    # Entity mentioned but no page exists - could be a gap
                    pass  # This is already covered by missing_cross_ref
        
        return gaps[:3]
    
    def _llm_generate_investigations(
        self,
        contradictions: List[dict],
        data_gaps: List[dict],
    ) -> dict:
        """Use LLM to generate investigation suggestions.
        
        Returns dict with suggested_questions and suggested_sources.
        Only called when lint(generate_investigations=True).
        """
        try:
            from ..llm_client import LLMClient
            
            client = LLMClient.from_config(self.config)
        except (ImportError, ValueError, OSError):
            return {
                "suggested_questions": [],
                "suggested_sources": [],
                "warning": "LLM client not available",
            }
        
        registry = self._get_prompt_registry()
        
        total_pages = len(list(self.wiki_dir.glob("*.md"))) if self.wiki_dir.exists() else 0
        
        variables = {
            "contradictions_json": json.dumps(contradictions, indent=2),
            "data_gaps_json": json.dumps(data_gaps, indent=2),
            "total_pages": total_pages,
        }
        
        messages = registry.get_messages("investigate_lint", **variables)
        params = registry.get_params("investigate_lint")
        
        try:
            result = client.chat_json(messages, **params)
            if isinstance(result, dict):
                return {
                    "suggested_questions": result.get("suggested_questions", []),
                    "suggested_sources": result.get("suggested_sources", []),
                }
        except (ConnectionError, TimeoutError, ValueError, OSError):
            pass
        
        return {
            "suggested_questions": [],
            "suggested_sources": [],
            "warning": "LLM investigation generation failed",
        }
    
    def lint(self, generate_investigations: bool = False) -> dict:
        """Health check the wiki.
        
        Args:
            generate_investigations: If True, use LLM to suggest investigations.
        """
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
        
        sink_status = self.query_sink.status()
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
        
        # Generate investigations (v0.16.0)
        contradictions = self._detect_potential_contradictions()
        data_gaps = self._detect_data_gaps()
        
        investigations = {
            "contradictions": contradictions,
            "data_gaps": data_gaps,
        }
        
        if generate_investigations:
            llm_suggestions = self._llm_generate_investigations(contradictions, data_gaps)
            investigations.update(llm_suggestions)
        
        return {
            "total_pages": len(list(self.wiki_dir.glob("*.md"))),
            "issue_count": len(issues),
            "issues": issues,
            "hints": {
                "critical": critical_hints,
                "informational": informational_hints,
            },
            "investigations": investigations,
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

            sink_info = self.query_sink.get_info_for_page(page_name)
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
        except OSError:
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
    
    def _llm_generate_synthesize_answer(
        self,
        query: str,
        source_pages: Optional[List[str]] = None,
        raw_sources: Optional[List[str]] = None,
    ) -> dict:
        """Use LLM to generate a structured answer for a query.
        
        This method reads the provided source pages and raw sources,
        injects wiki context, and calls the LLM to produce a well-structured
        answer suitable for wiki synthesis.
        
        Args:
            query: The question to answer.
            source_pages: Wiki page names to use as context.
            raw_sources: Raw source file paths to use as context.
        
        Returns:
            Dict with 'answer' (str), 'suggested_page_name' (optional str),
            and 'source_citations' (list of page names referenced).
        """
        try:
            from ..llm_client import LLMClient
            client = LLMClient.from_config(self.config)
        except (ImportError, ValueError, OSError):
            return {
                "answer": "",
                "suggested_page_name": "",
                "source_citations": [],
                "warning": "LLM client not available",
            }
        
        registry = self._get_prompt_registry()
        
        # Read source page contents
        source_page_data = []
        for page_name in (source_pages or []):
            page_path = self.wiki_dir / f"{page_name}.md"
            if page_path.exists():
                source_page_data.append({
                    "name": page_name,
                    "content": page_path.read_text(),
                })
        
        # Read raw source contents
        raw_source_data = []
        for raw_path in (raw_sources or []):
            full_path = self.root / raw_path
            if full_path.exists():
                raw_source_data.append({
                    "name": raw_path,
                    "content": full_path.read_text(),
                })
        
        # Inject dynamic context from wiki state
        template = registry._load_template("wiki_synthesize")
        dynamic_context = {}
        if template.context_injection:
            dynamic_context = registry.inject_context(template.context_injection, wiki=self)
        
        # Build variables for prompt rendering
        variables = {
            **dynamic_context,
            "query": query,
            "source_pages": source_page_data,
            "raw_sources": raw_source_data,
        }
        
        messages = registry.get_messages("wiki_synthesize", **variables)
        params = registry.get_api_params("wiki_synthesize")
        
        try:
            result = client.chat_json(messages, **params)
            
            errors = registry.validate_output("wiki_synthesize", result)
            if errors:
                return {
                    "answer": "",
                    "suggested_page_name": "",
                    "source_citations": [],
                    "warning": f"LLM output validation failed: {'; '.join(errors)}",
                }
            
            return {
                "answer": result.get("answer", ""),
                "suggested_page_name": result.get("suggested_page_name", ""),
                "source_citations": result.get("source_citations", []),
            }
        except (ConnectionError, TimeoutError, ValueError, OSError) as e:
            return {
                "answer": "",
                "suggested_page_name": "",
                "source_citations": [],
                "warning": f"LLM synthesis generation failed: {e}",
            }
    
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
            sink_path = self.query_sink.append_to_sink(
                similar_name, query, answer, source_pages, raw_sources
            )
            self._update_index_file()
            
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
                    f"Read pending entries: wiki_read_page('wiki/.sink/{similar_name}.sink.md')",
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
            except OSError:
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
                except (OSError, ValueError, OverflowError):
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
    
    # -- QuerySink delegation --

    def read_sink(self, page_name: str) -> dict:
        """Read all pending entries from a query sink file."""
        return self.query_sink.read(page_name)

    def clear_sink(self, page_name: str) -> dict:
        """Clear processed entries from a query sink file."""
        result = self.query_sink.clear(page_name)
        self._update_index_file()
        return result

    def sink_status(self) -> dict:
        """Overview of all query sinks with entry counts and urgency."""
        return self.query_sink.status()

    def close(self):
        """Close database connections."""
        if self._index:
            self._index.close()
