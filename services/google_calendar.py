"""Google Calendar API adapter and normalized scheduling primitives."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from email.utils import parseaddr
import re
import secrets
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.google_connection import (
    GoogleConfigurationError,
    GoogleConnectionService,
    GoogleProviderError,
    get_google_connection_service,
)


CALENDAR_API = "https://www.googleapis.com/calendar/v3"
CALENDAR_EVENTS_READ = "https://www.googleapis.com/auth/calendar.events.readonly"
CALENDAR_EVENTS_WRITE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_READ = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
CALENDAR_FREEBUSY = "https://www.googleapis.com/auth/calendar.freebusy"

_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")


class CalendarValidationError(ValueError):
    """A calendar command is invalid or ambiguous."""


class CalendarSyncTokenExpired(GoogleProviderError):
    """The provider rejected an incremental-sync cursor and needs a full sync."""

    code = "calendar_sync_token_expired"

    def __init__(self) -> None:
        super().__init__(
            "Google Calendar sync token expired; perform a new full sync.",
            status_code=410,
        )


def _calendar_id(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 1024 or any(ord(c) < 32 for c in normalized):
        raise CalendarValidationError("calendar_id is invalid.")
    return normalized


def _event_id(value: object) -> str:
    normalized = str(value or "").strip()
    if not _EVENT_ID_RE.fullmatch(normalized):
        raise CalendarValidationError("event_id is invalid.")
    return normalized


def _parse_rfc3339(value: object, *, field: str) -> datetime:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CalendarValidationError(f"{field} must be RFC3339.") from exc
    if parsed.tzinfo is None:
        raise CalendarValidationError(f"{field} must include a timezone offset.")
    return parsed


def _rfc3339(value: datetime) -> str:
    encoded = value.isoformat()
    return encoded[:-6] + "Z" if encoded.endswith("+00:00") else encoded


def _validate_timezone(value: object) -> str:
    name = str(value or "UTC").strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CalendarValidationError("timezone must be a valid IANA name.") from exc
    return name


def _event_time(value: object, *, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise CalendarValidationError(f"{field} must be an object.")
    date_time = str(value.get("dateTime") or value.get("date_time") or "").strip()
    all_day = str(value.get("date") or "").strip()
    if bool(date_time) == bool(all_day):
        raise CalendarValidationError(
            f"{field} must contain exactly one of dateTime or date."
        )
    if date_time:
        _parse_rfc3339(date_time, field=f"{field}.dateTime")
        result = {"dateTime": date_time}
        if value.get("timeZone") or value.get("timezone"):
            result["timeZone"] = _validate_timezone(
                value.get("timeZone") or value.get("timezone")
            )
        return result
    try:
        date.fromisoformat(all_day)
    except ValueError as exc:
        raise CalendarValidationError(f"{field}.date must be YYYY-MM-DD.") from exc
    return {"date": all_day}


def _validate_interval(start: Mapping[str, str], end: Mapping[str, str]) -> None:
    if ("date" in start) != ("date" in end):
        raise CalendarValidationError("start and end must both be all-day or timed.")
    if "date" in start:
        start_value = date.fromisoformat(start["date"])
        end_value = date.fromisoformat(end["date"])
    else:
        start_value = _parse_rfc3339(start["dateTime"], field="start.dateTime")
        end_value = _parse_rfc3339(end["dateTime"], field="end.dateTime")
    if end_value <= start_value:
        raise CalendarValidationError("event end must be after start.")


def _attendees(values: object) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise CalendarValidationError("attendees must be a list.")
    if len(values) > 200:
        raise CalendarValidationError("attendees cannot exceed 200 entries.")
    result = []
    seen = set()
    for item in values:
        if isinstance(item, Mapping):
            raw = str(item.get("email") or "")
            optional = bool(item.get("optional", False))
            comment = str(item.get("comment") or "")[:1024]
        else:
            raw = str(item)
            optional = False
            comment = ""
        _name, address = parseaddr(raw)
        lowered = address.lower()
        if not address or "@" not in address or lowered in seen:
            if lowered in seen:
                continue
            raise CalendarValidationError("attendees contains an invalid email address.")
        seen.add(lowered)
        entry: dict[str, Any] = {"email": address, "optional": optional}
        if comment:
            entry["comment"] = comment
        result.append(entry)
    return result


def normalize_event(
    event: Mapping[str, Any],
    *,
    calendar_id: str,
) -> dict[str, Any]:
    start = dict(event.get("start") or {})
    end = dict(event.get("end") or {})
    attendees = []
    for attendee in event.get("attendees") or []:
        if not isinstance(attendee, Mapping):
            continue
        attendees.append(
            {
                "email": str(attendee.get("email") or ""),
                "display_name": str(attendee.get("displayName") or ""),
                "response_status": str(attendee.get("responseStatus") or "needsAction"),
                "optional": bool(attendee.get("optional", False)),
                "organizer": bool(attendee.get("organizer", False)),
                "self": bool(attendee.get("self", False)),
                "comment": str(attendee.get("comment") or ""),
            }
        )
    conference = event.get("conferenceData") or {}
    entry_points = []
    if isinstance(conference, Mapping):
        entry_points = [
            dict(item)
            for item in conference.get("entryPoints") or []
            if isinstance(item, Mapping)
        ]
    return {
        "provider": "google",
        "external_id": str(event.get("id") or ""),
        "calendar_id": calendar_id,
        "etag": str(event.get("etag") or ""),
        "status": str(event.get("status") or "confirmed"),
        "title": str(event.get("summary") or ""),
        "description": str(event.get("description") or ""),
        "location": str(event.get("location") or ""),
        "html_link": str(event.get("htmlLink") or ""),
        "created_at": str(event.get("created") or ""),
        "updated_at": str(event.get("updated") or ""),
        "start": start,
        "end": end,
        "all_day": "date" in start,
        "original_timezone": str(start.get("timeZone") or end.get("timeZone") or ""),
        "recurrence": [str(item) for item in event.get("recurrence") or []],
        "recurring_event_id": str(event.get("recurringEventId") or ""),
        "original_start_time": dict(event.get("originalStartTime") or {}),
        "attendees": attendees,
        "organizer": dict(event.get("organizer") or {}),
        "creator": dict(event.get("creator") or {}),
        "visibility": str(event.get("visibility") or "default"),
        "transparency": str(event.get("transparency") or "opaque"),
        "reminders": dict(event.get("reminders") or {}),
        "hangout_link": str(event.get("hangoutLink") or ""),
        "conference_entry_points": entry_points,
        "sequence": int(event.get("sequence") or 0),
        "i_cal_uid": str(event.get("iCalUID") or ""),
    }


def build_event_body(command: Mapping[str, Any]) -> dict[str, Any]:
    title = str(command.get("title") or command.get("summary") or "").strip()
    if not title or len(title) > 1024:
        raise CalendarValidationError("event title is required.")
    start = _event_time(command.get("start"), field="start")
    end = _event_time(command.get("end"), field="end")
    _validate_interval(start, end)
    body: dict[str, Any] = {"summary": title, "start": start, "end": end}
    for incoming, provider, limit in (
        ("description", "description", 32_000),
        ("location", "location", 2048),
        ("visibility", "visibility", 32),
        ("transparency", "transparency", 32),
        ("color_id", "colorId", 32),
        ("status", "status", 32),
    ):
        if command.get(incoming) is not None:
            body[provider] = str(command.get(incoming) or "")[:limit]
    if body.get("visibility") not in {None, "default", "public", "private", "confidential"}:
        raise CalendarValidationError("visibility is invalid.")
    if body.get("transparency") not in {None, "opaque", "transparent"}:
        raise CalendarValidationError("transparency is invalid.")
    if body.get("status") not in {None, "confirmed", "tentative"}:
        raise CalendarValidationError("status is invalid.")
    attendees = _attendees(command.get("attendees"))
    if attendees:
        body["attendees"] = attendees
    recurrence = command.get("recurrence")
    if recurrence is not None:
        if not isinstance(recurrence, Sequence) or isinstance(recurrence, (str, bytes)):
            raise CalendarValidationError("recurrence must be a list of RFC5545 lines.")
        lines = [str(item).strip() for item in recurrence]
        if len(lines) > 20 or any(
            not line.startswith(("RRULE:", "RDATE:", "EXDATE:")) or len(line) > 2048
            for line in lines
        ):
            raise CalendarValidationError("recurrence contains an invalid RFC5545 line.")
        body["recurrence"] = lines
    reminders = command.get("reminders")
    if reminders is not None:
        if not isinstance(reminders, Mapping):
            raise CalendarValidationError("reminders must be an object.")
        overrides = reminders.get("overrides") or []
        if not isinstance(overrides, list) or len(overrides) > 5:
            raise CalendarValidationError("reminder overrides cannot exceed five.")
        normalized_overrides = []
        for item in overrides:
            if not isinstance(item, Mapping):
                raise CalendarValidationError("reminder override is invalid.")
            method = str(item.get("method") or "")
            minutes = item.get("minutes")
            if method not in {"email", "popup"} or isinstance(minutes, bool):
                raise CalendarValidationError("reminder override is invalid.")
            try:
                minutes = int(minutes)
            except (TypeError, ValueError) as exc:
                raise CalendarValidationError("reminder minutes must be an integer.") from exc
            if not 0 <= minutes <= 40320:
                raise CalendarValidationError("reminder minutes are out of range.")
            normalized_overrides.append({"method": method, "minutes": minutes})
        body["reminders"] = {
            "useDefault": bool(reminders.get("use_default", reminders.get("useDefault", False))),
            "overrides": normalized_overrides,
        }
    if command.get("create_video_call"):
        body["conferenceData"] = {
            "createRequest": {
                "requestId": secrets.token_urlsafe(24),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    return body


class GoogleCalendarService:
    def __init__(self, connection_service: Optional[GoogleConnectionService] = None) -> None:
        self._connections = connection_service or get_google_connection_service()

    def _scope(self, owner, connection_id, candidates: Iterable[str]) -> str:
        granted = set(
            self._connections.get_connection(owner, connection_id)["granted_scopes"]
        )
        for candidate in candidates:
            if candidate in granted:
                return candidate
        raise GoogleConfigurationError(
            "Google connection does not grant the required Calendar capability."
        )

    async def _api(
        self,
        owner,
        connection_id,
        *,
        method: str,
        path: str,
        scopes: Iterable[str],
        params: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        accept_empty: bool = False,
    ) -> dict[str, Any]:
        scope = self._scope(owner, connection_id, scopes)
        return await self._connections.authorized_request_json(
            owner,
            connection_id,
            method=method,
            url=f"{CALENDAR_API}{path}",
            required_scopes={scope},
            params=params,
            json_body=body,
            extra_headers=headers,
            accept_empty=accept_empty,
        )

    async def list_calendars(self, owner, connection_id) -> list[dict[str, Any]]:
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path="/users/me/calendarList",
            scopes=(CALENDAR_LIST_READ, CALENDAR_EVENTS_READ, CALENDAR_EVENTS_WRITE),
        )
        output = []
        for item in result.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            output.append(
                {
                    "id": str(item.get("id") or ""),
                    "summary": str(item.get("summary") or ""),
                    "description": str(item.get("description") or ""),
                    "timezone": str(item.get("timeZone") or ""),
                    "primary": bool(item.get("primary", False)),
                    "selected": bool(item.get("selected", False)),
                    "access_role": str(item.get("accessRole") or ""),
                    "color": str(item.get("backgroundColor") or ""),
                }
            )
        return output

    async def list_events(
        self,
        owner,
        connection_id,
        *,
        calendar_id: str = "primary",
        time_min: str,
        time_max: str,
        query: str = "",
        max_results: int = 100,
        page_token: Optional[str] = None,
        sync_token: Optional[str] = None,
        show_deleted: bool = False,
    ) -> dict[str, Any]:
        calendar_id = _calendar_id(calendar_id)
        start = _parse_rfc3339(time_min, field="time_min")
        end = _parse_rfc3339(time_max, field="time_max")
        if end <= start:
            raise CalendarValidationError("time_max must be after time_min.")
        if not 1 <= int(max_results) <= 2500:
            raise CalendarValidationError("max_results must be between 1 and 2500.")
        params: dict[str, Any] = {
            "timeMin": _rfc3339(start),
            "timeMax": _rfc3339(end),
            "singleEvents": True,
            "orderBy": "startTime",
            "showDeleted": bool(show_deleted),
            "maxResults": int(max_results),
        }
        if query:
            params["q"] = str(query)[:2048]
        if page_token:
            params["pageToken"] = str(page_token)[:2048]
        if sync_token:
            # Google forbids time bounds/order/query with syncToken.  Fail
            # explicitly instead of sending a subtly invalid combination.
            raise CalendarValidationError(
                "sync_token cannot be combined with a bounded event query."
            )
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path=f"/calendars/{quote(calendar_id, safe='')}/events",
            scopes=(CALENDAR_EVENTS_READ, CALENDAR_EVENTS_WRITE),
            params=params,
        )
        return {
            "events": [
                normalize_event(item, calendar_id=calendar_id)
                for item in result.get("items") or []
                if isinstance(item, Mapping)
            ],
            "next_page_token": result.get("nextPageToken"),
            "next_sync_token": result.get("nextSyncToken"),
            "timezone": result.get("timeZone"),
            "etag": result.get("etag"),
        }

    async def sync_events(
        self,
        owner,
        connection_id,
        *,
        sync_token: str,
        calendar_id: str = "primary",
        max_results: int = 2500,
        page_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return one incremental page using a cursor from a completed full sync.

        Google forbids time bounds, ordering, and search terms alongside a sync
        token.  Keeping this as a separate operation makes invalid combinations
        impossible for both route and agent callers.
        """

        calendar_id = _calendar_id(calendar_id)
        token = str(sync_token or "").strip()
        if (
            not token
            or len(token) > 4096
            or any(ord(character) < 32 for character in token)
        ):
            raise CalendarValidationError("sync_token is invalid.")
        if not 1 <= int(max_results) <= 2500:
            raise CalendarValidationError("max_results must be between 1 and 2500.")
        params: dict[str, Any] = {
            "syncToken": token,
            "showDeleted": True,
            "singleEvents": True,
            "maxResults": int(max_results),
        }
        if page_token:
            page = str(page_token).strip()
            if len(page) > 4096 or any(ord(character) < 32 for character in page):
                raise CalendarValidationError("page_token is invalid.")
            params["pageToken"] = page
        try:
            result = await self._api(
                owner,
                connection_id,
                method="GET",
                path=f"/calendars/{quote(calendar_id, safe='')}/events",
                scopes=(CALENDAR_EVENTS_READ, CALENDAR_EVENTS_WRITE),
                params=params,
            )
        except GoogleProviderError as exc:
            if exc.status_code == 410:
                raise CalendarSyncTokenExpired() from exc
            raise
        return {
            "events": [
                normalize_event(item, calendar_id=calendar_id)
                for item in result.get("items") or []
                if isinstance(item, Mapping)
            ],
            "next_page_token": result.get("nextPageToken"),
            "next_sync_token": result.get("nextSyncToken"),
            "timezone": result.get("timeZone"),
            "etag": result.get("etag"),
        }

    async def get_event(self, owner, connection_id, calendar_id, event_id):
        calendar_id = _calendar_id(calendar_id)
        event_id = _event_id(event_id)
        result = await self._api(
            owner,
            connection_id,
            method="GET",
            path=(
                f"/calendars/{quote(calendar_id, safe='')}/events/"
                f"{quote(event_id, safe='')}"
            ),
            scopes=(CALENDAR_EVENTS_READ, CALENDAR_EVENTS_WRITE),
        )
        return normalize_event(result, calendar_id=calendar_id)

    async def create_event(
        self,
        owner,
        connection_id,
        *,
        calendar_id: str = "primary",
        send_updates: str = "none",
        **command,
    ) -> dict[str, Any]:
        calendar_id = _calendar_id(calendar_id)
        if send_updates not in {"all", "externalOnly", "none"}:
            raise CalendarValidationError("send_updates is invalid.")
        body = build_event_body(command)
        params = {
            "sendUpdates": send_updates,
            "conferenceDataVersion": 1 if "conferenceData" in body else 0,
        }
        created = await self._api(
            owner,
            connection_id,
            method="POST",
            path=f"/calendars/{quote(calendar_id, safe='')}/events",
            scopes=(CALENDAR_EVENTS_WRITE,),
            params=params,
            body=body,
        )
        return await self._verify_write(
            owner, connection_id, calendar_id, created, body
        )

    async def update_event(
        self,
        owner,
        connection_id,
        event_id: str,
        *,
        calendar_id: str = "primary",
        send_updates: str = "none",
        etag: Optional[str] = None,
        **command,
    ) -> dict[str, Any]:
        calendar_id = _calendar_id(calendar_id)
        event_id = _event_id(event_id)
        if send_updates not in {"all", "externalOnly", "none"}:
            raise CalendarValidationError("send_updates is invalid.")
        body = build_event_body(command)
        updated = await self._api(
            owner,
            connection_id,
            method="PATCH",
            path=(
                f"/calendars/{quote(calendar_id, safe='')}/events/"
                f"{quote(event_id, safe='')}"
            ),
            scopes=(CALENDAR_EVENTS_WRITE,),
            params={
                "sendUpdates": send_updates,
                "conferenceDataVersion": 1 if "conferenceData" in body else 0,
            },
            body=body,
            headers={"If-Match": etag} if etag else None,
        )
        return await self._verify_write(
            owner, connection_id, calendar_id, updated, body
        )

    async def delete_event(
        self,
        owner,
        connection_id,
        event_id: str,
        *,
        calendar_id: str = "primary",
        send_updates: str = "none",
        etag: Optional[str] = None,
    ) -> dict[str, Any]:
        calendar_id = _calendar_id(calendar_id)
        event_id = _event_id(event_id)
        await self._api(
            owner,
            connection_id,
            method="DELETE",
            path=(
                f"/calendars/{quote(calendar_id, safe='')}/events/"
                f"{quote(event_id, safe='')}"
            ),
            scopes=(CALENDAR_EVENTS_WRITE,),
            params={"sendUpdates": send_updates},
            headers={"If-Match": etag} if etag else None,
            accept_empty=True,
        )
        try:
            await self.get_event(owner, connection_id, calendar_id, event_id)
        except GoogleProviderError as exc:
            if exc.status_code in {404, 410}:
                return {
                    "event_id": event_id,
                    "calendar_id": calendar_id,
                    "verification": {
                        "status": "verified",
                        "provider": "google_calendar",
                        "read_back": "not_found",
                    },
                }
            raise
        return {
            "event_id": event_id,
            "calendar_id": calendar_id,
            "verification": {
                "status": "mismatch",
                "provider": "google_calendar",
                "read_back": "still_present",
            },
        }

    async def respond_to_invitation(
        self,
        owner,
        connection_id,
        event_id: str,
        *,
        response_status: str,
        calendar_id: str = "primary",
        comment: str = "",
    ) -> dict[str, Any]:
        if response_status not in {"accepted", "declined", "tentative", "needsAction"}:
            raise CalendarValidationError("response_status is invalid.")
        current = await self.get_event(owner, connection_id, calendar_id, event_id)
        own_email = self._connections.get_connection(owner, connection_id)["email"].lower()
        attendees = []
        found = False
        for attendee in current["attendees"]:
            entry = {"email": attendee["email"]}
            if attendee["email"].lower() == own_email or attendee.get("self"):
                entry["responseStatus"] = response_status
                if comment:
                    entry["comment"] = str(comment)[:1024]
                found = True
            elif attendee.get("response_status"):
                entry["responseStatus"] = attendee["response_status"]
            attendees.append(entry)
        if not found:
            raise CalendarValidationError(
                "Connected Google account is not an attendee of this event."
            )
        updated = await self._api(
            owner,
            connection_id,
            method="PATCH",
            path=(
                f"/calendars/{quote(_calendar_id(calendar_id), safe='')}/events/"
                f"{quote(_event_id(event_id), safe='')}"
            ),
            scopes=(CALENDAR_EVENTS_WRITE,),
            params={"sendUpdates": "all"},
            body={"attendees": attendees},
            headers={"If-Match": current["etag"]} if current.get("etag") else None,
        )
        normalized = normalize_event(updated, calendar_id=_calendar_id(calendar_id))
        matching = [
            item
            for item in normalized["attendees"]
            if item["email"].lower() == own_email or item.get("self")
        ]
        normalized["verification"] = {
            "status": "verified"
            if matching and matching[0]["response_status"] == response_status
            else "mismatch",
            "provider": "google_calendar",
        }
        return normalized

    async def update_attendees(
        self,
        owner,
        connection_id,
        event_id: str,
        *,
        add: Sequence[object] = (),
        remove: Sequence[str] = (),
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        current = await self.get_event(owner, connection_id, calendar_id, event_id)
        attendees = {
            item["email"].lower(): {"email": item["email"]}
            for item in current["attendees"]
            if item.get("email")
        }
        for address in remove:
            attendees.pop(parseaddr(str(address))[1].lower(), None)
        for item in _attendees(add):
            attendees[item["email"].lower()] = item
        updated = await self._api(
            owner,
            connection_id,
            method="PATCH",
            path=(
                f"/calendars/{quote(_calendar_id(calendar_id), safe='')}/events/"
                f"{quote(_event_id(event_id), safe='')}"
            ),
            scopes=(CALENDAR_EVENTS_WRITE,),
            params={"sendUpdates": "all"},
            body={"attendees": list(attendees.values())},
            headers={"If-Match": current["etag"]} if current.get("etag") else None,
        )
        normalized = normalize_event(updated, calendar_id=_calendar_id(calendar_id))
        expected = set(attendees)
        actual = {item["email"].lower() for item in normalized["attendees"]}
        normalized["verification"] = {
            "status": "verified" if actual == expected else "mismatch",
            "provider": "google_calendar",
        }
        return normalized

    async def freebusy(
        self,
        owner,
        connection_id,
        *,
        calendar_ids: Sequence[str],
        time_min: str,
        time_max: str,
        timezone_name: str = "UTC",
    ) -> dict[str, Any]:
        if not calendar_ids or len(calendar_ids) > 50:
            raise CalendarValidationError("calendar_ids must contain 1 to 50 calendars.")
        start = _parse_rfc3339(time_min, field="time_min")
        end = _parse_rfc3339(time_max, field="time_max")
        if end <= start or end - start > timedelta(days=90):
            raise CalendarValidationError("free/busy range must be positive and at most 90 days.")
        timezone_name = _validate_timezone(timezone_name)
        ids = [_calendar_id(item) for item in calendar_ids]
        result = await self._api(
            owner,
            connection_id,
            method="POST",
            path="/freeBusy",
            scopes=(CALENDAR_FREEBUSY, CALENDAR_EVENTS_READ, CALENDAR_EVENTS_WRITE),
            body={
                "timeMin": _rfc3339(start),
                "timeMax": _rfc3339(end),
                "timeZone": timezone_name,
                "items": [{"id": item} for item in ids],
            },
        )
        calendars = {}
        for calendar_id, data in (result.get("calendars") or {}).items():
            if not isinstance(data, Mapping):
                continue
            calendars[str(calendar_id)] = {
                "busy": [
                    {"start": str(item.get("start")), "end": str(item.get("end"))}
                    for item in data.get("busy") or []
                    if isinstance(item, Mapping)
                ],
                "errors": [dict(item) for item in data.get("errors") or [] if isinstance(item, Mapping)],
            }
        return {
            "time_min": str(result.get("timeMin") or _rfc3339(start)),
            "time_max": str(result.get("timeMax") or _rfc3339(end)),
            "calendars": calendars,
        }

    async def detect_conflicts(
        self,
        owner,
        connection_id,
        *,
        calendar_ids: Sequence[str],
        start: Mapping[str, Any],
        end: Mapping[str, Any],
        timezone_name: str = "UTC",
        buffer_before_minutes: int = 0,
        buffer_after_minutes: int = 0,
    ) -> dict[str, Any]:
        """Check an exact proposed interval against one or more calendars."""

        zone = ZoneInfo(_validate_timezone(timezone_name))
        normalized_start = _event_time(start, field="start")
        normalized_end = _event_time(end, field="end")
        _validate_interval(normalized_start, normalized_end)
        if "date" in normalized_start:
            proposed_start = datetime.combine(
                date.fromisoformat(normalized_start["date"]), time.min, tzinfo=zone
            )
            proposed_end = datetime.combine(
                date.fromisoformat(normalized_end["date"]), time.min, tzinfo=zone
            )
        else:
            proposed_start = _parse_rfc3339(
                normalized_start["dateTime"], field="start.dateTime"
            )
            proposed_end = _parse_rfc3339(
                normalized_end["dateTime"], field="end.dateTime"
            )
        before = timedelta(minutes=max(0, min(int(buffer_before_minutes), 1440)))
        after = timedelta(minutes=max(0, min(int(buffer_after_minutes), 1440)))
        window_start = proposed_start - before
        window_end = proposed_end + after
        availability = await self.freebusy(
            owner,
            connection_id,
            calendar_ids=calendar_ids,
            time_min=_rfc3339(window_start),
            time_max=_rfc3339(window_end),
            timezone_name=timezone_name,
        )
        conflicts: list[dict[str, str]] = []
        errors: list[dict[str, Any]] = []
        for calendar_id, calendar in availability["calendars"].items():
            if calendar["errors"]:
                errors.append(
                    {"calendar_id": calendar_id, "errors": calendar["errors"]}
                )
            for interval in calendar["busy"]:
                busy_start = _parse_rfc3339(interval["start"], field="busy.start")
                busy_end = _parse_rfc3339(interval["end"], field="busy.end")
                if busy_start < window_end and busy_end > window_start:
                    conflicts.append(
                        {
                            "calendar_id": calendar_id,
                            "start": _rfc3339(busy_start),
                            "end": _rfc3339(busy_end),
                        }
                    )
        return {
            "has_conflicts": bool(conflicts),
            "conflicts": conflicts,
            "calendar_errors": errors,
            "proposed_start": _rfc3339(proposed_start),
            "proposed_end": _rfc3339(proposed_end),
            "checked_start": _rfc3339(window_start),
            "checked_end": _rfc3339(window_end),
            "timezone": timezone_name,
        }

    async def find_free_time(
        self,
        owner,
        connection_id,
        *,
        calendar_ids: Sequence[str],
        time_min: str,
        time_max: str,
        duration_minutes: int,
        timezone_name: str,
        workday_start: str = "09:00",
        workday_end: str = "17:30",
        buffer_before_minutes: int = 0,
        buffer_after_minutes: int = 0,
        slot_step_minutes: int = 30,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        if not 5 <= int(duration_minutes) <= 1440:
            raise CalendarValidationError("duration_minutes must be between 5 and 1440.")
        if not 1 <= int(limit) <= 50:
            raise CalendarValidationError("limit must be between 1 and 50.")
        if not 5 <= int(slot_step_minutes) <= 240:
            raise CalendarValidationError("slot_step_minutes must be between 5 and 240.")
        zone = ZoneInfo(_validate_timezone(timezone_name))
        try:
            work_start = time.fromisoformat(workday_start)
            work_end = time.fromisoformat(workday_end)
        except ValueError as exc:
            raise CalendarValidationError("working-hour values must be HH:MM.") from exc
        if work_end <= work_start:
            raise CalendarValidationError("workday_end must be after workday_start.")
        requested_start = _parse_rfc3339(time_min, field="time_min")
        requested_end = _parse_rfc3339(time_max, field="time_max")
        availability = await self.freebusy(
            owner,
            connection_id,
            calendar_ids=calendar_ids,
            time_min=_rfc3339(requested_start),
            time_max=_rfc3339(requested_end),
            timezone_name=timezone_name,
        )
        before = timedelta(minutes=max(0, min(int(buffer_before_minutes), 1440)))
        after = timedelta(minutes=max(0, min(int(buffer_after_minutes), 1440)))
        busy = []
        for calendar in availability["calendars"].values():
            if calendar["errors"]:
                raise GoogleProviderError("Google returned a calendar free/busy error.")
            for interval in calendar["busy"]:
                busy.append(
                    (
                        _parse_rfc3339(interval["start"], field="busy.start") - before,
                        _parse_rfc3339(interval["end"], field="busy.end") + after,
                    )
                )
        busy.sort(key=lambda item: item[0])
        merged = []
        for start, end in busy:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        duration = timedelta(minutes=int(duration_minutes))
        step = timedelta(minutes=int(slot_step_minutes))
        slots = []

        def append_gap(gap_start: datetime, gap_end: datetime) -> None:
            candidate = gap_start
            while candidate + duration <= gap_end and len(slots) < limit:
                slots.append(
                    {
                        "start": _rfc3339(candidate),
                        "end": _rfc3339(candidate + duration),
                        "timezone": timezone_name,
                    }
                )
                candidate += step

        local_day = requested_start.astimezone(zone).date()
        final_day = requested_end.astimezone(zone).date()
        while local_day <= final_day and len(slots) < limit:
            day_start = datetime.combine(local_day, work_start, tzinfo=zone)
            day_end = datetime.combine(local_day, work_end, tzinfo=zone)
            cursor = max(day_start, requested_start.astimezone(zone))
            boundary = min(day_end, requested_end.astimezone(zone))
            for busy_start, busy_end in merged:
                local_busy_start = busy_start.astimezone(zone)
                local_busy_end = busy_end.astimezone(zone)
                if local_busy_end <= cursor or local_busy_start >= boundary:
                    continue
                if local_busy_start - cursor >= duration:
                    append_gap(cursor, min(local_busy_start, boundary))
                    if len(slots) >= limit:
                        break
                cursor = max(cursor, local_busy_end)
            if len(slots) < limit and boundary - cursor >= duration:
                append_gap(cursor, boundary)
            local_day += timedelta(days=1)
        return slots[:limit]

    async def _verify_write(
        self,
        owner,
        connection_id,
        calendar_id: str,
        provider_result: Mapping[str, Any],
        requested: Mapping[str, Any],
    ) -> dict[str, Any]:
        event_id = _event_id(provider_result.get("id"))
        stored = await self.get_event(owner, connection_id, calendar_id, event_id)
        expected_attendees = {
            str(item.get("email") or "").lower()
            for item in requested.get("attendees") or []
        }
        actual_attendees = {
            item["email"].lower() for item in stored["attendees"]
        }
        matches = (
            stored["title"] == requested.get("summary")
            and stored["start"] == requested.get("start")
            and stored["end"] == requested.get("end")
            and expected_attendees <= actual_attendees
        )
        if "location" in requested:
            matches = matches and stored["location"] == requested["location"]
        if "status" in requested:
            matches = matches and stored["status"] == requested["status"]
        return {
            "event": stored,
            "verification": {
                "status": "verified" if matches else "mismatch",
                "provider": "google_calendar",
                "read_back_id": event_id,
            },
        }


_calendar_service: Optional[GoogleCalendarService] = None


def get_google_calendar_service() -> GoogleCalendarService:
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = GoogleCalendarService()
    return _calendar_service
