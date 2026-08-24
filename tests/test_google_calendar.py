"""Google Calendar normalization, scheduling, and verification tests."""

from __future__ import annotations

import pytest

from services.google_calendar import (
    CALENDAR_EVENTS_READ,
    CALENDAR_EVENTS_WRITE,
    CALENDAR_FREEBUSY,
    CalendarSyncTokenExpired,
    CalendarValidationError,
    GoogleCalendarService,
    build_event_body,
    normalize_event,
)
from src.google_connection import GoogleConfigurationError, GoogleProviderError


def _provider_event(
    *,
    event_id="event-1",
    title="Board meeting",
    start="2026-07-20T10:00:00+01:00",
    end="2026-07-20T11:00:00+01:00",
    attendees=None,
):
    return {
        "id": event_id,
        "etag": '"etag-1"',
        "status": "confirmed",
        "summary": title,
        "description": "Review the quarter",
        "location": "Dublin",
        "htmlLink": "https://calendar.google.com/event?eid=opaque",
        "created": "2026-07-18T10:00:00Z",
        "updated": "2026-07-18T11:00:00Z",
        "start": {"dateTime": start, "timeZone": "Europe/Dublin"},
        "end": {"dateTime": end, "timeZone": "Europe/Dublin"},
        "attendees": attendees
        or [
            {
                "email": "alice@example.com",
                "responseStatus": "accepted",
                "self": True,
            },
            {"email": "bob@example.com", "responseStatus": "needsAction"},
        ],
        "visibility": "private",
        "transparency": "opaque",
        "reminders": {"useDefault": True},
        "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=4"],
        "sequence": 2,
        "iCalUID": "event-1@example.com",
    }


class _Connections:
    def __init__(self, scopes=None):
        self.scopes = list(
            scopes
            or (
                CALENDAR_EVENTS_READ,
                CALENDAR_EVENTS_WRITE,
                CALENDAR_FREEBUSY,
            )
        )
        self.calls = []
        self.responses = []

    def get_connection(self, owner, connection_id):
        assert owner == "alice"
        assert connection_id == "google-1"
        return {
            "granted_scopes": self.scopes,
            "email": "alice@example.com",
        }

    async def authorized_request_json(self, owner, connection_id, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"Unexpected Calendar call: {kwargs}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _event_command():
    return {
        "title": "Board meeting",
        "description": "Review the quarter",
        "location": "Dublin",
        "start": {
            "dateTime": "2026-07-20T10:00:00+01:00",
            "timeZone": "Europe/Dublin",
        },
        "end": {
            "dateTime": "2026-07-20T11:00:00+01:00",
            "timeZone": "Europe/Dublin",
        },
        "attendees": ["bob@example.com"],
        "visibility": "private",
        "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=4"],
        "reminders": {
            "use_default": False,
            "overrides": [{"method": "popup", "minutes": 30}],
        },
    }


def test_normalized_event_retains_sync_and_provider_fields():
    event = normalize_event(_provider_event(), calendar_id="primary")

    assert event["provider"] == "google"
    assert event["external_id"] == "event-1"
    assert event["calendar_id"] == "primary"
    assert event["etag"] == '"etag-1"'
    assert event["original_timezone"] == "Europe/Dublin"
    assert event["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=4"]
    assert event["attendees"][0]["response_status"] == "accepted"
    assert event["visibility"] == "private"


def test_event_builder_supports_all_day_recurrence_reminders_and_video():
    body = build_event_body(
        {
            "title": "Annual leave",
            "start": {"date": "2026-08-01"},
            "end": {"date": "2026-08-04"},
            "recurrence": ["RRULE:FREQ=YEARLY;COUNT=2"],
            "reminders": {
                "use_default": False,
                "overrides": [{"method": "email", "minutes": 1440}],
            },
            "create_video_call": True,
            "status": "tentative",
        }
    )

    assert body["start"] == {"date": "2026-08-01"}
    assert body["end"] == {"date": "2026-08-04"}
    assert body["conferenceData"]["createRequest"]["requestId"]
    assert body["reminders"]["overrides"] == [
        {"method": "email", "minutes": 1440}
    ]
    assert body["status"] == "tentative"


@pytest.mark.parametrize(
    "changes",
    (
        {"start": {"dateTime": "2026-01-01T10:00:00"}},
        {
            "start": {"date": "2026-01-02"},
            "end": {"date": "2026-01-01"},
        },
        {"recurrence": ["DROP TABLE events"]},
        {"attendees": ["not-an-email"]},
    ),
)
def test_event_builder_rejects_ambiguous_or_invalid_commands(changes):
    command = {
        "title": "Test",
        "start": {"date": "2026-01-01"},
        "end": {"date": "2026-01-02"},
    }
    command.update(changes)
    with pytest.raises(CalendarValidationError):
        build_event_body(command)


@pytest.mark.asyncio
async def test_create_event_reads_back_and_verifies_exact_fields():
    connections = _Connections()
    connections.responses.extend(
        [
            {"id": "event-1", "etag": '"etag-1"'},
            _provider_event(),
        ]
    )
    calendar = GoogleCalendarService(connections)

    result = await calendar.create_event(
        "alice",
        "google-1",
        calendar_id="primary",
        send_updates="all",
        **_event_command(),
    )

    assert result["verification"]["status"] == "verified"
    assert result["verification"]["read_back_id"] == "event-1"
    assert connections.calls[0]["method"] == "POST"
    assert connections.calls[0]["params"]["sendUpdates"] == "all"
    assert connections.calls[1]["method"] == "GET"


@pytest.mark.asyncio
async def test_incremental_sync_uses_cursor_without_incompatible_query_fields():
    connections = _Connections(scopes=(CALENDAR_EVENTS_READ,))
    deleted = _provider_event()
    deleted["status"] = "cancelled"
    connections.responses.append(
        {"items": [deleted], "nextSyncToken": "next-sync-cursor"}
    )
    calendar = GoogleCalendarService(connections)

    result = await calendar.sync_events(
        "alice", "google-1", sync_token="sync-cursor", max_results=500
    )

    assert result["events"][0]["status"] == "cancelled"
    assert result["next_sync_token"] == "next-sync-cursor"
    assert connections.calls[0]["params"] == {
        "syncToken": "sync-cursor",
        "showDeleted": True,
        "singleEvents": True,
        "maxResults": 500,
    }


@pytest.mark.asyncio
async def test_expired_incremental_sync_cursor_requests_a_full_resync():
    connections = _Connections(scopes=(CALENDAR_EVENTS_READ,))
    connections.responses.append(GoogleProviderError("gone", status_code=410))
    calendar = GoogleCalendarService(connections)

    with pytest.raises(CalendarSyncTokenExpired) as caught:
        await calendar.sync_events(
            "alice", "google-1", sync_token="expired-cursor"
        )

    assert caught.value.status_code == 410


@pytest.mark.asyncio
async def test_update_uses_etag_and_reports_readback_mismatch():
    connections = _Connections()
    connections.responses.extend(
        [
            {"id": "event-1"},
            _provider_event(title="Provider changed title"),
        ]
    )
    calendar = GoogleCalendarService(connections)

    result = await calendar.update_event(
        "alice",
        "google-1",
        "event-1",
        etag='"etag-1"',
        **_event_command(),
    )

    assert connections.calls[0]["extra_headers"] == {"If-Match": '"etag-1"'}
    assert result["verification"]["status"] == "mismatch"


@pytest.mark.asyncio
async def test_delete_verifies_provider_not_found_readback():
    connections = _Connections()
    connections.responses.extend(
        [
            {},
            GoogleProviderError("not found", status_code=404),
        ]
    )
    calendar = GoogleCalendarService(connections)

    result = await calendar.delete_event(
        "alice", "google-1", "event-1", etag='"etag-1"'
    )

    assert result["verification"]["status"] == "verified"
    assert result["verification"]["read_back"] == "not_found"
    assert connections.calls[0]["method"] == "DELETE"


@pytest.mark.asyncio
async def test_invitation_response_updates_only_connected_attendee():
    connections = _Connections()
    accepted = _provider_event()
    connections.responses.extend([_provider_event(), accepted])
    calendar = GoogleCalendarService(connections)

    result = await calendar.respond_to_invitation(
        "alice",
        "google-1",
        "event-1",
        response_status="accepted",
        comment="Thank you",
    )

    attendees = connections.calls[1]["json_body"]["attendees"]
    alice = next(item for item in attendees if item["email"] == "alice@example.com")
    assert alice["responseStatus"] == "accepted"
    assert alice["comment"] == "Thank you"
    assert result["verification"]["status"] == "verified"


@pytest.mark.asyncio
async def test_find_free_time_respects_workday_busy_intervals_and_buffers():
    connections = _Connections(scopes=(CALENDAR_FREEBUSY,))
    connections.responses.append(
        {
            "timeMin": "2026-07-20T08:00:00Z",
            "timeMax": "2026-07-20T17:00:00Z",
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2026-07-20T09:30:00+01:00",
                            "end": "2026-07-20T10:30:00+01:00",
                        },
                        {
                            "start": "2026-07-20T13:00:00+01:00",
                            "end": "2026-07-20T14:00:00+01:00",
                        },
                    ]
                }
            },
        }
    )
    calendar = GoogleCalendarService(connections)

    slots = await calendar.find_free_time(
        "alice",
        "google-1",
        calendar_ids=["primary"],
        time_min="2026-07-20T08:00:00Z",
        time_max="2026-07-20T17:00:00Z",
        duration_minutes=60,
        timezone_name="Europe/Dublin",
        workday_start="09:00",
        workday_end="17:30",
        buffer_before_minutes=15,
        buffer_after_minutes=15,
    )

    assert slots[0] == {
        "start": "2026-07-20T10:45:00+01:00",
        "end": "2026-07-20T11:45:00+01:00",
        "timezone": "Europe/Dublin",
    }
    assert slots[1]["start"] == "2026-07-20T11:15:00+01:00"
    assert all(slot["start"] != "2026-07-20T09:00:00+01:00" for slot in slots)


@pytest.mark.asyncio
async def test_conflict_detection_accounts_for_preparation_and_recovery_buffers():
    connections = _Connections(scopes=(CALENDAR_FREEBUSY,))
    connections.responses.append(
        {
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2026-07-20T09:30:00+01:00",
                            "end": "2026-07-20T10:00:00+01:00",
                        }
                    ]
                }
            }
        }
    )
    calendar = GoogleCalendarService(connections)

    result = await calendar.detect_conflicts(
        "alice",
        "google-1",
        calendar_ids=["primary"],
        start={"dateTime": "2026-07-20T10:15:00+01:00"},
        end={"dateTime": "2026-07-20T11:00:00+01:00"},
        timezone_name="Europe/Dublin",
        buffer_before_minutes=30,
    )

    assert result["has_conflicts"] is True
    assert result["conflicts"][0]["calendar_id"] == "primary"
    assert connections.calls[0]["json_body"]["timeMin"] == "2026-07-20T09:45:00+01:00"


@pytest.mark.asyncio
async def test_missing_write_scope_fails_before_provider_call():
    connections = _Connections(scopes=(CALENDAR_EVENTS_READ,))
    calendar = GoogleCalendarService(connections)

    with pytest.raises(GoogleConfigurationError):
        await calendar.create_event(
            "alice", "google-1", **_event_command()
        )
    assert connections.calls == []
