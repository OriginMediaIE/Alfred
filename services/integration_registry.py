"""Connector registry, manifest validation, and normalized health monitoring."""

from __future__ import annotations
from collections.abc import Mapping
from threading import RLock
from typing import Any,Optional
from src.integration_contract import HEALTH_STATES,IntegrationAdapter,IntegrationManifest


class IntegrationRegistryError(RuntimeError):code="integration_registry_error"


class StaticAdapter:
    def __init__(self,manifest,health_provider=None):self.manifest=manifest;self._health=health_provider
    def health(self,owner):
        if self._health:return self._health(owner)
        return {"status":"not_configured","last_successful_action":None,"last_error":None,"recommended_repair":"Configure this integration in Settings."}
    def uninstall(self,owner):return {"removed":False,"reason":"Use the integration-specific settings flow."}
    async def execute(self,owner,action,parameters):raise IntegrationRegistryError("This integration action is not configured with an executable adapter")


class IntegrationRegistry:
    def __init__(self):self._adapters={};self._lock=RLock()
    def register(self,adapter:IntegrationAdapter):
        manifest=adapter.manifest
        if not isinstance(manifest,IntegrationManifest):raise IntegrationRegistryError("adapter manifest is invalid")
        with self._lock:
            if manifest.id in self._adapters:raise IntegrationRegistryError(f"integration '{manifest.id}' is already registered")
            self._adapters[manifest.id]=adapter
        return manifest
    def replace(self,adapter):
        if not isinstance(adapter.manifest,IntegrationManifest):raise IntegrationRegistryError("adapter manifest is invalid")
        with self._lock:self._adapters[adapter.manifest.id]=adapter
    def unregister(self,integration_id):
        with self._lock:return self._adapters.pop(str(integration_id),None) is not None
    def manifests(self):
        with self._lock:return [adapter.manifest.as_dict() for _,adapter in sorted(self._adapters.items())]
    def health(self,owner,integration_id=None,privacy_service=None):
        with self._lock:
            items=[(integration_id,self._adapters.get(integration_id))] if integration_id else sorted(self._adapters.items())
        output=[]
        for key,adapter in items:
            if adapter is None:raise IntegrationRegistryError("integration not found")
            if privacy_service is not None and not privacy_service.integration_enabled(owner,key):
                output.append({"id":key,"name":adapter.manifest.name,"status":"disabled","last_successful_action":None,"last_error":None,"recommended_repair":"Enable this integration in Privacy settings."})
                continue
            try:value=dict(adapter.health(owner));status=str(value.get("status") or "degraded")
            except Exception as exc:value={"status":"degraded","last_error":type(exc).__name__,"recommended_repair":"Inspect integration configuration and local service logs."};status="degraded"
            if status not in HEALTH_STATES:status="degraded"
            # Health is metadata-only; non-conforming adapters cannot leak secrets.
            safe={k:v for k,v in value.items() if not any(marker in str(k).lower() for marker in ("token","secret","password","api_key","credential"))}
            safe.update({"id":key,"name":adapter.manifest.name,"status":status});output.append(safe)
        return output
    async def execute(self,owner,integration_id,action,parameters,privacy_service=None):
        with self._lock:adapter=self._adapters.get(str(integration_id))
        if adapter is None:raise IntegrationRegistryError("integration not found")
        if privacy_service is not None:privacy_service.require_integration(owner,str(integration_id))
        if str(action) not in adapter.manifest.actions:raise IntegrationRegistryError("integration action is not declared by its manifest")
        result=await adapter.execute(owner,str(action),dict(parameters or {}))
        if not isinstance(result,Mapping):raise IntegrationRegistryError("integration adapter returned an invalid result")
        return dict(result)


def _manifest(id,name,auth,capabilities,actions=(),triggers=(),scopes=(),retention="provider_defined"):
    return IntegrationManifest(id=id,name=name,version="1.0.0",capabilities=tuple(capabilities),authentication_method=auth,permission_scopes=tuple(scopes),configuration_schema={"type":"object","additionalProperties":False},actions=tuple(actions),triggers=tuple(triggers),rate_limits={"policy":"adapter_enforced"},data_retention=retention)


def _google_health(owner):
    from src.google_connection import get_google_connection_service
    rows=get_google_connection_service().list_connections(owner)
    if not rows:return {"status":"not_configured","recommended_repair":"Connect a Google account in Settings."}
    states={row.get("status") for row in rows}
    if "connected" in states:return {"status":"connected","accounts":len([row for row in rows if row.get("status")=="connected"]),"last_successful_action":max((row.get("last_successful_sync") or "" for row in rows),default="") or None,"last_error":next((row.get("last_sync_error") for row in rows if row.get("last_sync_error")),None),"recommended_repair":None}
    state="authentication_failed" if "error" in states else "expired" if "expired" in states else "disconnected"
    return {"status":state,"last_error":next((row.get("last_sync_error") for row in rows if row.get("last_sync_error")),None),"recommended_repair":"Reconnect the Google account in Settings."}


_registry:Optional[IntegrationRegistry]=None
def get_integration_registry():
    global _registry
    if _registry is None:
        registry=IntegrationRegistry()
        registry.register(StaticAdapter(_manifest("google-workspace","Google Workspace","oauth2",("gmail","calendar"),("email.read","email.draft","email.send","calendar.read","calendar.write"),("new_email","calendar_before_event"),("gmail.readonly","gmail.modify","calendar.events")),_google_health))
        registry.register(StaticAdapter(_manifest("caldav","CalDAV","basic",("calendar",),("calendar.read","calendar.write"),("calendar_before_event",))))
        registry.register(StaticAdapter(_manifest("imap-smtp","IMAP / SMTP","basic",("email",),("email.read","email.draft","email.send"),("new_email",))))
        registry.register(StaticAdapter(_manifest("mcp","Model Context Protocol","token",("tools","resources","prompts"),("mcp.call",),("integration_event",),retention="server_manifest_defined")))
        registry.register(StaticAdapter(_manifest("rest-api","REST APIs","api_key",("external_api",),("integration.call",),("conditional_polling","integration_event"))))
        registry.register(StaticAdapter(_manifest("webhooks","Signed Webhooks","token",("inbound_events","outbound_events"),("webhook.send",),("webhook",))))
        registry.register(StaticAdapter(_manifest("local-files","Local Files and Import/Export","none",("file_watcher","import","export"),("file.read","file.import","data.export"),("file_added",),retention="local_owner_controlled")))
        registry.register(StaticAdapter(_manifest("connector-manifests","Connector Manifest SDK","none",("plugins","connector_manifests"),("connector.register","connector.uninstall"),("integration_event",))))
        _registry=registry
    return _registry
