"""Wiki query mixin — query page creation, similarity matching, synthesis."""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from .constants import (
    MAX_KEY_TOPICS,
    MAX_QUERY_TOPIC_LENGTH,
    MIN_KEYWORD_LENGTH,
    SIMILARITY_THRESHOLD,
    STOP_WORDS,
)

logger = logging.getLogger(__name__)


class WikiQueryMixin:
    """Query handling: page creation, similarity matching, sink integration."""

    def synthesize_query(
        self,
        query: str,
        answer: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
        page_name: str | None = None,
        auto_link: bool = True,
        auto_log: bool = True,
        mode: str = "sink",
        merge_or_replace: str | None = None,
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
            mode: Strategy when similar page exists:
                "sink" (default) — append to sink buffer (duplicates auto-compressed)
                "update" — overwrite the formal page with comprehensive answer
            merge_or_replace: Deprecated. Use `mode` instead.
                Maps: "sink"→"sink", "merge"/"replace"→"update".

        Returns:
            Dict with status, page_name, page_path, sources info, hint about duplicates.
        """
        source_pages = source_pages or []
        raw_sources = raw_sources or []

        if merge_or_replace is not None:
            mode = "update" if merge_or_replace in ("merge", "replace") else "sink"

        similar_page = self._find_similar_query_page(query)
        hint = ""

        if similar_page and mode == "update":
            similar_name = similar_page['page_name']
            page_name = similar_name
            page_path = self.wiki_dir / f"{page_name}.md"

            if auto_link:
                answer = self._append_sources_section(
                    answer, query, source_pages, raw_sources
                )

            page_path.write_text(answer)

            rel_path = str(page_path.relative_to(self.wiki_dir))
            self.index.upsert_page(rel_path[:-3], answer, rel_path)
            self._update_index_file()

            status = "updated"
            message = f"Updated query page: {page_name}"

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
                    "Update formal page: wiki_synthesize(..., mode='update')",
                    "Or let the sink accumulate for later review during lint",
                ],
            }

            page_name = similar_name
            page_path = self.root / sink_path

            status = "sunk"
            message = f"Appended to sink for: {similar_name}"

        else:
            page_name = page_name or self._generate_query_page_name(query)
            page_path = self.wiki_dir / f"{page_name}.md"

            counter = 1
            while page_path.exists():
                base = page_name
                page_name = f"{base} ({counter})"
                page_path = self.wiki_dir / f"{page_name}.md"
                counter += 1

            self._create_query_page(page_path, page_name, answer, query, source_pages, raw_sources, auto_link)
            status = "created"
            message = f"Created query page: {page_name}"

        logged = False
        if auto_log:
            if status == "sunk":
                log_detail = f"{query} → [sink] (see wiki/.sink/{similar_page['page_name']}.sink.md)"
            elif status == "updated":
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
        topic = query.strip()[:MAX_QUERY_TOPIC_LENGTH].strip()
        topic = topic.title()
        topic = topic.rstrip(".,;:!?")
        return f"Query: {topic}"

    def _find_similar_query_page(self, query: str) -> dict | None:
        """Find an existing query page with similar topic.

        Searches for pages starting with 'Query: ' that share significant
        keywords with the given query.

        Returns:
            Dict with page_name, preview, key_topics, word_count, created, score.
            None if no similar page found.
        """
        if not self.wiki_dir.exists():
            return None

        keywords = {
            w.lower().strip(".,;:!?\"'()[]{}")
            for w in query.split()
            if w.lower() not in STOP_WORDS and len(w) > MIN_KEYWORD_LENGTH
        }

        if not keywords:
            return None

        best_match = None
        best_score = 0

        for page in self.wiki_dir.rglob("*.md"):
            page_name = page.stem

            if not page_name.startswith("Query:"):
                continue

            page_keywords = {
                w.lower().strip(".,;:!?\"'()[]{}")
                for w in page_name.replace("Query:", "").split()
                if w.lower() not in STOP_WORDS and len(w) > MIN_KEYWORD_LENGTH
            }

            if not page_keywords:
                continue

            overlap = len(keywords & page_keywords)
            union = len(keywords | page_keywords)
            score = overlap / union if union > 0 else 0

            try:
                content = page.read_text()
                content_keywords = {
                    w.lower() for w in re.findall(r'\b\w{4,}\b', content)
                    if w.lower() not in STOP_WORDS
                }
                content_overlap = len(keywords & content_keywords)
                content_score = content_overlap / len(keywords) if keywords else 0
                score = max(score, content_score * 0.8)
            except OSError:
                pass

            if score > best_score and score >= SIMILARITY_THRESHOLD:
                best_score = score

                preview = content.split('\n')[-1] if '\n' in content else content
                for line in content.split('\n'):
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#') and not stripped.startswith('---'):
                        preview = stripped[:200]
                        break

                key_topics = list(page_keywords)[:MAX_KEY_TOPICS]
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
        source_pages: list[str],
        raw_sources: list[str],
        auto_link: bool,
    ) -> None:
        """Create a new query page with sources section."""
        content = answer

        if auto_link and (source_pages or raw_sources):
            content = self._append_sources_section(content, query, source_pages, raw_sources)

        page_path.write_text(content)

        rel_path = str(page_path.relative_to(self.wiki_dir))
        self.index.upsert_page(rel_path[:-3], content, rel_path)
        self._update_index_file()

    def _append_sources_section(
        self,
        answer: str,
        query: str,
        source_pages: list[str],
        raw_sources: list[str],
    ) -> str:
        """Append structured Sources section to answer content."""
        sources_section = "\n\n---\n\n## Sources\n\n"

        sources_section += "### Query\n"
        sources_section += f"- **Question**: {query}\n"
        sources_section += f"- **Generated**: {self._now()}\n"

        if source_pages:
            sources_section += "\n### Wiki Pages Referenced\n"
            for page in source_pages:
                sources_section += f"- [[{page}]]\n"

        if raw_sources:
            sources_section += "\n### Raw Sources\n"
            for raw_path in raw_sources:
                filename = Path(raw_path).name
                sources_section += f"- [Source: {filename}]({raw_path})\n"

        return answer + sources_section

    def read_sink(self, page_name: str) -> dict:
        """Read all entries from a query sink file (hash references resolved)."""
        return self.query_sink.read(page_name)

    def sink_status(self) -> dict:
        """Overview of all query sinks with entry counts and urgency."""
        return self.query_sink.status()
