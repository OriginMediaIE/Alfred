"""Isolated relational schema for the OM Automate meeting domain.

The application currently lacks a versioned, shared migration system.  To
avoid another import-time mutation of ``core.database``, this slice owns a
small declarative base and accepts an injected SQLAlchemy session factory.
``ensure_meeting_schema`` is intentionally explicit and idempotent; the ADR
documents how these tables move into the future migration framework.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from src.schema_migrations import Migration, run_migrations


MEETING_SCHEMA_VERSION = 1
MeetingBase = declarative_base()


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MeetingSchemaMeta(MeetingBase):
    __tablename__ = "meeting_schema_meta"

    key = Column(String(100), primary_key=True)
    value = Column(String(100), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive)


class MeetingRecord(MeetingBase):
    __tablename__ = "meeting_records"

    id = Column(String(36), primary_key=True)
    owner = Column(String(255), nullable=False, default="", index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(40), nullable=False, default="draft", index=True)
    source_type = Column(String(40), nullable=False, default="manual")
    calendar_event_id = Column(String(500), nullable=True, index=True)
    project_id = Column(String(100), nullable=True, index=True)
    scheduled_start = Column(DateTime, nullable=True, index=True)
    scheduled_end = Column(DateTime, nullable=True)
    timezone = Column(String(100), nullable=False, default="UTC")
    attendee_names_json = Column(Text, nullable=False, default="[]")

    original_filename = Column(String(255), nullable=True)
    media_type = Column(String(120), nullable=True)
    media_kind = Column(String(20), nullable=True)
    media_storage_key = Column(String(500), nullable=True, unique=True)
    media_sha256 = Column(String(64), nullable=True)
    media_bytes = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    recording_consent_at = Column(DateTime, nullable=True)

    transcription_provider = Column(String(100), nullable=True)
    transcription_provider_version = Column(String(100), nullable=True)
    transcription_model = Column(String(240), nullable=True)
    detected_language = Column(String(40), nullable=True)
    transcription_config_json = Column(Text, nullable=False, default="{}")
    transcription_warnings_json = Column(Text, nullable=False, default="[]")
    transcript_revision = Column(Integer, nullable=False, default=0)
    progress_percent = Column(Integer, nullable=False, default=0)
    last_error_code = Column(String(100), nullable=True)
    last_error_message = Column(String(1000), nullable=True)

    audio_retention_days = Column(Integer, nullable=True, default=0)
    transcript_retention_days = Column(Integer, nullable=True, default=365)
    audio_delete_after = Column(DateTime, nullable=True, index=True)
    transcript_delete_after = Column(DateTime, nullable=True, index=True)
    media_deleted_at = Column(DateTime, nullable=True)
    transcript_deleted_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )
    revision = Column(Integer, nullable=False, default=1)

    segments = relationship(
        "MeetingTranscriptSegment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        back_populates="meeting",
    )
    speakers = relationship(
        "MeetingSpeaker",
        cascade="all, delete-orphan",
        passive_deletes=True,
        back_populates="meeting",
    )
    claims = relationship(
        "MeetingClaim",
        cascade="all, delete-orphan",
        passive_deletes=True,
        back_populates="meeting",
    )
    links = relationship(
        "MeetingLink",
        cascade="all, delete-orphan",
        passive_deletes=True,
        back_populates="meeting",
    )
    jobs = relationship(
        "MeetingProcessingJob",
        cascade="all, delete-orphan",
        passive_deletes=True,
        back_populates="meeting",
    )

    __table_args__ = (
        UniqueConstraint(
            "owner",
            "media_sha256",
            name="ux_meeting_records_owner_media_sha256",
        ),
        Index("ix_meeting_records_owner_status_created", "owner", "status", "created_at"),
        Index("ix_meeting_records_owner_calendar", "owner", "calendar_event_id"),
    )


class MeetingTranscriptSegment(MeetingBase):
    __tablename__ = "meeting_transcript_segments"

    id = Column(String(36), primary_key=True)
    meeting_id = Column(
        String(36),
        ForeignKey("meeting_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation = Column(Integer, nullable=False, default=1)
    position = Column(Integer, nullable=False)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    speaker_label = Column(String(100), nullable=True)
    speaker_id = Column(String(36), nullable=True, index=True)
    confidence = Column(Float, nullable=True)
    words_json = Column(Text, nullable=False, default="[]")
    trust_classification = Column(
        String(80), nullable=False, default="untrusted_user_content"
    )
    active = Column(Boolean, nullable=False, default=True, index=True)
    is_edited = Column(Boolean, nullable=False, default=False)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )

    meeting = relationship("MeetingRecord", back_populates="segments")

    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "generation",
            "position",
            name="ux_meeting_segment_generation_position",
        ),
        Index(
            "ix_meeting_segments_meeting_time",
            "meeting_id",
            "active",
            "start_ms",
            "end_ms",
        ),
    )


class MeetingTranscriptRevision(MeetingBase):
    __tablename__ = "meeting_transcript_revisions"

    id = Column(String(36), primary_key=True)
    meeting_id = Column(
        String(36),
        ForeignKey("meeting_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id = Column(
        String(36),
        ForeignKey("meeting_transcript_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner = Column(String(255), nullable=False, default="", index=True)
    prior_text = Column(Text, nullable=False)
    prior_start_ms = Column(Integer, nullable=False)
    prior_end_ms = Column(Integer, nullable=False)
    prior_speaker_label = Column(String(100), nullable=True)
    resulting_revision = Column(Integer, nullable=False)
    edited_by = Column(String(255), nullable=False, default="")
    edited_at = Column(DateTime, nullable=False, default=utcnow_naive)


class MeetingSpeaker(MeetingBase):
    __tablename__ = "meeting_speakers"

    id = Column(String(36), primary_key=True)
    meeting_id = Column(
        String(36),
        ForeignKey("meeting_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label = Column(String(100), nullable=False)
    display_name = Column(String(255), nullable=True)
    attendee_id = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    user_confirmed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )

    meeting = relationship("MeetingRecord", back_populates="speakers")

    __table_args__ = (
        UniqueConstraint("meeting_id", "label", name="ux_meeting_speaker_label"),
    )


class MeetingClaim(MeetingBase):
    __tablename__ = "meeting_claims"

    id = Column(String(36), primary_key=True)
    meeting_id = Column(
        String(36),
        ForeignKey("meeting_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(40), nullable=False, index=True)
    text = Column(Text, nullable=False)
    inferred = Column(Boolean, nullable=False, default=True)
    approval_state = Column(String(40), nullable=False, default="pending", index=True)
    created_by = Column(String(40), nullable=False, default="analyzer")
    analyzer = Column(String(100), nullable=True)
    analyzer_version = Column(String(100), nullable=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    linked_resource_type = Column(String(60), nullable=True)
    linked_resource_id = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=False, default=True, index=True)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )
    reviewed_at = Column(DateTime, nullable=True)

    meeting = relationship("MeetingRecord", back_populates="claims")
    evidence = relationship(
        "MeetingClaimEvidence",
        cascade="all, delete-orphan",
        passive_deletes=True,
        back_populates="claim",
    )

    __table_args__ = (
        Index("ix_meeting_claims_meeting_active_kind", "meeting_id", "active", "kind"),
    )


class MeetingClaimEvidence(MeetingBase):
    __tablename__ = "meeting_claim_evidence"

    id = Column(String(36), primary_key=True)
    claim_id = Column(
        String(36),
        ForeignKey("meeting_claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id = Column(
        String(36),
        ForeignKey("meeting_transcript_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    speaker_label = Column(String(100), nullable=True)
    excerpt = Column(Text, nullable=False, default="")

    claim = relationship("MeetingClaim", back_populates="evidence")

    __table_args__ = (
        UniqueConstraint("claim_id", "segment_id", name="ux_meeting_claim_segment"),
    )


class MeetingLink(MeetingBase):
    __tablename__ = "meeting_links"

    id = Column(String(36), primary_key=True)
    meeting_id = Column(
        String(36),
        ForeignKey("meeting_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner = Column(String(255), nullable=False, default="", index=True)
    link_type = Column(String(60), nullable=False, index=True)
    external_id = Column(String(500), nullable=False)
    label = Column(String(500), nullable=False, default="")
    url = Column(Text, nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)

    meeting = relationship("MeetingRecord", back_populates="links")

    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "link_type", "external_id", name="ux_meeting_link_target"
        ),
        Index("ix_meeting_links_owner_type", "owner", "link_type"),
    )


class MeetingProcessingJob(MeetingBase):
    __tablename__ = "meeting_processing_jobs"

    id = Column(String(36), primary_key=True)
    meeting_id = Column(
        String(36),
        ForeignKey("meeting_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner = Column(String(255), nullable=False, default="", index=True)
    kind = Column(String(40), nullable=False, default="transcribe")
    status = Column(String(40), nullable=False, default="queued", index=True)
    progress_percent = Column(Integer, nullable=False, default=0)
    config_json = Column(Text, nullable=False, default="{}")
    idempotency_key = Column(String(200), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    replace_edited = Column(Boolean, nullable=False, default=False)
    error_code = Column(String(100), nullable=True)
    error_message = Column(String(1000), nullable=True)
    correlation_id = Column(String(200), nullable=False, default="")
    queued_at = Column(DateTime, nullable=False, default=utcnow_naive)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )

    meeting = relationship("MeetingRecord", back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("owner", "idempotency_key", name="ux_meeting_job_idempotency"),
        Index("ix_meeting_jobs_status_queued", "status", "queued_at"),
        Index("ix_meeting_jobs_owner_meeting", "owner", "meeting_id"),
    )


def ensure_meeting_schema(engine) -> None:
    """Create the isolated v1 schema and record its version explicitly."""

    applied = run_migrations(
        engine,
        "meetings",
        (Migration(1, "create_meeting_domain", lambda bind: MeetingBase.metadata.create_all(bind)),),
    )
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = factory()
    try:
        row = db.get(MeetingSchemaMeta, "schema_version")
        if row is None:
            db.add(
                MeetingSchemaMeta(
                    key="schema_version",
                    value=str(MEETING_SCHEMA_VERSION),
                )
            )
            db.commit()
        elif row.value != str(MEETING_SCHEMA_VERSION):
            raise RuntimeError(
                "Meeting schema version is unsupported; run the documented migration"
            )
    finally:
        db.close()
    return applied
