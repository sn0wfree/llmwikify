"""Wiki relation mixin — relation engine integration, graph analysis."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .relation_engine import RelationEngine

from .protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiRelationMixin(WikiProtocol):
    """Relation engine and graph analysis integration."""

    def write_relations(self, relations: list, source_file: str | None = None) -> dict:
        """Write extracted relations to the database.

        Args:
            relations: List of {source, target, relation, confidence, context} dicts.
            source_file: Original source file name.

        Returns:
            Dict with count of relations added.
        """
        if not relations:
            return {"status": "skipped", "count": 0}

        from .relation_engine import RelationEngine

        engine = RelationEngine(self.index, wiki_root=self.root)

        for r in relations:
            if "source_file" not in r and source_file:
                r["source_file"] = source_file

        count = engine.add_relations(relations)

        if count == 0 and relations:
            valid_types = engine.get_relation_types()
            return {
                "status": "skipped",
                "count": 0,
                "reason": f"No valid relations added. Valid types: {sorted(valid_types)}",
            }

        return {
            "status": "completed",
            "count": count,
            "source_file": source_file,
        }

    def get_relation_engine(self) -> RelationEngine:
        """Get the relation engine instance."""
        from .relation_engine import RelationEngine
        return RelationEngine(self.index, wiki_root=self.root)

    def graph_analyze(self) -> dict:
        """Run full knowledge graph analysis.

        Returns suggestions only — never auto-creates pages.
        Respects "stay involved" principle.

        Returns:
            Dict with:
            - centrality: PageRank scores, hubs, authorities
            - communities: Community detection with labels
            - suggestions: Pages to create, links to add
            - stats: Graph statistics
        """
        from .graph_analyzer import GraphAnalyzer

        analyzer = GraphAnalyzer(self)
        return analyzer.analyze()

    def graph_suggested_pages_report(self) -> str:
        """Generate human-readable report of suggested pages."""
        from .graph_analyzer import GraphAnalyzer

        analyzer = GraphAnalyzer(self)
        return analyzer.get_suggested_pages_report()

    def execute_operations(self, operations: list) -> dict:
        """Execute a list of wiki operations from LLM processing.

        Args:
            operations: List of {action, ...} dicts from _llm_process_source().

        Returns:
            Dict with results of each operation.

        Transaction protection:
        - Takes snapshot of wiki pages before execution
        - On failure, rolls back to snapshot
        - Tracks timing for each operation
        """
        import time

        # Take snapshot of existing pages for rollback
        snapshot_dir = self.root / ".wiki_snapshot"
        snapshot_dir.mkdir(exist_ok=True)
        page_snapshots = {}

        try:
            # Snapshot existing pages that will be modified
            write_ops = [op for op in operations if op.get("action") == "write_page"]
            for op in write_ops:
                page_name = op.get("page_name", "")
                if page_name:
                    page_path = self.wiki_dir / f"{page_name}.md"
                    if page_path.exists():
                        snapshot_path = snapshot_dir / f"{page_name}.md"
                        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(page_path, snapshot_path)
                        page_snapshots[page_name] = snapshot_path

            # Execute operations with timing
            results = []
            for op in operations:
                t0 = time.monotonic()
                action = op.get("action", "")
                if action == "write_page":
                    page_name = op.get("page_name", "")
                    content = op.get("content", "")
                    if page_name and content:
                        self.write_page(page_name, content)
                        results.append({
                            "action": "write_page",
                            "page": page_name,
                            "status": "done",
                            "ms": int((time.monotonic() - t0) * 1000),
                        })
                    else:
                        results.append({
                            "action": "write_page",
                            "status": "skipped",
                            "reason": "missing page_name or content",
                        })
                elif action == "log":
                    operation = op.get("operation", "")
                    details = op.get("details", "")
                    if operation and details:
                        self.append_log(operation, details)
                        results.append({
                            "action": "log",
                            "operation": operation,
                            "status": "done",
                            "ms": int((time.monotonic() - t0) * 1000),
                        })
                    else:
                        results.append({
                            "action": "log",
                            "status": "skipped",
                            "reason": "missing operation or details",
                        })
                else:
                    results.append({"action": action, "status": "unknown"})

            return {
                "status": "completed",
                "operations_executed": len(results),
                "results": results,
            }

        except Exception as e:
            # Rollback on failure
            logger.error("Operation failed, rolling back %d pages: %s", len(page_snapshots), e)
            for page_name, snapshot_path in page_snapshots.items():
                try:
                    page_path = self.wiki_dir / f"{page_name}.md"
                    if snapshot_path.exists():
                        shutil.copy2(snapshot_path, page_path)
                    elif page_path.exists():
                        page_path.unlink()
                except Exception as rollback_error:
                    logger.error("Rollback failed for %s: %s", page_name, rollback_error)

            return {
                "status": "rolled_back",
                "error": str(e),
                "pages_rolled_back": len(page_snapshots),
            }

        finally:
            # Cleanup snapshot directory
            try:
                if snapshot_dir.exists():
                    shutil.rmtree(snapshot_dir)
            except Exception:
                pass
