"""Enforce owner retention preferences across local derivative stores."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any

from src.constants import SCHEDULED_EMAILS_DB

SCHEDULED_DB = Path(SCHEDULED_EMAILS_DB)

logger = logging.getLogger(__name__)

_EMAIL_CACHE_TABLES = {
    "email_summaries": "created_at",
    "email_ai_replies": "created_at",
    "email_translations": "created_at",
    "email_tags": "created_at",
    "email_calendar_extractions": "created_at",
    "email_urgency_alerts": "created_at",
    "email_event_seen": "first_seen_at",
    "email_message_index": "updated_at",
    "email_body_preview_cache": "updated_at",
    "email_attachment_metadata_cache": "updated_at",
}


def purge_email_cache(
    owner: str | None,
    retention_days: int,
    *,
    database_path: str | Path = SCHEDULED_DB,
) -> int:
    """Purge only owner-scoped cache tables, never scheduled outgoing mail."""
    path = Path(database_path)
    if not path.exists():
        return 0
    owner_key = str(owner or "")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(retention_days))).isoformat()
    deleted = 0
    with sqlite3.connect(str(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table, timestamp_column in _EMAIL_CACHE_TABLES.items():
            if table not in tables:
                continue
            columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            if "owner" not in columns or timestamp_column not in columns:
                continue
            cursor = connection.execute(
                f'DELETE FROM "{table}" WHERE owner=? '
                f'AND datetime("{timestamp_column}") < datetime(?)',
                (owner_key, cutoff),
            )
            deleted += max(0, int(cursor.rowcount or 0))
        connection.commit()
    return deleted


class PrivacyRetentionService:
    def __init__(self, *, session_manager, upload_handler):
        self.session_manager = session_manager
        self.upload_handler = upload_handler

    async def purge_owner(self, owner: str | None) -> dict[str, Any]:
        from services.privacy_service import get_privacy_service
        settings = get_privacy_service().get(owner)
        result: dict[str, Any] = {
            "owner": owner,
            "conversations_purged": 0,
            "email_cache_rows_purged": 0,
            "files_purged": 0,
            "memories_purged": 0,
            "knowledge_sources_expired": 0,
            "meeting_audio_purged": 0,
            "meeting_transcripts_purged": 0,
        }
        if settings.get("conversation_retention_days") is not None:
            from src.cleanup_service import purge_conversations_by_retention
            result["conversations_purged"] = await asyncio.to_thread(
                purge_conversations_by_retention,
                self.session_manager,
                owner,
                int(settings["conversation_retention_days"]),
            )
        if settings.get("email_retention_days") is not None:
            result["email_cache_rows_purged"] = await asyncio.to_thread(
                purge_email_cache, owner, int(settings["email_retention_days"])
            )
        if settings.get("file_retention_days") is not None:
            result["files_purged"] = await asyncio.to_thread(
                self.upload_handler.cleanup_old_uploads,
                owner,
                int(settings["file_retention_days"]),
            )
        from services.knowledge_service import get_knowledge_service
        knowledge = await asyncio.to_thread(
            get_knowledge_service().purge_expired,
            owner,
            memory_retention_days=settings.get("memory_retention_days"),
        )
        result["memories_purged"] = knowledge["memories_purged"]
        result["knowledge_sources_expired"] = knowledge["sources_expired"]
        from services.meeting_service import get_meeting_service
        meetings = await asyncio.to_thread(get_meeting_service().purge_expired, owner)
        result["meeting_audio_purged"] = meetings["audio_purged"]
        result["meeting_transcripts_purged"] = meetings["transcripts_purged"]
        return result

    async def purge_configured_owners(self) -> list[dict[str, Any]]:
        from services.privacy_service import get_privacy_service
        results = []
        for owner in get_privacy_service().configured_owners():
            try:
                results.append(await self.purge_owner(owner))
            except Exception:
                logger.exception("Privacy retention purge failed for owner=%s", owner)
        return results


class PrivacyRetentionWorker:
    def __init__(self, service: PrivacyRetentionService, interval_seconds: float = 21600):
        self.service = service
        self.interval_seconds = interval_seconds
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        # Give startup and migration work priority before the first sweep.
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=60)
            return
        except asyncio.TimeoutError:
            pass
        while not self._stop.is_set():
            await self.service.purge_configured_owners()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass


def start_privacy_retention_worker(service: PrivacyRetentionService):
    worker = PrivacyRetentionWorker(service)
    return worker, asyncio.create_task(worker.run(), name="om-privacy-retention-worker")
