"""Strict, owner-scoped HTTP routes for the meeting workflow.

The router is injectable for deterministic tests and worker integration.  It
does not run transcription in the request thread: enqueue endpoints return a
durable job for the controlled meeting worker to claim through
``MeetingService.run_job``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from services.meeting_service import (
    CLAIM_KINDS,
    LINK_TYPES,
    MEETING_STATUSES,
    MeetingDuplicateUpload,
    MeetingError,
    MeetingService,
    UPLOAD_CHUNK_BYTES,
    get_meeting_service,
)
from src.auth_helpers import require_user
from src.meeting_contract import (
    ALLOWED_DEVICES,
    ALLOWED_QUANTIZATIONS,
    ALLOWED_TIMESTAMP_GRANULARITIES,
)


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeetingCreateBody(_StrictBody):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=100_000)
    source_type: Literal["manual", "calendar", "upload", "browser_recording"] = "manual"
    calendar_event_id: Optional[str] = Field(default=None, max_length=500)
    project_id: Optional[str] = Field(default=None, max_length=100)
    scheduled_start: Optional[str] = Field(default=None, max_length=100)
    scheduled_end: Optional[str] = Field(default=None, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    attendee_names: list[str] = Field(default_factory=list, max_length=500)
    audio_retention_days: Optional[int] = Field(default=0, ge=0, le=3650)
    transcript_retention_days: Optional[int] = Field(default=365, ge=0, le=3650)


class MeetingUpdateBody(_StrictBody):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=100_000)
    scheduled_start: Optional[str] = Field(default=None, max_length=100)
    scheduled_end: Optional[str] = Field(default=None, max_length=100)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=100)
    attendee_names: Optional[list[str]] = Field(default=None, max_length=500)
    revision: int = Field(ge=1)


class TranscriptionJobBody(_StrictBody):
    model: str = Field(default="base", min_length=1, max_length=240)
    language: Optional[str] = Field(default=None, min_length=1, max_length=32)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    quantization: Literal["auto", "int8", "int8_float16", "float16", "float32"] = "auto"
    diarization: bool = False
    timestamp_granularity: Literal["segment", "word"] = "segment"
    max_upload_bytes: int = Field(default=500 * 1024 * 1024, ge=1, le=10 * 1024 * 1024 * 1024)
    audio_retention_days: Optional[int] = Field(default=0, ge=0, le=3650)
    transcript_retention_days: Optional[int] = Field(default=365, ge=0, le=3650)
    allow_model_download: bool = False
    replace_edited: bool = False


class QueueAnalysisBody(_StrictBody):
    reason: Optional[str] = Field(default=None, max_length=500)


class RetryBody(_StrictBody):
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)


class SegmentEditBody(_StrictBody):
    text: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    start_ms: Optional[int] = Field(default=None, ge=0)
    end_ms: Optional[int] = Field(default=None, ge=0)
    speaker_label: Optional[str] = Field(default=None, max_length=100)
    revision: int = Field(ge=1)


class SpeakerMapBody(_StrictBody):
    display_name: str = Field(min_length=1, max_length=255)
    attendee_id: Optional[str] = Field(default=None, max_length=255)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class ClaimReviewBody(_StrictBody):
    decision: Literal["approve", "confirm", "reject"]
    confirm: Literal[True]
    edited_text: Optional[str] = Field(default=None, min_length=1, max_length=20_000)
    revision: Optional[int] = Field(default=None, ge=1)


class MeetingLinkBody(_StrictBody):
    type: Literal[
        "calendar_event", "project", "task", "document", "knowledge_source", "contact"
    ]
    external_id: str = Field(min_length=1, max_length=500)
    label: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfirmBody(_StrictBody):
    confirm: Literal[True]


class ExportBody(ConfirmBody):
    format: Literal["json", "markdown", "txt"] = "json"


class DeleteBody(ConfirmBody):
    purge_record: bool = False


class RetentionBody(_StrictBody):
    audio_days: Optional[int] = Field(default=0, ge=0, le=3650)
    transcript_days: Optional[int] = Field(default=365, ge=0, le=3650)


class ReprocessBody(_StrictBody):
    mode: Literal["analysis", "transcription"] = "analysis"
    confirm_replace_edited: bool = False
    transcription: Optional[TranscriptionJobBody] = None


def _raise_meeting_error(exc: MeetingError) -> None:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if isinstance(exc, MeetingDuplicateUpload):
        detail["existing_meeting_id"] = exc.existing_meeting_id
    raise HTTPException(status_code=exc.status_code, detail=detail) from exc


def setup_meeting_routes(service: Optional[MeetingService] = None) -> APIRouter:
    meetings = service or get_meeting_service()
    router = APIRouter(prefix="/api/meetings", tags=["meetings"])

    @router.get("/meta")
    async def meeting_metadata(owner: str = Depends(require_user)):
        del owner
        return {
            "statuses": sorted(MEETING_STATUSES),
            "claim_kinds": sorted(CLAIM_KINDS),
            "link_types": sorted(LINK_TYPES),
            "transcription": {
                "devices": sorted(ALLOWED_DEVICES),
                "quantizations": sorted(ALLOWED_QUANTIZATIONS),
                "timestamp_granularities": sorted(ALLOWED_TIMESTAMP_GRANULARITIES),
                "stable_realtime": False,
            },
        }

    @router.get("/provider")
    async def meeting_provider_status(owner: str = Depends(require_user)):
        del owner
        return meetings.provider_status()

    @router.get("/jobs")
    async def list_meeting_jobs(
        meeting_id: Optional[str] = Query(default=None, max_length=36),
        status: Optional[str] = Query(default=None, max_length=40),
        limit: int = Query(default=100, ge=1, le=500),
        owner: str = Depends(require_user),
    ):
        try:
            return {
                "jobs": meetings.list_jobs(
                    owner,
                    meeting_id=meeting_id,
                    status=status,
                    limit=limit,
                )
            }
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.get("/jobs/{job_id}")
    async def get_meeting_job(job_id: str, owner: str = Depends(require_user)):
        try:
            return meetings.get_job(owner, job_id)
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_meeting_job(
        job_id: str,
        body: ConfirmBody,
        owner: str = Depends(require_user),
    ):
        del body
        try:
            return meetings.cancel_job(owner, job_id)
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/jobs/{job_id}/retry")
    async def retry_meeting_job(
        job_id: str,
        body: RetryBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.retry_job(
                owner,
                job_id,
                idempotency_key=body.idempotency_key,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/privacy/purge-expired")
    async def purge_expired_meetings(
        body: ConfirmBody,
        owner: str = Depends(require_user),
    ):
        del body
        try:
            return meetings.purge_expired(owner)
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.get("")
    async def list_meetings(
        query: str = Query(default="", max_length=500),
        status: Optional[str] = Query(default=None, max_length=40),
        project_id: Optional[str] = Query(default=None, max_length=100),
        calendar_event_id: Optional[str] = Query(default=None, max_length=500),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0, le=1_000_000),
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.list_meetings(
                owner,
                query=query,
                status=status,
                project_id=project_id,
                calendar_event_id=calendar_event_id,
                limit=limit,
                offset=offset,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("")
    async def create_meeting(
        body: MeetingCreateBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.create_meeting(owner, body.model_dump())
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.get("/{meeting_id}")
    async def get_meeting(
        meeting_id: str,
        include_history: bool = False,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.get_meeting(
                owner,
                meeting_id,
                include_history=include_history,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.patch("/{meeting_id}")
    async def update_meeting(
        meeting_id: str,
        body: MeetingUpdateBody,
        owner: str = Depends(require_user),
    ):
        values = body.model_dump(exclude_unset=True)
        revision = values.pop("revision")
        try:
            return meetings.update_meeting(
                owner,
                meeting_id,
                values,
                expected_revision=revision,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/media")
    async def upload_meeting_media(
        meeting_id: str,
        file: UploadFile = File(...),
        consent_confirmed: bool = Form(False),
        replace: bool = Form(False),
        owner: str = Depends(require_user),
    ):
        async def chunks() -> AsyncIterator[bytes]:
            while True:
                block = await file.read(UPLOAD_CHUNK_BYTES)
                if not block:
                    break
                yield block

        try:
            return await meetings.attach_media(
                owner,
                meeting_id,
                filename=file.filename or "",
                content_type=file.content_type or "",
                chunks=chunks(),
                consent_confirmed=consent_confirmed,
                replace=replace,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)
        finally:
            await file.close()

    @router.post("/{meeting_id}/transcription-jobs")
    async def queue_transcription(
        meeting_id: str,
        body: TranscriptionJobBody,
        idempotency_key: Optional[str] = Header(
            default=None,
            alias="Idempotency-Key",
            max_length=200,
        ),
        x_request_id: Optional[str] = Header(
            default=None,
            alias="X-Request-ID",
            max_length=200,
        ),
        owner: str = Depends(require_user),
    ):
        values = body.model_dump()
        replace_edited = values.pop("replace_edited")
        try:
            return meetings.enqueue_transcription(
                owner,
                meeting_id,
                config=values,
                idempotency_key=idempotency_key,
                correlation_id=x_request_id or "",
                replace_edited=replace_edited,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/analysis-jobs")
    async def queue_analysis(
        meeting_id: str,
        body: QueueAnalysisBody,
        idempotency_key: Optional[str] = Header(
            default=None,
            alias="Idempotency-Key",
            max_length=200,
        ),
        x_request_id: Optional[str] = Header(
            default=None,
            alias="X-Request-ID",
            max_length=200,
        ),
        owner: str = Depends(require_user),
    ):
        del body
        try:
            return meetings.enqueue_analysis(
                owner,
                meeting_id,
                idempotency_key=idempotency_key,
                correlation_id=x_request_id or "",
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/reprocess")
    async def reprocess_meeting(
        meeting_id: str,
        body: ReprocessBody,
        idempotency_key: Optional[str] = Header(
            default=None,
            alias="Idempotency-Key",
            max_length=200,
        ),
        owner: str = Depends(require_user),
    ):
        try:
            if body.mode == "analysis":
                return meetings.enqueue_analysis(
                    owner,
                    meeting_id,
                    idempotency_key=idempotency_key,
                )
            transcription = body.transcription or TranscriptionJobBody()
            values = transcription.model_dump()
            values.pop("replace_edited", None)
            return meetings.enqueue_transcription(
                owner,
                meeting_id,
                config=values,
                idempotency_key=idempotency_key,
                replace_edited=body.confirm_replace_edited,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.patch("/{meeting_id}/segments/{segment_id}")
    async def edit_transcript_segment(
        meeting_id: str,
        segment_id: str,
        body: SegmentEditBody,
        owner: str = Depends(require_user),
    ):
        values = body.model_dump(exclude_unset=True)
        revision = values.pop("revision")
        try:
            return meetings.edit_segment(
                owner,
                meeting_id,
                segment_id,
                values,
                expected_revision=revision,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.get("/{meeting_id}/segments/{segment_id}/revisions")
    async def transcript_segment_revisions(
        meeting_id: str,
        segment_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return {
                "revisions": meetings.transcript_revisions(
                    owner,
                    meeting_id,
                    segment_id,
                )
            }
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.put("/{meeting_id}/speakers/{label}")
    async def map_meeting_speaker(
        meeting_id: str,
        label: str,
        body: SpeakerMapBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.map_speaker(
                owner,
                meeting_id,
                label,
                display_name=body.display_name,
                attendee_id=body.attendee_id,
                confidence=body.confidence,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/claims/{claim_id}/review")
    async def review_meeting_claim(
        meeting_id: str,
        claim_id: str,
        body: ClaimReviewBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.review_claim(
                owner,
                meeting_id,
                claim_id,
                decision=body.decision,
                confirm=body.confirm,
                edited_text=body.edited_text,
                expected_revision=body.revision,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/links")
    async def add_meeting_link(
        meeting_id: str,
        body: MeetingLinkBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.add_link(owner, meeting_id, body.model_dump())
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/knowledge")
    async def save_meeting_to_knowledge(
        meeting_id: str,
        body: ConfirmBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.save_to_knowledge(
                owner,
                meeting_id,
                confirm=body.confirm,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/export")
    async def export_meeting(
        meeting_id: str,
        body: ExportBody,
        owner: str = Depends(require_user),
    ):
        try:
            filename, media_type, content = meetings.export_meeting(
                owner,
                meeting_id,
                format=body.format,
                confirm=body.confirm,
            )
            return Response(
                content=content,
                media_type=media_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.put("/{meeting_id}/retention")
    async def update_meeting_retention(
        meeting_id: str,
        body: RetentionBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.update_retention(
                owner,
                meeting_id,
                audio_days=body.audio_days,
                transcript_days=body.transcript_days,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    @router.post("/{meeting_id}/delete")
    async def delete_meeting(
        meeting_id: str,
        body: DeleteBody,
        owner: str = Depends(require_user),
    ):
        try:
            return meetings.delete_meeting(
                owner,
                meeting_id,
                confirm=body.confirm,
                purge_record=body.purge_record,
            )
        except MeetingError as exc:
            _raise_meeting_error(exc)

    return router
