"""Dependency-light native tool schemas for Google Workspace operations."""

from __future__ import annotations


def _schema(name: str, description: str, properties: dict, required=("action",)):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


_CONNECTION = {
    "connection_id": {
        "type": "string",
        "description": "Connected Google account ID; omit only when exactly one account is connected.",
    }
}

_COMPOSE = {
    "to": {"type": ["string", "array"], "items": {"type": "string"}},
    "subject": {"type": "string"},
    "body": {"type": "string"},
    "body_html": {"type": "string"},
    "cc": {"type": ["string", "array"], "items": {"type": "string"}},
    "bcc": {"type": ["string", "array"], "items": {"type": "string"}},
}

_EVENT = {
    "calendar_id": {"type": "string"},
    "title": {"type": "string"},
    "start": {"type": "object", "additionalProperties": True},
    "end": {"type": "object", "additionalProperties": True},
    "description": {"type": "string"},
    "location": {"type": "string"},
    "visibility": {
        "type": "string",
        "enum": ["default", "public", "private", "confidential"],
    },
    "transparency": {"type": "string", "enum": ["opaque", "transparent"]},
    "color_id": {"type": "string"},
    "attendees": {"type": "array", "items": {}},
    "recurrence": {"type": "array", "items": {"type": "string"}},
    "reminders": {"type": "object", "additionalProperties": True},
    "create_video_call": {"type": "boolean"},
    "send_updates": {
        "type": "string",
        "enum": ["all", "externalOnly", "none"],
    },
}


GOOGLE_WORKSPACE_TOOL_SCHEMAS = (
    _schema(
        "query_gmail",
        "Read a connected Gmail account: labels, search results, messages, threads, drafts, or attachment metadata. Never sends or changes mail.",
        {
            **_CONNECTION,
            "action": {
                "type": "string",
                "enum": [
                    "list_labels",
                    "search_messages",
                    "read_message",
                    "read_thread",
                    "list_attachments",
                    "list_drafts",
                    "read_draft",
                ],
            },
            "query": {"type": "string"},
            "label_ids": {"type": "array", "items": {"type": "string"}},
            "message_id": {"type": "string"},
            "thread_id": {"type": "string"},
            "draft_id": {"type": "string"},
            "max_results": {"type": "integer"},
            "page_token": {"type": "string"},
            "include_metadata": {"type": "boolean"},
        },
    ),
    _schema(
        "manage_gmail_draft",
        "Create or update a reviewable Gmail draft. This never sends the draft.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["create", "update"]},
            "draft_id": {"type": "string"},
            **_COMPOSE,
        },
    ),
    _schema(
        "send_gmail",
        "Send a Gmail draft, new message, reply/reply-all, or forward after approval.",
        {
            **_CONNECTION,
            "action": {
                "type": "string",
                "enum": ["send_draft", "send_message", "reply", "reply_all", "forward"],
            },
            "draft_id": {"type": "string"},
            "message_id": {"type": "string"},
            "note": {"type": "string"},
            **_COMPOSE,
        },
    ),
    _schema(
        "modify_gmail_message",
        "Apply or remove labels, archive, mark read/unread, or star/unstar one Gmail message.",
        {
            **_CONNECTION,
            "action": {
                "type": "string",
                "enum": ["labels", "archive", "mark_read", "mark_unread", "star", "unstar"],
            },
            "message_id": {"type": "string"},
            "add": {"type": "array", "items": {"type": "string"}},
            "remove": {"type": "array", "items": {"type": "string"}},
        },
    ),
    _schema(
        "delete_gmail",
        "Move one Gmail message to trash or permanently delete one draft. Always requires explicit approval.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["trash_message", "delete_draft"]},
            "message_id": {"type": "string"},
            "draft_id": {"type": "string"},
        },
    ),
    _schema(
        "download_gmail_attachment",
        "Download one Gmail attachment to an explicitly approved, workspace-confined path and verify the saved bytes.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["download"]},
            "message_id": {"type": "string"},
            "attachment_id": {"type": "string"},
            "path": {"type": "string"},
        },
        required=("action", "message_id", "attachment_id", "path"),
    ),
    _schema(
        "query_google_calendar",
        "Read Google Calendar data, sync changes, inspect conflicts, free/busy data, or find free time. Never changes events.",
        {
            **_CONNECTION,
            "action": {
                "type": "string",
                "enum": [
                    "list_calendars",
                    "list_events",
                    "read_event",
                    "sync_events",
                    "freebusy",
                    "detect_conflicts",
                    "find_free_time",
                ],
            },
            "calendar_id": {"type": "string"},
            "calendar_ids": {"type": "array", "items": {"type": "string"}},
            "event_id": {"type": "string"},
            "time_min": {"type": "string"},
            "time_max": {"type": "string"},
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
            "page_token": {"type": "string"},
            "sync_token": {"type": "string"},
            "show_deleted": {"type": "boolean"},
            "timezone": {"type": "string"},
            "start": {"type": "object", "additionalProperties": True},
            "end": {"type": "object", "additionalProperties": True},
            "duration_minutes": {"type": "integer"},
            "workday_start": {"type": "string"},
            "workday_end": {"type": "string"},
            "buffer_before_minutes": {"type": "integer"},
            "buffer_after_minutes": {"type": "integer"},
            "slot_step_minutes": {"type": "integer"},
            "limit": {"type": "integer"},
        },
    ),
    _schema(
        "create_google_calendar_hold",
        "Create a tentative Google Calendar hold without attendees, recurrence, notifications, or a video call.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["create_hold"]},
            "calendar_id": {"type": "string"},
            "title": {"type": "string"},
            "start": {"type": "object", "additionalProperties": True},
            "end": {"type": "object", "additionalProperties": True},
            "description": {"type": "string"},
            "location": {"type": "string"},
            "visibility": {"type": "string", "enum": ["default", "private"]},
            "transparency": {"type": "string", "enum": ["opaque", "transparent"]},
            "reminders": {"type": "object", "additionalProperties": True},
        },
        required=("action", "title", "start", "end"),
    ),
    _schema(
        "create_google_calendar_event",
        "Create a confirmed Google Calendar event, potentially inviting attendees or creating recurrence/video conferencing.",
        {**_CONNECTION, "action": {"type": "string", "enum": ["create_event"]}, **_EVENT},
        required=("action", "title", "start", "end"),
    ),
    _schema(
        "update_google_calendar_event",
        "Modify an existing Google Calendar event after approval and verify it by reading it back.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["update_event"]},
            "event_id": {"type": "string"},
            "etag": {"type": "string"},
            **_EVENT,
        },
        required=("action", "event_id", "title", "start", "end"),
    ),
    _schema(
        "respond_google_calendar_invitation",
        "Accept, decline, or tentatively respond to one Google Calendar invitation.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["respond"]},
            "calendar_id": {"type": "string"},
            "event_id": {"type": "string"},
            "response_status": {
                "type": "string",
                "enum": ["accepted", "declined", "tentative", "needsAction"],
            },
            "comment": {"type": "string"},
        },
        required=("action", "event_id", "response_status"),
    ),
    _schema(
        "update_google_calendar_attendees",
        "Invite or remove attendees on an existing Google Calendar event.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["update_attendees"]},
            "calendar_id": {"type": "string"},
            "event_id": {"type": "string"},
            "add": {"type": "array", "items": {}},
            "remove": {"type": "array", "items": {"type": "string"}},
        },
        required=("action", "event_id"),
    ),
    _schema(
        "delete_google_calendar_event",
        "Delete one Google Calendar event after explicit approval and verify it no longer exists.",
        {
            **_CONNECTION,
            "action": {"type": "string", "enum": ["delete_event"]},
            "calendar_id": {"type": "string"},
            "event_id": {"type": "string"},
            "etag": {"type": "string"},
            "send_updates": {
                "type": "string",
                "enum": ["all", "externalOnly", "none"],
            },
        },
        required=("action", "event_id"),
    ),
)


GOOGLE_WORKSPACE_TOOL_NAMES = frozenset(
    schema["function"]["name"] for schema in GOOGLE_WORKSPACE_TOOL_SCHEMAS
)


__all__ = ["GOOGLE_WORKSPACE_TOOL_NAMES", "GOOGLE_WORKSPACE_TOOL_SCHEMAS"]
