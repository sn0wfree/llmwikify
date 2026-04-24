"""Wiki synthesis mixin — cross-source synthesis suggestions."""

import logging

from .protocols import WikiProtocol

logger = logging.getLogger(__name__)


class WikiSynthesisMixin(WikiProtocol):
    """Cross-source synthesis: compare sources, generate update suggestions."""

    def suggest_synthesis(self, source_name: str | None = None) -> dict:
        """Analyze sources and generate cross-source synthesis suggestions.

        This method compares new or existing sources against the wiki
        and returns suggestions (not auto-executed). Respects the
        "stay involved" principle — human decides what to do with suggestions.

        Args:
            source_name: Specific source to analyze, or None for all unanalyzed sources.

        Returns:
            Dict with synthesis suggestions:
            - suggestions: list of synthesis suggestions
            - summary: human-readable summary
            - sources_analyzed: number of sources analyzed
        """
        from .synthesis_engine import SynthesisEngine

        engine = SynthesisEngine(self)
        all_suggestions = []

        if source_name:
            analysis = self.analyze_source(source_name)
            if analysis.get("status") in ("error", "skipped"):
                return {
                    "error": f"Failed to analyze {source_name}: {analysis.get('reason')}",
                    "suggestions": [],
                    "sources_analyzed": 0,
                }

            suggestion = engine.analyze_new_source(analysis, source_name)
            all_suggestions.append(suggestion)
        else:
            sources_dir = self.raw_dir
            if not sources_dir.exists():
                return {
                    "suggestions": [],
                    "sources_analyzed": 0,
                    "summary": "No raw sources found",
                }

            sources = [f for f in sources_dir.rglob("*") if f.is_file()]
            analyzed_count = 0

            for source_file in sources:
                rel_path = str(source_file.relative_to(self.root))
                try:
                    analysis = self.analyze_source(rel_path)
                    if analysis.get("status") not in ("error", "skipped"):
                        suggestion = engine.analyze_new_source(analysis, rel_path)
                        all_suggestions.append(suggestion)
                        analyzed_count += 1
                except Exception:
                    logger.warning("Source analysis failed for %s", source_file)

        total_suggestions = sum(
            len(s.get("suggested_updates", [])) +
            len(s.get("new_contradictions", [])) +
            len(s.get("knowledge_gaps", []))
            for s in all_suggestions
        )

        return {
            "suggestions": all_suggestions,
            "sources_analyzed": len(all_suggestions),
            "total_suggestions": total_suggestions,
            "summary": f"Analyzed {len(all_suggestions)} source(s), generated {total_suggestions} suggestion(s)",
        }
