"""Owner-scoped Gmail and Calendar routes backed by Google APIs.

These endpoints never return OAuth credentials.  Read operations are direct,
while externally visible human-triggered writes require a literal confirmation
bit so an accidental generic POST cannot send mail or alter a calendar.
Companion/agent writes use the canonical tool ledger instead of these routes.
"""

from __future__ import annotations

import io
from pathlib import Path
import re
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from services.google_calendar import (
    CalendarSyncTokenExpired,
    CalendarValidationError,
    GoogleCalendarService,
    get_google_calendar_service,
)
from services.google_gmail import (
    GmailValidationError,
    GoogleGmailService,
    get_google_gmail_service,
)
from src.auth_helpers import require_user
from src.google_connection import (
    GoogleConfigurationError,
    GoogleConnectionError,
    GoogleConnectionNotFound,
    GoogleProviderError,
)


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComposeBody(_StrictBody):
    to: str | list[str]
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(max_length=10 * 1024 * 1024)
    body_html: Optional[str] = Field(default=None, max_length=10 * 1024 * 1024)
    cc: str | list[str] | None = None
    bcc: str | list[str] | None = None


class ConfirmedComposeBody(ComposeBody):
    confirm: Literal[True]


class ConfirmBody(_StrictBody):
    confirm: Literal[True]


class ReplyBody(ConfirmBody):
    body: str = Field(max_length=10 * 1024 * 1024)
    body_html: Optional[str] = Field(default=None, max_length=10 * 1024 * 1024)
    reply_all: bool = False


class ForwardBody(ConfirmBody):
    to: str | list[str]
    note: str = Field(default="", max_length=1_000_000)


class LabelsBody(_StrictBody):
    add: list[str] = Field(default_factory=list, max_length=100)
    remove: list[str] = Field(default_factory=list, max_length=100)


class BooleanStateBody(_StrictBody):
    value: bool


class CalendarSyncBody(_StrictBody):
    sync_token: str = Field(min_length=1, max_length=4096)
    page_token: Optional[str] = Field(default=None, max_length=4096)
    max_results: int = Field(default=2500, ge=1, le=2500)


class CalendarIntervalBody(_StrictBody):
    calendar_ids: list[str] = Field(min_length=1, max_length=50)
    time_min: str = Field(min_length=1, max_length=128)
    time_max: str = Field(min_length=1, max_length=128)
    timezone: str = Field(default="UTC", min_length=1, max_length=128)


class ConflictBody(_StrictBody):
    calendar_ids: list[str] = Field(min_length=1, max_length=50)
    start: dict[str, Any]
    end: dict[str, Any]
    timezone: str = Field(default="UTC", min_length=1, max_length=128)
    buffer_before_minutes: int = Field(default=0, ge=0, le=1440)
    buffer_after_minutes: int = Field(default=0, ge=0, le=1440)


class FreeTimeBody(CalendarIntervalBody):
    duration_minutes: int = Field(ge=5, le=1440)
    workday_start: str = Field(default="09:00", min_length=4, max_length=8)
    workday_end: str = Field(default="17:30", min_length=4, max_length=8)
    buffer_before_minutes: int = Field(default=0, ge=0, le=1440)
    buffer_after_minutes: int = Field(default=0, ge=0, le=1440)
    slot_step_minutes: int = Field(default=30, ge=5, le=240)
    limit: int = Field(default=10, ge=1, le=50)


class CalendarEventBody(_StrictBody):
    title: str = Field(min_length=1, max_length=1024)
    start: dict[str, Any]
    end: dict[str, Any]
    description: Optional[str] = Field(default=None, max_length=32_000)
    location: Optional[str] = Field(default=None, max_length=2048)
    visibility: Optional[Literal["default", "public", "private", "confidential"]] = None
    transparency: Optional[Literal["opaque", "transparent"]] = None
    color_id: Optional[str] = Field(default=None, max_length=32)
    attendees: list[Any] = Field(default_factory=list, max_length=200)
    recurrence: Optional[list[str]] = Field(default=None, max_length=20)
    reminders: Optional[dict[str, Any]] = None
    create_video_call: bool = False
    send_updates: Literal["all", "externalOnly", "none"] = "none"
    confirm: Literal[True]


class InvitationResponseBody(ConfirmBody):
    response_status: Literal["accepted", "declined", "tentative", "needsAction"]
    comment: str = Field(default="", max_length=1024)


class AttendeeUpdateBody(ConfirmBody):
    add: list[Any] = Field(default_factory=list, max_length=200)
    remove: list[str] = Field(default_factory=list, max_length=200)


def _raise_workspace_error(exc: Exception) -> None:
    if isinstance(exc, (GmailValidationError, CalendarValidationError)):
        status = 422
        code = "invalid_google_workspace_request"
    elif isinstance(exc, CalendarSyncTokenExpired):
        status = 409
        code = exc.code
    elif isinstance(exc, GoogleConnectionNotFound):
        status = 404
        code = exc.code
    elif isinstance(exc, GoogleConfigurationError):
        status = 409
        code = exc.code
    elif isinstance(exc, GoogleProviderError):
        status = 503 if exc.status_code == 429 else 502
        code = exc.code
    elif isinstance(exc, GoogleConnectionError):
        status = 500
        code = exc.code
    else:  # pragma: no cover - call sites only pass controlled errors
        status = 500
        code = "google_workspace_error"
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": str(exc)},
    ) from exc


def _event_command(payload: CalendarEventBody) -> tuple[str, dict[str, Any]]:
    values = payload.model_dump(exclude={"confirm", "send_updates"}, exclude_none=True)
    return payload.send_updates, values


def _safe_attachment_name(value: str, fallback: str) -> str:
    name = Path(str(value or "")).name
    name = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", name).strip(". ")
    return (name or fallback)[:180]


def _safe_media_type(value: str) -> str:
    media_type = str(value or "application/octet-stream").strip().lower()
    if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", media_type):
        return "application/octet-stream"
    return media_type


def setup_google_workspace_routes(
    gmail_service: GoogleGmailService | None = None,
    calendar_service: GoogleCalendarService | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/integrations/google/connections/{connection_id}",
        tags=["google-workspace"],
    )
    gmail = gmail_service or get_google_gmail_service()
    calendar = calendar_service or get_google_calendar_service()

    @router.get("/gmail/labels")
    async def list_gmail_labels(
        connection_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return {"labels": await gmail.list_labels(owner, connection_id)}
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/gmail/messages")
    async def search_gmail_messages(
        connection_id: str,
        q: str = Query("", max_length=4096),
        label_id: list[str] = Query(default=[]),
        max_results: int = Query(20, ge=1, le=100),
        page_token: Optional[str] = Query(None, max_length=2048),
        include_metadata: bool = Query(True),
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.search_messages(
                owner,
                connection_id,
                query=q,
                label_ids=label_id,
                max_results=max_results,
                page_token=page_token,
                include_metadata=include_metadata,
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/gmail/messages/{message_id}")
    async def read_gmail_message(
        connection_id: str,
        message_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.read_message(owner, connection_id, message_id)
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/gmail/threads/{thread_id}")
    async def read_gmail_thread(
        connection_id: str,
        thread_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.read_thread(owner, connection_id, thread_id)
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/gmail/messages/{message_id}/attachments")
    async def list_gmail_attachments(
        connection_id: str,
        message_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            message = await gmail.read_message(owner, connection_id, message_id)
            return {"attachments": message["attachments"]}
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/gmail/messages/{message_id}/attachments/{attachment_id}")
    async def download_gmail_attachment(
        connection_id: str,
        message_id: str,
        attachment_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            message = await gmail.read_message(owner, connection_id, message_id)
            metadata = next(
                (
                    item
                    for item in message["attachments"]
                    if item.get("attachment_id") == attachment_id
                ),
                None,
            )
            if metadata is None:
                raise HTTPException(
                    404,
                    detail={
                        "code": "attachment_not_found",
                        "message": "Gmail attachment was not found on this message.",
                    },
                )
            content = await gmail.get_attachment(
                owner, connection_id, message_id, attachment_id
            )
        except HTTPException:
            raise
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)
        filename = _safe_attachment_name(
            str(metadata.get("filename") or ""), f"attachment-{attachment_id}"
        )
        return StreamingResponse(
            io.BytesIO(content),
            media_type=_safe_media_type(str(metadata.get("mime_type") or "")),
            headers={
                "Content-Disposition": (
                    "attachment; filename=\"download\"; "
                    f"filename*=UTF-8''{quote(filename, safe='')}"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/gmail/drafts")
    async def list_gmail_drafts(
        connection_id: str,
        max_results: int = Query(20, ge=1, le=100),
        page_token: Optional[str] = Query(None, max_length=2048),
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.list_drafts(
                owner,
                connection_id,
                max_results=max_results,
                page_token=page_token,
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/drafts", status_code=201)
    async def create_gmail_draft(
        connection_id: str,
        body: ComposeBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.create_draft(
                owner, connection_id, **body.model_dump(exclude_none=True)
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/gmail/drafts/{draft_id}")
    async def read_gmail_draft(
        connection_id: str,
        draft_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.get_draft(owner, connection_id, draft_id)
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.put("/gmail/drafts/{draft_id}")
    async def update_gmail_draft(
        connection_id: str,
        draft_id: str,
        body: ComposeBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.update_draft(
                owner,
                connection_id,
                draft_id,
                **body.model_dump(exclude_none=True),
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.delete("/gmail/drafts/{draft_id}")
    async def delete_gmail_draft(
        connection_id: str,
        draft_id: str,
        body: ConfirmBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.delete_draft(owner, connection_id, draft_id)
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/drafts/{draft_id}/send")
    async def send_gmail_draft(
        connection_id: str,
        draft_id: str,
        body: ConfirmBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.send_draft(owner, connection_id, draft_id)
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/send")
    async def send_gmail_message(
        connection_id: str,
        body: ConfirmedComposeBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.send_message(
                owner,
                connection_id,
                **body.model_dump(exclude={"confirm"}, exclude_none=True),
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/{message_id}/reply")
    async def reply_to_gmail_message(
        connection_id: str,
        message_id: str,
        body: ReplyBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.reply(
                owner,
                connection_id,
                message_id,
                **body.model_dump(exclude={"confirm"}, exclude_none=True),
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/{message_id}/forward")
    async def forward_gmail_message(
        connection_id: str,
        message_id: str,
        body: ForwardBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.forward(
                owner,
                connection_id,
                message_id,
                **body.model_dump(exclude={"confirm"}),
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/{message_id}/labels")
    async def modify_gmail_labels(
        connection_id: str,
        message_id: str,
        body: LabelsBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.modify_labels(
                owner, connection_id, message_id, add=body.add, remove=body.remove
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/{message_id}/archive")
    async def archive_gmail_message(
        connection_id: str,
        message_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.archive(owner, connection_id, message_id)
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/{message_id}/read")
    async def mark_gmail_read_state(
        connection_id: str,
        message_id: str,
        body: BooleanStateBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.mark_read(
                owner, connection_id, message_id, read=body.value
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/{message_id}/star")
    async def mark_gmail_star_state(
        connection_id: str,
        message_id: str,
        body: BooleanStateBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.star(
                owner, connection_id, message_id, starred=body.value
            )
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/gmail/messages/{message_id}/trash")
    async def trash_gmail_message(
        connection_id: str,
        message_id: str,
        body: ConfirmBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await gmail.trash(owner, connection_id, message_id)
        except (GoogleConnectionError, GmailValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/calendar/calendars")
    async def list_google_calendars(
        connection_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return {"calendars": await calendar.list_calendars(owner, connection_id)}
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/calendar/events")
    async def list_google_events(
        connection_id: str,
        time_min: str = Query(..., max_length=128),
        time_max: str = Query(..., max_length=128),
        calendar_id: str = Query("primary", max_length=1024),
        q: str = Query("", max_length=2048),
        max_results: int = Query(100, ge=1, le=2500),
        page_token: Optional[str] = Query(None, max_length=2048),
        show_deleted: bool = Query(False),
        owner: str = Depends(require_user),
    ):
        try:
            return await calendar.list_events(
                owner,
                connection_id,
                calendar_id=calendar_id,
                time_min=time_min,
                time_max=time_max,
                query=q,
                max_results=max_results,
                page_token=page_token,
                show_deleted=show_deleted,
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/calendar/calendars/{calendar_id}/sync")
    async def sync_google_events(
        connection_id: str,
        calendar_id: str,
        body: CalendarSyncBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await calendar.sync_events(
                owner,
                connection_id,
                calendar_id=calendar_id,
                **body.model_dump(exclude_none=True),
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.get("/calendar/calendars/{calendar_id}/events/{event_id}")
    async def read_google_event(
        connection_id: str,
        calendar_id: str,
        event_id: str,
        owner: str = Depends(require_user),
    ):
        try:
            return await calendar.get_event(
                owner, connection_id, calendar_id, event_id
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/calendar/calendars/{calendar_id}/events", status_code=201)
    async def create_google_event(
        connection_id: str,
        calendar_id: str,
        body: CalendarEventBody,
        owner: str = Depends(require_user),
    ):
        send_updates, command = _event_command(body)
        try:
            return await calendar.create_event(
                owner,
                connection_id,
                calendar_id=calendar_id,
                send_updates=send_updates,
                **command,
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.put("/calendar/calendars/{calendar_id}/events/{event_id}")
    async def update_google_event(
        connection_id: str,
        calendar_id: str,
        event_id: str,
        body: CalendarEventBody,
        etag: Optional[str] = Query(None, max_length=2048),
        owner: str = Depends(require_user),
    ):
        send_updates, command = _event_command(body)
        try:
            return await calendar.update_event(
                owner,
                connection_id,
                event_id,
                calendar_id=calendar_id,
                send_updates=send_updates,
                etag=etag,
                **command,
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.delete("/calendar/calendars/{calendar_id}/events/{event_id}")
    async def delete_google_event(
        connection_id: str,
        calendar_id: str,
        event_id: str,
        body: ConfirmBody,
        send_updates: Literal["all", "externalOnly", "none"] = Query("none"),
        etag: Optional[str] = Query(None, max_length=2048),
        owner: str = Depends(require_user),
    ):
        try:
            return await calendar.delete_event(
                owner,
                connection_id,
                event_id,
                calendar_id=calendar_id,
                send_updates=send_updates,
                etag=etag,
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/calendar/calendars/{calendar_id}/events/{event_id}/response")
    async def respond_to_google_event(
        connection_id: str,
        calendar_id: str,
        event_id: str,
        body: InvitationResponseBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await calendar.respond_to_invitation(
                owner,
                connection_id,
                event_id,
                calendar_id=calendar_id,
                **body.model_dump(exclude={"confirm"}),
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.patch("/calendar/calendars/{calendar_id}/events/{event_id}/attendees")
    async def update_google_event_attendees(
        connection_id: str,
        calendar_id: str,
        event_id: str,
        body: AttendeeUpdateBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await calendar.update_attendees(
                owner,
                connection_id,
                event_id,
                calendar_id=calendar_id,
                add=body.add,
                remove=body.remove,
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/calendar/freebusy")
    async def google_calendar_freebusy(
        connection_id: str,
        body: CalendarIntervalBody,
        owner: str = Depends(require_user),
    ):
        try:
            return await calendar.freebusy(
                owner,
                connection_id,
                calendar_ids=body.calendar_ids,
                time_min=body.time_min,
                time_max=body.time_max,
                timezone_name=body.timezone,
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/calendar/conflicts")
    async def detect_google_calendar_conflicts(
        connection_id: str,
        body: ConflictBody,
        owner: str = Depends(require_user),
    ):
        values = body.model_dump()
        values["timezone_name"] = values.pop("timezone")
        try:
            return await calendar.detect_conflicts(
                owner, connection_id, **values
            )
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    @router.post("/calendar/free-time")
    async def find_google_calendar_free_time(
        connection_id: str,
        body: FreeTimeBody,
        owner: str = Depends(require_user),
    ):
        values = body.model_dump()
        values["timezone_name"] = values.pop("timezone")
        try:
            return {
                "slots": await calendar.find_free_time(
                    owner, connection_id, **values
                )
            }
        except (GoogleConnectionError, CalendarValidationError) as exc:
            _raise_workspace_error(exc)

    return router
