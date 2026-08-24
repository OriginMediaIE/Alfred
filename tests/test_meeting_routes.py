"""ASGI coverage for the owner-facing meetings API."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from routes.meeting_routes import setup_meeting_routes
from services.meeting_analysis import RuleBasedMeetingAnalyzer
from services.meeting_service import MeetingService
from src.auth_helpers import require_user
from src.meeting_contract import TranscriptionResult, TranscriptionSegmentResult
from src.meeting_models import MeetingBase, ensure_meeting_schema


class _Provider:
    name = "route-local"
    version = "1"

    def health(self):
        return {"status": "available", "provider": self.name, "local_only": True}

    def capabilities(self):
        return {"streaming": False, "stable_realtime": False}

    def transcribe(self, media_path, config, *, cancel_requested, progress):
        progress(50)
        return TranscriptionResult(
            segments=(
                TranscriptionSegmentResult(
                    text="Action: send the approved brief.",
                    start_ms=100,
                    end_ms=900,
                    speaker_label=None,
                ),
            ),
            language="en",
            duration_ms=900,
            provider=self.name,
            provider_version=self.version,
            model=config.model,
        )


@pytest.fixture
def route_env(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_meeting_schema(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    service = MeetingService(
        session_factory=factory,
        storage_root=tmp_path / "media",
        transcription_provider=_Provider(),
        analyzer=RuleBasedMeetingAnalyzer(),
    )
    owner = {"value": "alice"}
    app = FastAPI()
    app.dependency_overrides[require_user] = lambda: owner["value"]
    app.include_router(setup_meeting_routes(service))
    try:
        yield app, service, owner
    finally:
        MeetingBase.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.asyncio
async def test_route_workflow_upload_queue_process_and_edit(route_env):
    app, service, _owner = route_env
    transport = httpx.ASGITransport(app=app)
    wav = b"RIFF" + (9).to_bytes(4, "little") + b"WAVEaudio"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created_response = await client.post(
            "/api/meetings",
            json={"title": "Route review", "source_type": "browser_recording"},
        )
        assert created_response.status_code == 200
        meeting = created_response.json()

        denied = await client.post(
            f"/api/meetings/{meeting['id']}/media",
            files={"file": ("recording.wav", wav, "audio/wav")},
            data={"consent_confirmed": "false"},
        )
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "recording_consent_required"

        uploaded = await client.post(
            f"/api/meetings/{meeting['id']}/media",
            files={"file": ("recording.wav", wav, "audio/wav")},
            data={"consent_confirmed": "true"},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["media"]["available"] is True

        queued = await client.post(
            f"/api/meetings/{meeting['id']}/transcription-jobs",
            headers={"Idempotency-Key": "route-job"},
            json={"model": "base", "audio_retention_days": 1},
        )
        assert queued.status_code == 200
        job = queued.json()
        assert service.run_job("alice", job["id"])["status"] == "succeeded"

        full = (await client.get(f"/api/meetings/{meeting['id']}")).json()
        assert full["segments"][0]["trust_classification"] == "untrusted_user_content"
        assert full["claims"][0]["evidence"][0]["start_ms"] == 100
        segment = full["segments"][0]
        edited = await client.patch(
            f"/api/meetings/{meeting['id']}/segments/{segment['id']}",
            json={"text": "Action: send the final brief.", "revision": segment["revision"]},
        )
        assert edited.status_code == 200
        assert edited.json()["is_edited"] is True


@pytest.mark.asyncio
async def test_route_owner_isolation_confirmation_and_strict_bodies(route_env):
    app, _service, owner = route_env
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = (await client.post("/api/meetings", json={"title": "Private"})).json()
        bad = await client.post(
            "/api/meetings",
            json={"title": "Bad", "unexpected": "field"},
        )
        assert bad.status_code == 422

        owner["value"] = "bob"
        assert (await client.get("/api/meetings")).json()["meetings"] == []
        hidden = await client.get(f"/api/meetings/{created['id']}")
        assert hidden.status_code == 404

        owner["value"] = "alice"
        missing_confirmation = await client.post(
            f"/api/meetings/{created['id']}/delete",
            json={"confirm": False},
        )
        assert missing_confirmation.status_code == 422
        deleted = await client.post(
            f"/api/meetings/{created['id']}/delete",
            json={"confirm": True, "purge_record": False},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_provider_metadata_never_claims_realtime(route_env):
    app, _service, _owner = route_env
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        metadata = (await client.get("/api/meetings/meta")).json()
        provider = (await client.get("/api/meetings/provider")).json()
    assert metadata["transcription"]["stable_realtime"] is False
    assert provider["limits"]["stable_realtime"] is False
    assert "token" not in str(provider).lower()
