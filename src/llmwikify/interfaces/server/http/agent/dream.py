"""Wiki Dream 路由 — 提案管理。"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from llmwikify.interfaces.server.http._helpers import get_wiki_id
from llmwikify.interfaces.server.http._models import (
    ApplyProposalsRequest,
    BatchApproveProposalsRequest,
)
from llmwikify.interfaces.server.http.agent._common import (
    JsonBodyHelper,
    get_agent_service,
    router,
)


@router.get("/wiki-dream/log")
async def dream_log(request: Request, limit: int = 20) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.get_wiki_dream_log(wiki_id, limit)


@router.post("/wiki-dream/run")
async def dream_run(request: Request) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return await service.run_wiki_dream(wiki_id)


@router.get("/wiki-dream/proposals")
async def dream_proposals(request: Request) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    return service.get_wiki_dream_proposals(wiki_id)


@router.post("/wiki-dream/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str) -> Any:
    service = get_agent_service()
    return service.approve_wiki_dream_proposal(proposal_id)


@router.post("/wiki-dream/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str) -> Any:
    service = get_agent_service()
    return service.reject_wiki_dream_proposal(proposal_id)


@router.post("/wiki-dream/proposals/batch-approve")
async def batch_approve_proposals(request: Request) -> Any:
    req = await JsonBodyHelper.execute(request, BatchApproveProposalsRequest)
    service = get_agent_service()
    return service.batch_approve_wiki_dream_proposals(req.ids)


@router.post("/wiki-dream/proposals/apply")
async def apply_proposals(request: Request) -> Any:
    req = await JsonBodyHelper.execute(request, ApplyProposalsRequest)
    service = get_agent_service()
    return await service.apply_wiki_dream_proposals(req.wiki_id, req.ids)
