"""Wiki relation mixin — relation engine integration, graph analysis."""

import logging

logger = logging.getLogger(__name__)


class WikiRelationMixin:
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

    def get_relation_engine(self) -> "RelationEngine":
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
        """
        results = []
        for op in operations:
            action = op.get("action", "")
            if action == "write_page":
                page_name = op.get("page_name", "")
                content = op.get("content", "")
                if page_name and content:
                    self.write_page(page_name, content)
                    results.append({"action": "write_page", "page": page_name, "status": "done"})
                else:
                    results.append({"action": "write_page", "status": "skipped", "reason": "missing page_name or content"})
            elif action == "log":
                operation = op.get("operation", "")
                details = op.get("details", "")
                if operation and details:
                    self.append_log(operation, details)
                    results.append({"action": "log", "operation": operation, "status": "done"})
                else:
                    results.append({"action": "log", "status": "skipped", "reason": "missing operation or details"})
            else:
                results.append({"action": action, "status": "unknown"})

        return {
            "status": "completed",
            "operations_executed": len(results),
            "results": results,
        }
