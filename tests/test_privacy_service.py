import pytest
from services.privacy_service import PrivacyError,PrivacyService

def test_privacy_defaults_are_conservative_and_owner_scoped(tmp_path):
    service=PrivacyService(tmp_path/"privacy.json")
    defaults=service.get("alice")
    assert defaults["telemetry_enabled"] is False and defaults["model_logging_enabled"] is False and defaults["sensitive_data_redaction"] is True
    service.update("alice",{"local_only_mode":True,"transcript_retention_days":30})
    assert service.get("alice")["local_only_mode"] is True and service.get("bob")["local_only_mode"] is False

def test_local_only_filters_remote_providers(tmp_path):
    service=PrivacyService(tmp_path/"privacy.json");service.update("alice",{"local_only_mode":True})
    candidates=[("https://api.openai.com/v1","remote",{}),("http://127.0.0.1:11434/v1","local",{})]
    assert service.route_candidates("alice",candidates)==[candidates[1]]

def test_local_only_shared_guard_and_integration_controls(tmp_path):
    service=PrivacyService(tmp_path/"privacy.json")
    service.update("alice",{"local_only_mode":True,"integration_controls":{"rest-api":False}})
    service.ensure_local_endpoint("alice","http://127.0.0.1:11434",purpose="rewrite")
    with pytest.raises(PrivacyError,match="Local-only mode"):
        service.ensure_local_endpoint("alice","https://api.example.com/v1",purpose="rewrite")
    assert service.integration_enabled("alice","google-workspace") is True
    assert service.integration_enabled("alice","rest-api") is False
    with pytest.raises(PrivacyError,match="disabled"):
        service.require_integration("alice","rest-api")

def test_privacy_rejects_unknown_and_invalid_retention(tmp_path):
    service=PrivacyService(tmp_path/"privacy.json")
    with pytest.raises(PrivacyError):service.update("alice",{"mystery":True})
    with pytest.raises(PrivacyError):service.update("alice",{"file_retention_days":0})
    with pytest.raises(PrivacyError):service.update("alice",{"integration_controls":{"mcp":"no"}})
