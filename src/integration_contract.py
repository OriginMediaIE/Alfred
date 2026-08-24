"""Public connector SDK contract for OM Automate integrations."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

AUTH_METHODS=frozenset({"none","oauth2","api_key","basic","token","local_socket","client_certificate"})
HEALTH_STATES=frozenset({"connected","disconnected","disabled","expired","degraded","rate_limited","authentication_failed","not_configured"})


@dataclass(frozen=True,slots=True)
class IntegrationManifest:
    id:str;name:str;version:str;capabilities:tuple[str,...];authentication_method:str;permission_scopes:tuple[str,...]=();configuration_schema:Mapping[str,Any]=field(default_factory=dict);actions:tuple[str,...]=();triggers:tuple[str,...]=();rate_limits:Mapping[str,Any]=field(default_factory=dict);data_retention:str="provider_defined";uninstall_cleanup:str="disconnect_and_remove_local_secrets"
    def __post_init__(self):
        if not self.id or len(self.id)>100 or not all(ch.isalnum() or ch in "._-" for ch in self.id):raise ValueError("integration id is invalid")
        if not self.name or len(self.name)>200 or not self.version:raise ValueError("integration name/version are required")
        if self.authentication_method not in AUTH_METHODS:raise ValueError("authentication method is invalid")
        if self.configuration_schema.get("type") not in (None,"object"):raise ValueError("configuration schema must describe an object")
        for collection in (self.capabilities,self.permission_scopes,self.actions,self.triggers):
            if len(collection)>200 or any(not isinstance(item,str) or not item or len(item)>200 for item in collection):raise ValueError("manifest collection is invalid")
    def as_dict(self):return {"id":self.id,"name":self.name,"version":self.version,"capabilities":list(self.capabilities),"authentication_method":self.authentication_method,"permission_scopes":list(self.permission_scopes),"configuration_schema":dict(self.configuration_schema),"actions":list(self.actions),"triggers":list(self.triggers),"rate_limits":dict(self.rate_limits),"data_retention":self.data_retention,"uninstall_cleanup":self.uninstall_cleanup}


class IntegrationAdapter(Protocol):
    manifest:IntegrationManifest
    def health(self,owner:str|None)->Mapping[str,Any]:...
    async def execute(self,owner:str|None,action:str,parameters:Mapping[str,Any])->Mapping[str,Any]:...
    def uninstall(self,owner:str|None)->Mapping[str,Any]:...
