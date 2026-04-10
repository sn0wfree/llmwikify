#!/usr/bin/env python3
"""
llmwikify.py v0.10.0 - Zero-dependency LLM Wiki CLI

Single-file implementation of llm-wiki-kit functionality with:
- SQLite FTS5 full-text search
- Bidirectional reference tracking
- JSON export for Obsidian/LLM compatibility
- MCP server support

Commands:
  init, ingest, write_page, read_page, search, lint, status, log,
  references, build-index, export-index, batch, hint, serve

Usage:
  ./llmwikify.py ingest document.pdf
  ./llmwikify.py search "gold mining"
  ./llmwikify.py references "Agnico Eagle"
  ./llmwikify.py build-index
  ./llmwikify.py export-index -o custom.json
  ./llmwikify.py serve

Environment variables:
  WIKI_ROOT    Wiki root directory (default: /home/ll/mining_news)
"""

# ============================================================================
# 1. Imports & Constants
# ============================================================================

import argparse
import sys
import os
import re
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

# Directory layout constants
RAW_DIR = "raw"
WIKI_DIR = "wiki"
INDEX_FILE = "wiki/index.md"
LOG_FILE = "wiki/log.md"
DB_FILE = ".llm-wiki-kit.db"
REF_INDEX_FILE = "wiki/reference_index.json"

# ============================================================================
# 2. Data Classes
# ============================================================================

@dataclass
class ExtractedContent:
    """Result of extracting content from a source."""
    text: str
    source_type: str
    title: str = ""
    metadata: dict = field(default_factory=dict)
    
    @property
    def content_length(self) -> int:
        return len(self.text)


@dataclass
class Link:
    """Represents a wiki link."""
    target: str
    section: str = ""
    display: str = ""
    file: str = ""


@dataclass
class Issue:
    """Represents a wiki health issue."""
    issue_type: str
    page: str
    message: str
    link: str = ""


@dataclass
class PageMeta:
    """Page metadata."""
    page_name: str
    file_path: str
    content_length: int
    word_count: int = 0
    link_count: int = 0
    updated_at: str = ""

# ============================================================================
# 3. Extractors
# ============================================================================

_YOUTUBE_PATTERNS = (
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)",
)


def detect_source_type(source: str) -> str:
    """Detect whether a source is a URL, YouTube link, or file (by extension)."""
    if any(re.search(p, source) for p in _YOUTUBE_PATTERNS):
        return "youtube"
    
    if source.startswith(("http://", "https://")):
        return "url"
    
    ext = Path(source).suffix.lower()
    return {
        ".pdf": "pdf",
        ".md": "markdown",
        ".txt": "text",
        ".html": "html",
        ".htm": "html",
    }.get(ext, "text")


def extract(source: str, wiki_root: Optional[Path] = None) -> ExtractedContent:
    """Extract content from any supported source. Auto-detects type.
    
    Args:
        source: File path (absolute or relative) or URL.
        wiki_root: Wiki root directory for resolving relative paths.
    
    Returns:
        ExtractedContent with the extracted text and metadata.
    """
    source_type = detect_source_type(source)
    
    if source_type in ("youtube", "url"):
        return _extract_youtube(source) if source_type == "youtube" else _extract_url(source)
    
    # It's a file — resolve the path
    path = Path(source)
    if not path.is_absolute() and wiki_root:
        path = wiki_root / path
    
    if not path.exists():
        return ExtractedContent(
            text="",
            source_type="error",
            title=str(path),
            metadata={"error": f"File not found: {path}"},
        )
    
    extractors = {
        "pdf": _extract_pdf,
        "markdown": _extract_text_file,
        "text": _extract_text_file,
        "html": _extract_html_file,
    }
    
    extractor = extractors.get(source_type, _extract_text_file)
    return extractor(path)


def _extract_text_file(path: Path) -> ExtractedContent:
    """Extract content from a plain text or markdown file."""
    content = path.read_text(errors="replace")
    title = path.stem.replace("-", " ").replace("_", " ").title()
    
    # Try to get title from first heading
    first_heading = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
    if first_heading:
        title = first_heading.group(1).strip()
    
    return ExtractedContent(
        text=content,
        source_type="markdown" if path.suffix == ".md" else "text",
        title=title,
        metadata={"file_name": path.name, "file_size": path.stat().st_size},
    )


def _extract_html_file(path: Path) -> ExtractedContent:
    """Extract content from a local HTML file."""
    raw_html = path.read_text(errors="replace")
    text = _html_to_text(raw_html)
    
    title = path.stem.replace("-", " ").replace("_", " ").title()
    title_match = re.search(r"<title>(.+?)</title>", raw_html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
    
    return ExtractedContent(
        text=text,
        source_type="html",
        title=title,
        metadata={"file_name": path.name},
    )


def _extract_pdf(path: Path) -> ExtractedContent:
    """Extract text from a PDF file using pymupdf."""
    try:
        import pymupdf
    except ImportError:
        return ExtractedContent(
            text="",
            source_type="error",
            title=path.name,
            metadata={
                "error": (
                    "PDF support requires pymupdf. Install with:\n"
                    "  pip install pymupdf"
                )
            },
        )
    
    pages_text = []
    metadata = {"file_name": path.name, "file_size": path.stat().st_size}
    
    try:
        with pymupdf.open(str(path)) as doc:
            metadata["page_count"] = len(doc)
            metadata["pdf_title"] = doc.metadata.get("title", "")
            metadata["pdf_author"] = doc.metadata.get("author", "")
            
            for page_num, page in enumerate(doc, 1):
                text = page.get_text()
                if text.strip():
                    pages_text.append(f"<!-- Page {page_num} -->\n{text}")
        
        title = metadata["pdf_title"] or path.stem.replace("-", " ").replace("_", " ").title()
        full_text = "\n\n".join(pages_text)
        
        return ExtractedContent(
            text=full_text,
            source_type="pdf",
            title=title,
            metadata=metadata,
        )
    except Exception as e:
        return ExtractedContent(
            text="",
            source_type="error",
            title=path.name,
            metadata={"error": f"Failed to read PDF: {e}"},
        )


def _extract_url(url: str) -> ExtractedContent:
    """Extract article content from a web URL using trafilatura."""
    try:
        import trafilatura
    except ImportError:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={
                "error": (
                    "Web URL support requires trafilatura. Install with:\n"
                    "  pip install trafilatura"
                )
            },
        )
    
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ExtractedContent(
                text="",
                source_type="error",
                title=url,
                metadata={"error": f"Failed to download: {url}"},
            )
        
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            output_format="txt",
        ) or ""
        
        title = url
        title_match = re.search(r"<title[^>]*>(.+?)</title>", downloaded, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
        
        return ExtractedContent(
            text=text,
            source_type="url",
            title=title,
            metadata={"url": url},
        )
    except Exception as e:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": f"Failed to extract from {url}: {e}"},
        )


def _extract_youtube(url: str) -> ExtractedContent:
    """Extract transcript from a YouTube video."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={
                "error": (
                    "YouTube support requires youtube-transcript-api. Install with:\n"
                    "  pip install youtube-transcript-api"
                )
            },
        )
    
    video_id = _extract_youtube_id(url)
    if not video_id:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": f"Could not extract video ID from: {url}"},
        )
    
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_entries = ytt_api.fetch(video_id)
        lines = [entry.text for entry in transcript_entries]
        text = " ".join(lines)
        
        timestamped = []
        for entry in transcript_entries:
            mins, secs = divmod(int(entry.start), 60)
            timestamped.append(f"[{mins:02d}:{secs:02d}] {entry.text}")
        
        return ExtractedContent(
            text=text,
            source_type="youtube",
            title=f"YouTube: {video_id}",
            metadata={
                "video_id": video_id,
                "url": url,
                "timestamped_transcript": "\n".join(timestamped),
                "segment_count": len(transcript_entries),
            },
        )
    except Exception as e:
        return ExtractedContent(
            text="",
            source_type="error",
            title=url,
            metadata={"error": f"Failed to get transcript for {video_id}: {e}"},
        )


def _extract_youtube_id(url: str) -> Optional[str]:
    """Extract the video ID from various YouTube URL formats."""
    from urllib.parse import urlparse, parse_qs
    
    parsed = urlparse(url)
    
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    
    if parsed.hostname in ("www.youtube.com", "youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/")[2]
    
    return None


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text."""
    try:
        import trafilatura
        result = trafilatura.extract(html, include_tables=True, output_format="txt")
        if result:
            return result
    except ImportError:
        pass
    
    # Fallback: basic regex stripping
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# ============================================================================
# 4. WikiIndex - Unified Index Manager (FTS5 + References)
# ============================================================================

class WikiIndex:
    """Unified index manager for full-text search and reference tracking."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
    
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self.initialize()
        return self._conn
    
    def initialize(self) -> None:
        """Create all tables if they don't exist."""
        self.conn.executescript("""
            -- FTS5 full-text search
            CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                page_name, content,
                tokenize='porter unicode61'
            );
            
            -- Reference links
            CREATE TABLE IF NOT EXISTS page_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_page TEXT NOT NULL,
                target_page TEXT NOT NULL,
                section TEXT,
                display_text TEXT,
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_links_source ON page_links(source_page);
            CREATE INDEX IF NOT EXISTS idx_links_target ON page_links(target_page);
            
            -- Page metadata
            CREATE TABLE IF NOT EXISTS pages (
                page_name TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                content_length INTEGER,
                word_count INTEGER,
                link_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()
    
    def upsert_page(self, page_name: str, content: str, file_path: str = "") -> None:
        """Insert or update a page in all indexes."""
        # 1. Update FTS5
        self.conn.execute("DELETE FROM pages_fts WHERE page_name = ?", (page_name,))
        self.conn.execute("INSERT INTO pages_fts (page_name, content) VALUES (?, ?)", 
                         (page_name, content))
        
        # 2. Parse links from content
        links = self._parse_links(content, file_path)
        
        # 3. Update page_links table
        self.conn.execute("DELETE FROM page_links WHERE source_page = ?", (page_name,))
        for link in links:
            self.conn.execute(
                "INSERT INTO page_links (source_page, target_page, section, display_text, file_path) VALUES (?, ?, ?, ?, ?)",
                (page_name, link['target'], link['section'], link['display'], link['file'])
            )
        
        # 4. Update page metadata
        word_count = len(content.split())
        link_count = len(links)
        updated_at = datetime.now(timezone.utc).isoformat()
        self.conn.execute("""
            INSERT INTO pages (page_name, file_path, content_length, word_count, link_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_name) DO UPDATE SET
                file_path = excluded.file_path,
                content_length = excluded.content_length,
                word_count = excluded.word_count,
                link_count = excluded.link_count,
                updated_at = excluded.updated_at
        """, (page_name, file_path, len(content), word_count, link_count, updated_at))
        
        self.conn.commit()
    
    def delete_page(self, page_name: str) -> None:
        """Remove a page from all indexes."""
        self.conn.execute("DELETE FROM pages_fts WHERE page_name = ?", (page_name,))
        self.conn.execute("DELETE FROM page_links WHERE source_page = ?", (page_name,))
        self.conn.execute("DELETE FROM pages WHERE page_name = ?", (page_name,))
        self.conn.commit()
    
    def search(self, query: str, limit: int = 10) -> List[dict]:
        """Search for pages matching the query."""
        if not query.strip():
            return []
        
        try:
            rows = self.conn.execute(
                """
                SELECT page_name, snippet(pages_fts, 1, '**', '**', '...', 32) as snippet,
                       rank
                FROM pages_fts
                WHERE pages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback to LIKE
            rows = self.conn.execute(
                """
                SELECT page_name, substr(content, 1, 200) as snippet, 0 as rank
                FROM pages_fts
                WHERE content LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()
        
        return [
            {
                "page_name": row["page_name"],
                "snippet": row["snippet"],
                "score": abs(row["rank"]),
            }
            for row in rows
        ]
    
    def get_inbound_links(self, page_name: str) -> List[dict]:
        """Get all pages that link to the given page."""
        cursor = self.conn.execute(
            "SELECT source_page, section, file_path FROM page_links WHERE target_page = ?",
            (page_name,)
        )
        return [
            {"source": row["source_page"], "section": row["section"] or "", "file": row["file_path"]}
            for row in cursor.fetchall()
        ]
    
    def get_outbound_links(self, page_name: str) -> List[dict]:
        """Get all pages that the given page links to."""
        cursor = self.conn.execute(
            "SELECT target_page, section, display_text, file_path FROM page_links WHERE source_page = ?",
            (page_name,)
        )
        return [
            {"target": row["target_page"], "section": row["section"] or "", 
             "display": row["display_text"] or row["target_page"], "file": row["file_path"]}
            for row in cursor.fetchall()
        ]
    
    def get_page_count(self) -> int:
        """Get total number of indexed pages."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM pages")
        return cursor.fetchone()[0]
    
    def get_link_count(self) -> int:
        """Get total number of links."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM page_links")
        return cursor.fetchone()[0]
    
    def _parse_links(self, content: str, file_path: str = "") -> List[dict]:
        """Parse [[wikilinks]] from content."""
        links = []
        # Match [[target]], [[target|display]], [[target#section]], [[target#section|display]]
        pattern = r'\[\[([^\]]+)\]\]'
        
        for match in re.finditer(pattern, content):
            link_text = match.group(1).strip()
            
            # Parse: target#section|display
            # First split by | for display text
            display = link_text
            if '|' in link_text:
                link_text, display = link_text.rsplit('|', 1)
            
            # Then split by # for section
            target = link_text
            section = ""
            if '#' in link_text:
                target, section = link_text.rsplit('#', 1)
                section = '#' + section
            
            links.append({
                'target': target.strip(),
                'section': section.strip() if section else '',
                'display': display.strip() if display else target.strip(),
                'file': file_path
            })
        
        return links
    
    def build_index_from_files(self, wiki_dir: Path, batch_size: int = 100) -> dict:
        """Build index by scanning all wiki markdown files.
        
        Optimized for bulk operations with:
        - Batch inserts using executemany()
        - Single transaction for all operations
        - PRAGMA optimizations for speed
        - Progress tracking for large collections
        
        Args:
            wiki_dir: Path to wiki directory
            batch_size: Number of files to process before progress update
        
        Returns:
            Dict with total_pages, total_links, and timing info
        """
        import time
        start_time = time.time()
        
        all_files = list(wiki_dir.rglob('*.md'))
        total_files = len(all_files)
        
        # Collect all data in memory first
        fts_data = []
        links_data = []
        pages_data = []
        processed = 0
        errors = 0
        
        for i, file_path in enumerate(all_files, 1):
            try:
                content = file_path.read_text()
                rel_path = str(file_path.relative_to(wiki_dir))
                page_name = rel_path[:-3]  # Faster than with_suffix('')
                
                # Parse links
                links = self._parse_links(content, rel_path)
                word_count = len(content.split())
                
                # Collect data for batch insert
                fts_data.append((page_name, content))
                pages_data.append((page_name, rel_path, len(content), word_count, len(links)))
                
                for link in links:
                    links_data.append((
                        page_name, 
                        link['target'], 
                        link['section'], 
                        link['display'], 
                        rel_path
                    ))
                
                processed += 1
                
                # Progress reporting for large collections
                if i % batch_size == 0 and total_files > batch_size:
                    elapsed = time.time() - start_time
                    rate = i / elapsed if elapsed > 0 else 0
                    eta = (total_files - i) / rate if rate > 0 else 0
                    print(f"  Processing: {i}/{total_files} ({i/total_files*100:.1f}%) - {rate:.1f} files/sec - ETA: {eta:.0f}s")
                
            except Exception as e:
                errors += 1
                continue
        
        # Optimize SQLite for bulk write (before transaction)
        orig_journal = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        orig_sync = self.conn.execute("PRAGMA synchronous").fetchone()[0]
        orig_cache = self.conn.execute("PRAGMA cache_size").fetchone()[0]
        
        self.conn.execute("PRAGMA journal_mode = MEMORY")
        self.conn.execute("PRAGMA synchronous = OFF")
        self.conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
        self.conn.execute("PRAGMA temp_store = MEMORY")
        
        try:
            # Begin explicit transaction
            self.conn.execute("BEGIN IMMEDIATE")
            
            # Batch delete old entries
            if fts_data:
                page_names = [p[0] for p in fts_data]
                placeholders = ','.join('?' * len(page_names))
                self.conn.execute(f"DELETE FROM pages_fts WHERE page_name IN ({placeholders})", page_names)
                self.conn.execute(f"DELETE FROM page_links WHERE source_page IN ({placeholders})", page_names)
                self.conn.execute(f"DELETE FROM pages WHERE page_name IN ({placeholders})", page_names)
            
            # Batch inserts using executemany
            if fts_data:
                self.conn.executemany(
                    "INSERT INTO pages_fts (page_name, content) VALUES (?, ?)", fts_data)
            
            if links_data:
                self.conn.executemany(
                    "INSERT INTO page_links (source_page, target_page, section, display_text, file_path) VALUES (?, ?, ?, ?, ?)", 
                    links_data)
            
            if pages_data:
                self.conn.executemany(
                    "INSERT INTO pages (page_name, file_path, content_length, word_count, link_count) VALUES (?, ?, ?, ?, ?)",
                    pages_data)
            
            # Commit transaction
            self.conn.commit()
            
            # Optimize FTS5 index
            self.conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('optimize')")
            
        except Exception as e:
            self.conn.rollback()
            raise
        finally:
            # Restore original PRAGMA settings (transaction already committed)
            try:
                self.conn.execute("PRAGMA synchronous = NORMAL")  # Safe default
                self.conn.execute(f"PRAGMA journal_mode = {orig_journal}")
                self.conn.execute(f"PRAGMA cache_size = {orig_cache}")
            except:
                pass  # Ignore errors when restoring
        
        elapsed = time.time() - start_time
        
        return {
            'total_pages': total_files,
            'total_links': len(links_data),
            'processed': processed,
            'errors': errors,
            'elapsed_seconds': round(elapsed, 2),
            'files_per_second': round(processed / elapsed, 1) if elapsed > 0 else 0
        }
    
    def export_json(self, output_path: Path) -> dict:
        """Export reference index to JSON format."""
        # Query all links
        cursor = self.conn.execute(
            "SELECT source_page, target_page, section, display_text, file_path FROM page_links"
        )
        
        data = {
            'built_at': datetime.now().isoformat(),
            'total_pages': self.get_page_count(),
            'outbound_links': {},
            'inbound_links': {},
            'summary': {}
        }
        
        for row in cursor.fetchall():
            source, target, section, display, file_path = row
            
            # Build outbound
            if source not in data['outbound_links']:
                data['outbound_links'][source] = []
            data['outbound_links'][source].append({
                'target': target,
                'section': section or '',
                'display': display or target
            })
            
            # Build inbound
            if target not in data['inbound_links']:
                data['inbound_links'][target] = []
            data['inbound_links'][target].append({
                'source': source,
                'section': section or '',
                'file': file_path or ''
            })
        
        # Calculate summary
        data['summary'] = {
            'pages_with_outbound': len(data['outbound_links']),
            'pages_with_inbound': len(data['inbound_links']),
            'total_outbound': sum(len(v) for v in data['outbound_links'].values()),
            'total_inbound': sum(len(v) for v in data['inbound_links'].values())
        }
        
        # Write JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return data
    
    def migrate_from_json(self, json_path: Path) -> int:
        """Migrate existing JSON reference index to SQLite."""
        if not json_path.exists():
            return 0
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        count = 0
        for source, links in data.get('outbound_links', {}).items():
            for link in links:
                self.conn.execute(
                    "INSERT INTO page_links (source_page, target_page, section, display_text) VALUES (?, ?, ?, ?)",
                    (source, link['target'], link.get('section', ''), link.get('display', link['target']))
                )
                count += 1
        
        self.conn.commit()
        return count
    
    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

# ============================================================================
# 5. Wiki Core
# ============================================================================

class Wiki:
    """Main Wiki manager."""
    
    def __init__(self, root: Path, config: Optional[dict] = None):
        self.root = root.resolve()
        self.raw_dir = self.root / RAW_DIR
        self.wiki_dir = self.root / WIKI_DIR
        self.index_file = self.root / INDEX_FILE
        self.log_file = self.root / LOG_FILE
        self.db_path = self.root / DB_FILE
        self._ref_index_path: Optional[Path] = None
        
        # Load configuration (pure tool design - zero domain assumptions)
        self.config = config or self._load_config()
        
        # Universal exclusion patterns (minimal, cross-domain)
        self._default_exclude_patterns = [
            r'^\d{4}-\d{2}-\d{2}$',      # Date format: 2025-07-31
            r'^\d{4}-\d{2}$',            # Month format: 2025-07
            r'^\d{4}-Q[1-4]$',           # Quarter format: 2025-Q1
        ]
        
        # User-configured patterns
        self._user_exclude_patterns = self.config.get('orphan_exclude_patterns', [])
        
        # Frontmatter keys that indicate exclusion
        self._exclude_frontmatter_keys = self.config.get('orphan_exclude_frontmatter', ['redirect_to'])
        
        # Archive directory names
        self._archive_dirs = self.config.get('archive_directories', ['archive', 'logs', 'history'])
        
        self._index: Optional[WikiIndex] = None
        self._ref_index_path: Optional[Path] = None
    
    def _load_config(self) -> dict:
        """Load configuration from multiple sources.
        
        Priority (high to low):
        1. Explicit config parameter
        2. .wiki-config.yaml
        3. WIKI.md frontmatter
        4. Defaults (minimal assumptions)
        
        Returns:
            Config dict with orphan exclusion settings
        """
        config = {}
        
        # 1. Check .wiki-config.yaml
        config_file = self.root / '.wiki-config.yaml'
        if config_file.exists():
            try:
                import yaml
                config.update(yaml.safe_load(config_file.read_text()) or {})
            except Exception:
                pass  # Ignore parse errors, use defaults
        
        # 2. Check WIKI.md frontmatter (if not already configured)
        if not config:
            wiki_md = self.root / 'WIKI.md'
            if wiki_md.exists():
                content = wiki_md.read_text()
                # Extract YAML frontmatter
                match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
                if match:
                    try:
                        import yaml
                        frontmatter = yaml.safe_load(match.group(1))
                        if frontmatter:
                            config.update(frontmatter)
                    except Exception:
                        pass
        
        return config
    
    def _should_exclude_orphan(self, page_name: str, page_path: Path) -> bool:
        """Determine if a page should be excluded from orphan detection.
        
        Pure tool design - zero domain assumptions. Uses:
        1. Universal patterns: dates, quarters (cross-domain conventions)
        2. Frontmatter markers: redirect_to, user-defined keys
        3. Directory structure: archive/, logs/, user-defined dirs
        4. User-configured patterns: regex from config
        
        Does NOT assume any domain-specific concepts like "daily summary".
        
        Args:
            page_name: Page name (stem, lowercase)
            page_path: Full path to the page file
        
        Returns:
            True if page should be excluded from orphan detection
        """
        # 1. Check frontmatter markers
        if page_path.exists():
            try:
                content = page_path.read_text()
                
                # Check for configured frontmatter keys
                for key in self._exclude_frontmatter_keys:
                    if re.search(rf'^{key}:', content, re.MULTILINE):
                        return True
            except Exception:
                pass
        
        # 2. Check universal patterns
        for pattern in self._default_exclude_patterns:
            if re.match(pattern, page_name):
                return True
        
        # 3. Check user-configured patterns
        for pattern in self._user_exclude_patterns:
            if re.match(pattern, page_name):
                return True
        
        # 4. Check directory structure
        if page_path.exists():
            try:
                rel_path = str(page_path.relative_to(self.wiki_dir))
                if any(rel_path.startswith(d + '/') for d in self._archive_dirs):
                    return True
            except Exception:
                pass
        
        return False
    
    @property
    def ref_index_path(self) -> Path:
        """Get reference index JSON path."""
        if self._ref_index_path is None:
            self._ref_index_path = self.wiki_dir / 'reference_index.json'
        return self._ref_index_path
    
    @property
    def index(self) -> WikiIndex:
        """Lazy-load WikiIndex."""
        if self._index is None:
            self._index = WikiIndex(self.db_path)
        return self._index
    
    @property
    def is_initialized(self) -> bool:
        return self.wiki_dir.exists()
    
    def init(self, agent: str = "claude") -> str:
        """Initialize wiki directory structure."""
        if self.is_initialized:
            return f"Wiki already initialized at {self.root}"
        
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        
        # Create index.md
        self.index_file.write_text(
            "# Wiki Index\n\n"
            "_This index is maintained by the LLM._\n\n"
            "## Pages\n\n"
            "_No pages yet. Ingest a source to get started._\n"
        )
        
        # Create log.md
        self.log_file.write_text(
            "# Wiki Log\n\n"
            "_Chronological record of wiki operations._\n\n"
            f"## [{_now()}] init | Wiki initialized (agent: {agent})\n\n"
        )
        
        # Initialize database
        self.index.initialize()
        
        # Create config template (if not exists)
        config_template = self.root / '.wiki-config.yaml.example'
        if not config_template.exists():
            # Copy template from package
            template_content = """# Wiki Configuration
# Copy to .wiki-config.yaml and customize for your use case.

orphan_pages:
  exclude_patterns: []
  # Examples:
  # - '^\\d{4}-\\d{2}-\\d{2}$'  # Daily logs
  # - '^meeting-.*'             # Meeting notes
  
  exclude_frontmatter: []
  # Examples:
  # - 'redirect_to'             # Redirect pages
  # - 'template: true'          # Template pages
  
  archive_directories: []
  # Examples:
  # - 'daily'                   # Daily summaries
  # - 'journal'                 # Personal journal
"""
            config_template.write_text(template_content)
        
        return (
            f"Wiki initialized at {self.root}\n"
            f"  raw/     → drop source files here\n"
            f"  wiki/    → LLM-maintained wiki pages\n"
            f"  {DB_FILE} → SQLite index (search + references)\n"
            f"  .wiki-config.yaml.example → configuration template\n"
        )
    
    def ingest_source(self, source: str) -> dict:
        """Ingest a source and return extracted content."""
        result = extract(source, wiki_root=self.root)
        
        if result.source_type == "error":
            return {"error": result.metadata.get("error", "Unknown extraction error")}
        
        # Save URL-sourced content to raw/
        source_name = result.title
        if result.source_type in ("url", "youtube"):
            safe_name = self._slugify(result.title) + ".md"
            saved_path = self.raw_dir / safe_name
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_text(result.text)
            source_name = safe_name
        else:
            source_name = Path(source).name
        
        # Get current index for context
        index_content = ""
        if self.index_file.exists():
            index_content = self.index_file.read_text()
        
        self.append_log("ingest", f"Source ({result.source_type}): {result.title}")
        
        return {
            "source_name": source_name,
            "source_type": result.source_type,
            "title": result.title,
            "content": result.text,
            "content_length": result.content_length,
            "metadata": result.metadata,
            "current_index": index_content,
            "instructions": (
                "You have received a new source document. Please:\n"
                "1. Read and understand the content\n"
                "2. Create/update relevant wiki pages using wiki_write_page\n"
                "3. Update the index using wiki_write_page for 'index.md'\n"
                "4. Add cross-references ([[Page Name]]) between related pages\n"
                "5. Log what you did using wiki_log"
            ),
        }
    
    def write_page(self, page_name: str, content: str) -> str:
        """Create or update a wiki page."""
        if not page_name.endswith(".md"):
            page_name += ".md"
        
        page_path = self.wiki_dir / page_name
        page_path.parent.mkdir(parents=True, exist_ok=True)
        
        is_update = page_path.exists()
        page_path.write_text(content)
        
        # Index for search and references
        rel_path = str(page_path.relative_to(self.wiki_dir))
        self.index.upsert_page(page_name[:-3], content, rel_path)
        
        action = "Updated" if is_update else "Created"
        return f"{action} wiki/{page_name} ({len(content)} chars)"
    
    def read_page(self, page_name: str) -> dict:
        """Read a wiki page."""
        if not page_name.endswith(".md"):
            page_name += ".md"
        
        page_path = self.wiki_dir / page_name
        if not page_path.exists():
            return {"error": f"Page not found: wiki/{page_name}"}
        
        return {
            "page_name": page_name,
            "content": page_path.read_text(),
        }
    
    def search(self, query: str, limit: int = 10) -> list:
        """Full-text search."""
        return self.index.search(query, limit)
    
    def lint(self) -> dict:
        """Health-check the wiki."""
        issues: List[Issue] = []
        pages = list(self.wiki_dir.glob("**/*.md"))
        
        # Collect all page names
        page_names = {p.stem.lower() for p in pages}
        page_names_full = {p.stem: str(p) for p in pages}
        
        # Track inbound links
        inbound_links: Dict[str, int] = {p.stem.lower(): 0 for p in pages}
        meta_pages = {"index", "log"}
        
        for page_path in pages:
            content = page_path.read_text()
            name = page_path.stem.lower()
            
            # Check empty pages
            stripped = content.strip()
            if not stripped or stripped == f"# {page_path.stem}":
                issues.append(Issue(
                    issue_type="empty_page",
                    page=page_path.stem,
                    message="Page is empty or has only a title"
                ))
            
            # Find [[wiki links]]
            links = re.findall(r"\[\[([^\]]+)\]\]", content)
            for link in links:
                link_lower = link.lower().split('|')[0].split('#')[0].strip()
                if link_lower in inbound_links:
                    inbound_links[link_lower] += 1
                if link_lower not in page_names:
                    issues.append(Issue(
                        issue_type="broken_link",
                        page=page_path.stem,
                        message=f"Links to [[{link}]] but no such page exists",
                        link=link
                    ))
        
        # Check orphan pages
        for page_name, count in inbound_links.items():
            if count == 0 and page_name not in meta_pages:
                page_path = self.wiki_dir / f"{page_name}.md"
                
                # Use pure tool design - check if should be excluded
                if not self._should_exclude_orphan(page_name, page_path):
                    issues.append(Issue(
                        issue_type="orphan_page",
                        page=page_name,
                        message="No other page links to this page"
                    ))
        
        return {
            "total_pages": len(pages),
            "issue_count": len(issues),
            "issues": [vars(i) for i in issues],
            "summary": f"Found {len(issues)} issue(s) across {len(pages)} pages"
        }
    
    def recommend(self) -> dict:
        """Generate smart recommendations for wiki improvements.
        
        Analyzes the wiki to suggest:
        - Missing pages (frequently referenced but don't exist)
        - Orphan pages that need linking
        - Content gaps (topics mentioned but not covered)
        - Cross-reference opportunities
        
        Returns:
            Dict with recommendations categorized by type and priority
        """
        pages = list(self.wiki_dir.glob("**/*.md"))
        page_names = {p.stem.lower() for p in pages}
        page_names_normalized = {p.stem: p.stem.lower() for p in pages}
        
        # Collect all links and their frequencies
        all_links = []
        link_counts = {}
        link_sources = {}  # Track which pages reference each missing link
        
        for page_path in pages:
            content = page_path.read_text()
            links = re.findall(r"\[\[([^\]]+)\]\]", content)
            
            for link in links:
                # Normalize: extract base name without section/display
                link_base = link.lower().split('|')[0].split('#')[0].strip()
                all_links.append(link_base)
                
                if link_base not in page_names:
                    # Missing page
                    if link_base not in link_counts:
                        link_counts[link_base] = 0
                        link_sources[link_base] = []
                    link_counts[link_base] += 1
                    link_sources[link_base].append(str(page_path.relative_to(self.wiki_dir)))
        
        # Identify inbound link counts for existing pages
        inbound_counts = {name: 0 for name in page_names}
        for page_path in pages:
            content = page_path.read_text()
            links = re.findall(r"\[\[([^\]]+)\]\]", content)
            for link in links:
                link_base = link.lower().split('|')[0].split('#')[0].strip()
                if link_base in inbound_counts:
                    inbound_counts[link_base] += 1
        
        # Find frequently referenced missing pages (priority candidates)
        missing_pages = []
        for link, count in sorted(link_counts.items(), key=lambda x: x[1], reverse=True):
            if count >= 2:  # Referenced at least twice
                missing_pages.append({
                    'page': link,
                    'reference_count': count,
                    'referenced_by': list(set(link_sources[link]))[:10],  # Limit to 10
                    'priority': 'high' if count >= 5 else 'medium'
                })
        
        # Find orphan pages (no inbound links) - pure tool design
        meta_pages = {"index", "log"}
        orphan_pages = []
        for name, count in inbound_counts.items():
            if count == 0 and name not in meta_pages:
                page_path = self.wiki_dir / f"{name}.md"
                
                # Exclude pages based on universal patterns + user config
                if not self._should_exclude_orphan(name, page_path):
                    orphan_pages.append({
                        'page': name,
                        'priority': 'low'
                    })
        
        # Find content gaps (topics mentioned in text but not linked)
        # This is a simple heuristic - could be enhanced with NLP
        content_gaps = []
        common_topics = [
            'gold', 'copper', 'silver', 'lithium', 'mining', 'price', 
            'production', 'reserve', 'exploration', 'acquisition', 'ipo'
        ]
        
        for page_path in pages:
            if page_path.stem.lower() in meta_pages:
                continue
            content = page_path.read_text().lower()
            
            for topic in common_topics:
                if topic in content and f"[[{topic}" not in content.lower():
                    # Topic mentioned but not linked
                    content_gaps.append({
                        'page': str(page_path.relative_to(self.wiki_dir)),
                        'topic': topic,
                        'suggestion': f"Consider adding [[{topic}]] link"
                    })
        
        # Calculate cross-reference opportunities
        # Pages that should be linked but aren't
        cross_ref_opportunities = []
        page_topics = {}
        
        for page_path in pages:
            content = page_path.read_text().lower()
            page_name = page_path.stem.lower()
            
            # Extract topics from content
            topics = []
            for topic in common_topics:
                if topic in content:
                    topics.append(topic)
            
            page_topics[page_name] = topics
        
        # Find pages with similar topics that don't reference each other
        page_list = list(page_topics.keys())
        for i, page1 in enumerate(page_list):
            for page2 in page_list[i+1:]:
                # Check if they share topics
                shared = set(page_topics[page1]) & set(page_topics[page2])
                if len(shared) >= 2:
                    # Check if they reference each other
                    page1_path = self.wiki_dir / f"{page1}.md"
                    if page1_path.exists():
                        content = page1_path.read_text()
                        if f"[[{page2}]]" not in content and f"[[{page2}|".lower() not in content.lower():
                            cross_ref_opportunities.append({
                                'from': page1,
                                'to': page2,
                                'shared_topics': list(shared),
                                'reason': f"Share topics: {', '.join(shared)}"
                            })
        
        # Limit recommendations
        cross_ref_opportunities = cross_ref_opportunities[:20]
        content_gaps = content_gaps[:30]
        
        return {
            'missing_pages': missing_pages,
            'orphan_pages': orphan_pages,
            'content_gaps': content_gaps,
            'cross_reference_opportunities': cross_ref_opportunities,
            'summary': {
                'total_missing_pages': len(missing_pages),
                'high_priority_missing': len([m for m in missing_pages if m['priority'] == 'high']),
                'total_orphans': len(orphan_pages),
                'content_gaps_count': len(content_gaps),
                'cross_ref_opportunities': len(cross_ref_opportunities)
            }
        }
    
    def status(self) -> dict:
        """Get wiki status overview."""
        if not self.is_initialized:
            return {"initialized": False, "message": "Wiki not initialized"}
        
        pages = list(self.wiki_dir.glob("**/*.md"))
        sources = [s for s in self.raw_dir.glob("**/*") if s.is_file()]
        
        # Get recent log
        recent_log = ""
        if self.log_file.exists():
            log_lines = self.log_file.read_text().strip().split("\n")
            recent_log = "\n".join(log_lines[-20:])
        
        return {
            "initialized": True,
            "root": str(self.root),
            "page_count": len(pages),
            "source_count": len(sources),
            "indexed_pages": self.index.get_page_count(),
            "total_links": self.index.get_link_count(),
            "pages": [p.stem for p in pages],
            "sources": [s.name for s in sources],
            "recent_log": recent_log
        }
    
    def append_log(self, operation: str, details: str) -> str:
        """Append entry to wiki log."""
        entry = f"\n## [{_now()}] {operation} | {details}\n"
        if self.log_file.exists():
            with open(self.log_file, "a") as f:
                f.write(entry)
        else:
            self.log_file.write_text(f"# Wiki Log\n{entry}")
        return f"Logged: {operation} | {details}"
    
    def build_index(self, auto_export: bool = True, output_path: Optional[Path] = None) -> dict:
        """Build reference index from all wiki files."""
        result = self.index.build_index_from_files(self.wiki_dir)
        
        if auto_export:
            export_path = output_path or self.ref_index_path
            export_data = self.index.export_json(export_path)
            result['json_export'] = str(export_path)
            result['summary'] = export_data.get('summary', {})
        
        return result
    
    def export_index(self, output_path: Path) -> dict:
        """Export reference index to JSON."""
        return self.index.export_json(output_path)
    
    def get_inbound_links(self, page_name: str) -> list:
        """Get inbound links for a page."""
        return self.index.get_inbound_links(page_name)
    
    def get_outbound_links(self, page_name: str) -> list:
        """Get outbound links for a page."""
        return self.index.get_outbound_links(page_name)
    
    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to slug."""
        slug = re.sub(r"[^\w\s-]", "", text.lower())
        return re.sub(r"[\s_-]+", "-", slug).strip("-")[:80]
    
    def close(self):
        """Cleanup."""
        if self._index:
            self._index.close()


def _now() -> str:
    """Get current timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


# ============================================================================
# 6. MCP Server
# ============================================================================

class MCPServer:
    """MCP server for wiki operations."""
    
    def __init__(self, wiki: Wiki):
        self.wiki = wiki
        self._mcp = None
    
    def register_tools(self):
        """Register all wiki tools with MCP."""
        try:
            from mcp.server.fastmcp import FastMCP
            
            self._mcp = FastMCP(
                "wiki",
                instructions="LLM Wiki — a persistent, LLM-maintained knowledge base."
            )
            
            @self._mcp.tool()
            def wiki_init(agent: str = "claude") -> str:
                """Initialize a new LLM Wiki."""
                return self.wiki.init(agent=agent)
            
            @self._mcp.tool()
            def wiki_ingest(source: str) -> dict:
                """Ingest a source into the wiki."""
                return self.wiki.ingest_source(source)
            
            @self._mcp.tool()
            def wiki_write_page(page_name: str, content: str) -> str:
                """Create or update a wiki page."""
                return self.wiki.write_page(page_name, content)
            
            @self._mcp.tool()
            def wiki_read_page(page_name: str) -> dict:
                """Read a wiki page."""
                return self.wiki.read_page(page_name)
            
            @self._mcp.tool()
            def wiki_search(query: str, limit: int = 10) -> list:
                """Search the wiki."""
                return self.wiki.search(query, limit)
            
            @self._mcp.tool()
            def wiki_lint() -> dict:
                """Health-check the wiki."""
                return self.wiki.lint()
            
            @self._mcp.tool()
            def wiki_status() -> dict:
                """Get wiki status."""
                return self.wiki.status()
            
            @self._mcp.tool()
            def wiki_log(operation: str, details: str) -> str:
                """Append entry to wiki log."""
                return self.wiki.append_log(operation, details)
            
        except ImportError:
            raise ImportError("MCP server requires 'mcp' package: pip install mcp")
    
    def serve(self, transport: str = "stdio"):
        """Start MCP server."""
        if self._mcp is None:
            self.register_tools()
        
        self._mcp.run(transport=transport)


# ============================================================================
# 7. CLI Handler
# ============================================================================

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
        
        if result.get('recent_log'):
            print("\n📝 Recent Log:")
            for line in result['recent_log'].split('\n')[-5:]:
                if line.strip():
                    print(f"   {line}")
        
        return 0
    
    def log(self, args) -> int:
        """Record log entry."""
        result = self.wiki.append_log(args.operation, args.description)
        print(f"✅ {result}")
        return 0
    
    def references(self, args) -> int:
        """Show page references."""
        page_name = args.page
        
        inbound = self.wiki.get_inbound_links(page_name)
        outbound = self.wiki.get_outbound_links(page_name)
        
        if not inbound and not outbound:
            print(f"No references found for: {page_name}")
            return 0
        
        print(f"=== References for {page_name} ===\n")
        
        if outbound:
            print(f"📤 Outbound links ({len(outbound)}):")
            for link in outbound[:20]:
                if link['section']:
                    print(f"   → [[{link['target']}{link['section']}|{link['display']}]]")
                else:
                    print(f"   → [[{link['target']}|{link['display']}]]")
            if len(outbound) > 20:
                print(f"   ... and {len(outbound) - 20} more")
            print()
        
        if inbound:
            print(f"📥 Inbound links ({len(inbound)}):")
            for ref in inbound[:20]:
                if ref['section']:
                    print(f"   ← [[{ref['source']}{ref['section']}|{ref['source']}]] ({ref['file']})")
                else:
                    print(f"   ← [[{ref['source']}|{ref['source']}]] ({ref['file']})")
            if len(inbound) > 20:
                print(f"   ... and {len(inbound) - 20} more")
            print()
        
        print(f"📊 Summary:")
        print(f"   This page links to: {len(outbound)} pages")
        print(f"   Referenced by: {len(inbound)} pages")
        
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
        print(f"Processed: {result.get('processed', result['total_pages'])}")
        print(f"Errors: {result.get('errors', 0)}")
        print(f"⏱️  Elapsed: {result.get('elapsed_seconds', 'N/A')}s")
        print(f"📈 Speed: {result.get('files_per_second', 'N/A')} files/sec")
        
        if not no_export:
            print(f"JSON export: {result.get('json_export', 'N/A')}")
            if 'summary' in result:
                print(f"Pages with outbound: {result['summary'].get('pages_with_outbound', 'N/A')}")
                print(f"Pages with inbound: {result['summary'].get('pages_with_inbound', 'N/A')}")
        
        return 0
    
    def export_index(self, args) -> int:
        """Export reference index to JSON."""
        output = getattr(args, 'output', str(self.wiki.ref_index_path))
        output_path = Path(output)
        
        print(f"=== Exporting Reference Index ===")
        data = self.wiki.export_index(output_path)
        
        print(f"Exported to: {output_path}")
        print(f"Total pages: {data['total_pages']}")
        print(f"Total links: {data['summary'].get('total_outbound', 'N/A')}")
        
        return 0
    
    def batch(self, args) -> int:
        """Batch ingest files."""
        source_dir = Path(args.directory)
        limit = getattr(args, 'limit', 10)
        
        if not source_dir.exists():
            print(f"❌ Directory not found: {source_dir}")
            return 1
        
        pdf_files = list(source_dir.glob('*.pdf'))[:limit]
        
        if not pdf_files:
            print(f"❌ No PDF files found in: {source_dir}")
            return 1
        
        print(f"📊 Batch Ingest")
        print(f"   Source: {source_dir}")
        print(f"   Files: {len(pdf_files)}\n")
        
        success = failed = 0
        for pdf in pdf_files:
            print(f"Processing: {pdf.name}")
            
            class Args:
                file = pdf
            
            if self.ingest(Args()) == 0:
                success += 1
            else:
                failed += 1
        
        print(f"\n✅ Batch complete!")
        print(f"   Processed: {success}")
        print(f"   Failed: {failed}")
        
        return 0 if failed == 0 else 1
    
    def hint(self, args) -> int:
        """Smart suggestions."""
        lint_result = self.wiki.lint()
        status_result = self.wiki.status()
        
        print("=== Wiki Hint Report ===\n")
        print(f"📊 Total pages: {status_result.get('page_count', 0)}")
        print(f"📦 Total sources: {status_result.get('source_count', 0)}")
        print(f"⚠️  Health issues: {lint_result.get('issue_count', 0)}")
        
        if lint_result['issues']:
            by_type = {}
            for issue in lint_result['issues']:
                t = issue.get('type') or issue.get('issue_type', 'unknown')
                by_type[t] = by_type.get(t, 0) + 1
            
            print("\n⚠️  Issues by type:")
            for t, count in sorted(by_type.items()):
                print(f"   {t}: {count}")
            
            # Missing pages
            missing = [i for i in lint_result['issues'] if (i.get('type') or i.get('issue_type')) == 'broken_link']
            if missing:
                link_counts = {}
                for issue in missing:
                    link = issue.get('link', 'unknown')
                    link_counts[link] = link_counts.get(link, 0) + 1
                
                top_missing = sorted(link_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                print("\n   Missing pages (referenced but not exist):")
                for link, count in top_missing:
                    print(f"      [[{link}]] - referenced {count} times")
        else:
            print("\n✅ Wiki is healthy!")
        
        print("\n💡 Suggestions:")
        print("   - Run 'wiki lint' for detailed issue list")
        print("   - Create pages for frequently referenced topics")
        print("   - Add [[cross-references]] between related pages")
        
        return 0 if not lint_result['issues'] else 1
    
    def recommend(self, args) -> int:
        """Generate smart recommendations for wiki improvements."""
        result = self.wiki.recommend()
        
        print("=== Wiki Recommendations ===\n")
        
        # Missing pages (high priority)
        if result['missing_pages']:
            print(f"🔴 Missing Pages ({result['summary']['total_missing_pages']} found)")
            print(f"   High priority: {result['summary']['high_priority_missing']}\n")
            
            for rec in result['missing_pages'][:10]:
                priority_icon = "🔴" if rec['priority'] == 'high' else "🟡"
                print(f"   {priority_icon} [[{rec['page']}]]")
                print(f"      Referenced {rec['reference_count']} times")
                if rec['referenced_by']:
                    print(f"      From: {', '.join(rec['referenced_by'][:3])}")
                print()
        else:
            print("✅ No missing pages detected\n")
        
        # Orphan pages
        if result['orphan_pages']:
            print(f"🟠 Orphan Pages ({result['summary']['total_orphans']} found)")
            print("   Pages with no inbound links:\n")
            for rec in result['orphan_pages'][:10]:
                print(f"   - [[{rec['page']}]]")
            if len(result['orphan_pages']) > 10:
                print(f"   ... and {len(result['orphan_pages']) - 10} more")
            print()
        else:
            print("✅ No orphan pages\n")
        
        # Cross-reference opportunities
        if result['cross_reference_opportunities']:
            print(f"🔗 Cross-Reference Opportunities ({result['summary']['cross_ref_opportunities']})\n")
            for opp in result['cross_reference_opportunities'][:10]:
                print(f"   • [[{opp['from']}]] → [[{opp['to']}]]")
                print(f"     Reason: {opp['reason']}")
            print()
        else:
            print("✅ Good cross-reference coverage\n")
        
        # Content gaps
        if result['content_gaps']:
            print(f"💬 Content Gaps ({result['summary']['content_gaps_count']} opportunities)\n")
            for gap in result['content_gaps'][:10]:
                print(f"   • {gap['page']}: {gap['suggestion']}")
            print()
        
        # Summary
        print("=== Summary ===")
        print(f"Total recommendations:")
        print(f"  - Missing pages to create: {result['summary']['total_missing_pages']}")
        print(f"  - Orphan pages to link: {result['summary']['total_orphans']}")
        print(f"  - Cross-references to add: {result['summary']['cross_ref_opportunities']}")
        print(f"  - Content gaps to fill: {result['summary']['content_gaps_count']}")
        
        return 0
    
    def serve(self, args) -> int:
        """Start MCP server."""
        try:
            server = MCPServer(self.wiki)
            server.register_tools()
            print("Starting MCP server...")
            server.serve()
            return 0
        except ImportError as e:
            print(f"❌ Error: {e}")
            print("   Install with: pip install mcp")
            return 1
    
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


# ============================================================================
# 8. Main Entry Point
# ============================================================================

def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='wiki',
        description='Wiki.py v9.0 - LLM Wiki Management CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  wiki ingest document.pdf                Ingest a PDF file
  wiki write_page "Page" -c "Content"     Create a page
  wiki read_page "Page"                   Read a page
  wiki search "gold" -l 10                Full-text search
  wiki lint                               Health check
  wiki status                             Show status
  wiki log "ingest" "doc.pdf"             Record log
  wiki references "Agnico Eagle"          Show references
  wiki build-index                        Build reference index
  wiki export-index -o custom.json        Export to JSON
  wiki batch raw/pdfs/ -l 15              Batch ingest
  wiki init --agent claude                Initialize wiki
  wiki serve                              Start MCP server

Environment variables:
  WIKI_ROOT    Wiki root directory (default: /home/ll/mining_news)
"""
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # init
    p = subparsers.add_parser('init', help='Initialize wiki')
    p.add_argument('--agent', '-a', default='claude', 
                   choices=['claude', 'codex', 'cursor', 'generic'],
                   help='LLM agent type')
    
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
    p.add_argument('--limit', '-l', type=int, default=10, help='Max results')
    
    # lint
    subparsers.add_parser('lint', help='Health check')
    
    # status
    subparsers.add_parser('status', help='Show status')
    
    # log
    p = subparsers.add_parser('log', help='Record log')
    p.add_argument('operation', help='Operation name')
    p.add_argument('description', help='Description')
    
    # references
    p = subparsers.add_parser('references', help='Show page references')
    p.add_argument('page', help='Page name')
    
    # build-index
    p = subparsers.add_parser('build-index', help='Build reference index')
    p.add_argument('--no-export', action='store_true', help='Skip JSON export')
    p.add_argument('--output', '-o', help='Custom JSON output path')
    
    # export-index
    p = subparsers.add_parser('export-index', help='Export reference index to JSON')
    p.add_argument('--output', '-o', help='Output file path')
    
    # batch
    p = subparsers.add_parser('batch', help='Batch ingest')
    p.add_argument('directory', help='Source directory')
    p.add_argument('--limit', '-l', type=int, default=10, help='Max files')
    
    # hint
    subparsers.add_parser('hint', help='Smart suggestions')
    
    # recommend
    subparsers.add_parser('recommend', help='Generate smart recommendations')
    
    # serve
    subparsers.add_parser('serve', help='Start MCP server')
    
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
            pass  # Use defaults on error
    
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
        'references': cli.references,
        'build-index': cli.build_index,
        'export-index': cli.export_index,
        'batch': cli.batch,
        'hint': cli.hint,
        'recommend': cli.recommend,
        'serve': cli.serve,
    }
    
    try:
        return commands[args.command](args)
    finally:
        cli.wiki.close()


if __name__ == '__main__':
    sys.exit(main())
