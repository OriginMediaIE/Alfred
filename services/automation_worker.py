"""Lifecycle-owned polling worker for due structured automations."""

import asyncio, logging
from services.automation_service import AutomationService, get_automation_service
logger=logging.getLogger(__name__)


class AutomationWorker:
    def __init__(self, service: AutomationService, poll_seconds: float = 15): self.service=service;self.poll_seconds=poll_seconds;self._stop=asyncio.Event()
    def stop(self): self._stop.set()
    async def run(self):
        while not self._stop.is_set():
            try: await self.service.run_due()
            except asyncio.CancelledError: raise
            except Exception: logger.exception("Structured automation worker iteration failed")
            try: await asyncio.wait_for(self._stop.wait(),timeout=self.poll_seconds)
            except asyncio.TimeoutError: pass


def start_automation_worker(service=None):
    worker=AutomationWorker(service or get_automation_service());return worker,asyncio.create_task(worker.run(),name="om-automation-worker")
