"""Canonical Google Workspace tool routing and safety tests."""

from __future__ import annotations

import json
import os

import pytest

from src.tools import google_workspace as tools


class _Connections:
    def __init__(self, count=1):
        self.rows = [
            {
                "id": f"google-{index + 1}",
                "status": "connected",
                "default_calendar": "primary",
                "selected_calendars": ["primary"],
                "timezone": "Europe/Dublin",
            }
            for index in range(count)
        ]

    def list_connections(self, owner):
        assert owner == "alice"
        return list(self.rows)

    def get_connection(self, owner, connection_id):
        assert owner == "alice"
        return next(item for item in self.rows if item["id"] == connection_id)


class _Gmail:
    def __init__(self):
        self.calls = []

    async def search_messages(self, owner, connection_id, **kwargs):
        self.calls.append(("search", owner, connection_id, kwargs))
        return {"messages": [{"id": "m-1"}], "next_page_token": None}

    async def send_message(self, owner, connection_id, **kwargs):
        self.calls.append(("send", owner, connection_id, kwargs))
        return {
            "message": {"id": "m-1"},
            "verification": {
                "status": "verified",
                "provider": "gmail",
                "read_back_id": "m-1",
            },
        }

    async def get_attachment(self, owner, connection_id, message_id, attachment_id):
        self.calls.append(("attachment", owner, connection_id, message_id, attachment_id))
        return b"verified attachment"


class _Calendar:
    def __init__(self):
        self.calls = []

    async def create_event(self, owner, connection_id, **kwargs):
        self.calls.append(("create", owner, connection_id, kwargs))
        return {
            "event": {"external_id": "event-1", "status": kwargs.get("status")},
            "verification": {
                "status": "verified",
                "provider": "google_calendar",
                "read_back_id": "event-1",
            },
        }

    async def find_free_time(self, owner, connection_id, **kwargs):
        self.calls.append(("free", owner, connection_id, kwargs))
        return [{"start": "2026-07-20T10:00:00+01:00"}]


@pytest.fixture
def provider_env(monkeypatch):
    connections = _Connections()
    gmail = _Gmail()
    calendar = _Calendar()
    monkeypatch.setattr(tools, "get_google_connection_service", lambda: connections)
    monkeypatch.setattr(tools, "get_google_gmail_service", lambda: gmail)
    monkeypatch.setattr(tools, "get_google_calendar_service", lambda: calendar)
    return connections, gmail, calendar


@pytest.mark.asyncio
async def test_query_gmail_selects_only_unambiguous_owned_connection(provider_env):
    _, gmail, _ = provider_env

    result = await tools.do_query_gmail(
        json.dumps(
            {
                "action": "search_messages",
                "query": "is:unread",
                "max_results": 5,
            }
        ),
        owner="alice",
    )

    assert result["exit_code"] == 0
    assert result["messages"] == [{"id": "m-1"}]
    assert gmail.calls[0][1:3] == ("alice", "google-1")
    assert gmail.calls[0][3]["query"] == "is:unread"
    assert "access_token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_implicit_account_selection_fails_when_multiple_accounts_exist(
    provider_env, monkeypatch
):
    _, gmail, _ = provider_env
    monkeypatch.setattr(tools, "get_google_connection_service", lambda: _Connections(2))

    result = await tools.do_query_gmail(
        '{"action":"search_messages"}', owner="alice"
    )

    assert result["exit_code"] == 1
    assert "choose connection_id" in result["error"]
    assert gmail.calls == []


@pytest.mark.asyncio
async def test_send_gmail_requires_claim_before_provider_call(provider_env, monkeypatch):
    _, gmail, _ = provider_env
    content = json.dumps(
        {
            "action": "send_message",
            "to": "bob@example.com",
            "subject": "Plan",
            "body": "Ready.",
        }
    )
    denied = await tools.do_send_gmail(content, owner="alice")
    assert denied["exit_code"] == 1
    assert gmail.calls == []

    claims = []
    monkeypatch.setattr(
        tools,
        "_require_claimed_action",
        lambda owner, expected_tool, **kwargs: claims.append(
            (owner, expected_tool, kwargs)
        ),
    )
    sent = await tools.do_send_gmail(
        content,
        owner="alice",
        approval_action_id="action-1",
        request_id="request-1",
    )

    assert sent["verification"]["status"] == "verified"
    assert claims[0][0:2] == ("alice", "send_gmail")
    assert gmail.calls[0][0] == "send"


@pytest.mark.asyncio
async def test_calendar_hold_is_forced_tentative_and_cannot_notify_attendees(
    provider_env, monkeypatch
):
    _, _, calendar = provider_env
    monkeypatch.setattr(tools, "_require_claimed_action", lambda *args, **kwargs: None)
    result = await tools.do_create_google_calendar_hold(
        json.dumps(
            {
                "action": "create_hold",
                "title": "Focus",
                "start": {"dateTime": "2026-07-20T10:00:00+01:00"},
                "end": {"dateTime": "2026-07-20T11:00:00+01:00"},
            }
        ),
        owner="alice",
        approval_action_id="action-1",
        request_id="request-1",
    )

    assert result["verification"]["status"] == "verified"
    command = calendar.calls[0][3]
    assert command["status"] == "tentative"
    assert command["send_updates"] == "none"
    assert "attendees" not in command
    assert "recurrence" not in command


@pytest.mark.asyncio
async def test_calendar_free_time_uses_saved_calendar_and_timezone(provider_env):
    _, _, calendar = provider_env
    result = await tools.do_query_google_calendar(
        json.dumps(
            {
                "action": "find_free_time",
                "time_min": "2026-07-20T08:00:00Z",
                "time_max": "2026-07-20T17:00:00Z",
                "duration_minutes": 60,
            }
        ),
        owner="alice",
    )

    assert result["slots"][0]["start"].endswith("+01:00")
    kwargs = calendar.calls[0][3]
    assert kwargs["calendar_ids"] == ["primary"]
    assert kwargs["timezone_name"] == "Europe/Dublin"


@pytest.mark.asyncio
async def test_attachment_download_is_exclusive_private_and_read_back_verified(
    provider_env, monkeypatch, tmp_path
):
    _, gmail, _ = provider_env
    monkeypatch.setattr(tools, "_require_claimed_action", lambda *args, **kwargs: None)
    destination = tmp_path / "attachment.txt"
    content = json.dumps(
        {
            "action": "download",
            "message_id": "m-1",
            "attachment_id": "a-1",
            "path": str(destination),
        }
    )

    result = await tools.do_download_gmail_attachment(
        content,
        owner="alice",
        approval_action_id="action-1",
        request_id="request-1",
    )
    replay = await tools.do_download_gmail_attachment(
        content,
        owner="alice",
        approval_action_id="action-2",
        request_id="request-2",
    )

    assert result["verification"]["status"] == "verified"
    assert destination.read_bytes() == b"verified attachment"
    assert os.stat(destination).st_mode & 0o777 == 0o600
    assert replay["exit_code"] == 1
    assert "exist" in replay["error"].lower()
    assert len(gmail.calls) == 2  # provider reads happened, but the second write did not overwrite
