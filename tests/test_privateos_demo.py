from services.privateos_demo_service import PrivateOSDemoService


def test_privateos_demo_is_synthetic_idempotent_and_installs_three_routines(tmp_path):
    service=PrivateOSDemoService(tmp_path)
    try:
        first=service.seed("alice");second=service.seed("alice")
        assert first["synthetic"] is True and first["routine_count"]==3
        assert second["project_id"]==first["project_id"]
        assert second["meeting_id"]==first["meeting_id"]
        assert second["knowledge_source_id"]==first["knowledge_source_id"]
        assert len(service.work.list_projects("alice"))==1
        assert len(service.automations.list("alice"))==3
    finally:service.close()
