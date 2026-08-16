"""REST endpoints for the self-maintenance subsystem.

The MaintenanceManager instance is created by the server lifespan and
attached to ``app.state.maintenance_manager``. All endpoints degrade to
503 when maintenance is disabled or not yet started.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


def _get_manager(request: Request):
    manager = getattr(request.app.state, "maintenance_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="maintenance not running (disabled by config or not started)",
        )
    return manager


@router.get("/health")
async def maintenance_health(request: Request) -> dict:
    """Aggregated health report: per-wiki status + history trend."""
    return _get_manager(request).health_report()


@router.get("/status")
async def maintenance_status(request: Request) -> dict:
    """Current task runtime status (no history)."""
    return _get_manager(request).status()


@router.post("/trigger")
async def maintenance_trigger(request: Request, task: str = "all") -> dict:
    """Manually trigger a maintenance task: gaps | db | lint | all."""
    manager = _get_manager(request)
    result = await manager.trigger(task)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/proposals")
async def maintenance_proposals(request: Request, status: str = "pending", wiki_id: str | None = None) -> dict:
    """List maintenance proposals (fallback proposals from auto_ingest + gap_filler)."""
    manager = _get_manager(request)
    db = manager._get_proposal_db()
    if db is None:
        return {"proposals": [], "db_available": False}
    try:
        proposals = db.get_dream_proposals(wiki_id, status=status)
        return {"proposals": proposals, "db_available": True}
    except Exception as e:
        return {"proposals": [], "error": str(e)}


@router.post("/proposals/approve")
async def maintenance_approve_proposals(request: Request) -> dict:
    """Batch approve proposals by IDs."""
    from starlette.requests import Request as StarletteRequest
    body = await request.json()
    proposal_ids = body.get("ids", [])
    if not proposal_ids:
        raise HTTPException(status_code=400, detail="ids list required")
    manager = _get_manager(request)
    db = manager._get_proposal_db()
    if db is None:
        raise HTTPException(status_code=503, detail="proposal DB not available")
    approved = 0
    for pid in proposal_ids:
        try:
            db.update_dream_proposal_status(pid, "approved")
            approved += 1
        except Exception:
            pass
    return {"approved": approved, "total": len(proposal_ids)}


@router.post("/proposals/reject")
async def maintenance_reject_proposals(request: Request) -> dict:
    """Batch reject proposals by IDs."""
    body = await request.json()
    proposal_ids = body.get("ids", [])
    if not proposal_ids:
        raise HTTPException(status_code=400, detail="ids list required")
    manager = _get_manager(request)
    db = manager._get_proposal_db()
    if db is None:
        raise HTTPException(status_code=503, detail="proposal DB not available")
    rejected = 0
    for pid in proposal_ids:
        try:
            db.update_dream_proposal_status(pid, "rejected")
            rejected += 1
        except Exception:
            pass
    return {"rejected": rejected, "total": len(proposal_ids)}


def register_maintenance_routes(app) -> None:
    """Mount maintenance routes (called from routes.py)."""
    app.include_router(router)
