"""Query Sink management — content-addressable storage with deduplication."""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


class QuerySink:
    """Manages query sink buffers with content-addressable storage.

    Sink files use a two-section format:
    - Content Store: unique answers stored once, keyed by hash
    - Entry Log: all entries referencing Content Store by hash

    Duplicate and near-duplicate answers are compressed automatically.
    """

    HASH_LEN = 8               # SHA-256 前 8 位 (42.9 亿空间)
    SIMILARITY_THRESHOLD = 0.92  # near-duplicate 阈值

    def __init__(self, root: Path, wiki_dir: Path) -> None:
        self.root = root.resolve()
        self.wiki_dir = wiki_dir
        self.sink_dir = wiki_dir / '.sink'

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    @staticmethod
    def _normalize_for_hash(text: str) -> str:
        """Normalize text to eliminate format differences."""
        text = text.strip()
        text = re.sub(r'\s+', ' ', text)       # collapse whitespace
        text = re.sub(r'[""\u201c\u201d\u300c\u300d]', '"', text)
        text = re.sub(r"[''\u2018\u2019]", "'", text)
        text = re.sub(r'[\u2014\u2013\u2212]', '-', text)
        return text

    def _content_hash(self, text: str) -> str:
        """Compute normalized SHA-256 hash (first HASH_LEN hex chars)."""
        normalized = self._normalize_for_hash(text)
        return hashlib.sha256(normalized.encode()).hexdigest()[:self.HASH_LEN]

    @staticmethod
    def _jaccard_similarity(text1: str, text2: str) -> float:
        """Compute Jaccard similarity of word sets."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)

    def _find_similar_hash(self, content_store: dict, new_answer: str) -> str | None:
        """Find a hash in content_store with similarity >= threshold."""
        new_clean = self._normalize_for_hash(new_answer).strip()
        for hash_val, existing in content_store.items():
            existing_clean = self._normalize_for_hash(existing).strip()
            sim = self._jaccard_similarity(new_clean, existing_clean)
            if sim >= self.SIMILARITY_THRESHOLD:
                return hash_val
        return None

    # -- Parsing methods --

    def _parse_content_store(self, content: str) -> dict[str, str]:
        """Parse Content Store section → {hash: text}."""
        store = {}
        pattern = (
            r'### ([a-f0-9]{8}) — (\d{4}-\d{2}-\d{2})\n'
            r'(.*?)(?=\n### [a-f0-9]{8} — |\n+---\n+## Entry Log|\Z)'
        )
        for match in re.finditer(pattern, content, re.DOTALL):
            store[match.group(1)] = match.group(3).strip()
        return store

    def _parse_entry_log(self, content: str) -> list[dict]:
        """Parse Entry Log table → [{num, timestamp, query, hash, note}]."""
        entries = []
        pattern = (
            r'\| (\d+) \| (.+?) \| (.+?) \| `([a-f0-9]{8})` \| (.+?) \|'
        )
        for match in re.finditer(pattern, content):
            entries.append({
                "num": int(match.group(1)),
                "timestamp": match.group(2).strip(),
                "query": match.group(3).strip(),
                "hash": match.group(4),
                "note": match.group(5).strip().rstrip('`').strip(),
            })
        return entries

    def _count_entries(self, content: str) -> int:
        """Count Entry Log rows (handles both new and old format)."""
        if "## Entry Log" in content:
            return len(self._parse_entry_log(content))
        # Fallback for legacy format
        return len(re.findall(
            r'^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]',
            content, re.MULTILINE
        ))

    # -- Public interface --

    def get_info_for_page(self, page_name: str) -> dict:
        """Get sink status for a wiki page."""
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            return {"has_sink": False, "sink_entries": 0}
        try:
            content = sink_file.read_text()
            count = self._count_entries(content)
            return {"has_sink": True, "sink_entries": count}
        except OSError:
            return {"has_sink": False, "sink_entries": 0}

    def _find_or_create_sink_file(self, page_name: str) -> Path:
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            content = (
                f"---\n"
                f"formal_page: \"{page_name}\"\n"
                f"formal_path: wiki/{page_name}.md\n"
                f"created: {self._now()}\n"
                f"unique_count: 0\n"
                f"entry_count: 0\n"
                f"last_updated: {self._now()}\n"
                f"---\n\n"
                f"# Query Sink: {page_name.replace('Query: ', '')}\n\n"
                f"> Pending entries for [[{page_name}]]\n\n"
                f"---\n\n"
                f"## Content Store\n\n"
                f"*(No unique answers stored yet)*\n\n"
                f"---\n\n"
                f"## Entry Log\n\n"
                f"*(No entries yet)*\n"
            )
            sink_file.write_text(content)
            formal_path = self.wiki_dir / f"{page_name}.md"
            if formal_path.exists():
                self._update_page_sink_meta(formal_path, sink_file)
        else:
            # Migrate legacy format if needed
            self._migrate_legacy_sink(sink_file)
        return sink_file

    def _update_page_sink_meta(self, page_path: Path, sink_file: Path) -> None:
        """Update formal page frontmatter with sink_path."""
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
                            new_lines.append(
                                f'sink_path: {str(sink_file.relative_to(self.root))}'
                            )
                            has_sink_path = True
                        elif line.startswith('sink_entries:') or line.startswith('last_merged:'):
                            continue
                        else:
                            new_lines.append(line)
                    if not has_sink_path:
                        new_lines.append(
                            f'sink_path: {str(sink_file.relative_to(self.root))}'
                        )
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
        except OSError:
            pass

    def _migrate_legacy_sink(self, sink_file: Path) -> None:
        """Migrate old format sink file to new Content Store + Entry Log format."""
        content = sink_file.read_text()
        if "## Content Store" in content:
            return  # Already in new format

        # Parse old format entries
        old_entries = re.findall(
            r'## \[(\d{4}-\d{2}-\d{2}[^]]*)\] Query: (.+?)\n\n(.+?)'
            r'(?=\n> ⚠️|\n### 💡|\n### Sources\n|'
            r'\n---\n\n## \[|$)',
            content, re.DOTALL,
        )

        if not old_entries:
            # No entries, just rewrite header
            header_match = re.match(r'(---\n.*?---)', content, re.DOTALL)
            if header_match:
                header = header_match.group(1)
                # Parse existing frontmatter
                fm_content = header[3:-3].strip()
                fm_dict = {}
                for line in fm_content.split('\n'):
                    if ':' in line:
                        key, _, val = line.partition(':')
                        fm_dict[key.strip()] = val.strip().strip('"')

                new_content = (
                    f"{header}\n\n"
                    f"# Query Sink: {fm_dict.get('formal_page', 'Unknown').replace('Query: ', '')}\n\n"
                    f"> Pending entries for [[{fm_dict.get('formal_page', 'Unknown')}]]\n\n"
                    f"---\n\n"
                    f"## Content Store\n\n"
                    f"*(No unique answers stored yet)*\n\n"
                    f"---\n\n"
                    f"## Entry Log\n\n"
                    f"*(No entries yet)*\n"
                )
                sink_file.write_text(new_content)
            return

        content_store = {}
        entry_log = []

        for i, (ts, query, answer) in enumerate(old_entries):
            # Clean answer: remove suggestions and source sections
            answer_clean = re.sub(
                r'\n### 💡 Suggestions.*', '', answer, flags=re.DOTALL
            )
            answer_clean = re.sub(
                r'\n### Sources.*', '', answer_clean, flags=re.DOTALL
            )
            answer_clean = answer_clean.strip()

            h = self._content_hash(answer_clean)

            if h not in content_store:
                date_short = ts[:10] if len(ts) >= 10 else "unknown"
                content_store[h] = answer_clean
                content_store[f"_date_{h}"] = date_short

            note = "—"
            entry_log.append({
                "num": i + 1,
                "timestamp": ts.strip(),
                "query": query.strip(),
                "hash": h,
                "note": note,
            })

        # Parse existing frontmatter
        header_match = re.match(r'(---\n.*?---)', content, re.DOTALL)
        if header_match:
            header = header_match.group(1)
            fm_content = header[3:-3].strip()
            fm_dict = {}
            for line in fm_content.split('\n'):
                if ':' in line:
                    key, _, val = line.partition(':')
                    fm_dict[key.strip()] = val.strip().strip('"')

            formal_page = fm_dict.get('formal_page', 'Unknown')

            # Build new format
            lines = [header, ""]
            lines.append(f"# Query Sink: {formal_page.replace('Query: ', '')}")
            lines.append("")
            lines.append(f"> Pending entries for [[{formal_page}]]")
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("## Content Store")
            lines.append("")

            for h, text in content_store.items():
                if h.startswith("_date_"):
                    continue
                date = content_store.get(f"_date_{h}", "unknown")
                lines.append(f"### {h} — {date}")
                lines.append(text)
                lines.append("")

            lines.append("---")
            lines.append("")
            lines.append("## Entry Log")
            lines.append("")
            lines.append("| # | Timestamp | Query | Answer Hash | Note |")
            lines.append("|---|-----------|-------|-------------|------|")

            for entry in entry_log:
                lines.append(
                    f"| {entry['num']} | {entry['timestamp']} | {entry['query']} | "
                    f"`{entry['hash']}` | {entry['note']} |"
                )

            lines.append("")
            sink_file.write_text("\n".join(lines))

    @staticmethod
    def _extract_topics(text: str) -> set:
        stop_words = {
            "this", "that", "these", "those", "with", "from", "have", "been",
            "were", "will", "also", "each", "which", "their", "there", "about",
            "through", "during", "before", "after", "above", "below", "between",
            "into", "against", "among", "within", "without",
        }
        return {
            w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', text)
            if w.lower() not in stop_words
        }

    def _detect_content_gaps(self, answer: str, page_name: str) -> list[str]:
        suggestions: list[str] = []
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
        self, source_pages: list[str], raw_sources: list[str], page_name: str,
    ) -> list[str]:
        suggestions: list[str] = []
        formal_path = self.wiki_dir / f"{page_name}.md"
        formal_sources_wiki: set = set()
        formal_sources_raw: set = set()
        if formal_path.exists():
            content = formal_path.read_text()
            formal_sources_wiki = set(re.findall(r'\[\[(.*?)\]\]', content))
            formal_sources_raw = set(
                re.findall(r'\[Source:[^\]]*\]\((raw/[^\)]+)\)', content)
            )
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

    @staticmethod
    def _query_similarity(q1: str, q2: str) -> float:
        stop = {
            "what", "is", "the", "a", "an", "how", "do", "does", "why", "can",
            "tell", "me", "about", "explain", "describe", "compare",
        }
        words1 = {
            w.lower() for w in q1.split() if w.lower() not in stop and len(w) > 2
        }
        words2 = {
            w.lower() for w in q2.split() if w.lower() not in stop and len(w) > 2
        }
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)

    def _analyze_query_patterns(self, query: str, page_name: str) -> list[str]:
        suggestions: list[str] = []
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            return suggestions
        content = sink_file.read_text()
        entry_log = self._parse_entry_log(content)
        entries = [e['query'] for e in entry_log]
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

    def _suggest_knowledge_growth(self, answer: str, page_name: str) -> list[str]:
        suggestions: list[str] = []
        formal_path = self.wiki_dir / f"{page_name}.md"
        if formal_path.exists():
            formal_content = formal_path.read_text()
            formal_words = {
                w.lower() for w in re.findall(r'\b[A-Z][a-z]{3,}\b', formal_content)
            }
            answer_words = {
                w.lower() for w in re.findall(r'\b[A-Z][a-z]{3,}\b', answer)
            }
            common = {
                "this", "that", "with", "from", "have", "been", "were", "will",
                "also", "each",
            }
            new_concepts = answer_words - formal_words - common
            if len(new_concepts) >= 3:
                suggestions.append(
                    f"New Concepts: Mentions {', '.join(sorted(new_concepts)[:3])} "
                    f"not in formal page. Consider if any deserve their own page."
                )
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if sink_file.exists():
            negation_words = re.findall(
                r'\b(not|never|no longer|however|contrary|contradicts?)\b',
                answer, re.IGNORECASE,
            )
            if negation_words:
                suggestions.append(
                    "Possible Contradiction: This answer contains negation words. "
                    "Review against previous entries before updating."
                )
        return suggestions

    def _generate_sink_suggestions(
        self, query: str, answer: str,
        source_pages: list[str], raw_sources: list[str], page_name: str,
    ) -> list[str]:
        suggestions: list[str] = []
        suggestions.extend(self._detect_content_gaps(answer, page_name))
        suggestions.extend(
            self._suggest_source_improvements(source_pages, raw_sources, page_name)
        )
        suggestions.extend(self._analyze_query_patterns(query, page_name))
        suggestions.extend(self._suggest_knowledge_growth(answer, page_name))
        return suggestions

    def append_to_sink(
        self, page_name: str, query: str, answer: str,
        source_pages: list[str], raw_sources: list[str],
    ) -> str:
        """Append a query answer to the sink file with content-addressable dedup."""
        sink_file = self._find_or_create_sink_file(page_name)
        content = sink_file.read_text()

        content_store = self._parse_content_store(content)
        entry_log = self._parse_entry_log(content)

        answer_clean = answer.strip()
        answer_hash = self._content_hash(answer_clean)

        note = "—"

        if answer_hash in content_store:
            note = "duplicate"
        else:
            similar_hash = self._find_similar_hash(content_store, answer_clean)
            if similar_hash:
                answer_hash = similar_hash
                ref_num = next(
                    (e['num'] for e in entry_log if e['hash'] == similar_hash),
                    0
                )
                note = f"near-dup of #{ref_num}" if ref_num else "near-dup"
            else:
                content_store[answer_hash] = answer_clean

        entry_num = len(entry_log) + 1
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        entry_log.append({
            "num": entry_num,
            "timestamp": timestamp,
            "query": query,
            "hash": answer_hash,
            "note": note,
        })

        # Rebuild entire file from parsed data
        new_content = self._rebuild_sink_file(content, content_store, entry_log, page_name)
        sink_file.write_text(new_content)

        formal_path = self.wiki_dir / f"{page_name}.md"
        if formal_path.exists():
            self._update_page_sink_meta(formal_path, sink_file)

        return str(sink_file.relative_to(self.root))

    def _rebuild_sink_file(
        self, original: str, content_store: dict, entry_log: list, page_name: str,
    ) -> str:
        """Rebuild sink file from parsed data, preserving original header/metadata."""
        # Extract original frontmatter
        fm_match = re.match(r'(---\n.*?---\n)', original, re.DOTALL)
        if fm_match:
            header = fm_match.group(1)
        else:
            header = f"---\nformal_page: \"{page_name}\"\n---\n"

        # Update frontmatter counts
        unique_count = len(content_store)
        entry_count = len(entry_log)
        now_str = self._now()

        def update_fm(m):
            fm = m.group(1)
            lines = fm.split('\n')
            new_lines = []
            seen_unique = seen_entry = seen_updated = False
            for line in lines:
                if line.startswith('unique_count:'):
                    new_lines.append(f"unique_count: {unique_count}")
                    seen_unique = True
                elif line.startswith('entry_count:'):
                    new_lines.append(f"entry_count: {entry_count}")
                    seen_entry = True
                elif line.startswith('last_updated:'):
                    new_lines.append(f"last_updated: {now_str}")
                    seen_updated = True
                else:
                    new_lines.append(line)
            if not seen_unique:
                new_lines.insert(1, f"unique_count: {unique_count}")
            if not seen_entry:
                new_lines.insert(1, f"entry_count: {entry_count}")
            if not seen_updated:
                new_lines.insert(1, f"last_updated: {now_str}")
            return '---\n' + '\n'.join(new_lines) + '\n---\n'

        header = re.sub(r'^(---\n.*?---\n)', update_fm, header, count=1, flags=re.DOTALL)

        # Extract title line (preserve original if possible)
        title_match = re.search(r'^# Query Sink: (.+)$', original, re.MULTILINE)
        title = title_match.group(1) if title_match else page_name.replace('Query: ', '')

        # Extract description line
        desc_match = re.search(r'^> (.+)$', original, re.MULTILINE)
        desc = desc_match.group(1) if desc_match else f"Pending entries for [[{page_name}]]"

        # Build body
        lines = [""]
        lines.append(f"# Query Sink: {title}")
        lines.append("")
        lines.append(f"> {desc}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Content Store")
        lines.append("")

        if content_store:
            for h, text in content_store.items():
                # Try to find date from original content
                date_match = re.search(
                    rf'### {h} — (\d{{4}}-\d{{2}}-\d{{2}})', original
                )
                date = date_match.group(1) if date_match else datetime.now(timezone.utc).strftime("%Y-%m-%d")
                lines.append(f"### {h} — {date}")
                lines.append(text)
                lines.append("")
        else:
            lines.append("*(No unique answers stored yet)*")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Entry Log")
        lines.append("")

        if entry_log:
            lines.append("| # | Timestamp | Query | Answer Hash | Note |")
            lines.append("|---|-----------|-------|-------------|------|")
            for entry in entry_log:
                lines.append(
                    f"| {entry['num']} | {entry['timestamp']} | {entry['query']} | "
                    f"`{entry['hash']}` | {entry['note']} |"
                )
            lines.append("")
        else:
            lines.append("*(No entries yet)*")
            lines.append("")

        return header + "\n".join(lines)

    def read(self, page_name: str) -> dict:
        """Read all entries from a query sink file, resolving hash references."""
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            return {
                "status": "empty", "page_name": page_name,
                "entries": [], "message": "No sink file found",
            }

        content = sink_file.read_text()

        # Migrate legacy format if needed
        if "## Content Store" not in content:
            self._migrate_legacy_sink(sink_file)
            content = sink_file.read_text()

        content_store = self._parse_content_store(content)
        entry_log = self._parse_entry_log(content)

        entries = []
        for entry in entry_log:
            answer_text = content_store.get(entry["hash"], "[content not found]")
            entries.append({
                "timestamp": entry["timestamp"],
                "query": entry["query"],
                "answer": answer_text,
                "hash": entry["hash"],
                "note": entry["note"],
            })

        return {
            "status": "ok",
            "page_name": page_name,
            "file": str(sink_file.relative_to(self.root)),
            "entries": entries,
            "total_entries": len(entries),
            "unique_count": len(content_store),
        }

    def status(self) -> dict:
        """Overview of all query sinks with entry counts and urgency."""
        if not self.sink_dir.exists():
            return {
                "total_entries": 0, "total_sinks": 0,
                "urgent_count": 0, "sinks": [],
                "message": "No sink directory",
            }
        sinks = []
        total_entries = 0
        now = datetime.now(timezone.utc)
        for sink_file in sorted(self.sink_dir.glob("*.sink.md")):
            page_name = sink_file.stem.replace('.sink', '')
            content = sink_file.read_text()

            # Handle both old and new format
            if "## Entry Log" in content:
                entry_log = self._parse_entry_log(content)
                entry_count = len(entry_log)
                # Get newest entry timestamp
                newest_ts = None
                oldest_ts = None
                for entry in entry_log:
                    ts = entry['timestamp']
                    # Extract date portion
                    date_part = ts[:10] if len(ts) >= 10 else None
                    if date_part:
                        if newest_ts is None or ts > newest_ts:
                            newest_ts = ts
                        if oldest_ts is None or ts < oldest_ts:
                            oldest_ts = ts
                newest = newest_ts[:10] if newest_ts else None
                oldest = oldest_ts[:10] if oldest_ts else None
            else:
                # Legacy format
                entry_count = self._count_entries(content)
                dates = re.findall(
                    r'^## \[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\]',
                    content, re.MULTILINE,
                )
                oldest = min(dates) if dates else None
                newest = max(dates) if dates else None

            days_old = 0
            urgency = "ok"
            if newest:
                try:
                    newest_dt = datetime.strptime(
                        newest, "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)
                    days_old = (now - newest_dt).days
                except (ValueError, TypeError):
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
                "entry_count": entry_count,
                "oldest_entry": oldest,
                "newest_entry": newest,
                "days_since_last_entry": days_old,
                "urgency": urgency,
            })
            total_entries += entry_count
        sinks.sort(key=lambda x: x['entry_count'], reverse=True)
        urgent_count = sum(1 for s in sinks if s['urgency'] != 'ok')
        return {
            "total_entries": total_entries,
            "total_sinks": len(sinks),
            "urgent_count": urgent_count,
            "sinks": sinks,
        }
