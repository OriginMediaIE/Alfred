"""Executive dashboard composition stays source-based and provider-degradable."""

from datetime import datetime, timezone
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from routes.dashboard_routes import setup_dashboard_routes
from services.executive_service import ExecutiveService
from src.auth_helpers import require_user


class Work:
    def daily_focus(self, owner, **kwargs): return {"tasks": [{"id": "t1", "title": "Ship brief"}], "date": "2026-07-18"}
    def list_commitments(self, owner, **kwargs): return [{"id": "c1", "title": "Send proposal"}]
    def pending_reminders(self, owner, **kwargs): return [{"id": "r1", "message": "Renew policy"}]
    def list_projects(self, owner, **kwargs): return [{"id": "p1", "title": "Apollo"}]
    def list_tasks(self, owner, **kwargs): return [{"id": "t2", "title": "Overdue item"}]
    def operating_metrics(self, owner, **kwargs): return {"completed_tasks": 3, "fulfilled_commitments": 1, "attention_returned_items": 4, "attention_returned_minutes": 95, "minutes_are_estimated": True}


class Meetings:
    def list_meetings(self, owner, **kwargs): return {"meetings": [{"id": "m1", "title": "Review"}]}
    def get_meeting(self, owner, meeting_id): return {"claims": [{"id": "claim1", "kind": "decision", "text": "Ship Friday", "fact_state": "confirmed"}]}


class Knowledge:
    def list_sources(self, owner, **kwargs): return {"sources": [{"id": "s1", "title": "Roadmap"}]}


class Actions:
    def list_actions(self, owner, **kwargs): return [{"id": "a1", "tool_name": "send_gmail", "approval_reason": "Send update"}]
    def operating_metrics(self, owner, **kwargs): return {"proposed": 5, "accepted": 4, "rejected": 1, "pending": 0, "succeeded": 3, "verified": 3, "proposal_acceptance_rate": 0.8}


class Connections:
    def __init__(self, connected=True): self.connected = connected
    def list_connections(self, owner): return [{"id": "g1", "email": "alice@example.com", "status": "connected", "selected_calendars": ["primary"]}] if self.connected else []


class Calendar:
    async def list_events(self, *args, **kwargs): return {"events": [{"id": "e1", "summary": "Leadership call", "start": {"dateTime": "2026-07-18T15:00:00+01:00"}}]}


class Gmail:
    async def search_messages(self, *args, **kwargs): return {"messages": [{"id": "mail1", "subject": "Needs review"}]}


def service(connected=True):
    return ExecutiveService(work=Work(), meetings=Meetings(), knowledge=Knowledge(), actions=Actions(), connections=Connections(connected), calendar=Calendar(), gmail=Gmail(), clock=lambda: datetime(2026, 7, 18, 10, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_today_contains_every_required_executive_signal():
    result = await service().today("alice", timezone_name="Europe/Dublin", now=datetime(2026, 7, 18, 11, tzinfo=timezone.utc))
    assert result["date"] == "2026-07-18"
    assert result["next_event"]["summary"] == "Leadership call"
    assert result["priority_tasks"][0]["title"] == "Ship brief"
    assert result["emails_requiring_attention"][0]["subject"] == "Needs review"
    assert result["pending_approvals"][0]["tool_name"] == "send_gmail"
    assert result["unresolved_commitments"][0]["title"] == "Send proposal"
    assert result["recent_meeting_actions"][0]["text"] == "Ship Friday"
    assert result["important_reminders"][0]["message"] == "Renew policy"
    assert result["weather"]["status"] == "not_configured"
    assert result["daily_briefing"]["source_grounded"] is True


@pytest.mark.asyncio
async def test_disconnected_google_is_an_explicit_empty_degraded_state():
    result = await service(False).today("alice", timezone_name="UTC")
    assert result["schedule"] == []
    assert result["emails_requiring_attention"] == []
    assert result["integration_health"][0]["gmail"] == "not_configured"
    assert result["source_status"]["google_workspace"] == "not_configured"


@pytest.mark.asyncio
async def test_briefings_carry_source_references_and_transparent_metrics():
    executive = service()
    briefing = await executive.briefing("alice", kind="morning")
    metrics = executive.metrics("alice", days=30)

    assert briefing["source_grounded"] is True
    assert briefing["source_count"] == 5
    assert briefing["sections"][0]["sources"][0] == {
        "type": "google_calendar",
        "id": "e1",
        "label": "Leadership call",
        "url": "",
    }
    assert metrics["attention_returned_items"] == 7
    assert metrics["attention_returned_minutes"] == 95
    assert metrics["approvals"]["proposal_acceptance_rate"] == 0.8


@pytest.mark.asyncio
async def test_briefing_runs_are_durable_idempotent_and_owner_scoped():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    executive = ExecutiveService(
        work=Work(), meetings=Meetings(), knowledge=Knowledge(), actions=Actions(),
        connections=Connections(), calendar=Calendar(), gmail=Gmail(),
        clock=lambda: datetime(2026, 7, 18, 10, tzinfo=timezone.utc),
        session_factory=factory,
    )
    try:
        first = await executive.generate_briefing(
            "alice", kind="morning", timezone_name="Europe/Dublin"
        )
        second = await executive.generate_briefing(
            "alice", kind="morning", timezone_name="Europe/Dublin"
        )

        assert first["id"] == second["id"]
        assert executive.list_briefings("alice")[0]["source_count"] == 5
        assert executive.get_briefing("bob", first["id"]) is None

        app = FastAPI()
        app.dependency_overrides[require_user] = lambda: "alice"
        app.include_router(setup_dashboard_routes(executive))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            generated = await client.post(
                "/api/dashboard/briefings/morning/runs",
                json={"timezone": "Europe/Dublin"},
            )
            history = await client.get("/api/dashboard/briefings/runs")
            metrics = await client.get("/api/dashboard/metrics", params={"days": 30})
        assert generated.status_code == 201
        assert history.json()["briefings"][0]["id"] == first["id"]
        assert metrics.json()["approvals"]["proposal_acceptance_rate"] == 0.8
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_today_and_all_review_routes_are_owner_scoped():
    app = FastAPI(); app.dependency_overrides[require_user] = lambda: "alice"; app.include_router(setup_dashboard_routes(service()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        today = await client.get("/api/dashboard/today", params={"timezone": "Europe/Dublin"})
        assert today.status_code == 200
        for kind in ("morning", "evening", "weekly"):
            response = await client.get(f"/api/dashboard/briefings/{kind}")
            assert response.status_code == 200
            assert response.json()["kind"] == kind
