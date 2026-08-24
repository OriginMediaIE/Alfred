"""Narrow, source-linked bridges from reviewed meetings into product domains."""

from __future__ import annotations

import json
import threading
from typing import Any, Mapping, Optional

from src.work_service import MutationContext, WorkService, get_work_service
from services.knowledge_service import KnowledgeService, get_knowledge_service


class WorkMeetingTaskSink:
    """Create exactly one canonical work task per approved meeting claim.

    The durable source id survives a crash between task creation and the
    meeting claim commit. A process lock closes the only concurrency window in
    the supported single-process deployment model.
    """

    def __init__(self, service: Optional[WorkService] = None) -> None:
        self.service = service or get_work_service()
        self._lock = threading.RLock()

    def create_task_from_meeting(
        self,
        *,
        owner: str,
        title: str,
        description: str,
        source: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        source_id = str(idempotency_key or "").strip()
        if not source_id:
            raise ValueError("idempotency_key is required")
        meeting_id = str(source.get("meeting_id") or "").strip()
        if not meeting_id:
            raise ValueError("meeting source requires meeting_id")
        with self._lock:
            existing = self.service.find_task_by_source(
                owner,
                source_type="meeting",
                source_id=source_id,
            )
            if existing is not None:
                return existing
            evidence = source.get("evidence") or []
            excerpt = json.dumps(
                {
                    "meeting_id": meeting_id,
                    "claim_id": source.get("claim_id"),
                    "transcript_revision": source.get("transcript_revision"),
                    "evidence": evidence,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )[:10_000]
            return self.service.create_task(
                owner,
                {
                    "title": title,
                    "description": description,
                    "status": "inbox",
                    "source_type": "meeting",
                    "source_id": source_id,
                    "source_excerpt": excerpt,
                    "references": [
                        {
                            "type": "meeting",
                            "external_id": meeting_id,
                            "label": "Meeting action item",
                            "metadata": {
                                "claim_id": source.get("claim_id"),
                                "transcript_revision": source.get(
                                    "transcript_revision"
                                ),
                                "evidence": evidence,
                                "trust_classification": source.get(
                                    "trust_classification"
                                ),
                            },
                        }
                    ],
                },
                context=MutationContext(
                    actor_kind="integration",
                    actor_id=owner,
                    correlation_id=source_id,
                ),
            )


class KnowledgeMeetingSink:
    """Ingest an approved transcript into the canonical private index."""

    def __init__(self, service: Optional[KnowledgeService] = None) -> None:
        self.service = service or get_knowledge_service()

    def ingest_meeting(
        self,
        *,
        owner: str,
        meeting_id: str,
        title: str,
        content: str,
        metadata: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        return self.service.ingest_text(
            owner,
            source_type="meeting_transcript",
            title=title,
            content=content,
            metadata={"meeting_id": meeting_id, **dict(metadata)},
            original_location=f"meeting:{meeting_id}",
            sensitivity="confidential",
            idempotency_key=idempotency_key,
        )


__all__ = ["KnowledgeMeetingSink", "WorkMeetingTaskSink"]
