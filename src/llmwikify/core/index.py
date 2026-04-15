"""WikiIndex - SQLite FTS5 full-text search and reference tracking."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class WikiIndex:
    """Unified index manager for full-text search and reference tracking."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
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

    def _execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Thread-safe SQL execution."""
        with self._lock:
            return self.conn.execute(query, params)

    def _executemany(self, query: str, params_list: list) -> sqlite3.Cursor:
        """Thread-safe bulk SQL execution."""
        with self._lock:
            return self.conn.executemany(query, params_list)

    def _commit(self) -> None:
        """Thread-safe commit."""
        with self._lock:
            self.conn.commit()

    def upsert_page(self, page_name: str, content: str, file_path: str = "") -> None:
        """Insert or update a page in all indexes."""
        # 1. Update FTS5
        self._execute("DELETE FROM pages_fts WHERE page_name = ?", (page_name,))
        self._execute(
            "INSERT INTO pages_fts (page_name, content) VALUES (?, ?)",
            (page_name, content)
        )

        # 2. Parse links from content
        links = self._parse_links(content, page_name, file_path)

        # 3. Update links
        self._execute("DELETE FROM page_links WHERE source_page = ?", (page_name,))
        if links:
            self._executemany(
                """INSERT INTO page_links (source_page, target_page, section, display_text, file_path)
                   VALUES (?, ?, ?, ?, ?)""",
                [(l['source_page'], l['target'], l['section'], l['display'], l['file_path']) for l in links]
            )

        # 4. Update metadata (ON CONFLICT preserves created_at)
        self._execute(
            """INSERT INTO pages (page_name, file_path, content_length, word_count, link_count)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(page_name) DO UPDATE SET
                   file_path = excluded.file_path,
                   content_length = excluded.content_length,
                   word_count = excluded.word_count,
                   link_count = excluded.link_count,
                   updated_at = CURRENT_TIMESTAMP""",
            (page_name, file_path, len(content), len(content.split()), len(links))
        )

        self._commit()

    def delete_page(self, page_name: str) -> None:
        """Remove a page from all indexes."""
        self._execute("DELETE FROM pages_fts WHERE page_name = ?", (page_name,))
        self._execute("DELETE FROM page_links WHERE source_page = ?", (page_name,))
        self._execute("DELETE FROM pages WHERE page_name = ?", (page_name,))
        self._commit()

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search with ranking and highlighted snippets."""
        try:
            cursor = self.conn.execute(
                """SELECT page_name,
                          snippet(pages_fts, 1, '**', '**', '...', 32) as snippet,
                          bm25(pages_fts) as score
                   FROM pages_fts
                   WHERE pages_fts MATCH ?
                   ORDER BY score
                   LIMIT ?""",
                (query, limit)
            )
        except sqlite3.OperationalError:
            # FTS5 query syntax error, fallback to LIKE
            cursor = self.conn.execute(
                """SELECT page_name,
                          substr(content, 1, 200) as snippet,
                          0 as score
                   FROM pages_fts
                   WHERE content LIKE ?
                   LIMIT ?""",
                (f"%{query}%", limit)
            )

        results = []
        for row in cursor.fetchall():
            snippet = row['snippet']
            results.append({
                "page_name": row['page_name'],
                "score": abs(row['score']),
                "snippet": snippet,
            })

        return results

    def get_inbound_links(self, page_name: str) -> list[dict]:
        """Get pages that link to this page."""
        cursor = self.conn.execute(
            """SELECT source_page, section, file_path
               FROM page_links
               WHERE target_page = ?
               ORDER BY created_at DESC""",
            (page_name,)
        )

        return [
            {
                "source": row['source_page'],
                "section": row['section'],
                "file": row['file_path'],
            }
            for row in cursor.fetchall()
        ]

    def get_outbound_links(self, page_name: str) -> list[dict]:
        """Get pages that this page links to."""
        cursor = self.conn.execute(
            """SELECT target_page, section, display_text, file_path
               FROM page_links
               WHERE source_page = ?
               ORDER BY created_at DESC""",
            (page_name,)
        )

        return [
            {
                "target": row['target_page'],
                "section": row['section'],
                "display": row['display_text'],
                "file": row['file_path'],
            }
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

    def _parse_links(self, content: str, source_page: str, file_path: str = "") -> list[dict]:
        """Parse [[wikilinks]] from content."""
        import re
        pattern = r'\[\[([^\]]+)\]\]'
        links = []

        for match in re.finditer(pattern, content):
            link_text = match.group(1)
            parts = link_text.split('|')

            if len(parts) == 2:
                # [[target|display]] or [[target#section|display]]
                target_part = parts[0]
                display = parts[1]
            else:
                target_part = link_text
                display = target_part

            # Split target and section
            if '#' in target_part:
                target, section = target_part.split('#', 1)
                section = '#' + section
            else:
                target = target_part
                section = ''

            links.append({
                "source_page": source_page,
                "target": target.strip(),
                "section": section,
                "display": display.strip(),
                "file_path": file_path,
            })

        return links

    def build_index_from_files(self, wiki_dir: Path, batch_size: int = 100) -> dict:
        """Build index from all wiki markdown files."""
        import time
        start_time = time.time()

        # Clear existing index
        self._execute("DELETE FROM pages_fts")
        self._execute("DELETE FROM page_links")
        self._execute("DELETE FROM pages")

        # Process all markdown files
        md_files = list(wiki_dir.rglob("*.md"))
        total = len(md_files)

        for i, md_file in enumerate(md_files):
            if (i + 1) % batch_size == 0 or (i + 1) == total:
                elapsed = time.time() - start_time
                speed = (i + 1) / elapsed if elapsed > 0 else 0
                print(f"\r  Processing: {i+1}/{total} ({(i+1)/total*100:.1f}%) - {speed:.1f} files/sec", end='', flush=True)

            content = md_file.read_text()
            page_name = md_file.stem
            rel_path = str(md_file.relative_to(wiki_dir))

            self.upsert_page(page_name, content, rel_path)

        print()  # New line after progress

        elapsed = time.time() - start_time
        speed = total / elapsed if elapsed > 0 else 0

        return {
            "total_pages": total,
            "total_links": self.get_link_count(),
            "processed": total,
            "errors": 0,
            "elapsed_seconds": round(elapsed, 2),
            "files_per_second": round(speed, 1),
        }

    def export_json(self, output_path: Path) -> dict:
        """Export reference index to JSON."""
        # Build data structure
        data = {
            "built_at": datetime.now(timezone.utc).isoformat(),
            "total_pages": self.get_page_count(),
            "total_links": self.get_link_count(),
            "outbound_links": {},
            "inbound_links": {},
            "summary": {
                "pages_with_outbound": 0,
                "pages_with_inbound": 0,
            },
        }

        # Get all outbound links
        cursor = self.conn.execute(
            """SELECT DISTINCT source_page FROM page_links"""
        )
        pages_with_outbound = set(row[0] for row in cursor.fetchall())
        data["summary"]["pages_with_outbound"] = len(pages_with_outbound)

        for page in pages_with_outbound:
            data["outbound_links"][page] = self.get_outbound_links(page)

        # Get all inbound links
        cursor = self.conn.execute(
            """SELECT DISTINCT target_page FROM page_links"""
        )
        pages_with_inbound = set(row[0] for row in cursor.fetchall())
        data["summary"]["pages_with_inbound"] = len(pages_with_inbound)

        for page in pages_with_inbound:
            data["inbound_links"][page] = self.get_inbound_links(page)

        # Write JSON
        output_path.write_text(json.dumps(data, indent=2))

        data["json_export"] = str(output_path)
        return data

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
