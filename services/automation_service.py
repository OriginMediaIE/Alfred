"""Validated automation engine with bounded execution and durable history."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
import hashlib, hmac, json, os, re, secrets, uuid
from pathlib import Path
from typing import Any, Optional
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from services.executive_service import get_executive_service
from services.knowledge_service import get_knowledge_service
from src.automation_models import AutomationDeadLetter, AutomationDefinition, AutomationEvent, AutomationRun, ensure_automation_schema
from src.constants import DATA_DIR
from src.work_service import MutationContext, get_work_service
from src.secret_storage import decrypt, encrypt

TRIGGERS = frozenset({"scheduled_time", "new_email", "calendar_before_event", "task_due", "meeting_completed", "file_added", "integration_event", "manual", "webhook", "recurring_interval", "conditional_polling"})
ACTIONS = frozenset({"generate_briefing", "create_task", "draft_email", "add_reminder", "query_knowledge", "run_research", "notify_user", "call_integration", "request_approval", "start_agent_workflow", "create_backup"})
OPERATORS = frozenset({"equals", "not_equals", "greater_than", "less_than", "contains", "exists"})
MAX_STEPS = 25; MAX_DEPTH = 3; MAX_DEFINITION_BYTES = 256_000

ROUTINE_TEMPLATES = {
    "renewals": {"name": "Renewals review", "description": "Review indexed renewal and expiry evidence each day.", "interval": 86400, "minutes": 10, "actions": [{"type": "query_knowledge", "parameters": {"query": "renewal expiry valid until due date", "limit": 12}}]},
    "follow-ups": {"name": "Follow-up review", "description": "Surface source-backed follow-ups and commitments each day.", "interval": 86400, "minutes": 10, "actions": [{"type": "query_knowledge", "parameters": {"query": "follow up commitment action required", "limit": 12}}]},
    "weekly-review": {"name": "Weekly review", "description": "Generate a source-backed weekly operating review.", "interval": 604800, "minutes": 20, "actions": [{"type": "generate_briefing", "parameters": {"kind": "weekly"}}]},
    "inbox-triage": {"name": "Inbox triage", "description": "Create a durable prompt to review the inbox without sending messages.", "interval": 14400, "minutes": 8, "actions": [{"type": "notify_user", "parameters": {"title": "Inbox triage", "message": "Review messages requiring attention and prepare drafts only."}}]},
    "backup-reminder": {"name": "Backup reminder", "description": "Record a weekly reminder to create and verify an encrypted backup.", "interval": 604800, "minutes": 5, "actions": [{"type": "notify_user", "parameters": {"title": "PrivateOS backup", "message": "Create and verify an encrypted PrivateOS backup."}}]},
    "meeting-follow-up": {"name": "Meeting follow-up", "description": "Review source-linked meeting decisions and actions after a meeting completes.", "event": "meeting_completed", "minutes": 12, "actions": [{"type": "query_knowledge", "parameters": {"query": "meeting decision action item follow up", "limit": 12}}]},
}


class AutomationError(RuntimeError): code = "automation_error"
class AutomationNotFound(AutomationError): code = "automation_not_found"
class AutomationConflict(AutomationError): code = "automation_conflict"
class AutomationValidationError(AutomationError): code = "invalid_automation_definition"
class AutomationRateLimited(AutomationError): code = "automation_rate_limited"
class AutomationLoopDetected(AutomationError): code = "automation_loop_detected"
class AutomationStateError(AutomationError): code = "automation_state_error"


def _owner(value): return str(value or "__local__")
def _now(): return datetime.now(timezone.utc)
def _iso(value):
    if not value: return None
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
def _aware(value):
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def _json(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _field(payload: Mapping[str, Any], path: str):
    value: Any = payload
    for part in str(path).split("."):
        if not isinstance(value, Mapping) or part not in value: return None
        value = value[part]
    return value


def _condition(condition, payload):
    actual = _field(payload, condition["field"]); expected = condition.get("value"); op = condition["operator"]
    if op == "exists": return actual is not None
    if op == "equals": return actual == expected
    if op == "not_equals": return actual != expected
    if op == "contains": return expected in actual if isinstance(actual, (str, list, tuple, set, dict)) else False
    try:
        if op == "greater_than": return actual > expected
        if op == "less_than": return actual < expected
    except TypeError: return False
    return False


def _validate_action_parameters(kind: str, parameters: Mapping[str, Any]) -> None:
    """Reject definitions that cannot ever execute successfully."""

    required = {
        "create_task": ("title",),
        "draft_email": ("to", "subject", "body"),
        "add_reminder": ("remind_at",),
        "query_knowledge": ("query",),
        "notify_user": ("message",),
        "call_integration": ("integration_id", "action"),
        "start_agent_workflow": ("automation_id",),
    }.get(kind, ())
    missing = [name for name in required if parameters.get(name) in (None, "")]
    if missing:
        raise AutomationValidationError(
            f"{kind} requires parameter(s): {', '.join(missing)}"
        )
    if kind == "generate_briefing" and parameters.get("kind", "morning") not in {"morning", "evening", "weekly"}:
        raise AutomationValidationError("generate_briefing kind is invalid")
    if kind == "run_research" and not (parameters.get("topic") or parameters.get("query")):
        raise AutomationValidationError("run_research requires topic or query")
    if kind == "call_integration" and not isinstance(parameters.get("parameters", {}), Mapping):
        raise AutomationValidationError("call_integration parameters must be an object")


def validate_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise AutomationValidationError("Automation definition must be an object")
    unknown = set(value) - {"name", "trigger", "conditions", "actions", "limits", "description", "routine_key", "estimated_minutes_saved"}
    if unknown: raise AutomationValidationError(f"Unknown definition fields: {', '.join(sorted(unknown))}")
    name = str(value.get("name") or "").strip()
    if not name or len(name) > 300: raise AutomationValidationError("name is required and must be at most 300 characters")
    trigger = value.get("trigger")
    if not isinstance(trigger, Mapping) or trigger.get("type") not in TRIGGERS: raise AutomationValidationError("trigger.type is invalid")
    trigger = dict(trigger); allowed_trigger = {"type", "at", "timezone", "minutes_before", "interval_seconds", "poll_seconds", "event", "signature_required"}
    if set(trigger) - allowed_trigger: raise AutomationValidationError("trigger has unknown fields")
    if trigger["type"] == "recurring_interval" and not 60 <= int(trigger.get("interval_seconds", 0)) <= 31_536_000: raise AutomationValidationError("interval_seconds must be 60-31536000")
    if trigger["type"] == "conditional_polling" and not 60 <= int(trigger.get("poll_seconds", 0)) <= 86400: raise AutomationValidationError("poll_seconds must be 60-86400")
    if trigger["type"] == "calendar_before_event" and not 1 <= int(trigger.get("minutes_before", 0)) <= 10080: raise AutomationValidationError("minutes_before must be 1-10080")
    if trigger["type"] == "scheduled_time":
        try: datetime.fromisoformat(str(trigger.get("at") or "").replace("Z", "+00:00"))
        except ValueError as exc: raise AutomationValidationError("scheduled_time trigger requires an ISO 'at' datetime") from exc
    conditions = value.get("conditions") or []
    if not isinstance(conditions, list) or len(conditions) > 25: raise AutomationValidationError("conditions must be a list of at most 25")
    normalized_conditions = []
    for item in conditions:
        if not isinstance(item, Mapping) or set(item) - {"field", "operator", "value"} or item.get("operator") not in OPERATORS or not re.fullmatch(r"[A-Za-z0-9_.]{1,200}", str(item.get("field") or "")): raise AutomationValidationError("condition is invalid")
        normalized_conditions.append(dict(item))
    actions = value.get("actions") or []
    if not isinstance(actions, list) or not actions or len(actions) > MAX_STEPS: raise AutomationValidationError(f"actions must contain 1-{MAX_STEPS} items")
    normalized_actions = []
    for item in actions:
        if not isinstance(item, Mapping) or set(item) - {"type", "parameters", "continue_on_error"} or item.get("type") not in ACTIONS or not isinstance(item.get("parameters", {}), Mapping): raise AutomationValidationError("action is invalid")
        parameters=dict(item.get("parameters", {}));_validate_action_parameters(item["type"],parameters)
        normalized_actions.append({"type": item["type"], "parameters": parameters, "continue_on_error": bool(item.get("continue_on_error", False))})
    limits = dict(value.get("limits") or {}); allowed_limits = {"max_steps", "max_runs_per_hour", "cooldown_seconds", "disable_after_failures"}
    if set(limits) - allowed_limits: raise AutomationValidationError("limits has unknown fields")
    limits = {"max_steps": min(MAX_STEPS, max(1, int(limits.get("max_steps", MAX_STEPS)))), "max_runs_per_hour": min(100, max(1, int(limits.get("max_runs_per_hour", 20)))), "cooldown_seconds": min(86400, max(0, int(limits.get("cooldown_seconds", 0)))), "disable_after_failures": min(20, max(1, int(limits.get("disable_after_failures", 3))))}
    routine_key = str(value.get("routine_key") or "")[:80]
    estimated_minutes = min(240, max(0, int(value.get("estimated_minutes_saved") or 0)))
    normalized = {"name": name, "description": str(value.get("description") or "")[:2000], "trigger": trigger, "conditions": normalized_conditions, "actions": normalized_actions, "limits": limits, "routine_key": routine_key, "estimated_minutes_saved": estimated_minutes}
    if len(_json(normalized).encode()) > MAX_DEFINITION_BYTES: raise AutomationValidationError("definition is too large")
    return normalized


class DefaultActionRunner:
    async def __call__(self, owner: str, action: Mapping[str, Any], context: Mapping[str, Any]):
        kind = action["type"]; p = dict(action.get("parameters") or {})
        approved = bool(context.get("approved"))
        if kind == "generate_briefing": return await get_executive_service().briefing(owner, kind=p.get("kind", "morning"), timezone_name=p.get("timezone"))
        if kind == "query_knowledge": return get_knowledge_service().grounded_context(owner, str(p.get("query") or ""), limit=min(int(p.get("limit", 8)), 50))
        if kind == "create_task":
            task = get_work_service().create_task(owner, p, context=MutationContext(actor_kind="integration", actor_id=str(owner or ""), correlation_id=context["correlation_id"])); return {"task": task}
        if kind == "notify_user": return {"notification": {"title": str(p.get("title") or "OM Automate"), "message": str(p.get("message") or "")[:10000]}, "delivered": "in_app_run_history"}
        if kind == "draft_email":
            to = str(p.get("to") or "").strip()
            subject = str(p.get("subject") or "").strip()
            body = str(p.get("body") or "")
            if not to or not subject or not body:
                raise AutomationValidationError("draft_email requires to, subject, and body")
            return {"draft": {"to": to, "cc": str(p.get("cc") or ""), "bcc": str(p.get("bcc") or ""), "subject": subject, "body": body}, "sent": False, "review_required_before_send": True}
        if kind == "add_reminder":
            remind_at = str(p.get("remind_at") or "").strip()
            title = str(p.get("title") or p.get("message") or "Reminder").strip()
            if not remind_at:
                raise AutomationValidationError("add_reminder requires remind_at")
            task = get_work_service().create_task(
                owner,
                {"title": title, "description": str(p.get("message") or ""), "status": "planned", "reminders": [{"remind_at": remind_at, "message": str(p.get("message") or title), "channel": "in_app"}]},
                context=MutationContext(actor_kind="integration", actor_id=str(owner or ""), correlation_id=context["correlation_id"]),
            )
            return {"task": task, "reminder_created": True}
        if kind == "create_backup":
            from services.backup_service import BackupService
            # The secret is referenced outside the workflow definition and
            # never copied into run history or the backup itself.
            passphrase_file = Path(os.getenv("OM_SCHEDULED_BACKUP_PASSPHRASE_FILE") or "").expanduser()
            if not str(passphrase_file) or not passphrase_file.is_file():
                raise AutomationValidationError("Scheduled backups require OM_SCHEDULED_BACKUP_PASSPHRASE_FILE")
            try:
                passphrase = passphrase_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise AutomationError("Scheduled backup passphrase file is unreadable") from exc
            payload, manifest = BackupService().create(passphrase=passphrase)
            backup_dir = Path(DATA_DIR) / "backups"; backup_dir.mkdir(parents=True, exist_ok=True)
            filename = f"scheduled-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.ombak"
            target = backup_dir / filename
            with open(target, "xb") as handle: handle.write(payload)
            try: os.chmod(target,0o600)
            except OSError: pass
            return {"backup": {"path": str(target), "bytes": len(payload), "files": len(manifest["files"]), "encrypted": True, "key_included": False}}
        if kind == "call_integration":
            integration_id = str(p.get("integration_id") or "").strip()
            if not integration_id:
                raise AutomationValidationError("call_integration requires integration_id")
            from services.privacy_service import get_privacy_service
            get_privacy_service().require_integration(owner, integration_id)
            if approved:
                from services.integration_registry import get_integration_registry
                action_name=str(p.get("action") or "").strip()
                if not action_name:raise AutomationValidationError("call_integration requires action")
                return await get_integration_registry().execute(owner,integration_id,action_name,p.get("parameters") or {},privacy_service=get_privacy_service())
        if approved and kind == "request_approval":
            return {"approved_checkpoint": True, "parameters": p}
        if approved and kind == "run_research":
            from src.tools.research import do_trigger_research
            result = dict(await do_trigger_research(_json(p), owner))
            if result.get("error") or result.get("exit_code") not in (None, 0):
                raise AutomationError(str(result.get("error") or "Research could not start"))
            return result
        if approved and kind == "start_agent_workflow":
            target=str(p.get("automation_id") or "").strip()
            if not target:raise AutomationValidationError("start_agent_workflow requires automation_id")
            nested=await get_automation_service().run(owner,target,trigger={"type":"integration_event","parent_run_id":context["run_id"]},inputs=dict(p.get("inputs") or {}),dedupe_key=f"nested:{context['run_id']}:{target}",depth=int(context.get("depth") or 0)+1,lineage=tuple(context.get("lineage") or ()))
            return {"workflow_run":nested}
        # External communications, research, integration calls and agent work
        # never execute implicitly. The run becomes approval_required and the
        # exact requested parameters remain visible in durable history.
        return {"approval_required": True, "requested_action": kind, "parameters": p}


class AutomationService:
    def __init__(self, *, session_factory=None, database_url=None, action_runner: Optional[Callable[..., Awaitable[Mapping[str, Any]]]] = None, clock=None, approval_proposer=None):
        if session_factory is None:
            url = database_url or os.getenv("OM_AUTOMATION_DATABASE_URL") or f"sqlite:///{Path(DATA_DIR) / 'automations.db'}"; engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}); ensure_automation_schema(engine); session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        self.sessions = session_factory; self.runner = action_runner or DefaultActionRunner(); self.clock = clock or _now; self.approval_proposer = approval_proposer; self._last_proactive_at = None

    @staticmethod
    def _definition(row):
        return {"id": row.id, "owner": None if row.owner == "__local__" else row.owner, **json.loads(row.definition_json), "status": row.status, "version": row.version, "next_run_at": _iso(row.next_run_at), "last_run_at": _iso(row.last_run_at), "consecutive_failures": row.consecutive_failures, "run_count": row.run_count, "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at)}
    @staticmethod
    def _run(row):
        return {"id": row.id, "automation_id": row.automation_id, "trigger": json.loads(row.trigger_json), "inputs": json.loads(row.inputs_json), "steps": json.loads(row.steps_json), "tool_calls": json.loads(row.tool_calls_json), "output": json.loads(row.output_json) if row.output_json else None, "logs": json.loads(row.logs_json), "status": row.status, "retry_status": row.retry_status, "approval_state": row.approval_state, "correlation_id": row.correlation_id, "depth": row.depth, "started_at": _iso(row.started_at), "finished_at": _iso(row.finished_at), "duration_ms": row.duration_ms, "error": row.error}
    def _owned(self, db, owner, automation_id):
        row = db.query(AutomationDefinition).filter(AutomationDefinition.id == str(automation_id), AutomationDefinition.owner == _owner(owner)).first()
        if not row: raise AutomationNotFound("Automation not found")
        return row
    def create(self, owner, definition):
        clean = validate_definition(definition); now = self.clock(); trigger = clean["trigger"]
        if trigger["type"] == "recurring_interval": next_run = now + timedelta(seconds=trigger["interval_seconds"])
        elif trigger["type"] == "conditional_polling": next_run = now + timedelta(seconds=trigger["poll_seconds"])
        elif trigger["type"] == "scheduled_time":
            next_run = datetime.fromisoformat(str(trigger["at"]).replace("Z", "+00:00")); next_run = next_run.replace(tzinfo=timezone.utc) if next_run.tzinfo is None else next_run.astimezone(timezone.utc)
        else: next_run = None
        webhook_secret = secrets.token_urlsafe(32) if trigger["type"] == "webhook" else None
        row = AutomationDefinition(id=str(uuid.uuid4()), owner=_owner(owner), name=clean["name"], definition_json=_json(clean), webhook_secret_enc=encrypt(webhook_secret) if webhook_secret else None, status="enabled", next_run_at=next_run, created_at=now, updated_at=now); db = self.sessions()
        try:
            db.add(row); db.commit(); db.refresh(row); result=self._definition(row)
            if webhook_secret: result.update({"webhook_secret":webhook_secret,"webhook_path":f"/api/automation-hooks/{row.id}","webhook_secret_shown_once":True})
            return result
        finally: db.close()
    def list(self, owner):
        db=self.sessions()
        try:return [self._definition(row) for row in db.query(AutomationDefinition).filter(AutomationDefinition.owner==_owner(owner)).order_by(AutomationDefinition.created_at.desc()).all()]
        finally:db.close()
    def routine_templates(self, owner):
        installed = {item.get("routine_key"): item["id"] for item in self.list(owner) if item.get("routine_key")}
        return [{"key": key, "name": value["name"], "description": value["description"], "trigger_type": value.get("event") or "recurring_interval", "interval_seconds": value.get("interval"), "estimated_minutes_saved": value["minutes"], "installed_automation_id": installed.get(key)} for key, value in ROUTINE_TEMPLATES.items()]
    def install_routine(self, owner, routine_key):
        template = ROUTINE_TEMPLATES.get(str(routine_key))
        if template is None: raise AutomationNotFound("Routine template not found")
        existing = next((item for item in self.list(owner) if item.get("routine_key") == routine_key), None)
        if existing: return {**existing, "already_installed": True}
        trigger = {"type": template["event"]} if template.get("event") else {"type": "recurring_interval", "interval_seconds": template["interval"]}
        return self.create(owner, {"name": template["name"], "description": template["description"], "trigger": trigger, "conditions": [], "actions": template["actions"], "limits": {"max_steps": 10, "max_runs_per_hour": 4, "disable_after_failures": 3}, "routine_key": routine_key, "estimated_minutes_saved": template["minutes"]})
    def operating_metrics(self, owner, *, since):
        db = self.sessions()
        try:
            rows = db.query(AutomationRun, AutomationDefinition).join(AutomationDefinition, AutomationDefinition.id == AutomationRun.automation_id).filter(AutomationRun.owner == _owner(owner), AutomationRun.status == "success", AutomationRun.started_at >= since).all()
            minutes = 0; routines = 0
            for run, definition in rows:
                clean = json.loads(definition.definition_json)
                if clean.get("routine_key"):
                    routines += 1; minutes += int(clean.get("estimated_minutes_saved") or 0)
            return {"successful_routine_runs": routines, "attention_returned_minutes": minutes, "measurement": "template_estimate_per_successful_run"}
        finally: db.close()
    def get(self, owner, automation_id):
        db=self.sessions()
        try:return self._definition(self._owned(db,owner,automation_id))
        finally:db.close()
    def set_status(self, owner, automation_id, status):
        if status not in {"enabled","paused"}: raise AutomationValidationError("status must be enabled or paused")
        db=self.sessions()
        try: row=self._owned(db,owner,automation_id); row.status=status; row.version+=1; row.updated_at=self.clock(); db.commit(); db.refresh(row); return self._definition(row)
        finally:db.close()
    def delete(self, owner, automation_id, expected_version):
        db=self.sessions()
        try:
            row=self._owned(db,owner,automation_id)
            if row.version != int(expected_version): raise AutomationConflict("Automation was changed by another request")
            db.delete(row); db.commit(); return {"id":automation_id,"deleted":True}
        finally:db.close()
    def list_runs(self, owner, automation_id=None, limit=100):
        db=self.sessions()
        try:
            q=db.query(AutomationRun).filter(AutomationRun.owner==_owner(owner)); q=q.filter(AutomationRun.automation_id==automation_id) if automation_id else q
            return [self._run(row) for row in q.order_by(AutomationRun.started_at.desc()).limit(min(500,max(1,int(limit)))).all()]
        finally:db.close()
    def _owned_run(self, db, owner, run_id):
        row = db.query(AutomationRun).filter(
            AutomationRun.id == str(run_id),
            AutomationRun.owner == _owner(owner),
        ).first()
        if not row:
            raise AutomationNotFound("Automation run not found")
        return row

    def get_run(self, owner, run_id):
        db = self.sessions()
        try:
            return self._run(self._owned_run(db, owner, run_id))
        finally:
            db.close()

    def cancel_run(self, owner, run_id):
        """Request cancellation without crossing the owner boundary.

        Action runners are not forcibly interrupted because that can leave an
        external provider in an unknown state. The executor observes this
        durable state before each subsequent step and when persisting results.
        """

        db = self.sessions()
        try:
            row = self._owned_run(db, owner, run_id)
            if row.status in {"success", "failed", "skipped", "cancelled"}:
                raise AutomationStateError(
                    f"Run in '{row.status}' state cannot be cancelled"
                )
            row.status = "cancel_requested" if row.status == "running" else "cancelled"
            row.approval_state = (
                "cancelled" if row.approval_state == "pending" else row.approval_state
            )
            if row.status == "cancelled":
                row.finished_at = self.clock()
            db.commit()
            db.refresh(row)
            return self._run(row)
        finally:
            db.close()

    def _cancellation_requested(self, owner, run_id):
        db = self.sessions()
        try:
            row = self._owned_run(db, owner, run_id)
            return row.status in {"cancel_requested", "cancelled"}
        finally:
            db.close()

    def _propose_step_approval(self, owner, automation_id, run_id, step_index):
        """Create an immutable Approval Centre proposal for one exact step."""

        if self.approval_proposer is not None:
            return self.approval_proposer(owner, automation_id, run_id, step_index)

        from src.action_ledger import get_action_ledger
        from src.tool_actions import build_action_envelope
        from src.tool_authorization import ExecutionOrigin, ResolvedToolIdentity
        from src.tool_registry import ToolSurface, build_builtin_registry

        definition = build_builtin_registry().resolve(
            "manage_automation", surface=ToolSurface.FENCE
        )
        identity = ResolvedToolIdentity(
            requested_name="manage_automation",
            canonical_name="manage_automation",
            definition=definition,
            surface=ToolSurface.FENCE,
        )
        arguments = {
            "action": "approve_step",
            "automation_id": str(automation_id),
            "run_id": str(run_id),
            "step_index": int(step_index),
        }
        envelope = build_action_envelope(
            identity,
            arguments,
            owner=owner,
            session_id=None,
            request_id=f"automation:{run_id}:step:{step_index}",
            origin=ExecutionOrigin.SCHEDULED_AUTOMATION,
        )
        return get_action_ledger().propose(
            envelope,
            risk_level=2,
            approval_reason="A consequential automation step requires explicit approval.",
            origin=ExecutionOrigin.SCHEDULED_AUTOMATION.value,
        )

    async def approve_step(self, owner, automation_id, run_id, step_index):
        """Consume approval for an exact paused step and resume later steps.

        The external request itself is recorded as approved. Integrations that
        cannot execute an action report a failure rather than pretending the
        side effect happened.
        """

        db = self.sessions()
        try:
            definition = self._owned(db, owner, automation_id)
            run = self._owned_run(db, owner, run_id)
            if run.automation_id != definition.id or run.status != "approval_required":
                raise AutomationStateError("Run is not waiting for this approval")
            clean = json.loads(definition.definition_json)
            index = int(step_index)
            if index < 0 or index >= len(clean["actions"]):
                raise AutomationValidationError("step_index is invalid")
            steps = json.loads(run.steps_json or "[]")
            if not steps or steps[-1].get("index") != index or steps[-1].get("status") != "approval_required":
                raise AutomationStateError("Run step does not match the pending approval")
            action = clean["actions"][index]
            correlation_id = run.correlation_id
            run_depth = run.depth
            output = json.loads(run.output_json or "[]")
            logs = json.loads(run.logs_json or "[]")
            run.status = "running"
            run.approval_state = "approved"
            run.finished_at = None
            db.commit()
        finally:
            db.close()

        status = "success"
        error = None
        try:
            result = dict(await self.runner(owner, action, {"correlation_id": correlation_id, "run_id": run_id, "depth": run_depth, "lineage": [automation_id], "approved": True}))
            if result.get("approval_required"):
                raise AutomationStateError("Approved action has no executable integration adapter")
            steps[-1].update({"status": "success", "result": result, "finished_at": _iso(self.clock())})
            output.append(result)
            for next_index in range(index + 1, min(len(clean["actions"]), clean["limits"]["max_steps"])):
                if self._cancellation_requested(owner, run_id):
                    status = "cancelled"; logs.append({"level": "info", "message": "Cancellation requested"}); break
                next_action = clean["actions"][next_index]
                step = {"index": next_index, "action": next_action["type"], "started_at": _iso(self.clock())}
                try:
                    next_result = dict(await self.runner(owner, next_action, {"correlation_id": correlation_id, "run_id": run_id, "depth": run_depth, "lineage": [automation_id]}))
                    if next_result.get("approval_required"):
                        proposal = self._propose_step_approval(owner, automation_id, run_id, next_index)
                        next_result["approval_id"] = proposal["id"]
                        step.update({"status": "approval_required", "result": next_result, "finished_at": _iso(self.clock())})
                        output.append(next_result); steps.append(step); status = "approval_required"; break
                    step.update({"status": "success", "result": next_result, "finished_at": _iso(self.clock())}); output.append(next_result)
                except Exception as exc:
                    step.update({"status": "error", "error": str(exc)[:2000], "finished_at": _iso(self.clock())})
                    steps.append(step)
                    if not next_action.get("continue_on_error"): raise
                    continue
                steps.append(step)
        except Exception as exc:
            status = "failed"; error = f"{type(exc).__name__}: {exc}"[:4000]; logs.append({"level": "error", "message": error})

        finished = self.clock(); db = self.sessions()
        try:
            run = self._owned_run(db, owner, run_id)
            if run.status in {"cancel_requested", "cancelled"}: status = "cancelled"
            run.steps_json = _json(steps); run.tool_calls_json = _json([{"action": item["action"], "status": item["status"]} for item in steps]); run.output_json = _json(output); run.logs_json = _json(logs); run.status = status; run.approval_state = "pending" if status == "approval_required" else ("cancelled" if status == "cancelled" else "approved"); run.error = error; run.finished_at = finished; run.duration_ms = max(0, int((finished - _aware(run.started_at)).total_seconds() * 1000)); db.commit(); db.refresh(run); return self._run(run)
        finally:
            db.close()

    def reject_step(self, owner, automation_id, run_id, step_index, reason=""):
        """Close an exact pending checkpoint after an Approval Centre rejection."""

        db = self.sessions()
        try:
            definition = self._owned(db, owner, automation_id)
            run = self._owned_run(db, owner, run_id)
            steps = json.loads(run.steps_json or "[]")
            index = int(step_index)
            if (
                run.automation_id != definition.id
                or run.status != "approval_required"
                or not steps
                or steps[-1].get("index") != index
                or steps[-1].get("status") != "approval_required"
            ):
                raise AutomationStateError("Run is not waiting for this approval")
            steps[-1]["status"] = "rejected"
            steps[-1]["rejection_reason"] = str(reason or "")[:2000]
            run.steps_json = _json(steps)
            run.tool_calls_json = _json([{"action": item["action"], "status": item["status"]} for item in steps])
            run.status = "cancelled"
            run.approval_state = "rejected"
            run.finished_at = self.clock()
            run.logs_json = _json([*json.loads(run.logs_json or "[]"), {"level": "info", "message": "Approval rejected; run cancelled"}])
            db.commit(); db.refresh(run); return self._run(run)
        finally:
            db.close()

    async def retry_run(self, owner, run_id):
        """Retry a terminal failed/cancelled run exactly once per request."""

        db = self.sessions()
        try:
            previous = self._owned_run(db, owner, run_id)
            if previous.status not in {"failed", "cancelled"}:
                raise AutomationStateError("Only failed or cancelled runs can be retried")
            if previous.retry_status == "retrying":
                raise AutomationConflict("A retry is already in progress")
            automation_id = previous.automation_id
            trigger = json.loads(previous.trigger_json)
            inputs = json.loads(previous.inputs_json)
            depth = previous.depth
            previous.retry_status = "retrying"
            db.commit()
        finally:
            db.close()

        try:
            retried = await self.run(
                owner,
                automation_id,
                trigger={**trigger, "retry_of": str(run_id)},
                inputs=inputs,
                correlation_id=str(uuid.uuid4()),
                dedupe_key=f"retry:{run_id}:{uuid.uuid4()}",
                depth=depth,
                allow_disabled_failure=True,
            )
        except Exception:
            db = self.sessions()
            try:
                previous = self._owned_run(db, owner, run_id)
                previous.retry_status = "retry_failed"
                db.commit()
            finally:
                db.close()
            raise

        db = self.sessions()
        try:
            previous = self._owned_run(db, owner, run_id)
            previous.retry_status = "retried"
            previous.logs_json = _json([
                *json.loads(previous.logs_json or "[]"),
                {"level": "info", "message": f"Retried as run {retried['id']}"},
            ])
            db.commit()
        finally:
            db.close()
        return retried

    async def run(self, owner, automation_id, *, trigger=None, inputs=None, correlation_id=None, dedupe_key=None, depth=0, lineage=(), allow_disabled_failure=False):
        now=self.clock(); db=self.sessions()
        try:
            definition=self._owned(db,owner,automation_id); clean=json.loads(definition.definition_json)
            if definition.status != "enabled" and not (
                allow_disabled_failure and definition.status == "disabled_failure"
            ):
                raise AutomationConflict("Automation is not enabled")
            if depth>MAX_DEPTH or automation_id in lineage: raise AutomationLoopDetected("Automation run loop/depth limit reached")
            if definition.cooldown_until and _aware(definition.cooldown_until)>now: raise AutomationRateLimited("Automation is in cooldown")
            hour_ago=now-timedelta(hours=1); count=db.query(AutomationRun).filter(AutomationRun.automation_id==automation_id,AutomationRun.started_at>=hour_ago).count()
            if count>=clean["limits"]["max_runs_per_hour"]: raise AutomationRateLimited("Automation hourly rate limit reached")
            trigger=dict(trigger or {"type":"manual"}); inputs=dict(inputs or {}); correlation_id=str(correlation_id or uuid.uuid4()); idem=hashlib.sha256(f"{_owner(owner)}:{automation_id}:{dedupe_key or correlation_id}".encode()).hexdigest()
            existing=db.query(AutomationRun).filter(AutomationRun.idempotency_key==idem).first()
            if existing:return self._run(existing)
            run=AutomationRun(id=str(uuid.uuid4()),automation_id=automation_id,owner=_owner(owner),trigger_json=_json(trigger),inputs_json=_json(inputs),correlation_id=correlation_id,idempotency_key=idem,depth=depth,started_at=now,status="running");db.add(run);db.commit();db.refresh(run)
        finally:db.close()
        steps=[]; logs=[]; output=[]; status="success"; approval="not_required"; error=None
        try:
            if not all(_condition(item,inputs) for item in clean["conditions"]): status="skipped"; logs.append({"level":"info","message":"Conditions did not match"})
            else:
                for index, action in enumerate(clean["actions"][:clean["limits"]["max_steps"]]):
                    if self._cancellation_requested(owner, run.id):
                        status = "cancelled"
                        approval = "cancelled" if approval == "pending" else approval
                        logs.append({"level": "info", "message": "Cancellation requested"})
                        break
                    started=self.clock(); step={"index":index,"action":action["type"],"started_at":_iso(started)}
                    try:
                        result=dict(await self.runner(owner,action,{"correlation_id":correlation_id,"run_id":run.id,"depth":depth,"lineage":[*lineage,automation_id]}));step.update({"status":"success","result":result,"finished_at":_iso(self.clock())});output.append(result)
                        if result.get("approval_required"):
                            proposal=self._propose_step_approval(owner,automation_id,run.id,index);result["approval_id"]=proposal["id"];step.update({"status":"approval_required","result":result});output[-1]=result;status="approval_required";approval="pending";steps.append(step);break
                    except Exception as exc:
                        step.update({"status":"error","error":str(exc)[:2000],"finished_at":_iso(self.clock())});
                        if not action.get("continue_on_error"): raise
                    steps.append(step)
        except Exception as exc: status="failed";error=f"{type(exc).__name__}: {exc}"[:4000];logs.append({"level":"error","message":error})
        finished=self.clock();db=self.sessions()
        try:
            run=self._owned_run(db,owner,run.id)
            if run.status in {"cancel_requested", "cancelled"}:
                status = "cancelled"
                approval = "cancelled" if approval == "pending" else approval
                logs.append({"level": "info", "message": "Run cancelled"})
            run.steps_json=_json(steps);run.tool_calls_json=_json([{"action":item["action"],"status":item["status"]} for item in steps]);run.output_json=_json(output);run.logs_json=_json(logs);run.status=status;run.approval_state=approval;run.error=error;run.finished_at=finished;run.duration_ms=max(0,int((finished-now).total_seconds()*1000))
            definition=self._owned(db,owner,automation_id);definition.last_run_at=finished;definition.run_count+=1;definition.updated_at=finished
            if status=="failed":
                definition.consecutive_failures+=1
                if definition.consecutive_failures>=clean["limits"]["disable_after_failures"]:definition.status="disabled_failure";db.add(AutomationDeadLetter(id=str(uuid.uuid4()),automation_id=automation_id,owner=_owner(owner),run_id=run.id,reason=error or "Repeated failure",payload_json=_json(inputs),created_at=finished))
            else:
                definition.consecutive_failures=0
                if allow_disabled_failure and definition.status == "disabled_failure":
                    definition.status = "enabled"
            if clean["limits"]["cooldown_seconds"]:definition.cooldown_until=finished+timedelta(seconds=clean["limits"]["cooldown_seconds"])
            if clean["trigger"]["type"]=="recurring_interval":definition.next_run_at=finished+timedelta(seconds=clean["trigger"]["interval_seconds"])
            elif clean["trigger"]["type"]=="conditional_polling":definition.next_run_at=finished+timedelta(seconds=clean["trigger"]["poll_seconds"])
            elif clean["trigger"]["type"]=="scheduled_time": definition.next_run_at=None; definition.status="completed"
            db.commit();db.refresh(run);return self._run(run)
        finally:db.close()
    async def emit(self, owner, event_type, payload, *, dedupe_key, correlation_id=None, depth=0, lineage=()):
        if event_type not in TRIGGERS-{"scheduled_time","recurring_interval","conditional_polling","manual"}: raise AutomationValidationError("event type is invalid")
        db=self.sessions();event=AutomationEvent(id=str(uuid.uuid4()),owner=_owner(owner),event_type=event_type,dedupe_key=str(dedupe_key)[:300],received_at=self.clock())
        try:
            db.add(event);db.commit();event_id=event.id;rows=db.query(AutomationDefinition).filter(AutomationDefinition.owner==_owner(owner),AutomationDefinition.status=="enabled").all();ids=[row.id for row in rows if json.loads(row.definition_json)["trigger"]["type"]==event_type]
        except IntegrityError:db.rollback();return {"duplicate":True,"runs":[]}
        finally:db.close()
        runs=[]
        for automation_id in ids:runs.append(await self.run(owner,automation_id,trigger={"type":event_type,"event_id":event_id},inputs=payload,correlation_id=correlation_id,dedupe_key=f"{event_type}:{dedupe_key}:{automation_id}",depth=depth,lineage=lineage))
        return {"duplicate":False,"runs":runs}
    async def accept_webhook(self, automation_id, body: bytes, *, timestamp: str, signature: str, delivery_id: str):
        if len(body)>1024*1024: raise AutomationValidationError("Webhook payload exceeds 1 MiB")
        try: sent=datetime.fromtimestamp(int(timestamp),tz=timezone.utc)
        except (ValueError,OverflowError) as exc: raise AutomationValidationError("Webhook timestamp is invalid") from exc
        if abs((self.clock()-sent).total_seconds())>300: raise AutomationValidationError("Webhook timestamp is outside the five-minute replay window")
        db=self.sessions()
        try:
            row=db.query(AutomationDefinition).filter(AutomationDefinition.id==str(automation_id),AutomationDefinition.status=="enabled").first()
            if not row: raise AutomationNotFound("Webhook automation not found")
            clean=json.loads(row.definition_json)
            if clean["trigger"]["type"]!="webhook" or not row.webhook_secret_enc: raise AutomationNotFound("Webhook automation not found")
            owner=None if row.owner=="__local__" else row.owner;secret=decrypt(row.webhook_secret_enc)
        finally:db.close()
        expected="sha256="+hmac.new(secret.encode(),timestamp.encode()+b"."+body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,str(signature or "")): raise AutomationValidationError("Webhook signature is invalid")
        try: payload=json.loads(body)
        except json.JSONDecodeError as exc: raise AutomationValidationError("Webhook body must be JSON") from exc
        if not isinstance(payload,dict): raise AutomationValidationError("Webhook body must be a JSON object")
        return await self.emit(owner,"webhook",payload,dedupe_key=f"webhook:{delivery_id}",correlation_id=delivery_id)
    async def run_due(self):
        now=self.clock();db=self.sessions()
        try:due=[(row.owner,row.id) for row in db.query(AutomationDefinition).filter(AutomationDefinition.status=="enabled",AutomationDefinition.next_run_at.is_not(None),AutomationDefinition.next_run_at<=now).limit(100).all()]
        finally:db.close()
        results=[]
        for owner,automation_id in due:
            definition=self.get(None if owner=="__local__" else owner,automation_id)
            results.append(await self.run(None if owner=="__local__" else owner,automation_id,trigger={"type":definition["trigger"]["type"]},inputs={},dedupe_key=f"due:{int(now.timestamp()//60)}:{automation_id}"))
        # Event-like time windows are polled at most once per minute. Durable
        # run idempotency makes process restarts and overlapping polls safe.
        if self._last_proactive_at is None or (now-self._last_proactive_at).total_seconds()>=60:
            self._last_proactive_at=now
            results.extend(await self.run_proactive(now=now))
        return results

    async def run_proactive(self, *, now=None):
        """Poll task-due and calendar-before-event triggers with stable dedupe."""

        now=now or self.clock();db=self.sessions()
        try:
            rows=db.query(AutomationDefinition).filter(AutomationDefinition.status=="enabled").all()
            definitions=[(row.owner,row.id,json.loads(row.definition_json)) for row in rows if json.loads(row.definition_json)["trigger"]["type"] in {"task_due","calendar_before_event"}]
        finally:db.close()
        results=[]
        by_owner={}
        for stored_owner,automation_id,definition in definitions:by_owner.setdefault(stored_owner,[]).append((automation_id,definition))
        for stored_owner,items in by_owner.items():
            owner=None if stored_owner=="__local__" else stored_owner
            task_items=[item for item in items if item[1]["trigger"]["type"]=="task_due"]
            if task_items:
                reminders=get_work_service().pending_reminders(owner,due_before=now,limit=500)
                for automation_id,_definition in task_items:
                    for reminder in reminders:
                        results.append(await self.run(owner,automation_id,trigger={"type":"task_due"},inputs={"task":{"reminder":reminder}},dedupe_key=f"task-due:{reminder['id']}:{automation_id}"))
            calendar_items=[item for item in items if item[1]["trigger"]["type"]=="calendar_before_event"]
            if calendar_items:
                max_minutes=max(int(item[1]["trigger"].get("minutes_before") or 0) for item in calendar_items)
                try:
                    snapshot=await get_executive_service()._google_snapshot(owner,now,now+timedelta(minutes=max(1,max_minutes)))
                except Exception:
                    snapshot={"schedule":[]}
                for automation_id,definition in calendar_items:
                    window=now+timedelta(minutes=int(definition["trigger"].get("minutes_before") or 0))
                    for event in snapshot.get("schedule",[]):
                        raw=(event.get("start") or {}).get("dateTime")
                        try:event_start=datetime.fromisoformat(str(raw).replace("Z","+00:00"));event_start=event_start.replace(tzinfo=timezone.utc) if event_start.tzinfo is None else event_start.astimezone(timezone.utc)
                        except (TypeError,ValueError):continue
                        if now<=event_start<=window:
                            event_id=str(event.get("id") or hashlib.sha256(_json(event).encode()).hexdigest())
                            results.append(await self.run(owner,automation_id,trigger={"type":"calendar_before_event"},inputs={"event":event},dedupe_key=f"calendar-before:{event_id}:{automation_id}"))
        return results


_service=None
def get_automation_service():
    global _service
    if _service is None:_service=AutomationService()
    return _service
