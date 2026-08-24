"""Owner-scoped service for tasks, projects, commitments and planning.

The service is the only mutation boundary for the Phase Ten ``work_*`` schema.
It validates graph and relationship integrity, records an append-only receipt,
and requires durable action-ledger evidence for agent-originated writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping, Optional, Sequence
import uuid

from sqlalchemy import inspect as sqlalchemy_inspect

from core.database import AgentAction, ScheduledTask, SessionLocal, engine
from src.work_models import (
    WORK_SCHEMA_VERSION,
    WorkCommitment,
    WorkMilestone,
    WorkMutationReceipt,
    WorkPlan,
    WorkProject,
    WorkReference,
    WorkReminder,
    WorkSchemaMeta,
    WorkTask,
    WorkTaskDependency,
    ensure_work_schema,
)


TASK_STATUSES = frozenset(
    {
        "inbox",
        "planned",
        "ready",
        "in_progress",
        "blocked",
        "on_hold",
        "scheduled",
        "completed",
        "cancelled",
    }
)
TASK_TERMINAL_STATUSES = frozenset({"completed", "cancelled"})
TASK_PRIORITIES = frozenset({"none", "low", "normal", "high", "urgent"})
ENERGY_LEVELS = frozenset({"low", "medium", "high"})
APPROVAL_STATES = frozenset(
    {"not_required", "pending", "approved", "rejected", "expired", "migrated"}
)
CREATOR_KINDS = frozenset({"user", "agent", "migration", "integration"})
PROJECT_STATUSES = frozenset(
    {"proposed", "active", "on_hold", "completed", "cancelled", "archived"}
)
MILESTONE_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})
COMMITMENT_STATUSES = frozenset({"open", "fulfilled", "broken", "cancelled"})
COMMITMENT_REVIEW_STATES = frozenset({"suggested", "approved", "rejected", "expired"})
REMINDER_STATUSES = frozenset({"pending", "fired", "dismissed", "cancelled"})
REFERENCE_TYPES = frozenset(
    {"email", "meeting", "document", "calendar_event", "contact", "note", "url", "other"}
)
PLAN_TYPES = frozenset({"focus", "breakdown", "reschedule"})
PLAN_STATUSES = frozenset({"draft", "accepted", "rejected", "applied"})
RECURRENCE_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "yearly", "custom"})
class WorkError(RuntimeError):
    code = "work_error"
    status_code = 400


class WorkNotFound(WorkError):
    code = "not_found"
    status_code = 404


class WorkConflict(WorkError):
    code = "conflict"
    status_code = 409


class WorkValidationError(WorkError):
    code = "invalid_work_record"
    status_code = 422


class WorkApprovalRequired(WorkError):
    code = "approval_required"
    status_code = 409


@dataclass(frozen=True, slots=True)
class MutationContext:
    actor_kind: str
    actor_id: str = ""
    action_id: Optional[str] = None
    correlation_id: str = ""

    @classmethod
    def user(cls, owner: Optional[str], *, correlation_id: str = "") -> "MutationContext":
        return cls(
            actor_kind="user",
            actor_id=str(owner or ""),
            correlation_id=correlation_id,
        )

    @classmethod
    def agent(
        cls,
        owner: Optional[str],
        *,
        action_id: Optional[str],
        correlation_id: str = "",
    ) -> "MutationContext":
        return cls(
            actor_kind="agent",
            actor_id=str(owner or ""),
            action_id=action_id,
            correlation_id=correlation_id,
        )


def _owner_key(owner: Optional[str]) -> str:
    return str(owner or "")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any, field: str, *, allow_none: bool = True) -> Optional[datetime]:
    if value in (None, ""):
        if allow_none:
            return None
        raise WorkValidationError(f"{field} is required")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        try:
            text = value.strip()
            if len(text) == 10:
                parsed = datetime.combine(date.fromisoformat(text), time.min)
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WorkValidationError(f"{field} must be an ISO 8601 date or datetime") from exc
    else:
        raise WorkValidationError(f"{field} must be an ISO 8601 date or datetime")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _json_load(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return default
    return decoded


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _bounded_text(value: Any, field: str, *, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise WorkValidationError(f"{field} is required")
    if len(text) > maximum:
        raise WorkValidationError(f"{field} must be at most {maximum} characters")
    return text


def _enum(value: Any, field: str, allowed: frozenset[str], default: str) -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in allowed:
        raise WorkValidationError(
            f"{field} must be one of: {', '.join(sorted(allowed))}"
        )
    return normalized


def _bounded_int(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
    allow_none: bool = True,
) -> Optional[int]:
    if value in (None, "") and allow_none:
        return None
    if isinstance(value, bool):
        raise WorkValidationError(f"{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkValidationError(f"{field} must be an integer") from exc
    if number < minimum or number > maximum:
        raise WorkValidationError(f"{field} must be between {minimum} and {maximum}")
    return number


def _string_list(value: Any, field: str, *, maximum: int = 50) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple, set)):
        raise WorkValidationError(f"{field} must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = _bounded_text(raw, field, maximum=120)
        if not item:
            continue
        marker = item.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    if len(out) > maximum:
        raise WorkValidationError(f"{field} supports at most {maximum} values")
    return out


def _dict_list(value: Any, field: str, *, maximum: int = 100) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise WorkValidationError(f"{field} must be a list of objects")
    if len(value) > maximum:
        raise WorkValidationError(f"{field} supports at most {maximum} values")
    # Canonical JSON round trip rejects non-serialisable/NaN values and copies
    # caller-owned structures before they reach persistence.
    try:
        return json.loads(_canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise WorkValidationError(f"{field} must contain JSON values") from exc


def _recurrence(value: Any) -> dict[str, Any]:
    if value in (None, "", {}):
        return {}
    if not isinstance(value, Mapping):
        raise WorkValidationError("recurrence must be an object")
    rule = dict(value)
    frequency = str(rule.get("frequency") or "").strip().lower()
    if frequency not in RECURRENCE_FREQUENCIES:
        raise WorkValidationError(
            "recurrence.frequency must be daily, weekly, monthly, yearly or custom"
        )
    normalized: dict[str, Any] = {
        "frequency": frequency,
        "interval": _bounded_int(
            rule.get("interval", 1),
            "recurrence.interval",
            minimum=1,
            maximum=365,
            allow_none=False,
        ),
    }
    if rule.get("weekdays") is not None:
        weekdays = rule["weekdays"]
        if not isinstance(weekdays, list):
            raise WorkValidationError("recurrence.weekdays must be a list")
        normalized["weekdays"] = sorted(
            {
                _bounded_int(day, "recurrence.weekdays", minimum=0, maximum=6, allow_none=False)
                for day in weekdays
            }
        )
    if rule.get("until") not in (None, ""):
        normalized["until"] = _iso(_parse_datetime(rule["until"], "recurrence.until"))
    if rule.get("count") not in (None, ""):
        normalized["count"] = _bounded_int(
            rule["count"],
            "recurrence.count",
            minimum=1,
            maximum=10000,
            allow_none=False,
        )
    if rule.get("timezone"):
        normalized["timezone"] = _bounded_text(
            rule["timezone"], "recurrence.timezone", maximum=100
        )
    if frequency == "custom":
        normalized["rule"] = _bounded_text(
            rule.get("rule"), "recurrence.rule", maximum=500, required=True
        )
    return normalized


class WorkService:
    def __init__(
        self,
        *,
        session_factory=SessionLocal,
        bind=None,
        initialise: bool = True,
        backfill_legacy: bool = True,
        clock=_utcnow,
    ) -> None:
        self._session_factory = session_factory
        self._bind = bind or getattr(session_factory, "kw", {}).get("bind") or engine
        self._clock = clock
        if initialise:
            ensure_work_schema(bind=self._bind)
            self._record_schema_version()
            if backfill_legacy:
                self.backfill_legacy_scheduled_tasks()

    def _record_schema_version(self) -> None:
        db = self._session_factory()
        try:
            row = db.query(WorkSchemaMeta).filter(WorkSchemaMeta.key == "schema_version").first()
            if row is None:
                row = WorkSchemaMeta(key="schema_version", value=str(WORK_SCHEMA_VERSION))
                db.add(row)
            else:
                row.value = str(WORK_SCHEMA_VERSION)
                row.updated_at = self._clock()
            db.commit()
        finally:
            db.close()

    def _authorize_mutation(
        self,
        db,
        owner: str,
        context: MutationContext,
        *,
        expected_tool: str,
    ) -> Optional[AgentAction]:
        kind = str(context.actor_kind or "").strip().lower()
        if kind not in {"user", "agent", "migration", "integration"}:
            raise WorkApprovalRequired("Unknown mutation actor")
        if context.actor_id != owner:
            raise WorkApprovalRequired("Mutation actor does not match the record owner")
        if kind == "migration":
            return None
        if kind in {"user", "integration"}:
            if context.action_id:
                raise WorkApprovalRequired(
                    "Direct user/integration mutations cannot claim an agent action"
                )
            return None
        if not context.action_id:
            raise WorkApprovalRequired("Agent mutation requires an approved action-ledger claim")
        if not sqlalchemy_inspect(self._bind).has_table("agent_actions"):
            raise WorkApprovalRequired("The action ledger is not available")
        allowed_tools = (
            ("delete_work", "work.delete")
            if expected_tool == "delete_work"
            else ("manage_work", "work.manage")
        )
        row = db.query(AgentAction).filter(
            AgentAction.id == context.action_id,
            AgentAction.owner == owner,
            AgentAction.tool_name.in_(allowed_tools),
            AgentAction.status == "executing",
            AgentAction.expires_at > self._clock(),
            AgentAction.approval_consumed_at.is_not(None),
        ).first()
        if row is None:
            raise WorkApprovalRequired(
                "Agent mutation action is missing, belongs to another owner, expired, "
                "unconsumed, or is not executing"
            )
        if str(row.request_id or "") != str(context.correlation_id or ""):
            raise WorkApprovalRequired(
                "Agent mutation request does not match the approved action"
            )
        already_used = db.query(WorkMutationReceipt.id).filter(
            WorkMutationReceipt.owner == owner,
            WorkMutationReceipt.action_id == context.action_id,
        ).first()
        if already_used is not None:
            raise WorkApprovalRequired(
                "Agent mutation action has already been used by the work service"
            )
        return row

    def _receipt(
        self,
        db,
        *,
        owner: str,
        entity_type: str,
        entity_id: str,
        operation: str,
        context: MutationContext,
        before: Optional[Mapping[str, Any]],
        after: Optional[Mapping[str, Any]],
        details: Optional[Mapping[str, Any]] = None,
    ) -> WorkMutationReceipt:
        receipt = WorkMutationReceipt(
            id=uuid.uuid4().hex,
            owner=owner,
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            actor_kind=context.actor_kind,
            actor_id=context.actor_id,
            action_id=context.action_id,
            correlation_id=context.correlation_id,
            before_hash=_digest(before) if before else "",
            after_hash=_digest(after) if after else "",
            details_json=_canonical_json(dict(details or {})),
            occurred_at=self._clock(),
        )
        db.add(receipt)
        return receipt

    @staticmethod
    def _owned(db, model, record_id: str, owner: str):
        row = db.query(model).filter(model.id == record_id, model.owner == owner).first()
        if row is None:
            raise WorkNotFound(f"{model.__name__.removeprefix('Work')} not found")
        return row

    def _references(self, db, owner: str, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        rows = db.query(WorkReference).filter(
            WorkReference.owner == owner,
            WorkReference.entity_type == entity_type,
            WorkReference.entity_id == entity_id,
        ).order_by(WorkReference.created_at.asc()).all()
        return [
            {
                "id": row.id,
                "type": row.reference_type,
                "external_id": row.external_id,
                "label": row.label,
                "url": row.url,
                "metadata": _json_load(row.metadata_json, {}),
            }
            for row in rows
        ]

    def _replace_references(
        self,
        db,
        *,
        owner: str,
        entity_type: str,
        entity_id: str,
        values: Any,
    ) -> None:
        references = _dict_list(values, "references", maximum=100)
        db.query(WorkReference).filter(
            WorkReference.owner == owner,
            WorkReference.entity_type == entity_type,
            WorkReference.entity_id == entity_id,
        ).delete(synchronize_session=False)
        for item in references:
            reference_type = _enum(item.get("type"), "reference.type", REFERENCE_TYPES, "other")
            external_id = _bounded_text(item.get("external_id"), "reference.external_id", maximum=500)
            url = _bounded_text(item.get("url"), "reference.url", maximum=4000)
            if not external_id and not url:
                raise WorkValidationError("Each reference requires external_id or url")
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                raise WorkValidationError("reference.metadata must be an object")
            db.add(
                WorkReference(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    reference_type=reference_type,
                    external_id=external_id,
                    label=_bounded_text(item.get("label"), "reference.label", maximum=300),
                    url=url,
                    metadata_json=_canonical_json(dict(metadata)),
                )
            )

    def _reminders(self, db, owner: str, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        rows = db.query(WorkReminder).filter(
            WorkReminder.owner == owner,
            WorkReminder.entity_type == entity_type,
            WorkReminder.entity_id == entity_id,
        ).order_by(WorkReminder.remind_at.asc()).all()
        return [
            {
                "id": row.id,
                "remind_at": _iso(row.remind_at),
                "message": row.message,
                "channel": row.channel,
                "status": row.status,
                "recurrence": _json_load(row.recurrence_rule_json, {}),
                "fired_at": _iso(row.fired_at),
            }
            for row in rows
        ]

    def _replace_reminders(
        self,
        db,
        *,
        owner: str,
        entity_type: str,
        entity_id: str,
        values: Any,
    ) -> None:
        reminders = _dict_list(values, "reminders", maximum=25)
        db.query(WorkReminder).filter(
            WorkReminder.owner == owner,
            WorkReminder.entity_type == entity_type,
            WorkReminder.entity_id == entity_id,
        ).delete(synchronize_session=False)
        for item in reminders:
            db.add(
                WorkReminder(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    remind_at=_parse_datetime(item.get("remind_at"), "reminder.remind_at", allow_none=False),
                    message=_bounded_text(item.get("message"), "reminder.message", maximum=1000),
                    channel=_bounded_text(item.get("channel") or "in_app", "reminder.channel", maximum=50),
                    status=_enum(item.get("status"), "reminder.status", REMINDER_STATUSES, "pending"),
                    recurrence_rule_json=_canonical_json(_recurrence(item.get("recurrence"))),
                )
            )

    def _task_dependency_ids(self, db, owner: str, task_id: str) -> list[str]:
        return [
            row[0]
            for row in db.query(WorkTaskDependency.depends_on_task_id).filter(
                WorkTaskDependency.owner == owner,
                WorkTaskDependency.task_id == task_id,
            ).all()
        ]

    def _task_dict(self, db, row: WorkTask, *, expanded: bool = True) -> dict[str, Any]:
        data = {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "priority": row.priority,
            "due_at": _iso(row.due_at),
            "start_at": _iso(row.start_at),
            "estimated_minutes": row.estimated_minutes,
            "actual_minutes": row.actual_minutes,
            "project_id": row.project_id,
            "milestone_id": row.milestone_id,
            "parent_task_id": row.parent_task_id,
            "area": row.area,
            "tags": _json_load(row.tags_json, []),
            "contexts": _json_load(row.contexts_json, []),
            "assignees": _json_load(row.assignees_json, []),
            "energy": row.energy,
            "effort": row.effort,
            "recurrence": _json_load(row.recurrence_rule_json, {}),
            "source": {
                "type": row.source_type,
                "id": row.source_id,
                "url": row.source_url,
                "excerpt": row.source_excerpt,
            },
            "completion_notes": row.completion_notes,
            "completed_at": _iso(row.completed_at),
            "created_by": row.created_by,
            "approval_state": row.approval_state,
            "action_id": row.action_id,
            "legacy_scheduled_task_id": row.legacy_scheduled_task_id,
            "legacy_read_only": bool(row.legacy_read_only),
            "sort_order": row.sort_order,
            "revision": row.revision,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        if expanded:
            data["dependency_ids"] = self._task_dependency_ids(db, row.owner, row.id)
            data["references"] = self._references(db, row.owner, "task", row.id)
            data["reminders"] = self._reminders(db, row.owner, "task", row.id)
            data["subtask_count"] = db.query(WorkTask).filter(
                WorkTask.owner == row.owner,
                WorkTask.parent_task_id == row.id,
            ).count()
        return data

    def _project_dict(self, db, row: WorkProject, *, expanded: bool = True) -> dict[str, Any]:
        task_q = db.query(WorkTask).filter(
            WorkTask.owner == row.owner,
            WorkTask.project_id == row.id,
        )
        total = task_q.count()
        completed = task_q.filter(WorkTask.status == "completed").count()
        data = {
            "id": row.id,
            "title": row.title,
            "goal": row.goal,
            "desired_outcome": row.desired_outcome,
            "status": row.status,
            "area": row.area,
            "notes": row.notes,
            "risks": _json_load(row.risks_json, []),
            "decisions": _json_load(row.decisions_json, []),
            "tags": _json_load(row.tags_json, []),
            "budget": {
                "enabled": bool(row.budget_enabled),
                "currency": row.budget_currency,
                "amount_minor": row.budget_amount_minor,
                "spent_minor": row.budget_spent_minor,
            },
            "start_at": _iso(row.start_at),
            "target_at": _iso(row.target_at),
            "progress_summary": row.progress_summary,
            "progress": {
                "total_tasks": total,
                "completed_tasks": completed,
                "percent": round(completed * 100 / total) if total else 0,
            },
            "created_by": row.created_by,
            "approval_state": row.approval_state,
            "action_id": row.action_id,
            "revision": row.revision,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        if expanded:
            milestones = db.query(WorkMilestone).filter(
                WorkMilestone.owner == row.owner,
                WorkMilestone.project_id == row.id,
            ).order_by(WorkMilestone.sort_order.asc(), WorkMilestone.created_at.asc()).all()
            data["milestones"] = [self._milestone_dict(m) for m in milestones]
            data["references"] = self._references(db, row.owner, "project", row.id)
        return data

    @staticmethod
    def _milestone_dict(row: WorkMilestone) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "target_at": _iso(row.target_at),
            "completed_at": _iso(row.completed_at),
            "sort_order": row.sort_order,
            "revision": row.revision,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def _commitment_dict(self, db, row: WorkCommitment, *, expanded: bool = True) -> dict[str, Any]:
        data = {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "review_state": row.review_state,
            "due_at": _iso(row.due_at),
            "fulfilled_at": _iso(row.fulfilled_at),
            "counterparty": row.counterparty,
            "project_id": row.project_id,
            "task_id": row.task_id,
            "source": {
                "type": row.source_type,
                "id": row.source_id,
                "url": row.source_url,
                "excerpt": row.source_excerpt,
                "occurred_at": _iso(row.source_occurred_at),
            },
            "confidence": row.confidence,
            "created_by": row.created_by,
            "action_id": row.action_id,
            "completion_notes": row.completion_notes,
            "revision": row.revision,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        if expanded:
            data["references"] = self._references(db, row.owner, "commitment", row.id)
            data["reminders"] = self._reminders(db, row.owner, "commitment", row.id)
        return data

    def _plan_dict(self, row: WorkPlan) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_type": row.plan_type,
            "title": row.title,
            "goal": row.goal,
            "plan_date": _iso(row.plan_date),
            "status": row.status,
            "proposals": _json_load(row.proposals_json, []),
            "work_blocks": _json_load(row.work_blocks_json, []),
            "assumptions": _json_load(row.assumptions_json, []),
            "created_by": row.created_by,
            "action_id": row.action_id,
            "applied_at": _iso(row.applied_at),
            "revision": row.revision,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def _validate_project_links(
        self,
        db,
        owner: str,
        *,
        project_id: Optional[str],
        milestone_id: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        project = None
        milestone = None
        if project_id:
            project = self._owned(db, WorkProject, project_id, owner)
        if milestone_id:
            milestone = self._owned(db, WorkMilestone, milestone_id, owner)
            if project is None:
                project = self._owned(db, WorkProject, milestone.project_id, owner)
            elif milestone.project_id != project.id:
                raise WorkValidationError("milestone_id does not belong to project_id")
        return project.id if project else None, milestone.id if milestone else None

    def _validate_parent(self, db, owner: str, task_id: str, parent_id: Optional[str]) -> Optional[str]:
        if not parent_id:
            return None
        if parent_id == task_id:
            raise WorkValidationError("Task cannot be its own parent")
        parent = self._owned(db, WorkTask, parent_id, owner)
        cursor = parent
        seen = set()
        while cursor.parent_task_id:
            if cursor.id in seen:
                raise WorkValidationError("Existing subtask hierarchy contains a cycle")
            seen.add(cursor.id)
            if cursor.parent_task_id == task_id:
                raise WorkValidationError("Subtask hierarchy would create a cycle")
            cursor = self._owned(db, WorkTask, cursor.parent_task_id, owner)
        return parent.id

    def _dependency_reaches(self, db, owner: str, start: str, target: str) -> bool:
        stack = [start]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(
                edge[0]
                for edge in db.query(WorkTaskDependency.depends_on_task_id).filter(
                    WorkTaskDependency.owner == owner,
                    WorkTaskDependency.task_id == current,
                ).all()
            )
        return False

    def _replace_dependencies(self, db, owner: str, task_id: str, dependency_ids: Any) -> None:
        ids = _string_list(dependency_ids, "dependency_ids", maximum=100)
        if task_id in ids:
            raise WorkValidationError("Task cannot depend on itself")
        for dependency_id in ids:
            self._owned(db, WorkTask, dependency_id, owner)
            if self._dependency_reaches(db, owner, dependency_id, task_id):
                raise WorkValidationError("Task dependency would create a cycle")
        db.query(WorkTaskDependency).filter(
            WorkTaskDependency.owner == owner,
            WorkTaskDependency.task_id == task_id,
        ).delete(synchronize_session=False)
        for dependency_id in ids:
            db.add(
                WorkTaskDependency(
                    id=uuid.uuid4().hex,
                    owner=owner,
                    task_id=task_id,
                    depends_on_task_id=dependency_id,
                )
            )

    def _task_values(
        self,
        db,
        owner: str,
        payload: Mapping[str, Any],
        *,
        task_id: str,
        existing: Optional[WorkTask] = None,
        context: MutationContext,
    ) -> dict[str, Any]:
        def value(name: str, fallback: Any = None) -> Any:
            if name in payload:
                return payload[name]
            if existing is not None and name in {
                "tags",
                "contexts",
                "assignees",
                "recurrence",
            }:
                column = {
                    "tags": existing.tags_json,
                    "contexts": existing.contexts_json,
                    "assignees": existing.assignees_json,
                    "recurrence": existing.recurrence_rule_json,
                }[name]
                return _json_load(column, [] if name != "recurrence" else {})
            return getattr(existing, name, fallback) if existing is not None else fallback

        start_at = _parse_datetime(value("start_at"), "start_at")
        due_at = _parse_datetime(value("due_at"), "due_at")
        if start_at and due_at and start_at > due_at:
            raise WorkValidationError("start_at cannot be after due_at")
        project_id, milestone_id = self._validate_project_links(
            db,
            owner,
            project_id=value("project_id"),
            milestone_id=value("milestone_id"),
        )
        parent_id = self._validate_parent(db, owner, task_id, value("parent_task_id"))
        status = _enum(value("status"), "status", TASK_STATUSES, "inbox")
        completed_at = _parse_datetime(value("completed_at"), "completed_at")
        if status == "completed" and completed_at is None:
            completed_at = self._clock()
        if status != "completed" and "status" in payload and "completed_at" not in payload:
            completed_at = None
        created_by = (
            existing.created_by
            if existing is not None
            else context.actor_kind
        )
        approval_state = (
            existing.approval_state
            if existing is not None
            else "approved" if context.actor_kind == "agent" else "not_required"
        )
        return {
            "title": _bounded_text(value("title"), "title", maximum=300, required=True),
            "description": _bounded_text(value("description"), "description", maximum=20000),
            "status": status,
            "priority": _enum(value("priority"), "priority", TASK_PRIORITIES, "normal"),
            "due_at": due_at,
            "start_at": start_at,
            "estimated_minutes": _bounded_int(
                value("estimated_minutes"), "estimated_minutes", minimum=1, maximum=525600
            ),
            "actual_minutes": _bounded_int(
                value("actual_minutes"), "actual_minutes", minimum=0, maximum=525600
            ),
            "project_id": project_id,
            "milestone_id": milestone_id,
            "parent_task_id": parent_id,
            "area": _bounded_text(value("area"), "area", maximum=200),
            "tags_json": _canonical_json(_string_list(value("tags"), "tags")),
            "contexts_json": _canonical_json(_string_list(value("contexts"), "contexts")),
            "assignees_json": _canonical_json(_string_list(value("assignees"), "assignees")),
            "energy": _enum(value("energy"), "energy", ENERGY_LEVELS, "medium"),
            "effort": _bounded_int(value("effort"), "effort", minimum=1, maximum=5),
            "recurrence_rule_json": _canonical_json(_recurrence(value("recurrence"))),
            "source_type": _bounded_text(value("source_type", "manual"), "source_type", maximum=100) or "manual",
            "source_id": _bounded_text(value("source_id"), "source_id", maximum=500),
            "source_url": _bounded_text(value("source_url"), "source_url", maximum=4000),
            "source_excerpt": _bounded_text(value("source_excerpt"), "source_excerpt", maximum=10000),
            "completion_notes": _bounded_text(value("completion_notes"), "completion_notes", maximum=20000),
            "completed_at": completed_at,
            "created_by": created_by,
            "approval_state": approval_state,
            "action_id": context.action_id or (existing.action_id if existing is not None else None),
            "sort_order": _bounded_int(
                value("sort_order", 0), "sort_order", minimum=-100000, maximum=100000, allow_none=False
            ),
        }

    def create_task(
        self,
        owner: Optional[str],
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            task_id = uuid.uuid4().hex
            values = self._task_values(
                db, owner_value, payload, task_id=task_id, context=context
            )
            row = WorkTask(id=task_id, owner=owner_value, **values)
            db.add(row)
            db.flush()
            if "dependency_ids" in payload:
                self._replace_dependencies(db, owner_value, task_id, payload.get("dependency_ids"))
            if "references" in payload:
                self._replace_references(
                    db,
                    owner=owner_value,
                    entity_type="task",
                    entity_id=task_id,
                    values=payload.get("references"),
                )
            if "reminders" in payload:
                self._replace_reminders(
                    db,
                    owner=owner_value,
                    entity_type="task",
                    entity_id=task_id,
                    values=payload.get("reminders"),
                )
            db.flush()
            after = self._task_dict(db, row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="task",
                entity_id=task_id,
                operation="create",
                context=context,
                before=None,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_task(self, owner: Optional[str], task_id: str) -> dict[str, Any]:
        db = self._session_factory()
        try:
            return self._task_dict(db, self._owned(db, WorkTask, task_id, _owner_key(owner)))
        finally:
            db.close()

    def find_task_by_source(
        self,
        owner: Optional[str],
        *,
        source_type: str,
        source_id: str,
    ) -> Optional[dict[str, Any]]:
        """Resolve a durable integration source for idempotent bridges."""

        owner_value = _owner_key(owner)
        normalized_type = _bounded_text(
            source_type, "source_type", maximum=100, required=True
        )
        normalized_id = _bounded_text(
            source_id, "source_id", maximum=500, required=True
        )
        db = self._session_factory()
        try:
            row = (
                db.query(WorkTask)
                .filter(
                    WorkTask.owner == owner_value,
                    WorkTask.source_type == normalized_type,
                    WorkTask.source_id == normalized_id,
                )
                .order_by(WorkTask.created_at.asc(), WorkTask.id)
                .first()
            )
            return self._task_dict(db, row) if row is not None else None
        finally:
            db.close()

    def list_tasks(
        self,
        owner: Optional[str],
        *,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        tag: Optional[str] = None,
        context: Optional[str] = None,
        due_before: Any = None,
        include_completed: bool = False,
        query: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            q = db.query(WorkTask).filter(WorkTask.owner == owner_value)
            if status:
                q = q.filter(WorkTask.status == _enum(status, "status", TASK_STATUSES, "inbox"))
            elif not include_completed:
                q = q.filter(~WorkTask.status.in_(tuple(TASK_TERMINAL_STATUSES)))
            if project_id:
                q = q.filter(WorkTask.project_id == project_id)
            if parent_task_id:
                q = q.filter(WorkTask.parent_task_id == parent_task_id)
            if due_before:
                q = q.filter(WorkTask.due_at <= _parse_datetime(due_before, "due_before", allow_none=False))
            if query:
                needle = f"%{str(query).strip()}%"
                q = q.filter((WorkTask.title.ilike(needle)) | (WorkTask.description.ilike(needle)))
            rows = q.order_by(
                WorkTask.due_at.is_(None),
                WorkTask.due_at.asc(),
                WorkTask.created_at.desc(),
            ).limit(max(1, min(int(limit), 500))).all()
            out = [self._task_dict(db, row) for row in rows]
            if tag:
                marker = tag.casefold()
                out = [item for item in out if marker in {v.casefold() for v in item["tags"]}]
            if context:
                marker = context.casefold()
                out = [item for item in out if marker in {v.casefold() for v in item["contexts"]}]
            return out
        finally:
            db.close()

    def update_task(
        self,
        owner: Optional[str],
        task_id: str,
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            row = self._owned(db, WorkTask, task_id, owner_value)
            if row.legacy_read_only:
                raise WorkConflict("Legacy scheduled-task projections are read-only")
            if expected_revision is not None and row.revision != expected_revision:
                raise WorkConflict("Task revision changed; reload before updating")
            before = self._task_dict(db, row)
            values = self._task_values(
                db,
                owner_value,
                payload,
                task_id=task_id,
                existing=row,
                context=context,
            )
            for field, value in values.items():
                setattr(row, field, value)
            row.revision += 1
            if "dependency_ids" in payload:
                self._replace_dependencies(db, owner_value, task_id, payload.get("dependency_ids"))
            if "references" in payload:
                self._replace_references(
                    db,
                    owner=owner_value,
                    entity_type="task",
                    entity_id=task_id,
                    values=payload.get("references"),
                )
            if "reminders" in payload:
                self._replace_reminders(
                    db,
                    owner=owner_value,
                    entity_type="task",
                    entity_id=task_id,
                    values=payload.get("reminders"),
                )
            db.flush()
            after = self._task_dict(db, row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="task",
                entity_id=task_id,
                operation="update",
                context=context,
                before=before,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_task(
        self,
        owner: Optional[str],
        task_id: str,
        *,
        context: MutationContext,
        expected_revision: int,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="delete_work")
            row = self._owned(db, WorkTask, task_id, owner_value)
            if row.legacy_read_only:
                raise WorkConflict("Legacy scheduled-task projections are read-only")
            if row.revision != expected_revision:
                raise WorkConflict("Task revision changed; reload before deleting")
            before = self._task_dict(db, row)
            for model in (WorkReference, WorkReminder):
                db.query(model).filter(
                    model.owner == owner_value,
                    model.entity_type == "task",
                    model.entity_id == task_id,
                ).delete(synchronize_session=False)
            db.delete(row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="task",
                entity_id=task_id,
                operation="delete",
                context=context,
                before=before,
                after=None,
            )
            db.commit()
            return {"ok": True, "id": task_id}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _project_values(
        self,
        payload: Mapping[str, Any],
        *,
        existing: Optional[WorkProject],
        context: MutationContext,
    ) -> dict[str, Any]:
        def value(name: str, fallback: Any = None) -> Any:
            if name in payload:
                return payload[name]
            if existing is not None and name in {"risks", "decisions", "tags"}:
                column = {
                    "risks": existing.risks_json,
                    "decisions": existing.decisions_json,
                    "tags": existing.tags_json,
                }[name]
                return _json_load(column, [])
            return getattr(existing, name, fallback) if existing is not None else fallback

        existing_budget = (
            {
                "enabled": existing.budget_enabled,
                "currency": existing.budget_currency,
                "amount_minor": existing.budget_amount_minor,
                "spent_minor": existing.budget_spent_minor,
            }
            if existing is not None
            else {}
        )
        supplied_budget = payload.get("budget") if "budget" in payload else {}
        if supplied_budget is None:
            supplied_budget = {}
        if not isinstance(supplied_budget, Mapping):
            raise WorkValidationError("budget must be an object")
        budget = {**existing_budget, **dict(supplied_budget)}
        start_at = _parse_datetime(value("start_at"), "start_at")
        target_at = _parse_datetime(value("target_at"), "target_at")
        if start_at and target_at and start_at > target_at:
            raise WorkValidationError("project start_at cannot be after target_at")
        created_by = (
            existing.created_by
            if existing is not None
            else "agent" if context.actor_kind == "agent" else "user"
        )
        approval_state = (
            existing.approval_state
            if existing is not None
            else "approved" if context.actor_kind == "agent" else "not_required"
        )
        return {
            "title": _bounded_text(value("title"), "title", maximum=300, required=True),
            "goal": _bounded_text(value("goal"), "goal", maximum=20000),
            "desired_outcome": _bounded_text(value("desired_outcome"), "desired_outcome", maximum=20000),
            "status": _enum(value("status"), "status", PROJECT_STATUSES, "active"),
            "area": _bounded_text(value("area"), "area", maximum=200),
            "notes": _bounded_text(value("notes"), "notes", maximum=50000),
            "risks_json": _canonical_json(_dict_list(value("risks"), "risks")),
            "decisions_json": _canonical_json(_dict_list(value("decisions"), "decisions")),
            "tags_json": _canonical_json(_string_list(value("tags"), "tags")),
            "budget_enabled": bool(budget.get("enabled", False)),
            "budget_currency": _bounded_text(budget.get("currency"), "budget.currency", maximum=3).upper(),
            "budget_amount_minor": _bounded_int(
                budget.get("amount_minor"), "budget.amount_minor", minimum=0, maximum=10**15
            ),
            "budget_spent_minor": _bounded_int(
                budget.get("spent_minor"), "budget.spent_minor", minimum=0, maximum=10**15
            ),
            "start_at": start_at,
            "target_at": target_at,
            "progress_summary": _bounded_text(value("progress_summary"), "progress_summary", maximum=20000),
            "created_by": created_by,
            "approval_state": approval_state,
            "action_id": context.action_id or (existing.action_id if existing is not None else None),
        }

    def _replace_milestones(self, db, owner: str, project_id: str, values: Any) -> None:
        milestones = _dict_list(values, "milestones", maximum=100)
        existing = {
            row.id: row
            for row in db.query(WorkMilestone).filter(
                WorkMilestone.owner == owner,
                WorkMilestone.project_id == project_id,
            ).all()
        }
        keep: set[str] = set()
        for index, item in enumerate(milestones):
            milestone_id = str(item.get("id") or uuid.uuid4().hex)
            row = existing.get(milestone_id)
            if row is None:
                row = WorkMilestone(id=milestone_id, owner=owner, project_id=project_id)
                db.add(row)
            keep.add(milestone_id)
            row.title = _bounded_text(item.get("title"), "milestone.title", maximum=300, required=True)
            row.description = _bounded_text(item.get("description"), "milestone.description", maximum=10000)
            row.status = _enum(item.get("status"), "milestone.status", MILESTONE_STATUSES, "pending")
            row.target_at = _parse_datetime(item.get("target_at"), "milestone.target_at")
            row.completed_at = _parse_datetime(item.get("completed_at"), "milestone.completed_at")
            if row.status == "completed" and row.completed_at is None:
                row.completed_at = self._clock()
            row.sort_order = _bounded_int(
                item.get("sort_order", index), "milestone.sort_order", minimum=-100000, maximum=100000, allow_none=False
            )
            if row.id in existing:
                row.revision += 1
        for milestone_id, row in existing.items():
            if milestone_id not in keep:
                db.delete(row)

    def create_project(
        self,
        owner: Optional[str],
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            project_id = uuid.uuid4().hex
            row = WorkProject(
                id=project_id,
                owner=owner_value,
                **self._project_values(payload, existing=None, context=context),
            )
            db.add(row)
            db.flush()
            if "milestones" in payload:
                self._replace_milestones(db, owner_value, project_id, payload.get("milestones"))
            if "references" in payload:
                self._replace_references(
                    db,
                    owner=owner_value,
                    entity_type="project",
                    entity_id=project_id,
                    values=payload.get("references"),
                )
            db.flush()
            after = self._project_dict(db, row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="project",
                entity_id=project_id,
                operation="create",
                context=context,
                before=None,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_project(self, owner: Optional[str], project_id: str) -> dict[str, Any]:
        db = self._session_factory()
        try:
            return self._project_dict(
                db, self._owned(db, WorkProject, project_id, _owner_key(owner))
            )
        finally:
            db.close()

    def list_projects(
        self,
        owner: Optional[str],
        *,
        status: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            q = db.query(WorkProject).filter(WorkProject.owner == owner_value)
            if status:
                q = q.filter(WorkProject.status == _enum(status, "status", PROJECT_STATUSES, "active"))
            elif not include_archived:
                q = q.filter(WorkProject.status != "archived")
            rows = q.order_by(
                WorkProject.target_at.is_(None),
                WorkProject.target_at.asc(),
                WorkProject.created_at.desc(),
            ).limit(max(1, min(int(limit), 500))).all()
            return [self._project_dict(db, row) for row in rows]
        finally:
            db.close()

    def update_project(
        self,
        owner: Optional[str],
        project_id: str,
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            row = self._owned(db, WorkProject, project_id, owner_value)
            if expected_revision is not None and row.revision != expected_revision:
                raise WorkConflict("Project revision changed; reload before updating")
            before = self._project_dict(db, row)
            for field, value in self._project_values(
                payload, existing=row, context=context
            ).items():
                setattr(row, field, value)
            row.revision += 1
            if "milestones" in payload:
                self._replace_milestones(db, owner_value, project_id, payload.get("milestones"))
            if "references" in payload:
                self._replace_references(
                    db,
                    owner=owner_value,
                    entity_type="project",
                    entity_id=project_id,
                    values=payload.get("references"),
                )
            db.flush()
            after = self._project_dict(db, row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="project",
                entity_id=project_id,
                operation="update",
                context=context,
                before=before,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_project(
        self,
        owner: Optional[str],
        project_id: str,
        *,
        context: MutationContext,
        expected_revision: int,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="delete_work")
            row = self._owned(db, WorkProject, project_id, owner_value)
            if row.revision != expected_revision:
                raise WorkConflict("Project revision changed; reload before deleting")
            before = self._project_dict(db, row)
            db.query(WorkReference).filter(
                WorkReference.owner == owner_value,
                WorkReference.entity_type == "project",
                WorkReference.entity_id == project_id,
            ).delete(synchronize_session=False)
            db.delete(row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="project",
                entity_id=project_id,
                operation="delete",
                context=context,
                before=before,
                after=None,
            )
            db.commit()
            return {"ok": True, "id": project_id}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _commitment_values(
        self,
        db,
        owner: str,
        payload: Mapping[str, Any],
        *,
        existing: Optional[WorkCommitment],
        context: MutationContext,
    ) -> dict[str, Any]:
        def value(name: str, fallback: Any = None) -> Any:
            if name in payload:
                return payload[name]
            return getattr(existing, name, fallback) if existing is not None else fallback

        project_id = value("project_id")
        task_id = value("task_id")
        if project_id:
            self._owned(db, WorkProject, project_id, owner)
        if task_id:
            task = self._owned(db, WorkTask, task_id, owner)
            if project_id and task.project_id and task.project_id != project_id:
                raise WorkValidationError("Commitment task belongs to a different project")
        status = _enum(value("status"), "status", COMMITMENT_STATUSES, "open")
        review_default = "suggested" if context.actor_kind == "agent" else "approved"
        fulfilled_at = _parse_datetime(value("fulfilled_at"), "fulfilled_at")
        if status == "fulfilled" and fulfilled_at is None:
            fulfilled_at = self._clock()
        if status != "fulfilled" and "status" in payload and "fulfilled_at" not in payload:
            fulfilled_at = None
        source_type = _bounded_text(value("source_type"), "source_type", maximum=100, required=True)
        return {
            "title": _bounded_text(value("title"), "title", maximum=500, required=True),
            "description": _bounded_text(value("description"), "description", maximum=20000),
            "status": status,
            "review_state": _enum(
                value("review_state"),
                "review_state",
                COMMITMENT_REVIEW_STATES,
                review_default,
            ),
            "due_at": _parse_datetime(value("due_at"), "due_at"),
            "fulfilled_at": fulfilled_at,
            "counterparty": _bounded_text(value("counterparty"), "counterparty", maximum=500),
            "project_id": project_id or None,
            "task_id": task_id or None,
            "source_type": source_type,
            "source_id": _bounded_text(value("source_id"), "source_id", maximum=500),
            "source_url": _bounded_text(value("source_url"), "source_url", maximum=4000),
            "source_excerpt": _bounded_text(value("source_excerpt"), "source_excerpt", maximum=10000),
            "source_occurred_at": _parse_datetime(value("source_occurred_at"), "source_occurred_at"),
            "confidence": _bounded_int(value("confidence"), "confidence", minimum=0, maximum=100),
            "created_by": (
                existing.created_by
                if existing is not None
                else "agent" if context.actor_kind == "agent" else "user"
            ),
            "action_id": context.action_id or (existing.action_id if existing is not None else None),
            "completion_notes": _bounded_text(value("completion_notes"), "completion_notes", maximum=20000),
        }

    def create_commitment(
        self,
        owner: Optional[str],
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            commitment_id = uuid.uuid4().hex
            row = WorkCommitment(
                id=commitment_id,
                owner=owner_value,
                **self._commitment_values(
                    db, owner_value, payload, existing=None, context=context
                ),
            )
            db.add(row)
            db.flush()
            if "references" in payload:
                self._replace_references(
                    db,
                    owner=owner_value,
                    entity_type="commitment",
                    entity_id=commitment_id,
                    values=payload.get("references"),
                )
            if "reminders" in payload:
                self._replace_reminders(
                    db,
                    owner=owner_value,
                    entity_type="commitment",
                    entity_id=commitment_id,
                    values=payload.get("reminders"),
                )
            db.flush()
            after = self._commitment_dict(db, row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="commitment",
                entity_id=commitment_id,
                operation="create",
                context=context,
                before=None,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_commitment(self, owner: Optional[str], commitment_id: str) -> dict[str, Any]:
        db = self._session_factory()
        try:
            return self._commitment_dict(
                db, self._owned(db, WorkCommitment, commitment_id, _owner_key(owner))
            )
        finally:
            db.close()

    def list_commitments(
        self,
        owner: Optional[str],
        *,
        status: Optional[str] = None,
        review_state: Optional[str] = None,
        due_before: Any = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            q = db.query(WorkCommitment).filter(WorkCommitment.owner == owner_value)
            if status:
                q = q.filter(
                    WorkCommitment.status
                    == _enum(status, "status", COMMITMENT_STATUSES, "open")
                )
            if review_state:
                q = q.filter(
                    WorkCommitment.review_state
                    == _enum(
                        review_state,
                        "review_state",
                        COMMITMENT_REVIEW_STATES,
                        "suggested",
                    )
                )
            if due_before:
                q = q.filter(
                    WorkCommitment.due_at
                    <= _parse_datetime(due_before, "due_before", allow_none=False)
                )
            rows = q.order_by(
                WorkCommitment.due_at.is_(None),
                WorkCommitment.due_at.asc(),
                WorkCommitment.created_at.desc(),
            ).limit(max(1, min(int(limit), 500))).all()
            return [self._commitment_dict(db, row) for row in rows]
        finally:
            db.close()

    def update_commitment(
        self,
        owner: Optional[str],
        commitment_id: str,
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
        expected_revision: Optional[int] = None,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            row = self._owned(db, WorkCommitment, commitment_id, owner_value)
            if expected_revision is not None and row.revision != expected_revision:
                raise WorkConflict("Commitment revision changed; reload before updating")
            if "review_state" in payload:
                transition = (row.review_state, str(payload["review_state"]).lower())
                allowed = {
                    ("suggested", "approved"),
                    ("suggested", "rejected"),
                    ("suggested", "expired"),
                    ("approved", "approved"),
                    ("rejected", "rejected"),
                    ("expired", "expired"),
                }
                if transition not in allowed:
                    raise WorkConflict(
                        f"Commitment review cannot transition from {transition[0]} to {transition[1]}"
                    )
            before = self._commitment_dict(db, row)
            for field, value in self._commitment_values(
                db, owner_value, payload, existing=row, context=context
            ).items():
                setattr(row, field, value)
            row.revision += 1
            if "references" in payload:
                self._replace_references(
                    db,
                    owner=owner_value,
                    entity_type="commitment",
                    entity_id=commitment_id,
                    values=payload.get("references"),
                )
            if "reminders" in payload:
                self._replace_reminders(
                    db,
                    owner=owner_value,
                    entity_type="commitment",
                    entity_id=commitment_id,
                    values=payload.get("reminders"),
                )
            db.flush()
            after = self._commitment_dict(db, row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="commitment",
                entity_id=commitment_id,
                operation="update",
                context=context,
                before=before,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_commitment(
        self,
        owner: Optional[str],
        commitment_id: str,
        *,
        context: MutationContext,
        expected_revision: int,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="delete_work")
            row = self._owned(db, WorkCommitment, commitment_id, owner_value)
            if row.revision != expected_revision:
                raise WorkConflict("Commitment revision changed; reload before deleting")
            before = self._commitment_dict(db, row)
            for model in (WorkReference, WorkReminder):
                db.query(model).filter(
                    model.owner == owner_value,
                    model.entity_type == "commitment",
                    model.entity_id == commitment_id,
                ).delete(synchronize_session=False)
            db.delete(row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="commitment",
                entity_id=commitment_id,
                operation="delete",
                context=context,
                before=before,
                after=None,
            )
            db.commit()
            return {"ok": True, "id": commitment_id}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def blocked_tasks(self, owner: Optional[str]) -> list[dict[str, Any]]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            active = db.query(WorkTask).filter(
                WorkTask.owner == owner_value,
                ~WorkTask.status.in_(tuple(TASK_TERMINAL_STATUSES)),
            ).all()
            out = []
            for task in active:
                dependencies = db.query(WorkTask).join(
                    WorkTaskDependency,
                    WorkTask.id == WorkTaskDependency.depends_on_task_id,
                ).filter(
                    WorkTaskDependency.owner == owner_value,
                    WorkTaskDependency.task_id == task.id,
                    WorkTask.status != "completed",
                ).all()
                if dependencies:
                    item = self._task_dict(db, task)
                    item["blocked_by"] = [
                        {"id": dep.id, "title": dep.title, "status": dep.status}
                        for dep in dependencies
                    ]
                    out.append(item)
            return out
        finally:
            db.close()

    def overdue_commitments(
        self,
        owner: Optional[str],
        *,
        as_of: Any = None,
    ) -> list[dict[str, Any]]:
        cutoff = _parse_datetime(as_of, "as_of") if as_of else self._clock()
        db = self._session_factory()
        try:
            rows = db.query(WorkCommitment).filter(
                WorkCommitment.owner == _owner_key(owner),
                WorkCommitment.status == "open",
                WorkCommitment.review_state.in_(("approved", "suggested")),
                WorkCommitment.due_at.isnot(None),
                WorkCommitment.due_at < cutoff,
            ).order_by(WorkCommitment.due_at.asc()).all()
            return [self._commitment_dict(db, row) for row in rows]
        finally:
            db.close()

    def daily_focus(
        self,
        owner: Optional[str],
        *,
        plan_date: Any = None,
        available_minutes: int = 480,
        energy: Optional[str] = None,
        contexts: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        day = _parse_datetime(plan_date, "plan_date") if plan_date else self._clock()
        day_start = datetime.combine(day.date(), time.min)
        day_end = day_start + timedelta(days=1)
        available = _bounded_int(
            available_minutes,
            "available_minutes",
            minimum=15,
            maximum=1440,
            allow_none=False,
        )
        wanted_energy = None
        if energy:
            wanted_energy = _enum(energy, "energy", ENERGY_LEVELS, "medium")
        wanted_contexts = {value.casefold() for value in _string_list(contexts, "contexts")}
        blocked_ids = {item["id"] for item in self.blocked_tasks(owner)}
        db = self._session_factory()
        try:
            rows = db.query(WorkTask).filter(
                WorkTask.owner == _owner_key(owner),
                ~WorkTask.status.in_(tuple(TASK_TERMINAL_STATUSES)),
                (WorkTask.start_at.is_(None)) | (WorkTask.start_at < day_end),
            ).all()
            priority_score = {"urgent": 50, "high": 35, "normal": 20, "low": 10, "none": 0}
            ranked = []
            for row in rows:
                if row.id in blocked_ids:
                    continue
                row_contexts = {v.casefold() for v in _json_load(row.contexts_json, [])}
                if wanted_contexts and row_contexts and not (wanted_contexts & row_contexts):
                    continue
                score = priority_score.get(row.priority, 0)
                reasons = [f"{row.priority} priority"]
                if row.status == "in_progress":
                    score += 30
                    reasons.append("already in progress")
                if row.due_at:
                    if row.due_at < day_start:
                        score += 60
                        reasons.append("overdue")
                    elif row.due_at < day_end:
                        score += 45
                        reasons.append("due today")
                    elif row.due_at < day_end + timedelta(days=3):
                        score += 20
                        reasons.append("due soon")
                if wanted_energy and row.energy == wanted_energy:
                    score += 12
                    reasons.append("energy match")
                ranked.append((score, row, reasons))
            ranked.sort(
                key=lambda item: (
                    -item[0],
                    item[1].due_at is None,
                    item[1].due_at or datetime.max,
                    item[1].created_at,
                )
            )
            selected = []
            used = 0
            for score, row, reasons in ranked:
                duration = row.estimated_minutes or 30
                if selected and used + duration > available:
                    continue
                used += duration
                task = self._task_dict(db, row)
                task["planning"] = {
                    "score": score,
                    "reasons": reasons,
                    "scheduled_minutes": duration,
                }
                selected.append(task)
                if used >= available:
                    break
            return {
                "date": day_start.date().isoformat(),
                "available_minutes": available,
                "scheduled_minutes": used,
                "remaining_minutes": max(0, available - used),
                "tasks": selected,
            }
        finally:
            db.close()

    def create_plan(
        self,
        owner: Optional[str],
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            plan_type = _enum(payload.get("plan_type"), "plan_type", PLAN_TYPES, "focus")
            plan_date = _parse_datetime(payload.get("plan_date"), "plan_date") or self._clock()
            goal = _bounded_text(payload.get("goal"), "goal", maximum=20000)
            proposals: list[dict[str, Any]] = []
            blocks: list[dict[str, Any]] = []
            assumptions: list[Any] = []
            if plan_type == "focus":
                focus = self.daily_focus(
                    owner,
                    plan_date=plan_date,
                    available_minutes=payload.get("available_minutes", 480),
                    energy=payload.get("energy"),
                    contexts=payload.get("contexts"),
                )
                try:
                    start_time = time.fromisoformat(str(payload.get("start_time") or "09:00"))
                except ValueError as exc:
                    raise WorkValidationError("start_time must be an ISO local time") from exc
                cursor = datetime.combine(plan_date.date(), start_time)
                for item in focus["tasks"]:
                    duration = item["planning"]["scheduled_minutes"]
                    block_end = cursor + timedelta(minutes=duration)
                    proposals.append({"task_id": item["id"], "title": item["title"]})
                    blocks.append(
                        {
                            "task_id": item["id"],
                            "title": item["title"],
                            "start_at": _iso(cursor),
                            "end_at": _iso(block_end),
                            "minutes": duration,
                        }
                    )
                    cursor = block_end
                assumptions.append("Work blocks are local planning suggestions; no calendar event was created.")
            elif plan_type == "breakdown":
                if not goal:
                    raise WorkValidationError("goal is required for a breakdown plan")
                provided = payload.get("steps")
                if provided:
                    steps = _dict_list(provided, "steps", maximum=100)
                else:
                    short_goal = goal.rstrip(". ")
                    steps = [
                        {"title": f"Define the outcome for {short_goal}", "estimated_minutes": 30},
                        {"title": f"Gather inputs for {short_goal}", "estimated_minutes": 60},
                        {"title": f"Complete {short_goal}", "estimated_minutes": 120},
                        {"title": f"Review and close {short_goal}", "estimated_minutes": 30},
                    ]
                    assumptions.append("Generic breakdown generated locally; edit steps before applying.")
                for index, step in enumerate(steps):
                    proposals.append(
                        {
                            "title": _bounded_text(step.get("title"), "step.title", maximum=300, required=True),
                            "description": _bounded_text(step.get("description"), "step.description", maximum=10000),
                            "estimated_minutes": _bounded_int(
                                step.get("estimated_minutes", 30),
                                "step.estimated_minutes",
                                minimum=1,
                                maximum=525600,
                                allow_none=False,
                            ),
                            "priority": _enum(step.get("priority"), "step.priority", TASK_PRIORITIES, "normal"),
                            "sort_order": index,
                        }
                    )
            else:
                task_ids = _string_list(payload.get("task_ids"), "task_ids", maximum=100)
                if not task_ids:
                    raise WorkValidationError("task_ids are required for a reschedule plan")
                cursor_date = plan_date
                for task_id in task_ids:
                    task = self._owned(db, WorkTask, task_id, owner_value)
                    if task.status in TASK_TERMINAL_STATUSES:
                        continue
                    proposals.append(
                        {
                            "task_id": task.id,
                            "title": task.title,
                            "previous_due_at": _iso(task.due_at),
                            "due_at": _iso(cursor_date),
                        }
                    )
                    cursor_date += timedelta(days=1)
                assumptions.append("Due-date changes remain a draft until explicitly applied.")
            row = WorkPlan(
                id=uuid.uuid4().hex,
                owner=owner_value,
                plan_type=plan_type,
                title=_bounded_text(
                    payload.get("title") or f"{plan_type.title()} plan",
                    "title",
                    maximum=300,
                    required=True,
                ),
                goal=goal,
                plan_date=plan_date,
                status="draft",
                proposals_json=_canonical_json(proposals),
                work_blocks_json=_canonical_json(blocks),
                assumptions_json=_canonical_json(assumptions),
                created_by="agent" if context.actor_kind == "agent" else "user",
                action_id=context.action_id,
            )
            db.add(row)
            db.flush()
            after = self._plan_dict(row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="plan",
                entity_id=row.id,
                operation="create",
                context=context,
                before=None,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_plan(self, owner: Optional[str], plan_id: str) -> dict[str, Any]:
        db = self._session_factory()
        try:
            return self._plan_dict(self._owned(db, WorkPlan, plan_id, _owner_key(owner)))
        finally:
            db.close()

    def update_plan(
        self,
        owner: Optional[str],
        plan_id: str,
        payload: Mapping[str, Any],
        *,
        context: MutationContext,
        expected_revision: int,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            row = self._owned(db, WorkPlan, plan_id, owner_value)
            if row.revision != expected_revision:
                raise WorkConflict("Plan revision changed; reload before updating")
            if row.status != "draft":
                raise WorkConflict("Only draft plans can be edited")
            before = self._plan_dict(row)
            if "title" in payload:
                row.title = _bounded_text(payload["title"], "title", maximum=300, required=True)
            if "goal" in payload:
                row.goal = _bounded_text(payload["goal"], "goal", maximum=20000)
            if "proposals" in payload:
                row.proposals_json = _canonical_json(_dict_list(payload["proposals"], "proposals", maximum=100))
            if "work_blocks" in payload:
                row.work_blocks_json = _canonical_json(_dict_list(payload["work_blocks"], "work_blocks", maximum=100))
            if "status" in payload:
                status = _enum(payload["status"], "status", PLAN_STATUSES, "draft")
                if status not in {"draft", "accepted", "rejected"}:
                    raise WorkValidationError("Use the apply endpoint to mark a plan applied")
                row.status = status
            row.revision += 1
            db.flush()
            after = self._plan_dict(row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="plan",
                entity_id=plan_id,
                operation="update",
                context=context,
                before=before,
                after=after,
            )
            db.commit()
            return after
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def apply_plan(
        self,
        owner: Optional[str],
        plan_id: str,
        *,
        context: MutationContext,
        expected_revision: int,
    ) -> dict[str, Any]:
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            self._authorize_mutation(db, owner_value, context, expected_tool="manage_work")
            row = self._owned(db, WorkPlan, plan_id, owner_value)
            if row.revision != expected_revision:
                raise WorkConflict("Plan revision changed; reload before applying")
            if row.status not in {"draft", "accepted"}:
                raise WorkConflict("Plan is not available to apply")
            before = self._plan_dict(row)
            proposals = _json_load(row.proposals_json, [])
            affected: list[dict[str, Any]] = []
            if row.plan_type == "breakdown":
                for proposal in proposals:
                    task_payload = {
                        "title": proposal.get("title"),
                        "description": proposal.get("description", ""),
                        "estimated_minutes": proposal.get("estimated_minutes", 30),
                        "priority": proposal.get("priority", "normal"),
                        "status": "planned",
                        "sort_order": proposal.get("sort_order", 0),
                        "source_type": "work_plan",
                        "source_id": row.id,
                    }
                    task_id = uuid.uuid4().hex
                    task = WorkTask(
                        id=task_id,
                        owner=owner_value,
                        **self._task_values(
                            db,
                            owner_value,
                            task_payload,
                            task_id=task_id,
                            context=context,
                        ),
                    )
                    db.add(task)
                    db.flush()
                    task_data = self._task_dict(db, task)
                    affected.append(task_data)
                    self._receipt(
                        db,
                        owner=owner_value,
                        entity_type="task",
                        entity_id=task_id,
                        operation="create_from_plan",
                        context=context,
                        before=None,
                        after=task_data,
                        details={"plan_id": row.id},
                    )
            elif row.plan_type == "reschedule":
                for proposal in proposals:
                    task = self._owned(db, WorkTask, str(proposal.get("task_id") or ""), owner_value)
                    if task.legacy_read_only:
                        raise WorkConflict("Legacy scheduled-task projections cannot be rescheduled")
                    task_before = self._task_dict(db, task)
                    task.due_at = _parse_datetime(proposal.get("due_at"), "proposal.due_at", allow_none=False)
                    task.revision += 1
                    task_after = self._task_dict(db, task)
                    affected.append(task_after)
                    self._receipt(
                        db,
                        owner=owner_value,
                        entity_type="task",
                        entity_id=task.id,
                        operation="reschedule_from_plan",
                        context=context,
                        before=task_before,
                        after=task_after,
                        details={"plan_id": row.id},
                    )
            else:
                # Focus plans persist local work blocks only. Applying confirms
                # the corrected plan but does not create calendar side effects.
                affected = list(proposals)
            row.status = "applied"
            row.applied_at = self._clock()
            row.revision += 1
            db.flush()
            after = self._plan_dict(row)
            self._receipt(
                db,
                owner=owner_value,
                entity_type="plan",
                entity_id=row.id,
                operation="apply",
                context=context,
                before=before,
                after=after,
                details={"affected_count": len(affected)},
            )
            db.commit()
            return {"plan": after, "affected": affected}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def list_receipts(
        self,
        owner: Optional[str],
        *,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        db = self._session_factory()
        try:
            q = db.query(WorkMutationReceipt).filter(
                WorkMutationReceipt.owner == _owner_key(owner)
            )
            if entity_type:
                q = q.filter(WorkMutationReceipt.entity_type == entity_type)
            if entity_id:
                q = q.filter(WorkMutationReceipt.entity_id == entity_id)
            rows = q.order_by(WorkMutationReceipt.occurred_at.desc()).limit(
                max(1, min(int(limit), 500))
            ).all()
            return [
                {
                    "id": row.id,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "operation": row.operation,
                    "actor_kind": row.actor_kind,
                    "actor_id": row.actor_id,
                    "action_id": row.action_id,
                    "correlation_id": row.correlation_id,
                    "before_hash": row.before_hash,
                    "after_hash": row.after_hash,
                    "details": _json_load(row.details_json, {}),
                    "occurred_at": _iso(row.occurred_at),
                }
                for row in rows
            ]
        finally:
            db.close()

    def pending_reminders(
        self,
        owner: Optional[str],
        *,
        due_before: Any = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        cutoff = _parse_datetime(due_before, "due_before") if due_before else self._clock()
        db = self._session_factory()
        try:
            rows = db.query(WorkReminder).filter(
                WorkReminder.owner == _owner_key(owner),
                WorkReminder.status == "pending",
                WorkReminder.remind_at <= cutoff,
            ).order_by(WorkReminder.remind_at.asc()).limit(
                max(1, min(int(limit), 500))
            ).all()
            return [
                {
                    "id": row.id,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "remind_at": _iso(row.remind_at),
                    "message": row.message,
                    "channel": row.channel,
                    "recurrence": _json_load(row.recurrence_rule_json, {}),
                }
                for row in rows
            ]
        finally:
            db.close()

    def operating_metrics(
        self,
        owner: Optional[str],
        *,
        since: Any,
    ) -> dict[str, Any]:
        """Return conservative attention-returned evidence for one owner."""

        start = _parse_datetime(since, "since", allow_none=False)
        owner_value = _owner_key(owner)
        db = self._session_factory()
        try:
            tasks = db.query(WorkTask).filter(
                WorkTask.owner == owner_value,
                WorkTask.status == "completed",
                WorkTask.completed_at.isnot(None),
                WorkTask.completed_at >= start,
            ).all()
            commitments = db.query(WorkCommitment).filter(
                WorkCommitment.owner == owner_value,
                WorkCommitment.status == "fulfilled",
                WorkCommitment.fulfilled_at.isnot(None),
                WorkCommitment.fulfilled_at >= start,
            ).count()
            estimated_minutes = sum(
                max(0, int(task.actual_minutes or task.estimated_minutes or 0))
                for task in tasks
            )
            return {
                "completed_tasks": len(tasks),
                "fulfilled_commitments": commitments,
                "attention_returned_items": len(tasks) + commitments,
                "attention_returned_minutes": estimated_minutes,
                "minutes_are_estimated": any(
                    task.actual_minutes is None and task.estimated_minutes is not None
                    for task in tasks
                ),
            }
        finally:
            db.close()

    def backfill_legacy_scheduled_tasks(self) -> dict[str, int]:
        """Idempotently project legacy automations without changing them."""

        if not sqlalchemy_inspect(self._bind).has_table("scheduled_tasks"):
            return {"created": 0, "updated": 0}
        db = self._session_factory()
        created = 0
        updated = 0
        try:
            for legacy in db.query(ScheduledTask).all():
                owner = _owner_key(legacy.owner)
                row = db.query(WorkTask).filter(
                    WorkTask.legacy_scheduled_task_id == legacy.id
                ).first()
                status = {
                    "active": "scheduled",
                    "paused": "on_hold",
                    "completed": "completed",
                }.get(str(legacy.status or "").lower(), "scheduled")
                recurrence = {}
                if legacy.schedule and legacy.schedule != "once":
                    recurrence = {
                        "frequency": legacy.schedule
                        if legacy.schedule in RECURRENCE_FREQUENCIES
                        else "custom",
                        "interval": 1,
                    }
                    if recurrence["frequency"] == "custom":
                        recurrence["rule"] = legacy.cron_expression or legacy.schedule
                values = {
                    "owner": owner,
                    "title": legacy.name or "Untitled automation",
                    "description": legacy.prompt or "",
                    "status": status,
                    "priority": "normal",
                    "due_at": legacy.scheduled_date or legacy.next_run,
                    "recurrence_rule_json": _canonical_json(recurrence),
                    "source_type": "scheduled_task",
                    "source_id": legacy.id,
                    "created_by": "migration",
                    "approval_state": "migrated",
                    "legacy_scheduled_task_id": legacy.id,
                    "legacy_read_only": True,
                }
                if row is None:
                    row = WorkTask(id=uuid.uuid4().hex, **values)
                    db.add(row)
                    db.flush()
                    self._receipt(
                        db,
                        owner=owner,
                        entity_type="task",
                        entity_id=row.id,
                        operation="legacy_backfill",
                        context=MutationContext(actor_kind="migration", actor_id=owner),
                        before=None,
                        after=self._task_dict(db, row),
                        details={"legacy_scheduled_task_id": legacy.id},
                    )
                    created += 1
                else:
                    changed = any(getattr(row, key) != value for key, value in values.items())
                    if changed:
                        for key, value in values.items():
                            setattr(row, key, value)
                        row.revision += 1
                        updated += 1
            db.commit()
            return {"created": created, "updated": updated}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


_default_work_service: Optional[WorkService] = None


def get_work_service() -> WorkService:
    """Return the process service used by routes and canonical tool handlers."""

    global _default_work_service
    if _default_work_service is None:
        _default_work_service = WorkService()
    return _default_work_service
