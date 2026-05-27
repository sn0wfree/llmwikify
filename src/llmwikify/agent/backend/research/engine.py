"""Research Engine — 7-stage orchestrator with review loop and model layering."""

from __future__ import annotations

import json
import time
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
        self._timeout_seconds = self.config.get("research_timeout_minutes", 30) * 60
        self._start_time: float = 0

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

    def _check_timeout(self) -> None:
        """Raise TimeoutError if pipeline has exceeded timeout."""
        if self._start_time > 0:
            elapsed = time.monotonic() - self._start_time
            if elapsed > self._timeout_seconds:
                raise TimeoutError(f"Research timed out after {elapsed:.0f}s (limit: {self._timeout_seconds}s)")

    # Stage order for checkpoint resume
    STAGE_ORDER = ["planning", "gathering", "analyzing", "synthesizing", "report", "reviewing", "done"]

    def _stage_index(self, stage: str) -> int:
        try:
            return self.STAGE_ORDER.index(stage)
        except ValueError:
            return -1

    async def run(self, session_id: str, query: str, resume: bool = False) -> AsyncIterator[dict[str, Any]]:
        """Execute the 7-stage research pipeline, yielding SSE events.

        If resume=True, skips stages already completed based on current_step in DB.
        Times out after research_timeout_minutes (default 30).
        """
        self.session_manager.session_id = session_id
        self._start_time = time.monotonic()

        try:
            async for event in self._run_stages(session_id, query, resume):
                self._check_timeout()
                yield event
        except TimeoutError:
            self.session_manager.update_status(session_id, "timeout", "timeout", -1)
            yield {"type": "error", "error": f"Research timed out after {self._timeout_seconds}s"}
        except Exception:
            raise

    async def _run_stages(self, session_id: str, query: str, resume: bool) -> AsyncIterator[dict[str, Any]]:
        """Internal pipeline stages."""
        self.session_manager.session_id = session_id

        # Determine starting point
        start_stage = 0
        sub_queries: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        synthesis: dict[str, Any] = {}

        if resume:
            session = self.db.get_research_session(session_id)
            if session:
                current_step = session.get("current_step", "planning")
                start_stage = self._stage_index(current_step)
                if start_stage < 0:
                    start_stage = 0
                # Load existing sub_queries and sources for reuse
                existing_sub_queries = self.db.get_sub_queries(session_id) or []
                existing_sources = self.db.get_sources(session_id) or []
                yield {"type": "progress", "progress": session.get("progress", 0.0), "message": f"Resuming from {current_step}"}

                # Ensure variables are populated for resume from any stage
                if existing_sub_queries:
                    sub_queries = [
                        {"id": sq["id"], "query": sq["query"], "source_type": sq["source_type"], "url": sq.get("url")}
                        for sq in existing_sub_queries
                    ]
                if existing_sources:
                    sources = existing_sources

        # 1. PLANNING
        if start_stage <= self._stage_index("planning"):
            self.session_manager.update_status(session_id, "planning", "planning", 0.0)
            yield self._step_event("planning", "Decomposing research topic...")

            if resume and sub_queries:
                yield {"type": "progress", "progress": 0.1, "message": f"Reusing {len(sub_queries)} existing sub-queries"}
            else:
                sub_queries = await self._plan_sub_queries(query)
                for sq in sub_queries:
                    yield {
                        "type": "sub_query_created",
                        "sub_query_id": sq["id"],
                        "query": sq["query"],
                        "source_type": sq["source_type"],
                        "url": sq.get("url"),
                    }
            yield {"type": "progress", "progress": 0.1, "message": f"Planning complete: {len(sub_queries)} sub-queries"}

        # 2. GATHERING
        if start_stage <= self._stage_index("gathering"):
            self.session_manager.update_status(session_id, "gathering", "gathering", 0.1)
            yield self._step_event("gathering", "Gathering sources...")

            if resume and sources:
                # Skip gathering for sub-queries that already have sources
                gathered_sq_ids = {s.get("sub_query_id") for s in sources}
                remaining_queries = [sq for sq in sub_queries if sq["id"] not in gathered_sq_ids]
                gathered = len(sources)
                yield {"type": "progress", "progress": 0.1 + gathered / max(len(sub_queries), 1) * 0.3, "message": f"Reusing {gathered} existing sources, {len(remaining_queries)} remaining"}
            else:
                remaining_queries = sub_queries
                gathered = 0

            if remaining_queries:
                gatherer = SourceGatherer(self.wiki, self.db, self.session_manager, self.config)
                total = len(sub_queries)
                gather_events = await gatherer.gather(remaining_queries)
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

            if not sources:
                self.session_manager.update_status(session_id, "error", "gathering", -1)
                yield {"type": "error", "error": "No sources gathered. All sub-queries failed."}
                return

        # 3. ANALYZING
        if start_stage <= self._stage_index("analyzing"):
            sources = self.db.get_sources(session_id)  # refresh
            self.session_manager.update_status(session_id, "analyzing", "analyzing", 0.4)
            yield self._step_event("analyzing", "Analyzing sources...")

            analyzer = SourceAnalyzer(self.wiki, self.session_manager, self.config)
            analysis_events = await analyzer.analyze_sources(sources)
            for event in analysis_events:
                yield event
            sources = self.db.get_sources(session_id)  # refresh with analysis
            yield {"type": "progress", "progress": 0.55, "message": "Analysis complete"}

        # 4. SYNTHESIZING
        if start_stage <= self._stage_index("synthesizing"):
            sources = self.db.get_sources(session_id)  # refresh
            self.session_manager.update_status(session_id, "synthesizing", "synthesizing", 0.55)
            yield self._step_event("synthesizing", "Synthesizing cross-source findings...")

            synthesizer = ResearchSynthesizer(self.wiki, self.config)
            synthesis = await synthesizer.synthesize(sources)
            yield {"type": "synthesis_complete", "synthesis": {
                "reinforced_claims": synthesis.get("reinforced_claims", []),
                "contradictions": synthesis.get("contradictions", []),
                "knowledge_gaps": synthesis.get("knowledge_gaps", []),
                "new_entities": synthesis.get("new_entities", []),
            }}
            yield {"type": "progress", "progress": 0.65, "message": "Synthesis complete"}

        # 5. REPORT
        if start_stage <= self._stage_index("report"):
            sources = self.db.get_sources(session_id)  # refresh
            # Ensure synthesis is available (rebuild if resuming past synthesizing)
            if not synthesis and sources:
                synthesizer = ResearchSynthesizer(self.wiki, self.config)
                synthesis = await synthesizer.synthesize(sources)
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
        sources = self.db.get_sources(session_id)  # final refresh
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
        from ....core.prompt_registry import PromptRegistry
        registry = PromptRegistry(provider="openai")

        wiki_index = ""
        if self.wiki.index_file.exists():
            wiki_index = self.wiki.index_file.read_text()[:3000]

        messages = registry.get_messages(
            "research_plan",
            query=query,
            wiki_index=wiki_index[:2000] if wiki_index else "",
        )
        api_params = registry.get_api_params("research_plan")

        try:
            import asyncio
            import json as json_mod

            def _call_llm():
                raw = self._planning_llm.chat(
                    messages,
                    json_mode=api_params.get("json_mode", True),
                    max_tokens=api_params.get("max_tokens", 2048),
                    temperature=api_params.get("temperature", 0.3),
                )
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
        return {"type": "step", "step": step, "message": message, "session_id": self.session_manager.session_id}
