from typing import Any,Optional
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict
from services.privacy_service import PrivacyError,get_privacy_service
from src.auth_helpers import require_user
class PrivacyUpdate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    local_only_mode:Optional[bool]=None;provider_routing_visibility:Optional[bool]=None;conversation_retention_days:Optional[int]=None;email_retention_days:Optional[int]=None;transcript_retention_days:Optional[int]=None;file_retention_days:Optional[int]=None;memory_retention_days:Optional[int]=None;model_logging_enabled:Optional[bool]=None;telemetry_enabled:Optional[bool]=None;sensitive_data_redaction:Optional[bool]=None;integration_controls:Optional[dict[str,bool]]=None
class PurgeRequest(BaseModel):
    confirm: bool = False

def setup_privacy_routes(service=None,retention_service=None):
    privacy=service or get_privacy_service();router=APIRouter(prefix="/api/privacy",tags=["privacy"])
    @router.get("")
    async def get(owner:str=Depends(require_user)):return privacy.get(owner)
    @router.put("")
    async def update(body:PrivacyUpdate,owner:str=Depends(require_user)):
        try:return privacy.update(owner,body.model_dump(exclude_unset=True))
        except PrivacyError as exc:raise HTTPException(422,str(exc)) from exc
    if retention_service is not None:
        @router.post("/purge-expired")
        async def purge_expired(body:PurgeRequest,owner:str=Depends(require_user)):
            if body.confirm is not True:raise HTTPException(422,"Explicit purge confirmation is required")
            return await retention_service.purge_owner(owner)
    return router
