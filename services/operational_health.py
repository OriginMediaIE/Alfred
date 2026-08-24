"""Secret-free, local operational health probes for the admin diagnostics API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.service_health import DEGRADED, DISABLED, DOWN, OK, _svc


def _task_alive(task: Any) -> bool:
    return task is not None and not task.done()


def _application_health() -> dict[str, Any]:
    return _svc("application", OK, "Application process is serving requests.")


def _database_health() -> dict[str, Any]:
    from core.database import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return _svc("database", OK, "Database query succeeded.")
    except Exception:
        return _svc("database", DOWN, "Database query failed.", error="query_failed")


def _scheduler_health(state: Any) -> dict[str, Any]:
    configured = os.getenv("ODYSSEUS_INPROCESS_TASKS", "1").strip().lower() not in {
        "0", "false", "no", "off", "",
    }
    if not configured:
        return _svc("scheduler", DISABLED, "In-process scheduling is disabled.")
    scheduler = getattr(state, "task_scheduler", None)
    if scheduler is None:
        return _svc("scheduler", DISABLED, "Scheduler is not attached to this application process.")
    running = bool(scheduler is not None and getattr(scheduler, "_running", False))
    loop_alive = _task_alive(getattr(scheduler, "_task", None)) if scheduler else False
    if running and loop_alive:
        return _svc("scheduler", OK, "Scheduler loop is running.", concurrency_cap=1)
    return _svc("scheduler", DOWN, "Scheduler loop is not running.")


def _queue_health(state: Any) -> dict[str, Any]:
    depths = {"scheduled": 0, "meetings": 0, "automations": 0}
    failures: list[str] = []
    try:
        from core.database import SessionLocal, TaskRun

        db = SessionLocal()
        try:
            depths["scheduled"] = db.query(TaskRun).filter(
                TaskRun.status.in_(("queued", "running"))
            ).count()
        finally:
            db.close()
    except Exception:
        failures.append("scheduled")
    try:
        from services.meeting_service import get_meeting_service
        from src.meeting_models import MeetingProcessingJob

        service = get_meeting_service()
        db = service.session_factory()
        try:
            depths["meetings"] = db.query(MeetingProcessingJob).filter(
                MeetingProcessingJob.status.in_(("queued", "running"))
            ).count()
        finally:
            db.close()
    except Exception:
        failures.append("meetings")
    try:
        from services.automation_service import get_automation_service
        from src.automation_models import AutomationRun

        service = get_automation_service()
        db = service.sessions()
        try:
            depths["automations"] = db.query(AutomationRun).filter(
                AutomationRun.status.in_(("running", "approval_required", "cancel_requested"))
            ).count()
        finally:
            db.close()
    except Exception:
        failures.append("automations")

    workers = {}
    for name, attribute in (
        ("meeting", "meeting_worker_task"),
        ("automation", "automation_worker_task"),
    ):
        task = getattr(state, attribute, None)
        workers[name] = None if task is None else _task_alive(task)
    total = sum(depths.values())
    if failures:
        attached = any(
            getattr(state, attribute, None) is not None
            for attribute in (
                "task_scheduler", "meeting_worker_task", "automation_worker_task"
            )
        )
        if not attached:
            return _svc(
                "queue", DISABLED,
                "Queue workers are not attached to this application process.",
                depth=total, queues=depths, unavailable=failures, workers=workers,
            )
        return _svc(
            "queue", DEGRADED, "One or more queue depths could not be read.",
            depth=total, queues=depths, unavailable=failures, workers=workers,
        )
    if total and any(value is False for value in workers.values()):
        return _svc(
            "queue", DOWN, "Queued work has no active worker.",
            depth=total, queues=depths, workers=workers,
        )
    return _svc(
        "queue", OK, "Durable queues are readable.",
        depth=total, queues=depths, workers=workers,
    )


def _embedding_health(rag_manager: Any, memory_vector: Any) -> dict[str, Any]:
    stores = [item for item in (rag_manager, memory_vector) if item is not None]
    if not stores:
        return _svc("embedding_provider", DISABLED, "No embedding-backed store is configured.")
    available = sum(bool(getattr(item, "healthy", False)) for item in stores)
    lane_count = sum(len(getattr(item, "_lanes", ()) or ()) for item in stores)
    status = OK if available == len(stores) and lane_count else DEGRADED
    detail = "Embedding lanes are available." if status == OK else "Embedding lanes are partially unavailable."
    return _svc(
        "embedding_provider", status, detail,
        configured_stores=len(stores), healthy_stores=available, lanes=lane_count,
    )


def _google_capability_health(owner: str | None, capability: str) -> dict[str, Any]:
    from services.integration_registry import get_integration_registry
    from services.privacy_service import get_privacy_service

    name = "gmail" if capability == "gmail" else "calendar"
    try:
        row = get_integration_registry().health(
            owner, "google-workspace", get_privacy_service()
        )[0]
    except Exception:
        return _svc(name, DEGRADED, "Google Workspace status could not be read.")
    raw = str(row.get("status") or "degraded")
    status = {
        "connected": OK,
        "disabled": DISABLED,
        "not_configured": DISABLED,
        "disconnected": DEGRADED,
        "expired": DEGRADED,
        "authentication_failed": DOWN,
        "rate_limited": DEGRADED,
        "degraded": DEGRADED,
    }.get(raw, DEGRADED)
    detail = {
        OK: "Google Workspace connection is active.",
        DISABLED: "Google Workspace is not configured or is disabled.",
        DOWN: "Google Workspace authentication failed.",
        DEGRADED: "Google Workspace connection needs attention.",
    }[status]
    return _svc(name, status, detail, accounts=int(row.get("accounts") or 0))


def _transcription_health() -> dict[str, Any]:
    try:
        from services.meeting_service import get_meeting_service

        health = get_meeting_service().provider_status().get("health", {})
        raw = str(health.get("status") or "degraded")
        status = OK if raw in {"available", "ok", "connected"} else (
            DISABLED if raw in {"unavailable", "disabled", "not_configured"} else DEGRADED
        )
        return _svc(
            "transcription", status,
            "Local transcription provider is available."
            if status == OK else "Local transcription provider is unavailable.",
            local_only=bool(health.get("local_only", True)),
        )
    except Exception:
        return _svc("transcription", DEGRADED, "Transcription status could not be read.")


def _file_storage_health() -> dict[str, Any]:
    from src.constants import DATA_DIR

    root = Path(DATA_DIR)
    try:
        root.mkdir(parents=True, exist_ok=True)
        writable = os.access(root, os.R_OK | os.W_OK | os.X_OK)
        if not writable:
            return _svc("file_storage", DOWN, "Application storage is not writable.")
        stat = os.statvfs(root)
        free_bytes = int(stat.f_bavail * stat.f_frsize)
        status = DEGRADED if free_bytes < 256 * 1024 * 1024 else OK
        return _svc(
            "file_storage", status,
            "Application storage is readable and writable."
            if status == OK else "Application storage space is low.",
            free_bytes=free_bytes,
        )
    except Exception:
        return _svc("file_storage", DOWN, "Application storage is unavailable.")


def collect_operational_health(
    state: Any,
    *,
    owner: str | None,
    rag_manager: Any = None,
    memory_vector: Any = None,
) -> list[dict[str, Any]]:
    """Return the specification's local operational health dimensions."""

    return [
        _application_health(),
        _database_health(),
        _scheduler_health(state),
        _queue_health(state),
        _embedding_health(rag_manager, memory_vector),
        _google_capability_health(owner, "gmail"),
        _google_capability_health(owner, "calendar"),
        _transcription_health(),
        _file_storage_health(),
    ]


__all__ = ["collect_operational_health"]
