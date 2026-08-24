"""Read-only Today and briefing endpoints."""

from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from services.executive_service import ExecutiveService, get_executive_service
from services.operational_health import collect_operational_health
from src.auth_helpers import require_user


class BriefingRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: Optional[str] = Field(None, max_length=100)


def setup_dashboard_routes(service: Optional[ExecutiveService] = None) -> APIRouter:
    executive = service or get_executive_service(); router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

    @router.get("/today")
    async def today(request: Request, timezone: Optional[str] = Query(None, max_length=100), owner: str = Depends(require_user)):
        result = await executive.today(owner, timezone_name=timezone)
        try:
            result["local_core_health"] = collect_operational_health(
                request.app.state,
                owner=owner,
                rag_manager=getattr(request.app.state, "rag_manager", None),
                memory_vector=getattr(request.app.state, "memory_vector", None),
            )
        except Exception:
            result["local_core_health"] = [{"name": "application", "status": "degraded", "detail": "Local Core health could not be fully read."}]
        return result

    @router.get("/briefings/runs")
    async def list_briefing_runs(kind: Optional[Literal["morning", "evening", "weekly"]] = None, limit: int = Query(50, ge=1, le=200), owner: str = Depends(require_user)):
        return {"briefings": executive.list_briefings(owner, kind=kind, limit=limit)}

    @router.get("/briefings/runs/{briefing_id}")
    async def get_briefing_run(briefing_id: str, owner: str = Depends(require_user)):
        result = executive.get_briefing(owner, briefing_id)
        if result is None:
            raise HTTPException(404, "Briefing run not found.")
        return result

    @router.get("/briefings/{kind}")
    async def briefing(kind: Literal["morning", "evening", "weekly"], timezone: Optional[str] = Query(None, max_length=100), owner: str = Depends(require_user)):
        try: return await executive.briefing(owner, kind=kind, timezone_name=timezone)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc

    @router.post("/briefings/{kind}/runs", status_code=201)
    async def generate_briefing_run(kind: Literal["morning", "evening", "weekly"], body: BriefingRunBody, owner: str = Depends(require_user)):
        return await executive.generate_briefing(owner, kind=kind, timezone_name=body.timezone)

    @router.get("/metrics")
    async def operating_metrics(days: int = Query(30, ge=1, le=365), owner: str = Depends(require_user)):
        return executive.metrics(owner, days=days)

    return router
