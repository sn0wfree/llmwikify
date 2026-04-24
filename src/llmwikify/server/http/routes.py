"""FastAPI route definitions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request, HTTPException, Depends

from llmwikify.core import Wiki


def register_routes(app: FastAPI, wiki: Wiki, agent: Any | None = None) -> None:
    """Register all API routes."""

    def get_wiki() -> Wiki:
        return wiki

    def get_agent() -> Any:
        if agent is None:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        return agent

    wiki_router = APIRouter(prefix="/api/wiki", tags=["wiki"])

    @wiki_router.get("/status")
    async def wiki_status(wiki: Wiki = Depends(get_wiki)):
        """Get wiki status summary."""
        status = wiki.status()
        if "pages_by_type" in status:
            status["all_types"] = list(status["pages_by_type"].keys())
        return status

    @wiki_router.get("/search")
    async def wiki_search(q: str, limit: int = 10, wiki: Wiki = Depends(get_wiki)):
        """Full-text search across wiki pages."""
        return wiki.search(q, limit)

    @wiki_router.get("/page/{page_name:path}")
    async def wiki_read_page(page_name: str, wiki: Wiki = Depends(get_wiki)):
        """Read a wiki page (supports wiki/.sink/ files)."""
        try:
            page_data = wiki.read_page(page_name)
            if isinstance(page_data, dict) and "error" in page_data:
                raise HTTPException(status_code=404, detail=page_data["error"])
            sink_info = wiki.query_sink.get_info_for_page(page_name)
            if isinstance(page_data, dict):
                return {**page_data, **sink_info}
            return page_data
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @wiki_router.post("/page")
    async def wiki_write_page(request: Request, wiki: Wiki = Depends(get_wiki)):
        """Write a wiki page."""
        body = await request.json()
        page_name = body.get("page_name", "")
        content = body.get("content", "")
        if not page_name:
            raise HTTPException(status_code=400, detail="page_name required")
        result = wiki.write_page(page_name, content)
        return {"message": result, "page_name": page_name}

    @wiki_router.get("/sink/status")
    async def wiki_sink_status(wiki: Wiki = Depends(get_wiki)):
        """Get sink buffer status."""
        return wiki.sink_status()

    @wiki_router.get("/lint")
    async def wiki_lint(
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
        wiki: Wiki = Depends(get_wiki),
    ):
        """Health-check the wiki (broken links, orphans, schema gaps)."""
        return wiki.lint(mode=mode, limit=limit, force=force)

    @wiki_router.get("/recommend")
    async def wiki_recommend(wiki: Wiki = Depends(get_wiki)):
        """Get wiki recommendations (missing pages, orphans)."""
        return wiki.recommend()

    @wiki_router.get("/suggest_synthesis")
    async def wiki_suggest_synthesis(source_name: str | None = None, wiki: Wiki = Depends(get_wiki)):
        """Get cross-source synthesis suggestions."""
        return wiki.suggest_synthesis(source_name=source_name)

    @wiki_router.get("/graph_analyze")
    async def wiki_graph_analyze(wiki: Wiki = Depends(get_wiki)):
        """Analyze knowledge graph structure (PageRank, communities, suggestions)."""
        return wiki.graph_analyze()

    @wiki_router.get("/graph")
    async def wiki_graph(
        current_page: str | None = None,
        mode: str = "auto",
        wiki: Wiki = Depends(get_wiki),
    ):
        """Return graph data optimized for visualization.

        Uses shared graph_visualizer module - single source of truth.
        """
        from llmwikify.core.graph_visualizer import build_visualization_data
        return build_visualization_data(wiki.index, wiki, current_page, mode)

    app.include_router(wiki_router)

    if agent:
        agent_router = APIRouter(prefix="/api/agent", tags=["agent"])

        @agent_router.post("/chat")
        async def agent_chat(request: Request, agent: Any = Depends(get_agent)):
            """Send a message to the agent."""
            body = await request.json()
            message = body.get("message", "")
            try:
                result = await agent.chat(message)
                return result
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @agent_router.get("/status")
        async def agent_status(agent: Any = Depends(get_agent)):
            """Get agent status."""
            return agent.get_status()

        @agent_router.get("/tools")
        async def agent_tools(agent: Any = Depends(get_agent)):
            """List available agent tools."""
            return agent.list_tools()

        @agent_router.get("/notifications")
        async def agent_notifications(agent: Any = Depends(get_agent)):
            """List notifications."""
            return agent.get_notifications()

        @agent_router.post("/notifications/{id}/read")
        async def notification_mark_read(id: str, agent: Any = Depends(get_agent)):
            """Mark notification as read."""
            return agent.mark_notification_read(id)

        @agent_router.get("/confirmations")
        async def confirmations_list(agent: Any = Depends(get_agent)):
            """List pending confirmations."""
            return agent.get_pending_confirmations()

        @agent_router.post("/confirmations/{id}")
        async def confirmation_approve(id: str, agent: Any = Depends(get_agent)):
            """Approve a confirmation."""
            return agent.approve_confirmation(id)

        @agent_router.delete("/confirmations/{id}")
        async def confirmation_reject(id: str, agent: Any = Depends(get_agent)):
            """Reject a confirmation."""
            return agent.reject_confirmation(id)

        @agent_router.post("/confirmations/batch")
        async def confirmations_batch(request: Request, agent: Any = Depends(get_agent)):
            """Batch approve confirmations."""
            body = await request.json()
            ids = body.get("ids", [])
            return agent.batch_approve_confirmations(ids)

        @agent_router.get("/dream/log")
        async def dream_log(agent: Any = Depends(get_agent)):
            """Get dream editor log."""
            return agent.get_dream_log()

        @agent_router.post("/dream/run")
        async def dream_run(request: Request, agent: Any = Depends(get_agent)):
            """Run dream editor."""
            body = await request.json()
            prompt = body.get("prompt", "")
            return await agent.run_dream(prompt)

        @agent_router.get("/dream/proposals")
        async def dream_proposals(agent: Any = Depends(get_agent)):
            """List dream proposals."""
            return agent.get_dream_proposals()

        @agent_router.post("/dream/proposals/{id}/approve")
        async def dream_proposal_approve(id: str, agent: Any = Depends(get_agent)):
            """Approve a dream proposal."""
            return agent.approve_dream_proposal(id)

        @agent_router.post("/dream/proposals/{id}/reject")
        async def dream_proposal_reject(id: str, agent: Any = Depends(get_agent)):
            """Reject a dream proposal."""
            return agent.reject_dream_proposal(id)

        @agent_router.post("/dream/proposals/batch-approve")
        async def dream_proposals_batch_approve(request: Request, agent: Any = Depends(get_agent)):
            """Batch approve dream proposals."""
            body = await request.json()
            ids = body.get("ids", [])
            return agent.batch_approve_dream_proposals(ids)

        @agent_router.post("/dream/proposals/apply")
        async def dream_proposals_apply(request: Request, agent: Any = Depends(get_agent)):
            """Apply dream proposals to wiki."""
            body = await request.json()
            ids = body.get("ids", None)
            return await agent.apply_dream_proposals(ids)

        @agent_router.get("/ingest/log")
        async def ingest_log_list(agent: Any = Depends(get_agent)):
            """List ingest log entries."""
            return agent.get_ingest_log()

        @agent_router.get("/ingest/log/{id}")
        async def ingest_log_detail(id: str, agent: Any = Depends(get_agent)):
            """Get ingest log detail."""
            return agent.get_ingest_log_entry(id)

        @agent_router.post("/ingest/log/{id}/revert")
        async def ingest_log_revert(id: str, agent: Any = Depends(get_agent)):
            """Revert an ingest operation."""
            return agent.revert_ingest(id)

        app.include_router(agent_router)
