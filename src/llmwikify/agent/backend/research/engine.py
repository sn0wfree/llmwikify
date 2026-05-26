"""Research Engine — 7-stage orchestrator with review loop and model layering."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ..adapters import StreamableLLMClient
from ..db import AgentDatabase
from ..providers.registry import create_llm
from .analyzer import SourceAnalyzer
from .config import merge_research_config
from .gatherer import SourceGatherer
from .report import ReportGenerator
from .review import ResearchReviewer, ResearchRevisor
from .session import ResearchSessionManager
from .synthesizer import ResearchSynthesizer
from .web_search import WebSearch

logger = logging.getLogger(__name__)


class ResearchEngine:
    """Orchestrates the 7-stage Deep Research pipeline.

    Stages:
    1. PLANNING — decompose query into sub-queries (planning_model)
    2. GATHERING — parallel source extraction
    3. ANALYZING — content analysis via Wiki.analyze_source()
    4. SYNTHESIZING — cross-source synthesis with rating weighting
    5. REPORT — generate structured markdown report (report_model)
    6. REVIEW — evaluate report quality; REVISE if issues found
    7. DONE — finalize
    """

    def __init__(
        self,
        wiki: Any,
        db: AgentDatabase,
        llm_client: StreamableLLMClient,
        config: dict[str, Any] | None = None,
    ):
        self.wiki = wiki
        self.db = db
        self.config = merge_research_config(config)
        self.session_manager = ResearchSessionManager(db)

        # Model layering
        self._default_llm = llm_client
        self._planning_llm = self._resolve_model("planning_model") or llm_client
        self._report_llm = self._resolve_model("report_model") or llm_client

    def _resolve_model(self, config_key: str) -> StreamableLLMClient | None:
        model_cfg = self.config.get(config_key)
        if not model_cfg:
            return None
        try:
            return create_llm(model_cfg)
        except Exception as e:
            logger.warning("Failed to resolve %s: %s, using default LLM", config_key, e)
            return None

    async def run(self, session_id: str, query: str) -> AsyncIterator[dict[str, Any]]:
        """Execute the 7-stage research pipeline, yielding SSE events."""
        self.session_manager.session_id = session_id

        # 1. PLANNING
        self.session_manager.update_status(session_id, "planning", "planning", 0.0)
        yield self._step_event("planning", "Decomposing research topic...")

        sub_queries = await self._plan_sub_queries(query)
        for sq in sub_queries:
            yield {
                "type": "sub_query_created",
                "sub_query_id": sq["id"],
                "query": sq["query"],
                "source_type": sq["source_type"],
                "url": sq.get("url"),
            }
        yield {"type": "progress", "progress": 0.1, "message": f"Created {len(sub_queries)} sub-queries"}

        # 2. GATHERING
        self.session_manager.update_status(session_id, "gathering", "gathering", 0.1)
        yield self._step_event("gathering", "Gathering sources...")

        gatherer = SourceGatherer(self.wiki, self.db, self.session_manager, self.config)
        total = len(sub_queries)
        gathered = 0

        gather_events = await gatherer.gather(sub_queries)
        for event in gather_events:
            if event.get("type") == "source_gathered":
                gathered += 1
                yield {
                    "type": "progress",
                    "progress": 0.1 + gathered / total * 0.3,
                    "message": f"Gathered {gathered}/{total} sources",
                }
            yield event

        sources = self.db.get_sources(session_id)
        yield {"type": "progress", "progress": 0.4, "message": f"Gathered {len(sources)} sources total"}

        # 3. ANALYZING
        self.session_manager.update_status(session_id, "analyzing", "analyzing", 0.4)
        yield self._step_event("analyzing", "Analyzing sources...")

        analyzer = SourceAnalyzer(self.wiki, self.session_manager, self.config)
        analysis_events = await analyzer.analyze_sources(sources)
        for event in analysis_events:
            yield event
        sources = self.db.get_sources(session_id)  # refresh with analysis
        yield {"type": "progress", "progress": 0.55, "message": "Analysis complete"}

        # 4. SYNTHESIZING
        self.session_manager.update_status(session_id, "synthesizing", "synthesizing", 0.55)
        yield self._step_event("synthesizing", "Synthesizing cross-source findings...")

        synthesizer = ResearchSynthesizer(self.wiki, self.config)
        synthesis = await synthesizer.synthesize(sources)
        yield {"type": "synthesis_complete", "synthesis": {
            "reinforced_claims": len(synthesis.get("reinforced_claims", [])),
            "contradictions": len(synthesis.get("contradictions", [])),
            "knowledge_gaps": len(synthesis.get("knowledge_gaps", [])),
            "new_entities": len(synthesis.get("new_entities", [])),
        }}
        yield {"type": "progress", "progress": 0.65, "message": "Synthesis complete"}

        # 5. REPORT
        self.session_manager.update_status(session_id, "report", "report", 0.65)
        yield self._step_event("report", "Generating research report...")

        generator = ReportGenerator(self.wiki, self._report_llm, self.config)
        report_md = await generator.generate(query, sources, synthesis)
        yield {"type": "progress", "progress": 0.75, "message": "Report generated"}

        # 6. REVIEW + REVISE loop
        max_rounds = self.config.get("max_review_rounds", 2)
        reviewer = ResearchReviewer(self.wiki, self._default_llm, self.config)
        revisor = ResearchRevisor(self.wiki, self._report_llm, self.config)

        for round_num in range(max_rounds):
            self.session_manager.update_status(session_id, "reviewing", "reviewing", 0.75 + round_num * 0.08)
            yield self._step_event("review", f"Reviewing report (round {round_num + 1})...")

            review = await reviewer.review(query, report_md, sources)

            if review.get("approved"):
                yield {
                    "type": "review_passed",
                    "round": round_num + 1,
                    "score": review.get("score", 0),
                    "feedback": review.get("feedback", ""),
                }
                break
            else:
                yield {
                    "type": "review_issues",
                    "round": round_num + 1,
                    "score": review.get("score", 0),
                    "issues": review.get("issues", []),
                }
                yield self._step_event("revise", f"Revising report (round {round_num + 1})...")
                report_md = await revisor.revise(report_md, review.get("issues", []), sources)
                yield {"type": "progress", "progress": 0.75 + (round_num + 1) * 0.08, "message": "Report revised"}
        else:
            yield {
                "type": "review_max_rounds",
                "message": f"Reached max review rounds ({max_rounds}), using current version",
            }

        # 7. DONE
        self.session_manager.update_status(session_id, "done", "done", 1.0)
        self.session_manager.finalize(session_id, {"markdown": report_md, "query": query})
        yield {
            "type": "done",
            "report": {
                "query": query,
                "markdown": report_md,
                "sources": [
                    {"id": s["id"], "title": s.get("title", ""), "url": s.get("url", ""), "source_type": s.get("source_type", "")}
                    for s in sources
                ],
                "synthesis_summary": {
                    "reinforced_claims": len(synthesis.get("reinforced_claims", [])),
                    "contradictions": len(synthesis.get("contradictions", [])),
                    "knowledge_gaps": len(synthesis.get("knowledge_gaps", [])),
                },
            },
        }

    async def _plan_sub_queries(self, query: str) -> list[dict[str, Any]]:
        """Decompose the research topic into sub-queries using planning_model."""
        wiki_index = ""
        if self.wiki.index_file.exists():
            wiki_index = self.wiki.index_file.read_text()[:3000]

        system = """You are a research planning assistant. Given a research topic, decompose it into focused sub-queries for gathering information from multiple sources.

Rules:
- Generate 3-10 sub-queries covering different aspects of the topic
- Each sub-query should be specific and searchable
- Assign source_type: "web" for general knowledge, "youtube" for video content, "wiki" for internal wiki knowledge
- Use "web" as default source_type
- Leave url empty for web/youtube (search will find results)
- For wiki, the query should be a wiki page name or search term
- Consider existing wiki content to avoid redundant queries
- Use English for queries

Return a JSON array of objects, each with "query", "source_type", and "url" fields.
Example: [{"query": "Python programming basics", "source_type": "web", "url": ""}]"""

        user = f"Research topic: {query}\n\n"
        if wiki_index:
            user += f"Existing wiki content (avoid redundancy):\n{wiki_index[:2000]}\n\n"
        user += "Generate sub-queries now. Return ONLY a JSON array."

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            import asyncio
            import json as json_mod

            def _call_llm():
                raw = self._planning_llm.chat(messages, json_mode=True, max_tokens=2048, temperature=0.3)
                return raw

            raw = await asyncio.to_thread(_call_llm)
            # Parse JSON response
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            result = json_mod.loads(raw)
            if not isinstance(result, list):
                result = []
        except Exception as e:
            logger.warning("Planning LLM failed: %s, using single query", e)
            result = [{"query": query, "source_type": "web", "url": ""}]

        # Limit and save to DB
        max_sq = self.config.get("max_sub_queries", 20)
        sub_queries: list[dict[str, Any]] = []
        session_id = self.session_manager.session_id

        for item in result[:max_sq]:
            sq_type = item.get("source_type", "web")
            if sq_type not in ("web", "youtube", "wiki", "pdf"):
                sq_type = "web"
            sq_id = self.session_manager.add_sub_query(
                session_id=session_id,
                query=item.get("query", ""),
                source_type=sq_type,
                url=item.get("url"),
            )
            sub_queries.append({
                "id": sq_id,
                "query": item.get("query", ""),
                "source_type": sq_type,
                "url": item.get("url"),
            })

        # Fallback: at least one sub-query
        if not sub_queries:
            sq_id = self.session_manager.add_sub_query(session_id, query, "web")
            sub_queries.append({"id": sq_id, "query": query, "source_type": "web", "url": ""})

        return sub_queries

    def _step_event(self, step: str, message: str) -> dict[str, Any]:
        return {"type": "step", "step": step, "message": message}
