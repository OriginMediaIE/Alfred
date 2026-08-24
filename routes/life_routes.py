"""HTTP API for relationship, personal administration, and travel records."""
from typing import Any, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from services.life_service import LifeError, get_life_service
from src.auth_helpers import require_user

Kind=Literal["relationship","admin","trip","travel_item"]
class Body(BaseModel): model_config=ConfigDict(extra="forbid")
class CreateBody(Body): kind:Kind;record:dict[str,Any]
class UpdateBody(Body): record:dict[str,Any];revision:int=Field(ge=1)
class DeleteBody(Body): revision:int=Field(ge=1);confirm:Literal[True]
def _raise(exc):
    status=404 if getattr(exc,"code","")=="life_not_found" else 409 if getattr(exc,"code","")=="life_conflict" else 422
    raise HTTPException(status,detail={"code":getattr(exc,"code","life_error"),"message":str(exc)}) from exc

def setup_life_routes(service=None):
    api=service or get_life_service();router=APIRouter(prefix="/api/life",tags=["personal-life"])
    @router.get("")
    async def list_records(kind:Kind,status:Optional[str]=None,trip_id:Optional[str]=None,limit:int=Query(100,ge=1,le=500),owner:str=Depends(require_user)):
        try:return {"records":api.list(owner,kind,status=status,trip_id=trip_id,limit=limit)}
        except LifeError as exc:_raise(exc)
    @router.get("/{kind}/{record_id}")
    async def get_record(kind:Kind,record_id:str,owner:str=Depends(require_user)):
        try:return {"record":api.get(owner,kind,record_id)}
        except LifeError as exc:_raise(exc)
    @router.post("")
    async def create_record(body:CreateBody,owner:str=Depends(require_user)):
        try:return {"record":api.create(owner,body.kind,body.record)}
        except LifeError as exc:_raise(exc)
    @router.put("/{kind}/{record_id}")
    async def update_record(kind:Kind,record_id:str,body:UpdateBody,owner:str=Depends(require_user)):
        try:return {"record":api.update(owner,kind,record_id,body.record,body.revision)}
        except LifeError as exc:_raise(exc)
    @router.delete("/{kind}/{record_id}")
    async def delete_record(kind:Kind,record_id:str,body:DeleteBody,owner:str=Depends(require_user)):
        try:return api.delete(owner,kind,record_id,body.revision)
        except LifeError as exc:_raise(exc)
    return router
