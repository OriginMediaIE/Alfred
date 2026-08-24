"""Connector SDK and normalized health contract tests."""
import httpx,pytest
from fastapi import FastAPI
from routes.integration_registry_routes import setup_integration_registry_routes
from services.integration_registry import IntegrationRegistry,IntegrationRegistryError,StaticAdapter,get_integration_registry
from src.auth_helpers import require_user
from src.integration_contract import IntegrationManifest
from services.privacy_service import PrivacyService


def manifest(id="demo"):
    return IntegrationManifest(id=id,name="Demo",version="1.2.3",capabilities=("records",),authentication_method="api_key",permission_scopes=("records.read",),configuration_schema={"type":"object","properties":{"endpoint":{"type":"string"}},"additionalProperties":False},actions=("records.read",),triggers=("integration_event",),rate_limits={"requests_per_minute":60},data_retention="30 days",uninstall_cleanup="revoke and delete local secret")


def test_sdk_validates_identity_and_duplicate_registration():
    registry=IntegrationRegistry();adapter=StaticAdapter(manifest(),lambda owner:{"status":"connected","token":"must-not-leak","last_successful_action":"2026-07-18"});registry.register(adapter)
    assert registry.manifests()[0]["actions"]==["records.read"]
    health=registry.health("alice")[0];assert health["status"]=="connected" and "token" not in health
    with pytest.raises(IntegrationRegistryError):registry.register(adapter)
    with pytest.raises(ValueError):manifest("bad id")


def test_health_reflects_owner_disabled_integrations(tmp_path):
    registry=IntegrationRegistry();registry.register(StaticAdapter(manifest()))
    privacy=PrivacyService(tmp_path/"privacy.json");privacy.update("alice",{"integration_controls":{"demo":False}})
    health=registry.health("alice",privacy_service=privacy)[0]
    assert health["status"]=="disabled" and health["recommended_repair"]


def test_builtin_catalog_covers_every_required_integration_method():
    ids={item["id"] for item in get_integration_registry().manifests()}
    assert {"google-workspace","caldav","imap-smtp","mcp","rest-api","webhooks","local-files","connector-manifests"}<=ids


@pytest.mark.asyncio
async def test_sdk_executes_only_manifest_declared_privacy_enabled_actions(tmp_path):
    class Adapter(StaticAdapter):
        async def execute(self,owner,action,parameters):return {"owner":owner,"action":action,"value":parameters["value"]}
    registry=IntegrationRegistry();registry.register(Adapter(manifest()))
    privacy=PrivacyService(tmp_path/"privacy.json")
    result=await registry.execute("alice","demo","records.read",{"value":7},privacy_service=privacy)
    assert result=={"owner":"alice","action":"records.read","value":7}
    with pytest.raises(IntegrationRegistryError,match="not declared"):
        await registry.execute("alice","demo","records.delete",{},privacy_service=privacy)
    privacy.update("alice",{"integration_controls":{"demo":False}})
    with pytest.raises(Exception,match="disabled"):
        await registry.execute("alice","demo","records.read",{},privacy_service=privacy)


@pytest.mark.asyncio
async def test_registry_routes_are_authenticated_and_metadata_only():
    registry=IntegrationRegistry();registry.register(StaticAdapter(manifest(),lambda owner:{"status":"degraded","password":"hidden","last_error":"timeout","recommended_repair":"Reconnect"}));app=FastAPI();app.dependency_overrides[require_user]=lambda:"alice";app.include_router(setup_integration_registry_routes(registry))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        catalog=(await client.get("/api/integration-registry/catalog")).json();assert catalog["integrations"][0]["authentication_method"]=="api_key"
        health=(await client.get("/api/integration-registry/health")).json()["integrations"][0];assert health["status"]=="degraded" and "password" not in health and health["recommended_repair"]=="Reconnect"
