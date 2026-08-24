"""Canonical tool handlers for Phase Ten personal-work records.

The handlers are deliberately split by risk: ``query_work`` is read-only,
``manage_work`` creates or updates local reversible records, and
``delete_work`` performs destructive removal.  Mutation handlers fail closed
unless the executor supplies the currently claimed action-ledger ID.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.tools._common import _configured_auth_requires_owner, _parse_tool_args
from src.work_tool_contract import (
    DELETE_WORK_ACTIONS,
    DELETE_WORK_TOOL_SCHEMA,
    MANAGE_WORK_ACTIONS,
    MANAGE_WORK_TOOL_SCHEMA,
    QUERY_WORK_ACTIONS,
    QUERY_WORK_TOOL_SCHEMA,
    WORK_TOOL_SCHEMAS,
)
from src.work_service import (
    MutationContext,
    WorkError,
    WorkNotFound,
    get_work_service,
)


def _args(content: str) -> dict[str, Any]:
    try:
        parsed = _parse_tool_args(content)
    except ValueError as exc:
        raise ValueError("Invalid JSON arguments") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be an object")
    return parsed


def _error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, WorkError):
        return {
            "error": str(exc),
            "code": exc.code,
            "exit_code": 1,
        }
    return {"error": str(exc), "code": "invalid_arguments", "exit_code": 1}


def _payload(args: dict[str, Any]) -> dict[str, Any]:
    payload = dict(args.get("record") or {})
    if not isinstance(payload, dict):
        raise ValueError("record must be an object")
    # Top-level fields remain accepted for concise model calls; explicit
    # `record` values win and executor-only fields never enter persistence.
    for key, value in args.items():
        if key not in {
            "action",
            "record",
            "task_id",
            "project_id",
            "commitment_id",
            "plan_id",
            "revision",
            "limit",
        }:
            payload.setdefault(key, value)
    source = payload.pop("source", None)
    if source is not None:
        if not isinstance(source, dict):
            raise ValueError("source must be an object")
        payload.update(
            {
                "source_type": source.get("type"),
                "source_id": source.get("id"),
                "source_url": source.get("url"),
                "source_excerpt": source.get("excerpt"),
                "source_occurred_at": source.get("occurred_at"),
            }
        )
    return payload


def _read_back_verification(
    record_id: str,
    expected: dict[str, Any],
    reader,
) -> dict[str, Any]:
    try:
        observed = reader()
        matches = observed == expected
        reason = None if matches else "Stored work record differs from the mutation result."
    except Exception as exc:
        matches = False
        reason = f"Could not read the work record back: {type(exc).__name__}"
    result = {
        "status": "verified" if matches else "mismatch",
        "provider": "local_work",
        "read_back_id": record_id,
    }
    if reason:
        result["reason"] = reason
    return result


def _delete_verification(record_id: str, reader) -> dict[str, Any]:
    try:
        reader()
    except WorkNotFound:
        return {
            "status": "verified",
            "provider": "local_work",
            "read_back_id": record_id,
            "read_back": "not_found",
        }
    except Exception as exc:
        return {
            "status": "mismatch",
            "provider": "local_work",
            "read_back_id": record_id,
            "reason": f"Could not verify deletion: {type(exc).__name__}",
        }
    return {
        "status": "mismatch",
        "provider": "local_work",
        "read_back_id": record_id,
        "read_back": "still_present",
    }


async def do_query_work(content: str, owner: Optional[str] = None) -> Dict[str, Any]:
    if _configured_auth_requires_owner(owner):
        return {"error": "Authenticated owner is required", "code": "owner_required", "exit_code": 1}
    try:
        args = _args(content)
        action = str(args.get("action") or "list_tasks").strip().lower()
        if action not in QUERY_WORK_ACTIONS:
            return {
                "error": f"Unknown read action: {action}",
                "allowed_actions": sorted(QUERY_WORK_ACTIONS),
                "exit_code": 1,
            }
        service = get_work_service()
        if action == "list_tasks":
            result = {"tasks": service.list_tasks(
                owner,
                status=args.get("status"),
                project_id=args.get("project_id"),
                parent_task_id=args.get("parent_task_id"),
                tag=args.get("tag"),
                context=args.get("context"),
                due_before=args.get("due_before"),
                include_completed=bool(args.get("include_completed", False)),
                query=args.get("query"),
                limit=args.get("limit", 200),
            )}
        elif action == "get_task":
            result = {"task": service.get_task(owner, str(args.get("task_id") or ""))}
        elif action == "list_projects":
            result = {"projects": service.list_projects(
                owner,
                status=args.get("status"),
                include_archived=bool(args.get("include_archived", False)),
                limit=args.get("limit", 200),
            )}
        elif action == "get_project":
            result = {"project": service.get_project(owner, str(args.get("project_id") or ""))}
        elif action == "list_commitments":
            result = {"commitments": service.list_commitments(
                owner,
                status=args.get("status"),
                review_state=args.get("review_state"),
                due_before=args.get("due_before"),
                limit=args.get("limit", 200),
            )}
        elif action == "get_commitment":
            result = {"commitment": service.get_commitment(
                owner, str(args.get("commitment_id") or "")
            )}
        elif action == "daily_focus":
            result = service.daily_focus(
                owner,
                plan_date=args.get("plan_date"),
                available_minutes=args.get("available_minutes", 480),
                energy=args.get("energy"),
                contexts=args.get("contexts"),
            )
        elif action == "blocked_tasks":
            result = {"tasks": service.blocked_tasks(owner)}
        elif action == "overdue_commitments":
            result = {"commitments": service.overdue_commitments(owner, as_of=args.get("as_of"))}
        elif action == "get_plan":
            result = {"plan": service.get_plan(owner, str(args.get("plan_id") or ""))}
        elif action == "due_reminders":
            result = {"reminders": service.pending_reminders(
                owner,
                due_before=args.get("due_before"),
                limit=args.get("limit", 200),
            )}
        else:
            result = {"receipts": service.list_receipts(
                owner,
                entity_type=args.get("entity_type"),
                entity_id=args.get("entity_id"),
                limit=args.get("limit", 200),
            )}
        return {**result, "exit_code": 0}
    except Exception as exc:
        return _error(exc)


async def do_manage_work(
    content: str,
    owner: Optional[str] = None,
    *,
    approval_action_id: Optional[str] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    if _configured_auth_requires_owner(owner):
        return {"error": "Authenticated owner is required", "code": "owner_required", "exit_code": 1}
    try:
        args = _args(content)
        action = str(args.get("action") or "").strip().lower()
        if action not in MANAGE_WORK_ACTIONS:
            return {
                "error": f"Unknown mutation action: {action}",
                "allowed_actions": sorted(MANAGE_WORK_ACTIONS),
                "exit_code": 1,
            }
        service = get_work_service()
        revision = args.get("revision")
        context = MutationContext.agent(
            owner,
            action_id=approval_action_id,
            correlation_id=request_id,
        )
        record = _payload(args)
        revision = args.get("revision")
        if action == "create_task":
            result = {"task": service.create_task(owner, record, context=context)}
        elif action == "update_task":
            result = {"task": service.update_task(
                owner,
                str(args.get("task_id") or ""),
                record,
                context=context,
                expected_revision=revision,
            )}
        elif action == "create_project":
            result = {"project": service.create_project(owner, record, context=context)}
        elif action == "update_project":
            result = {"project": service.update_project(
                owner,
                str(args.get("project_id") or ""),
                record,
                context=context,
                expected_revision=revision,
            )}
        elif action == "create_commitment":
            result = {"commitment": service.create_commitment(owner, record, context=context)}
        elif action == "update_commitment":
            result = {"commitment": service.update_commitment(
                owner,
                str(args.get("commitment_id") or ""),
                record,
                context=context,
                expected_revision=revision,
            )}
        elif action == "create_plan":
            result = {"plan": service.create_plan(owner, record, context=context)}
        elif action == "update_plan":
            if revision is None:
                raise ValueError("revision is required for update_plan")
            result = {"plan": service.update_plan(
                owner,
                str(args.get("plan_id") or ""),
                record,
                context=context,
                expected_revision=int(revision),
            )}
        else:
            if revision is None:
                raise ValueError("revision is required for apply_plan")
            result = service.apply_plan(
                owner,
                str(args.get("plan_id") or ""),
                context=context,
                expected_revision=int(revision),
            )
        if "task" in result:
            expected = result["task"]
            verification = _read_back_verification(
                expected["id"], expected, lambda: service.get_task(owner, expected["id"])
            )
        elif "project" in result:
            expected = result["project"]
            verification = _read_back_verification(
                expected["id"], expected, lambda: service.get_project(owner, expected["id"])
            )
        elif "commitment" in result:
            expected = result["commitment"]
            verification = _read_back_verification(
                expected["id"],
                expected,
                lambda: service.get_commitment(owner, expected["id"]),
            )
        else:
            expected = result["plan"]
            verification = _read_back_verification(
                expected["id"], expected, lambda: service.get_plan(owner, expected["id"])
            )
        return {**result, "verification": verification, "exit_code": 0}
    except Exception as exc:
        return _error(exc)


async def do_delete_work(
    content: str,
    owner: Optional[str] = None,
    *,
    approval_action_id: Optional[str] = None,
    request_id: str = "",
) -> Dict[str, Any]:
    if _configured_auth_requires_owner(owner):
        return {"error": "Authenticated owner is required", "code": "owner_required", "exit_code": 1}
    try:
        args = _args(content)
        action = str(args.get("action") or "").strip().lower()
        if action not in DELETE_WORK_ACTIONS:
            return {
                "error": f"Unknown delete action: {action}",
                "allowed_actions": sorted(DELETE_WORK_ACTIONS),
                "exit_code": 1,
            }
        service = get_work_service()
        revision = args.get("revision")
        if revision is None:
            raise ValueError("revision is required for delete actions")
        context = MutationContext.agent(
            owner,
            action_id=approval_action_id,
            correlation_id=request_id,
        )
        if action == "delete_task":
            record_id = str(args.get("task_id") or "")
            result = service.delete_task(
                owner,
                record_id,
                context=context,
                expected_revision=int(revision),
            )
            verification = _delete_verification(
                record_id, lambda: service.get_task(owner, record_id)
            )
        elif action == "delete_project":
            record_id = str(args.get("project_id") or "")
            result = service.delete_project(
                owner,
                record_id,
                context=context,
                expected_revision=int(revision),
            )
            verification = _delete_verification(
                record_id, lambda: service.get_project(owner, record_id)
            )
        else:
            record_id = str(args.get("commitment_id") or "")
            result = service.delete_commitment(
                owner,
                record_id,
                context=context,
                expected_revision=int(revision),
            )
            verification = _delete_verification(
                record_id, lambda: service.get_commitment(owner, record_id)
            )
        return {**result, "verification": verification, "exit_code": 0}
    except Exception as exc:
        return _error(exc)


__all__ = [
    "DELETE_WORK_ACTIONS",
    "DELETE_WORK_TOOL_SCHEMA",
    "MANAGE_WORK_ACTIONS",
    "MANAGE_WORK_TOOL_SCHEMA",
    "QUERY_WORK_ACTIONS",
    "QUERY_WORK_TOOL_SCHEMA",
    "WORK_TOOL_SCHEMAS",
    "do_delete_work",
    "do_manage_work",
    "do_query_work",
]
