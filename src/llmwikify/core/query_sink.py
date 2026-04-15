"""Query Sink management — handles pending query answers for later review."""

import re
from datetime import datetime, timezone
from pathlib import Path


class QuerySink:
    """Manages query sink buffers for pending wiki updates.

    When a query answer is similar to an existing page, it goes to a sink
    file instead of creating a duplicate. The sink accumulates entries
    for later review and merging during lint.
    """

    def __init__(self, root: Path, wiki_dir: Path) -> None:
        self.root = root.resolve()
        self.wiki_dir = wiki_dir
        self.sink_dir = wiki_dir / '.sink'

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def get_info_for_page(self, page_name: str) -> dict:
        """Get sink status for a wiki page."""
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            return {"has_sink": False, "sink_entries": 0}
        try:
            content = sink_file.read_text()
            entries = len(re.findall(
                r'^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]', content, re.MULTILINE
            ))
            return {"has_sink": True, "sink_entries": entries}
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
        entries = re.findall(
            r'## \[\d{4}-\d{2}-\d{2}[^]]*\] Query: (.+?)\n', content
        )
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
                    "Review against previous entries before merging."
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

    def _check_sink_duplicate(
        self, sink_file: Path, new_answer: str,
    ) -> str | None:
        if not sink_file.exists():
            return None
        content = sink_file.read_text()
        entries = re.findall(
            r'## \[\d{4}-\d{2}-\d{2}[^]]*\] Query: .+?\n\n(.+?)'
            r'(?:\n###|\n>|\n---\n\n## \[|$)',
            content, re.DOTALL,
        )
        new_answer_clean = new_answer.strip()
        for entry in entries:
            entry_clean = entry.strip()
            if not entry_clean:
                continue
            similarity = self._query_similarity(
                new_answer_clean[:200], entry_clean[:200]
            )
            if similarity > 0.7:
                return (
                    f"High similarity ({similarity:.0%}) with a previous sink entry. "
                    f"Consider using merge_or_replace='replace' to consolidate."
                )
        return None

    def append_to_sink(
        self, page_name: str, query: str, answer: str,
        source_pages: list[str], raw_sources: list[str],
    ) -> str:
        """Append a query answer to the sink file. Returns path relative to root."""
        sink_file = self._find_or_create_sink_file(page_name)
        suggestions = self._generate_sink_suggestions(
            query, answer, source_pages, raw_sources, page_name,
        )
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
        formal_path = self.wiki_dir / f"{page_name}.md"
        if formal_path.exists():
            self._update_page_sink_meta(formal_path, sink_file)
        return str(sink_file.relative_to(self.root))

    def read(self, page_name: str) -> dict:
        """Read all pending entries from a query sink file."""
        sink_file = self.sink_dir / f"{page_name}.sink.md"
        if not sink_file.exists():
            return {
                "status": "empty", "page_name": page_name,
                "entries": [], "message": "No sink file found",
            }
        content = sink_file.read_text()
        entries = []
        parts = re.split(r'^---\n\n## \[', content, flags=re.MULTILINE)
        for part in parts[1:]:
            match = re.match(
                r'(\d{4}-\d{2}-\d{2}[^]]*)\] Query: (.+?)\n\n(.+)',
                part, re.DOTALL,
            )
            if match:
                entries.append({
                    "timestamp": match.group(1).strip(),
                    "query": match.group(2).strip(),
                    "answer": match.group(3).strip(),
                })
        return {
            "status": "ok",
            "page_name": page_name,
            "file": str(sink_file.relative_to(self.root)),
            "entries": entries,
            "total_entries": len(entries),
        }

    def clear(self, page_name: str) -> dict:
        """Clear processed entries from a query sink file."""
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
                                now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                                new_lines.append(f'last_merged: {now_date}')
                                has_last_merged = True
                            else:
                                new_lines.append(line)
                        if not has_last_merged:
                            now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                            new_lines.append(f'last_merged: {now_date}')
                        formal_path.write_text(
                            f'---\n{chr(10).join(new_lines)}\n---{body}'
                        )
            except OSError:
                pass
        return {"status": "cleared", "page_name": page_name}

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
            entries = len(re.findall(
                r'^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]',
                content, re.MULTILINE,
            ))
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
