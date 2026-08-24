"""Dependency-light contracts for meeting transcription and analysis.

The meeting domain deliberately keeps provider payloads away from ORM and
FastAPI types.  Adapters can therefore be contract-tested without importing
the application, and workers can run in a separate process later without
changing the persisted domain model.

Transcript text is always labelled as untrusted user content.  Implementations
must treat it as data: it cannot change instructions, grant permissions, or
authorize a tool call.  The domain service independently validates every
generated claim and requires explicit approval before invoking a task or
knowledge sink.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence


TRANSCRIPT_TRUST_CLASSIFICATION = "untrusted_user_content"
TRANSCRIPTION_CONTRACT_VERSION = "1.0"

ALLOWED_DEVICES = frozenset({"auto", "cpu", "cuda"})
ALLOWED_QUANTIZATIONS = frozenset(
    {"auto", "int8", "int8_float16", "float16", "float32"}
)
ALLOWED_TIMESTAMP_GRANULARITIES = frozenset({"segment", "word"})


class TranscriptionContractError(RuntimeError):
    """Base class for normalized provider failures."""

    code = "transcription_error"
    retryable = False


class TranscriptionUnavailable(TranscriptionContractError):
    code = "transcription_unavailable"
    retryable = True


class TranscriptionCapabilityError(TranscriptionContractError):
    code = "transcription_capability_unavailable"


class TranscriptionCancelled(TranscriptionContractError):
    code = "transcription_cancelled"


class TranscriptionInvalidResult(TranscriptionContractError):
    code = "invalid_transcription_result"


@dataclass(frozen=True, slots=True)
class TranscriptionConfig:
    """Local-first provider configuration captured with each durable job."""

    model: str = "base"
    language: Optional[str] = None
    device: str = "auto"
    quantization: str = "auto"
    diarization: bool = False
    timestamp_granularity: str = "segment"
    max_upload_bytes: int = 500 * 1024 * 1024
    audio_retention_days: Optional[int] = 0
    transcript_retention_days: Optional[int] = 365
    allow_model_download: bool = False

    def __post_init__(self) -> None:
        model = str(self.model or "").strip()
        if not model or len(model) > 240 or any(ord(ch) < 32 for ch in model):
            raise ValueError("model must be a non-empty printable value")
        if self.language is not None:
            language = str(self.language).strip()
            if not language or len(language) > 32:
                raise ValueError("language must be null or 1-32 characters")
        if self.device not in ALLOWED_DEVICES:
            raise ValueError(f"device must be one of {sorted(ALLOWED_DEVICES)}")
        if self.quantization not in ALLOWED_QUANTIZATIONS:
            raise ValueError(
                f"quantization must be one of {sorted(ALLOWED_QUANTIZATIONS)}"
            )
        if self.timestamp_granularity not in ALLOWED_TIMESTAMP_GRANULARITIES:
            raise ValueError(
                "timestamp_granularity must be 'segment' or 'word'"
            )
        if not 1 <= int(self.max_upload_bytes) <= 10 * 1024 * 1024 * 1024:
            raise ValueError("max_upload_bytes must be between 1 byte and 10 GiB")
        for field_name in ("audio_retention_days", "transcript_retention_days"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= int(value) <= 3650:
                raise ValueError(f"{field_name} must be null or between 0 and 3650")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "language": self.language,
            "device": self.device,
            "quantization": self.quantization,
            "diarization": self.diarization,
            "timestamp_granularity": self.timestamp_granularity,
            "max_upload_bytes": self.max_upload_bytes,
            "audio_retention_days": self.audio_retention_days,
            "transcript_retention_days": self.transcript_retention_days,
            "allow_model_download": self.allow_model_download,
        }

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "TranscriptionConfig":
        allowed = set(cls.__dataclass_fields__)
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unknown transcription setting(s): {', '.join(sorted(unknown))}")
        return cls(**dict(values))


@dataclass(frozen=True, slots=True)
class TranscriptionWord:
    text: str
    start_ms: int
    end_ms: int
    confidence: Optional[float] = None


@dataclass(frozen=True, slots=True)
class TranscriptionSegmentResult:
    text: str
    start_ms: int
    end_ms: int
    speaker_label: Optional[str] = None
    confidence: Optional[float] = None
    words: tuple[TranscriptionWord, ...] = ()


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    segments: tuple[TranscriptionSegmentResult, ...]
    language: Optional[str]
    duration_ms: Optional[int]
    provider: str
    model: str
    provider_version: str = "unknown"
    diarization_applied: bool = False
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class TranscriptionProvider(Protocol):
    """Contract implemented by local/private transcription adapters."""

    name: str
    version: str

    def capabilities(self) -> Mapping[str, Any]: ...

    def health(self) -> Mapping[str, Any]: ...

    def transcribe(
        self,
        media_path: Path,
        config: TranscriptionConfig,
        *,
        cancel_requested: Callable[[], bool],
        progress: Callable[[int], None],
    ) -> TranscriptionResult: ...


@dataclass(frozen=True, slots=True)
class UntrustedTranscriptSegment:
    id: str
    text: str
    start_ms: int
    end_ms: int
    speaker_label: Optional[str]
    confidence: Optional[float]
    trust_classification: str = TRANSCRIPT_TRUST_CLASSIFICATION


@dataclass(frozen=True, slots=True)
class MeetingAnalysisRequest:
    meeting_id: str
    title: str
    segments: tuple[UntrustedTranscriptSegment, ...]
    trust_classification: str = TRANSCRIPT_TRUST_CLASSIFICATION


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    segment_id: str
    start_ms: int
    end_ms: int
    speaker_label: Optional[str] = None


@dataclass(frozen=True, slots=True)
class GeneratedMeetingClaim:
    """A generated statement that is inert until the service persists it."""

    kind: str
    text: str
    evidence: tuple[ClaimEvidence, ...]
    inferred: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MeetingAnalysisResult:
    claims: tuple[GeneratedMeetingClaim, ...]
    warnings: tuple[str, ...] = ()
    analyzer: str = "unknown"
    analyzer_version: str = "unknown"


class MeetingAnalyzer(Protocol):
    name: str
    version: str

    def analyze(
        self,
        request: MeetingAnalysisRequest,
        *,
        cancel_requested: Callable[[], bool],
    ) -> MeetingAnalysisResult: ...


class TaskProposalSink(Protocol):
    """Approval-only bridge into the canonical task domain.

    Implementations MUST make ``idempotency_key`` durable before creating a
    task, because worker interruption may repeat the call.
    """

    def create_task_from_meeting(
        self,
        *,
        owner: str,
        title: str,
        description: str,
        source: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...


class MeetingKnowledgeSink(Protocol):
    """Explicit-save bridge into the knowledge ingestion domain."""

    def ingest_meeting(
        self,
        *,
        owner: str,
        meeting_id: str,
        title: str,
        content: str,
        metadata: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...


# These dependency-light declarations are intentionally not registered here.
# Root integration should translate them into canonical ToolSpec values so the
# central policy engine remains the sole execution/approval boundary.
MEETING_TOOL_CONTRACTS: tuple[Mapping[str, Any], ...] = (
    {
        "name": "search_meetings",
        "domain": "meetings",
        "permission": "meetings.read",
        "risk": "level_0",
        "confirmation": "never",
        "operation": "query",
    },
    {
        "name": "create_meeting",
        "domain": "meetings",
        "permission": "meetings.record",
        "risk": "level_1",
        "confirmation": "trusted_mode_only",
        "operation": "create",
    },
    {
        "name": "request_meeting_transcription",
        "domain": "meetings",
        "permission": "meetings.transcribe",
        "risk": "level_1",
        "confirmation": "trusted_mode_only",
        "operation": "enqueue",
    },
    {
        "name": "approve_meeting_action_item",
        "domain": "meetings",
        "permissions": ("meetings.write", "tasks.write"),
        "risk": "level_2",
        "confirmation": "always",
        "operation": "approve_action",
    },
    {
        "name": "delete_meeting",
        "domain": "meetings",
        "permission": "meetings.delete",
        "risk": "level_3",
        "confirmation": "always",
        "operation": "delete",
    },
)
