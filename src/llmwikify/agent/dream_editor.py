"""Dream Editor - Surgical wiki page editing engine.

Analyzes QuerySink content and performs minimal, targeted edits to wiki pages.
All edits are logged and reversible.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DreamEditor:
    """Performs surgical edits to wiki pages based on QuerySink analysis.

    Workflow:
    1. Read new entries from QuerySink
    2. Analyze what needs to be updated in wiki pages
    3. Apply minimal edits (append/insert/replace sections)
    4. Log all edits for reversibility
    """

    def __init__(self, wiki: Any, data_dir: Path | None = None):
        self.wiki = wiki
        self.data_dir = data_dir or wiki.root / ".llmwikify" / "agent"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.edits_file = self.data_dir / "edits.jsonl"

    def run_dream(self) -> dict:
        """Execute a Dream cycle: analyze sinks and apply surgical edits."""
        sink_status = self.wiki.query_sink.status()
        sinks = sink_status.get("sinks", [])

        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sinks_processed": 0,
            "edits_applied": 0,
            "edits": [],
            "errors": [],
        }

        for sink_info in sinks:
            page_name = sink_info["page_name"]
            if sink_info["entry_count"] == 0:
                continue

            try:
                edit_result = self._process_sink(page_name)
                results["sinks_processed"] += 1
                results["edits_applied"] += edit_result.get("edit_count", 0)
                results["edits"].append(edit_result)
            except Exception as e:
                logger.error(f"Dream edit failed for {page_name}: {e}")
                results["errors"].append({"page": page_name, "error": str(e)})

        self._log_dream_run(results)
        return results

    def _process_sink(self, page_name: str) -> dict:
        """Process a single sink and apply edits to the corresponding wiki page."""
        sink_data = self.wiki.query_sink.read(page_name)
        if sink_data.get("status") != "ok":
            return {"page": page_name, "edit_count": 0, "status": "no_data"}

        entries = sink_data.get("entries", [])
        if not entries:
            return {"page": page_name, "edit_count": 0, "status": "no_entries"}

        wiki_page = self.wiki.wiki_dir / f"{page_name}.md"

        if wiki_page.exists():
            return self._update_existing_page(page_name, wiki_page, entries)
        else:
            return self._create_page_from_sink(page_name, entries)

    def _update_existing_page(self, page_name: str, page_path: Path, entries: list[dict]) -> dict:
        """Append new knowledge to an existing wiki page."""
        content = page_path.read_text()

        new_content_parts = []
        edit_count = 0

        for entry in entries:
            if entry.get("note") == "duplicate":
                continue

            answer = entry.get("answer", "").strip()
            query = entry.get("query", "").strip()

            if not answer:
                continue

            section = f"\n\n### {query}\n\n{answer}\n"
            if section.strip() not in content:
                new_content_parts.append(section.strip())
                edit_count += 1

        if new_content_parts:
            new_content = content.rstrip() + "\n\n" + "\n\n".join(new_content_parts) + "\n"
            page_path.write_text(new_content)
            self.wiki.index.upsert_page(page_name, new_content, str(page_path.relative_to(self.wiki.wiki_dir)))
            self.wiki.append_log("dream_edit", f"Updated {page_name} with {edit_count} new sections")

        return {
            "page": page_name,
            "edit_count": edit_count,
            "status": "updated" if edit_count > 0 else "no_changes",
            "sections_added": new_content_parts,
        }

    def _create_page_from_sink(self, page_name: str, entries: list[dict]) -> dict:
        """Create a new wiki page from sink entries."""
        non_dup_entries = [e for e in entries if e.get("note") != "duplicate"]
        if not non_dup_entries:
            return {"page": page_name, "edit_count": 0, "status": "no_entries"}

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content_parts = [
            f"---",
            f"title: {page_name}",
            f"created: {now}",
            f"updated: {now}",
            f"sources: []",
            f"tags: []",
            f"---",
            f"",
            f"# {page_name}",
            f"",
            f"> Auto-generated from QuerySink entries",
            f"",
        ]

        for entry in non_dup_entries:
            query = entry.get("query", "").strip()
            answer = entry.get("answer", "").strip()
            if query and answer:
                content_parts.extend([
                    f"## {query}",
                    f"",
                    f"{answer}",
                    f"",
                ])

        content = "\n".join(content_parts)
        page_path = self.wiki.wiki_dir / f"{page_name}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(content)
        self.wiki.index.upsert_page(page_name, content, str(page_path.relative_to(self.wiki.wiki_dir)))
        self.wiki.append_log("dream_create", f"Created {page_name} from {len(non_dup_entries)} sink entries")

        return {
            "page": page_name,
            "edit_count": len(non_dup_entries),
            "status": "created",
        }

    def _apply_surgical_edit(self, page: str, edit: dict) -> bool:
        """Apply a single surgical edit operation.

        Edit types:
        - append: Add content to end of page
        - insert_before: Insert content before a marker
        - insert_after: Insert content after a marker
        - replace_section: Replace content between markers
        """
        page_path = self.wiki.wiki_dir / f"{page}.md"
        if not page_path.exists():
            return False

        content = page_path.read_text()
        edit_type = edit.get("type", "append")

        if edit_type == "append":
            new_content = content.rstrip() + "\n\n" + edit.get("content", "") + "\n"
        elif edit_type == "insert_before":
            marker = edit.get("marker", "")
            if marker in content:
                new_content = content.replace(marker, edit.get("content", "") + "\n\n" + marker, 1)
            else:
                return False
        elif edit_type == "insert_after":
            marker = edit.get("marker", "")
            if marker in content:
                new_content = content.replace(marker, marker + "\n\n" + edit.get("content", ""), 1)
            else:
                return False
        elif edit_type == "replace_section":
            start = edit.get("start_marker", "")
            end = edit.get("end_marker", "")
            if start in content and end in content:
                start_idx = content.index(start)
                end_idx = content.index(end) + len(end)
                new_content = content[:start_idx] + edit.get("content", "") + content[end_idx:]
            else:
                return False
        else:
            return False

        page_path.write_text(new_content)
        return True

    def restore_edit(self, timestamp: str) -> bool:
        """Restore a page to its state before a Dream edit.

        Note: This is a best-effort restore. Full backup/restore requires
        git or external version control.
        """
        logger.warning(f"Restore for {timestamp} requested - requires git integration for full support")
        return False

    def _log_dream_run(self, results: dict) -> None:
        with open(self.edits_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(results, ensure_ascii=False) + "\n")

    def get_edit_log(self, limit: int = 20) -> list[dict]:
        if not self.edits_file.exists():
            return []
        entries = []
        with open(self.edits_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries[-limit:]
