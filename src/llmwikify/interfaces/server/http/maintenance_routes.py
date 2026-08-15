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
    """Manually trigger a maintenance task: gaps | db | all."""
    manager = _get_manager(request)
    result = await manager.trigger(task)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


def register_maintenance_routes(app) -> None:
    """Mount maintenance routes (called from routes.py)."""
    app.include_router(router)
