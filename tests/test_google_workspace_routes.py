"""ASGI contract tests for owner-scoped Google Workspace routes."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from routes.google_workspace_routes import setup_google_workspace_routes
from src.auth_helpers import require_user
from services.google_calendar import CalendarSyncTokenExpired


class _FakeGmail:
    def __init__(self) -> None:
        self.calls = []

    async def send_message(self, owner, connection_id, **command):
        self.calls.append(("send_message", owner, connection_id, command))
        return {"verification": {"status": "verified"}}

    async def read_message(self, owner, connection_id, message_id):
        self.calls.append(("read_message", owner, connection_id, message_id))
        return {
            "id": message_id,
            "attachments": [
                {
                    "attachment_id": "a-1",
                    "filename": "../../quarterly plan.pdf",
                    "mime_type": "application/pdf",
                }
            ],
        }

    async def get_attachment(self, owner, connection_id, message_id, attachment_id):
        self.calls.append(
            ("get_attachment", owner, connection_id, message_id, attachment_id)
        )
        return b"%PDF-safe-test"


class _FakeCalendar:
    def __init__(self) -> None:
        self.calls = []
        self.expire_sync = False

    async def create_event(self, owner, connection_id, **command):
        self.calls.append(("create_event", owner, connection_id, command))
        return {"verification": {"status": "verified"}}

    async def sync_events(self, owner, connection_id, **command):
        self.calls.append(("sync_events", owner, connection_id, command))
        if self.expire_sync:
            raise CalendarSyncTokenExpired()
        return {"events": [], "next_sync_token": "next"}


@pytest.fixture
def route_environment():
    gmail = _FakeGmail()
    calendar = _FakeCalendar()
    owner = {"value": "alice"}
    app = FastAPI()
    app.dependency_overrides[require_user] = lambda: owner["value"]
    app.include_router(setup_google_workspace_routes(gmail, calendar))
    return app, gmail, calendar, owner


@pytest.mark.asyncio
async def test_email_send_requires_literal_confirmation_and_passes_trusted_owner(
    route_environment,
):
    app, gmail, _, owner = route_environment
    transport = httpx.ASGITransport(app=app)
    path = "/api/integrations/google/connections/google-1/gmail/messages/send"
    message = {
        "to": "bob@example.com",
        "subject": "Quarterly plan",
        "body": "Ready for review.",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(path, json=message)
        assert rejected.status_code == 422
        assert gmail.calls == []

        sent = await client.post(path, json={**message, "confirm": True})
        assert sent.status_code == 200
        assert gmail.calls[0][1:3] == ("alice", "google-1")
        assert "confirm" not in gmail.calls[0][3]

        owner["value"] = "bob"
        read = await client.get(
            "/api/integrations/google/connections/google-1/gmail/messages/m-1"
        )
        assert read.status_code == 200
        assert gmail.calls[-1][1] == "bob"


@pytest.mark.asyncio
async def test_calendar_create_is_confirmed_and_strips_transport_fields(
    route_environment,
):
    app, _, calendar, _ = route_environment
    transport = httpx.ASGITransport(app=app)
    path = (
        "/api/integrations/google/connections/google-1/calendar/"
        "calendars/primary/events"
    )
    event = {
        "title": "Board meeting",
        "start": {"dateTime": "2026-07-20T10:00:00+01:00"},
        "end": {"dateTime": "2026-07-20T11:00:00+01:00"},
        "send_updates": "all",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post(path, json=event)).status_code == 422
        created = await client.post(path, json={**event, "confirm": True})

    assert created.status_code == 201
    command = calendar.calls[0][3]
    assert command["send_updates"] == "all"
    assert command["calendar_id"] == "primary"
    assert "confirm" not in command


@pytest.mark.asyncio
async def test_expired_calendar_sync_maps_to_recoverable_conflict(route_environment):
    app, _, calendar, _ = route_environment
    calendar.expire_sync = True
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/integrations/google/connections/google-1/calendar/"
            "calendars/primary/sync",
            json={"sync_token": "expired"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "calendar_sync_token_expired"


@pytest.mark.asyncio
async def test_attachment_download_confines_provider_filename(route_environment):
    app, _, _, _ = route_environment
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/integrations/google/connections/google-1/gmail/messages/"
            "m-1/attachments/a-1"
        )

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "quarterly%20plan.pdf" in disposition
    assert ".." not in disposition
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == b"%PDF-safe-test"
