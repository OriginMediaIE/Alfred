"""Read-only executive dashboard and source-grounded review composition."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from typing import Any, Optional
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.google_calendar import get_google_calendar_service
from services.google_gmail import get_google_gmail_service
from services.knowledge_service import get_knowledge_service
from services.meeting_service import get_meeting_service
from src.action_ledger import get_action_ledger
from src.google_connection import get_google_connection_service
from src.work_service import get_work_service
from core.database import SessionLocal
from src.executive_models import ExecutiveBriefingRun, ensure_executive_schema


def _zone(name: Optional[str]) -> ZoneInfo:
    try: return ZoneInfo(str(name or "UTC"))
    except ZoneInfoNotFoundError: return ZoneInfo("UTC")


def _event_start(event: dict[str, Any]) -> str:
    value = event.get("start") or {}
    return str(value.get("dateTime") or value.get("date") or "")


def _is_future_event(event: dict[str, Any], now: datetime) -> bool:
    raw = _event_start(event)
    if not raw: return False
    try:
        if len(raw) == 10: parsed = datetime.combine(datetime.fromisoformat(raw).date(), time.min, tzinfo=now.tzinfo)
        else: parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=now.tzinfo)
        return parsed >= now
    except ValueError: return False


class ExecutiveService:
    def __init__(self, *, work=None, meetings=None, knowledge=None, actions=None, connections=None, calendar=None, gmail=None, clock=None, session_factory=SessionLocal, initialise=True):
        self.work = work or get_work_service(); self.meetings = meetings or get_meeting_service(); self.knowledge = knowledge or get_knowledge_service(); self.actions = actions or get_action_ledger(); self.connections = connections or get_google_connection_service(); self.calendar = calendar or get_google_calendar_service(); self.gmail = gmail or get_google_gmail_service(); self.clock = clock or (lambda: datetime.now(timezone.utc)); self.sessions = session_factory
        if initialise:
            bind = getattr(session_factory, "kw", {}).get("bind")
            ensure_executive_schema(bind=bind) if bind is not None else ensure_executive_schema()

    async def _google_snapshot(self, owner: str, start: datetime, end: datetime) -> dict[str, Any]:
        schedule: list[dict[str, Any]] = []; attention: list[dict[str, Any]] = []; health: list[dict[str, Any]] = []
        connected = [item for item in self.connections.list_connections(owner) if item.get("status") == "connected"]
        for connection in connected:
            connection_id = connection["id"]; account_health = {"connection_id": connection_id, "email": connection.get("email"), "calendar": "not_configured", "gmail": "not_configured"}
            calendar_ids = connection.get("selected_calendars") or [connection.get("default_calendar") or "primary"]
            for calendar_id in calendar_ids[:20]:
                try:
                    result = await self.calendar.list_events(owner, connection_id, calendar_id=calendar_id, time_min=start.isoformat(), time_max=end.isoformat(), max_results=250)
                    for event in result.get("events", []): schedule.append({**event, "connection_id": connection_id, "account": connection.get("email")})
                    account_health["calendar"] = "connected"
                except Exception as exc:
                    account_health["calendar"] = "degraded"; account_health["calendar_error"] = type(exc).__name__
            try:
                result = await self.gmail.search_messages(owner, connection_id, query="is:unread newer_than:14d -category:promotions -category:social", max_results=20, include_metadata=True)
                attention.extend([{**item, "connection_id": connection_id, "account": connection.get("email")} for item in result.get("messages", [])]); account_health["gmail"] = "connected"
            except Exception as exc:
                account_health["gmail"] = "degraded"; account_health["gmail_error"] = type(exc).__name__
            health.append(account_health)
        if not connected:
            health.append({
                "connection_id": "google-workspace",
                "email": "Google Workspace",
                "calendar": "not_configured",
                "gmail": "not_configured",
            })
        schedule.sort(key=_event_start)
        return {"schedule": schedule, "emails_requiring_attention": attention, "connections": health, "configured": bool(connected)}

    async def today(self, owner: str, *, timezone_name: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
        current = (now or self.clock()).astimezone(_zone(timezone_name)); start = datetime.combine(current.date(), time.min, tzinfo=current.tzinfo); end = start + timedelta(days=1)
        google = await self._google_snapshot(owner, start.astimezone(timezone.utc), end.astimezone(timezone.utc))
        focus = self.work.daily_focus(owner, plan_date=current, available_minutes=480)
        commitments = self.work.list_commitments(owner, due_before=end + timedelta(days=7), limit=100)
        reminders = self.work.pending_reminders(owner, due_before=end, limit=100)
        pending = self.actions.list_actions(owner, status="pending", limit=100)
        recent_meeting_actions = []
        for summary in self.meetings.list_meetings(owner, limit=10).get("meetings", []):
            try:
                full = self.meetings.get_meeting(owner, summary["id"])
                recent_meeting_actions.extend([{"meeting_id": summary["id"], "meeting_title": summary["title"], **claim} for claim in full["claims"] if claim["kind"] in {"action_item", "decision"}])
            except Exception: continue
        next_event = next((item for item in google["schedule"] if _is_future_event(item, current)), None)
        snapshot = {"date": current.date().isoformat(), "local_time": current.isoformat(), "timezone": str(current.tzinfo), "weather": {"status": "not_configured", "message": "Weather integration is optional and has not been connected."}, "next_event": next_event, "schedule": google["schedule"], "priority_tasks": focus.get("tasks", []), "focus_plan": focus, "emails_requiring_attention": google["emails_requiring_attention"], "pending_approvals": pending, "unresolved_commitments": commitments, "recent_meeting_actions": recent_meeting_actions[:30], "important_reminders": reminders, "integration_health": google["connections"], "local_core_health": [], "source_status": {"google_workspace": "connected" if google["configured"] else "not_configured", "work": "connected", "meetings": "connected", "approvals": "connected"}}
        snapshot["daily_briefing"] = self._compose_briefing("morning", snapshot)
        return snapshot

    @staticmethod
    def _source(kind: str, item: dict[str, Any], label: str) -> dict[str, Any]:
        return {
            "type": kind,
            "id": str(item.get("id") or item.get("event_id") or ""),
            "label": str(label or "Untitled source"),
            "url": str(item.get("html_link") or item.get("source_url") or ""),
        }

    def _section(self, title: str, values: list[tuple[str, dict[str, Any], str]]) -> dict[str, Any]:
        bounded = [(kind, item, label) for kind, item, label in values if label][:20]
        return {
            "title": title,
            "items": [label for _kind, _item, label in bounded],
            "sources": [self._source(kind, item, label) for kind, item, label in bounded],
        }

    def _compose_briefing(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        sections = []
        if kind == "morning":
            sections = [self._section("Schedule", [("google_calendar", item, item.get("summary") or item.get("title") or "Untitled event") for item in data.get("schedule", [])]), self._section("Priorities", [("work_task", item, item.get("title", "")) for item in data.get("priority_tasks", [])]), self._section("Messages", [("gmail_message", item, item.get("subject") or item.get("snippet") or "Unread message") for item in data.get("emails_requiring_attention", [])]), self._section("At-risk commitments", [("work_commitment", item, item.get("title", "")) for item in data.get("unresolved_commitments", [])]), self._section("Pending approvals", [("agent_action", item, item.get("approval_reason") or item.get("tool_name", "")) for item in data.get("pending_approvals", [])])]
        elif kind == "evening":
            sections = [self._section("Incomplete tasks", [("work_task", item, item.get("title", "")) for item in data.get("priority_tasks", [])]), self._section("New commitments", [("work_commitment", item, item.get("title", "")) for item in data.get("unresolved_commitments", [])]), self._section("Unanswered communications", [("gmail_message", item, item.get("subject") or item.get("snippet") or "Unread message") for item in data.get("emails_requiring_attention", [])]), self._section("Meeting follow-ups", [("meeting_claim", item, item.get("text", "")) for item in data.get("recent_meeting_actions", [])])]
        else:
            projects = self.work.list_projects(data["owner"], limit=100); tasks = self.work.list_tasks(data["owner"], due_before=self.clock(), limit=100); sources = self.knowledge.list_sources(data["owner"], limit=50)["sources"]
            sections = [self._section("Project progress", [("work_project", item, item.get("title", "")) for item in projects]), self._section("Overdue tasks", [("work_task", item, item.get("title", "")) for item in tasks]), self._section("Important decisions", [("meeting_claim", item, item.get("text", "")) for item in data.get("recent_meeting_actions", []) if item.get("kind") == "decision"]), self._section("Knowledge added", [("knowledge_source", item, item.get("title", "")) for item in sources])]
        source_count = sum(len(section["sources"]) for section in sections)
        return {"kind": kind, "generated_at": self.clock().isoformat(), "sections": sections, "source_grounded": True, "source_count": source_count, "missing_sources": [key for key, value in data.get("source_status", {}).items() if value != "connected"]}

    async def briefing(self, owner: str, *, kind: str, timezone_name: Optional[str] = None) -> dict[str, Any]:
        if kind not in {"morning", "evening", "weekly"}: raise ValueError("briefing kind is invalid")
        data = await self.today(owner, timezone_name=timezone_name); data["owner"] = owner
        return self._compose_briefing(kind, data)

    @staticmethod
    def _period_key(kind: str, generated: datetime) -> str:
        if kind == "weekly":
            year, week, _ = generated.isocalendar()
            return f"{year}-W{week:02d}"
        return generated.date().isoformat()

    @staticmethod
    def _briefing_dict(row: ExecutiveBriefingRun) -> dict[str, Any]:
        content = json.loads(row.content_json)
        return {**content, "id": row.id, "period_key": row.period_key, "timezone": row.timezone, "source_digest": row.source_digest, "saved": True}

    async def generate_briefing(self, owner: str, *, kind: str, timezone_name: Optional[str] = None) -> dict[str, Any]:
        briefing = await self.briefing(owner, kind=kind, timezone_name=timezone_name)
        canonical = json.dumps(briefing, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        evidence = json.dumps(
            {
                "kind": briefing["kind"],
                "missing_sources": briefing["missing_sources"],
                "sections": briefing["sections"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        generated = self.clock(); period = self._period_key(kind, generated)
        key = hashlib.sha256(f"{owner}|{kind}|{period}|{digest}".encode()).hexdigest()
        db = self.sessions()
        try:
            existing = db.query(ExecutiveBriefingRun).filter(ExecutiveBriefingRun.idempotency_key == key, ExecutiveBriefingRun.owner == str(owner or "")).first()
            if existing is not None:
                return self._briefing_dict(existing)
            row = ExecutiveBriefingRun(id=uuid.uuid4().hex, owner=str(owner or ""), kind=kind, period_key=period, timezone=str(timezone_name or "UTC"), source_digest=digest, idempotency_key=key, content_json=canonical, generated_at=generated.replace(tzinfo=None) if generated.tzinfo else generated)
            db.add(row); db.commit(); db.refresh(row)
            return self._briefing_dict(row)
        finally:
            db.close()

    def list_briefings(self, owner: str, *, kind: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        db = self.sessions()
        try:
            query = db.query(ExecutiveBriefingRun).filter(ExecutiveBriefingRun.owner == str(owner or ""))
            if kind:
                query = query.filter(ExecutiveBriefingRun.kind == kind)
            rows = query.order_by(ExecutiveBriefingRun.generated_at.desc()).limit(max(1, min(limit, 200))).all()
            return [self._briefing_dict(row) for row in rows]
        finally:
            db.close()

    def get_briefing(self, owner: str, briefing_id: str) -> Optional[dict[str, Any]]:
        db = self.sessions()
        try:
            row = db.query(ExecutiveBriefingRun).filter(ExecutiveBriefingRun.id == briefing_id, ExecutiveBriefingRun.owner == str(owner or "")).first()
            return self._briefing_dict(row) if row is not None else None
        finally:
            db.close()

    def metrics(self, owner: str, *, days: int = 30) -> dict[str, Any]:
        bounded_days = max(1, min(int(days), 365)); since = self.clock() - timedelta(days=bounded_days)
        naive_since = since.replace(tzinfo=None) if since.tzinfo else since
        work = self.work.operating_metrics(owner, since=naive_since)
        approvals = self.actions.operating_metrics(owner, since=naive_since)
        return {"period_days": bounded_days, "since": since.isoformat(), "work": work, "approvals": approvals, "attention_returned_items": work["attention_returned_items"] + approvals["verified"], "attention_returned_minutes": work["attention_returned_minutes"], "measurement_note": "Minutes use recorded actual time when available, otherwise task estimates; verified approvals count as returned attention items, not minutes."}


_executive_service: Optional[ExecutiveService] = None


def get_executive_service() -> ExecutiveService:
    global _executive_service
    if _executive_service is None: _executive_service = ExecutiveService()
    return _executive_service
