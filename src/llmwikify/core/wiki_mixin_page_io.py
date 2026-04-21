"""Wiki page I/O mixin — page read/write, search, log, index update."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class WikiPageIOMixin:
    """Page read/write, search, log, and index file update."""

    def write_page(self, page_name: str, content: str, page_type: str = None) -> str:
        """Write a wiki page.

        Args:
            page_name: Page name. Can be:
                - Pure name: "Risk Parity" (use with page_type)
                - Path: "concepts/Risk Parity" (legacy, still supported)
            content: Page content markdown.
            page_type: Page type from wiki.md Page Types table.
                Dynamically resolved to directory via _load_page_type_mapping().
                If None and page_name has no '/', writes to wiki/ root.

        Examples:
            write_page("Risk Parity", content, page_type="Concept")
            write_page("concepts/Risk Parity", content)  # legacy
        """
        if ".." in page_name or page_name.startswith("/"):
            raise ValueError(f"Invalid page name: {page_name!r} — path traversal not allowed")

        if page_name.startswith("wiki/"):
            raise ValueError(
                f"page_name should NOT include 'wiki/' prefix. "
                f"Use '{page_name[5:]}' instead of '{page_name}'. "
                f"The 'wiki/' directory is added automatically."
            )

        if page_type:
            type_to_dir = self._load_page_type_mapping()
            
            directory = type_to_dir.get(page_type)
            if directory is None:
                lower_map = {k.lower(): v for k, v in type_to_dir.items()}
                directory = lower_map.get(page_type.lower())
            
            if directory is None:
                directory = page_type.lower()
            
            full_path = f"{directory}/{page_name}"
        elif '/' in page_name:
            full_path = page_name
        else:
            full_path = page_name

        if '\\n' in content or '\\t' in content:
            try:
                content = content.encode('utf-8').decode('unicode_escape')
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass

        page_path = (self.wiki_dir / f"{full_path}.md").resolve()

        try:
            page_path.relative_to(self.wiki_dir.resolve())
        except ValueError:
            raise ValueError(f"Page path escapes wiki/ directory: {full_path!r}")

        page_path.parent.mkdir(parents=True, exist_ok=True)

        if page_path.exists():
            page_path.write_text(content)
            action = "Updated"
        else:
            page_path.write_text(content)
            action = "Created"

        rel_path = str(page_path.relative_to(self.wiki_dir))
        self.index.upsert_page(rel_path[:-3], content, rel_path)

        self._update_index_file()

        return f"{action} page: {full_path}"

    def read_page(self, page_name: str, page_type: str = None) -> dict:
        """Read a wiki page with sink status attached.

        Args:
            page_name: Page name. Can be pure name or path.
            page_type: Page type to resolve directory (same as write_page).
        """
        if page_name.startswith('sink/'):
            page_name = page_name.replace('sink/', '.sink/', 1)

        if page_name.startswith('.sink/') or page_name.startswith('wiki/.sink/'):
            sink_name = page_name.rsplit('/', 1)[-1]
            sink_file = self.sink_dir / sink_name
            if not sink_file.exists():
                return {"error": f"Sink file not found: {page_name}"}
            raw_name = sink_file.name
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

        if page_type and '/' not in page_name:
            type_to_dir = self._load_page_type_mapping()
            directory = type_to_dir.get(page_type)
            if directory is None:
                lower_map = {k.lower(): v for k, v in type_to_dir.items()}
                directory = lower_map.get(page_type.lower())
            if directory is None:
                directory = page_type.lower()
            full_path = f"{directory}/{page_name}"
        else:
            full_path = page_name

        page_path = self.wiki_dir / f"{full_path}.md"

        if not page_path.exists():
            return {"error": f"Page not found: {full_path}"}

        result = {
            "page_name": full_path,
            "content": page_path.read_text(),
            "file": str(page_path),
            "is_sink": False,
        }

        sink_info = self.query_sink.get_info_for_page(full_path)
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

    def append_log(self, operation: str, details: str) -> str:
        """Append entry to wiki log."""
        entry = f"## [{self._now()}] {operation} | {details}\n"
        with open(self.log_file, 'a') as f:
            f.write(entry)
        return "Logged"

    def build_index(self, auto_export: bool = True, output_path: Path | None = None) -> dict:
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

    def _extract_page_summary(self, page_path: Path, max_len: int = 120) -> str:
        """Extract a one-line summary from a wiki page.

        Priority:
        1. YAML frontmatter 'summary' field
        2. First paragraph under ## Summary section (Source pages)
        3. First paragraph after title/frontmatter
        4. Fallback: page title
        """
        try:
            content = page_path.read_text()
        except OSError:
            return ""

        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            for line in fm_text.split('\n'):
                if line.startswith('summary:'):
                    val = line.split(':', 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val if len(val) <= max_len else val[:max_len - 3] + '...'

        summary_match = re.search(r'^## Summary\s*\n(.*?)(?:\n## |\Z)', content, re.MULTILINE | re.DOTALL)
        if summary_match:
            section_text = summary_match.group(1).strip()
            for line in section_text.split('\n'):
                line = line.strip()
                if line and not line.startswith('<!--'):
                    return line if len(line) <= max_len else line[:max_len - 3] + '...'

        body = content
        if fm_match:
            body = content[fm_match.end():]

        lines = body.split('\n')
        in_title = True
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if in_title and stripped.startswith('#'):
                continue
            if in_title:
                in_title = False
            if stripped.startswith('<!--'):
                continue
            clean = re.sub(r'\*\*|\*|`', '', stripped).strip()
            if clean:
                return clean if len(clean) <= max_len else clean[:max_len - 3] + '...'

        title_match = re.match(r'^#\s*(.+)', content)
        if title_match:
            return title_match.group(1).strip()

        return page_path.stem

    def _get_source_analysis_summary(self, page_path: Path) -> dict | None:
        """Extract topics and entities from cached Source analysis.

        Returns dict with:
        - topics: list of topic strings
        - entities: list of entity name strings
        Or None if no cached analysis exists.
        """
        cached = self._get_cached_source_analysis(page_path)
        if not cached:
            return None

        data = cached.get('data', {})
        topics = [t for t in data.get('topics', []) if isinstance(t, str)][:5]
        entities = [e['name'] for e in data.get('entities', []) if isinstance(e, dict) and 'name' in e][:5]

        if not topics and not entities:
            return None

        return {'topics': topics, 'entities': entities}

    def _update_index_file(self) -> None:
        """Update index.md with current wiki contents, summaries, and sink status.

        Groups pages by type (Sources, Concepts, Entities, etc.).
        Each page entry includes:
        - Summary extracted from page content
        - For Source pages: topics and entities from cached analysis
        - Word count and link statistics from SQLite index
        - Sink status if applicable
        """
        dir_labels = {
            'sources': 'Sources',
            'concepts': 'Concepts',
            'entities': 'Entities',
            'comparisons': 'Comparisons',
            'synthesis': 'Synthesis',
            'claims': 'Claims',
        }

        groups: dict[str, list[str]] = {}
        sink_entries = []
        type_counts: dict[str, int] = {}

        for page in sorted(self.wiki_dir.rglob("*.md")):
            page_path = page.relative_to(self.wiki_dir)

            if page_path.parts[0] == '.sink':
                try:
                    sink_content = page.read_text()
                    entries = len(re.findall(
                        r'^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]',
                        sink_content, re.MULTILINE
                    ))
                    last_match = re.search(
                        r'^## \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]',
                        sink_content, re.MULTILINE
                    )
                    last_entry = last_match.group(1) if last_match else "unknown"
                    sink_name = page_path.stem.replace('.sink', '')
                    sink_entries.append(
                        f"- [[{sink_name}]] — {entries} pending updates\n"
                        f"  Last entry: {last_entry}"
                    )
                except OSError:
                    pass
                continue

            if page.name in ("index.md", "log.md"):
                continue

            page_name = str(page_path.with_suffix(''))

            subdir = page_path.parts[0] if len(page_path.parts) > 1 else ''
            if len(page_path.parts) > 1:
                label = dir_labels.get(subdir, subdir.capitalize())
            else:
                label = 'Overview'

            if label not in groups:
                groups[label] = []
                type_counts[label] = 0
            type_counts[label] += 1

            summary = self._extract_page_summary(page)

            analysis_extra = ""
            if subdir == 'sources':
                analysis = self._get_source_analysis_summary(page)
                if analysis:
                    parts = []
                    if analysis['topics']:
                        parts.append(f"📊 Topics: {', '.join(analysis['topics'])}")
                    if analysis['entities']:
                        parts.append(f"👤 Entities: {', '.join(analysis['entities'])}")
                    if parts:
                        analysis_extra = "\n  " + " | ".join(parts)

            stats_extra = ""
            try:
                cursor = self.index.conn.execute(
                    "SELECT word_count FROM pages WHERE page_name = ?",
                    (page_name,)
                )
                row = cursor.fetchone()
                if row and row['word_count']:
                    wc = row['word_count']
                    wc_str = f"{wc / 1000:.1f}k" if wc >= 1000 else str(wc)
                    stats_extra = f" | 📝 {wc_str} words"
            except Exception:
                logger.debug("Failed to get word count for %s", page_name)

            try:
                in_count = len(self.index.get_inbound_links(page_name))
                out_count = len(self.index.get_outbound_links(page_name))
                if in_count > 0 or out_count > 0:
                    link_str = f"🔗 {out_count} out"
                    if in_count > 0:
                        link_str += f" | {in_count} in"
                    stats_extra = f" | {link_str}" + stats_extra
            except Exception:
                logger.debug("Failed to get link counts for %s", page_name)

            sink_marker = ""
            try:
                sink_info = self.query_sink.get_info_for_page(page_name)
                if sink_info['has_sink']:
                    sink_marker = f" 📥 {sink_info['sink_entries']} pending"
            except Exception:
                logger.debug("Failed to get sink info for %s", page_name)

            entry = f"- [[{page_name}]] - {summary}{sink_marker}"
            if analysis_extra or stats_extra:
                entry += f"\n  {analysis_extra}{stats_extra}".lstrip()

            groups[label].append(entry)

        total = sum(type_counts.values())
        type_summary = " | ".join(f"{label}: {count}" for label, count in type_counts.items() if count > 0)

        index_content = (
            f"# Wiki Index\n\n"
            f"Last updated: {self._now()}\n\n"
            f"Total pages: {total}"
            + (f" — {type_summary}" if type_summary else "")
            + f"\n\n---\n\n"
        )

        section_order = ['Sources', 'Concepts', 'Entities', 'Comparisons', 'Synthesis', 'Claims', 'Overview']
        remaining = [k for k in groups if k not in section_order]
        ordered_sections = section_order + sorted(remaining)

        has_content = False
        for section in ordered_sections:
            if section not in groups or not groups[section]:
                continue
            has_content = True
            count = type_counts.get(section, len(groups[section]))
            index_content += f"## {section} ({count})\n\n"
            index_content += '\n\n'.join(groups[section]) + '\n\n'

        if not has_content:
            index_content += "*(No pages yet)*\n\n"

        if sink_entries:
            index_content += "## Pending Sink Buffers 📥\n\n"
            index_content += '\n\n'.join(sink_entries) + '\n'

        self.index_file.write_text(index_content)
