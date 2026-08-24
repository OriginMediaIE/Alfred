"""Lifecycle-managed worker for durable local meeting jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from services.meeting_service import MeetingConflict, MeetingService, get_meeting_service


logger = logging.getLogger(__name__)


class MeetingWorker:
    def __init__(
        self,
        service: Optional[MeetingService] = None,
        *,
        poll_seconds: float = 0.5,
    ) -> None:
        if not 0.05 <= float(poll_seconds) <= 60:
            raise ValueError("poll_seconds must be between 0.05 and 60")
        self.service = service or get_meeting_service()
        self.poll_seconds = float(poll_seconds)
        self._stop = asyncio.Event()
        self._active: Optional[tuple[str, str]] = None

    def stop(self) -> None:
        self._stop.set()
        if self._active is not None:
            owner, job_id = self._active
            try:
                self.service.cancel_job(owner, job_id)
            except Exception:
                logger.warning("Could not request cancellation for meeting job %s", job_id)

    async def run(self) -> None:
        recovered = await asyncio.to_thread(self.service.recover_interrupted_jobs)
        if recovered:
            logger.info("Recovered %s interrupted meeting job(s)", recovered)
        while not self._stop.is_set():
            queued = await asyncio.to_thread(self.service.next_queued_job)
            if queued is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                except asyncio.TimeoutError:
                    pass
                continue
            owner, job_id = queued
            self._active = (owner, job_id)
            try:
                await asyncio.to_thread(self.service.run_job, owner, job_id)
            except MeetingConflict:
                # Another worker claimed the same durable row between selection
                # and transition. The authoritative status remains in storage.
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Meeting worker failed while dispatching job %s", job_id)
            finally:
                self._active = None


def start_meeting_worker(
    service: Optional[MeetingService] = None,
    *,
    poll_seconds: float = 0.5,
) -> tuple[MeetingWorker, asyncio.Task]:
    worker = MeetingWorker(service, poll_seconds=poll_seconds)
    return worker, asyncio.create_task(worker.run(), name="meeting-worker")


__all__ = ["MeetingWorker", "start_meeting_worker"]
