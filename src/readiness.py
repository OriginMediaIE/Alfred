"""Secret-free liveness and readiness contracts for the local PrivateOS Core."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _result(
    status: str,
    *,
    required: bool,
    code: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {"status": status, "required": required}
    if code:
        result["code"] = code
    return result


def _database_check() -> dict[str, object]:
    from core.database import engine
    from sqlalchemy import text

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return _result("ok", required=True)
    except Exception:
        return _result("failed", required=True, code="database_unavailable")


def _storage_check() -> dict[str, object]:
    from src.constants import DATA_DIR

    probe: Path | None = None
    try:
        root = Path(DATA_DIR)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".ready-{uuid.uuid4().hex}"
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("ok")
            handle.flush()
            os.fsync(handle.fileno())
        probe.unlink()
        return _result("ok", required=True)
    except Exception:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
        return _result("failed", required=True, code="storage_unavailable")


def _permissions_check() -> dict[str, object]:
    from src.constants import BASE_DIR, DATA_DIR
    from src.runtime_security import audit_private_runtime_paths

    issues = audit_private_runtime_paths(DATA_DIR, Path(BASE_DIR) / ".env")
    if issues:
        return _result("failed", required=True, code="private_permissions_invalid")
    return _result("ok", required=True)


def _auth_store_check(app_state: Any | None) -> dict[str, object]:
    """Fail readiness when the auth store is present but damaged.

    A store that exists yet cannot be parsed leaves the product in a
    recovery-only state (see ``core.auth.AuthManager._load``). Reporting ready
    there would tell an operator or supervisor that a login-capable instance is
    healthy when no owner can authenticate. OM-BUG-003.
    """
    if app_state is None:
        return _result("skipped", required=False)
    manager = getattr(app_state, "auth_manager", None)
    if manager is None:
        return _result("skipped", required=False)
    if bool(getattr(manager, "recovery_required", False)):
        return _result("failed", required=True, code="auth_recovery_required")
    return _result("ok", required=True)


def _task_running(task: Any) -> bool:
    return task is not None and not task.done()


def _lifecycle_checks(app_state: Any | None) -> dict[str, dict[str, object]]:
    if app_state is None:
        return {}
    checks: dict[str, dict[str, object]] = {}
    phase = str(getattr(app_state, "lifecycle_phase", "unknown"))
    checks["lifecycle"] = _result(
        "ok" if phase == "running" else "failed",
        required=True,
        code=None if phase == "running" else "lifecycle_not_running",
    )

    scheduler_enabled = os.getenv("ODYSSEUS_INPROCESS_TASKS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "",
    }
    if scheduler_enabled:
        scheduler = getattr(app_state, "task_scheduler", None)
        scheduler_ok = bool(
            scheduler
            and getattr(scheduler, "_running", False)
            and _task_running(getattr(scheduler, "_task", None))
        )
        checks["scheduler"] = _result(
            "ok" if scheduler_ok else "failed",
            required=True,
            code=None if scheduler_ok else "scheduler_not_running",
        )
    else:
        checks["scheduler"] = _result("disabled", required=False)

    for name, attribute in (
        ("meeting_worker", "meeting_worker_task"),
        ("automation_worker", "automation_worker_task"),
        ("privacy_worker", "privacy_retention_worker_task"),
    ):
        running = _task_running(getattr(app_state, attribute, None))
        checks[name] = _result(
            "ok" if running else "failed",
            required=True,
            code=None if running else f"{name}_not_running",
        )
    return checks


def _optional_service_checks(
    rag_manager: Any,
    memory_vector: Any,
) -> dict[str, dict[str, object]]:
    stores = [store for store in (rag_manager, memory_vector) if store is not None]
    if not stores:
        vector = _result(
            "degraded",
            required=False,
            code="vector_store_unavailable",
        )
    elif all(bool(getattr(store, "healthy", False)) for store in stores):
        vector = _result("ok", required=False)
    else:
        vector = _result("degraded", required=False, code="vector_store_degraded")
    return {"vector_store": vector}


def check_readiness(
    app_state: Any | None = None,
    *,
    rag_manager: Any = None,
    memory_vector: Any = None,
) -> dict[str, object]:
    """Return public readiness without paths, identities, or exception text."""

    from src.constants import APP_VERSION

    checks: dict[str, dict[str, object]] = {
        "database": _database_check(),
        "storage": _storage_check(),
        "permissions": _permissions_check(),
        "auth_store": _auth_store_check(app_state),
        **_lifecycle_checks(app_state),
        **_optional_service_checks(rag_manager, memory_vector),
    }
    required_failed = any(
        check["required"] and check["status"] != "ok" for check in checks.values()
    )
    optional_degraded = any(
        not check["required"] and check["status"] in {"degraded", "failed"}
        for check in checks.values()
    )
    status = "failed" if required_failed else ("degraded" if optional_degraded else "ready")
    return {
        "status": status,
        "live": True,
        "ready": not required_failed,
        "version": APP_VERSION,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["check_readiness"]
