"""End-to-end service coverage for local meeting transcription and review."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.meeting_analysis import RuleBasedMeetingAnalyzer
from services.meeting_service import (
    MeetingConflict,
    MeetingConsentRequired,
    MeetingDuplicateUpload,
    MeetingNotFound,
    MeetingProviderUnavailable,
    MeetingService,
    MeetingUnsupportedMedia,
    MeetingUploadTooLarge,
)
from services.meeting_worker import MeetingWorker
from src.meeting_contract import (
    TranscriptionConfig,
    TranscriptionResult,
    TranscriptionSegmentResult,
    TranscriptionUnavailable,
)
from src.meeting_models import MeetingBase, MeetingProcessingJob, ensure_meeting_schema
from src.tools import meetings as meeting_tools


class FakeTranscriber:
    name = "fake-local"
    version = "1.0"

    def __init__(self, *, fail: bool = False, multiple_speakers: bool = True):
        self.fail = fail
        self.multiple_speakers = multiple_speakers
        self.calls = []

    def capabilities(self):
        return {"local_only": True, "streaming": False, "diarization": True}

    def health(self):
        return {"status": "available", "provider": self.name, "local_only": True}

    def transcribe(self, media_path, config, *, cancel_requested, progress):
        self.calls.append((Path(media_path), config))
        if self.fail:
            raise TranscriptionUnavailable("poor audio could not be transcribed")
        progress(25)
        second_speaker = "SPEAKER_01" if self.multiple_speakers else None
        return TranscriptionResult(
            segments=(
                TranscriptionSegmentResult(
                    text="Decision: ship the reviewed release on Friday.",
                    start_ms=0,
                    end_ms=2500,
                    speaker_label="SPEAKER_00",
                    confidence=0.93,
                ),
                TranscriptionSegmentResult(
                    text="Action item: prepare the release notes.",
                    start_ms=2600,
                    end_ms=5000,
                    speaker_label=second_speaker,
                    confidence=0.88,
                ),
            ),
            language="en",
            duration_ms=5000,
            provider=self.name,
            provider_version=self.version,
            model=config.model,
            diarization_applied=bool(config.diarization),
        )


class FakeTaskSink:
    def __init__(self):
        self.by_key = {}

    def create_task_from_meeting(self, **values):
        key = values["idempotency_key"]
        if key not in self.by_key:
            self.by_key[key] = {"id": f"task-{len(self.by_key) + 1}", **values}
        return self.by_key[key]


class FakeKnowledgeSink:
    def __init__(self):
        self.by_key = {}

    def ingest_meeting(self, **values):
        key = values["idempotency_key"]
        if key not in self.by_key:
            self.by_key[key] = {"id": f"source-{len(self.by_key) + 1}", **values}
        return self.by_key[key]


@pytest.fixture
def meeting_env(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_meeting_schema(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    transcriber = FakeTranscriber()
    tasks = FakeTaskSink()
    knowledge = FakeKnowledgeSink()
    service = MeetingService(
        session_factory=factory,
        storage_root=tmp_path / "media",
        transcription_provider=transcriber,
        analyzer=RuleBasedMeetingAnalyzer(),
        task_sink=tasks,
        knowledge_sink=knowledge,
        max_upload_bytes=500 * 1024 * 1024,
    )
    try:
        yield service, transcriber, tasks, knowledge, tmp_path
    finally:
        MeetingBase.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.asyncio
async def test_canonical_meeting_tools_fail_closed_then_read_back_owner_state(
    meeting_env, monkeypatch
):
    service, _, _, _, _ = meeting_env
    monkeypatch.setattr(meeting_tools, "get_meeting_service", lambda: service)
    payload = json.dumps({"record": {"title": "Tool-created meeting"}})

    denied = await meeting_tools.do_create_meeting(payload, owner="alice")
    assert denied["exit_code"] == 1
    assert service.list_meetings("alice")["total"] == 0

    monkeypatch.setattr(meeting_tools, "_require_claimed_action", lambda *a, **k: None)
    created = await meeting_tools.do_create_meeting(
        payload,
        owner="alice",
        approval_action_id="approved-create",
        request_id="request-create",
    )
    assert created["exit_code"] == 0
    assert created["verification"]["status"] == "verified"
    meeting_id = created["meeting"]["id"]

    listed = await meeting_tools.do_search_meetings(
        json.dumps({"action": "list", "query": "Tool-created"}), owner="alice"
    )
    assert [item["id"] for item in listed["meetings"]] == [meeting_id]
    other_owner = await meeting_tools.do_search_meetings(
        json.dumps({"action": "get", "meeting_id": meeting_id}), owner="bob"
    )
    assert other_owner["code"] == "meeting_not_found"

    deleted = await meeting_tools.do_delete_meeting(
        json.dumps({"meeting_id": meeting_id}),
        owner="alice",
        approval_action_id="approved-delete",
        request_id="request-delete",
    )
    assert deleted["verification"]["status"] == "verified"
    assert service.list_meetings("alice")["total"] == 0


def wav_bytes(payload: bytes = b"meeting audio") -> bytes:
    return b"RIFF" + (len(payload) + 4).to_bytes(4, "little") + b"WAVE" + payload


async def chunks(*parts: bytes):
    for part in parts:
        yield part


def create_with_media(service, owner="alice", *, title="Weekly review", data=None):
    meeting = service.create_meeting(owner, {"title": title})
    attached = asyncio.run(
        service.attach_media(
            owner,
            meeting["id"],
            filename="review.wav",
            content_type="audio/wav",
            chunks=chunks(data or wav_bytes()),
            consent_confirmed=True,
        )
    )
    return attached


def test_manual_and_calendar_meetings_are_owner_scoped(meeting_env):
    service, *_ = meeting_env
    manual = service.create_meeting("alice", {"title": "Manual notes"})
    linked = service.create_meeting(
        "alice",
        {
            "title": "Calendar call",
            "source_type": "calendar",
            "calendar_event_id": "event-123",
            "attendee_names": ["Sam", "Unknown guest"],
        },
    )

    assert manual["source_type"] == "manual"
    full = service.get_meeting("alice", linked["id"])
    assert full["links"][0]["type"] == "calendar_event"
    assert full["attendee_names"] == ["Sam", "Unknown guest"]
    with pytest.raises(MeetingNotFound):
        service.get_meeting("mallory", manual["id"])


def test_upload_requires_consent_and_valid_media_signature(meeting_env):
    service, *_ = meeting_env
    meeting = service.create_meeting("alice", {"title": "Upload"})
    with pytest.raises(MeetingConsentRequired):
        asyncio.run(
            service.attach_media(
                "alice",
                meeting["id"],
                filename="call.wav",
                content_type="audio/wav",
                chunks=chunks(wav_bytes()),
                consent_confirmed=False,
            )
        )
    with pytest.raises(MeetingUnsupportedMedia):
        asyncio.run(
            service.attach_media(
                "alice",
                meeting["id"],
                filename="call.wav",
                content_type="audio/wav",
                chunks=chunks(b"not a wav"),
                consent_confirmed=True,
            )
        )
    assert not list((meeting_env[-1] / "media").rglob("*.part"))


def test_interrupted_upload_cleans_partial_file(meeting_env):
    service, *_ = meeting_env
    meeting = service.create_meeting("alice", {"title": "Interrupted"})

    async def interrupted():
        yield wav_bytes(b"partial")
        raise RuntimeError("client disconnected")

    with pytest.raises(RuntimeError, match="client disconnected"):
        asyncio.run(
            service.attach_media(
                "alice",
                meeting["id"],
                filename="call.wav",
                content_type="audio/wav",
                chunks=interrupted(),
                consent_confirmed=True,
            )
        )
    assert not list((meeting_env[-1] / "media").rglob("*.part"))


def test_duplicate_upload_is_rejected_per_owner(meeting_env):
    service, *_ = meeting_env
    first = create_with_media(service)
    second = service.create_meeting("alice", {"title": "Duplicate"})
    with pytest.raises(MeetingDuplicateUpload) as exc:
        asyncio.run(
            service.attach_media(
                "alice",
                second["id"],
                filename="same.wav",
                content_type="audio/wav",
                chunks=chunks(wav_bytes()),
                consent_confirmed=True,
            )
        )
    assert exc.value.existing_meeting_id == first["id"]


def test_upload_limit_fails_without_persisting_media(meeting_env):
    service, *_ = meeting_env
    service.max_upload_bytes = 16
    meeting = service.create_meeting("alice", {"title": "Too large"})
    with pytest.raises(MeetingUploadTooLarge):
        asyncio.run(
            service.attach_media(
                "alice",
                meeting["id"],
                filename="large.wav",
                content_type="audio/wav",
                chunks=chunks(wav_bytes(b"x" * 64)),
                consent_confirmed=True,
            )
        )
    assert service.get_meeting("alice", meeting["id"])["media"]["available"] is False


def test_transcription_analysis_preserves_timestamps_speakers_and_evidence(meeting_env):
    service, _provider, *_ = meeting_env
    meeting = create_with_media(service)
    queued = service.enqueue_transcription(
        "alice",
        meeting["id"],
        config={"diarization": True, "timestamp_granularity": "word"},
        idempotency_key="transcribe-weekly-review",
    )
    repeated = service.enqueue_transcription(
        "alice",
        meeting["id"],
        config={"diarization": True, "timestamp_granularity": "word"},
        idempotency_key="transcribe-weekly-review",
    )
    assert repeated["id"] == queued["id"]

    result = service.run_job("alice", queued["id"])
    assert result["status"] == "succeeded"
    full = service.get_meeting("alice", meeting["id"])
    assert full["status"] == "review"
    assert [s["speaker_label"] for s in full["segments"]] == ["SPEAKER_00", "SPEAKER_01"]
    assert [s["start_ms"] for s in full["segments"]] == [0, 2600]
    assert full["transcription"]["trust_classification"] == "untrusted_user_content"
    decisions = [claim for claim in full["claims"] if claim["kind"] == "decision"]
    actions = [claim for claim in full["claims"] if claim["kind"] == "action_item"]
    assert decisions[0]["fact_state"] == "proposed"
    assert decisions[0]["evidence"][0]["segment_id"] == full["segments"][0]["id"]
    assert actions[0]["evidence"][0]["start_ms"] == 2600


def test_transcription_failure_is_durable_and_retryable(meeting_env):
    service, provider, *_ = meeting_env
    provider.fail = True
    meeting = create_with_media(service, title="Poor audio")
    queued = service.enqueue_transcription("alice", meeting["id"])

    failed = service.run_job("alice", queued["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "transcription_unavailable"
    assert service.get_meeting("alice", meeting["id"])["status"] == "failed"
    provider.fail = False
    retry = service.retry_job("alice", queued["id"], idempotency_key="retry-poor-audio")
    assert service.run_job("alice", retry["id"])["status"] == "succeeded"


def test_user_edit_is_versioned_and_requires_explicit_replacement(meeting_env):
    service, *_ = meeting_env
    meeting = create_with_media(service)
    service.update_retention("alice", meeting["id"], audio_days=1, transcript_days=365)
    job = service.enqueue_transcription("alice", meeting["id"])
    service.run_job("alice", job["id"])
    full = service.get_meeting("alice", meeting["id"])
    segment = full["segments"][0]

    edited = service.edit_segment(
        "alice",
        meeting["id"],
        segment["id"],
        {"text": "Decision: ship only after final review."},
        expected_revision=segment["revision"],
    )
    assert edited["is_edited"] is True
    assert service.transcript_revisions("alice", meeting["id"], segment["id"])[0]["prior_text"].startswith("Decision:")
    with pytest.raises(MeetingConflict, match="user edits"):
        service.enqueue_transcription("alice", meeting["id"])


def test_claim_review_creates_one_source_linked_task_and_confirms_decision(meeting_env):
    service, _provider, tasks, *_ = meeting_env
    meeting = create_with_media(service)
    job = service.enqueue_transcription("alice", meeting["id"])
    service.run_job("alice", job["id"])
    full = service.get_meeting("alice", meeting["id"])
    action = next(c for c in full["claims"] if c["kind"] == "action_item")
    decision = next(c for c in full["claims"] if c["kind"] == "decision")

    approved = service.review_claim(
        "alice", meeting["id"], action["id"],
        decision="approve", confirm=True, expected_revision=action["revision"],
    )
    repeated = service.review_claim(
        "alice", meeting["id"], action["id"],
        decision="approve", confirm=True,
    )
    confirmed = service.review_claim(
        "alice", meeting["id"], decision["id"],
        decision="confirm", confirm=True, expected_revision=decision["revision"],
    )
    assert approved["linked_resource"]["type"] == "task"
    assert repeated["linked_resource"] == approved["linked_resource"]
    assert len(tasks.by_key) == 1
    assert next(iter(tasks.by_key.values()))["source"]["evidence"][0]["segment_id"]
    assert confirmed["fact_state"] == "confirmed"


def test_explicit_knowledge_save_is_revision_idempotent(meeting_env):
    service, _provider, _tasks, knowledge, *_ = meeting_env
    meeting = create_with_media(service)
    job = service.enqueue_transcription("alice", meeting["id"])
    service.run_job("alice", job["id"])
    first = service.save_to_knowledge("alice", meeting["id"], confirm=True)
    second = service.save_to_knowledge("alice", meeting["id"], confirm=True)
    assert first["knowledge_source"]["id"] == second["knowledge_source"]["id"]
    assert len(knowledge.by_key) == 1
    assert "[0-2500 ms] SPEAKER_00" in first["knowledge_source"]["content"]


def test_missing_sinks_fail_closed(meeting_env):
    service, *_ = meeting_env
    service.knowledge_sink = None
    meeting = create_with_media(service)
    job = service.enqueue_transcription("alice", meeting["id"])
    service.run_job("alice", job["id"])
    with pytest.raises(MeetingProviderUnavailable):
        service.save_to_knowledge("alice", meeting["id"], confirm=True)


@pytest.mark.asyncio
async def test_worker_processes_durable_queue_and_stops_cleanly(meeting_env):
    service, *_ = meeting_env
    meeting = service.create_meeting("alice", {"title": "Worker review"})
    meeting = await service.attach_media(
        "alice",
        meeting["id"],
        filename="worker.wav",
        content_type="audio/wav",
        chunks=chunks(wav_bytes()),
        consent_confirmed=True,
    )
    queued = service.enqueue_transcription("alice", meeting["id"])
    worker = MeetingWorker(service, poll_seconds=0.05)
    task = asyncio.create_task(worker.run())
    try:
        for _ in range(60):
            if service.get_job("alice", queued["id"])["status"] == "succeeded":
                break
            await asyncio.sleep(0.02)
        assert service.get_job("alice", queued["id"])["status"] == "succeeded"
    finally:
        worker.stop()
        await asyncio.wait_for(task, timeout=2)


def test_worker_requeues_interrupted_jobs_without_resetting_attempt_count(meeting_env):
    service, *_ = meeting_env
    meeting = create_with_media(service)
    queued = service.enqueue_transcription("alice", meeting["id"])
    db = service.session_factory()
    try:
        row = db.get(MeetingProcessingJob, queued["id"])
        row.status = "running"
        row.attempts = 1
        db.commit()
    finally:
        db.close()

    assert service.recover_interrupted_jobs() == 1
    recovered = service.get_job("alice", queued["id"])
    assert recovered["status"] == "queued"
    assert recovered["attempts"] == 1
    assert recovered["error"]["code"] == "worker_interrupted"
