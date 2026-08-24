"""Approval-aware canonical handlers for meeting records and transcripts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from services.meeting_service import MeetingError, MeetingNotFound, get_meeting_service
from src.action_ledger import ActionLedgerError, get_action_ledger
from src.meeting_tool_contract import QUERY_MEETING_ACTIONS, TRANSCRIPT_MEETING_ACTIONS
from src.tools._common import _configured_auth_requires_owner, _parse_tool_args


_MUTATIONS = frozenset(
    {
        "create_meeting",
        "request_meeting_transcription",
        "approve_meeting_action_item",
        "save_meeting_knowledge",
        "delete_meeting",
    }
)


def _args(content: str) -> dict[str, Any]:
    value = _parse_tool_args(content)
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be an object")
    return value


def _error(exc: Exception) -> dict[str, Any]:
    return {
        "error": str(exc),
        "code": getattr(exc, "code", "invalid_arguments"),
        "exit_code": 1,
    }


def _parse_iso(value: Any) -> datetime:
    raw = str(value or "")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require_claimed_action(
    owner: Optional[str], tool_name: str, approval_action_id: Optional[str], request_id: str
) -> None:
    if tool_name not in _MUTATIONS or not approval_action_id or not request_id:
        raise ValueError("Meeting mutation requires an approved action-ledger claim")
    try:
        action = get_action_ledger().get_action(approval_action_id, owner)
    except ActionLedgerError as exc:
        raise ValueError("Meeting approval evidence is unavailable") from exc
    if (
        action.get("tool_name") != tool_name
        or action.get("status") != "executing"
        or not action.get("approval_consumed_at")
        or str(action.get("request_id") or "") != str(request_id)
        or _parse_iso(action.get("expires_at")) <= datetime.now(timezone.utc)
    ):
        raise ValueError("Meeting approval evidence is invalid, expired, or mismatched")


def _verification(record_id: str, expected: Mapping[str, Any], reader) -> dict[str, Any]:
    try:
        observed = reader()
        matches = all(observed.get(key) == value for key, value in expected.items())
        reason = None if matches else "Stored meeting state differs from the mutation result"
    except Exception as exc:
        matches = False
        reason = f"Could not read meeting state back: {type(exc).__name__}"
    value = {
        "status": "verified" if matches else "mismatch",
        "provider": "local_meetings",
        "read_back_id": record_id,
    }
    if reason:
        value["reason"] = reason
    return value


async def do_search_meetings(content: str, owner: Optional[str] = None) -> dict[str, Any]:
    if _configured_auth_requires_owner(owner):
        return {"error": "Authenticated owner is required", "code": "owner_required", "exit_code": 1}
    try:
        args = _args(content)
        action = str(args.get("action") or "").lower()
        if action not in QUERY_MEETING_ACTIONS:
            raise ValueError(f"Unknown meeting query action: {action}")
        service = get_meeting_service()
        if action == "list":
            result = service.list_meetings(owner, query=args.get("query", ""), status=args.get("status"), project_id=args.get("project_id"), calendar_event_id=args.get("calendar_event_id"), limit=args.get("limit", 100), offset=args.get("offset", 0))
        elif action == "get":
            result = {"meeting": service.get_meeting(owner, str(args.get("meeting_id") or ""), include_history=bool(args.get("include_history", False)))}
        elif action == "list_jobs":
            result = {"jobs": service.list_jobs(owner, meeting_id=args.get("meeting_id"), status=args.get("status"), limit=args.get("limit", 100))}
        elif action == "get_job":
            result = {"job": service.get_job(owner, str(args.get("job_id") or ""))}
        elif action == "transcript_revisions":
            result = {"revisions": service.transcript_revisions(owner, str(args.get("meeting_id") or ""), str(args.get("segment_id") or ""))}
        else:
            result = {"provider": service.provider_status()}
        return {**result, "exit_code": 0}
    except Exception as exc:
        return _error(exc)


async def do_create_meeting(content: str, owner: Optional[str] = None, *, approval_action_id: Optional[str] = None, request_id: str = "") -> dict[str, Any]:
    try:
        _require_claimed_action(owner, "create_meeting", approval_action_id, request_id)
        args = _args(content)
        meeting = get_meeting_service().create_meeting(owner, args.get("record") or {})
        return {"meeting": meeting, "verification": _verification(meeting["id"], meeting, lambda: get_meeting_service().get_meeting(owner, meeting["id"])), "exit_code": 0}
    except Exception as exc:
        return _error(exc)


async def do_request_meeting_transcription(content: str, owner: Optional[str] = None, *, approval_action_id: Optional[str] = None, request_id: str = "") -> dict[str, Any]:
    try:
        _require_claimed_action(owner, "request_meeting_transcription", approval_action_id, request_id)
        args = _args(content)
        action = str(args.get("action") or "").lower()
        if action not in TRANSCRIPT_MEETING_ACTIONS:
            raise ValueError(f"Unknown meeting transcript action: {action}")
        service = get_meeting_service()
        meeting_id = str(args.get("meeting_id") or "")
        if action == "enqueue_transcription":
            job = service.enqueue_transcription(owner, meeting_id, config=args.get("config"), idempotency_key=args.get("idempotency_key"), correlation_id=request_id, replace_edited=bool(args.get("replace_edited", False)))
            result, read_id, reader = {"job": job}, job["id"], lambda: service.get_job(owner, job["id"])
        elif action == "enqueue_analysis":
            job = service.enqueue_analysis(owner, meeting_id, idempotency_key=args.get("idempotency_key"), correlation_id=request_id)
            result, read_id, reader = {"job": job}, job["id"], lambda: service.get_job(owner, job["id"])
        elif action == "edit_segment":
            segment = service.edit_segment(owner, meeting_id, str(args.get("segment_id") or ""), args.get("record") or {}, expected_revision=int(args.get("revision") or 0))
            result, read_id, reader = {"segment": segment}, meeting_id, lambda: next(item for item in service.get_meeting(owner, meeting_id)["segments"] if item["id"] == segment["id"])
        elif action == "map_speaker":
            speaker = service.map_speaker(owner, meeting_id, str(args.get("label") or ""), display_name=str(args.get("display_name") or ""), attendee_id=args.get("attendee_id"), confidence=args.get("confidence"))
            result, read_id, reader = {"speaker": speaker}, meeting_id, lambda: next(item for item in service.get_meeting(owner, meeting_id)["speakers"] if item["id"] == speaker["id"])
        elif action == "cancel_job":
            job = service.cancel_job(owner, str(args.get("job_id") or "")); result, read_id, reader = {"job": job}, job["id"], lambda: service.get_job(owner, job["id"])
        elif action == "retry_job":
            job = service.retry_job(owner, str(args.get("job_id") or ""), idempotency_key=args.get("idempotency_key")); result, read_id, reader = {"job": job}, job["id"], lambda: service.get_job(owner, job["id"])
        elif action == "add_link":
            link = service.add_link(owner, meeting_id, args.get("record") or {}); result, read_id, reader = {"link": link}, meeting_id, lambda: next(item for item in service.get_meeting(owner, meeting_id)["links"] if item["id"] == link["id"])
        else:
            meeting = service.update_retention(owner, meeting_id, audio_days=args.get("audio_days"), transcript_days=args.get("transcript_days")); result, read_id, reader = {"meeting": meeting}, meeting_id, lambda: service.get_meeting(owner, meeting_id)
        expected = next(value for key, value in result.items() if key in {"job", "segment", "speaker", "link", "meeting"})
        return {**result, "verification": _verification(read_id, expected, reader), "exit_code": 0}
    except Exception as exc:
        return _error(exc)


async def do_approve_meeting_action_item(content: str, owner: Optional[str] = None, *, approval_action_id: Optional[str] = None, request_id: str = "") -> dict[str, Any]:
    try:
        _require_claimed_action(owner, "approve_meeting_action_item", approval_action_id, request_id)
        args = _args(content); service = get_meeting_service(); meeting_id = str(args.get("meeting_id") or "")
        claim = service.review_claim(owner, meeting_id, str(args.get("claim_id") or ""), decision=str(args.get("decision") or ""), confirm=True, edited_text=args.get("edited_text"), expected_revision=args.get("revision"))
        return {"claim": claim, "verification": _verification(claim["id"], claim, lambda: next(item for item in service.get_meeting(owner, meeting_id)["claims"] if item["id"] == claim["id"])), "exit_code": 0}
    except Exception as exc:
        return _error(exc)


async def do_save_meeting_knowledge(content: str, owner: Optional[str] = None, *, approval_action_id: Optional[str] = None, request_id: str = "") -> dict[str, Any]:
    try:
        _require_claimed_action(owner, "save_meeting_knowledge", approval_action_id, request_id)
        args = _args(content); meeting_id = str(args.get("meeting_id") or ""); result = get_meeting_service().save_to_knowledge(owner, meeting_id, confirm=True)
        link = result["link"]
        return {**result, "verification": _verification(link["id"], link, lambda: next(item for item in get_meeting_service().get_meeting(owner, meeting_id)["links"] if item["id"] == link["id"])), "exit_code": 0}
    except Exception as exc:
        return _error(exc)


async def do_delete_meeting(content: str, owner: Optional[str] = None, *, approval_action_id: Optional[str] = None, request_id: str = "") -> dict[str, Any]:
    try:
        _require_claimed_action(owner, "delete_meeting", approval_action_id, request_id)
        args = _args(content); meeting_id = str(args.get("meeting_id") or ""); result = get_meeting_service().delete_meeting(owner, meeting_id, confirm=True, purge_record=bool(args.get("purge_record", False)))
        try:
            get_meeting_service().get_meeting(owner, meeting_id); matches = False
        except MeetingNotFound:
            matches = True
        return {**result, "verification": {"status": "verified" if matches else "mismatch", "provider": "local_meetings", "read_back_id": meeting_id, "read_back": "not_found" if matches else "still_present"}, "exit_code": 0}
    except Exception as exc:
        return _error(exc)
