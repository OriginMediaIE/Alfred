"""Durable approvals and tamper-evident audit events for agent actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import logging
import secrets
import threading
import uuid
from typing import Any, Callable, Mapping, Optional

from sqlalchemy.exc import IntegrityError

from core.database import (
    AgentAction,
    AgentActionAuditEvent,
    AgentApprovalRule,
    SessionLocal,
)
from src.tool_actions import ActionArgumentError, ActionEnvelope, build_action_envelope
from src.tool_authorization import ExecutionOrigin, ResolvedToolIdentity
from src.tool_registry import RiskLevel, ToolSurface, build_builtin_registry


logger = logging.getLogger(__name__)


class ActionStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_ACTION_STATUSES = frozenset(
    {
        ActionStatus.SUCCEEDED.value,
        ActionStatus.FAILED.value,
        ActionStatus.REJECTED.value,
        ActionStatus.EXPIRED.value,
        ActionStatus.CANCELLED.value,
    }
)


class ActionLedgerError(RuntimeError):
    code = "action_ledger_error"
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ActionNotFound(ActionLedgerError):
    code = "action_not_found"
    status_code = 404


class ActionConflict(ActionLedgerError):
    code = "action_conflict"
    status_code = 409


class ActionExpired(ActionConflict):
    code = "action_expired"


class ActionValidationError(ActionLedgerError):
    code = "invalid_arguments"
    status_code = 422


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "master_password",
        "oauth_access_token",
        "oauth_refresh_token",
        "password",
        "secret",
        "token",
    }
)


def _redact_for_audit(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in _SENSITIVE_KEYS):
        digest = hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]
        return f"[REDACTED sha256:{digest}]"
    if isinstance(value, Mapping):
        return {
            str(child_key): _redact_for_audit(child, key=str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_for_audit(child, key=key) for child in value]
    return value


def _result_for_storage(result: Mapping[str, Any]) -> dict[str, Any]:
    """Bound and redact durable result data without altering the live result."""

    redacted = _redact_for_audit(dict(result))
    encoded = _canonical_json(redacted)
    if len(encoded) > 64_000:
        return {
            "truncated": True,
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "preview": encoded[:16_000],
        }
    return redacted


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """One-time trusted evidence returned only after atomic ledger claim."""

    approval_id: str
    owner: Optional[str]
    tool_name: str
    tool_version: int
    arguments_hash: str
    revision: int
    surface: ToolSurface
    origin: ExecutionOrigin
    expires_at: datetime
    correlation_id: str
    nonce: str
    request_id: str
    session_id: Optional[str]
    rule_id: Optional[str] = None

    def matches(
        self,
        action: ActionEnvelope,
        *,
        now: Optional[datetime] = None,
    ) -> bool:
        now = now or _utcnow()
        return (
            str(self.owner or "") == str(action.owner or "")
            and self.tool_name == action.tool_name
            and self.tool_version == action.tool_version
            and self.arguments_hash == action.arguments_hash
            and self.surface is action.surface
            and self.origin is action.origin
            and self.request_id == action.request_id
            and self.session_id == action.session_id
            and now < self.expires_at
        )


class ActionLedger:
    """Transactional owner-scoped action ledger.

    A process lock closes SQLite's read/update race.  Database uniqueness on
    idempotency keys and audit sequence remains the cross-process backstop.
    """

    def __init__(
        self,
        *,
        session_factory: Callable = SessionLocal,
        clock: Callable[[], datetime] = _utcnow,
        approval_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._approval_ttl = approval_ttl
        self._lock = threading.RLock()

    @staticmethod
    def _owner_value(owner: Optional[str]) -> str:
        return str(owner or "")

    @staticmethod
    def _rule_scope_for_action(action: ActionEnvelope) -> dict[str, str]:
        """Return the complete narrow scope represented by a standing rule."""

        return {
            "arguments_hash": action.arguments_hash,
            "mode": "exact_arguments",
            "origin": action.origin.value,
            "surface": action.surface.value,
        }

    @classmethod
    def _rule_matches_action(
        cls,
        rule: AgentApprovalRule,
        action: ActionEnvelope,
    ) -> bool:
        try:
            scope = json.loads(rule.scope_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return False
        return isinstance(scope, dict) and scope == cls._rule_scope_for_action(action)

    def _idempotency_key(
        self,
        action: ActionEnvelope,
        execution_context: Mapping[str, Any],
    ) -> str:
        # Calls without an ingress request id are not safely deduplicatable;
        # retain uniqueness rather than conflating two intentional actions.
        nonce = action.request_id or uuid.uuid4().hex
        payload = {
            "arguments_hash": action.arguments_hash,
            "execution_context": dict(execution_context),
            "owner": self._owner_value(action.owner),
            "origin": action.origin.value,
            "request_id": nonce,
            "session_id": action.session_id or "",
            "surface": action.surface.value,
            "tool": action.tool_name,
            "version": action.tool_version,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def _append_audit(
        self,
        db,
        action: AgentAction,
        event_type: str,
        *,
        actor: str,
        payload: Mapping[str, Any],
    ) -> AgentActionAuditEvent:
        previous = (
            db.query(AgentActionAuditEvent)
            .filter(AgentActionAuditEvent.action_id == action.id)
            .order_by(AgentActionAuditEvent.sequence.desc())
            .first()
        )
        sequence = (previous.sequence + 1) if previous else 1
        previous_hash = previous.event_hash if previous else ""
        occurred_at = self._clock()
        safe_payload = _redact_for_audit(dict(payload))
        payload_json = _canonical_json(safe_payload)
        hash_body = {
            "action_id": action.id,
            "actor": actor,
            "correlation_id": action.correlation_id,
            "event_type": event_type,
            "occurred_at": _iso(occurred_at),
            "owner": action.owner,
            "payload": safe_payload,
            "previous_hash": previous_hash,
            "sequence": sequence,
        }
        event_hash = hashlib.sha256(
            _canonical_json(hash_body).encode("utf-8")
        ).hexdigest()
        event = AgentActionAuditEvent(
            id=uuid.uuid4().hex,
            action_id=action.id,
            owner=action.owner,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            occurred_at=occurred_at,
            correlation_id=action.correlation_id,
            payload_json=payload_json,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        db.add(event)
        db.flush()
        return event

    def propose(
        self,
        action: ActionEnvelope,
        *,
        risk_level: int,
        approval_reason: str,
        origin: Optional[str] = None,
        execution_context: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Persist or retrieve one idempotent pending proposal."""

        context = dict(execution_context or {})
        # Only trusted executor metadata belongs here. Keep the durable shape
        # deliberately narrow so callers cannot smuggle arbitrary secrets.
        context = {
            key: value
            for key, value in context.items()
            if key in {"workspace"} and (value is None or isinstance(value, str))
        }
        key = self._idempotency_key(action, context)
        owner = self._owner_value(action.owner)
        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                existing = (
                    db.query(AgentAction)
                    .filter(AgentAction.idempotency_key == key)
                    .first()
                )
                if existing is not None:
                    return self._action_dict(existing, now=now)

                row = AgentAction(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    session_id=action.session_id,
                    request_id=action.request_id or "",
                    correlation_id=action.request_id or uuid.uuid4().hex,
                    requested_tool=action.requested_name,
                    tool_name=action.tool_name,
                    tool_version=action.tool_version,
                    surface=action.surface.value,
                    origin=str(origin or action.origin.value)[:64],
                    arguments_json=action.canonical_arguments,
                    arguments_hash=action.arguments_hash,
                    execution_context_json=_canonical_json(context),
                    idempotency_key=key,
                    risk_level=int(risk_level),
                    approval_reason=str(approval_reason or "")[:2000],
                    status=ActionStatus.PENDING.value,
                    expires_at=now + self._approval_ttl,
                    revision=1,
                )
                db.add(row)
                db.flush()
                self._append_audit(
                    db,
                    row,
                    "proposed",
                    actor="agent",
                    payload={
                        "arguments": action.arguments_dict(),
                        "arguments_hash": action.arguments_hash,
                        "execution_context": context,
                        "risk_level": int(risk_level),
                        "tool": action.tool_name,
                        "tool_version": action.tool_version,
                    },
                )
                db.commit()
                db.refresh(row)
                return self._action_dict(row, now=now)
            except IntegrityError:
                db.rollback()
                existing = (
                    db.query(AgentAction)
                    .filter(AgentAction.idempotency_key == key)
                    .first()
                )
                if existing is None:
                    raise
                return self._action_dict(existing, now=now)
            finally:
                db.close()

    def _owned_row(self, db, action_id: str, owner: Optional[str]) -> AgentAction:
        row = (
            db.query(AgentAction)
            .filter(
                AgentAction.id == action_id,
                AgentAction.owner == self._owner_value(owner),
            )
            .first()
        )
        if row is None:
            raise ActionNotFound("Action not found.")
        return row

    def _effective_status(self, row: AgentAction, *, now: datetime) -> str:
        if row.status == ActionStatus.PENDING.value and row.expires_at <= now:
            return ActionStatus.EXPIRED.value
        return row.status

    def _action_dict(self, row: AgentAction, *, now: Optional[datetime] = None) -> dict[str, Any]:
        now = now or self._clock()
        try:
            arguments = json.loads(row.arguments_json or "{}")
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        try:
            result = json.loads(row.result_json) if row.result_json else None
        except (json.JSONDecodeError, TypeError):
            result = None
        try:
            execution_context = json.loads(row.execution_context_json or "{}")
        except (json.JSONDecodeError, TypeError):
            execution_context = {}
        return {
            "id": row.id,
            "owner": row.owner,
            "session_id": row.session_id,
            "request_id": row.request_id,
            "correlation_id": row.correlation_id,
            "requested_tool": row.requested_tool,
            "tool_name": row.tool_name,
            "tool_version": row.tool_version,
            "surface": row.surface,
            "origin": row.origin,
            "arguments": arguments,
            "arguments_hash": row.arguments_hash,
            "execution_context": execution_context,
            "risk_level": row.risk_level,
            "approval_reason": row.approval_reason,
            "status": self._effective_status(row, now=now),
            "stored_status": row.status,
            "expires_at": _iso(row.expires_at),
            "revision": row.revision,
            "approved_at": _iso(row.approved_at),
            "approved_by": row.approved_by,
            "approval_consumed_at": _iso(row.approval_consumed_at),
            "rejected_at": _iso(row.rejected_at),
            "rejected_by": row.rejected_by,
            "decision_reason": row.decision_reason,
            "execution_started_at": _iso(row.execution_started_at),
            "execution_finished_at": _iso(row.execution_finished_at),
            "result": result,
            "error": row.error,
            "verification_status": row.verification_status,
            "reversal_status": row.reversal_status,
            "approval_rule_id": row.approval_rule_id,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def list_actions(
        self,
        owner: Optional[str],
        *,
        status: str = "pending",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        now = self._clock()
        limit = max(1, min(int(limit), 250))
        db = self._session_factory()
        try:
            query = db.query(AgentAction).filter(
                AgentAction.owner == self._owner_value(owner)
            )
            if status == "pending":
                query = query.filter(
                    AgentAction.status == ActionStatus.PENDING.value,
                    AgentAction.expires_at > now,
                )
            elif status == "history":
                query = query.filter(
                    (AgentAction.status != ActionStatus.PENDING.value)
                    | (AgentAction.expires_at <= now)
                )
            elif status in {item.value for item in ActionStatus}:
                query = query.filter(AgentAction.status == status)
            else:
                raise ActionValidationError("Unknown action status filter.")
            rows = query.order_by(AgentAction.created_at.desc()).limit(limit).all()
            return [self._action_dict(row, now=now) for row in rows]
        finally:
            db.close()

    def operating_metrics(
        self,
        owner: Optional[str],
        *,
        since: datetime,
    ) -> dict[str, Any]:
        """Summarize proposal decisions without exposing action payloads."""

        db = self._session_factory()
        try:
            rows = db.query(AgentAction).filter(
                AgentAction.owner == self._owner_value(owner),
                AgentAction.created_at >= since,
            ).all()
            proposed = len(rows)
            accepted = sum(row.approved_at is not None for row in rows)
            rejected = sum(row.status == ActionStatus.REJECTED.value for row in rows)
            pending = sum(row.status == ActionStatus.PENDING.value for row in rows)
            succeeded = sum(row.status == ActionStatus.SUCCEEDED.value for row in rows)
            verified = sum(
                row.status == ActionStatus.SUCCEEDED.value
                and str(row.verification_status or "")
                not in {"", "indeterminate", "read_back_pending"}
                for row in rows
            )
            decided = accepted + rejected
            return {
                "proposed": proposed,
                "accepted": accepted,
                "rejected": rejected,
                "pending": pending,
                "succeeded": succeeded,
                "verified": verified,
                "proposal_acceptance_rate": (
                    round(accepted / decided, 4) if decided else None
                ),
            }
        finally:
            db.close()

    def get_action(self, action_id: str, owner: Optional[str]) -> dict[str, Any]:
        db = self._session_factory()
        try:
            return self._action_dict(self._owned_row(db, action_id, owner))
        finally:
            db.close()

    def edit_arguments(
        self,
        action_id: str,
        owner: Optional[str],
        arguments: Mapping[str, Any],
        *,
        expected_revision: int,
        actor: Optional[str] = None,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                row = self._owned_row(db, action_id, owner)
                self._assert_pending_current(row, now=now, expected_revision=expected_revision)
                registry = build_builtin_registry()
                try:
                    surface = ToolSurface(row.surface)
                    definition = registry.resolve(row.tool_name, surface=surface)
                except (KeyError, ValueError) as exc:
                    raise ActionConflict("The registered tool is no longer available.") from exc
                if definition.version != row.tool_version:
                    raise ActionConflict("The tool definition changed; request a new action.")
                identity = ResolvedToolIdentity(
                    requested_name=row.requested_tool,
                    canonical_name=row.tool_name,
                    definition=definition,
                    surface=surface,
                )
                try:
                    envelope = build_action_envelope(
                        identity,
                        _canonical_json(dict(arguments)),
                        owner=row.owner or None,
                        session_id=row.session_id,
                        request_id=row.request_id,
                    )
                except ActionArgumentError as exc:
                    raise ActionValidationError(str(exc)) from exc
                old_hash = row.arguments_hash
                row.arguments_json = envelope.canonical_arguments
                row.arguments_hash = envelope.arguments_hash
                row.revision += 1
                self._append_audit(
                    db,
                    row,
                    "arguments_edited",
                    actor=actor or row.owner or "user",
                    payload={
                        "arguments": envelope.arguments_dict(),
                        "new_arguments_hash": envelope.arguments_hash,
                        "old_arguments_hash": old_hash,
                        "revision": row.revision,
                    },
                )
                db.commit()
                db.refresh(row)
                return self._action_dict(row, now=now)
            finally:
                db.close()

    def _assert_pending_current(
        self,
        row: AgentAction,
        *,
        now: datetime,
        expected_revision: int,
        expected_hash: Optional[str] = None,
    ) -> None:
        if row.status != ActionStatus.PENDING.value:
            raise ActionConflict(f"Action is already {row.status}.")
        if row.expires_at <= now:
            row.status = ActionStatus.EXPIRED.value
            raise ActionExpired("Action approval expired; request it again.")
        if int(expected_revision) != int(row.revision):
            raise ActionConflict("Action changed since it was reviewed; refresh and try again.")
        if expected_hash is not None and expected_hash != row.arguments_hash:
            raise ActionConflict("Action arguments changed since they were reviewed.")

    def claim_approval(
        self,
        action_id: str,
        owner: Optional[str],
        *,
        expected_revision: int,
        expected_hash: str,
        actor: Optional[str] = None,
        always_allow: bool = False,
    ) -> ApprovalGrant:
        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                row = self._owned_row(db, action_id, owner)
                try:
                    self._assert_pending_current(
                        row,
                        now=now,
                        expected_revision=expected_revision,
                        expected_hash=expected_hash,
                    )
                except ActionExpired:
                    self._append_audit(
                        db,
                        row,
                        "expired",
                        actor="system",
                        payload={"expired_at": _iso(row.expires_at)},
                    )
                    db.commit()
                    raise

                rule_id = None
                if always_allow:
                    if row.risk_level >= int(RiskLevel.LEVEL_3):
                        raise ActionConflict("Level 3 actions can never be always allowed.")
                    rule = (
                        db.query(AgentApprovalRule)
                        .filter(
                            AgentApprovalRule.owner == row.owner,
                            AgentApprovalRule.tool_name == row.tool_name,
                            AgentApprovalRule.tool_version == row.tool_version,
                            AgentApprovalRule.arguments_hash == row.arguments_hash,
                        )
                        .first()
                    )
                    if rule is None:
                        rule = AgentApprovalRule(
                            id=uuid.uuid4().hex,
                            owner=row.owner,
                            tool_name=row.tool_name,
                            tool_version=row.tool_version,
                            arguments_hash=row.arguments_hash,
                            scope_json=_canonical_json(
                                {
                                    "arguments_hash": row.arguments_hash,
                                    "mode": "exact_arguments",
                                    "origin": row.origin,
                                    "surface": row.surface,
                                }
                            ),
                            max_risk_level=2,
                            enabled=True,
                            created_by=actor or row.owner,
                        )
                        db.add(rule)
                        db.flush()
                    else:
                        rule.enabled = True
                        # The unique key intentionally remains exact tool +
                        # version + arguments. Re-approving from another
                        # trusted workflow replaces, rather than widens, the
                        # standing scope.
                        rule.scope_json = _canonical_json(
                            {
                                "arguments_hash": row.arguments_hash,
                                "mode": "exact_arguments",
                                "origin": row.origin,
                                "surface": row.surface,
                            }
                        )
                    rule_id = rule.id

                row.status = ActionStatus.EXECUTING.value
                row.approved_at = now
                row.approved_by = actor or row.owner or "user"
                row.execution_started_at = now
                row.approval_rule_id = rule_id
                nonce = secrets.token_urlsafe(32)
                row.approval_nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
                self._append_audit(
                    db,
                    row,
                    "approved",
                    actor=row.approved_by,
                    payload={
                        "always_allow": bool(always_allow),
                        "arguments_hash": row.arguments_hash,
                        "revision": row.revision,
                        "rule_id": rule_id,
                    },
                )
                self._append_audit(
                    db,
                    row,
                    "execution_started",
                    actor="system",
                    payload={"approval_id": row.id},
                )
                db.commit()
                return ApprovalGrant(
                    approval_id=row.id,
                    owner=row.owner or None,
                    tool_name=row.tool_name,
                    tool_version=row.tool_version,
                    arguments_hash=row.arguments_hash,
                    revision=row.revision,
                    surface=ToolSurface(row.surface),
                    origin=ExecutionOrigin(row.origin),
                    expires_at=row.expires_at,
                    correlation_id=row.correlation_id,
                    nonce=nonce,
                    request_id=row.request_id,
                    session_id=row.session_id,
                    rule_id=rule_id,
                )
            finally:
                db.close()

    def claim_matching_rule(
        self,
        action: ActionEnvelope,
        *,
        risk_level: int,
        approval_reason: str,
        origin: Optional[str] = None,
        execution_context: Optional[Mapping[str, Any]] = None,
    ) -> Optional[ApprovalGrant]:
        """Auto-claim an exact Level-1/2 action under a stored narrow rule."""

        if int(risk_level) >= int(RiskLevel.LEVEL_3):
            return None
        owner = self._owner_value(action.owner)
        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                rule = (
                    db.query(AgentApprovalRule)
                    .filter(
                        AgentApprovalRule.owner == owner,
                        AgentApprovalRule.tool_name == action.tool_name,
                        AgentApprovalRule.tool_version == action.tool_version,
                        AgentApprovalRule.arguments_hash == action.arguments_hash,
                        AgentApprovalRule.enabled.is_(True),
                        AgentApprovalRule.max_risk_level >= int(risk_level),
                    )
                    .first()
                )
                if (
                    rule is None
                    or not self._rule_matches_action(rule, action)
                    or (rule.expires_at is not None and rule.expires_at <= now)
                ):
                    return None
                rule_id = rule.id
            finally:
                db.close()

            # Create the immutable proposal/audit record even when a rule can
            # authorize it. RLock permits the nested call safely.
            proposed = self.propose(
                action,
                risk_level=risk_level,
                approval_reason=approval_reason,
                origin=origin,
                execution_context=execution_context,
            )
            db = self._session_factory()
            try:
                row = self._owned_row(db, proposed["id"], action.owner)
                rule = (
                    db.query(AgentApprovalRule)
                    .filter(
                        AgentApprovalRule.id == rule_id,
                        AgentApprovalRule.owner == owner,
                        AgentApprovalRule.enabled.is_(True),
                    )
                    .first()
                )
                if (
                    rule is None
                    or not self._rule_matches_action(rule, action)
                    or row.status != ActionStatus.PENDING.value
                    or row.owner != owner
                    or row.tool_name != action.tool_name
                    or row.tool_version != action.tool_version
                    or row.arguments_hash != action.arguments_hash
                    or row.surface != action.surface.value
                    or row.origin != str(origin or action.origin.value)
                ):
                    return None
                if row.expires_at <= now:
                    row.status = ActionStatus.EXPIRED.value
                    self._append_audit(
                        db,
                        row,
                        "expired",
                        actor="system",
                        payload={"expired_at": _iso(row.expires_at)},
                    )
                    db.commit()
                    return None
                row.status = ActionStatus.EXECUTING.value
                row.approved_at = now
                row.approved_by = f"rule:{rule.id}"
                row.execution_started_at = now
                row.approval_rule_id = rule.id
                nonce = secrets.token_urlsafe(32)
                row.approval_nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
                rule.last_used_at = now
                self._append_audit(
                    db,
                    row,
                    "auto_approved",
                    actor=row.approved_by,
                    payload={
                        "arguments_hash": row.arguments_hash,
                        "revision": row.revision,
                        "rule_id": rule.id,
                    },
                )
                self._append_audit(
                    db,
                    row,
                    "execution_started",
                    actor="system",
                    payload={"approval_id": row.id, "rule_id": rule.id},
                )
                db.commit()
                return ApprovalGrant(
                    approval_id=row.id,
                    owner=row.owner or None,
                    tool_name=row.tool_name,
                    tool_version=row.tool_version,
                    arguments_hash=row.arguments_hash,
                    revision=row.revision,
                    surface=ToolSurface(row.surface),
                    origin=ExecutionOrigin(row.origin),
                    expires_at=row.expires_at,
                    correlation_id=row.correlation_id,
                    nonce=nonce,
                    request_id=row.request_id,
                    session_id=row.session_id,
                    rule_id=rule.id,
                )
            finally:
                db.close()

    def consume_grant(self, grant: ApprovalGrant) -> None:
        """Atomically consume one approval nonce immediately before dispatch."""

        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                row = self._owned_row(db, grant.approval_id, grant.owner)
                nonce_hash = hashlib.sha256(grant.nonce.encode("utf-8")).hexdigest()
                if row.status != ActionStatus.EXECUTING.value:
                    raise ActionConflict(f"Action is already {row.status}.")
                if row.approval_consumed_at is not None:
                    raise ActionConflict("Approval evidence has already been consumed.")
                if not row.approval_nonce_hash or not secrets.compare_digest(
                    row.approval_nonce_hash,
                    nonce_hash,
                ):
                    raise ActionConflict("Approval evidence is invalid.")
                if (
                    row.tool_name != grant.tool_name
                    or row.tool_version != grant.tool_version
                    or row.arguments_hash != grant.arguments_hash
                    or row.revision != grant.revision
                    or row.surface != grant.surface.value
                    or row.origin != grant.origin.value
                    or row.request_id != grant.request_id
                    or row.session_id != grant.session_id
                    or row.expires_at <= now
                ):
                    raise ActionConflict("Approval evidence no longer matches the action.")
                row.approval_consumed_at = now
                self._append_audit(
                    db,
                    row,
                    "approval_consumed",
                    actor="executor",
                    payload={
                        "arguments_hash": row.arguments_hash,
                        "revision": row.revision,
                    },
                )
                db.commit()
            finally:
                db.close()

    def list_rules(self, owner: Optional[str]) -> list[dict[str, Any]]:
        now = self._clock()
        db = self._session_factory()
        try:
            rows = (
                db.query(AgentApprovalRule)
                .filter(AgentApprovalRule.owner == self._owner_value(owner))
                .order_by(AgentApprovalRule.created_at.desc())
                .all()
            )
            output = []
            for row in rows:
                try:
                    scope = json.loads(row.scope_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    scope = {}
                output.append(
                    {
                        "id": row.id,
                        "tool_name": row.tool_name,
                        "tool_version": row.tool_version,
                        "arguments_hash": row.arguments_hash,
                        "scope": scope,
                        "max_risk_level": row.max_risk_level,
                        "enabled": bool(row.enabled),
                        "expires_at": _iso(row.expires_at),
                        "last_used_at": _iso(row.last_used_at),
                        "created_at": _iso(row.created_at),
                        "created_by": row.created_by,
                    }
                )
            return output
        finally:
            db.close()

    def revoke_rule(self, rule_id: str, owner: Optional[str]) -> dict[str, Any]:
        with self._lock:
            db = self._session_factory()
            try:
                row = (
                    db.query(AgentApprovalRule)
                    .filter(
                        AgentApprovalRule.id == rule_id,
                        AgentApprovalRule.owner == self._owner_value(owner),
                    )
                    .first()
                )
                if row is None:
                    raise ActionNotFound("Approval rule not found.")
                row.enabled = False
                db.commit()
                return {"id": row.id, "enabled": False}
            finally:
                db.close()

    def reject(
        self,
        action_id: str,
        owner: Optional[str],
        *,
        expected_revision: int,
        reason: str = "",
        actor: Optional[str] = None,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                row = self._owned_row(db, action_id, owner)
                try:
                    self._assert_pending_current(
                        row,
                        now=now,
                        expected_revision=expected_revision,
                    )
                except ActionExpired:
                    self._append_audit(
                        db,
                        row,
                        "expired",
                        actor="system",
                        payload={"expired_at": _iso(row.expires_at)},
                    )
                    db.commit()
                    raise
                row.status = ActionStatus.REJECTED.value
                row.rejected_at = now
                row.rejected_by = actor or row.owner or "user"
                row.decision_reason = str(reason or "")[:2000]
                self._append_audit(
                    db,
                    row,
                    "rejected",
                    actor=row.rejected_by,
                    payload={"reason": row.decision_reason, "revision": row.revision},
                )
                db.commit()
                db.refresh(row)
                return self._action_dict(row, now=now)
            finally:
                db.close()

    def cancel(
        self,
        action_id: str,
        owner: Optional[str],
        *,
        expected_revision: int,
        reason: str = "",
        actor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Cancel a pending or executing action without overstating reversal."""

        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                row = self._owned_row(db, action_id, owner)
                if row.revision != expected_revision:
                    raise ActionConflict("The action changed after it was reviewed.")
                if row.status not in {
                    ActionStatus.PENDING.value,
                    ActionStatus.EXECUTING.value,
                }:
                    raise ActionConflict(f"Action is already {row.status}.")
                if row.status == ActionStatus.PENDING.value and row.expires_at <= now:
                    row.status = ActionStatus.EXPIRED.value
                    self._append_audit(
                        db,
                        row,
                        "expired",
                        actor="system",
                        payload={"expired_at": _iso(row.expires_at)},
                    )
                    db.commit()
                    raise ActionExpired("The approval request has expired.")

                previous_status = row.status
                execution_may_have_started = (
                    previous_status == ActionStatus.EXECUTING.value
                    or row.approval_consumed_at is not None
                )
                row.status = ActionStatus.CANCELLED.value
                row.execution_finished_at = now
                row.decision_reason = str(reason or "")[:2000]
                if execution_may_have_started:
                    row.verification_status = "reconciliation_required"
                    row.reversal_status = "not_attempted"
                self._append_audit(
                    db,
                    row,
                    "cancelled",
                    actor=actor or row.owner or "user",
                    payload={
                        "previous_status": previous_status,
                        "reason": row.decision_reason,
                        "revision": row.revision,
                        "verification_status": row.verification_status,
                        "reversal_status": row.reversal_status,
                    },
                )
                db.commit()
                db.refresh(row)
                return self._action_dict(row, now=now)
            finally:
                db.close()

    def finish_execution(
        self,
        grant: ApprovalGrant,
        result: Mapping[str, Any],
        *,
        verification_status: str,
    ) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            db = self._session_factory()
            try:
                row = self._owned_row(db, grant.approval_id, grant.owner)
                if row.status != ActionStatus.EXECUTING.value:
                    raise ActionConflict(f"Action is already {row.status}.")
                if row.approval_consumed_at is None:
                    raise ActionConflict("Approval was not consumed by the executor.")
                if (
                    row.tool_name != grant.tool_name
                    or row.tool_version != grant.tool_version
                    or row.arguments_hash != grant.arguments_hash
                    or row.revision != grant.revision
                    or row.request_id != grant.request_id
                    or row.session_id != grant.session_id
                ):
                    raise ActionConflict("Approval evidence no longer matches the action.")
                normalized_verification = str(
                    verification_status or "indeterminate"
                )[:64]
                verification_failed = normalized_verification in {
                    "failed",
                    "read_back_failed",
                }
                failed = (
                    bool(result.get("error"))
                    or result.get("exit_code") not in (None, 0)
                    or verification_failed
                )
                row.status = (
                    ActionStatus.FAILED.value if failed else ActionStatus.SUCCEEDED.value
                )
                row.execution_finished_at = now
                row.result_json = _canonical_json(_result_for_storage(result))
                row.error = str(
                    result.get("error")
                    or (
                        "Post-execution verification failed."
                        if verification_failed
                        else ""
                    )
                )[:4000] or None
                row.verification_status = normalized_verification
                self._append_audit(
                    db,
                    row,
                    "execution_failed" if failed else "execution_succeeded",
                    actor="system",
                    payload={
                        "result": _result_for_storage(result),
                        "verification_status": row.verification_status,
                    },
                )
                db.commit()
                db.refresh(row)
                return self._action_dict(row, now=now)
            finally:
                db.close()

    def fail_claimed_execution(
        self,
        grant: ApprovalGrant,
        error: str,
    ) -> dict[str, Any]:
        return self.finish_execution(
            grant,
            {"error": str(error)[:4000], "exit_code": 1},
            verification_status="failed",
        )

    def list_audit_events(
        self,
        owner: Optional[str],
        *,
        action_id: Optional[str] = None,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        db = self._session_factory()
        try:
            query = db.query(AgentActionAuditEvent).filter(
                AgentActionAuditEvent.owner == self._owner_value(owner)
            )
            if action_id:
                # Prove ownership even when the action has no events yet.
                self._owned_row(db, action_id, owner)
                query = query.filter(AgentActionAuditEvent.action_id == action_id)
            rows = (
                query.order_by(AgentActionAuditEvent.occurred_at.desc())
                .limit(limit)
                .all()
            )
            output = []
            for row in rows:
                try:
                    payload = json.loads(row.payload_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                output.append(
                    {
                        "id": row.id,
                        "action_id": row.action_id,
                        "sequence": row.sequence,
                        "event_type": row.event_type,
                        "actor": row.actor,
                        "occurred_at": _iso(row.occurred_at),
                        "correlation_id": row.correlation_id,
                        "payload": payload,
                        "previous_hash": row.previous_hash,
                        "event_hash": row.event_hash,
                    }
                )
            return output
        finally:
            db.close()

    def verify_audit_chain(self, action_id: str, owner: Optional[str]) -> bool:
        db = self._session_factory()
        try:
            action = self._owned_row(db, action_id, owner)
            rows = (
                db.query(AgentActionAuditEvent)
                .filter(AgentActionAuditEvent.action_id == action.id)
                .order_by(AgentActionAuditEvent.sequence.asc())
                .all()
            )
            previous_hash = ""
            expected_sequence = 1
            for row in rows:
                try:
                    payload = json.loads(row.payload_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    return False
                hash_body = {
                    "action_id": row.action_id,
                    "actor": row.actor,
                    "correlation_id": row.correlation_id,
                    "event_type": row.event_type,
                    "occurred_at": _iso(row.occurred_at),
                    "owner": row.owner,
                    "payload": payload,
                    "previous_hash": previous_hash,
                    "sequence": expected_sequence,
                }
                expected_hash = hashlib.sha256(
                    _canonical_json(hash_body).encode("utf-8")
                ).hexdigest()
                if (
                    row.sequence != expected_sequence
                    or row.previous_hash != previous_hash
                    or row.event_hash != expected_hash
                ):
                    return False
                previous_hash = row.event_hash
                expected_sequence += 1
            return bool(rows)
        finally:
            db.close()


_ledger: Optional[ActionLedger] = None
_ledger_lock = threading.Lock()


def get_action_ledger() -> ActionLedger:
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = ActionLedger()
    return _ledger
