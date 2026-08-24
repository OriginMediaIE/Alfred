"""Canonical agent adapters for token-free Gmail and Google Calendar access."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from services.google_calendar import CalendarValidationError, get_google_calendar_service
from services.google_gmail import GmailValidationError, get_google_gmail_service
from src.action_ledger import ActionLedgerError, get_action_ledger
from src.google_connection import (
    GoogleConfigurationError,
    GoogleConnectionError,
    get_google_connection_service,
)
from src.google_workspace_tool_contract import (
    GOOGLE_WORKSPACE_TOOL_NAMES,
    GOOGLE_WORKSPACE_TOOL_SCHEMAS,
)
from src.tools._common import _configured_auth_requires_owner, _parse_tool_args


_MUTATION_TOOLS = GOOGLE_WORKSPACE_TOOL_NAMES - {
    "query_gmail",
    "query_google_calendar",
}


def _arguments(content: str) -> dict[str, Any]:
    parsed = _parse_tool_args(content)
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return parsed


def _required(args: Mapping[str, Any], key: str) -> Any:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{key} is required.")
    return value


def _provider_error(exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", None) or "invalid_google_workspace_request"
    return {"error": str(exc), "code": str(code), "exit_code": 1}


def _ok(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {**dict(value), "exit_code": 0}
    return {"result": value, "exit_code": 0}


def _parse_iso(value: object) -> datetime:
    raw = str(value or "")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require_claimed_action(
    owner: Optional[str],
    expected_tool: str,
    *,
    approval_action_id: Optional[str],
    request_id: str,
) -> None:
    if expected_tool not in _MUTATION_TOOLS or not approval_action_id or not request_id:
        raise GoogleConfigurationError(
            "Google Workspace mutation requires an approved action-ledger claim."
        )
    try:
        action = get_action_ledger().get_action(approval_action_id, owner)
    except ActionLedgerError as exc:
        raise GoogleConfigurationError(
            "Google Workspace approval evidence is unavailable."
        ) from exc
    if (
        action.get("tool_name") != expected_tool
        or action.get("status") != "executing"
        or not action.get("approval_consumed_at")
        or str(action.get("request_id") or "") != str(request_id)
        or _parse_iso(action.get("expires_at")) <= datetime.now(timezone.utc)
    ):
        raise GoogleConfigurationError(
            "Google Workspace approval evidence is invalid, expired, or mismatched."
        )


def _connection(owner: Optional[str], args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    manager = get_google_connection_service()
    connection_id = str(args.get("connection_id") or "").strip()
    if connection_id:
        connection = manager.get_connection(owner, connection_id)
        if connection.get("status") != "connected":
            raise GoogleConfigurationError(
                "The selected Google account must be reconnected before use."
            )
        return connection_id, connection
    connected = [
        item
        for item in manager.list_connections(owner)
        if item.get("status") == "connected"
    ]
    if not connected:
        raise GoogleConfigurationError("Connect a Google account before using this tool.")
    if len(connected) != 1:
        raise GoogleConfigurationError(
            "More than one Google account is connected; choose connection_id explicitly."
        )
    return str(connected[0]["id"]), connected[0]


def _calendar_id(args: Mapping[str, Any], connection: Mapping[str, Any]) -> str:
    return str(
        args.get("calendar_id")
        or connection.get("default_calendar")
        or "primary"
    )


def _calendar_ids(args: Mapping[str, Any], connection: Mapping[str, Any]) -> list[str]:
    supplied = args.get("calendar_ids")
    if supplied:
        if not isinstance(supplied, list):
            raise ValueError("calendar_ids must be a list.")
        return [str(item) for item in supplied]
    selected = connection.get("selected_calendars") or []
    return [str(item) for item in selected] or [_calendar_id(args, connection)]


def _compose(args: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: args[key]
        for key in ("to", "subject", "body", "body_html", "cc", "bcc")
        if key in args
    }


def _event_command(args: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: args[key]
        for key in (
            "title",
            "start",
            "end",
            "description",
            "location",
            "visibility",
            "transparency",
            "color_id",
            "attendees",
            "recurrence",
            "reminders",
            "create_video_call",
            "status",
        )
        if key in args
    }


async def do_query_gmail(content: str, owner: Optional[str] = None) -> dict[str, Any]:
    if _configured_auth_requires_owner(owner):
        return {"error": "Authenticated owner is required.", "code": "owner_required", "exit_code": 1}
    try:
        args = _arguments(content)
        action = str(_required(args, "action"))
        connection_id, _ = _connection(owner, args)
        gmail = get_google_gmail_service()
        if action == "list_labels":
            result = {"labels": await gmail.list_labels(owner, connection_id)}
        elif action == "search_messages":
            result = await gmail.search_messages(
                owner,
                connection_id,
                query=str(args.get("query") or ""),
                label_ids=args.get("label_ids") or (),
                max_results=int(args.get("max_results", 20)),
                page_token=args.get("page_token"),
                include_metadata=bool(args.get("include_metadata", True)),
            )
        elif action == "read_message":
            result = {
                "message": await gmail.read_message(
                    owner, connection_id, str(_required(args, "message_id"))
                )
            }
        elif action == "read_thread":
            result = {
                "thread": await gmail.read_thread(
                    owner, connection_id, str(_required(args, "thread_id"))
                )
            }
        elif action == "list_attachments":
            message = await gmail.read_message(
                owner, connection_id, str(_required(args, "message_id"))
            )
            result = {"attachments": message["attachments"], "message_id": message["id"]}
        elif action == "list_drafts":
            result = await gmail.list_drafts(
                owner,
                connection_id,
                max_results=int(args.get("max_results", 20)),
                page_token=args.get("page_token"),
            )
        elif action == "read_draft":
            result = await gmail.get_draft(
                owner, connection_id, str(_required(args, "draft_id"))
            )
        else:
            raise ValueError("Unknown query_gmail action.")
        return _ok(result)
    except (GoogleConnectionError, GmailValidationError, TypeError, ValueError) as exc:
        return _provider_error(exc)


async def do_manage_gmail_draft(
    content: str,
    owner: Optional[str] = None,
    *,
    approval_action_id: Optional[str] = None,
    request_id: str = "",
) -> dict[str, Any]:
    try:
        args = _arguments(content)
        _require_claimed_action(
            owner,
            "manage_gmail_draft",
            approval_action_id=approval_action_id,
            request_id=request_id,
        )
        connection_id, _ = _connection(owner, args)
        gmail = get_google_gmail_service()
        action = str(_required(args, "action"))
        if action == "create":
            result = await gmail.create_draft(owner, connection_id, **_compose(args))
        elif action == "update":
            result = await gmail.update_draft(
                owner,
                connection_id,
                str(_required(args, "draft_id")),
                **_compose(args),
            )
        else:
            raise ValueError("Unknown manage_gmail_draft action.")
        return _ok(result)
    except (GoogleConnectionError, GmailValidationError, TypeError, ValueError) as exc:
        return _provider_error(exc)


async def do_send_gmail(
    content: str,
    owner: Optional[str] = None,
    *,
    approval_action_id: Optional[str] = None,
    request_id: str = "",
) -> dict[str, Any]:
    try:
        args = _arguments(content)
        _require_claimed_action(
            owner,
            "send_gmail",
            approval_action_id=approval_action_id,
            request_id=request_id,
        )
        connection_id, _ = _connection(owner, args)
        gmail = get_google_gmail_service()
        action = str(_required(args, "action"))
        if action == "send_draft":
            result = await gmail.send_draft(
                owner, connection_id, str(_required(args, "draft_id"))
            )
        elif action == "send_message":
            result = await gmail.send_message(owner, connection_id, **_compose(args))
        elif action in {"reply", "reply_all"}:
            result = await gmail.reply(
                owner,
                connection_id,
                str(_required(args, "message_id")),
                body=str(_required(args, "body")),
                body_html=args.get("body_html"),
                reply_all=action == "reply_all",
            )
        elif action == "forward":
            result = await gmail.forward(
                owner,
                connection_id,
                str(_required(args, "message_id")),
                to=_required(args, "to"),
                note=str(args.get("note") or ""),
            )
        else:
            raise ValueError("Unknown send_gmail action.")
        return _ok(result)
    except (GoogleConnectionError, GmailValidationError, TypeError, ValueError) as exc:
        return _provider_error(exc)


async def do_modify_gmail_message(
    content: str,
    owner: Optional[str] = None,
    *,
    approval_action_id: Optional[str] = None,
    request_id: str = "",
) -> dict[str, Any]:
    try:
        args = _arguments(content)
        _require_claimed_action(
            owner,
            "modify_gmail_message",
            approval_action_id=approval_action_id,
            request_id=request_id,
        )
        connection_id, _ = _connection(owner, args)
        gmail = get_google_gmail_service()
        action = str(_required(args, "action"))
        message_id = str(_required(args, "message_id"))
        if action == "labels":
            result = await gmail.modify_labels(
                owner,
                connection_id,
                message_id,
                add=args.get("add") or (),
                remove=args.get("remove") or (),
            )
        elif action == "archive":
            result = await gmail.archive(owner, connection_id, message_id)
        elif action in {"mark_read", "mark_unread"}:
            result = await gmail.mark_read(
                owner, connection_id, message_id, read=action == "mark_read"
            )
        elif action in {"star", "unstar"}:
            result = await gmail.star(
                owner, connection_id, message_id, starred=action == "star"
            )
        else:
            raise ValueError("Unknown modify_gmail_message action.")
        return _ok(result)
    except (GoogleConnectionError, GmailValidationError, TypeError, ValueError) as exc:
        return _provider_error(exc)


async def do_delete_gmail(
    content: str,
    owner: Optional[str] = None,
    *,
    approval_action_id: Optional[str] = None,
    request_id: str = "",
) -> dict[str, Any]:
    try:
        args = _arguments(content)
        _require_claimed_action(
            owner,
            "delete_gmail",
            approval_action_id=approval_action_id,
            request_id=request_id,
        )
        connection_id, _ = _connection(owner, args)
        gmail = get_google_gmail_service()
        action = str(_required(args, "action"))
        if action == "trash_message":
            result = await gmail.trash(
                owner, connection_id, str(_required(args, "message_id"))
            )
        elif action == "delete_draft":
            result = await gmail.delete_draft(
                owner, connection_id, str(_required(args, "draft_id"))
            )
        else:
            raise ValueError("Unknown delete_gmail action.")
        return _ok(result)
    except (GoogleConnectionError, GmailValidationError, TypeError, ValueError) as exc:
        return _provider_error(exc)


async def do_download_gmail_attachment(
    content: str,
    owner: Optional[str] = None,
    *,
    approval_action_id: Optional[str] = None,
    request_id: str = "",
) -> dict[str, Any]:
    created_path: Optional[str] = None
    try:
        args = _arguments(content)
        _require_claimed_action(
            owner,
            "download_gmail_attachment",
            approval_action_id=approval_action_id,
            request_id=request_id,
        )
        connection_id, _ = _connection(owner, args)
        gmail = get_google_gmail_service()
        content_bytes = await gmail.get_attachment(
            owner,
            connection_id,
            str(_required(args, "message_id")),
            str(_required(args, "attachment_id")),
        )
        # Function-local import avoids a registry/executor import cycle while
        # reusing the exact workspace and sensitive-path confinement policy.
        from src.tool_execution import _resolve_tool_path

        resolved = _resolve_tool_path(str(_required(args, "path")))
        parent = Path(resolved).parent
        if not parent.is_dir():
            raise ValueError("Attachment destination directory does not exist.")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(resolved, flags, 0o600)
        created_path = resolved
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        observed = Path(resolved).read_bytes()
        expected_hash = hashlib.sha256(content_bytes).hexdigest()
        observed_hash = hashlib.sha256(observed).hexdigest()
        verified = observed_hash == expected_hash and len(observed) == len(content_bytes)
        return {
            "path": resolved,
            "size": len(observed),
            "sha256": observed_hash,
            "verification": {
                "status": "verified" if verified else "mismatch",
                "provider": "gmail_attachment",
                "read_back_id": observed_hash,
            },
            "exit_code": 0,
        }
    except (GoogleConnectionError, GmailValidationError, OSError, TypeError, ValueError) as exc:
        if created_path:
            try:
                os.unlink(created_path)
            except OSError:
                pass
        return _provider_error(exc)


async def do_query_google_calendar(
    content: str, owner: Optional[str] = None
) -> dict[str, Any]:
    if _configured_auth_requires_owner(owner):
        return {"error": "Authenticated owner is required.", "code": "owner_required", "exit_code": 1}
    try:
        args = _arguments(content)
        action = str(_required(args, "action"))
        connection_id, connection = _connection(owner, args)
        calendar = get_google_calendar_service()
        calendar_id = _calendar_id(args, connection)
        if action == "list_calendars":
            result = {"calendars": await calendar.list_calendars(owner, connection_id)}
        elif action == "list_events":
            result = await calendar.list_events(
                owner,
                connection_id,
                calendar_id=calendar_id,
                time_min=str(_required(args, "time_min")),
                time_max=str(_required(args, "time_max")),
                query=str(args.get("query") or ""),
                max_results=int(args.get("max_results", 100)),
                page_token=args.get("page_token"),
                show_deleted=bool(args.get("show_deleted", False)),
            )
        elif action == "read_event":
            result = {
                "event": await calendar.get_event(
                    owner,
                    connection_id,
                    calendar_id,
                    str(_required(args, "event_id")),
                )
            }
        elif action == "sync_events":
            result = await calendar.sync_events(
                owner,
                connection_id,
                calendar_id=calendar_id,
                sync_token=str(_required(args, "sync_token")),
                max_results=int(args.get("max_results", 2500)),
                page_token=args.get("page_token"),
            )
        elif action == "freebusy":
            result = await calendar.freebusy(
                owner,
                connection_id,
                calendar_ids=_calendar_ids(args, connection),
                time_min=str(_required(args, "time_min")),
                time_max=str(_required(args, "time_max")),
                timezone_name=str(args.get("timezone") or connection.get("timezone") or "UTC"),
            )
        elif action == "detect_conflicts":
            result = await calendar.detect_conflicts(
                owner,
                connection_id,
                calendar_ids=_calendar_ids(args, connection),
                start=_required(args, "start"),
                end=_required(args, "end"),
                timezone_name=str(args.get("timezone") or connection.get("timezone") or "UTC"),
                buffer_before_minutes=int(args.get("buffer_before_minutes", 0)),
                buffer_after_minutes=int(args.get("buffer_after_minutes", 0)),
            )
        elif action == "find_free_time":
            result = {
                "slots": await calendar.find_free_time(
                    owner,
                    connection_id,
                    calendar_ids=_calendar_ids(args, connection),
                    time_min=str(_required(args, "time_min")),
                    time_max=str(_required(args, "time_max")),
                    duration_minutes=int(_required(args, "duration_minutes")),
                    timezone_name=str(args.get("timezone") or connection.get("timezone") or "UTC"),
                    workday_start=str(args.get("workday_start") or "09:00"),
                    workday_end=str(args.get("workday_end") or "17:30"),
                    buffer_before_minutes=int(args.get("buffer_before_minutes", 0)),
                    buffer_after_minutes=int(args.get("buffer_after_minutes", 0)),
                    slot_step_minutes=int(args.get("slot_step_minutes", 30)),
                    limit=int(args.get("limit", 10)),
                )
            }
        else:
            raise ValueError("Unknown query_google_calendar action.")
        return _ok(result)
    except (GoogleConnectionError, CalendarValidationError, TypeError, ValueError) as exc:
        return _provider_error(exc)


async def _calendar_mutation(
    content: str,
    owner: Optional[str],
    *,
    tool_name: str,
    approval_action_id: Optional[str],
    request_id: str,
) -> dict[str, Any]:
    try:
        args = _arguments(content)
        _require_claimed_action(
            owner,
            tool_name,
            approval_action_id=approval_action_id,
            request_id=request_id,
        )
        connection_id, connection = _connection(owner, args)
        calendar = get_google_calendar_service()
        calendar_id = _calendar_id(args, connection)
        if tool_name == "create_google_calendar_hold":
            command = _event_command(args)
            command["status"] = "tentative"
            result = await calendar.create_event(
                owner,
                connection_id,
                calendar_id=calendar_id,
                send_updates="none",
                **command,
            )
        elif tool_name == "create_google_calendar_event":
            command = _event_command(args)
            command["status"] = "confirmed"
            result = await calendar.create_event(
                owner,
                connection_id,
                calendar_id=calendar_id,
                send_updates=str(
                    args.get("send_updates")
                    or ("all" if args.get("attendees") else "none")
                ),
                **command,
            )
        elif tool_name == "update_google_calendar_event":
            command = _event_command(args)
            result = await calendar.update_event(
                owner,
                connection_id,
                str(_required(args, "event_id")),
                calendar_id=calendar_id,
                send_updates=str(args.get("send_updates") or "all"),
                etag=args.get("etag"),
                **command,
            )
        elif tool_name == "respond_google_calendar_invitation":
            result = await calendar.respond_to_invitation(
                owner,
                connection_id,
                str(_required(args, "event_id")),
                calendar_id=calendar_id,
                response_status=str(_required(args, "response_status")),
                comment=str(args.get("comment") or ""),
            )
        elif tool_name == "update_google_calendar_attendees":
            result = await calendar.update_attendees(
                owner,
                connection_id,
                str(_required(args, "event_id")),
                calendar_id=calendar_id,
                add=args.get("add") or (),
                remove=args.get("remove") or (),
            )
        elif tool_name == "delete_google_calendar_event":
            result = await calendar.delete_event(
                owner,
                connection_id,
                str(_required(args, "event_id")),
                calendar_id=calendar_id,
                send_updates=str(args.get("send_updates") or "none"),
                etag=args.get("etag"),
            )
        else:  # pragma: no cover - wrappers pass compile-time constants
            raise ValueError("Unknown Calendar mutation tool.")
        return _ok(result)
    except (GoogleConnectionError, CalendarValidationError, TypeError, ValueError) as exc:
        return _provider_error(exc)


def _calendar_wrapper(tool_name: str):
    async def wrapper(
        content: str,
        owner: Optional[str] = None,
        *,
        approval_action_id: Optional[str] = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        return await _calendar_mutation(
            content,
            owner,
            tool_name=tool_name,
            approval_action_id=approval_action_id,
            request_id=request_id,
        )

    wrapper.__name__ = f"do_{tool_name}"
    return wrapper


do_create_google_calendar_hold = _calendar_wrapper("create_google_calendar_hold")
do_create_google_calendar_event = _calendar_wrapper("create_google_calendar_event")
do_update_google_calendar_event = _calendar_wrapper("update_google_calendar_event")
do_respond_google_calendar_invitation = _calendar_wrapper(
    "respond_google_calendar_invitation"
)
do_update_google_calendar_attendees = _calendar_wrapper(
    "update_google_calendar_attendees"
)
do_delete_google_calendar_event = _calendar_wrapper("delete_google_calendar_event")


__all__ = [
    "GOOGLE_WORKSPACE_TOOL_NAMES",
    "GOOGLE_WORKSPACE_TOOL_SCHEMAS",
    "do_query_gmail",
    "do_manage_gmail_draft",
    "do_send_gmail",
    "do_modify_gmail_message",
    "do_delete_gmail",
    "do_download_gmail_attachment",
    "do_query_google_calendar",
    "do_create_google_calendar_hold",
    "do_create_google_calendar_event",
    "do_update_google_calendar_event",
    "do_respond_google_calendar_invitation",
    "do_update_google_calendar_attendees",
    "do_delete_google_calendar_event",
]
