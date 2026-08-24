"""Approval Centre and immutable agent-action audit APIs."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from src.action_ledger import (
    ActionLedgerError,
    ApprovalGrant,
    get_action_ledger,
)
from src.action_verification import verification_status_from_result
from src.auth_helpers import require_user
from src.tool_authorization import ExecutionOrigin, authority_for_owner
from src.tool_execution import execute_tool_block
from src.tool_registry import ToolSurface, VerificationMode, build_builtin_registry


logger = logging.getLogger(__name__)


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditActionBody(_StrictBody):
    arguments: dict[str, Any]
    revision: int = Field(ge=1)


class ApproveActionBody(_StrictBody):
    revision: int = Field(ge=1)
    arguments_hash: str = Field(min_length=64, max_length=64)
    always_allow: bool = False


class RejectActionBody(_StrictBody):
    revision: int = Field(ge=1)
    reason: str = Field(default="", max_length=2000)


class CancelActionBody(_StrictBody):
    revision: int = Field(ge=1)
    reason: str = Field(default="", max_length=2000)


_active_approval_tasks: dict[str, asyncio.Task[Any]] = {}


def _raise_ledger_error(exc: ActionLedgerError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _verification_status(
    tool_name: str,
    result: Mapping[str, Any],
) -> str:
    """Return only verification states supported by evidence we actually have."""

    executor_status = verification_status_from_result(result)
    if executor_status:
        return executor_status

    try:
        definition = build_builtin_registry().resolve(tool_name)
    except KeyError:
        return "indeterminate"
    failed = bool(result.get("error")) or result.get("exit_code") not in (None, 0)
    if failed:
        return "failed"
    if definition.verification is VerificationMode.RESULT_SCHEMA:
        return "schema_verified" if isinstance(result, Mapping) else "failed"
    if definition.verification is VerificationMode.PROCESS_EXIT:
        return "process_exit_verified" if result.get("exit_code") == 0 else "failed"
    # READ_BACK requires a provider/file-specific verifier. Never turn a
    # successful handler return into a false verified claim.
    if definition.verification is VerificationMode.READ_BACK:
        return "read_back_pending"
    return "indeterminate"


def setup_action_routes() -> APIRouter:
    router = APIRouter(prefix="/api/approvals", tags=["approvals"])

    @router.get("")
    async def list_actions(
        status: str = Query("pending"),
        limit: int = Query(100, ge=1, le=250),
        owner: str = Depends(require_user),
    ):
        try:
            actions = get_action_ledger().list_actions(owner, status=status, limit=limit)
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)
        return {"actions": actions, "status": status}

    @router.get("/audit")
    async def list_audit_events(
        action_id: str | None = Query(None),
        limit: int = Query(250, ge=1, le=500),
        owner: str = Depends(require_user),
    ):
        ledger = get_action_ledger()
        try:
            events = ledger.list_audit_events(owner, action_id=action_id, limit=limit)
            chain_valid = (
                ledger.verify_audit_chain(action_id, owner) if action_id else None
            )
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)
        return {"events": events, "chain_valid": chain_valid}

    @router.get("/rules")
    async def list_approval_rules(owner: str = Depends(require_user)):
        return {"rules": get_action_ledger().list_rules(owner)}

    @router.delete("/rules/{rule_id}")
    async def revoke_approval_rule(
        rule_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            rule = get_action_ledger().revoke_rule(rule_id, owner)
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)
        return {"rule": rule}

    @router.get("/{action_id}")
    async def get_action(
        action_id: str,
        owner: str = Depends(require_user),
    ):
        ledger = get_action_ledger()
        try:
            action = ledger.get_action(action_id, owner)
            events = ledger.list_audit_events(owner, action_id=action_id)
            chain_valid = ledger.verify_audit_chain(action_id, owner)
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)
        return {"action": action, "events": events, "chain_valid": chain_valid}

    @router.patch("/{action_id}")
    async def edit_action(
        action_id: str,
        body: EditActionBody,
        owner: str = Depends(require_user),
    ):
        try:
            action = get_action_ledger().edit_arguments(
                action_id,
                owner,
                body.arguments,
                expected_revision=body.revision,
                actor=owner,
            )
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)
        return {"action": action}

    @router.post("/{action_id}/reject")
    async def reject_action(
        action_id: str,
        body: RejectActionBody,
        owner: str = Depends(require_user),
    ):
        ledger = get_action_ledger()
        try:
            pending = ledger.get_action(action_id, owner)
            action = ledger.reject(
                action_id,
                owner,
                expected_revision=body.revision,
                reason=body.reason,
                actor=owner,
            )
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)
        if pending.get("tool_name") == "manage_automation" and pending.get("arguments", {}).get("action") == "approve_step":
            try:
                from services.automation_service import get_automation_service
                args = pending["arguments"]
                get_automation_service().reject_step(owner, args.get("automation_id"), args.get("run_id"), args.get("step_index"), body.reason)
            except Exception:
                logger.exception("Could not reconcile rejected automation approval %s", action_id)
        return {"action": action}

    @router.post("/{action_id}/cancel")
    async def cancel_action(
        action_id: str,
        body: CancelActionBody,
        owner: str = Depends(require_user),
    ):
        try:
            action = get_action_ledger().cancel(
                action_id,
                owner,
                expected_revision=body.revision,
                reason=body.reason,
                actor=owner,
            )
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)

        active_task = _active_approval_tasks.get(action_id)
        cancellation_signalled = bool(active_task and not active_task.done())
        if cancellation_signalled and active_task is not asyncio.current_task():
            active_task.cancel()
        return {
            "action": action,
            "cancellation_signalled": cancellation_signalled,
        }

    @router.post("/{action_id}/approve")
    async def approve_action(
        action_id: str,
        body: ApproveActionBody,
        request: Request,
        owner: str = Depends(require_user),
    ):
        ledger = get_action_ledger()
        try:
            # Fetch before the claim so exact canonical arguments/context are
            # available after status atomically moves to executing.
            action = ledger.get_action(action_id, owner)
            grant = ledger.claim_approval(
                action_id,
                owner,
                expected_revision=body.revision,
                expected_hash=body.arguments_hash,
                actor=owner,
                always_allow=body.always_allow,
            )
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)

        try:
            current_task = asyncio.current_task()
            if current_task is not None:
                _active_approval_tasks[action_id] = current_task
            surface = ToolSurface(action["surface"])
            authority = authority_for_owner(
                owner or None,
                surface=surface,
                auth_manager=getattr(request.app.state, "auth_manager", None),
                # The approving human is the audit actor. Execution retains
                # the proposal's origin so the exact grant can bind to it.
                origin=ExecutionOrigin(action["origin"]),
            )
            description, result = await execute_tool_block(
                SimpleNamespace(
                    tool_type=action["tool_name"],
                    content=json.dumps(
                        action["arguments"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                ),
                session_id=action.get("session_id"),
                owner=owner or None,
                request_id=action.get("request_id") or "",
                workspace=(action.get("execution_context") or {}).get("workspace"),
                authority=authority,
                approval_grant=grant,
            )
            completed = ledger.finish_execution(
                grant,
                result,
                verification_status=_verification_status(action["tool_name"], result),
            )
            return {
                "action": completed,
                "description": description,
                "result": result,
            }
        except ActionLedgerError as exc:
            _raise_ledger_error(exc)
        except Exception as exc:
            logger.exception("Approved action %s failed during execution", action_id)
            try:
                ledger.fail_claimed_execution(grant, str(exc))
            except Exception:
                logger.exception("Could not persist approved action failure %s", action_id)
            raise HTTPException(500, "Approved action execution failed.") from exc
        finally:
            current_task = asyncio.current_task()
            if _active_approval_tasks.get(action_id) is current_task:
                _active_approval_tasks.pop(action_id, None)

    return router
