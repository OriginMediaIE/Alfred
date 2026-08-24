"""Dependency-light schemas for the canonical meeting agent tools."""

from __future__ import annotations


QUERY_MEETING_ACTIONS = frozenset(
    {"list", "get", "list_jobs", "get_job", "transcript_revisions", "provider_status"}
)
TRANSCRIPT_MEETING_ACTIONS = frozenset(
    {
        "enqueue_transcription",
        "enqueue_analysis",
        "edit_segment",
        "map_speaker",
        "cancel_job",
        "retry_job",
        "add_link",
        "update_retention",
    }
)


def _schema(name: str, description: str, properties: dict, required: list[str]):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


SEARCH_MEETINGS_TOOL_SCHEMA = _schema(
    "search_meetings",
    "Read owner-scoped meetings, source-linked transcript evidence, claims, jobs, revisions, or local transcription provider status.",
    {
        "action": {"type": "string", "enum": sorted(QUERY_MEETING_ACTIONS)},
        "meeting_id": {"type": "string"},
        "job_id": {"type": "string"},
        "segment_id": {"type": "string"},
        "query": {"type": "string", "maxLength": 500},
        "status": {"type": "string"},
        "project_id": {"type": "string"},
        "calendar_event_id": {"type": "string"},
        "include_history": {"type": "boolean"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000},
    },
    ["action"],
)

CREATE_MEETING_TOOL_SCHEMA = _schema(
    "create_meeting",
    "Create an editable local meeting record from manual details or a known calendar event. This does not record audio or claim realtime transcription.",
    {
        "record": {"type": "object", "additionalProperties": True},
    },
    ["record"],
)

REQUEST_MEETING_TRANSCRIPTION_TOOL_SCHEMA = _schema(
    "request_meeting_transcription",
    "Queue local transcription/analysis, edit a transcript segment, map a speaker, manage a job, add a source link, or update retention. Binary upload and microphone capture remain user UI actions.",
    {
        "action": {"type": "string", "enum": sorted(TRANSCRIPT_MEETING_ACTIONS)},
        "meeting_id": {"type": "string"},
        "job_id": {"type": "string"},
        "segment_id": {"type": "string"},
        "revision": {"type": "integer", "minimum": 1},
        "record": {"type": "object", "additionalProperties": True},
        "config": {"type": "object", "additionalProperties": True},
        "idempotency_key": {"type": "string", "maxLength": 200},
        "replace_edited": {"type": "boolean"},
        "label": {"type": "string"},
        "display_name": {"type": "string"},
        "attendee_id": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "audio_days": {"type": ["integer", "null"], "minimum": 0, "maximum": 3650},
        "transcript_days": {"type": ["integer", "null"], "minimum": 0, "maximum": 3650},
    },
    ["action"],
)

APPROVE_MEETING_ACTION_ITEM_TOOL_SCHEMA = _schema(
    "approve_meeting_action_item",
    "Approve, confirm, or reject one exact source-linked meeting claim. Approved action items create one idempotent personal task; inferred decisions become confirmed facts only after this action.",
    {
        "meeting_id": {"type": "string"},
        "claim_id": {"type": "string"},
        "decision": {"type": "string", "enum": ["approve", "confirm", "reject"]},
        "edited_text": {"type": "string", "maxLength": 20000},
        "revision": {"type": "integer", "minimum": 1},
    },
    ["meeting_id", "claim_id", "decision"],
)

SAVE_MEETING_KNOWLEDGE_TOOL_SCHEMA = _schema(
    "save_meeting_knowledge",
    "Explicitly save one active meeting transcript to the private knowledge index with segment timestamps, speaker labels, trust classification, and durable idempotency.",
    {"meeting_id": {"type": "string"}},
    ["meeting_id"],
)

DELETE_MEETING_TOOL_SCHEMA = _schema(
    "delete_meeting",
    "Delete one exact meeting, its transcript, jobs, links, and retained media after destructive-action approval.",
    {
        "meeting_id": {"type": "string"},
        "purge_record": {"type": "boolean"},
    },
    ["meeting_id"],
)

MEETING_TOOL_SCHEMAS = (
    SEARCH_MEETINGS_TOOL_SCHEMA,
    CREATE_MEETING_TOOL_SCHEMA,
    REQUEST_MEETING_TRANSCRIPTION_TOOL_SCHEMA,
    APPROVE_MEETING_ACTION_ITEM_TOOL_SCHEMA,
    SAVE_MEETING_KNOWLEDGE_TOOL_SCHEMA,
    DELETE_MEETING_TOOL_SCHEMA,
)
MEETING_TOOL_NAMES = frozenset(item["function"]["name"] for item in MEETING_TOOL_SCHEMAS)
