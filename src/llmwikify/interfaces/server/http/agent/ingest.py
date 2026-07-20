"""Ingest 路由 — 数据导入日志。"""

from __future__ import annotations

from fastapi import Request

from llmwikify.interfaces.server.http._helpers import get_wiki_id
from llmwikify.interfaces.server.http.agent._common import (
    get_agent_service,
    router,
)


@router.get("/ingest/log")
async def ingest_log(request: Request, limit: int = 20):
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.get_ingest_log(wiki_id, limit)


@router.get("/ingest/log/{ingest_id}")
async def ingest_changes(ingest_id: str):
    service = get_agent_service()
    return service.get_ingest_entry(ingest_id)


@router.post("/ingest/log/{ingest_id}/revert")
async def revert_ingest(ingest_id: str):
    return {"status": "error", "error": "Revert not implemented - ingest is append-only"}
