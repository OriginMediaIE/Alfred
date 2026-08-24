"""Strict owner-scoped API for validated structured automations."""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from services.automation_service import AutomationError, AutomationService, get_automation_service
from src.auth_helpers import require_user


class Strict(BaseModel): model_config=ConfigDict(extra="forbid")
class DefinitionBody(Strict):
    name:str=Field(min_length=1,max_length=300);description:str=Field("",max_length=2000);trigger:dict[str,Any];conditions:list[dict[str,Any]]=Field(default_factory=list,max_length=25);actions:list[dict[str,Any]]=Field(min_length=1,max_length=25);limits:dict[str,Any]=Field(default_factory=dict)
class StatusBody(Strict): status:Literal["enabled","paused"]
class RunBody(Strict): inputs:dict[str,Any]=Field(default_factory=dict);dedupe_key:Optional[str]=Field(None,max_length=300)
class EventBody(Strict): event_type:str=Field(min_length=1,max_length=80);payload:dict[str,Any]=Field(default_factory=dict);dedupe_key:str=Field(min_length=1,max_length=300);correlation_id:Optional[str]=Field(None,max_length=100)
class DeleteBody(Strict): confirm:Literal[True];version:int=Field(ge=1)
class ConfirmBody(Strict): confirm:Literal[True]


def fail(exc):
    code=getattr(exc,"code","automation_error"); status=404 if code=="automation_not_found" else 409 if code in {"automation_conflict","automation_loop_detected","automation_rate_limited","automation_state_error"} else 422
    raise HTTPException(status,detail={"code":code,"message":str(exc)}) from exc


def setup_automation_routes(service:Optional[AutomationService]=None):
    automations=service or get_automation_service();router=APIRouter(prefix="/api/automations",tags=["automations"])
    @router.post("")
    async def create(body:DefinitionBody,owner:str=Depends(require_user)):
        try:return automations.create(owner,body.model_dump())
        except AutomationError as exc:fail(exc)
    @router.get("")
    async def list_definitions(owner:str=Depends(require_user)):return {"automations":automations.list(owner)}
    @router.get("/templates")
    async def list_templates(owner:str=Depends(require_user)):return {"templates":automations.routine_templates(owner)}
    @router.post("/templates/{routine_key}")
    async def install_template(routine_key:str,body:ConfirmBody,owner:str=Depends(require_user)):
        try:return automations.install_routine(owner,routine_key)
        except AutomationError as exc:fail(exc)
    @router.get("/metrics")
    async def metrics(days:int=Query(30,ge=1,le=365),owner:str=Depends(require_user)):
        return automations.operating_metrics(owner,since=datetime.now(timezone.utc)-timedelta(days=days))
    @router.get("/runs")
    async def list_runs(automation_id:Optional[str]=None,limit:int=Query(100,ge=1,le=500),owner:str=Depends(require_user)):return {"runs":automations.list_runs(owner,automation_id,limit)}
    @router.get("/runs/{run_id}")
    async def get_run(run_id:str,owner:str=Depends(require_user)):
        try:return automations.get_run(owner,run_id)
        except AutomationError as exc:fail(exc)
    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id:str,body:ConfirmBody,owner:str=Depends(require_user)):
        try:return automations.cancel_run(owner,run_id)
        except AutomationError as exc:fail(exc)
    @router.post("/runs/{run_id}/retry")
    async def retry_run(run_id:str,body:ConfirmBody,owner:str=Depends(require_user)):
        try:return await automations.retry_run(owner,run_id)
        except AutomationError as exc:fail(exc)
    @router.get("/{automation_id}")
    async def get(automation_id:str,owner:str=Depends(require_user)):
        try:return automations.get(owner,automation_id)
        except AutomationError as exc:fail(exc)
    @router.put("/{automation_id}/status")
    async def status(automation_id:str,body:StatusBody,owner:str=Depends(require_user)):
        try:return automations.set_status(owner,automation_id,body.status)
        except AutomationError as exc:fail(exc)
    @router.post("/{automation_id}/run")
    async def run(automation_id:str,body:RunBody,owner:str=Depends(require_user)):
        try:return await automations.run(owner,automation_id,trigger={"type":"manual"},inputs=body.inputs,dedupe_key=body.dedupe_key)
        except AutomationError as exc:fail(exc)
    @router.post("/events/emit")
    async def emit(body:EventBody,owner:str=Depends(require_user)):
        try:return await automations.emit(owner,body.event_type,body.payload,dedupe_key=body.dedupe_key,correlation_id=body.correlation_id)
        except AutomationError as exc:fail(exc)
    @router.delete("/{automation_id}")
    async def delete(automation_id:str,body:DeleteBody,owner:str=Depends(require_user)):
        try:return automations.delete(owner,automation_id,body.version)
        except AutomationError as exc:fail(exc)
    return router


def setup_automation_webhook_routes(service:Optional[AutomationService]=None):
    automations=service or get_automation_service();router=APIRouter(prefix="/api/automation-hooks",tags=["automation-webhooks"])
    @router.post("/{automation_id}")
    async def inbound(automation_id:str,request:Request,x_om_timestamp:str=Header(alias="X-OM-Timestamp",max_length=20),x_om_signature:str=Header(alias="X-OM-Signature",max_length=100),x_om_delivery_id:str=Header(alias="X-OM-Delivery-ID",max_length=100)):
        length=request.headers.get("content-length")
        if length and int(length)>1024*1024:raise HTTPException(413,"Webhook payload exceeds 1 MiB")
        body=await request.body()
        try:return await automations.accept_webhook(automation_id,body,timestamp=x_om_timestamp,signature=x_om_signature,delivery_id=x_om_delivery_id)
        except AutomationError as exc:fail(exc)
    return router
