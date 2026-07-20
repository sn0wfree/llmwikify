"""WikiIndex - SQLite FTS5 full-text search and reference tracking."""

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jieba

from .backend import is_path_excluded

logger = logging.getLogger(__name__)


# v0.40.1+ tokenizer: CJK-friendly. Splits on Unicode Letter/Number/Combining/
# Connector categories. NOTE: SQLite's unicode61 still treats contiguous CJK
# text as a single token (each CJK char is its own Unicode Letter, but they
# are NOT separated unless there is punctuation/space). This tokenizer helps
# for mixed Chinese+English content but does NOT solve pure 2-3-char Chinese
# search. The LIKE fallback in `search()` is what actually rescues short CJK
# queries — keep it.
_FTS5_TOKENIZE = 'unicode61 categories \'L* N* Co Mn\' tokenchars \'_\''

# Legacy tokenizer schema string. Detected on startup for auto-migration.
_LEGACY_FTS5_TOKENIZE_MARKERS = ("porter", "unicode61")
_LEGACY_FTS5_TOKENIZE_EXCLUDE = "categories"

# Built-in jieba dictionary paths (shipped with the package).
_DICT_DIR = Path(__file__).parent
_BUILTIN_DICT = _DICT_DIR / "jieba_dict.txt"
_STOP_WORDS_PATH = _DICT_DIR / "jieba_stopwords.txt"


class WikiIndex:
    """Unified index manager for full-text search and reference tracking."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._dict_loaded: bool = False
        self._stop_words: set[str] = set()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                    self._conn.row_factory = sqlite3.Row
                    self.initialize()
        return self._conn

    def initialize(self) -> None:
        """Create all tables if they don't exist.

        v0.40.1+: Auto-detects legacy `porter unicode61` schema and rebuilds
        `pages_fts` with the CJK-friendly tokenizer. Migration is one-shot
        and idempotent.
        """
        # Auto-migrate legacy tokenizer schema BEFORE the CREATE TABLE call.
        # CREATE VIRTUAL TABLE IF NOT EXISTS is a no-op when the table exists,
        # so we must DROP + CREATE ourselves to switch the tokenizer.
        self._migrate_fts_schema_if_needed()

        self.conn.executescript(f"""
            -- FTS5 full-text search (v0.40.1+: CJK-friendly tokenizer + content_seg)
            CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                page_name, content, content_seg,
                tokenize="{_FTS5_TOKENIZE}"
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

    def _get_fts_schema_sql(self) -> str | None:
        """Read the CREATE TABLE SQL for pages_fts from sqlite_master."""
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='pages_fts'"
        ).fetchone()
        return row[0] if row else None

    def _needs_migration(self, schema_sql: str) -> bool:
        """True if the current pages_fts needs a schema upgrade.

        Triggers on:
        - Legacy tokenizer (`porter unicode61`, no `categories` clause)
        - Missing ``content_seg`` column (needed for jieba-segmented search)
        """
        has_categories = _LEGACY_FTS5_TOKENIZE_EXCLUDE in schema_sql
        has_content_seg = "content_seg" in schema_sql
        return (not has_categories) or (not has_content_seg)

    def _migrate_fts_schema_if_needed(self) -> None:
        """Drop + rebuild pages_fts with the new tokenizer if legacy detected.

        Refills from the `pages` metadata table (which stores raw content);
        pages without stored content are silently skipped and will be
        reindexed on next `upsert_page` call.
        """
        schema_sql = self._get_fts_schema_sql()
        if schema_sql is None:
            return  # first init — let CREATE TABLE handle it
        if not self._needs_migration(schema_sql):
            return  # already on new tokenizer

        logger.info(
            "WikiIndex: schema upgrade needed; migrating to "
            "CJK-friendly tokenizer + content_seg column"
        )
        try:
            self._ensure_dict()
            self.conn.executescript(f"""
                DROP TABLE IF EXISTS pages_fts;
                CREATE VIRTUAL TABLE pages_fts USING fts5(
                    page_name, content, content_seg,
                    tokenize="{_FTS5_TOKENIZE}"
                );
            """)
            # Refill from the metadata table.
            # `pages` only has metadata (lengths/counts) — content lives in
            # .md files. Try a few common locations under the wiki root;
            # skip rows that we can't find; they will be picked up by the
            # next upsert or by running `llmwikify build-index`.
            cursor = self.conn.execute(
                "SELECT page_name, file_path FROM pages"
            )
            migrated = 0
            skipped = 0
            wiki_root = self.db_path.parent
            candidate_roots = (wiki_root, wiki_root / "wiki", wiki_root / "raw")
            for row in cursor.fetchall():
                page_name = row["page_name"]
                file_path = row["file_path"]
                if not file_path:
                    skipped += 1
                    continue
                rel = Path(file_path)
                md_file = None
                for root in candidate_roots:
                    candidate = root / rel
                    if candidate.exists():
                        md_file = candidate
                        break
                if md_file is None:
                    skipped += 1
                    continue
                content = md_file.read_text(errors="replace")
                fts_content = self._segment(content) if self._should_segment(content) else content
                self.conn.execute(
                    "INSERT INTO pages_fts (page_name, content, content_seg) "
                    "VALUES (?, ?, ?)",
                    (page_name, content, fts_content),
                )
                migrated += 1
            self.conn.commit()
            logger.info(
                "WikiIndex: migrated %d pages to new schema; "
                "%d skipped (run `llmwikify build-index` to refill)",
                migrated,
                skipped,
            )
        except Exception as e:
            logger.error("WikiIndex: FTS5 schema migration failed: %s", e)
            # Don't raise — keep the connection usable; search will fall back
            # to LIKE if the legacy tokenizer still works.

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

    # ── jieba dict lazy loading ──────────────────────────────────────

    def _ensure_dict(self) -> None:
        """Lazy-load jieba dictionary: built-in → stop words → user dict."""
        if self._dict_loaded:
            return
        if _BUILTIN_DICT.exists():
            jieba.load_userdict(str(_BUILTIN_DICT))
        if _STOP_WORDS_PATH.exists():
            self._stop_words = {
                line.strip()
                for line in _STOP_WORDS_PATH.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            }
        wiki_root = self.db_path.parent
        for subpath in (".wiki", ".wiki/jieba.dict", ".wiki/jieba.pmi.dict"):
            p = wiki_root / subpath
            if p.suffix == ".dict" and p.exists():
                jieba.load_userdict(str(p))
        self._dict_loaded = True

    # ── CJK detection & segmentation ────────────────────────────────

    @staticmethod
    def _should_segment(text: str) -> bool:
        """True if CJK characters make up >= 5% of the text."""
        if not text:
            return False
        cjk = sum(
            1 for c in text
            if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f'
        )
        return cjk / len(text) >= 0.05

    def _segment(self, text: str) -> str:
        """Segment text with jieba and join with spaces."""
        words = jieba.cut(text)
        if self._stop_words:
            words = (w for w in words if w not in self._stop_words)
        return " ".join(words)

    @staticmethod
    def _extract_snippet(content: str, query: str, context: int = 80) -> str:
        """Extract centred snippet around first match with **highlight**."""
        idx = content.lower().find(query.lower())
        if idx == -1:
            return content[:200]
        start = max(0, idx - context)
        end = min(len(content), idx + len(query) + context)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        snippet = content[start:end]
        snippet = re.sub(
            re.escape(query), r'**\g<0>**', snippet, flags=re.IGNORECASE
        )
        return f"{prefix}{snippet}{suffix}"

    # ── Core operations ─────────────────────────────────────────────

    def upsert_page(self, page_name: str, content: str, file_path: str = "") -> None:
        """Insert or update a page in all indexes."""
        self._ensure_dict()

        # 1. Update FTS5 — raw in content, segmented in content_seg
        self._execute("DELETE FROM pages_fts WHERE page_name = ?", (page_name,))
        fts_content = self._segment(content) if self._should_segment(content) else content
        self._execute(
            "INSERT INTO pages_fts (page_name, content, content_seg) VALUES (?, ?, ?)",
            (page_name, content, fts_content)
        )

        # 2. Parse links from content
        links = self._parse_links(content, page_name, file_path)

        # 3. Update links
        self._execute("DELETE FROM page_links WHERE source_page = ?", (page_name,))
        if links:
            self._executemany(
                """INSERT INTO page_links (source_page, target_page, section, display_text, file_path)
                   VALUES (?, ?, ?, ?, ?)""",
                [(link['source_page'], link['target'], link['section'], link['display'], link['file_path']) for link in links]
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

    def search(self, query: str, limit: int = 10, backend: str = "fts5") -> list[dict]:
        """Full-text search with ranking and highlighted snippets.

        Args:
            query: Search query string
            limit: Maximum number of results
            backend: Search backend - "fts5" (default) or "qmd"

        Returns:
            List of search results with page_name, score, and snippet

        Fallback chain:
        1. QMD if requested (currently a no-op until QMD ships)
        2. jieba-segmented FTS5 MATCH on content_seg with BM25 ranking
        3. LIKE + TF scoring fallback if FTS5 returns 0 rows or errors
        """
        self._ensure_dict()

        # Try QMD if requested and available
        if backend == "qmd":
            qmd_results = self._try_qmd_search(query, limit)
            if qmd_results:
                return qmd_results

        # Segment query for FTS5 if CJK
        query_seg = self._segment(query) if self._should_segment(query) else query

        # FTS5 match on segmented content
        try:
            cursor = self.conn.execute(
                """SELECT page_name,
                          snippet(pages_fts, 1, '**', '**', '...', 32) as snippet,
                          bm25(pages_fts) as score
                   FROM pages_fts
                   WHERE content_seg MATCH ?
                   ORDER BY score
                   LIMIT ?""",
                (query_seg, limit)
            )
        except sqlite3.OperationalError:
            return self._like_search(query, limit, mode="fts5-syntax-fallback")

        rows = cursor.fetchall()
        if not rows:
            like_results = self._like_search(query, limit, mode="fts5-zero-fallback")
            if like_results:
                return like_results

        return [
            {
                "page_name": row['page_name'],
                "score": abs(row['score']),
                "snippet": row['snippet'],
                "mode": "fts5",
            }
            for row in rows
        ]

    def _like_search(self, query: str, limit: int, mode: str = "fts5") -> list[dict]:
        """LIKE fallback with simple TF (term frequency) scoring.

        Used when FTS5 MATCH syntax errors or returns zero rows.
        Results are ranked by TF descending; snippet from raw content.
        """
        cursor = self.conn.execute(
            "SELECT page_name, content FROM pages_fts WHERE content LIKE ?",
            (f"%{query}%",)
        )
        scored = []
        for row in cursor.fetchall():
            content = row['content']
            tf = content.count(query)
            scored.append({
                "page_name": row['page_name'],
                "score": tf,
                "snippet": self._extract_snippet(content, query),
                "mode": mode,
            })
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:limit]

    def _try_qmd_search(self, query: str, limit: int, mode: str = "hybrid") -> list[dict]:
        """Attempt QMD search if the QMD module is available.

        Returns:
            List of results if QMD is available, empty list otherwise
        """
        try:
            from ..search.qmd_index import QmdIndex
            qmd = QmdIndex(self.db_path.parent, config=None)
            if qmd.is_available():
                return qmd.search(query, limit=limit, mode=mode)
        except Exception:
            logger.debug("QMD search unavailable, falling back to empty results")
        return []

    def get_qmd_recommendation(self) -> dict:
        """Check if QMD should be recommended based on wiki size.

        Returns:
            Dict with recommendation status and message
        """
        page_count = self.get_page_count()
        try:
            from ..search.qmd_index import QmdIndex
            qmd = QmdIndex(self.db_path.parent, config=None)
            return qmd.get_recommendation(page_count)
        except Exception:
            return {
                "recommended": page_count >= 1000,
                "page_count": page_count,
                "threshold": 1000,
            }

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

    def count_inbound_for_pages(self, page_names: list[str]) -> dict[str, int]:
        """Batch: count inbound links for multiple pages in one query.

        Returns a dict mapping page_name → inbound link count.
        Pages with zero inbound links are omitted from the result.
        """
        if not page_names:
            return {}
        placeholders = ",".join("?" * len(page_names))
        cursor = self.conn.execute(
            f"SELECT target_page, COUNT(*) FROM page_links "
            f"WHERE target_page IN ({placeholders}) GROUP BY target_page",
            page_names,
        )
        return {row[0]: row[1] for row in cursor.fetchall()}

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
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def get_link_count(self) -> int:
        """Get total number of links."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM page_links")
        result = cursor.fetchone()
        return int(result[0]) if result else 0

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
        md_files = [p for p in wiki_dir.rglob("*.md") if not is_path_excluded(p)]
        total = len(md_files)

        for i, md_file in enumerate(md_files):
            if (i + 1) % batch_size == 0 or (i + 1) == total:
                elapsed = time.time() - start_time
                speed = (i + 1) / elapsed if elapsed > 0 else 0
                print(f"\r  Processing: {i+1}/{total} ({(i+1)/total*100:.1f}%) - {speed:.1f} files/sec", end='', flush=True)

            content = md_file.read_text()
            rel_path = str(md_file.relative_to(wiki_dir))
            page_name = rel_path[:-3]  # e.g., "concepts/Factor Investing"

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

    def export_json(self, output_path: Path) -> dict[str, Any]:
        """Export reference index to JSON."""
        # Build data structure
        data: dict[str, Any] = {
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
        pages_with_outbound = {row[0] for row in cursor.fetchall()}
        data["summary"]["pages_with_outbound"] = len(pages_with_outbound)

        for page in pages_with_outbound:
            data["outbound_links"][page] = self.get_outbound_links(page)

        # Get all inbound links
        cursor = self.conn.execute(
            """SELECT DISTINCT target_page FROM page_links"""
        )
        pages_with_inbound = {row[0] for row in cursor.fetchall()}
        data["summary"]["pages_with_inbound"] = len(pages_with_inbound)

        for page in pages_with_inbound:
            data["inbound_links"][page] = self.get_inbound_links(page)

        # Write JSON
        output_path.write_text(json.dumps(data, indent=2))

        data["json_export"] = str(output_path)
        return data

    def resolve_by_name(self, page_name: str) -> str | None:
        """Resolve page name to file_path via exact match in SQLite index.

        Args:
            page_name: Full relative path (e.g., "concepts/Factor Investing").
                       Bare names (e.g., "Factor Investing") will NOT match
                       pages stored with directory prefix.

        Returns:
            Relative file path (e.g., "concepts/Factor Investing.md") or None.
        """
        cursor = self.conn.execute(
            "SELECT file_path FROM pages WHERE page_name = ? LIMIT 1",
            (page_name,)
        )
        row = cursor.fetchone()
        return row['file_path'] if row else None

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
