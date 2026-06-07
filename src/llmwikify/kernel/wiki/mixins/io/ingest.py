"""Wiki ingest mixin — source file ingestion, extraction, raw collection."""

import logging
import re
import time
from pathlib import Path

from .....foundation.extractors import extract

from ...protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiIngestMixin(WikiProtocol):
    """Source ingestion: extract, save to raw/, return data for LLM processing."""

    def extract_section_metadata(self, content: str, title: str = "") -> dict:
        """Extract section-level metadata from content for LLM-based navigation.

        Parses Markdown headings and falls back to paragraph-based heuristic
        splitting when no headings are found.

        Args:
            content: Full document content
            title: Document title (optional)

        Returns:
            Section metadata dict with sections, total_words, has_headers, etc.
        """
        lines = content.split("\n")
        sections = []
        header_lines = []

        for i, line in enumerate(lines):
            match = re.match(r'^(#{1,6})\s+(.+)', line)
            if match:
                level = len(match.group(1))
                header_lines.append(i)
                sections.append({
                    "id": len(header_lines),
                    "level": level,
                    "title": match.group(2).strip(),
                    "line": i,
                })

        if not header_lines:
            sections = self._detect_paragraph_sections(lines)

        for i, section in enumerate(sections):
            start = section.get("line", 0)
            end = sections[i + 1]["line"] if i + 1 < len(sections) else len(lines)
            section_text = "\n".join(lines[start:end])
            section["word_count"] = len(section_text.split())
            section["preview"] = section_text[:150].strip()

        return {
            "title": title,
            "total_words": len(content.split()),
            "has_headers": len(header_lines) > 0,
            "header_count": len(header_lines),
            "sections": sections,
        }

    def _detect_paragraph_sections(self, lines: list[str]) -> list[dict]:
        """Detect sections from paragraph structure when no headings exist.

        Uses heuristics: short lines surrounded by blank lines, or lines
        ending with colon, are treated as implicit headers.
        """
        sections = []
        current_section_start = 0

        for i, line in enumerate(lines):
            is_blank = line.strip() == ""
            if is_blank:
                if i > current_section_start:
                    paragraph = "\n".join(lines[current_section_start:i]).strip()
                    if paragraph:
                        words = paragraph.split()
                        if len(words) < 10 and (paragraph.endswith(":") or paragraph.isupper()):
                            sections.append({
                                "id": len(sections) + 1,
                                "level": 2,
                                "title": paragraph.rstrip(":").strip(),
                                "line": current_section_start,
                                "heuristic": True,
                            })
                        elif len(words) >= 50:
                            sections.append({
                                "id": len(sections) + 1,
                                "level": 2,
                                "title": f"Section {len(sections) + 1}",
                                "line": current_section_start,
                                "heuristic": True,
                            })
                current_section_start = i + 1

        remaining = "\n".join(lines[current_section_start:]).strip()
        if remaining and len(remaining.split()) >= 10:
            sections.append({
                "id": len(sections) + 1,
                "level": 2,
                "title": f"Section {len(sections) + 1}",
                "line": current_section_start,
                "heuristic": True,
            })

        return sections

    def targeted_read(self, content: str, selected_sections: list[int], max_chars: int = 32000) -> tuple[str, bool]:
        """Read only selected sections, respecting char budget.

        Args:
            content: Full document content
            selected_sections: List of section IDs to read (1-indexed)
            max_chars: Maximum characters to return

        Returns:
            Tuple of (targeted_content, was_truncated)
        """
        lines = content.split("\n")

        header_lines = []
        for i, line in enumerate(lines):
            if re.match(r'^#{1,6}\s+', line):
                header_lines.append(i)

        if not header_lines:
            return self._targeted_read_by_paragraph(lines, selected_sections, max_chars)

        selected_text = []
        char_budget = max_chars

        for section_id in selected_sections:
            if section_id < 1 or section_id > len(header_lines):
                continue

            start = header_lines[section_id - 1]
            end = header_lines[section_id] if section_id < len(header_lines) else len(lines)

            section_text = "\n".join(lines[start:end])

            if len(section_text) <= char_budget:
                selected_text.append(section_text)
                char_budget -= len(section_text)
            else:
                truncated = section_text[:char_budget]
                selected_text.append(truncated)
                char_budget = 0
                break

        result = "\n\n".join(selected_text)
        was_truncated = char_budget == 0 and len(result) < sum(
            len("\n".join(lines[header_lines[sid - 1]:header_lines[sid] if sid < len(header_lines) else len(lines)]))
            for sid in selected_sections if 1 <= sid <= len(header_lines)
        )

        return result, was_truncated

    def _targeted_read_by_paragraph(
        self, lines: list[str], selected_sections: list[int], max_chars: int
    ) -> tuple[str, bool]:
        """Fallback targeted reading by paragraph when no headings exist."""
        paragraphs = []
        current = []
        for line in lines:
            if line.strip() == "" and current:
                paragraphs.append("\n".join(current))
                current = []
            else:
                current.append(line)
        if current:
            paragraphs.append("\n".join(current))

        selected_text = []
        char_budget = max_chars

        for section_id in selected_sections:
            if section_id < 1 or section_id > len(paragraphs):
                continue

            paragraph = paragraphs[section_id - 1]
            if len(paragraph) <= char_budget:
                selected_text.append(paragraph)
                char_budget -= len(paragraph)
            else:
                truncated = paragraph[:char_budget]
                selected_text.append(truncated)
                char_budget = 0
                break

        return "\n\n".join(selected_text), char_budget == 0

    def _generate_lint_hint(self, source_name: str, content: str, already_exists: bool) -> dict:
        """Generate lightweight lint hints (pure computation, no LLM).

        Acts as a harness pre-check layer, alerting the Agent to potential
        issues before it starts creating pages.
        """
        issues = []

        word_count = len(content.split()) if content else 0
        if word_count < 50:
            issues.append({
                "type": "content_too_short",
                "message": f"Content is very short ({word_count} words), may need manual review"
            })

        image_refs = re.findall(r'!\[.*?\]\((.*?)\)', content or '')
        if image_refs:
            issues.append({
                "type": "has_images",
                "message": f"Document contains {len(image_refs)} image(s), review for important visuals"
            })

        if already_exists:
            issues.append({
                "type": "source_already_exists",
                "message": f"Source already exists in raw/{source_name}, consider updating"
            })

        return {
            "issues_found": len(issues),
            "suggestion": "Run wiki_lint(mode='check') for full analysis" if issues else None,
            "top_issues": issues[:5]
        }

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
        timing = {}
        t0 = time.monotonic()

        result = extract(source, wiki_root=self.root)
        timing["extract_ms"] = int((time.monotonic() - t0) * 1000)

        if result.source_type == "error":
            return {"error": result.metadata.get("error", "Unknown extraction error"), "timing": timing}

        if not result.text:
            return {"error": "No content extracted", "timing": timing}

        saved_to_raw = False
        already_exists = False
        hint = ""
        source_name = ""

        self._ensure_raw_dir()

        if result.source_type in ("url", "youtube"):
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
            original_path = Path(source).resolve()
            try:
                original_path.relative_to(self.raw_dir.resolve())
                source_name = str(original_path.relative_to(self.raw_dir))
                saved_to_raw = False
                hint = f"Source is already in raw/{source_name}"
            except ValueError:
                safe_name = self._slugify(result.title or original_path.stem) + original_path.suffix
                saved_path = self.raw_dir / safe_name

                if saved_path.exists():
                    already_exists = True
                    source_name = safe_name
                    hint = f"Source already exists in raw/{safe_name}"
                else:
                    saved_path.write_bytes(original_path.read_bytes())
                    saved_to_raw = True
                    source_name = safe_name
                    hint = f"Source copied to raw/{safe_name} from {original_path}"

        index_content = ""
        if self.index_file.exists():
            index_content = self._get_index_content()

        log_detail = f"Source ({result.source_type}): {result.title}"
        if saved_to_raw:
            log_detail += f" → raw/{source_name}"
        self.append_log("ingest", log_detail)

        raw_file = self.raw_dir / source_name
        file_size = 0
        word_count = 0
        has_images = False
        image_count = 0

        if raw_file.exists():
            file_size = raw_file.stat().st_size
            word_count = len(result.text.split()) if result.text else 0
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
            "section_metadata": self.extract_section_metadata(result.text or "", result.title),
            "lint_hint": self._generate_lint_hint(source_name, result.text or "", already_exists),
            "timing": {
                "extract_ms": timing.get("extract_ms", 0),
                "total_ms": int((time.monotonic() - t0) * 1000),
            },
        }
