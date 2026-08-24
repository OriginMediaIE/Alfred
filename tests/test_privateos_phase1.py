import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app_lifecycle import cancel_and_reap_tasks
from src import readiness
from src.runtime_security import audit_private_runtime_paths, secure_runtime_storage


class _TaskState:
    def __init__(self, done=False):
        self._done = done

    def done(self):
        return self._done


def _running_state():
    scheduler = SimpleNamespace(_running=True, _task=_TaskState())
    return SimpleNamespace(
        lifecycle_phase="running",
        task_scheduler=scheduler,
        meeting_worker_task=_TaskState(),
        automation_worker_task=_TaskState(),
        privacy_retention_worker_task=_TaskState(),
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not available")
def test_runtime_storage_is_owner_only(tmp_path):
    data = tmp_path / "data"
    data.mkdir(mode=0o755)
    database = data / "app.db"
    database.write_bytes(b"sqlite")
    database.chmod(0o644)
    env = tmp_path / ".env"
    env.write_text("TOKEN=private\n", encoding="utf-8")
    env.chmod(0o644)

    secure_runtime_storage(data, env)

    assert data.stat().st_mode & 0o777 == 0o700
    assert database.stat().st_mode & 0o777 == 0o600
    assert env.stat().st_mode & 0o777 == 0o600
    assert audit_private_runtime_paths(data, env) == []


def test_readiness_distinguishes_ready_degraded_and_failed(monkeypatch):
    monkeypatch.setattr(readiness, "_database_check", lambda: readiness._result("ok", required=True))
    monkeypatch.setattr(readiness, "_storage_check", lambda: readiness._result("ok", required=True))
    monkeypatch.setattr(readiness, "_permissions_check", lambda: readiness._result("ok", required=True))
    monkeypatch.setenv("ODYSSEUS_INPROCESS_TASKS", "1")

    healthy_store = SimpleNamespace(healthy=True)
    ready = readiness.check_readiness(
        _running_state(), rag_manager=healthy_store, memory_vector=healthy_store
    )
    assert ready["status"] == "ready"
    assert ready["ready"] is True

    degraded = readiness.check_readiness(_running_state())
    assert degraded["status"] == "degraded"
    assert degraded["ready"] is True

    failed_state = _running_state()
    failed_state.automation_worker_task = _TaskState(done=True)
    failed = readiness.check_readiness(failed_state, rag_manager=healthy_store)
    assert failed["status"] == "failed"
    assert failed["ready"] is False
    assert failed["checks"]["automation_worker"]["code"] == "automation_worker_not_running"
    assert "path" not in str(failed).lower()
    assert "exception" not in str(failed).lower()


@pytest.mark.asyncio
async def test_cancel_and_reap_waits_for_background_tasks():
    stopped = asyncio.Event()

    async def worker():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    task = asyncio.create_task(worker())
    await asyncio.sleep(0)

    assert await cancel_and_reap_tasks([task]) == 1
    assert task.done()
    assert stopped.is_set()
