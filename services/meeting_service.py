"""Owner-scoped meeting, transcription, evidence, and retention service.

All state-changing meeting operations go through this service.  Route and
future agent-tool adapters provide authenticated owners, while the service
rechecks ownership for every record and relationship.  Long-running work is
represented as durable jobs; calling ``run_job`` is a worker operation, not a
request-thread requirement.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
from typing import Any, Optional
import uuid

from sqlalchemy import create_engine, event, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from services.local_transcription import FasterWhisperTranscriptionProvider
from services.meeting_analysis import RuleBasedMeetingAnalyzer
from src.meeting_contract import (
    ClaimEvidence,
    GeneratedMeetingClaim,
    MeetingAnalysisRequest,
    MeetingAnalysisResult,
    MeetingAnalyzer,
    MeetingKnowledgeSink,
    TaskProposalSink,
    TRANSCRIPT_TRUST_CLASSIFICATION,
    TranscriptionCancelled,
    TranscriptionConfig,
    TranscriptionContractError,
    TranscriptionInvalidResult,
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptionSegmentResult,
    UntrustedTranscriptSegment,
)
from src.meeting_models import (
    MeetingClaim,
    MeetingClaimEvidence,
    MeetingLink,
    MeetingProcessingJob,
    MeetingRecord,
    MeetingSpeaker,
    MeetingTranscriptRevision,
    MeetingTranscriptSegment,
    ensure_meeting_schema,
)


logger = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 500 * 1024 * 1024
MAX_SEGMENTS = 250_000
MAX_TRANSCRIPT_CHARACTERS = 50_000_000
MAX_SEGMENT_CHARACTERS = 100_000
MAX_CLAIMS = 2_000
UPLOAD_CHUNK_BYTES = 1024 * 1024

MEETING_STATUSES = frozenset(
    {
        "draft",
        "uploaded",
        "queued",
        "transcribing",
        "analyzing",
        "review",
        "complete",
        "needs_reanalysis",
        "failed",
        "cancelled",
        "transcript_expired",
        "deleted",
    }
)
JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})
CLAIM_KINDS = frozenset(
    {"summary", "decision", "action_item", "question", "risk", "follow_up_draft"}
)
CLAIM_STATES = frozenset({"not_required", "pending", "approved", "confirmed", "rejected"})
LINK_TYPES = frozenset(
    {"calendar_event", "project", "task", "document", "knowledge_source", "contact"}
)

_SUPPORTED_MEDIA: dict[str, tuple[str, frozenset[str]]] = {
    ".wav": ("audio", frozenset({"audio/wav", "audio/x-wav", "audio/wave"})),
    ".mp3": ("audio", frozenset({"audio/mpeg", "audio/mp3"})),
    ".flac": ("audio", frozenset({"audio/flac", "audio/x-flac"})),
    ".ogg": ("audio", frozenset({"audio/ogg", "video/ogg", "application/ogg"})),
    ".webm": ("audio", frozenset({"audio/webm", "video/webm"})),
    ".m4a": (
        "audio",
        frozenset({"audio/mp4", "audio/x-m4a", "video/mp4", "application/mp4"}),
    ),
    ".mp4": (
        "video",
        frozenset({"video/mp4", "audio/mp4", "application/mp4"}),
    ),
    ".mov": ("video", frozenset({"video/quicktime"})),
}
_SAFE_MEDIA_TYPE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


class MeetingError(RuntimeError):
    code = "meeting_error"
    status_code = 400


class MeetingNotFound(MeetingError):
    code = "meeting_not_found"
    status_code = 404


class MeetingConflict(MeetingError):
    code = "meeting_conflict"
    status_code = 409


class MeetingValidationError(MeetingError):
    code = "invalid_meeting_request"
    status_code = 422


class MeetingUploadTooLarge(MeetingError):
    code = "meeting_upload_too_large"
    status_code = 413


class MeetingUnsupportedMedia(MeetingError):
    code = "unsupported_meeting_media"
    status_code = 415


class MeetingDuplicateUpload(MeetingConflict):
    code = "duplicate_meeting_upload"

    def __init__(self, existing_meeting_id: str) -> None:
        super().__init__("This recording has already been uploaded")
        self.existing_meeting_id = existing_meeting_id


class MeetingConsentRequired(MeetingError):
    code = "recording_consent_required"
    status_code = 409


class MeetingApprovalRequired(MeetingError):
    code = "meeting_approval_required"
    status_code = 409


class MeetingProviderUnavailable(MeetingError):
    code = "meeting_provider_unavailable"
    status_code = 503


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _owner_key(value: Optional[str]) -> str:
    owner = str(value or "").strip()
    if len(owner) > 255 or any(ord(ch) < 32 for ch in owner):
        raise MeetingValidationError("owner identity is invalid")
    return owner


def _bounded_text(
    value: Any,
    field: str,
    *,
    maximum: int,
    required: bool = False,
    strip: bool = True,
) -> str:
    text = str(value or "")
    if strip:
        text = text.strip()
    if required and not text:
        raise MeetingValidationError(f"{field} is required")
    if "\x00" in text or len(text) > maximum:
        raise MeetingValidationError(f"{field} must be at most {maximum} safe characters")
    return text


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError) as exc:
        raise MeetingValidationError("metadata must be valid JSON") from exc


def _json(value: Optional[str], fallback: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed


def _parse_datetime(value: Any, field: str) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise MeetingValidationError(f"{field} must be an ISO 8601 datetime") from exc
    else:
        raise MeetingValidationError(f"{field} must be an ISO 8601 datetime")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _retention_deadline(now: datetime, days: Optional[int]) -> Optional[datetime]:
    if days is None:
        return None
    return now + timedelta(days=int(days))


def _clean_filename(value: str) -> str:
    raw = str(value or "").replace("\\", "/")
    leaf = raw.rsplit("/", 1)[-1]
    leaf = re.sub(r"[\x00-\x1f\x7f]+", "_", leaf).strip(". ")
    if not leaf:
        raise MeetingUnsupportedMedia("A media filename with a supported extension is required")
    return leaf[:255]


def _media_descriptor(filename: str, content_type: str) -> tuple[str, str, str]:
    safe_name = _clean_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    descriptor = _SUPPORTED_MEDIA.get(suffix)
    if descriptor is None:
        raise MeetingUnsupportedMedia(
            "Supported meeting formats are WAV, MP3, FLAC, OGG, WebM, M4A, MP4, and MOV"
        )
    media_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if not _SAFE_MEDIA_TYPE.fullmatch(media_type):
        raise MeetingUnsupportedMedia("The media content type is invalid")
    kind, allowed_types = descriptor
    if media_type not in allowed_types:
        raise MeetingUnsupportedMedia("The media content type does not match its filename")
    return safe_name, suffix, kind


def _signature_matches(suffix: str, header: bytes) -> bool:
    if suffix == ".wav":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    if suffix == ".mp3":
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        )
    if suffix == ".flac":
        return header.startswith(b"fLaC")
    if suffix == ".ogg":
        return header.startswith(b"OggS")
    if suffix == ".webm":
        return header.startswith(b"\x1aE\xdf\xa3")
    if suffix in {".m4a", ".mp4", ".mov"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    return False


def _config_from(value: Mapping[str, Any] | TranscriptionConfig | None) -> TranscriptionConfig:
    if value is None:
        return TranscriptionConfig()
    if isinstance(value, TranscriptionConfig):
        return value
    try:
        return TranscriptionConfig.from_mapping(value)
    except (TypeError, ValueError) as exc:
        raise MeetingValidationError(str(exc)) from exc


def _sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_default_meeting_session_factory(database_url: Optional[str] = None):
    """Create the standalone meeting DB factory without mutating core.database."""

    if database_url is None:
        from src.constants import DATA_DIR

        data_dir = Path(DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            data_dir.chmod(0o700)
        except OSError:
            pass
        database_url = os.getenv(
            "OM_MEETINGS_DATABASE_URL",
            f"sqlite:///{(data_dir / 'meetings.db').as_posix()}",
        )
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_foreign_keys)
    ensure_meeting_schema(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False), engine


class MeetingService:
    """Durable meeting workflow and privacy boundary."""

    def __init__(
        self,
        *,
        session_factory=None,
        storage_root: Optional[Path] = None,
        transcription_provider: Optional[TranscriptionProvider] = None,
        analyzer: Optional[MeetingAnalyzer] = None,
        task_sink: Optional[TaskProposalSink] = None,
        knowledge_sink: Optional[MeetingKnowledgeSink] = None,
        event_sink=None,
        clock=None,
        max_upload_bytes: int = MAX_MEDIA_BYTES,
    ) -> None:
        self._owned_engine = None
        if session_factory is None:
            session_factory, self._owned_engine = create_default_meeting_session_factory()
        self.session_factory = session_factory
        if storage_root is None:
            from src.constants import DATA_DIR

            storage_root = Path(DATA_DIR) / "meeting-media"
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        if self.storage_root.is_symlink():
            raise MeetingValidationError("Meeting media root must not be a symbolic link")
        try:
            self.storage_root.chmod(0o700)
        except OSError:
            pass
        self.transcription_provider = (
            transcription_provider or FasterWhisperTranscriptionProvider()
        )
        self.analyzer = analyzer or RuleBasedMeetingAnalyzer()
        self.task_sink = task_sink
        self.knowledge_sink = knowledge_sink
        self.event_sink = event_sink
        self.clock = clock or _utcnow
        if not 1 <= int(max_upload_bytes) <= 10 * 1024 * 1024 * 1024:
            raise ValueError("max_upload_bytes must be between 1 byte and 10 GiB")
        self.max_upload_bytes = int(max_upload_bytes)

    def _owned_meeting(self, db, owner: str, meeting_id: str) -> MeetingRecord:
        meeting = (
            db.query(MeetingRecord)
            .filter(
                MeetingRecord.id == str(meeting_id),
                MeetingRecord.owner == owner,
                MeetingRecord.deleted_at.is_(None),
            )
            .first()
        )
        if meeting is None:
            raise MeetingNotFound("Meeting not found")
        return meeting

    def _storage_path(self, storage_key: str, *, must_exist: bool = False) -> Path:
        key = str(storage_key or "")
        if not key or Path(key).is_absolute() or ".." in Path(key).parts:
            raise MeetingValidationError("Stored media path is invalid")
        candidate = (self.storage_root / key).resolve(strict=must_exist)
        try:
            candidate.relative_to(self.storage_root)
        except ValueError as exc:
            raise MeetingValidationError("Stored media path escapes the meeting media root") from exc
        return candidate

    @staticmethod
    def _meeting_summary(meeting: MeetingRecord) -> dict[str, Any]:
        return {
            "id": meeting.id,
            "title": meeting.title,
            "description": meeting.description,
            "status": meeting.status,
            "source_type": meeting.source_type,
            "calendar_event_id": meeting.calendar_event_id,
            "project_id": meeting.project_id,
            "scheduled_start": _iso(meeting.scheduled_start),
            "scheduled_end": _iso(meeting.scheduled_end),
            "timezone": meeting.timezone,
            "attendee_names": _json(meeting.attendee_names_json, []),
            "media": {
                "filename": meeting.original_filename,
                "content_type": meeting.media_type,
                "kind": meeting.media_kind,
                "bytes": meeting.media_bytes,
                "sha256": meeting.media_sha256,
                "duration_ms": meeting.duration_ms,
                "available": bool(meeting.media_storage_key and meeting.media_deleted_at is None),
                "recording_consent_at": _iso(meeting.recording_consent_at),
                "deleted_at": _iso(meeting.media_deleted_at),
            },
            "transcription": {
                "provider": meeting.transcription_provider,
                "provider_version": meeting.transcription_provider_version,
                "model": meeting.transcription_model,
                "language": meeting.detected_language,
                "config": _json(meeting.transcription_config_json, {}),
                "warnings": _json(meeting.transcription_warnings_json, []),
                "revision": meeting.transcript_revision,
                "trust_classification": TRANSCRIPT_TRUST_CLASSIFICATION,
                "deleted_at": _iso(meeting.transcript_deleted_at),
            },
            "progress_percent": meeting.progress_percent,
            "last_error": (
                {
                    "code": meeting.last_error_code,
                    "message": meeting.last_error_message,
                }
                if meeting.last_error_code
                else None
            ),
            "retention": {
                "audio_days": meeting.audio_retention_days,
                "transcript_days": meeting.transcript_retention_days,
                "audio_delete_after": _iso(meeting.audio_delete_after),
                "transcript_delete_after": _iso(meeting.transcript_delete_after),
            },
            "completed_at": _iso(meeting.completed_at),
            "created_at": _iso(meeting.created_at),
            "updated_at": _iso(meeting.updated_at),
            "revision": meeting.revision,
        }

    @staticmethod
    def _segment_dict(segment: MeetingTranscriptSegment) -> dict[str, Any]:
        return {
            "id": segment.id,
            "position": segment.position,
            "generation": segment.generation,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "text": segment.text,
            "speaker_label": segment.speaker_label,
            "speaker_id": segment.speaker_id,
            "confidence": segment.confidence,
            "words": _json(segment.words_json, []),
            "trust_classification": segment.trust_classification,
            "is_edited": bool(segment.is_edited),
            "revision": segment.revision,
            "updated_at": _iso(segment.updated_at),
        }

    @staticmethod
    def _speaker_dict(speaker: MeetingSpeaker) -> dict[str, Any]:
        return {
            "id": speaker.id,
            "label": speaker.label,
            "display_name": speaker.display_name,
            "attendee_id": speaker.attendee_id,
            "confidence": speaker.confidence,
            "user_confirmed": bool(speaker.user_confirmed),
        }

    @staticmethod
    def _link_dict(link: MeetingLink) -> dict[str, Any]:
        return {
            "id": link.id,
            "type": link.link_type,
            "external_id": link.external_id,
            "label": link.label,
            "url": link.url,
            "metadata": _json(link.metadata_json, {}),
            "created_at": _iso(link.created_at),
        }

    @staticmethod
    def _claim_dict(claim: MeetingClaim) -> dict[str, Any]:
        evidence = sorted(claim.evidence, key=lambda item: (item.start_ms, item.id))
        return {
            "id": claim.id,
            "kind": claim.kind,
            "text": claim.text,
            "inferred": bool(claim.inferred),
            "fact_state": (
                "confirmed"
                if claim.approval_state == "confirmed"
                else "proposed"
                if claim.inferred
                else "reported"
            ),
            "approval_state": claim.approval_state,
            "created_by": claim.created_by,
            "analyzer": claim.analyzer,
            "analyzer_version": claim.analyzer_version,
            "metadata": _json(claim.metadata_json, {}),
            "linked_resource": (
                {
                    "type": claim.linked_resource_type,
                    "id": claim.linked_resource_id,
                }
                if claim.linked_resource_id
                else None
            ),
            "evidence": [
                {
                    "segment_id": item.segment_id,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "speaker_label": item.speaker_label,
                    "excerpt": item.excerpt,
                }
                for item in evidence
            ],
            "revision": claim.revision,
            "reviewed_at": _iso(claim.reviewed_at),
        }

    @staticmethod
    def _job_dict(job: MeetingProcessingJob) -> dict[str, Any]:
        return {
            "id": job.id,
            "meeting_id": job.meeting_id,
            "kind": job.kind,
            "status": job.status,
            "progress_percent": job.progress_percent,
            "config": _json(job.config_json, {}),
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "cancel_requested": bool(job.cancel_requested),
            "error": (
                {"code": job.error_code, "message": job.error_message}
                if job.error_code
                else None
            ),
            "correlation_id": job.correlation_id,
            "queued_at": _iso(job.queued_at),
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
            "updated_at": _iso(job.updated_at),
        }

    def create_meeting(self, owner: Optional[str], values: Mapping[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        allowed = {
            "title",
            "description",
            "source_type",
            "calendar_event_id",
            "project_id",
            "scheduled_start",
            "scheduled_end",
            "timezone",
            "attendee_names",
            "audio_retention_days",
            "transcript_retention_days",
        }
        unknown = set(values) - allowed
        if unknown:
            raise MeetingValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}")
        title = _bounded_text(values.get("title"), "title", maximum=500, required=True)
        source_type = _bounded_text(
            values.get("source_type", "manual"), "source_type", maximum=40, required=True
        ).lower()
        if source_type not in {"manual", "calendar", "upload", "browser_recording"}:
            raise MeetingValidationError("source_type is invalid")
        calendar_event_id = _bounded_text(
            values.get("calendar_event_id"), "calendar_event_id", maximum=500
        ) or None
        if source_type == "calendar" and not calendar_event_id:
            raise MeetingValidationError("calendar_event_id is required for calendar meetings")
        start = _parse_datetime(values.get("scheduled_start"), "scheduled_start")
        end = _parse_datetime(values.get("scheduled_end"), "scheduled_end")
        if start and end and end < start:
            raise MeetingValidationError("scheduled_end must not be before scheduled_start")
        attendee_names = values.get("attendee_names") or []
        if not isinstance(attendee_names, list) or len(attendee_names) > 500:
            raise MeetingValidationError("attendee_names must be a list of at most 500 names")
        attendees = [
            _bounded_text(item, "attendee name", maximum=255, required=True)
            for item in attendee_names
        ]
        default_transcript_days = 365
        try:
            from services.privacy_service import get_privacy_service
            configured_days = get_privacy_service().get(owner).get("transcript_retention_days")
            if configured_days is not None:
                default_transcript_days = int(configured_days)
        except Exception:
            logger.debug("Privacy retention defaults unavailable", exc_info=True)
        config = _config_from(
            {
                "audio_retention_days": values.get("audio_retention_days", 0),
                "transcript_retention_days": values.get("transcript_retention_days", default_transcript_days),
            }
        )
        now = self.clock()
        meeting = MeetingRecord(
            id=str(uuid.uuid4()),
            owner=owner_key,
            title=title,
            description=_bounded_text(
                values.get("description"), "description", maximum=100_000
            ),
            source_type=source_type,
            calendar_event_id=calendar_event_id,
            project_id=_bounded_text(
                values.get("project_id"), "project_id", maximum=100
            )
            or None,
            scheduled_start=start,
            scheduled_end=end,
            timezone=_bounded_text(
                values.get("timezone", "UTC"), "timezone", maximum=100, required=True
            ),
            attendee_names_json=_canonical_json(attendees),
            audio_retention_days=config.audio_retention_days,
            transcript_retention_days=config.transcript_retention_days,
            created_at=now,
            updated_at=now,
        )
        db = self.session_factory()
        try:
            db.add(meeting)
            if calendar_event_id:
                db.add(
                    MeetingLink(
                        id=str(uuid.uuid4()),
                        meeting_id=meeting.id,
                        owner=owner_key,
                        link_type="calendar_event",
                        external_id=calendar_event_id,
                        label="Calendar event",
                    )
                )
            if meeting.project_id:
                db.add(
                    MeetingLink(
                        id=str(uuid.uuid4()),
                        meeting_id=meeting.id,
                        owner=owner_key,
                        link_type="project",
                        external_id=meeting.project_id,
                        label="Project",
                    )
                )
            db.commit()
            db.refresh(meeting)
            return self._meeting_summary(meeting)
        finally:
            db.close()

    def update_meeting(
        self,
        owner: Optional[str],
        meeting_id: str,
        values: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        allowed = {
            "title",
            "description",
            "scheduled_start",
            "scheduled_end",
            "timezone",
            "attendee_names",
        }
        unknown = set(values) - allowed
        if unknown:
            raise MeetingValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}")
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            if meeting.revision != int(expected_revision):
                raise MeetingConflict("Meeting was changed by another request")
            if "title" in values:
                meeting.title = _bounded_text(
                    values["title"], "title", maximum=500, required=True
                )
            if "description" in values:
                meeting.description = _bounded_text(
                    values["description"], "description", maximum=100_000
                )
            if "timezone" in values:
                meeting.timezone = _bounded_text(
                    values["timezone"], "timezone", maximum=100, required=True
                )
            if "scheduled_start" in values:
                meeting.scheduled_start = _parse_datetime(
                    values["scheduled_start"], "scheduled_start"
                )
            if "scheduled_end" in values:
                meeting.scheduled_end = _parse_datetime(
                    values["scheduled_end"], "scheduled_end"
                )
            if meeting.scheduled_start and meeting.scheduled_end:
                if meeting.scheduled_end < meeting.scheduled_start:
                    raise MeetingValidationError(
                        "scheduled_end must not be before scheduled_start"
                    )
            if "attendee_names" in values:
                attendees = values["attendee_names"]
                if not isinstance(attendees, list) or len(attendees) > 500:
                    raise MeetingValidationError(
                        "attendee_names must be a list of at most 500 names"
                    )
                meeting.attendee_names_json = _canonical_json(
                    [
                        _bounded_text(item, "attendee name", maximum=255, required=True)
                        for item in attendees
                    ]
                )
            meeting.revision += 1
            meeting.updated_at = self.clock()
            db.commit()
            db.refresh(meeting)
            return self._meeting_summary(meeting)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_meeting(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        include_history: bool = False,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            result = self._meeting_summary(meeting)
            segment_query = db.query(MeetingTranscriptSegment).filter(
                MeetingTranscriptSegment.meeting_id == meeting.id
            )
            claim_query = db.query(MeetingClaim).filter(MeetingClaim.meeting_id == meeting.id)
            if not include_history:
                segment_query = segment_query.filter(MeetingTranscriptSegment.active.is_(True))
                claim_query = claim_query.filter(MeetingClaim.active.is_(True))
            segments = segment_query.order_by(
                MeetingTranscriptSegment.generation,
                MeetingTranscriptSegment.position,
            ).all()
            claims = claim_query.order_by(MeetingClaim.created_at, MeetingClaim.id).all()
            speakers = (
                db.query(MeetingSpeaker)
                .filter(MeetingSpeaker.meeting_id == meeting.id)
                .order_by(MeetingSpeaker.label)
                .all()
            )
            links = (
                db.query(MeetingLink)
                .filter(MeetingLink.meeting_id == meeting.id, MeetingLink.owner == owner_key)
                .order_by(MeetingLink.created_at, MeetingLink.id)
                .all()
            )
            jobs = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.meeting_id == meeting.id,
                    MeetingProcessingJob.owner == owner_key,
                )
                .order_by(MeetingProcessingJob.created_at.desc())
                .limit(50)
                .all()
            )
            result.update(
                {
                    "segments": [self._segment_dict(item) for item in segments],
                    "speakers": [self._speaker_dict(item) for item in speakers],
                    "claims": [self._claim_dict(item) for item in claims],
                    "links": [self._link_dict(item) for item in links],
                    "jobs": [self._job_dict(item) for item in jobs],
                }
            )
            return result
        finally:
            db.close()

    def list_meetings(
        self,
        owner: Optional[str],
        *,
        query: str = "",
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        calendar_event_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        query_text = _bounded_text(query, "query", maximum=500)
        if status is not None and status not in MEETING_STATUSES - {"deleted"}:
            raise MeetingValidationError("status is invalid")
        if not 1 <= int(limit) <= 500 or not 0 <= int(offset) <= 1_000_000:
            raise MeetingValidationError("pagination is invalid")
        db = self.session_factory()
        try:
            q = db.query(MeetingRecord).filter(
                MeetingRecord.owner == owner_key,
                MeetingRecord.deleted_at.is_(None),
            )
            if status:
                q = q.filter(MeetingRecord.status == status)
            if project_id:
                q = q.filter(MeetingRecord.project_id == str(project_id))
            if calendar_event_id:
                q = q.filter(MeetingRecord.calendar_event_id == str(calendar_event_id))
            if query_text:
                segment_meetings = db.query(MeetingTranscriptSegment.meeting_id).filter(
                    MeetingTranscriptSegment.active.is_(True),
                    MeetingTranscriptSegment.text.ilike(f"%{query_text}%"),
                )
                q = q.filter(
                    or_(
                        MeetingRecord.title.ilike(f"%{query_text}%"),
                        MeetingRecord.description.ilike(f"%{query_text}%"),
                        MeetingRecord.id.in_(segment_meetings),
                    )
                )
            total = q.count()
            rows = (
                q.order_by(MeetingRecord.created_at.desc(), MeetingRecord.id)
                .offset(int(offset))
                .limit(int(limit))
                .all()
            )
            return {
                "meetings": [self._meeting_summary(row) for row in rows],
                "total": total,
                "limit": int(limit),
                "offset": int(offset),
            }
        finally:
            db.close()

    async def attach_media(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        filename: str,
        content_type: str,
        chunks: AsyncIterable[bytes],
        consent_confirmed: bool,
        replace: bool = False,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        if consent_confirmed is not True:
            raise MeetingConsentRequired(
                "Confirm that recording and upload comply with attendee consent requirements"
            )
        safe_name, suffix, kind = _media_descriptor(filename, content_type)
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            if meeting.media_storage_key and not replace:
                raise MeetingConflict("Meeting already has media; explicit replacement is required")
            prior_storage_key = meeting.media_storage_key
            retention_days = meeting.audio_retention_days
        finally:
            db.close()

        owner_folder = hashlib.sha256(owner_key.encode("utf-8")).hexdigest()[:24]
        relative_dir = Path(owner_folder) / meeting_id
        target_dir = self._storage_path(relative_dir.as_posix())
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            target_dir.chmod(0o700)
        except OSError:
            pass
        temp_path = target_dir / f".{secrets.token_hex(12)}.part"
        final_key = ""
        final_path: Optional[Path] = None
        digest = hashlib.sha256()
        header = bytearray()
        size = 0
        try:
            with temp_path.open("xb") as handle:
                try:
                    os.chmod(temp_path, 0o600)
                except OSError:
                    pass
                async for chunk in chunks:
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise MeetingValidationError("Upload stream yielded a non-byte chunk")
                    data = bytes(chunk)
                    if not data:
                        continue
                    size += len(data)
                    if size > self.max_upload_bytes:
                        raise MeetingUploadTooLarge(
                            f"Meeting media exceeds the {self.max_upload_bytes}-byte limit"
                        )
                    if len(header) < 64:
                        header.extend(data[: 64 - len(header)])
                    digest.update(data)
                    handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise MeetingUnsupportedMedia("Meeting media is empty")
            if not _signature_matches(suffix, bytes(header)):
                raise MeetingUnsupportedMedia(
                    "The uploaded bytes do not match the declared meeting media format"
                )
            media_hash = digest.hexdigest()
            final_key = (relative_dir / f"media-{media_hash[:20]}{suffix}").as_posix()
            final_path = self._storage_path(final_key)

            db = self.session_factory()
            try:
                duplicate = (
                    db.query(MeetingRecord)
                    .filter(
                        MeetingRecord.owner == owner_key,
                        MeetingRecord.media_sha256 == media_hash,
                        MeetingRecord.id != meeting_id,
                        MeetingRecord.deleted_at.is_(None),
                    )
                    .first()
                )
                if duplicate:
                    raise MeetingDuplicateUpload(duplicate.id)
            finally:
                db.close()

            os.replace(temp_path, final_path)
            try:
                os.chmod(final_path, 0o600)
            except OSError:
                pass
            now = self.clock()
            db = self.session_factory()
            try:
                meeting = self._owned_meeting(db, owner_key, meeting_id)
                meeting.original_filename = safe_name
                meeting.media_type = content_type.split(";", 1)[0].strip().lower()
                meeting.media_kind = kind
                meeting.media_storage_key = final_key
                meeting.media_sha256 = media_hash
                meeting.media_bytes = size
                meeting.recording_consent_at = now
                meeting.media_deleted_at = None
                meeting.audio_delete_after = _retention_deadline(now, retention_days)
                meeting.status = "uploaded"
                meeting.progress_percent = 0
                meeting.last_error_code = None
                meeting.last_error_message = None
                meeting.revision += 1
                meeting.updated_at = now
                db.commit()
                db.refresh(meeting)
                result = self._meeting_summary(meeting)
            except IntegrityError as exc:
                db.rollback()
                duplicate = (
                    db.query(MeetingRecord)
                    .filter(
                        MeetingRecord.owner == owner_key,
                        MeetingRecord.media_sha256 == media_hash,
                        MeetingRecord.id != meeting_id,
                    )
                    .first()
                )
                raise MeetingDuplicateUpload(duplicate.id if duplicate else "unknown") from exc
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

            if prior_storage_key and prior_storage_key != final_key:
                try:
                    self._storage_path(prior_storage_key).unlink(missing_ok=True)
                except (OSError, MeetingError):
                    logger.warning("Could not remove superseded meeting media", extra={"meeting_id": meeting_id})
            return result
        except Exception:
            temp_path.unlink(missing_ok=True)
            # If the database update did not commit, do not leave a durable
            # orphan.  A pre-existing final file is retained on replacement.
            if final_path is not None and final_path.exists() and final_key != prior_storage_key:
                final_path.unlink(missing_ok=True)
            raise

    def enqueue_transcription(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        config: Mapping[str, Any] | TranscriptionConfig | None = None,
        idempotency_key: Optional[str] = None,
        correlation_id: str = "",
        replace_edited: bool = False,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        if isinstance(config, TranscriptionConfig):
            normalized_config = config
        else:
            supplied = dict(config or {})
            db = self.session_factory()
            try:
                configured_meeting = self._owned_meeting(db, owner_key, meeting_id)
                supplied.setdefault(
                    "audio_retention_days", configured_meeting.audio_retention_days
                )
                supplied.setdefault(
                    "transcript_retention_days",
                    configured_meeting.transcript_retention_days,
                )
            finally:
                db.close()
            normalized_config = _config_from(supplied)
        if normalized_config.max_upload_bytes > self.max_upload_bytes:
            raise MeetingValidationError(
                "Job maximum upload size cannot exceed the server upload limit"
            )
        idem = _bounded_text(
            idempotency_key or f"transcribe:{meeting_id}:{uuid.uuid4()}",
            "idempotency_key",
            maximum=200,
            required=True,
        )
        db = self.session_factory()
        try:
            existing = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.owner == owner_key,
                    MeetingProcessingJob.idempotency_key == idem,
                )
                .first()
            )
            if existing:
                if existing.meeting_id != meeting_id:
                    raise MeetingConflict("Idempotency key belongs to another meeting")
                return self._job_dict(existing)
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            if not meeting.media_storage_key or meeting.media_deleted_at is not None:
                raise MeetingConflict("Meeting media is unavailable for transcription")
            if meeting.media_bytes and meeting.media_bytes > normalized_config.max_upload_bytes:
                raise MeetingUploadTooLarge(
                    "Meeting media exceeds this transcription job's configured limit"
                )
            edited_exists = (
                db.query(MeetingTranscriptSegment.id)
                .filter(
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                    MeetingTranscriptSegment.active.is_(True),
                    MeetingTranscriptSegment.is_edited.is_(True),
                )
                .first()
                is not None
            )
            if edited_exists and not replace_edited:
                raise MeetingConflict(
                    "The current transcript contains user edits; explicit replacement is required"
                )
            active = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.meeting_id == meeting.id,
                    MeetingProcessingJob.owner == owner_key,
                    MeetingProcessingJob.status.in_(["queued", "running"]),
                )
                .first()
            )
            if active:
                raise MeetingConflict("A meeting processing job is already active")
            now = self.clock()
            job = MeetingProcessingJob(
                id=str(uuid.uuid4()),
                meeting_id=meeting.id,
                owner=owner_key,
                kind="transcribe",
                status="queued",
                config_json=_canonical_json(normalized_config.as_dict()),
                idempotency_key=idem,
                replace_edited=bool(replace_edited),
                correlation_id=_bounded_text(
                    correlation_id, "correlation_id", maximum=200
                ),
                queued_at=now,
                created_at=now,
                updated_at=now,
            )
            meeting.status = "queued"
            meeting.progress_percent = 0
            meeting.last_error_code = None
            meeting.last_error_message = None
            meeting.revision += 1
            meeting.updated_at = now
            db.add(job)
            db.commit()
            db.refresh(job)
            return self._job_dict(job)
        except IntegrityError as exc:
            db.rollback()
            existing = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.owner == owner_key,
                    MeetingProcessingJob.idempotency_key == idem,
                )
                .first()
            )
            if existing and existing.meeting_id == meeting_id:
                return self._job_dict(existing)
            raise MeetingConflict("Idempotency key is already in use") from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue_analysis(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        idempotency_key: Optional[str] = None,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        idem = _bounded_text(
            idempotency_key or f"analyze:{meeting_id}:{uuid.uuid4()}",
            "idempotency_key",
            maximum=200,
            required=True,
        )
        db = self.session_factory()
        try:
            existing = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.owner == owner_key,
                    MeetingProcessingJob.idempotency_key == idem,
                )
                .first()
            )
            if existing:
                if existing.meeting_id != meeting_id:
                    raise MeetingConflict("Idempotency key belongs to another meeting")
                return self._job_dict(existing)
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            segment_exists = (
                db.query(MeetingTranscriptSegment.id)
                .filter(
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                    MeetingTranscriptSegment.active.is_(True),
                )
                .first()
            )
            if segment_exists is None:
                raise MeetingConflict("Meeting has no active transcript to analyze")
            active = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.meeting_id == meeting.id,
                    MeetingProcessingJob.owner == owner_key,
                    MeetingProcessingJob.status.in_(["queued", "running"]),
                )
                .first()
            )
            if active:
                raise MeetingConflict("A meeting processing job is already active")
            now = self.clock()
            job = MeetingProcessingJob(
                id=str(uuid.uuid4()),
                meeting_id=meeting.id,
                owner=owner_key,
                kind="analyze",
                status="queued",
                config_json="{}",
                idempotency_key=idem,
                correlation_id=_bounded_text(
                    correlation_id, "correlation_id", maximum=200
                ),
                queued_at=now,
                created_at=now,
                updated_at=now,
            )
            meeting.status = "queued"
            meeting.progress_percent = 70
            meeting.last_error_code = None
            meeting.last_error_message = None
            meeting.revision += 1
            db.add(job)
            db.commit()
            db.refresh(job)
            return self._job_dict(job)
        except IntegrityError as exc:
            db.rollback()
            existing = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.owner == owner_key,
                    MeetingProcessingJob.idempotency_key == idem,
                )
                .first()
            )
            if existing and existing.meeting_id == meeting_id:
                return self._job_dict(existing)
            raise MeetingConflict("Idempotency key is already in use") from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_job(self, owner: Optional[str], job_id: str) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == str(job_id),
                    MeetingProcessingJob.owner == owner_key,
                )
                .first()
            )
            if job is None:
                raise MeetingNotFound("Meeting job not found")
            return self._job_dict(job)
        finally:
            db.close()

    def list_jobs(
        self,
        owner: Optional[str],
        *,
        meeting_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        owner_key = _owner_key(owner)
        if status is not None and status not in JOB_STATUSES:
            raise MeetingValidationError("job status is invalid")
        if not 1 <= int(limit) <= 500:
            raise MeetingValidationError("limit must be between 1 and 500")
        db = self.session_factory()
        try:
            q = db.query(MeetingProcessingJob).filter(
                MeetingProcessingJob.owner == owner_key
            )
            if meeting_id:
                self._owned_meeting(db, owner_key, meeting_id)
                q = q.filter(MeetingProcessingJob.meeting_id == meeting_id)
            if status:
                q = q.filter(MeetingProcessingJob.status == status)
            return [
                self._job_dict(job)
                for job in q.order_by(MeetingProcessingJob.created_at.desc())
                .limit(int(limit))
                .all()
            ]
        finally:
            db.close()

    def cancel_job(self, owner: Optional[str], job_id: str) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == str(job_id),
                    MeetingProcessingJob.owner == owner_key,
                )
                .first()
            )
            if job is None:
                raise MeetingNotFound("Meeting job not found")
            if job.status in {"succeeded", "failed", "cancelled"}:
                return self._job_dict(job)
            now = self.clock()
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = now
                meeting = self._owned_meeting(db, owner_key, job.meeting_id)
                meeting.status = "cancelled"
                meeting.progress_percent = job.progress_percent
                meeting.revision += 1
            job.updated_at = now
            db.commit()
            db.refresh(job)
            return self._job_dict(job)
        finally:
            db.close()

    def retry_job(
        self,
        owner: Optional[str],
        job_id: str,
        *,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        db = self.session_factory()
        try:
            old = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == str(job_id),
                    MeetingProcessingJob.owner == owner_key,
                )
                .first()
            )
            if old is None:
                raise MeetingNotFound("Meeting job not found")
            if old.status not in {"failed", "cancelled"}:
                raise MeetingConflict("Only failed or cancelled jobs can be retried")
            if old.attempts >= old.max_attempts:
                raise MeetingConflict("Meeting job retry limit has been reached")
            kind = old.kind
            config = _json(old.config_json, {})
            meeting_id = old.meeting_id
            replace_edited = bool(old.replace_edited)
        finally:
            db.close()
        new_key = idempotency_key or f"retry:{job_id}:{uuid.uuid4()}"
        if kind == "transcribe":
            result = self.enqueue_transcription(
                owner_key,
                meeting_id,
                config=config,
                idempotency_key=new_key,
                replace_edited=replace_edited,
            )
        else:
            result = self.enqueue_analysis(
                owner_key,
                meeting_id,
                idempotency_key=new_key,
            )
        db = self.session_factory()
        try:
            replacement = db.get(MeetingProcessingJob, result["id"])
            if replacement is not None:
                replacement.attempts = old.attempts
                replacement.max_attempts = old.max_attempts
                db.commit()
                db.refresh(replacement)
                return self._job_dict(replacement)
        finally:
            db.close()
        return result

    def _job_cancel_requested(self, owner: str, job_id: str) -> bool:
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == job_id,
                    MeetingProcessingJob.owner == owner,
                )
                .first()
            )
            return job is None or bool(job.cancel_requested) or job.status == "cancelled"
        finally:
            db.close()

    def _set_progress(self, owner: str, job_id: str, percent: int) -> None:
        progress = max(0, min(99, int(percent)))
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == job_id,
                    MeetingProcessingJob.owner == owner,
                    MeetingProcessingJob.status == "running",
                )
                .first()
            )
            if job is None:
                return
            if progress <= job.progress_percent:
                return
            job.progress_percent = progress
            job.updated_at = self.clock()
            meeting = (
                db.query(MeetingRecord)
                .filter(
                    MeetingRecord.id == job.meeting_id,
                    MeetingRecord.owner == owner,
                    MeetingRecord.deleted_at.is_(None),
                )
                .first()
            )
            if meeting:
                meeting.progress_percent = progress
                meeting.updated_at = self.clock()
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _validated_segments(
        result: TranscriptionResult,
    ) -> tuple[TranscriptionSegmentResult, ...]:
        if not isinstance(result, TranscriptionResult):
            raise TranscriptionInvalidResult("Provider returned an invalid result type")
        if not result.segments:
            raise TranscriptionInvalidResult("Provider returned no transcript segments")
        if len(result.segments) > MAX_SEGMENTS:
            raise TranscriptionInvalidResult("Provider returned too many transcript segments")
        total_characters = 0
        prior_start = -1
        clean: list[TranscriptionSegmentResult] = []
        for segment in result.segments:
            if not isinstance(segment, TranscriptionSegmentResult):
                raise TranscriptionInvalidResult("Provider returned an invalid segment")
            text = str(segment.text or "").replace("\x00", "").strip()
            if not text:
                continue
            if len(text) > MAX_SEGMENT_CHARACTERS:
                raise TranscriptionInvalidResult("A transcript segment is too large")
            total_characters += len(text)
            if total_characters > MAX_TRANSCRIPT_CHARACTERS:
                raise TranscriptionInvalidResult("Transcript is too large")
            start_ms = int(segment.start_ms)
            end_ms = int(segment.end_ms)
            if start_ms < 0 or end_ms < start_ms or start_ms < prior_start:
                raise TranscriptionInvalidResult("Transcript timestamps are invalid")
            prior_start = start_ms
            confidence = segment.confidence
            if confidence is not None:
                confidence = float(confidence)
                if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise TranscriptionInvalidResult("Transcript confidence is invalid")
            speaker = str(segment.speaker_label or "").strip()[:100] or None
            clean.append(
                TranscriptionSegmentResult(
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speaker_label=speaker,
                    confidence=confidence,
                    words=tuple(segment.words),
                )
            )
        if not clean:
            raise TranscriptionInvalidResult("Provider returned no usable speech")
        return tuple(clean)

    def _persist_transcription(
        self,
        owner: str,
        job_id: str,
        result: TranscriptionResult,
        config: TranscriptionConfig,
    ) -> tuple[str, list[UntrustedTranscriptSegment]]:
        segments = self._validated_segments(result)
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == job_id,
                    MeetingProcessingJob.owner == owner,
                    MeetingProcessingJob.status == "running",
                )
                .first()
            )
            if job is None:
                raise MeetingConflict("Meeting job is no longer runnable")
            if job.cancel_requested:
                raise TranscriptionCancelled("Transcription was cancelled")
            meeting = self._owned_meeting(db, owner, job.meeting_id)
            active_segments = (
                db.query(MeetingTranscriptSegment)
                .filter(
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                    MeetingTranscriptSegment.active.is_(True),
                )
                .all()
            )
            if any(segment.is_edited for segment in active_segments) and not job.replace_edited:
                raise MeetingConflict(
                    "The transcript was edited while processing; requeue with explicit replacement"
                )
            generation = max(
                [segment.generation for segment in active_segments] + [meeting.transcript_revision, 0]
            ) + 1
            for segment in active_segments:
                segment.active = False
            for claim in (
                db.query(MeetingClaim)
                .filter(MeetingClaim.meeting_id == meeting.id, MeetingClaim.active.is_(True))
                .all()
            ):
                claim.active = False
            created: list[UntrustedTranscriptSegment] = []
            speaker_labels: set[str] = set()
            for position, segment in enumerate(segments):
                segment_id = str(uuid.uuid4())
                words = [
                    {
                        "text": word.text,
                        "start_ms": word.start_ms,
                        "end_ms": word.end_ms,
                        "confidence": word.confidence,
                    }
                    for word in segment.words
                ]
                row = MeetingTranscriptSegment(
                    id=segment_id,
                    meeting_id=meeting.id,
                    generation=generation,
                    position=position,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    speaker_label=segment.speaker_label,
                    confidence=segment.confidence,
                    words_json=_canonical_json(words),
                    trust_classification=TRANSCRIPT_TRUST_CLASSIFICATION,
                    active=True,
                )
                db.add(row)
                if segment.speaker_label:
                    speaker_labels.add(segment.speaker_label)
                created.append(
                    UntrustedTranscriptSegment(
                        id=segment_id,
                        text=segment.text,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        speaker_label=segment.speaker_label,
                        confidence=segment.confidence,
                    )
                )
            existing_labels = {
                row.label
                for row in db.query(MeetingSpeaker)
                .filter(MeetingSpeaker.meeting_id == meeting.id)
                .all()
            }
            for label in sorted(speaker_labels - existing_labels):
                db.add(
                    MeetingSpeaker(
                        id=str(uuid.uuid4()),
                        meeting_id=meeting.id,
                        label=label,
                    )
                )
            meeting.transcription_provider = _bounded_text(
                result.provider, "provider", maximum=100, required=True
            )
            meeting.transcription_provider_version = _bounded_text(
                result.provider_version, "provider_version", maximum=100
            )
            meeting.transcription_model = _bounded_text(
                result.model, "model", maximum=240, required=True
            )
            meeting.detected_language = _bounded_text(
                result.language, "language", maximum=40
            ) or None
            meeting.duration_ms = int(result.duration_ms) if result.duration_ms is not None else None
            meeting.transcription_config_json = _canonical_json(config.as_dict())
            meeting.transcription_warnings_json = _canonical_json(list(result.warnings))
            meeting.transcript_revision = generation
            meeting.transcript_deleted_at = None
            meeting.transcript_retention_days = config.transcript_retention_days
            meeting.transcript_delete_after = _retention_deadline(
                self.clock(), config.transcript_retention_days
            )
            meeting.audio_retention_days = config.audio_retention_days
            meeting.audio_delete_after = _retention_deadline(
                self.clock(), config.audio_retention_days
            )
            meeting.status = "analyzing"
            meeting.progress_percent = 75
            meeting.revision += 1
            job.progress_percent = 75
            db.commit()
            return meeting.id, created
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _analysis_request(self, owner: str, meeting_id: str) -> MeetingAnalysisRequest:
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner, meeting_id)
            rows = (
                db.query(MeetingTranscriptSegment)
                .filter(
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                    MeetingTranscriptSegment.active.is_(True),
                )
                .order_by(MeetingTranscriptSegment.position)
                .all()
            )
            return MeetingAnalysisRequest(
                meeting_id=meeting.id,
                title=meeting.title,
                segments=tuple(
                    UntrustedTranscriptSegment(
                        id=row.id,
                        text=row.text,
                        start_ms=row.start_ms,
                        end_ms=row.end_ms,
                        speaker_label=row.speaker_label,
                        confidence=row.confidence,
                    )
                    for row in rows
                ),
            )
        finally:
            db.close()

    def _persist_analysis(
        self,
        owner: str,
        job_id: str,
        result: MeetingAnalysisResult,
    ) -> None:
        if not isinstance(result, MeetingAnalysisResult):
            raise MeetingValidationError("Analyzer returned an invalid result")
        if len(result.claims) > MAX_CLAIMS:
            raise MeetingValidationError("Analyzer returned too many claims")
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == job_id,
                    MeetingProcessingJob.owner == owner,
                    MeetingProcessingJob.status == "running",
                )
                .first()
            )
            if job is None:
                raise MeetingConflict("Meeting job is no longer runnable")
            if job.cancel_requested:
                raise TranscriptionCancelled("Meeting analysis was cancelled")
            meeting = self._owned_meeting(db, owner, job.meeting_id)
            segments = {
                row.id: row
                for row in db.query(MeetingTranscriptSegment)
                .filter(
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                    MeetingTranscriptSegment.active.is_(True),
                )
                .all()
            }
            for old in (
                db.query(MeetingClaim)
                .filter(MeetingClaim.meeting_id == meeting.id, MeetingClaim.active.is_(True))
                .all()
            ):
                # Reviewed statements remain visible and retain their original
                # evidence.  Unreviewed analysis is superseded atomically.
                if old.approval_state in {"approved", "confirmed"}:
                    continue
                old.active = False
            pending_count = 0
            for generated in result.claims:
                if not isinstance(generated, GeneratedMeetingClaim):
                    raise MeetingValidationError("Analyzer returned an invalid claim")
                kind = str(generated.kind or "").strip().lower()
                if kind not in CLAIM_KINDS:
                    raise MeetingValidationError("Analyzer returned an unsupported claim kind")
                text = _bounded_text(
                    generated.text,
                    "generated claim",
                    maximum=20_000,
                    required=True,
                )
                if not generated.evidence:
                    raise MeetingValidationError(
                        "Every generated meeting statement must cite transcript evidence"
                    )
                claim_id = str(uuid.uuid4())
                state = "not_required" if kind in {"summary", "question", "risk"} else "pending"
                if state == "pending":
                    pending_count += 1
                claim = MeetingClaim(
                    id=claim_id,
                    meeting_id=meeting.id,
                    kind=kind,
                    text=text,
                    inferred=bool(generated.inferred),
                    approval_state=state,
                    analyzer=_bounded_text(
                        result.analyzer, "analyzer", maximum=100
                    ),
                    analyzer_version=_bounded_text(
                        result.analyzer_version, "analyzer_version", maximum=100
                    ),
                    metadata_json=_canonical_json(dict(generated.metadata)),
                )
                db.add(claim)
                seen: set[str] = set()
                for evidence in generated.evidence:
                    if not isinstance(evidence, ClaimEvidence):
                        raise MeetingValidationError("Analyzer returned invalid evidence")
                    segment = segments.get(evidence.segment_id)
                    if segment is None:
                        raise MeetingValidationError(
                            "Generated claim cites a segment outside the active transcript"
                        )
                    if evidence.segment_id in seen:
                        continue
                    seen.add(evidence.segment_id)
                    if not (
                        segment.start_ms <= int(evidence.start_ms) <= int(evidence.end_ms) <= segment.end_ms
                    ):
                        raise MeetingValidationError(
                            "Generated claim evidence timestamps are outside its segment"
                        )
                    db.add(
                        MeetingClaimEvidence(
                            id=str(uuid.uuid4()),
                            claim_id=claim_id,
                            segment_id=segment.id,
                            start_ms=int(evidence.start_ms),
                            end_ms=int(evidence.end_ms),
                            speaker_label=(
                                _bounded_text(
                                    evidence.speaker_label,
                                    "speaker_label",
                                    maximum=100,
                                )
                                or None
                            ),
                            excerpt=segment.text[:500],
                        )
                    )
            warnings = list(_json(meeting.transcription_warnings_json, []))
            warnings.extend(str(item)[:500] for item in result.warnings)
            meeting.transcription_warnings_json = _canonical_json(warnings[:100])
            meeting.status = "review" if pending_count else "complete"
            meeting.progress_percent = 100
            meeting.completed_at = self.clock()
            meeting.last_error_code = None
            meeting.last_error_message = None
            meeting.revision += 1
            job.status = "succeeded"
            job.progress_percent = 100
            job.finished_at = self.clock()
            job.error_code = None
            job.error_message = None
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _finish_cancelled(self, owner: str, job_id: str) -> dict[str, Any]:
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == job_id,
                    MeetingProcessingJob.owner == owner,
                )
                .first()
            )
            if job is None:
                raise MeetingNotFound("Meeting job not found")
            job.status = "cancelled"
            job.cancel_requested = True
            job.error_code = "transcription_cancelled"
            job.error_message = "Meeting processing was cancelled"
            job.finished_at = self.clock()
            meeting = (
                db.query(MeetingRecord)
                .filter(MeetingRecord.id == job.meeting_id, MeetingRecord.owner == owner)
                .first()
            )
            if meeting and meeting.deleted_at is None:
                meeting.status = "cancelled"
                meeting.last_error_code = job.error_code
                meeting.last_error_message = job.error_message
                meeting.progress_percent = job.progress_percent
                meeting.revision += 1
            db.commit()
            db.refresh(job)
            return self._job_dict(job)
        finally:
            db.close()

    def _finish_failed(
        self,
        owner: str,
        job_id: str,
        *,
        code: str,
        message: str,
    ) -> dict[str, Any]:
        safe_code = re.sub(r"[^a-z0-9_.-]", "_", str(code or "meeting_processing_failed").lower())[:100]
        safe_message = _bounded_text(
            message or "Meeting processing failed",
            "error message",
            maximum=1000,
        )
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == job_id,
                    MeetingProcessingJob.owner == owner,
                )
                .first()
            )
            if job is None:
                raise MeetingNotFound("Meeting job not found")
            job.status = "failed"
            job.error_code = safe_code
            job.error_message = safe_message
            job.finished_at = self.clock()
            meeting = (
                db.query(MeetingRecord)
                .filter(MeetingRecord.id == job.meeting_id, MeetingRecord.owner == owner)
                .first()
            )
            if meeting and meeting.deleted_at is None:
                meeting.status = "failed"
                meeting.last_error_code = safe_code
                meeting.last_error_message = safe_message
                meeting.progress_percent = job.progress_percent
                meeting.revision += 1
            db.commit()
            db.refresh(job)
            return self._job_dict(job)
        finally:
            db.close()

    def _delete_media_if_due(self, owner: str, meeting_id: str, *, force: bool = False) -> bool:
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner, meeting_id)
            if not meeting.media_storage_key or meeting.media_deleted_at is not None:
                return False
            now = self.clock()
            if not force and (
                meeting.audio_delete_after is None or meeting.audio_delete_after > now
            ):
                return False
            storage_key = meeting.media_storage_key
            try:
                self._storage_path(storage_key).unlink(missing_ok=True)
            except OSError as exc:
                raise MeetingConflict("Meeting media could not be securely removed") from exc
            meeting.media_storage_key = None
            meeting.media_deleted_at = now
            meeting.revision += 1
            db.commit()
            return True
        finally:
            db.close()

    def run_job(self, owner: Optional[str], job_id: str) -> dict[str, Any]:
        """Run one durable job from a controlled worker process/thread."""

        owner_key = _owner_key(owner)
        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.id == str(job_id),
                    MeetingProcessingJob.owner == owner_key,
                )
                .first()
            )
            if job is None:
                raise MeetingNotFound("Meeting job not found")
            if job.status == "succeeded":
                return self._job_dict(job)
            if job.status != "queued":
                raise MeetingConflict("Meeting job is not queued")
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = self.clock()
                db.commit()
                return self._job_dict(job)
            if job.attempts >= job.max_attempts:
                raise MeetingConflict("Meeting job retry limit has been reached")
            meeting = self._owned_meeting(db, owner_key, job.meeting_id)
            now = self.clock()
            job.status = "running"
            job.started_at = now
            job.attempts += 1
            job.error_code = None
            job.error_message = None
            meeting.status = "transcribing" if job.kind == "transcribe" else "analyzing"
            meeting.progress_percent = max(job.progress_percent, 1 if job.kind == "transcribe" else 75)
            meeting.last_error_code = None
            meeting.last_error_message = None
            meeting.revision += 1
            storage_key = meeting.media_storage_key
            meeting_id = meeting.id
            kind = job.kind
            config_values = _json(job.config_json, {})
            db.commit()
        finally:
            db.close()

        cancel = lambda: self._job_cancel_requested(owner_key, job_id)
        progress = lambda value: self._set_progress(owner_key, job_id, value)
        try:
            if kind == "transcribe":
                if not storage_key:
                    raise MeetingConflict("Meeting media is unavailable")
                media_path = self._storage_path(storage_key, must_exist=True)
                config = _config_from(config_values)
                result = self.transcription_provider.transcribe(
                    media_path,
                    config,
                    cancel_requested=cancel,
                    progress=progress,
                )
                meeting_id, _created = self._persist_transcription(
                    owner_key,
                    job_id,
                    result,
                    config,
                )
                progress(80)
            request = self._analysis_request(owner_key, meeting_id)
            analysis = self.analyzer.analyze(request, cancel_requested=cancel)
            self._persist_analysis(owner_key, job_id, analysis)
            if kind == "transcribe":
                self._delete_media_if_due(owner_key, meeting_id)
            completed_job = self.get_job(owner_key, job_id)
            try:
                if self.event_sink is not None:
                    self.event_sink(
                        "meeting_completed",
                        owner_key,
                        payload={"meeting": {"id": meeting_id, "job_id": job_id}},
                        dedupe_key=(
                            f"meeting-completed:{meeting_id}:{completed_job.get('id')}"
                        ),
                    )
            except Exception:
                logger.debug("meeting_completed event dispatch failed", exc_info=True)
            return completed_job
        except TranscriptionCancelled:
            return self._finish_cancelled(owner_key, job_id)
        except TranscriptionContractError as exc:
            return self._finish_failed(
                owner_key,
                job_id,
                code=exc.code,
                message=str(exc),
            )
        except MeetingError as exc:
            return self._finish_failed(
                owner_key,
                job_id,
                code=exc.code,
                message=str(exc),
            )
        except Exception as exc:
            # Never persist provider exception text: it can contain a local
            # path, model prompt, or secret-bearing backend response.
            logger.warning(
                "Meeting job failed",
                extra={
                    "job_id": job_id,
                    "meeting_id": meeting_id,
                    "error_type": type(exc).__name__,
                },
            )
            return self._finish_failed(
                owner_key,
                job_id,
                code="meeting_processing_failed",
                message="Meeting processing failed; review local provider health and retry",
            )

    def edit_segment(
        self,
        owner: Optional[str],
        meeting_id: str,
        segment_id: str,
        values: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        allowed = {"text", "start_ms", "end_ms", "speaker_label"}
        unknown = set(values) - allowed
        if unknown:
            raise MeetingValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}")
        if not values:
            raise MeetingValidationError("At least one transcript field is required")
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            segment = (
                db.query(MeetingTranscriptSegment)
                .filter(
                    MeetingTranscriptSegment.id == str(segment_id),
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                    MeetingTranscriptSegment.active.is_(True),
                )
                .first()
            )
            if segment is None:
                raise MeetingNotFound("Transcript segment not found")
            if segment.revision != int(expected_revision):
                raise MeetingConflict("Transcript segment was changed by another request")
            new_text = (
                _bounded_text(
                    values["text"],
                    "text",
                    maximum=MAX_SEGMENT_CHARACTERS,
                    required=True,
                    strip=False,
                )
                if "text" in values
                else segment.text
            )
            new_start = int(values.get("start_ms", segment.start_ms))
            new_end = int(values.get("end_ms", segment.end_ms))
            if new_start < 0 or new_end < new_start:
                raise MeetingValidationError("Transcript timestamps are invalid")
            speaker_label = (
                _bounded_text(
                    values.get("speaker_label"), "speaker_label", maximum=100
                )
                or None
                if "speaker_label" in values
                else segment.speaker_label
            )
            revision = MeetingTranscriptRevision(
                id=str(uuid.uuid4()),
                meeting_id=meeting.id,
                segment_id=segment.id,
                owner=owner_key,
                prior_text=segment.text,
                prior_start_ms=segment.start_ms,
                prior_end_ms=segment.end_ms,
                prior_speaker_label=segment.speaker_label,
                resulting_revision=segment.revision + 1,
                edited_by=owner_key,
                edited_at=self.clock(),
            )
            db.add(revision)
            segment.text = new_text
            segment.start_ms = new_start
            segment.end_ms = new_end
            segment.speaker_label = speaker_label
            segment.is_edited = True
            segment.revision += 1
            segment.updated_at = self.clock()
            # Generated, unreviewed statements may no longer match their cited
            # text.  Hide them until reanalysis. Reviewed claims remain as a
            # traceable historical statement, using the prior revision audit.
            for claim in (
                db.query(MeetingClaim)
                .join(MeetingClaimEvidence, MeetingClaimEvidence.claim_id == MeetingClaim.id)
                .filter(
                    MeetingClaim.meeting_id == meeting.id,
                    MeetingClaim.active.is_(True),
                    MeetingClaimEvidence.segment_id == segment.id,
                )
                .all()
            ):
                if claim.approval_state not in {"approved", "confirmed"}:
                    claim.active = False
            meeting.status = "needs_reanalysis"
            meeting.transcript_revision += 1
            meeting.revision += 1
            meeting.updated_at = self.clock()
            db.commit()
            db.refresh(segment)
            return self._segment_dict(segment)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def transcript_revisions(
        self,
        owner: Optional[str],
        meeting_id: str,
        segment_id: str,
    ) -> list[dict[str, Any]]:
        owner_key = _owner_key(owner)
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            segment = (
                db.query(MeetingTranscriptSegment)
                .filter(
                    MeetingTranscriptSegment.id == str(segment_id),
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                )
                .first()
            )
            if segment is None:
                raise MeetingNotFound("Transcript segment not found")
            rows = (
                db.query(MeetingTranscriptRevision)
                .filter(
                    MeetingTranscriptRevision.meeting_id == meeting.id,
                    MeetingTranscriptRevision.segment_id == segment.id,
                    MeetingTranscriptRevision.owner == owner_key,
                )
                .order_by(MeetingTranscriptRevision.resulting_revision.desc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "prior_text": row.prior_text,
                    "prior_start_ms": row.prior_start_ms,
                    "prior_end_ms": row.prior_end_ms,
                    "prior_speaker_label": row.prior_speaker_label,
                    "resulting_revision": row.resulting_revision,
                    "edited_at": _iso(row.edited_at),
                }
                for row in rows
            ]
        finally:
            db.close()

    def map_speaker(
        self,
        owner: Optional[str],
        meeting_id: str,
        label: str,
        *,
        display_name: str,
        attendee_id: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        speaker_label = _bounded_text(label, "label", maximum=100, required=True)
        name = _bounded_text(
            display_name, "display_name", maximum=255, required=True
        )
        attendee = _bounded_text(attendee_id, "attendee_id", maximum=255) or None
        if confidence is not None:
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise MeetingValidationError("confidence must be between 0 and 1")
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            speaker = (
                db.query(MeetingSpeaker)
                .filter(
                    MeetingSpeaker.meeting_id == meeting.id,
                    MeetingSpeaker.label == speaker_label,
                )
                .first()
            )
            if speaker is None:
                speaker = MeetingSpeaker(
                    id=str(uuid.uuid4()),
                    meeting_id=meeting.id,
                    label=speaker_label,
                )
                db.add(speaker)
            speaker.display_name = name
            speaker.attendee_id = attendee
            speaker.confidence = confidence
            speaker.user_confirmed = True
            speaker.updated_at = self.clock()
            db.flush()
            (
                db.query(MeetingTranscriptSegment)
                .filter(
                    MeetingTranscriptSegment.meeting_id == meeting.id,
                    MeetingTranscriptSegment.active.is_(True),
                    MeetingTranscriptSegment.speaker_label == speaker_label,
                )
                .update(
                    {MeetingTranscriptSegment.speaker_id: speaker.id},
                    synchronize_session=False,
                )
            )
            meeting.revision += 1
            db.commit()
            db.refresh(speaker)
            return self._speaker_dict(speaker)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def review_claim(
        self,
        owner: Optional[str],
        meeting_id: str,
        claim_id: str,
        *,
        decision: str,
        confirm: bool,
        edited_text: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        if confirm is not True:
            raise MeetingApprovalRequired("Explicit confirmation is required")
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approve", "confirm", "reject"}:
            raise MeetingValidationError("decision must be approve, confirm, or reject")
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            claim = (
                db.query(MeetingClaim)
                .filter(
                    MeetingClaim.id == str(claim_id),
                    MeetingClaim.meeting_id == meeting.id,
                    MeetingClaim.active.is_(True),
                )
                .first()
            )
            if claim is None:
                raise MeetingNotFound("Meeting claim not found")
            if expected_revision is not None and claim.revision != int(expected_revision):
                raise MeetingConflict("Meeting claim was changed by another request")
            if claim.approval_state in {"approved", "confirmed", "rejected"}:
                expected_state = {
                    "approve": "approved",
                    "confirm": "confirmed",
                    "reject": "rejected",
                }[normalized]
                if claim.approval_state != expected_state:
                    raise MeetingConflict("Meeting claim has already been reviewed")
                return self._claim_dict(claim)
            if normalized == "confirm" and claim.kind != "decision":
                raise MeetingValidationError("Only a proposed decision can be confirmed")
            if normalized == "approve" and claim.kind == "decision":
                normalized = "confirm"
            if edited_text is not None:
                claim.text = _bounded_text(
                    edited_text,
                    "edited_text",
                    maximum=20_000,
                    required=True,
                )
                claim.revision += 1
            if normalized == "reject":
                claim.approval_state = "rejected"
                claim.reviewed_at = self.clock()
                claim.revision += 1
                meeting.revision += 1
                db.commit()
                db.refresh(claim)
                return self._claim_dict(claim)
            if claim.kind == "action_item":
                if self.task_sink is None:
                    raise MeetingProviderUnavailable(
                        "Task creation is unavailable until the work-domain sink is configured"
                    )
                evidence = sorted(claim.evidence, key=lambda item: item.start_ms)
                source = {
                    "type": "meeting",
                    "meeting_id": meeting.id,
                    "claim_id": claim.id,
                    "transcript_revision": meeting.transcript_revision,
                    "evidence": [
                        {
                            "segment_id": item.segment_id,
                            "start_ms": item.start_ms,
                            "end_ms": item.end_ms,
                            "speaker_label": item.speaker_label,
                            "excerpt": item.excerpt,
                        }
                        for item in evidence
                    ],
                    "trust_classification": TRANSCRIPT_TRUST_CLASSIFICATION,
                }
                # The sink's durable idempotency key prevents double task
                # creation across a crash between external creation and commit.
                task_result = self.task_sink.create_task_from_meeting(
                    owner=owner_key,
                    title=claim.text,
                    description=f"Approved action item from meeting: {meeting.title}",
                    source=source,
                    idempotency_key=f"meeting-claim:{claim.id}",
                )
                task_id = _bounded_text(
                    task_result.get("id"), "task id", maximum=255, required=True
                )
                claim.linked_resource_type = "task"
                claim.linked_resource_id = task_id
                link = (
                    db.query(MeetingLink)
                    .filter(
                        MeetingLink.meeting_id == meeting.id,
                        MeetingLink.link_type == "task",
                        MeetingLink.external_id == task_id,
                    )
                    .first()
                )
                if link is None:
                    db.add(
                        MeetingLink(
                            id=str(uuid.uuid4()),
                            meeting_id=meeting.id,
                            owner=owner_key,
                            link_type="task",
                            external_id=task_id,
                            label=claim.text[:500],
                            metadata_json=_canonical_json(
                                {"source_claim_id": claim.id}
                            ),
                        )
                    )
                claim.approval_state = "approved"
            elif normalized == "confirm":
                claim.approval_state = "confirmed"
            else:
                # Follow-up approval means "save this reviewed draft". It does
                # not send email; sending remains a separate Level-2 action.
                claim.approval_state = "approved"
            claim.reviewed_at = self.clock()
            claim.revision += 1
            meeting.revision += 1
            remaining = (
                db.query(MeetingClaim.id)
                .filter(
                    MeetingClaim.meeting_id == meeting.id,
                    MeetingClaim.active.is_(True),
                    MeetingClaim.approval_state == "pending",
                    MeetingClaim.id != claim.id,
                )
                .first()
            )
            if remaining is None:
                meeting.status = "complete"
            db.commit()
            db.refresh(claim)
            return self._claim_dict(claim)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add_link(
        self,
        owner: Optional[str],
        meeting_id: str,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        allowed = {"type", "external_id", "label", "url", "metadata"}
        unknown = set(values) - allowed
        if unknown:
            raise MeetingValidationError(f"Unknown field(s): {', '.join(sorted(unknown))}")
        link_type = _bounded_text(
            values.get("type"), "type", maximum=60, required=True
        ).lower()
        if link_type not in LINK_TYPES:
            raise MeetingValidationError("link type is invalid")
        external_id = _bounded_text(
            values.get("external_id"), "external_id", maximum=500, required=True
        )
        url = _bounded_text(values.get("url"), "url", maximum=4000)
        if url and not (url.startswith("https://") or url.startswith("http://localhost")):
            raise MeetingValidationError("link URL must use HTTPS or exact localhost HTTP")
        metadata = values.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise MeetingValidationError("metadata must be an object")
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            existing = (
                db.query(MeetingLink)
                .filter(
                    MeetingLink.meeting_id == meeting.id,
                    MeetingLink.link_type == link_type,
                    MeetingLink.external_id == external_id,
                )
                .first()
            )
            if existing:
                return self._link_dict(existing)
            link = MeetingLink(
                id=str(uuid.uuid4()),
                meeting_id=meeting.id,
                owner=owner_key,
                link_type=link_type,
                external_id=external_id,
                label=_bounded_text(values.get("label"), "label", maximum=500),
                url=url,
                metadata_json=_canonical_json(dict(metadata)),
                created_at=self.clock(),
            )
            db.add(link)
            if link_type == "project":
                meeting.project_id = external_id
            elif link_type == "calendar_event":
                meeting.calendar_event_id = external_id
            meeting.revision += 1
            db.commit()
            db.refresh(link)
            return self._link_dict(link)
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(MeetingLink)
                .filter(
                    MeetingLink.meeting_id == meeting_id,
                    MeetingLink.owner == owner_key,
                    MeetingLink.link_type == link_type,
                    MeetingLink.external_id == external_id,
                )
                .first()
            )
            if existing:
                return self._link_dict(existing)
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def save_to_knowledge(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        if confirm is not True:
            raise MeetingApprovalRequired("Explicit confirmation is required")
        if self.knowledge_sink is None:
            raise MeetingProviderUnavailable(
                "Knowledge ingestion is unavailable until a knowledge sink is configured"
            )
        meeting = self.get_meeting(owner_key, meeting_id)
        segments = meeting["segments"]
        if not segments:
            raise MeetingConflict("Meeting has no active transcript to save")
        lines = [
            f"[{item['start_ms']}-{item['end_ms']} ms] "
            f"{item.get('speaker_label') or 'Unknown speaker'}: {item['text']}"
            for item in segments
        ]
        content = "\n".join(lines)
        result = self.knowledge_sink.ingest_meeting(
            owner=owner_key,
            meeting_id=meeting_id,
            title=meeting["title"],
            content=content,
            metadata={
                "source_type": "meeting_transcript",
                "trust_classification": TRANSCRIPT_TRUST_CLASSIFICATION,
                "transcript_revision": meeting["transcription"]["revision"],
                "segment_count": len(segments),
            },
            idempotency_key=(
                f"meeting-knowledge:{meeting_id}:{meeting['transcription']['revision']}"
            ),
        )
        source_id = _bounded_text(
            result.get("id"), "knowledge source id", maximum=500, required=True
        )
        link = self.add_link(
            owner_key,
            meeting_id,
            {
                "type": "knowledge_source",
                "external_id": source_id,
                "label": "Meeting transcript",
                "metadata": {
                    "transcript_revision": meeting["transcription"]["revision"]
                },
            },
        )
        return {"knowledge_source": dict(result), "link": link}

    def export_meeting(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        format: str,
        confirm: bool,
    ) -> tuple[str, str, bytes]:
        if confirm is not True:
            raise MeetingApprovalRequired(
                "Exporting a private meeting requires explicit confirmation"
            )
        normalized = str(format or "json").strip().lower()
        if normalized not in {"json", "markdown", "txt"}:
            raise MeetingValidationError("export format must be json, markdown, or txt")
        meeting = self.get_meeting(owner, meeting_id)
        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", meeting["title"]).strip("-")[:80]
        safe_title = safe_title or "meeting"
        if normalized == "json":
            body = json.dumps(meeting, ensure_ascii=False, indent=2).encode("utf-8")
            return f"{safe_title}.json", "application/json", body
        lines = [
            f"# {meeting['title']}" if normalized == "markdown" else meeting["title"],
            "",
            f"Status: {meeting['status']}",
            f"Trust classification: {TRANSCRIPT_TRUST_CLASSIFICATION}",
            "",
            "## Transcript" if normalized == "markdown" else "TRANSCRIPT",
            "",
        ]
        for segment in meeting["segments"]:
            label = segment.get("speaker_label") or "Unknown speaker"
            lines.append(
                f"[{segment['start_ms']}-{segment['end_ms']} ms] {label}: {segment['text']}"
            )
        lines.extend(
            [
                "",
                "## Source-linked statements"
                if normalized == "markdown"
                else "SOURCE-LINKED STATEMENTS",
                "",
            ]
        )
        for claim in meeting["claims"]:
            evidence = ", ".join(
                f"{item['start_ms']}-{item['end_ms']} ms"
                for item in claim["evidence"]
            )
            lines.append(
                f"- [{claim['kind']}; {claim['fact_state']}] {claim['text']} (evidence: {evidence})"
            )
        extension = "md" if normalized == "markdown" else "txt"
        media_type = "text/markdown" if normalized == "markdown" else "text/plain"
        return f"{safe_title}.{extension}", media_type, ("\n".join(lines) + "\n").encode("utf-8")

    def update_retention(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        audio_days: Optional[int],
        transcript_days: Optional[int],
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        try:
            config = TranscriptionConfig(
                audio_retention_days=audio_days,
                transcript_retention_days=transcript_days,
            )
        except ValueError as exc:
            raise MeetingValidationError(str(exc)) from exc
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            now = self.clock()
            meeting.audio_retention_days = config.audio_retention_days
            meeting.transcript_retention_days = config.transcript_retention_days
            meeting.audio_delete_after = _retention_deadline(now, config.audio_retention_days)
            meeting.transcript_delete_after = _retention_deadline(
                now, config.transcript_retention_days
            )
            meeting.revision += 1
            db.commit()
            db.refresh(meeting)
            return self._meeting_summary(meeting)
        finally:
            db.close()

    def _purge_transcript(self, db, meeting: MeetingRecord, now: datetime) -> None:
        db.query(MeetingTranscriptRevision).filter(
            MeetingTranscriptRevision.meeting_id == meeting.id
        ).delete(synchronize_session=False)
        claim_ids = [
            row[0]
            for row in db.query(MeetingClaim.id)
            .filter(MeetingClaim.meeting_id == meeting.id)
            .all()
        ]
        if claim_ids:
            db.query(MeetingClaimEvidence).filter(
                MeetingClaimEvidence.claim_id.in_(claim_ids)
            ).delete(synchronize_session=False)
        db.query(MeetingClaim).filter(MeetingClaim.meeting_id == meeting.id).delete(
            synchronize_session=False
        )
        db.query(MeetingTranscriptSegment).filter(
            MeetingTranscriptSegment.meeting_id == meeting.id
        ).delete(synchronize_session=False)
        db.query(MeetingSpeaker).filter(MeetingSpeaker.meeting_id == meeting.id).delete(
            synchronize_session=False
        )
        meeting.transcript_deleted_at = now
        meeting.status = "transcript_expired"
        meeting.transcript_revision += 1
        meeting.revision += 1

    def purge_expired(self, owner: Optional[str]) -> dict[str, int]:
        owner_key = _owner_key(owner)
        now = self.clock()
        db = self.session_factory()
        audio_purged = 0
        transcript_purged = 0
        try:
            meetings = (
                db.query(MeetingRecord)
                .filter(MeetingRecord.owner == owner_key, MeetingRecord.deleted_at.is_(None))
                .all()
            )
            for meeting in meetings:
                if (
                    meeting.media_storage_key
                    and meeting.media_deleted_at is None
                    and meeting.audio_delete_after is not None
                    and meeting.audio_delete_after <= now
                ):
                    try:
                        self._storage_path(meeting.media_storage_key).unlink(missing_ok=True)
                    except OSError:
                        logger.warning(
                            "Could not purge expired meeting media",
                            extra={"meeting_id": meeting.id},
                        )
                    else:
                        meeting.media_storage_key = None
                        meeting.media_deleted_at = now
                        meeting.revision += 1
                        audio_purged += 1
                segment_exists = (
                    db.query(MeetingTranscriptSegment.id)
                    .filter(MeetingTranscriptSegment.meeting_id == meeting.id)
                    .first()
                )
                if (
                    segment_exists
                    and meeting.transcript_delete_after is not None
                    and meeting.transcript_delete_after <= now
                ):
                    self._purge_transcript(db, meeting, now)
                    transcript_purged += 1
            db.commit()
            return {
                "audio_purged": audio_purged,
                "transcripts_purged": transcript_purged,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_meeting(
        self,
        owner: Optional[str],
        meeting_id: str,
        *,
        confirm: bool,
        purge_record: bool = False,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        if confirm is not True:
            raise MeetingApprovalRequired("Deleting a meeting requires explicit confirmation")
        db = self.session_factory()
        try:
            meeting = self._owned_meeting(db, owner_key, meeting_id)
            storage_key = meeting.media_storage_key
            if storage_key:
                try:
                    self._storage_path(storage_key).unlink(missing_ok=True)
                except OSError as exc:
                    raise MeetingConflict(
                        "Meeting media could not be removed; the database record was retained"
                    ) from exc
            now = self.clock()
            if purge_record:
                db.delete(meeting)
                db.commit()
                return {"id": meeting_id, "deleted": True, "purged": True}
            self._purge_transcript(db, meeting, now)
            db.query(MeetingLink).filter(MeetingLink.meeting_id == meeting.id).delete(
                synchronize_session=False
            )
            db.query(MeetingProcessingJob).filter(
                MeetingProcessingJob.meeting_id == meeting.id
            ).delete(synchronize_session=False)
            meeting.title = "Deleted meeting"
            meeting.description = ""
            meeting.attendee_names_json = "[]"
            meeting.original_filename = None
            meeting.media_type = None
            meeting.media_kind = None
            meeting.media_storage_key = None
            meeting.media_sha256 = None
            meeting.media_bytes = None
            meeting.media_deleted_at = now
            meeting.calendar_event_id = None
            meeting.project_id = None
            meeting.status = "deleted"
            meeting.deleted_at = now
            meeting.revision += 1
            db.commit()
            return {"id": meeting_id, "deleted": True, "purged": False}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def provider_status(self) -> dict[str, Any]:
        try:
            health = dict(self.transcription_provider.health())
            capabilities = dict(self.transcription_provider.capabilities())
        except Exception:
            health = {
                "status": "degraded",
                "provider": getattr(self.transcription_provider, "name", "unknown"),
                "recommended_repair": "Inspect the local transcription provider configuration",
            }
            capabilities = {}
        # Provider status is public configuration only. Defensive removal keeps
        # a non-conforming adapter from exposing a token or filesystem path.
        for key in list(health):
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("token", "secret", "password", "api_key", "path")):
                health.pop(key, None)
        return {
            "health": health,
            "capabilities": capabilities,
            "limits": {
                "max_upload_bytes": self.max_upload_bytes,
                "supported_extensions": sorted(_SUPPORTED_MEDIA),
                "stable_realtime": False,
            },
        }

    def next_queued_job(self) -> Optional[tuple[str, str]]:
        """Return the oldest durable job for the local worker.

        ``run_job`` performs the authoritative queued-to-running transition,
        so concurrent workers remain fail-closed if they observe the same row.
        """

        db = self.session_factory()
        try:
            job = (
                db.query(MeetingProcessingJob)
                .filter(
                    MeetingProcessingJob.status == "queued",
                    MeetingProcessingJob.cancel_requested.is_(False),
                )
                .order_by(MeetingProcessingJob.queued_at, MeetingProcessingJob.id)
                .first()
            )
            return (job.owner, job.id) if job is not None else None
        finally:
            db.close()

    def recover_interrupted_jobs(self) -> int:
        """Requeue jobs left running by a process interruption."""

        db = self.session_factory()
        recovered = 0
        try:
            rows = (
                db.query(MeetingProcessingJob)
                .filter(MeetingProcessingJob.status == "running")
                .all()
            )
            now = self.clock()
            for job in rows:
                if job.cancel_requested or job.attempts >= job.max_attempts:
                    job.status = "cancelled" if job.cancel_requested else "failed"
                    job.finished_at = now
                    job.error_code = (
                        "transcription_cancelled"
                        if job.cancel_requested
                        else "meeting_retry_limit_reached"
                    )
                    job.error_message = (
                        "Meeting processing was cancelled"
                        if job.cancel_requested
                        else "Meeting processing stopped after reaching its retry limit"
                    )
                else:
                    job.status = "queued"
                    job.started_at = None
                    job.finished_at = None
                    job.error_code = "worker_interrupted"
                    job.error_message = "Meeting processing was interrupted and requeued"
                    job.queued_at = now
                job.updated_at = now
                meeting = (
                    db.query(MeetingRecord)
                    .filter(
                        MeetingRecord.id == job.meeting_id,
                        MeetingRecord.owner == job.owner,
                        MeetingRecord.deleted_at.is_(None),
                    )
                    .first()
                )
                if meeting is not None:
                    meeting.status = (
                        "queued" if job.status == "queued" else job.status
                    )
                    meeting.last_error_code = job.error_code
                    meeting.last_error_message = job.error_message
                    meeting.revision += 1
                    meeting.updated_at = now
                recovered += 1
            db.commit()
            return recovered
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


_default_meeting_service: Optional[MeetingService] = None


def get_meeting_service() -> MeetingService:
    """Return the process-wide meeting service used by routes and workers."""

    global _default_meeting_service
    if _default_meeting_service is None:
        from services.meeting_integrations import KnowledgeMeetingSink, WorkMeetingTaskSink
        from src.event_bus import fire_event

        _default_meeting_service = MeetingService(
            task_sink=WorkMeetingTaskSink(),
            knowledge_sink=KnowledgeMeetingSink(),
            event_sink=fire_event,
        )
    return _default_meeting_service
