"""Read-only connector catalogue and normalized health API."""
from typing import Optional
from fastapi import APIRouter,Depends,HTTPException
from services.integration_registry import IntegrationRegistryError,get_integration_registry
from src.auth_helpers import require_user


def setup_integration_registry_routes(registry=None):
    integrations=registry or get_integration_registry();router=APIRouter(prefix="/api/integration-registry",tags=["integration-registry"])
    @router.get("/catalog")
    async def catalog(owner:str=Depends(require_user)):
        from services.privacy_service import get_privacy_service
        privacy=get_privacy_service()
        return {"integrations":[{**item,"enabled":privacy.integration_enabled(owner,item["id"])} for item in integrations.manifests()]}
    @router.get("/health")
    async def health(integration_id:Optional[str]=None,owner:str=Depends(require_user)):
        from services.privacy_service import get_privacy_service
        try:return {"integrations":integrations.health(owner,integration_id,get_privacy_service())}
        except IntegrationRegistryError as exc:raise HTTPException(404,{"code":exc.code,"message":str(exc)}) from exc
    return router
