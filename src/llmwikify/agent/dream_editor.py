"""Dream Editor - Surgical wiki page editing engine with proposal mode.

Analyzes QuerySink content and generates edit proposals for human review.
Small edits (< 100 chars) can be auto-approved. All edits are logged and reversible.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ProposalManager:
    """Manages Dream edit proposals with auto-approve for small changes.

    Reuses NotificationManager pattern: in-memory list with UUID IDs,
    timestamps, status tracking, and max size limit.
    """

    AUTO_APPROVE_THRESHOLD = 100  # Character count threshold for auto-approve

    def __init__(self, max_size: int = 200):
        self._proposals: list[dict[str, Any]] = []
        self._max_size = max_size

    def _add_proposal(self, proposal: dict) -> dict:
        """Add a proposal with LRU eviction (reuses NotificationManager pattern)."""
        self._proposals.append(proposal)
        if len(self._proposals) > self._max_size:
            self._proposals = self._proposals[-self._max_size:]
        return proposal

    def create_proposal(
        self,
        page_name: str,
        edit_type: str,
        content: str,
        reason: str,
        source_entries: list[dict] | None = None,
    ) -> dict:
        """Create a new edit proposal."""
        proposal = {
            "id": f"prop-{uuid.uuid4().hex[:6]}",
            "page_name": page_name,
            "edit_type": edit_type,
            "content": content,
            "reason": reason,
            "source_entries": source_entries or [],
            "content_length": len(content),
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_at": None,
        }
        return self._add_proposal(proposal)

    def auto_approve_pending(self) -> list[dict]:
        """Auto-approve proposals that meet the small-edit threshold.

        Criteria: append edit type AND content_length < AUTO_APPROVE_THRESHOLD.
        Returns list of auto-approved proposals.
        """
        auto_approved = []
        for p in self._proposals:
            if p["status"] != "pending":
                continue
            if (p["edit_type"] == "append"
                    and p["content_length"] < self.AUTO_APPROVE_THRESHOLD):
                p["status"] = "auto_approved"
                p["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                auto_approved.append(p)
        return auto_approved

    def approve(self, proposal_id: str) -> dict | None:
        """Approve a proposal."""
        for p in self._proposals:
            if p["id"] == proposal_id:
                p["status"] = "approved"
                p["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                return p
        return None

    def reject(self, proposal_id: str) -> dict | None:
        """Reject a proposal."""
        for p in self._proposals:
            if p["id"] == proposal_id:
                p["status"] = "rejected"
                p["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                return p
        return None

    def batch_approve(self, proposal_ids: list[str]) -> list[dict]:
        """Approve multiple proposals."""
        results = []
        for pid in proposal_ids:
            result = self.approve(pid)
            if result:
                results.append(result)
        return results

    def get_pending(self) -> list[dict]:
        """Get all pending proposals."""
        return [p for p in self._proposals if p["status"] == "pending"]

    def get_pending_by_page(self) -> dict[str, list[dict]]:
        """Get pending proposals grouped by page name."""
        groups: dict[str, list[dict]] = {}
        for p in self._proposals:
            if p["status"] != "pending":
                continue
            page = p["page_name"]
            if page not in groups:
                groups[page] = []
            groups[page].append(p)
        return groups

    def get_stats(self) -> dict:
        """Get proposal statistics."""
        stats = {"pending": 0, "approved": 0, "rejected": 0, "auto_approved": 0, "applied": 0}
        for p in self._proposals:
            status = p.get("status", "pending")
            if status in stats:
                stats[status] += 1
        return stats

    def get_proposal(self, proposal_id: str) -> dict | None:
        """Get a specific proposal by ID."""
        for p in self._proposals:
            if p["id"] == proposal_id:
                return p
        return None

    def clear_applied(self) -> int:
        """Clear applied proposals to free memory. Returns count cleared."""
        before = len(self._proposals)
        self._proposals = [p for p in self._proposals if p["status"] != "applied"]
        return before - len(self._proposals)


class DreamEditor:
    """Performs surgical edits to wiki pages based on QuerySink analysis.

    Workflow (proposal mode):
    1. Read new entries from QuerySink
    2. Generate edit proposals (no file writes)
    3. Auto-approve small edits (< 100 chars append)
    4. Human reviews remaining proposals via WebUI
    5. Apply approved proposals to wiki files

    Legacy workflow (direct mode, deprecated):
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
        self.proposal_manager = ProposalManager()

    def run_dream(self) -> dict:
        """Execute a Dream cycle: generate proposals from sinks, auto-approve small edits.

        Does NOT write files directly. Returns proposal summary.
        Use apply_proposals() to apply approved proposals.
        """
        sink_status = self.wiki.query_sink.status()
        sinks = sink_status.get("sinks", [])

        results: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sinks_processed": 0,
            "proposals_generated": 0,
            "auto_approved": 0,
            "pending_review": 0,
            "errors": [],
        }

        for sink_info in sinks:
            page_name = sink_info["page_name"]
            if sink_info["entry_count"] == 0:
                continue

            try:
                self._generate_proposals_from_sink(page_name)
                results["sinks_processed"] += 1
            except Exception as e:
                logger.error(f"Dream proposal generation failed for {page_name}: {e}")
                results["errors"].append({"page": page_name, "error": str(e)})

        # Auto-approve small edits
        auto_approved = self.proposal_manager.auto_approve_pending()
        results["auto_approved"] = len(auto_approved)

        # Count stats
        all_stats = self.proposal_manager.get_stats()
        results["proposals_generated"] = sum(all_stats.values())
        results["pending_review"] = all_stats["pending"]

        self._log_dream_run(results)
        return results

    def _generate_proposals_from_sink(self, page_name: str) -> None:
        """Generate edit proposals from a single sink (no file writes)."""
        sink_data = self.wiki.query_sink.read(page_name)
        if sink_data.get("status") != "ok":
            return

        entries = sink_data.get("entries", [])
        if not entries:
            return

        wiki_page = self.wiki.wiki_dir / f"{page_name}.md"

        if wiki_page.exists():
            self._propose_update_existing_page(page_name, wiki_page, entries)
        else:
            self._propose_create_page_from_sink(page_name, entries)

    def _propose_update_existing_page(
        self, page_name: str, page_path: Path, entries: list[dict]
    ) -> None:
        """Generate proposals for updating an existing wiki page."""
        content = page_path.read_text()

        for entry in entries:
            if entry.get("note") == "duplicate":
                continue

            answer = entry.get("answer", "").strip()
            query = entry.get("query", "").strip()

            if not answer:
                continue

            section = f"\n\n### {query}\n\n{answer}\n"
            if section.strip() not in content:
                self.proposal_manager.create_proposal(
                    page_name=page_name,
                    edit_type="append",
                    content=section.strip(),
                    reason=f"Sink entry: {query}",
                    source_entries=[entry],
                )

    def _propose_create_page_from_sink(self, page_name: str, entries: list[dict]) -> None:
        """Generate proposal for creating a new wiki page from sink entries."""
        non_dup_entries = [e for e in entries if e.get("note") != "duplicate"]
        if not non_dup_entries:
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content_parts = [
            "---",
            f"title: {page_name}",
            f"created: {now}",
            f"updated: {now}",
            "sources: []",
            "tags: []",
            "---",
            "",
            f"# {page_name}",
            "",
            "> Auto-generated from QuerySink entries",
            "",
        ]

        for entry in non_dup_entries:
            query = entry.get("query", "").strip()
            answer = entry.get("answer", "").strip()
            if query and answer:
                content_parts.extend([
                    f"## {query}",
                    "",
                    f"{answer}",
                    "",
                ])

        content = "\n".join(content_parts)
        self.proposal_manager.create_proposal(
            page_name=page_name,
            edit_type="create",
            content=content,
            reason=f"New page from {len(non_dup_entries)} sink entries",
            source_entries=non_dup_entries,
        )

    def apply_proposals(self, proposal_ids: list[str] | None = None) -> dict:
        """Apply approved (or auto_approved) proposals to wiki files.

        Args:
            proposal_ids: List of proposal IDs to apply. If None, apply all approved.

        Returns:
            Dict with applied count and errors.
        """
        results: dict[str, Any] = {
            "applied": 0,
            "errors": [],
        }

        if proposal_ids is None:
            # Apply all approved and auto_approved
            to_apply = [
                p for p in self.proposal_manager._proposals
                if p["status"] in ("approved", "auto_approved")
            ]
        else:
            to_apply = []
            for pid in proposal_ids:
                p = self.proposal_manager.get_proposal(pid)
                if p and p["status"] in ("approved", "auto_approved"):
                    to_apply.append(p)

        for proposal in to_apply:
            try:
                self._apply_single_proposal(proposal)
                proposal["status"] = "applied"
                results["applied"] += 1
            except Exception as e:
                logger.error(f"Failed to apply proposal {proposal['id']}: {e}")
                results["errors"].append({
                    "proposal_id": proposal["id"],
                    "page": proposal["page_name"],
                    "error": str(e),
                })

        return results

    def _apply_single_proposal(self, proposal: dict) -> None:
        """Apply a single proposal to the wiki file."""
        page_name = proposal["page_name"]
        content = proposal["content"]
        edit_type = proposal["edit_type"]

        if edit_type == "create":
            self._apply_create_page(page_name, content)
        elif edit_type == "append":
            self._apply_append(page_name, content)
        elif edit_type == "insert_before":
            marker = proposal.get("marker", "")
            self._apply_insert(page_name, content, marker, position="before")
        elif edit_type == "insert_after":
            marker = proposal.get("marker", "")
            self._apply_insert(page_name, content, marker, position="after")
        elif edit_type == "replace_section":
            start = proposal.get("start_marker", "")
            end = proposal.get("end_marker", "")
            self._apply_replace(page_name, content, start, end)

    def _apply_create_page(self, page_name: str, content: str) -> None:
        """Create a new wiki page."""
        page_path = self.wiki.wiki_dir / f"{page_name}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(content)
        self.wiki.index.upsert_page(page_name, content, str(page_path.relative_to(self.wiki.wiki_dir)))
        self.wiki.append_log("dream_create", f"Created {page_name} from Dream proposal")

    def _apply_append(self, page_name: str, content: str) -> None:
        """Append content to an existing wiki page."""
        page_path = self.wiki.wiki_dir / f"{page_name}.md"
        if not page_path.exists():
            raise FileNotFoundError(f"Page not found: {page_name}")

        existing = page_path.read_text()
        new_content = existing.rstrip() + "\n\n" + content + "\n"
        page_path.write_text(new_content)
        self.wiki.index.upsert_page(page_name, new_content, str(page_path.relative_to(self.wiki.wiki_dir)))
        self.wiki.append_log("dream_edit", f"Appended to {page_name} from Dream proposal")

    def _apply_insert(self, page_name: str, content: str, marker: str, position: str) -> None:
        """Insert content before or after a marker."""
        page_path = self.wiki.wiki_dir / f"{page_name}.md"
        if not page_path.exists():
            raise FileNotFoundError(f"Page not found: {page_name}")

        existing = page_path.read_text()
        if marker not in existing:
            raise ValueError(f"Marker not found in page: {marker}")

        if position == "before":
            new_content = existing.replace(marker, content + "\n\n" + marker, 1)
        else:
            new_content = existing.replace(marker, marker + "\n\n" + content, 1)

        page_path.write_text(new_content)
        self.wiki.index.upsert_page(page_name, new_content, str(page_path.relative_to(self.wiki.wiki_dir)))
        self.wiki.append_log("dream_edit", f"Inserted into {page_name} from Dream proposal")

    def _apply_replace(self, page_name: str, content: str, start_marker: str, end_marker: str) -> None:
        """Replace content between markers."""
        page_path = self.wiki.wiki_dir / f"{page_name}.md"
        if not page_path.exists():
            raise FileNotFoundError(f"Page not found: {page_name}")

        existing = page_path.read_text()
        if start_marker not in existing or end_marker not in existing:
            raise ValueError(f"Markers not found in page: {start_marker}, {end_marker}")

        start_idx = existing.index(start_marker)
        end_idx = existing.index(end_marker) + len(end_marker)
        new_content = existing[:start_idx] + content + existing[end_idx:]

        page_path.write_text(new_content)
        self.wiki.index.upsert_page(page_name, new_content, str(page_path.relative_to(self.wiki.wiki_dir)))
        self.wiki.append_log("dream_edit", f"Replaced section in {page_name} from Dream proposal")

    def _apply_surgical_edit(self, page: str, edit: dict) -> bool:
        """Apply a single surgical edit operation. Legacy method, use apply_proposals instead."""
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
        with open(self.edits_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries[-limit:]

    def get_proposals(self, limit: int = 50) -> list[dict]:
        """Get recent proposals."""
        all_proposals = list(self.proposal_manager._proposals)
        return all_proposals[-limit:]

    def get_proposals_by_page(self) -> dict[str, list[dict]]:
        """Get pending proposals grouped by page."""
        return self.proposal_manager.get_pending_by_page()
